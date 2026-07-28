"""The 28 validation rules.

Design contract for every rule in this module:

  * Deterministic. Same inputs, same findings, always.
  * No I/O, no network, no model calls.
  * Never mutates the extraction.
  * `applies()` returns False when the rule's inputs are missing. A rule that
    cannot meaningfully run must SKIP, not fail — findings from unrunnable
    rules pollute the repair prompt and cost accuracy.
  * `message` is written for the repair MODEL to read. Name the actual numbers.

Rule IDs are stable and are stored in the database. Never renumber.
"""

from __future__ import annotations

import re
import unicodedata
from abc import ABC, abstractmethod
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import ClassVar, Iterable, NamedTuple

from ..extract.schema import ReceiptExtraction
from .context import ValidationContext
from .report import Finding, Severity

# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #

RULES: list["Rule"] = []


def register(cls: type["Rule"]) -> type["Rule"]:
    """Class decorator: instantiate and append to RULES, keeping ID order."""
    instance = cls()
    if any(r.id == instance.id for r in RULES):
        raise ValueError(f"Duplicate rule id {instance.id}")
    RULES.append(instance)
    RULES.sort(key=lambda r: r.id)
    return cls


class Rule(ABC):
    id: ClassVar[str]
    severity: ClassVar[Severity]
    description: ClassVar[str] = ""

    def applies(self, r: ReceiptExtraction, ctx: ValidationContext) -> bool:
        return True

    @abstractmethod
    def check(self, r: ReceiptExtraction, ctx: ValidationContext) -> list[Finding]:
        ...

    # convenience -------------------------------------------------------- #

    def finding(
        self,
        message: str,
        *,
        field_paths: Iterable[str] = (),
        context: dict | None = None,
        severity: Severity | None = None,
    ) -> Finding:
        return Finding(
            rule_id=self.id,
            severity=severity or self.severity,
            message=message,
            field_paths=list(field_paths),
            context=context or {},
        )


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #


def within_tolerance(
    a: Decimal | None,
    b: Decimal | None,
    *,
    rel: Decimal = Decimal("0.0002"),
    floor: Decimal = Decimal("0.02"),
) -> bool:
    """True when a and b agree to within max(floor, rel * max(|a|, |b|)).

    `floor` absorbs cent-level rounding; `rel` is a small safety valve for very
    large totals and 3-decimal currencies.

    KEEP `rel` SMALL. Rounding error is bounded in cents, not proportional to
    magnitude. A 0.5% relative tolerance grants +/-4.75 on a 949.20 total, which
    silently excuses a misread digit and defeats the entire point of the rule.
    Returns False if either side is None — callers must gate on presence in
    `applies()`, not rely on this.
    """
    if a is None or b is None:
        return False
    tol = max(floor, rel * max(abs(a), abs(b)))
    return abs(a - b) <= tol


def m(value: Decimal | None) -> str:
    """Format a money value for a prompt-facing message."""
    if value is None:
        return "null"
    return f"{value.normalize():f}" if value == value.to_integral_value() else f"{value:f}"


def discount_magnitude(value: Decimal | None) -> Decimal:
    """Discounts are stored positive but models emit them negative. Use the
    magnitude so the rule is correct under either convention."""
    return abs(value) if value is not None else Decimal(0)


def sum_line_nets(r: ReceiptExtraction) -> Decimal | None:
    """Sum of line_total + signed modifiers. None if any line_total is missing."""
    if not r.line_items:
        return None
    total = Decimal(0)
    for item in r.line_items:
        net = item.net_total()
        if net is None:
            return None
        total += net
    return total


class Comparand(NamedTuple):
    """A figure the line-item sum may legitimately equal.

    `label` is prompt-facing text (the finding names it), `key` is the stable
    short name recorded in the finding context, `field_path` is what a reviewer
    would edit if this figure is the wrong one.
    """

    key: str
    label: str
    value: Decimal
    field_path: str


def tax_convention_comparands(
    prices_include_tax: bool | None,
    *,
    net: Comparand | None,
    gross: Comparand | None,
) -> list[Comparand]:
    """Which figures a line-item sum may equal, given the document's convention.

    `net` is the comparand for an Amount column that EXCLUDES tax; `gross` for
    one that INCLUDES it (Philippine BIR "SALES INVOICE" forms, EU-style gross
    pricing — there `subtotal` is the net-of-tax base and the lines add up to
    `total`).

      * ``False`` -> net only.
      * ``True``  -> gross only. An explicit flag is honoured, never softened.
      * ``None``  -> either is acceptable, so the rule fires only when NEITHER
        fits. This is the common path: nothing in the pipeline sets the flag,
        most documents do not state a convention, and assuming one turns a
        receipt that reconciles perfectly (R022 passes) into a false ERROR that
        blocks auto-approval, burns a repair call, and pressures the model into
        changing numbers that are already right.

    A comparand whose value is missing is dropped, so an empty result means the
    rule cannot run and must SKIP rather than fire on a figure it does not have.
    """
    candidates: list[Comparand | None] = []
    if prices_include_tax is not True:
        candidates.append(net)
    if prices_include_tax is not False:
        candidates.append(gross)
    return [c for c in candidates if c is not None]


def render_comparisons(line_sum: Decimal, comparands: Iterable[Comparand]) -> str:
    """Render the attempted comparisons for a prompt-facing finding message.

    Produces e.g. `vs subtotal 892.86 -> difference 107.14; vs total ...`. Every
    comparison that was tried is named with its own difference, so the repair
    prompt can see which reading is closer instead of guessing.
    """
    return "; ".join(
        f"vs {c.label} {m(c.value)} -> difference {m(line_sum - c.value)}"
        for c in comparands
    )


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except (ValueError, AttributeError):
        return None


_AMOUNT_TAIL = re.compile(r"[\s:.\-]*[-+]?[\d,]+(?:[.,]\d+)?\s*$")
_NON_ALNUM = re.compile(r"[^A-Z0-9 ]+")
_WS = re.compile(r"\s+")


def normalize_desc(value: str | None) -> str:
    """Uppercase, drop a trailing amount, strip punctuation, collapse spaces."""
    s = unicodedata.normalize("NFKC", value or "").upper()
    s = _AMOUNT_TAIL.sub("", s)
    s = _NON_ALNUM.sub(" ", s)
    return _WS.sub(" ", s).strip()


#: Descriptions that are structurally NOT purchasable items. Exact match only,
#: after normalisation — "TOTAL WINE CO" and "CASH CARD TOPUP" must not match.
TOTAL_ROW_STRONG = frozenset(
    {
        "TOTAL", "SUBTOTAL", "SUB TOTAL", "GRAND TOTAL", "NET TOTAL", "GROSS TOTAL",
        "TOTAL DUE", "AMOUNT DUE", "BALANCE DUE", "TOTAL AMOUNT", "TOTAL SALES",
        "TAX", "TAXES", "TOTAL TAX", "SALES TAX", "VAT", "VAT AMOUNT", "VATABLE",
        "VATABLE SALES", "VAT EXEMPT", "VAT EXEMPT SALES", "ZERO RATED",
        "ZERO RATED SALES", "GST", "GST AMOUNT", "TOTAL VAT",
        "CHANGE", "CHANGE DUE", "CASH", "CASH TENDERED", "TENDER", "TENDERED",
        "AMOUNT TENDERED", "TOTAL PAYMENT", "TOTAL ITEMS", "ITEMS SOLD",
        "NO OF ITEMS", "TOTAL QTY", "THANK YOU", "THANKS", "CUSTOMER COPY",
        "MERCHANT COPY",
    }
)

#: Plausibly a real line on some receipts (restaurants charge service; some
#: merchants ring rounding as a line). Flagged softer.
TOTAL_ROW_SOFT = frozenset(
    {"SERVICE CHARGE", "DISCOUNT", "TOTAL DISCOUNT", "LESS DISCOUNT",
     "ROUNDING", "ROUND OFF", "PAYMENT"}
)


def digits_only(value: str) -> str:
    return re.sub(r"\D", "", value)


def median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / Decimal(2)


# =========================================================================== #
# PRESENCE
# =========================================================================== #


@register
class SchemaParses(Rule):
    id = "R001"
    severity = Severity.ERROR
    description = "Model output deserialised into ReceiptExtraction."

    def applies(self, r, ctx) -> bool:
        return ctx.parse_error is not None

    def check(self, r, ctx) -> list[Finding]:
        return [
            self.finding(
                "The previous response did not parse as valid JSON matching the "
                f"schema: {ctx.parse_error}. Return a single JSON object with no "
                "markdown fences and no prose.",
                context={"parse_error": ctx.parse_error},
            )
        ]


@register
class TotalPresent(Rule):
    id = "R010"
    severity = Severity.ERROR
    description = "totals.total is not null."

    def check(self, r, ctx) -> list[Finding]:
        if r.totals.total is not None:
            return []
        return [
            self.finding(
                "totals.total is null. Every receipt has a final amount payable. "
                "Locate it (usually the largest, boldest, or last figure) and "
                "extract it. If it is genuinely illegible, leave it null and add "
                "'totals.total' to meta.ambiguous_fields.",
                field_paths=["totals.total"],
            )
        ]


@register
class DatePresent(Rule):
    id = "R011"
    severity = Severity.WARN
    description = "receipt.date is not null."

    def check(self, r, ctx) -> list[Finding]:
        if r.receipt.date is not None:
            return []
        # Not a problem if the model correctly parked an ambiguous date.
        if r.receipt.date_raw:
            return [
                self.finding(
                    f"receipt.date is null but date_raw is {r.receipt.date_raw!r}. "
                    "This is acceptable if the printed date is genuinely ambiguous.",
                    field_paths=["receipt.date"],
                    severity=Severity.INFO,
                )
            ]
        return [
            self.finding(
                "receipt.date is null and no date_raw was captured. Check the "
                "header and footer of the receipt for a transaction date.",
                field_paths=["receipt.date", "receipt.date_raw"],
            )
        ]


@register
class MerchantPresent(Rule):
    id = "R012"
    severity = Severity.WARN
    description = "merchant.name is not null or blank."

    def check(self, r, ctx) -> list[Finding]:
        name = (r.merchant.name or "").strip()
        if name:
            return []
        return [
            self.finding(
                "merchant.name is empty. The merchant name is normally the "
                "largest text at the top of the receipt. Do not guess it from a "
                "logo you only partly recognise — leave it null if unreadable.",
                field_paths=["merchant.name"],
            )
        ]


@register
class LineItemsPresent(Rule):
    id = "R013"
    severity = Severity.WARN
    description = "At least one line item was extracted."

    def applies(self, r, ctx) -> bool:
        if not ctx.config.require_line_items:
            return False
        if ctx.triage and ctx.triage.estimated_line_item_count == 0:
            return False
        return True

    def check(self, r, ctx) -> list[Finding]:
        if r.line_items:
            return []
        expected = ctx.triage.estimated_line_item_count if ctx.triage else None
        hint = f" Triage estimated roughly {expected} line items." if expected else ""
        return [
            self.finding(
                f"No line items were extracted.{hint} Re-read the body of the "
                "receipt between the header and the subtotal.",
                field_paths=["line_items"],
                context={"estimated": expected},
            )
        ]


# =========================================================================== #
# ARITHMETIC
# =========================================================================== #


@register
class LineItemsSumToSubtotal(Rule):
    id = "R020"
    severity = Severity.ERROR
    description = (
        "Sum of line items equals the printed subtotal, or the total when the "
        "line amounts are tax-inclusive."
    )

    def _comparands(self, r) -> list[Comparand]:
        """The figures the line sum may equal under the document's convention.

        Net of tax the lines equal `subtotal`; tax-inclusive they equal `total`.
        `totals.prices_include_tax` picks one; null accepts either.
        """
        t = r.totals
        return tax_convention_comparands(
            t.prices_include_tax,
            net=(
                Comparand("subtotal", "subtotal", t.subtotal, "totals.subtotal")
                if t.subtotal is not None
                else None
            ),
            gross=(
                Comparand(
                    "total", "total (amounts read as tax-inclusive)", t.total, "totals.total"
                )
                if t.total is not None
                else None
            ),
        )

    def applies(self, r, ctx) -> bool:
        # A null subtotal is R024's case (the fallback), so this rule keeps its
        # spec contract of skipping there — the two must not report the same
        # problem twice.
        return (
            r.totals.subtotal is not None
            and bool(self._comparands(r))
            and sum_line_nets(r) is not None
        )

    def check(self, r, ctx) -> list[Finding]:
        total = sum_line_nets(r)
        if total is None:  # gated by applies(); a rule must never raise
            return []

        tol = ctx.tol(self.id)
        # Per-line rounding accumulates, so scale the floor with line count.
        tol["floor"] = max(tol["floor"], Decimal("0.01") * len(r.line_items))

        comparands = self._comparands(r)
        if any(within_tolerance(total, c.value, **tol) for c in comparands):
            return []

        lead = (
            f"Line items sum to {m(total)} across {len(r.line_items)} items and "
            f"reconcile with no printed figure: {render_comparisons(total, comparands)}."
        )
        if len(comparands) > 1:
            lead += (
                " Both readings of the amount column were tried (net of tax, where "
                "the lines sum to subtotal; tax-inclusive, where they sum to total) "
                "and neither fits."
            )
        return [
            self.finding(
                f"{lead} Either an item is missing, an item was read twice, one "
                "line amount is wrong, or a printed figure is wrong. Do not adjust "
                "a number that is printed correctly to make the arithmetic close.",
                field_paths=["line_items", *(c.field_path for c in comparands)],
                context={
                    "line_sum": str(total),
                    "item_count": len(r.line_items),
                    "prices_include_tax": r.totals.prices_include_tax,
                    "compared_against": {c.key: str(c.value) for c in comparands},
                    "differences": {c.key: str(total - c.value) for c in comparands},
                },
            )
        ]


@register
class LineItemMath(Rule):
    id = "R021"
    severity = Severity.ERROR
    description = "qty x unit_price equals line_total, per row."

    def applies(self, r, ctx) -> bool:
        return any(
            i.qty is not None and i.unit_price is not None and i.line_total is not None
            for i in r.line_items
        )

    def check(self, r, ctx) -> list[Finding]:
        tol = ctx.tol(self.id)
        findings: list[Finding] = []
        for item in r.line_items:
            if item.qty is None or item.unit_price is None or item.line_total is None:
                continue
            expected = item.qty * item.unit_price
            if within_tolerance(expected, item.line_total, **tol):
                continue
            findings.append(
                self.finding(
                    f"Line item {item.position} {item.description_raw!r}: "
                    f"qty({m(item.qty)}) x unit_price({m(item.unit_price)}) = "
                    f"{m(expected)}, but line_total was extracted as "
                    f"{m(item.line_total)}.",
                    field_paths=[
                        f"line_items[{item.position}].qty",
                        f"line_items[{item.position}].unit_price",
                        f"line_items[{item.position}].line_total",
                    ],
                    context={
                        "position": item.position,
                        "qty": str(item.qty),
                        "unit_price": str(item.unit_price),
                        "expected": str(expected),
                        "actual": str(item.line_total),
                    },
                )
            )
        return findings


@register
class TotalsEquation(Rule):
    id = "R022"
    severity = Severity.ERROR
    description = "subtotal + tax - discount equals total."

    def applies(self, r, ctx) -> bool:
        return r.totals.total is not None and r.totals.subtotal is not None

    def check(self, r, ctx) -> list[Finding]:
        t = r.totals
        tax = t.tax or Decimal(0)
        disc = discount_magnitude(t.discount)
        expected = t.subtotal + tax - disc

        if within_tolerance(expected, t.total, **ctx.tol(self.id)):
            return []

        return [
            self.finding(
                f"Totals equation failed: subtotal({m(t.subtotal)}) + "
                f"tax({m(tax)}) - discount({m(disc)}) = {m(expected)}, but total "
                f"was extracted as {m(t.total)} (difference "
                f"{m(abs(expected - t.total))}). Note: if the receipt is "
                "tax-inclusive, tax must NOT be added again on top of subtotal.",
                field_paths=[
                    "totals.subtotal", "totals.tax", "totals.discount", "totals.total"
                ],
                context={
                    "subtotal": str(t.subtotal),
                    "tax": str(tax),
                    "discount": str(disc),
                    "expected": str(expected),
                    "actual": str(t.total),
                },
            )
        ]


@register
class TenderChange(Rule):
    id = "R023"
    severity = Severity.WARN
    description = "tender - total equals change."

    def applies(self, r, ctx) -> bool:
        t = r.totals
        return t.tender is not None and t.change is not None and t.total is not None

    def check(self, r, ctx) -> list[Finding]:
        t = r.totals
        expected = t.tender - t.total
        if within_tolerance(expected, t.change, **ctx.tol(self.id)):
            return []
        return [
            self.finding(
                f"Cash reconciliation failed: tender({m(t.tender)}) - "
                f"total({m(t.total)}) = {m(expected)}, but change was extracted "
                f"as {m(t.change)}.",
                field_paths=["totals.tender", "totals.change", "totals.total"],
                context={
                    "tender": str(t.tender),
                    "total": str(t.total),
                    "expected_change": str(expected),
                    "actual_change": str(t.change),
                },
            )
        ]


@register
class LineItemsSumToTotal(Rule):
    id = "R024"
    severity = Severity.WARN
    description = "Fallback for receipts with no printed subtotal."

    def _comparands(self, r, total: Decimal) -> list[Comparand]:
        """Same convention split as R020, with no subtotal to lean on.

        Net of tax the lines equal `total - tax + discount`; tax-inclusive they
        equal `total` outright.
        """
        t = r.totals
        tax = t.tax or Decimal(0)
        disc = discount_magnitude(t.discount)
        return tax_convention_comparands(
            t.prices_include_tax,
            net=Comparand(
                "implied_net",
                f"total({m(total)}) - tax({m(tax)}) + discount({m(disc)}) =",
                total - tax + disc,
                "totals.total",
            ),
            gross=Comparand(
                "total", "total (amounts read as tax-inclusive)", total, "totals.total"
            ),
        )

    def applies(self, r, ctx) -> bool:
        return (
            r.totals.subtotal is None
            and r.totals.total is not None
            and sum_line_nets(r) is not None
        )

    def check(self, r, ctx) -> list[Finding]:
        line_sum = sum_line_nets(r)
        if line_sum is None or r.totals.total is None:  # gated by applies()
            return []

        tol = ctx.tol(self.id)
        tol["floor"] = max(tol["floor"], Decimal("0.01") * len(r.line_items))

        comparands = self._comparands(r, r.totals.total)
        if any(within_tolerance(line_sum, c.value, **tol) for c in comparands):
            return []

        lead = (
            f"No subtotal was printed, so line items were checked against the total: "
            f"items sum to {m(line_sum)}, {render_comparisons(line_sum, comparands)}."
        )
        if len(comparands) > 1:
            lead += (
                " Both readings of the amount column were tried (net of tax, where "
                "the lines sum to total minus tax; tax-inclusive, where they sum to "
                "the total itself) and neither fits."
            )
        return [
            self.finding(
                f"{lead} Items may be missing. Keep the printed figures as they are.",
                field_paths=["line_items", "totals.total"],
                context={
                    "line_sum": str(line_sum),
                    "item_count": len(r.line_items),
                    "prices_include_tax": r.totals.prices_include_tax,
                    "compared_against": {c.key: str(c.value) for c in comparands},
                    "differences": {c.key: str(line_sum - c.value) for c in comparands},
                },
            )
        ]


@register
class TaxBreakdownSums(Rule):
    id = "R025"
    severity = Severity.WARN
    description = "Tax breakdown bands sum to the total tax."

    def applies(self, r, ctx) -> bool:
        bands = r.totals.tax_breakdown
        return (
            bool(bands)
            and r.totals.tax is not None
            and all(b.amount is not None for b in bands)
        )

    def check(self, r, ctx) -> list[Finding]:
        band_sum = sum((b.amount for b in r.totals.tax_breakdown), Decimal(0))
        if within_tolerance(band_sum, r.totals.tax, **ctx.tol(self.id)):
            return []
        return [
            self.finding(
                f"Tax breakdown bands sum to {m(band_sum)}, but totals.tax is "
                f"{m(r.totals.tax)}. One band amount is likely misread.",
                field_paths=["totals.tax", "totals.tax_breakdown"],
                context={"band_sum": str(band_sum), "tax": str(r.totals.tax)},
            )
        ]


# =========================================================================== #
# PLAUSIBILITY
# =========================================================================== #


@register
class DateParseable(Rule):
    id = "R030"
    severity = Severity.ERROR
    description = "receipt.date is a real calendar date in ISO 8601 form."

    def applies(self, r, ctx) -> bool:
        return r.receipt.date is not None

    def check(self, r, ctx) -> list[Finding]:
        if parse_iso_date(r.receipt.date):
            return []
        return [
            self.finding(
                f"receipt.date {r.receipt.date!r} is not a valid ISO 8601 date. "
                "Use YYYY-MM-DD. If the printed date is ambiguous between "
                "conventions, set receipt.date to null and put the verbatim "
                "string in receipt.date_raw instead.",
                field_paths=["receipt.date"],
                context={"value": r.receipt.date},
            )
        ]


@register
class DateNotFuture(Rule):
    id = "R031"
    severity = Severity.ERROR
    description = "The transaction date is not in the future."

    def applies(self, r, ctx) -> bool:
        return parse_iso_date(r.receipt.date) is not None

    def check(self, r, ctx) -> list[Finding]:
        parsed = parse_iso_date(r.receipt.date)
        slack = ctx.config.future_date_slack_days
        if (parsed - ctx.today).days <= slack:
            return []
        return [
            self.finding(
                f"receipt.date {r.receipt.date} is in the future (today is "
                f"{ctx.today.isoformat()}). This usually means day and month "
                "were swapped, or a digit in the year was misread.",
                field_paths=["receipt.date"],
                context={"value": r.receipt.date, "today": ctx.today.isoformat()},
            )
        ]


@register
class DateNotAncient(Rule):
    id = "R032"
    severity = Severity.WARN
    description = "The transaction date is not implausibly old."

    def applies(self, r, ctx) -> bool:
        return parse_iso_date(r.receipt.date) is not None

    def check(self, r, ctx) -> list[Finding]:
        parsed = parse_iso_date(r.receipt.date)
        max_days = ctx.config.max_receipt_age_years * 365
        age = (ctx.today - parsed).days
        if age <= max_days:
            return []
        return [
            self.finding(
                f"receipt.date {r.receipt.date} is about {age // 365} years old, "
                f"beyond the {ctx.config.max_receipt_age_years}-year plausibility "
                "window. Check the year digits.",
                field_paths=["receipt.date"],
                context={"value": r.receipt.date, "age_days": age},
            )
        ]


@register
class CurrencyKnown(Rule):
    id = "R033"
    severity = Severity.WARN
    description = "receipt.currency is a recognised ISO 4217 code."

    def applies(self, r, ctx) -> bool:
        return bool(r.receipt.currency)

    def check(self, r, ctx) -> list[Finding]:
        code = r.receipt.currency.strip().upper()
        if code in ctx.config.known_currencies:
            return []
        return [
            self.finding(
                f"receipt.currency {r.receipt.currency!r} is not a recognised "
                "ISO 4217 code. Use the three-letter code, or null if no currency "
                "is actually printed — do not infer it from the language.",
                field_paths=["receipt.currency"],
                context={"value": r.receipt.currency},
            )
        ]


@register
class TotalPositive(Rule):
    id = "R040"
    severity = Severity.ERROR
    description = "The total is positive unless the document is a refund."

    def applies(self, r, ctx) -> bool:
        return r.totals.total is not None and not r.meta.is_refund

    def check(self, r, ctx) -> list[Finding]:
        if r.totals.total > 0:
            return []
        return [
            self.finding(
                f"totals.total is {m(r.totals.total)}, which is not positive. If "
                "this document is a refund, void, or credit note, set "
                "meta.is_refund = true. Otherwise a sign or digit was misread.",
                field_paths=["totals.total", "meta.is_refund"],
                context={"total": str(r.totals.total)},
            )
        ]


@register
class TotalMagnitude(Rule):
    id = "R041"
    severity = Severity.WARN
    description = "The total falls inside the plausible range."

    def applies(self, r, ctx) -> bool:
        return r.totals.total is not None

    def check(self, r, ctx) -> list[Finding]:
        total = abs(r.totals.total)
        cfg = ctx.config
        if cfg.min_plausible_total <= total <= cfg.max_plausible_total:
            return []
        return [
            self.finding(
                f"totals.total {m(r.totals.total)} is outside the plausible range "
                f"[{m(cfg.min_plausible_total)}, {m(cfg.max_plausible_total)}]. "
                "A misplaced decimal point is the usual cause.",
                field_paths=["totals.total"],
                context={"total": str(r.totals.total)},
            )
        ]


@register
class UnitPricesSane(Rule):
    id = "R042"
    severity = Severity.WARN
    description = "No unit price is a wild outlier against the receipt's median."

    MIN_SAMPLES = 4

    def applies(self, r, ctx) -> bool:
        prices = [i.unit_price for i in r.line_items if i.unit_price and i.unit_price > 0]
        return len(prices) >= self.MIN_SAMPLES

    def check(self, r, ctx) -> list[Finding]:
        priced = [i for i in r.line_items if i.unit_price and i.unit_price > 0]
        med = median([i.unit_price for i in priced])
        limit = med * ctx.config.unit_price_outlier_factor

        findings: list[Finding] = []
        for item in priced:
            if item.unit_price <= limit:
                continue
            findings.append(
                self.finding(
                    f"Line item {item.position} {item.description_raw!r} has "
                    f"unit_price {m(item.unit_price)}, more than "
                    f"{m(ctx.config.unit_price_outlier_factor)}x the median unit "
                    f"price on this receipt ({m(med)}). Likely a misplaced decimal "
                    "point or a merged column.",
                    field_paths=[f"line_items[{item.position}].unit_price"],
                    context={
                        "position": item.position,
                        "unit_price": str(item.unit_price),
                        "median": str(med),
                    },
                )
            )
        return findings


@register
class QtySane(Rule):
    id = "R043"
    severity = Severity.WARN
    description = "Quantities are positive and not absurdly large."

    def applies(self, r, ctx) -> bool:
        return any(i.qty is not None for i in r.line_items)

    def check(self, r, ctx) -> list[Finding]:
        findings: list[Finding] = []
        for item in r.line_items:
            if item.qty is None:
                continue
            if Decimal(0) < item.qty <= ctx.config.max_qty:
                continue
            findings.append(
                self.finding(
                    f"Line item {item.position} {item.description_raw!r} has "
                    f"qty {m(item.qty)}, outside the plausible range "
                    f"(0, {m(ctx.config.max_qty)}]. A price column may have been "
                    "read as a quantity.",
                    field_paths=[f"line_items[{item.position}].qty"],
                    context={"position": item.position, "qty": str(item.qty)},
                )
            )
        return findings


@register
class TaxRatePlausible(Rule):
    id = "R044"
    severity = Severity.WARN
    description = "The implied tax rate is within a believable band."

    def applies(self, r, ctx) -> bool:
        return (
            r.totals.tax is not None
            and r.totals.subtotal is not None
            and r.totals.subtotal > 0
        )

    def check(self, r, ctx) -> list[Finding]:
        try:
            rate = r.totals.tax / r.totals.subtotal
        except (InvalidOperation, ZeroDivisionError):
            return []
        if Decimal(0) <= rate <= ctx.config.max_tax_rate:
            return []
        return [
            self.finding(
                f"Implied tax rate is {rate:.1%} (tax {m(r.totals.tax)} on "
                f"subtotal {m(r.totals.subtotal)}), outside the plausible band "
                f"0-{ctx.config.max_tax_rate:.0%}. The tax figure may actually be "
                "the taxable base, or a different total.",
                field_paths=["totals.tax", "totals.subtotal"],
                context={
                    "tax": str(r.totals.tax),
                    "subtotal": str(r.totals.subtotal),
                    "rate": str(rate),
                },
            )
        ]


@register
class DiscountNotExceeding(Rule):
    id = "R045"
    severity = Severity.WARN
    description = "The discount does not exceed the subtotal."

    def applies(self, r, ctx) -> bool:
        return r.totals.discount is not None and r.totals.subtotal is not None

    def check(self, r, ctx) -> list[Finding]:
        disc = discount_magnitude(r.totals.discount)
        if disc <= r.totals.subtotal:
            return []
        return [
            self.finding(
                f"Discount {m(disc)} exceeds subtotal {m(r.totals.subtotal)}. One "
                "of the two is misread, or a non-discount figure was captured as "
                "a discount.",
                field_paths=["totals.discount", "totals.subtotal"],
                context={"discount": str(disc), "subtotal": str(r.totals.subtotal)},
            )
        ]


# =========================================================================== #
# STRUCTURAL INTEGRITY
# =========================================================================== #


@register
class NoDuplicateLineItems(Rule):
    id = "R050"
    severity = Severity.INFO
    description = "Adjacent identical rows may indicate a double-read line."

    def applies(self, r, ctx) -> bool:
        return len(r.line_items) >= 2

    def check(self, r, ctx) -> list[Finding]:
        findings: list[Finding] = []
        for prev, item in zip(r.line_items, r.line_items[1:]):
            same = (
                normalize_desc(prev.description_raw) == normalize_desc(item.description_raw)
                and prev.qty == item.qty
                and prev.unit_price == item.unit_price
                and prev.line_total == item.line_total
            )
            if not same or not normalize_desc(item.description_raw):
                continue
            findings.append(
                self.finding(
                    f"Line items {prev.position} and {item.position} are "
                    f"identical ({item.description_raw!r}). This is legitimate if "
                    "the item was rung up twice, but check the image for a "
                    "double-read.",
                    field_paths=[f"line_items[{item.position}]"],
                    context={"positions": [prev.position, item.position]},
                )
            )
        return findings


@register
class PositionsContiguous(Rule):
    id = "R051"
    severity = Severity.INFO
    description = "Line item positions are 0..n-1 with no gaps or repeats."

    def applies(self, r, ctx) -> bool:
        return bool(r.line_items)

    def check(self, r, ctx) -> list[Finding]:
        positions = [i.position for i in r.line_items]
        expected = list(range(len(positions)))
        if sorted(positions) == expected:
            return []
        return [
            self.finding(
                f"Line item positions are {positions}, expected "
                f"{expected}. Positions must be 0-based, contiguous, and in "
                "printed order.",
                field_paths=["line_items"],
                context={"positions": positions},
            )
        ]


@register
class NoTotalRowAsLineItem(Rule):
    id = "R052"
    severity = Severity.ERROR
    description = "Subtotal/tax/change rows must not appear as line items."

    def applies(self, r, ctx) -> bool:
        return bool(r.line_items)

    def check(self, r, ctx) -> list[Finding]:
        findings: list[Finding] = []
        for item in r.line_items:
            norm = normalize_desc(item.description_raw)
            if not norm:
                continue
            if norm in TOTAL_ROW_STRONG:
                findings.append(
                    self.finding(
                        f"Line item {item.position} {item.description_raw!r} is a "
                        "summary row, not a purchasable item. Remove it from "
                        "line_items and put its amount in the correct totals "
                        "field. This also breaks the arithmetic checks.",
                        field_paths=[f"line_items[{item.position}]"],
                        context={"position": item.position, "normalized": norm},
                    )
                )
            elif norm in TOTAL_ROW_SOFT:
                findings.append(
                    self.finding(
                        f"Line item {item.position} {item.description_raw!r} may "
                        "be a summary or adjustment row rather than a purchasable "
                        "item. Basket-level discounts belong in totals.discount; "
                        "item-level ones belong in that item's modifiers.",
                        field_paths=[f"line_items[{item.position}]"],
                        context={"position": item.position, "normalized": norm},
                        severity=Severity.WARN,
                    )
                )
        return findings


@register
class DescriptionNotEmpty(Rule):
    id = "R053"
    severity = Severity.WARN
    description = "Every line item has a non-blank description."

    def applies(self, r, ctx) -> bool:
        return bool(r.line_items)

    def check(self, r, ctx) -> list[Finding]:
        findings: list[Finding] = []
        for item in r.line_items:
            if (item.description_raw or "").strip():
                continue
            findings.append(
                self.finding(
                    f"Line item {item.position} has an empty description but an "
                    f"amount of {m(item.line_total)}. Either transcribe the text "
                    "or drop the row if it is not a real item.",
                    field_paths=[f"line_items[{item.position}].description_raw"],
                    context={"position": item.position},
                )
            )
        return findings


# =========================================================================== #
# GROUNDING (requires an OCR text layer)
# =========================================================================== #


@register
class TotalAppearsInOcr(Rule):
    id = "R060"
    severity = Severity.WARN
    description = "The extracted total's digits appear in the raw OCR text."

    def applies(self, r, ctx) -> bool:
        return bool(ctx.ocr_text) and r.totals.total is not None

    def check(self, r, ctx) -> list[Finding]:
        # Compare digit sequences so separator conventions don't matter.
        needle = digits_only(f"{abs(r.totals.total):.2f}")
        haystack = digits_only(ctx.ocr_text)
        if needle and needle in haystack:
            return []
        return [
            self.finding(
                f"The extracted total {m(r.totals.total)} does not appear "
                "anywhere in the independent OCR text layer for this image. This "
                "is a strong signal the value was hallucinated rather than read.",
                field_paths=["totals.total"],
                context={"total": str(r.totals.total)},
                severity=(
                    Severity.ERROR if ctx.config.strict_ocr_grounding else Severity.WARN
                ),
            )
        ]


@register
class MerchantAppearsInOcr(Rule):
    id = "R061"
    severity = Severity.INFO
    description = "The merchant name overlaps the raw OCR text."

    MIN_OVERLAP = 0.6

    def applies(self, r, ctx) -> bool:
        return bool(ctx.ocr_text) and bool((r.merchant.name or "").strip())

    def check(self, r, ctx) -> list[Finding]:
        tokens = set(normalize_desc(r.merchant.name).split())
        if not tokens:
            return []
        haystack = set(normalize_desc(ctx.ocr_text).split())
        overlap = len(tokens & haystack) / len(tokens)
        if overlap >= self.MIN_OVERLAP:
            return []
        return [
            self.finding(
                f"Merchant name {r.merchant.name!r} overlaps the OCR text layer by "
                f"only {overlap:.0%}. It may have been inferred from a logo rather "
                "than read from printed text.",
                field_paths=["merchant.name"],
                context={"name": r.merchant.name, "overlap": overlap},
            )
        ]


# =========================================================================== #
# SELF-CONSISTENCY
# =========================================================================== #


@register
class ConsistencyAgreement(Rule):
    id = "R070"
    severity = Severity.WARN
    description = "Fields that disagreed across repeated extraction runs."

    CRITICAL = ("merchant.name", "receipt.date", "totals.total",
                "totals.subtotal", "totals.tax")

    def applies(self, r, ctx) -> bool:
        return ctx.consistency is not None and bool(ctx.consistency.disputed)

    def check(self, r, ctx) -> list[Finding]:
        c = ctx.consistency
        findings: list[Finding] = []
        critical = [p for p in c.disputed if p in self.CRITICAL]
        other = [p for p in c.disputed if p not in self.CRITICAL]

        for path in critical:
            seen = c.values_by_path.get(path, [])
            agreement = c.agreement.get(path, 0.0)
            findings.append(
                self.finding(
                    f"Critical field {path} was read differently across "
                    f"{c.runs} independent passes (agreement {agreement:.0%}). "
                    f"Values seen: {seen}. Re-read this field carefully; if it is "
                    "genuinely ambiguous, set it to null.",
                    field_paths=[path],
                    context={"path": path, "values": [str(v) for v in seen],
                             "agreement": agreement},
                )
            )

        if other:
            findings.append(
                self.finding(
                    f"{len(other)} further field(s) disagreed across {c.runs} "
                    f"passes: {', '.join(other[:10])}"
                    f"{'...' if len(other) > 10 else ''}.",
                    field_paths=other,
                    context={"paths": other},
                    severity=Severity.INFO,
                )
            )
        return findings
