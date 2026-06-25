"""
execution/position_manager.py — Manages the single open options position.
Fetches current option premium from TastyTrade on each tick.
Drives exit decisions via ExitEngine.
Updates TradeRecord on stop/trail adjustments.
"""

import logging
from typing import Optional

from database.trade_logger import TradeRecord, get_trade_logger
from execution.exit_engine import get_exit_engine, ExitDecision
from data.tasty_client import get_client, TastyClientError
from risk.risk_manager import get_risk_manager
from notifications.alert_manager import get_alert_manager
from config import PAPER_TRADING, PAPER_FILL_SLIPPAGE_PCT, CONTRACT_MULTIPLIER

logger = logging.getLogger(__name__)


class PositionManager:
    """
    Manages the bot's single open position (one trade at a time).
    Fetches live option premium, evaluates exits, and closes when triggered.
    """

    def __init__(self, paper_trading: bool = PAPER_TRADING):
        self.paper_trading = paper_trading
        self._open_record: Optional[TradeRecord] = None
        self._trade_logger = get_trade_logger()

    def has_open_position(self) -> bool:
        if self._open_record is not None:
            return True
        # Also check DB in case of restart
        record = self._trade_logger.get_open_trade()
        if record:
            self._open_record = record
            return True
        return False

    def set_open_position(self, record: TradeRecord):
        self._open_record = record

    def get_open_record(self) -> Optional[TradeRecord]:
        return self._open_record

    def manage_open_position(self) -> bool:
        """
        Evaluate the open position and take action if needed.

        Returns:
            True if position is still open after evaluation
            False if position was closed
        """
        if self._open_record is None:
            return False

        record   = self._open_record
        trade_id = record["trade_id"]

        # ── Fetch current option premium ──────────────────────────────────────
        current_premium = self._fetch_current_premium(record)
        if current_premium is None:
            logger.warning(
                f"Could not fetch premium for {trade_id[:8]} — skipping tick"
            )
            return True

        # ── Evaluate exit conditions ───────────────────────────────────────────
        exit_eng = get_exit_engine(self.paper_trading)
        decision = exit_eng.evaluate(record, current_premium)

        # ── Update trailing stop in DB if changed ────────────────────────────
        if decision.new_trail_stop is not None:
            self._trade_logger.update_stop(trade_id, decision.new_trail_stop)
            record["stop_premium"] = decision.new_trail_stop

        # ── Execute exit if triggered ─────────────────────────────────────────
        if decision.should_exit:
            return self._execute_exit(record, decision, current_premium)

        # Log P&L on periodic heartbeat (caller decides frequency)
        logger.debug(
            f"Position [{trade_id[:8]}]: "
            f"premium=${current_premium:.2f} "
            f"pnl={decision.current_pnl_pct:.1%} "
            f"(${decision.current_pnl_usd:+.2f})"
        )
        return True

    def _fetch_current_premium(self, record: TradeRecord) -> Optional[float]:
        """
        Fetch current mark price for the option(s).
        For butterfly: fetch all three legs and compute net value.
        Paper mode: use last known mark with slight drift simulation.
        """
        is_butterfly = bool(record.get("is_butterfly", False))

        if self.paper_trading:
            # Paper: return entry premium (no live data needed for simulation)
            # The exit conditions will still trigger based on underlying logic
            return record.get("entry_premium", 0.0)

        client = get_client()

        try:
            if is_butterfly:
                lower_sym  = record.get("lower_symbol",  "")
                center_sym = record.get("center_symbol", "")
                upper_sym  = record.get("upper_symbol",  "")

                lower_mark  = self._get_option_mark(client, lower_sym)
                center_mark = self._get_option_mark(client, center_sym)
                upper_mark  = self._get_option_mark(client, upper_sym)

                if None in (lower_mark, center_mark, upper_mark):
                    return None

                # Current net value = lower + upper - 2×center
                return lower_mark + upper_mark - 2 * center_mark

            else:
                symbol = record.get("option_symbol", "")
                return self._get_option_mark(client, symbol)

        except Exception as e:
            logger.error(f"Premium fetch error: {e}")
            return None

    def _get_option_mark(self, client, symbol: str) -> Optional[float]:
        """Get mid-market price for a single option."""
        if not symbol:
            return None
        try:
            data  = client.get(f"/market-data/quotes/{symbol}")
            quote = data.get("data", {})
            bid   = float(quote.get("bid", 0) or 0)
            ask   = float(quote.get("ask", 0) or 0)
            if bid > 0 and ask > 0:
                return (bid + ask) / 2
            return float(quote.get("mark", 0) or quote.get("last", 0) or 0) or None
        except Exception:
            return None

    def _execute_exit(self, record: TradeRecord,
                       decision: ExitDecision,
                       current_premium: float) -> bool:
        """Close the position and record the trade."""
        trade_id = record["trade_id"]

        exit_eng = get_exit_engine(self.paper_trading)
        success  = exit_eng.place_exit_order(record, decision.exit_reason)

        if not success:
            logger.error(f"Exit order failed for {trade_id[:8]} — will retry next tick")
            return True  # Keep position open; retry next tick

        # Calculate final P&L
        entry_prem   = record["entry_premium"]
        contracts    = record["contracts"]
        pnl_per_share = current_premium - entry_prem
        pnl_usd      = pnl_per_share * contracts * CONTRACT_MULTIPLIER

        # Log to DB
        self._trade_logger.log_exit(
            trade_id    = trade_id,
            exit_price  = current_premium,
            pnl_usd     = pnl_usd,
            exit_reason = decision.exit_reason,
        )

        # Update risk manager
        risk_mgr = get_risk_manager()
        if pnl_usd >= 0:
            risk_mgr.record_win()
        else:
            risk_mgr.record_loss()

        # SMS alert
        get_alert_manager().send_exit_alert(
            trade_id    = trade_id,
            setup_type  = record.get("setup_type", ""),
            exit_premium = current_premium,
            entry_premium = entry_prem,
            pnl_usd     = pnl_usd,
            contracts   = contracts,
            reason      = decision.exit_reason,
        )

        # Clean up
        exit_eng.clear_trail(trade_id)
        self._open_record = None

        logger.info(
            f"✅ Position closed: {trade_id[:8]} "
            f"exit=${current_premium:.2f} "
            f"pnl=${pnl_usd:+.2f} "
            f"reason={decision.exit_reason}"
        )
        return False


# Singleton
_position_manager: Optional[PositionManager] = None


def get_position_manager(paper_trading: bool = PAPER_TRADING) -> PositionManager:
    global _position_manager
    if _position_manager is None:
        _position_manager = PositionManager(paper_trading)
    return _position_manager
