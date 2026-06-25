"""
execution/entry_engine.py — Options order placement via TastyTrade SDK.

Order types:
  - Single-leg (ORB, SweepReversal): market order via Account.place_order()
  - Multi-leg butterfly: limit at MID, retry once with 1-tick improvement
    if not filled within LIMIT_RETRY_SECONDS. Never pay worse than mid.

Paper mode: simulates fill at mark + slippage, no real order sent.
"""

import logging
import time
import uuid
from decimal import Decimal
from typing import Optional, Tuple

from tastytrade.order import (
    NewOrder, Leg, OrderAction, OrderType, OrderTimeInForce,
    PriceEffect, InstrumentType
)

from strategy.base_strategy import OptionsSignal
from risk.setup_scorer import SetupScore
from risk.risk_manager import SizingResult
from database.trade_logger import TradeRecord, get_trade_logger
from data.tasty_client import get_session, get_account, TastyClientError
from config import (
    PAPER_TRADING, PAPER_FILL_SLIPPAGE_PCT,
    CONTRACT_MULTIPLIER, INSTRUMENT,
    LIMIT_RETRY_SECONDS, LIMIT_IMPROVE_TICKS
)
from utils.time_utils import ts_for_db, fmt_et_short

logger = logging.getLogger(__name__)


class EntryEngine:
    """Places orders for all strategy types and returns a populated TradeRecord."""

    def __init__(self, paper_trading: bool = PAPER_TRADING):
        self.paper_trading = paper_trading
        self._trade_logger = get_trade_logger()

    def enter(self,
              signal:  OptionsSignal,
              score:   SetupScore,
              sizing:  SizingResult) -> Optional[TradeRecord]:
        """
        Place entry order and record the trade.

        Returns TradeRecord on success, None on failure.
        """
        mode = "PAPER" if self.paper_trading else "LIVE"

        if signal.is_butterfly:
            logger.info(
                f"[{mode}] BUTTERFLY ENTRY: "
                f"{signal.butterfly_direction.upper()} "
                f"{sizing.contracts} × "
                f"{signal.lower_contract.strike}/"
                f"{signal.center_contract.strike}/"
                f"{signal.upper_contract.strike} "
                f"net_debit=${signal.net_debit:.2f} "
                f"grade={score.grade}"
            )
            fill_premium, order_id = self._place_butterfly(signal, sizing.contracts)
        else:
            logger.info(
                f"[{mode}] DIRECTIONAL ENTRY: "
                f"{signal.option_side.upper()} {signal.strike} "
                f"{sizing.contracts} contract(s) "
                f"mark=${signal.entry_premium:.2f} "
                f"grade={score.grade}"
            )
            fill_premium, order_id = self._place_single_leg(signal, sizing.contracts)

        if fill_premium is None:
            logger.error("Entry order failed — no fill")
            return None

        total_cost = fill_premium * sizing.contracts * CONTRACT_MULTIPLIER

        record = TradeRecord(
            trade_id          = str(uuid.uuid4()),
            symbol            = INSTRUMENT,
            strategy          = signal.strategy_name,
            setup_type        = signal.setup_type,
            setup_grade       = score.grade,
            setup_score       = score.score,
            direction         = signal.direction,
            option_side       = signal.option_side if not signal.is_butterfly else signal.butterfly_direction,
            is_butterfly      = signal.is_butterfly,
            strike            = signal.strike if not signal.is_butterfly else signal.center_contract.strike,
            expiry            = signal.expiry if not signal.is_butterfly else signal.center_contract.expiry,
            contracts         = sizing.contracts,
            entry_premium     = fill_premium,
            total_cost        = total_cost,
            max_loss          = total_cost,
            stop_premium      = signal.stop_premium(),
            trail_activation  = signal.trail_activation_premium(),
            target_premium    = signal.target_premium(),
            underlying_entry  = signal.underlying_entry,
            underlying_stop   = signal.underlying_stop,
            underlying_target = signal.underlying_target,
            regime            = signal.regime,
            vix_at_entry      = signal.vix_at_signal,
            is_fed_day        = signal.is_fed_day,
            order_id          = order_id,
            paper_trade       = 1 if self.paper_trading else 0,
            status            = "open",
            notes             = signal.notes,
        )

        if signal.is_butterfly:
            record.lower_strike  = signal.lower_contract.strike
            record.center_strike = signal.center_contract.strike
            record.upper_strike  = signal.upper_contract.strike
            record.net_debit     = signal.net_debit
            record.max_profit    = signal.max_profit

        self._trade_logger.log_entry(record)

        logger.info(
            f"✅ Entry confirmed [{mode}]: "
            f"ID={record.trade_id[:8]} "
            f"fill=${fill_premium:.2f}/share "
            f"total=${total_cost:.2f}"
        )
        return record

    # ─── Order Placement ──────────────────────────────────────────────────────

    def _place_single_leg(self, signal: OptionsSignal,
                           contracts: int) -> Tuple[Optional[float], str]:
        """Market order for directional single-leg trade."""
        if self.paper_trading:
            return self._paper_fill_single(signal)

        try:
            session  = get_session()
            account  = get_account()
            order_id = f"OT-{uuid.uuid4().hex[:8].upper()}"

            leg = Leg(
                instrument_type = InstrumentType.EQUITY_OPTION,
                symbol          = signal.contract.symbol,
                action          = OrderAction.BUY_TO_OPEN,
                quantity        = contracts,
            )

            order = NewOrder(
                time_in_force = OrderTimeInForce.DAY,
                order_type    = OrderType.MARKET,
                legs          = [leg],
            )

            response = account.place_order(session, order, dry_run=False)

            if response.errors:
                logger.error(f"Order errors: {response.errors}")
                return None, ""

            placed = response.order
            fill_price = float(placed.price or signal.entry_premium)
            live_id    = str(placed.id or order_id)

            logger.info(f"Single-leg market order placed: {live_id} fill=${fill_price:.2f}")
            return fill_price, live_id

        except Exception as e:
            logger.error(f"Single-leg order failed: {e}")
            return None, ""

    def _place_butterfly(self, signal: OptionsSignal,
                          contracts: int) -> Tuple[Optional[float], str]:
        """
        Limit order for butterfly at MID.
        Retries once with 1-tick improvement if not filled.
        """
        if self.paper_trading:
            return self._paper_fill_butterfly(signal)

        try:
            session  = get_session()
            account  = get_account()
            mid      = signal.net_debit
            order_id = f"OT-BF-{uuid.uuid4().hex[:8].upper()}"

            for attempt in range(2):
                limit_price = round(mid + attempt * LIMIT_IMPROVE_TICKS * 0.01, 2)
                logger.info(
                    f"Butterfly limit attempt {attempt+1}: "
                    f"mid=${mid:.2f} limit=${limit_price:.2f}"
                )

                legs = [
                    Leg(
                        instrument_type = InstrumentType.EQUITY_OPTION,
                        symbol          = signal.lower_contract.symbol,
                        action          = OrderAction.BUY_TO_OPEN,
                        quantity        = contracts,
                    ),
                    Leg(
                        instrument_type = InstrumentType.EQUITY_OPTION,
                        symbol          = signal.center_contract.symbol,
                        action          = OrderAction.SELL_TO_OPEN,
                        quantity        = contracts * 2,
                    ),
                    Leg(
                        instrument_type = InstrumentType.EQUITY_OPTION,
                        symbol          = signal.upper_contract.symbol,
                        action          = OrderAction.BUY_TO_OPEN,
                        quantity        = contracts,
                    ),
                ]

                order = NewOrder(
                    time_in_force = OrderTimeInForce.DAY,
                    order_type    = OrderType.LIMIT,
                    price         = Decimal(str(limit_price)),
                    price_effect  = PriceEffect.DEBIT,
                    legs          = legs,
                )

                response = account.place_order(session, order, dry_run=False)

                if response.errors:
                    logger.error(f"Butterfly order errors: {response.errors}")
                    if attempt == 1:
                        return None, ""
                    continue

                placed = response.order
                status = placed.status if placed else None
                live_id = str(placed.id or order_id)

                if status and "Filled" in str(status):
                    fill = float(placed.price or limit_price)
                    logger.info(f"Butterfly filled: {live_id} @ ${fill:.2f}")
                    return fill, live_id

                if attempt == 0:
                    logger.info(
                        f"Butterfly not filled at ${limit_price:.2f}, "
                        f"waiting {LIMIT_RETRY_SECONDS}s then improving"
                    )
                    time.sleep(LIMIT_RETRY_SECONDS)
                    # Cancel before retry
                    try:
                        account.delete_order(session, live_id)
                    except Exception:
                        pass
                else:
                    logger.warning("Butterfly not filled after 2 attempts — abandoning")
                    try:
                        account.delete_order(session, live_id)
                    except Exception:
                        pass
                    return None, ""

        except Exception as e:
            logger.error(f"Butterfly order failed: {e}")
            return None, ""

        return None, ""

    def _paper_fill_single(self, signal: OptionsSignal) -> Tuple[float, str]:
        slippage   = signal.entry_premium * PAPER_FILL_SLIPPAGE_PCT
        fill_price = signal.entry_premium + slippage
        order_id   = f"PAPER-{uuid.uuid4().hex[:8].upper()}"
        return fill_price, order_id

    def _paper_fill_butterfly(self, signal: OptionsSignal) -> Tuple[float, str]:
        slippage   = signal.net_debit * PAPER_FILL_SLIPPAGE_PCT
        fill_price = signal.net_debit + slippage
        order_id   = f"PAPER-BF-{uuid.uuid4().hex[:8].upper()}"
        return fill_price, order_id


# Singleton
_entry_engine: Optional[EntryEngine] = None


def get_entry_engine(paper_trading: bool = PAPER_TRADING) -> EntryEngine:
    global _entry_engine
    if _entry_engine is None:
        _entry_engine = EntryEngine(paper_trading)
    return _entry_engine
