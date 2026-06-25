"""
execution/exit_engine.py — All exit logic for options positions.

Exit triggers (checked every poll tick):
  1. HARD STOP: current premium ≤ stop_premium → market close
  2. TARGET HIT: premium at 100% TP (directional) or 25% max profit (butterfly)
  3. TRAIL ACTIVATED: at 50% TP → trailing stop set, locks in gains
  4. HARD CLOSE: 15:45 ET → market close regardless of P&L
  5. BUTTERFLY MAX HOLD: 2.5 hours → force exit
"""

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
from datetime import datetime

from tastytrade.order import (
    NewOrder, Leg, OrderAction, OrderType, OrderTimeInForce,
    PriceEffect, InstrumentType
)

from database.trade_logger import TradeRecord, get_trade_logger
from data.tasty_client import get_session, get_account, TastyClientError
from config import (
    PAPER_TRADING, CONTRACT_MULTIPLIER,
    BUTTERFLY_MAX_HOLD_MIN, TRAIL_LOCK_PCT
)
from utils.time_utils import is_hard_close_time, minutes_since, now_utc, fmt_et_short

logger = logging.getLogger(__name__)


@dataclass
class ExitDecision:
    should_exit:        bool  = False
    exit_reason:        str   = ""
    new_trail_stop:     Optional[float] = None
    current_pnl_pct:    float = 0.0
    current_pnl_usd:    float = 0.0


class ExitEngine:
    """Evaluates every open options trade on each tick."""

    def __init__(self, paper_trading: bool = PAPER_TRADING):
        self.paper_trading  = paper_trading
        self._trail_stops:  dict = {}
        self._trail_active: dict = {}
        self._trade_logger  = get_trade_logger()

    def evaluate(self,
                 record: TradeRecord,
                 current_premium: float) -> ExitDecision:
        """Full exit evaluation for one open trade."""
        decision     = ExitDecision()
        trade_id     = record["trade_id"]
        entry_prem   = record["entry_premium"]
        stop_prem    = record["stop_premium"]
        trail_prem   = record["trail_activation"]
        target_prem  = record["target_premium"]
        entry_time   = record["entry_time"]
        is_butterfly = bool(record.get("is_butterfly", False))

        pnl_pct = (current_premium - entry_prem) / entry_prem if entry_prem > 0 else 0
        pnl_usd = (current_premium - entry_prem) * record["contracts"] * CONTRACT_MULTIPLIER
        decision.current_pnl_pct = pnl_pct
        decision.current_pnl_usd = pnl_usd

        # 1. HARD CLOSE TIME
        if is_hard_close_time():
            decision.should_exit = True
            decision.exit_reason = "hard_close_15:45_ET"
            return decision

        # 2. BUTTERFLY MAX HOLD
        if is_butterfly and entry_time:
            try:
                from datetime import timezone
                entry_dt = datetime.fromisoformat(entry_time)
                if entry_dt.tzinfo is None:
                    entry_dt = entry_dt.replace(tzinfo=timezone.utc)
                mins_held = minutes_since(entry_dt)
                if mins_held >= BUTTERFLY_MAX_HOLD_MIN:
                    decision.should_exit = True
                    decision.exit_reason = f"butterfly_max_hold({mins_held:.0f}min)"
                    return decision
            except Exception:
                pass

        # 3. HARD STOP
        if current_premium <= stop_prem:
            decision.should_exit = True
            decision.exit_reason = f"stop_hit pnl={pnl_pct:.1%}"
            logger.info(
                f"STOP HIT: {trade_id[:8]} "
                f"current=${current_premium:.2f} ≤ stop=${stop_prem:.2f}"
            )
            return decision

        # 4. TARGET HIT
        if current_premium >= target_prem:
            decision.should_exit = True
            decision.exit_reason = f"target_hit pnl={pnl_pct:.1%}"
            logger.info(
                f"TARGET HIT: {trade_id[:8]} "
                f"current=${current_premium:.2f} ≥ target=${target_prem:.2f}"
            )
            return decision

        # 5. TRAILING STOP (directional only)
        if not is_butterfly:
            trail_stop = self._update_trail(
                trade_id, current_premium, entry_prem, trail_prem, stop_prem
            )
            if trail_stop is not None:
                if current_premium <= trail_stop:
                    decision.should_exit = True
                    decision.exit_reason = (
                        f"trail_stop_hit pnl={pnl_pct:.1%} "
                        f"trail=${trail_stop:.2f}"
                    )
                    return decision
                else:
                    decision.new_trail_stop = trail_stop

        return decision

    def _update_trail(self, trade_id: str,
                       current: float, entry: float,
                       trail_activation: float,
                       hard_stop: float) -> Optional[float]:
        if current < trail_activation:
            return None

        if not self._trail_active.get(trade_id, False):
            self._trail_active[trade_id] = True
            initial_trail = entry * (1 + TRAIL_LOCK_PCT)
            self._trail_stops[trade_id] = initial_trail
            logger.info(
                f"TRAIL ACTIVATED: {trade_id[:8]} "
                f"initial_trail=${initial_trail:.2f}"
            )

        current_trail = self._trail_stops.get(trade_id, hard_stop)
        new_trail     = current * 0.75
        if new_trail > current_trail:
            self._trail_stops[trade_id] = new_trail

        return self._trail_stops[trade_id]

    def place_exit_order(self, record: TradeRecord, reason: str) -> bool:
        """Place closing order. Paper mode simulates. Live mode uses SDK."""
        mode         = "PAPER" if self.paper_trading else "LIVE"
        trade_id     = record["trade_id"]
        contracts    = record["contracts"]
        is_butterfly = bool(record.get("is_butterfly", False))

        logger.info(
            f"[{mode}] CLOSING {trade_id[:8]}: {reason} "
            f"contracts={contracts}"
        )

        if self.paper_trading:
            logger.info(f"[PAPER] Simulated close: {trade_id[:8]}")
            return True

        try:
            session = get_session()
            account = get_account()

            if is_butterfly:
                return self._close_butterfly(session, account, record, contracts)
            else:
                return self._close_single_leg(session, account, record, contracts)

        except Exception as e:
            logger.error(f"Exit order failed for {trade_id[:8]}: {e}")
            return False

    def _close_single_leg(self, session, account, record: TradeRecord,
                           contracts: int) -> bool:
        """Market order to close a single-leg options position."""
        symbol = record.get("option_symbol", "")
        if not symbol:
            # Try to reconstruct from record fields
            logger.error("Cannot close: no option_symbol in record")
            return False

        leg = Leg(
            instrument_type = InstrumentType.EQUITY_OPTION,
            symbol          = symbol,
            action          = OrderAction.SELL_TO_CLOSE,
            quantity        = contracts,
        )

        order = NewOrder(
            time_in_force = OrderTimeInForce.DAY,
            order_type    = OrderType.MARKET,
            legs          = [leg],
        )

        response = account.place_order(session, order, dry_run=False)
        if response.errors:
            logger.error(f"Close order errors: {response.errors}")
            return False

        logger.info(f"Single-leg close placed: {record['trade_id'][:8]}")
        return True

    def _close_butterfly(self, session, account, record: TradeRecord,
                          contracts: int) -> bool:
        """Market order to close all three butterfly legs."""
        lower_sym  = record.get("lower_symbol", "")
        center_sym = record.get("center_symbol", "")
        upper_sym  = record.get("upper_symbol", "")

        if not all([lower_sym, center_sym, upper_sym]):
            logger.error("Cannot close butterfly: missing leg symbols")
            return False

        legs = [
            Leg(instrument_type=InstrumentType.EQUITY_OPTION,
                symbol=lower_sym,  action=OrderAction.SELL_TO_CLOSE, quantity=contracts),
            Leg(instrument_type=InstrumentType.EQUITY_OPTION,
                symbol=center_sym, action=OrderAction.BUY_TO_CLOSE,  quantity=contracts * 2),
            Leg(instrument_type=InstrumentType.EQUITY_OPTION,
                symbol=upper_sym,  action=OrderAction.SELL_TO_CLOSE, quantity=contracts),
        ]

        order = NewOrder(
            time_in_force = OrderTimeInForce.DAY,
            order_type    = OrderType.MARKET,
            legs          = legs,
        )

        response = account.place_order(session, order, dry_run=False)
        if response.errors:
            logger.error(f"Butterfly close errors: {response.errors}")
            return False

        logger.info(f"Butterfly close placed: {record['trade_id'][:8]}")
        return True

    def clear_trail(self, trade_id: str):
        self._trail_stops.pop(trade_id, None)
        self._trail_active.pop(trade_id, None)


# Singleton
_exit_engine: Optional[ExitEngine] = None


def get_exit_engine(paper_trading: bool = PAPER_TRADING) -> ExitEngine:
    global _exit_engine
    if _exit_engine is None:
        _exit_engine = ExitEngine(paper_trading)
    return _exit_engine
