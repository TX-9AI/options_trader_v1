"""
strategy/base_strategy.py — Abstract base and OptionsSignal for all strategies.
OptionsSignal extends the crypto TradeSignal with options-specific fields:
strike, expiry, option_type, contract count, and premium.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, List

from data.options_chain import OptionContract, OptionsChain
from analysis.orb_engine import ORBData


@dataclass
class OptionsSignal:
    """
    A candidate options trade proposal.
    Validated and sized before reaching execution.
    """
    # ── Strategy identity ─────────────────────────────────────────────────────
    strategy_name:  str   = ""
    setup_type:     str   = ""      # e.g. "ORB Long", "Sweep Reversal Short"

    # ── Direction ─────────────────────────────────────────────────────────────
    direction:      str   = ""      # "long" or "short" (of the UNDERLYING)
    option_side:    str   = ""      # "call" or "put"

    # ── Underlying price levels ───────────────────────────────────────────────
    underlying_entry:   float = 0.0
    underlying_stop:    float = 0.0     # Underlying price that triggers exit
    underlying_target:  float = 0.0     # 100% TP at underlying level
    underlying_tp50:    float = 0.0     # 50% TP (trailing stop activation)

    # ── Option details (filled after chain lookup) ────────────────────────────
    strike:         float = 0.0
    expiry:         str   = ""          # YYYY-MM-DD (today for 0DTE)
    entry_premium:  float = 0.0         # Mark price at entry (per share)
    contract:       Optional[OptionContract] = None

    # For butterfly: three legs
    is_butterfly:   bool  = False
    lower_contract: Optional[OptionContract] = None
    center_contract: Optional[OptionContract] = None
    upper_contract:  Optional[OptionContract] = None
    butterfly_direction: str = ""       # "call" or "put"
    net_debit:      float = 0.0         # Net debit per share (butterfly)
    max_profit:     float = 0.0         # Max profit per share (butterfly)

    # ── Risk / sizing ─────────────────────────────────────────────────────────
    contracts:      int   = 0           # Whole contracts
    total_cost:     float = 0.0         # Total $ spent (contracts × premium × 100)
    max_loss:       float = 0.0         # = total_cost (defined-risk debit trade)
    stop_loss_pct:  float = 0.25        # Exit at 25% loss of premium
    tp_pct:         float = 1.0         # 100% TP (or 25% for butterfly)

    # ── Quality ───────────────────────────────────────────────────────────────
    confluence_factors: List[str] = field(default_factory=list)
    conviction:     float = 0.0
    setup_grade:    str   = "B"

    # ── Context ───────────────────────────────────────────────────────────────
    regime:         str   = ""
    vix_at_signal:  float = 0.0
    is_fed_day:     bool  = False
    notes:          str   = ""

    @property
    def is_valid(self) -> bool:
        if self.is_butterfly:
            return (
                self.butterfly_direction in ("call", "put") and
                self.net_debit > 0 and
                self.lower_contract is not None and
                self.center_contract is not None and
                self.upper_contract is not None
            )
        return (
            self.option_side in ("call", "put") and
            self.strike > 0 and
            self.entry_premium > 0 and
            self.underlying_entry > 0
        )

    def stop_premium(self) -> float:
        """Premium level at which we exit (25% loss)."""
        if self.is_butterfly:
            return self.net_debit * (1 - self.stop_loss_pct)
        return self.entry_premium * (1 - self.stop_loss_pct)

    def trail_activation_premium(self) -> float:
        """Premium level at which trailing stop activates (50% TP)."""
        if self.is_butterfly:
            return self.net_debit + self.max_profit * 0.5
        return self.entry_premium * (1 + self.tp_pct * 0.5)

    def target_premium(self) -> float:
        """Full TP premium target (100% for directional, 25% max profit for butterfly)."""
        if self.is_butterfly:
            return self.net_debit + self.max_profit * self.tp_pct
        return self.entry_premium * (1 + self.tp_pct)


class BaseOptionsStrategy(ABC):
    """Abstract base for all options strategies."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def generate_signal(self, *args, **kwargs) -> Optional[OptionsSignal]: ...

    def _add_confluence(self, signal: OptionsSignal, factor: str):
        signal.confluence_factors.append(factor)
