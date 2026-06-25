"""
risk/session_guard.py — Session boundary enforcement.
Manages: RTH gate, 3:45 ET hard close, entry cutoffs, Fed day flag.

Entry cutoffs:
  - Standard strategies (ORB, SweepReversal): 2:00 PM ET
  - Butterfly: 3:30 PM ET (short hold, 25% TP, late-day theta play)
"""

import logging
from typing import Optional
from datetime import datetime, time as dtime

from utils.time_utils import (
    is_rth, is_hard_close_time, is_past_entry_cutoff,
    now_et, fmt_et_short, seconds_until_rth_open
)
from data.macro_data import MacroSnapshot

logger = logging.getLogger(__name__)

BUTTERFLY_CUTOFF_ET = dtime(15, 30)   # Butterfly entries allowed until 3:30 PM ET


class SessionGuard:
    """
    Gate keeper for all session-level rules.
    Called at the start of each attempt_new_entry() loop.
    """

    def can_enter(self, macro: Optional[MacroSnapshot] = None,
                  is_butterfly: bool = False) -> tuple:
        """
        Check all pre-entry gates.

        Args:
            macro:        Current macro snapshot
            is_butterfly: True for butterfly — allowed until 3:30 ET

        Returns:
            (allowed: bool, reason: str)
        """
        # ── RTH gate ─────────────────────────────────────────────────────────
        if not is_rth():
            return False, f"outside RTH ({fmt_et_short()})"

        # ── Hard close approaching ────────────────────────────────────────────
        if is_hard_close_time():
            return False, "past 15:45 ET hard close — no new entries"

        # ── Entry cutoff ──────────────────────────────────────────────────────
        if is_past_entry_cutoff():
            if not is_butterfly:
                return False, "past 14:00 ET entry cutoff — no new 0DTE entries"
            # Butterfly exception: allowed until 3:30 ET
            if now_et().time() >= BUTTERFLY_CUTOFF_ET:
                return False, "past 15:30 ET butterfly cutoff"

        # ── Macro gates ───────────────────────────────────────────────────────
        if macro and not macro.new_entries_allowed:
            return False, f"VIX crisis ({macro.vix:.1f}) — no new entries"

        return True, ""

    def must_close_all(self) -> bool:
        """True when all open positions must be closed (15:45 ET)."""
        return is_hard_close_time()

    def seconds_to_open(self) -> float:
        return seconds_until_rth_open()

    def log_session_state(self, macro: Optional[MacroSnapshot] = None):
        """Log current session status for heartbeat."""
        allowed, reason = self.can_enter(macro)
        logger.info(
            f"Session [{fmt_et_short()}]: "
            f"rth={is_rth()} "
            f"entry={'OK' if allowed else 'BLOCKED: ' + reason} "
            f"hard_close={is_hard_close_time()} "
            f"vix={macro.vix:.1f if macro else 'N/A'} "
            f"fed_day={macro.is_fed_day if macro else False}"
        )


_session_guard: Optional[SessionGuard] = None


def get_session_guard() -> SessionGuard:
    global _session_guard
    if _session_guard is None:
        _session_guard = SessionGuard()
    return _session_guard
