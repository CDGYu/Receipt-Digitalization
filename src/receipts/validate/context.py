"""Validation context and tunable configuration.

Separated from validator.py so that rules.py can import it without a circular
dependency (validator.py imports RULES from rules.py).

Everything tunable lives here and is overridable from config/rules.yaml, so a
deployment can loosen tolerances without a code change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from ..extract.schema import ConsistencyResult, TriageResult

# --------------------------------------------------------------------------- #
# Defaults
# --------------------------------------------------------------------------- #

DEFAULT_TOLERANCE = {"rel": Decimal("0.0002"), "floor": Decimal("0.02")}

#: Per-rule tolerance overrides. Rules not listed use DEFAULT_TOLERANCE.
DEFAULT_RULE_TOLERANCES: dict[str, dict[str, Decimal]] = {
    # Weighed goods (0.734 kg x 249.50) round at 3dp, so give the floor a
    # little more room -- but NOT the relative term.
    "R021": {"rel": Decimal("0.0005"), "floor": Decimal("0.05")},
    # Sum-of-lines vs subtotal accumulates per-line rounding. That is handled
    # explicitly by scaling the floor with line count at call time (rules.py),
    # which is why the relative term stays small here.
    "R020": {"rel": Decimal("0.0002"), "floor": Decimal("0.05")},
    "R024": {"rel": Decimal("0.0005"), "floor": Decimal("0.10")},
}


@dataclass
class RuleConfig:
    """Tunable thresholds. Field names are referenced directly by rules."""

    # tolerances
    tolerances: dict[str, dict[str, Decimal]] = field(
        default_factory=lambda: {k: dict(v) for k, v in DEFAULT_RULE_TOLERANCES.items()}
    )
    default_tolerance: dict[str, Decimal] = field(
        default_factory=lambda: dict(DEFAULT_TOLERANCE)
    )

    # plausibility bounds
    max_plausible_total: Decimal = Decimal("1000000")
    min_plausible_total: Decimal = Decimal("0.01")
    max_receipt_age_years: int = 10
    future_date_slack_days: int = 1
    max_qty: Decimal = Decimal("10000")
    max_tax_rate: Decimal = Decimal("0.35")
    unit_price_outlier_factor: Decimal = Decimal("100")

    # currency
    known_currencies: frozenset[str] = frozenset(
        """
        AED ARS AUD BDT BGN BHD BND BRL CAD CHF CLP CNY COP CZK DKK EGP EUR
        GBP HKD HRK HUF IDR ILS INR IQD ISK JPY KES KRW KWD LKR MAD MXN MYR
        NGN NOK NZD OMR PEN PHP PKR PLN QAR RON RSD RUB SAR SEK SGD THB TRY
        TWD TZS UAH USD VND ZAR
        """.split()
    )

    # behaviour switches
    require_line_items: bool = True
    strict_ocr_grounding: bool = False

    # ------------------------------------------------------------------ #

    @classmethod
    def from_yaml(cls, path: str | Path) -> "RuleConfig":
        """Load overrides. Absent keys keep their defaults."""
        data: dict[str, Any] = yaml.safe_load(Path(path).read_text()) or {}
        cfg = cls()

        for rule_id, tol in (data.get("tolerances") or {}).items():
            cfg.tolerances[rule_id] = {k: Decimal(str(v)) for k, v in tol.items()}

        if "default_tolerance" in data:
            cfg.default_tolerance = {
                k: Decimal(str(v)) for k, v in data["default_tolerance"].items()
            }

        decimal_fields = {
            "max_plausible_total",
            "min_plausible_total",
            "max_qty",
            "max_tax_rate",
            "unit_price_outlier_factor",
        }
        for key in (
            decimal_fields
            | {"max_receipt_age_years", "future_date_slack_days",
               "require_line_items", "strict_ocr_grounding"}
        ):
            if key in data:
                value = data[key]
                setattr(cfg, key, Decimal(str(value)) if key in decimal_fields else value)

        if "known_currencies" in data:
            cfg.known_currencies = frozenset(str(c).upper() for c in data["known_currencies"])

        return cfg


@dataclass
class ValidationContext:
    """Everything the rules may look at besides the extraction itself.

    All fields are optional. A rule whose context is missing must SKIP via
    `applies()`, never fail — an unrunnable rule producing a finding pollutes
    the repair prompt with noise.
    """

    triage: TriageResult | None = None
    ocr_text: str | None = None
    merchant: Any | None = None
    consistency: ConsistencyResult | None = None
    parse_error: str | None = None
    config: RuleConfig = field(default_factory=RuleConfig)
    today: date = field(default_factory=date.today)

    def tol(self, rule_id: str) -> dict[str, Decimal]:
        """Tolerance kwargs for a rule, falling back to the default."""
        return dict(self.config.tolerances.get(rule_id, self.config.default_tolerance))
