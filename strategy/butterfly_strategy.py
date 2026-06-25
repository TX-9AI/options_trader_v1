"""
strategy/butterfly_strategy.py — Debit butterfly for RANGING/COMPRESSION regimes.

Debit call butterfly: buy 1 lower call + sell 2 ATM calls + buy 1 upper call
Debit put butterfly:  buy 1 upper put  + sell 2 ATM puts  + buy 1 lower put

Direction (call vs put butterfly):
  - VWAP above price → put butterfly (bearish lean)
  - VWAP below price → call butterfly (bullish lean)
  - Flat/neutral → whichever has lower net debit (tightest spread)

TP: 25% of max profit (quick exit)
SL: 25% of net debit paid
Hard exit: 2:00 PM ET (no butterfly entries after cutoff)
Max hold: 2.5 hours
Blocked if: VIX > 20, Fed day, or entry cutoff passed
"""

import logging
import math
from typing import Optional

from strategy.base_strategy import BaseOptionsStrategy, OptionsSignal
from analysis.regime_classifier import RegimeState, Regime
from analysis.volatility_engine import VolatilityState
from analysis.liquidity_mapper import LiquidityMap
from data.options_chain import OptionsChain, OptionContract
from data.options_chain import get_chain_fetcher
from data.macro_data import MacroSnapshot
from config import (
    BUTTERFLY_TP_PCT, BUTTERFLY_WING_ATR_MULT, BUTTERFLY_MIN_WING,
    STRIKE_INCREMENT, VIX_BUTTERFLY_DISABLE, CONTRACT_MULTIPLIER
)

logger = logging.getLogger(__name__)


class ButterflyStrategy(BaseOptionsStrategy):
    """
    Debit butterfly strategy for ranging/compression sessions.
    Profits when underlying stays near the center strike.
    """

    @property
    def name(self) -> str:
        return "ButterflyStrategy"

    def generate_signal(self,
                         regime: RegimeState,
                         vol_state: VolatilityState,
                         liq_map: LiquidityMap,
                         chain: OptionsChain,
                         macro: MacroSnapshot,
                         current_price: float) -> Optional[OptionsSignal]:
        """
        Generate a butterfly signal for ranging/compression conditions.

        Args:
            regime:         Must be RANGING or COMPRESSION
            vol_state:      For ATR (wing width) and VWAP (direction bias)
            liq_map:        For nearby pools (center strike placement)
            chain:          0DTE options chain
            macro:          VIX gate, Fed day gate
            current_price:  Current underlying price

        Returns:
            OptionsSignal with is_butterfly=True, or None
        """
        # ── Hard gates ────────────────────────────────────────────────────────
        if regime.primary_regime not in (Regime.RANGING, Regime.COMPRESSION):
            return None

        if not macro.butterfly_allowed:
            logger.info(
                f"Butterfly blocked: VIX={macro.vix:.1f} or Fed day={macro.is_fed_day}"
            )
            return None

        # ── Determine butterfly direction ─────────────────────────────────────
        direction = self._pick_direction(vol_state, liq_map, current_price)

        # ── Wing width from ATR ───────────────────────────────────────────────
        atr = vol_state.atr_current
        if atr <= 0:
            atr = current_price * 0.005   # Fallback: 0.5% of price
        wing_points = max(
            round(atr * BUTTERFLY_WING_ATR_MULT / STRIKE_INCREMENT) * STRIKE_INCREMENT,
            BUTTERFLY_MIN_WING * STRIKE_INCREMENT
        )
        wing_strikes = int(wing_points / STRIKE_INCREMENT)

        # ── Fetch butterfly strikes from chain ────────────────────────────────
        strikes = get_chain_fetcher().select_butterfly_strikes(
            chain, direction, current_price, wing_strikes
        )
        if strikes is None:
            logger.warning("Butterfly: could not find all three strikes")
            return None

        lower  = strikes["lower"]
        center = strikes["center"]
        upper  = strikes["upper"]

        # ── Net debit and max profit ──────────────────────────────────────────
        # Debit butterfly cost: buy lower + buy upper − sell 2×center
        net_debit = lower.mark + upper.mark - 2 * center.mark
        if net_debit <= 0:
            logger.info(
                f"Butterfly: net debit ≤ 0 ({net_debit:.2f}) — skip"
            )
            return None

        # Max profit = wing width (strike distance) − net debit
        wing_width = upper.strike - center.strike   # In points
        max_profit = wing_width - net_debit
        if max_profit <= 0:
            logger.info(
                f"Butterfly: no max profit potential "
                f"(wing={wing_width:.0f} debit={net_debit:.2f})"
            )
            return None

        # ── Build signal ──────────────────────────────────────────────────────
        signal = OptionsSignal(
            strategy_name      = self.name,
            setup_type         = f"Debit {direction.title()} Butterfly",
            direction          = "neutral",
            option_side        = direction,
            is_butterfly       = True,
            butterfly_direction = direction,
            lower_contract     = lower,
            center_contract    = center,
            upper_contract     = upper,
            net_debit          = net_debit,
            max_profit         = max_profit,
            underlying_entry   = current_price,
            underlying_stop    = 0.0,    # Not used for butterfly (premium-based stop)
            underlying_target  = center.strike,
            regime             = regime.primary_regime,
            vix_at_signal      = macro.vix,
            is_fed_day         = macro.is_fed_day,
            stop_loss_pct      = 0.25,   # Exit at 25% loss of net debit
            tp_pct             = BUTTERFLY_TP_PCT,  # 25% of max profit
        )

        # Halve size if VIX in 15–20 zone
        if macro.butterfly_half_size:
            signal.notes = "VIX 15–20: half size butterfly"

        # ── Confluence ────────────────────────────────────────────────────────
        self._add_confluence(signal, f"Regime: {regime.primary_regime}")
        if vol_state.bb_width_pct <= 0.20:
            self._add_confluence(signal, f"BB squeeze ({vol_state.bb_width_pct:.0%} percentile)")
        if regime.adx < 20:
            self._add_confluence(signal, f"Low ADX ({regime.adx:.1f}) — no trend")
        if direction == "call" and vol_state.price_vs_vwap == "ABOVE":
            self._add_confluence(signal, "Above VWAP — slight bullish lean")
        elif direction == "put" and vol_state.price_vs_vwap == "BELOW":
            self._add_confluence(signal, "Below VWAP — slight bearish lean")

        signal.conviction = regime.conviction * 0.7

        logger.info(
            f"🦋 BUTTERFLY {direction.upper()}: "
            f"strikes={lower.strike}/{center.strike}/{upper.strike} "
            f"net_debit=${net_debit:.2f} "
            f"max_profit=${max_profit:.2f} "
            f"TP_target=${max_profit * BUTTERFLY_TP_PCT:.2f} (25%) "
            f"SL_threshold=${net_debit * 0.75:.2f} (25% loss) "
            f"VIX={macro.vix:.1f} "
            f"confluence={signal.confluence_factors}"
        )
        return signal

    def _pick_direction(self, vol_state: VolatilityState,
                         liq_map: LiquidityMap,
                         current_price: float) -> str:
        """
        Decide call vs put butterfly based on VWAP and liquidity context.
        Call butterfly profits from slight upside / stagnation above center.
        Put butterfly profits from slight downside / stagnation below center.
        """
        # Primary: VWAP bias
        if vol_state.vwap > 0:
            if vol_state.price_vs_vwap == "ABOVE":
                return "call"   # Price above VWAP → call butterfly (bullish lean)
            elif vol_state.price_vs_vwap == "BELOW":
                return "put"    # Price below VWAP → put butterfly (bearish lean)

        # Fallback: recent sweep direction (if any)
        if liq_map.recent_sweep:
            sweep = liq_map.recent_sweep
            if sweep.kind == "low_sweep":
                return "call"   # Lows swept → expect upside → call butterfly
            elif sweep.kind == "high_sweep":
                return "put"    # Highs swept → expect downside → put butterfly

        # Default: call butterfly (neutral lean)
        return "call"
