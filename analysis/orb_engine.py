"""
analysis/orb_engine.py — Opening Range Breakout state machine.

ORB rules (exact):
  - Range defined by 9:30–9:35 ET candle (first 5-min candle) high and low
  - BREAK: 1-min candle CLOSE outside the ORB (not just a wick)
  - RETEST: a subsequent 1-min candle WICKS INTO the ORB but the BODY closes outside
  - CONFIRMED: break + retest both satisfied = valid ORB entry signal
  - Stop: 1-min close beyond the BODY of the breakout candle (not the wick)
  - TP100: ORB width projected from the break level
  - TP50 (trail activation): 50% of TP100
  - No entries after 14:00 ET
"""

import logging
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime
import pandas as pd

from utils.time_utils import now_et, is_orb_complete, is_past_entry_cutoff, ET
from utils.math_utils import orb_width, orb_breakout_target, orb_strike_selection
from config import (
    ORB_BREAK_BUFFER, ORB_MAX_RETEST_BARS, STRIKE_INCREMENT, INSTRUMENT
)

logger = logging.getLogger(__name__)


class ORBState:
    WAITING         = "WAITING"          # Pre-9:35, building range
    RANGE_SET       = "RANGE_SET"        # ORB defined, watching for break
    BREAK_LONG      = "BREAK_LONG"       # 1m close above ORB high — watching for retest
    BREAK_SHORT     = "BREAK_SHORT"      # 1m close below ORB low — watching for retest
    CONFIRMED_LONG  = "CONFIRMED_LONG"   # Break + retest confirmed — FIRE
    CONFIRMED_SHORT = "CONFIRMED_SHORT"  # Break + retest confirmed — FIRE
    INVALIDATED     = "INVALIDATED"      # Break failed (closed back inside range)
    TRIGGERED       = "TRIGGERED"        # Signal generated — done for session
    EXPIRED         = "EXPIRED"          # Past 14:00 ET — no more ORB entries


@dataclass
class ORBData:
    """ORB state for the current session."""
    state:              str   = ORBState.WAITING
    orb_high:           float = 0.0
    orb_low:            float = 0.0
    orb_width:          float = 0.0
    break_candle_high:  float = 0.0     # Body of the break candle (not wick)
    break_candle_low:   float = 0.0
    break_candle_close: float = 0.0
    break_direction:    str   = ""       # "long" or "short"
    bars_since_break:   int   = 0
    target_100pct:      float = 0.0
    target_50pct:       float = 0.0
    stop_level:         float = 0.0     # 1m close beyond break candle body
    target_strike:      int   = 0       # ORB-projected strike for option selection
    confirmed_at:       str   = ""


class ORBEngine:
    """
    State machine that tracks the ORB through the session.
    Call update() on every new 1-min and 5-min candle.
    Returns ORBData with the current state.
    """

    def __init__(self):
        self._data = ORBData()

    @property
    def data(self) -> ORBData:
        return self._data

    def reset_for_session(self):
        """Call at start of each RTH session to clear yesterday's state."""
        self._data = ORBData()
        logger.info("ORB engine reset for new session")

    def update(self, df_5m: pd.DataFrame, df_1m: pd.DataFrame,
               current_price: float) -> ORBData:
        """
        Process the latest candle data and advance the ORB state machine.

        Args:
            df_5m:          5-min candles (need the 9:30 candle for ORB range)
            df_1m:          1-min candles (break and retest confirmation)
            current_price:  Current underlying price

        Returns:
            Updated ORBData
        """
        d = self._data

        # If already triggered or expired — nothing to do
        if d.state in (ORBState.TRIGGERED, ORBState.EXPIRED):
            return d

        # Past entry cutoff — expire
        if is_past_entry_cutoff() and d.state not in (
            ORBState.CONFIRMED_LONG, ORBState.CONFIRMED_SHORT
        ):
            d.state = ORBState.EXPIRED
            logger.info("ORB: past 14:00 ET entry cutoff — state EXPIRED")
            return d

        # Step 1: Set the ORB range
        if d.state == ORBState.WAITING and is_orb_complete():
            self._set_orb_range(df_5m)

        # Step 2: Watch for break
        if d.state == ORBState.RANGE_SET:
            self._check_for_break(df_1m)

        # Step 3: Watch for retest
        if d.state in (ORBState.BREAK_LONG, ORBState.BREAK_SHORT):
            self._check_for_retest(df_1m)

        return d

    def _set_orb_range(self, df_5m: pd.DataFrame):
        """Extract the ORB high/low from the 9:30–9:35 ET candle."""
        d = self._data
        if df_5m is None or df_5m.empty:
            return

        # Find the 9:30 ET candle
        orb_candle = self._get_orb_candle(df_5m)
        if orb_candle is None:
            logger.debug("ORB candle not found in 5m data yet")
            return

        d.orb_high  = float(orb_candle["high"])
        d.orb_low   = float(orb_candle["low"])
        d.orb_width = d.orb_high - d.orb_low
        d.state     = ORBState.RANGE_SET

        logger.info(
            f"ORB range set: high={d.orb_high:.2f} "
            f"low={d.orb_low:.2f} "
            f"width={d.orb_width:.2f}"
        )

    def _get_orb_candle(self, df_5m: pd.DataFrame) -> Optional[pd.Series]:
        """Return the 9:30 ET 5-min candle."""
        try:
            idx = df_5m.index
            # Look for candle at or nearest to 9:30 ET
            for i, ts in enumerate(idx):
                ts_et = ts if hasattr(ts, 'hour') else ts.astimezone(ET)
                if ts_et.hour == 9 and ts_et.minute == 30:
                    return df_5m.iloc[i]
            # Fallback: first candle of the day
            today_et = now_et().date()
            today_candles = [
                (i, ts) for i, ts in enumerate(idx)
                if ts.date() == today_et
            ]
            if today_candles:
                first_idx = today_candles[0][0]
                return df_5m.iloc[first_idx]
        except Exception as e:
            logger.debug(f"ORB candle lookup error: {e}")
        return None

    def _check_for_break(self, df_1m: pd.DataFrame):
        """
        Detect a valid ORB break: 1-min candle CLOSE outside the ORB.
        The break must be by at least ORB_BREAK_BUFFER to avoid noise.
        """
        d = self._data
        if df_1m is None or len(df_1m) < 2:
            return

        # Use second-to-last confirmed candle ([-2]) for closed candle
        candle = df_1m.iloc[-2]
        close  = float(candle["close"])
        open_  = float(candle["open"])
        high   = float(candle["high"])
        low    = float(candle["low"])

        buffer = d.orb_high * ORB_BREAK_BUFFER / 100

        # Upside break: close clearly above ORB high
        if close > d.orb_high + buffer:
            d.break_direction    = "long"
            d.break_candle_close = close
            d.break_candle_high  = max(open_, close)  # Body top
            d.break_candle_low   = min(open_, close)  # Body bottom
            d.bars_since_break   = 0
            d.target_100pct      = d.orb_high + d.orb_width
            d.target_50pct       = d.orb_high + d.orb_width * 0.5
            d.stop_level         = d.break_candle_low   # Below break candle body
            d.target_strike      = orb_strike_selection(
                d.orb_high, d.orb_low, "long", STRIKE_INCREMENT
            )
            d.state              = ORBState.BREAK_LONG
            logger.info(
                f"ORB BREAK LONG: close={close:.2f} above ORB_HIGH={d.orb_high:.2f} "
                f"target={d.target_100pct:.2f} stop_body={d.stop_level:.2f} "
                f"strike={d.target_strike}"
            )

        # Downside break: close clearly below ORB low
        elif close < d.orb_low - buffer:
            d.break_direction    = "short"
            d.break_candle_close = close
            d.break_candle_high  = max(open_, close)  # Body top
            d.break_candle_low   = min(open_, close)  # Body bottom
            d.bars_since_break   = 0
            d.target_100pct      = d.orb_low - d.orb_width
            d.target_50pct       = d.orb_low - d.orb_width * 0.5
            d.stop_level         = d.break_candle_high  # Above break candle body
            d.target_strike      = orb_strike_selection(
                d.orb_high, d.orb_low, "short", STRIKE_INCREMENT
            )
            d.state              = ORBState.BREAK_SHORT
            logger.info(
                f"ORB BREAK SHORT: close={close:.2f} below ORB_LOW={d.orb_low:.2f} "
                f"target={d.target_100pct:.2f} stop_body={d.stop_level:.2f} "
                f"strike={d.target_strike}"
            )

    def _check_for_retest(self, df_1m: pd.DataFrame):
        """
        Detect the retest after a break.

        RETEST condition:
          - A 1-min candle wicks INTO the ORB (wick crosses the ORB boundary)
          - But the candle BODY closes OUTSIDE the ORB (confirmed continuation)

        Also checks for break invalidation:
          - If a 1-min candle CLOSES back inside the ORB, the break is invalidated
          - If max retest bars exceeded without retest, invalidate
        """
        d = self._data
        if df_1m is None or len(df_1m) < 2:
            return

        d.bars_since_break += 1

        # Timeout — too many bars without retest
        if d.bars_since_break > ORB_MAX_RETEST_BARS:
            d.state = ORBState.INVALIDATED
            logger.info(
                f"ORB: retest timeout after {d.bars_since_break} bars — INVALIDATED"
            )
            return

        candle = df_1m.iloc[-2]
        close  = float(candle["close"])
        open_  = float(candle["open"])
        high   = float(candle["high"])
        low    = float(candle["low"])

        body_high = max(open_, close)
        body_low  = min(open_, close)

        if d.break_direction == "long":
            # Wick INTO the ORB: low wicks below ORB high
            wick_into_range = low < d.orb_high
            # Body stays outside: body_low >= ORB high (or very close)
            body_outside    = body_low >= d.orb_high * 0.999
            # Invalidation: close back inside ORB
            invalidated     = close < d.orb_high

            if wick_into_range and body_outside:
                d.state        = ORBState.CONFIRMED_LONG
                d.confirmed_at = str(now_et())
                logger.info(
                    f"✅ ORB CONFIRMED LONG: retest wick to {low:.2f} "
                    f"body_low={body_low:.2f} above ORB_HIGH={d.orb_high:.2f}"
                )
            elif invalidated:
                d.state = ORBState.INVALIDATED
                logger.info(
                    f"ORB INVALIDATED: close={close:.2f} back inside ORB "
                    f"(orb_high={d.orb_high:.2f})"
                )

        else:  # break_direction == "short"
            wick_into_range = high > d.orb_low
            body_outside    = body_high <= d.orb_low * 1.001
            invalidated     = close > d.orb_low

            if wick_into_range and body_outside:
                d.state        = ORBState.CONFIRMED_SHORT
                d.confirmed_at = str(now_et())
                logger.info(
                    f"✅ ORB CONFIRMED SHORT: retest wick to {high:.2f} "
                    f"body_high={body_high:.2f} below ORB_LOW={d.orb_low:.2f}"
                )
            elif invalidated:
                d.state = ORBState.INVALIDATED
                logger.info(
                    f"ORB INVALIDATED: close={close:.2f} back inside ORB "
                    f"(orb_low={d.orb_low:.2f})"
                )

    def mark_triggered(self):
        """Call after the signal is consumed to prevent re-firing."""
        self._data.state = ORBState.TRIGGERED
        logger.info("ORB: signal consumed — state TRIGGERED")

    @property
    def is_confirmed(self) -> bool:
        return self._data.state in (
            ORBState.CONFIRMED_LONG, ORBState.CONFIRMED_SHORT
        )

    @property
    def direction(self) -> str:
        d = self._data
        if d.state == ORBState.CONFIRMED_LONG:
            return "long"
        if d.state == ORBState.CONFIRMED_SHORT:
            return "short"
        return ""


# Singleton — one ORB engine per session
_orb_engine: Optional[ORBEngine] = None


def get_orb_engine() -> ORBEngine:
    global _orb_engine
    if _orb_engine is None:
        _orb_engine = ORBEngine()
    return _orb_engine
