"""
strategy/orb_strategy.py — ORB break-and-retest signal generation.

Liquidity-aware ORB logic (the most important upgrade):

The single biggest cause of ORB losses is trading a breakout that is actually
a liquidity grab — price runs stops above/below a named level, then reverses.
Three rules address this:

RULE 1 — Named level IS the break level (catalyst, not obstacle):
  If the ORB high/low sits within 0.15% of a named pool (PDH, PDL, session H/L),
  and the break direction is THROUGH that level, this is a high-quality setup.
  The sweep of that level IS the ORB catalyst. Add confluence, don't penalize.

RULE 2 — Named level in path between entry and 50% TP (hard reduce):
  A named pool sitting between entry and the trail-activation level is a known
  reversal zone. This is the fakeout scenario. Require at least one extra
  confluence factor beyond the base two, OR block if no extra confluence exists.
  Unnamed equal-highs/lows clusters in path: drop grade by one letter (size only).

RULE 3 — Named level just beyond 100% TP (adjust target, don't block):
  If a named pool sits within 0.5 ORB-widths past the 100% TP, move the target
  to that pool price rather than projecting past it. Take the gift.
  Log clearly so operator knows target was adjusted.
"""

import logging
from typing import Optional, List, Tuple

from strategy.base_strategy import BaseOptionsStrategy, OptionsSignal
from analysis.orb_engine import ORBData, ORBState
from analysis.regime_classifier import RegimeState, Regime
from analysis.volatility_engine import VolatilityState
from analysis.liquidity_mapper import LiquidityMap, LiquidityPool
from data.options_chain import OptionsChain
from data.options_chain import get_chain_fetcher
from data.macro_data import MacroSnapshot
from config import FED_DAY_ORB_BOOST, INSTRUMENT

logger = logging.getLogger(__name__)

# How close a named level must be to the ORB boundary to be considered
# the SAME level (Rule 1 — catalyst).  0.15% of price.
BREAK_LEVEL_PROXIMITY_PCT   = 0.0015

# Named level in path within this distance of entry triggers Rule 2 hard block.
# Measured as fraction of ORB width — levels within 1.5× width are dangerous.
NAMED_IN_PATH_ORB_WIDTHS    = 1.5

# Named level beyond TP within this many ORB widths → adjust target (Rule 3).
BEYOND_TP_ADJUSTMENT_WIDTHS = 0.5


class ORBStrategy(BaseOptionsStrategy):
    """
    Opening Range Breakout strategy.
    Liquidity-aware: distinguishes catalyst sweeps from obstacle sweeps.
    """

    @property
    def name(self) -> str:
        return "ORBStrategy"

    def generate_signal(self,
                         orb: ORBData,
                         regime: RegimeState,
                         vol_state: VolatilityState,
                         liq_map: LiquidityMap,
                         chain: OptionsChain,
                         macro: MacroSnapshot,
                         current_price: float) -> Optional[OptionsSignal]:

        if orb.state not in (ORBState.CONFIRMED_LONG, ORBState.CONFIRMED_SHORT):
            return None

        direction   = orb.break_direction
        option_side = "call" if direction == "long" else "put"
        break_level = orb.orb_high if direction == "long" else orb.orb_low

        # ── Liquidity analysis (must run BEFORE signal is built) ──────────────
        liq_result = self._analyze_liquidity(
            orb, liq_map, current_price, direction, break_level
        )

        # Rule 2 hard block: named level between entry and 50% TP, no extra confluence
        if liq_result["block"]:
            logger.info(
                f"ORB BLOCKED — named liquidity pool in path with no extra "
                f"confluence to support continuation: {liq_result['block_reason']}"
            )
            return None

        # Adjust target if Rule 3 fired
        target_100 = liq_result.get("adjusted_target", orb.target_100pct)
        target_50  = orb.orb_high + (target_100 - orb.orb_high) * 0.5 \
                     if direction == "long" \
                     else orb.orb_low - (orb.orb_low - target_100) * 0.5

        signal = OptionsSignal(
            strategy_name     = self.name,
            setup_type        = f"ORB {direction.title()}",
            direction         = direction,
            option_side       = option_side,
            underlying_entry  = current_price,
            underlying_stop   = orb.stop_level,
            underlying_target = target_100,
            underlying_tp50   = target_50,
            regime            = regime.primary_regime,
            vix_at_signal     = macro.vix,
            is_fed_day        = macro.is_fed_day,
            stop_loss_pct     = 0.25,
            tp_pct            = 1.0,
        )

        # ── Base confluence ───────────────────────────────────────────────────
        self._add_confluence(signal, f"ORB break confirmed ({direction})")
        self._add_confluence(signal, "Break+retest pattern (1m body/wick rules)")

        # ── Rule 1: break level IS a named level (highest quality) ───────────
        if liq_result["break_is_named_level"]:
            pool_name = liq_result["break_level_name"]
            self._add_confluence(
                signal,
                f"ORB break through named level {pool_name} — sweep catalyst"
            )
            signal.conviction += 0.15   # Meaningful boost — this is the best setup

        # ── VWAP alignment ────────────────────────────────────────────────────
        if direction == "long" and vol_state.price_vs_vwap == "ABOVE":
            self._add_confluence(signal, "Above VWAP — bullish bias")
        elif direction == "short" and vol_state.price_vs_vwap == "BELOW":
            self._add_confluence(signal, "Below VWAP — bearish bias")

        # ── Trend / regime alignment ──────────────────────────────────────────
        if (direction == "long"  and regime.primary_regime == Regime.TRENDING_BULL) or \
           (direction == "short" and regime.primary_regime == Regime.TRENDING_BEAR):
            self._add_confluence(signal, f"Regime aligned ({regime.primary_regime})")

        # ── Liquidity path quality ────────────────────────────────────────────
        if liq_result["path_clear"]:
            self._add_confluence(signal, "Liquidity path clear to target")
        elif liq_result["unnamed_in_path"] > 0:
            # Unnamed clusters reduce grade via notes — handled in scorer
            signal.notes += (
                f" | {liq_result['unnamed_in_path']} unnamed liq cluster(s) in path"
                f" — grade reduced"
            )
            logger.info(
                f"ORB: {liq_result['unnamed_in_path']} unnamed pool(s) in path "
                f"— size will be reduced (grade drop)"
            )

        # ── Rule 3: target adjusted ───────────────────────────────────────────
        if liq_result.get("target_adjusted"):
            signal.notes += (
                f" | Target adjusted to {target_100:.2f} "
                f"(named level {liq_result['target_adj_reason']} just beyond TP)"
            )
            logger.info(
                f"ORB: target adjusted to {target_100:.2f} — "
                f"named level {liq_result['target_adj_reason']} beyond original TP"
            )

        # ── Fed day boost ─────────────────────────────────────────────────────
        if macro.is_fed_day:
            self._add_confluence(
                signal, f"Fed day: {macro.fed_event_name} (+confluence)"
            )
            signal.conviction += FED_DAY_ORB_BOOST

        signal.conviction += regime.conviction * 0.7

        # Need at least 2 confluence factors
        if len(signal.confluence_factors) < 2:
            logger.info("ORB: insufficient confluence — no signal")
            return None

        # ── Strike selection ──────────────────────────────────────────────────
        # If target was adjusted, project strike from the adjusted target
        target_strike = orb.target_strike
        if liq_result.get("target_adjusted"):
            from utils.math_utils import round_to_strike
            from config import STRIKE_INCREMENT
            target_strike = round_to_strike(target_100, STRIKE_INCREMENT)

        contract = get_chain_fetcher().select_orb_strike(
            chain, direction, target_strike
        )
        if contract is None:
            logger.warning("ORB: no valid option contract found")
            return None

        signal.strike        = contract.strike
        signal.expiry        = contract.expiry
        signal.entry_premium = contract.mark
        signal.contract      = contract

        if signal.entry_premium <= 0:
            logger.warning("ORB: option has zero premium — skipping")
            return None

        logger.info(
            f"🎯 ORB SIGNAL {direction.upper()}: "
            f"underlying={current_price:.2f} "
            f"orb={orb.orb_low:.2f}–{orb.orb_high:.2f} "
            f"width={orb.orb_width:.2f} "
            f"option={option_side.upper()} {contract.strike} "
            f"mark=${contract.mark:.2f} delta={contract.delta:.3f} "
            f"stop={orb.stop_level:.2f} target={target_100:.2f} "
            f"break_is_named={liq_result['break_is_named_level']} "
            f"path_clear={liq_result['path_clear']} "
            f"target_adjusted={liq_result.get('target_adjusted', False)} "
            f"fed_day={macro.is_fed_day} "
            f"confluence={signal.confluence_factors}"
        )
        return signal

    # ─── Liquidity Analysis ───────────────────────────────────────────────────

    def _analyze_liquidity(self,
                            orb: ORBData,
                            liq_map: LiquidityMap,
                            current_price: float,
                            direction: str,
                            break_level: float) -> dict:
        """
        Full liquidity analysis for the ORB setup. Returns a result dict:

          break_is_named_level: bool   — Rule 1: break level == named pool
          break_level_name:     str    — name of that pool if Rule 1 fired
          block:                bool   — Rule 2: hard block this trade
          block_reason:         str    — why it was blocked
          path_clear:           bool   — no pools between entry and 100% TP
          named_in_path:        int    — named pools in path (between entry and 50% TP)
          unnamed_in_path:      int    — unnamed clusters in path
          target_adjusted:      bool   — Rule 3 fired
          adjusted_target:      float  — new target if Rule 3 fired
          target_adj_reason:    str    — name of pool that caused adjustment
        """
        result = {
            "break_is_named_level": False,
            "break_level_name":     "",
            "block":                False,
            "block_reason":         "",
            "path_clear":           True,
            "named_in_path":        0,
            "unnamed_in_path":      0,
            "target_adjusted":      False,
            "adjusted_target":      orb.target_100pct,
            "target_adj_reason":    "",
        }

        orb_width   = orb.orb_width
        target_100  = orb.target_100pct
        target_50   = orb.target_50pct

        for pool in liq_map.pools:
            if pool.swept:
                continue

            pool_price  = pool.price
            is_named    = pool.is_named
            pool_name   = pool.name or "unnamed"

            # ── Rule 1: Is the break level itself a named pool? ───────────────
            # Break long = price broke above ORB high.
            # Is ORB high at or near a named level?
            prox = abs(pool_price - break_level) / max(break_level, 1)
            if is_named and prox <= BREAK_LEVEL_PROXIMITY_PCT:
                result["break_is_named_level"] = True
                result["break_level_name"]     = pool_name
                logger.info(
                    f"ORB Rule 1: break level {break_level:.2f} is "
                    f"named pool {pool_name} ({pool_price:.2f}) — catalyst setup"
                )
                # This pool is the catalyst — don't also count it as an obstacle
                continue

            # Determine if pool is directionally relevant (obstacle kind)
            # Long break: high pools above entry are obstacles
            # Short break: low pools below entry are obstacles
            is_obstacle_kind = (
                (direction == "long"  and pool.kind == "high") or
                (direction == "short" and pool.kind == "low")
            )
            if not is_obstacle_kind:
                continue

            # ── Rule 2: Named pool between entry and 50% TP ──────────────────
            # This is the danger zone — the fakeout reversal zone
            in_danger_zone = (
                (direction == "long"  and current_price < pool_price < target_50) or
                (direction == "short" and target_50 < pool_price < current_price)
            )
            if in_danger_zone and is_named:
                result["named_in_path"] += 1
                result["path_clear"]     = False
                logger.warning(
                    f"ORB Rule 2: named pool {pool_name} ({pool_price:.2f}) "
                    f"sits between entry ({current_price:.2f}) and "
                    f"50%TP ({target_50:.2f}) — fakeout risk"
                )

            # Unnamed pool in path (between entry and 100% TP)
            in_full_path = (
                (direction == "long"  and current_price < pool_price < target_100) or
                (direction == "short" and target_100 < pool_price < current_price)
            )
            if in_full_path and not is_named:
                result["unnamed_in_path"] += 1
                result["path_clear"]       = False

            # ── Rule 3: Named pool just beyond 100% TP ───────────────────────
            # Named level sits past TP but within 0.5 ORB widths — adjust target
            adj_zone_long  = (direction == "long"  and
                              target_100 < pool_price < target_100 + orb_width * BEYOND_TP_ADJUSTMENT_WIDTHS)
            adj_zone_short = (direction == "short" and
                              target_100 - orb_width * BEYOND_TP_ADJUSTMENT_WIDTHS < pool_price < target_100)

            if is_named and (adj_zone_long or adj_zone_short) and not result["target_adjusted"]:
                result["target_adjusted"]   = True
                result["adjusted_target"]   = pool_price
                result["target_adj_reason"] = pool_name
                logger.info(
                    f"ORB Rule 3: named pool {pool_name} ({pool_price:.2f}) "
                    f"just beyond TP ({target_100:.2f}) — adjusting target to pool"
                )

        # ── Rule 2 decision: block or allow? ─────────────────────────────────
        # Named pool in the danger zone (between entry and 50% TP):
        # Block unless we have the named-level catalyst (Rule 1 fired)
        # OR it's a Fed day (explosive move likely to run through)
        if result["named_in_path"] > 0 and not result["break_is_named_level"]:
            block_reason = (
                f"Named pool in fakeout zone (entry→50%TP): "
                f"{result['named_in_path']} named level(s). "
                f"High reversal risk — ORB may be funding a liquidity grab."
            )
            result["block"]        = True
            result["block_reason"] = block_reason

        return result
