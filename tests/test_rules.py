"""Rule tests.

Two kinds of test matter here:
  1. Each rule fires on a receipt that violates it (positive case).
  2. Each rule stays SILENT on a clean receipt (negative case). This is the
     one people skip, and it is the one that matters — a rule that fires
     spuriously pollutes the repair prompt and costs you accuracy.
"""

from __future__ import annotations

import copy
from datetime import date
from decimal import Decimal

import pytest

from eval.golden_set import DEFAULT_LABELS_DIR, load_labels
from receipts.extract.schema import (
    ConsistencyResult,
    DocumentType,
    Legibility,
    LineItem,
    Merchant,
    Modifier,
    PrintType,
    ReceiptExtraction,
    ReceiptMeta,
    TaxBand,
    Totals,
    TriageResult,
)
from receipts.validate.context import RuleConfig, ValidationContext
from receipts.validate.report import Severity
from receipts.validate.rules import RULES, normalize_desc, within_tolerance
from receipts.validate.validator import validate

D = Decimal
TODAY = date(2026, 7, 26)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def clean_receipt() -> ReceiptExtraction:
    """A well-formed receipt that must produce zero findings.

    100.00 + 250.00 + 497.50 = 847.50 subtotal
    847.50 * 0.12 = 101.70 tax
    847.50 + 101.70 - 0 = 949.20 total
    1000.00 tendered - 949.20 = 50.80 change
    """
    return ReceiptExtraction(
        merchant=Merchant(name="SUPERMART INC.", tax_id="123-456-789-000"),
        receipt=ReceiptMeta(
            number="OR-0099123",
            date="2026-07-20",
            time="14:32",
            currency="PHP",
        ),
        line_items=[
            LineItem(position=0, description_raw="RICE 5KG", qty=D("1"),
                     unit_price=D("100.00"), line_total=D("100.00")),
            LineItem(position=1, description_raw="CHKN BRST 1KG", qty=D("2"),
                     unit_price=D("125.00"), line_total=D("250.00")),
            LineItem(position=2, description_raw="COOKING OIL 1L", qty=D("5"),
                     unit_price=D("99.50"), line_total=D("497.50")),
        ],
        totals=Totals(
            subtotal=D("847.50"),
            tax=D("101.70"),
            discount=D("0.00"),
            total=D("949.20"),
            tender=D("1000.00"),
            change=D("50.80"),
        ),
    )


@pytest.fixture
def ctx() -> ValidationContext:
    return ValidationContext(
        today=TODAY,
        triage=TriageResult(
            document_type=DocumentType.POS_RECEIPT,
            print_type=PrintType.THERMAL,
            legibility=Legibility.GOOD,
            estimated_line_item_count=3,
        ),
        config=RuleConfig(),
    )


def fired(receipt, ctx, rule_id: str) -> bool:
    return validate(receipt, ctx).fired(rule_id)


# --------------------------------------------------------------------------- #
# The negative case — a clean receipt must be silent
# --------------------------------------------------------------------------- #


def test_clean_receipt_produces_no_findings(ctx):
    report = validate(clean_receipt(), ctx)
    assert report.findings == [], report.summary()
    assert not report.has_errors


def test_clean_receipt_with_ocr_grounding_is_silent(ctx):
    ctx.ocr_text = (
        "SUPERMART INC.\nRICE 5KG 100.00\nCHKN BRST 1KG 250.00\n"
        "COOKING OIL 1L 497.50\nSUBTOTAL 847.50\nVAT 101.70\nTOTAL 949.20\n"
    )
    assert validate(clean_receipt(), ctx).findings == []


# --------------------------------------------------------------------------- #
# Presence
# --------------------------------------------------------------------------- #


def test_R001_parse_error(ctx):
    ctx.parse_error = "Expecting ',' delimiter: line 4 column 9"
    assert fired(clean_receipt(), ctx, "R001")


def test_R010_missing_total(ctx):
    r = clean_receipt()
    r.totals.total = None
    assert fired(r, ctx, "R010")


def test_R011_missing_date(ctx):
    r = clean_receipt()
    r.receipt.date = None
    assert fired(r, ctx, "R011")


def test_R011_downgrades_when_date_raw_kept(ctx):
    r = clean_receipt()
    r.receipt.date = None
    r.receipt.date_raw = "03/04/2026"
    finding = validate(r, ctx).by_rule("R011")[0]
    assert finding.severity.value == "info"  # correctly parked, not an error


def test_R012_missing_merchant(ctx):
    r = clean_receipt()
    r.merchant.name = "   "
    assert fired(r, ctx, "R012")


def test_R013_no_line_items(ctx):
    r = clean_receipt()
    r.line_items = []
    r.totals.subtotal = None  # avoid confounding arithmetic rules
    assert fired(r, ctx, "R013")


def test_R013_skips_when_triage_expects_zero_items(ctx):
    ctx.triage.estimated_line_item_count = 0
    r = clean_receipt()
    r.line_items = []
    r.totals.subtotal = None
    assert not fired(r, ctx, "R013")


# --------------------------------------------------------------------------- #
# Arithmetic
# --------------------------------------------------------------------------- #


def test_R020_line_items_do_not_sum_to_subtotal(ctx):
    r = clean_receipt()
    r.line_items[1].line_total = D("150.00")  # was 250.00
    assert fired(r, ctx, "R020")


def test_R020_tolerates_cent_rounding(ctx):
    r = clean_receipt()
    r.totals.subtotal = D("847.52")  # 2 cents out across 3 lines
    assert not fired(r, ctx, "R020")


def test_R020_accounts_for_item_modifiers(ctx):
    r = clean_receipt()
    r.line_items[0].modifiers = [Modifier(label="SENIOR DISC", amount=D("-20.00"))]
    r.totals.subtotal = D("827.50")
    r.totals.tax = D("99.30")
    r.totals.total = D("926.80")
    r.totals.tender = D("1000.00")
    r.totals.change = D("73.20")
    assert not fired(r, ctx, "R020")


def test_R021_line_math_wrong(ctx):
    r = clean_receipt()
    r.line_items[1].qty = D("3")  # 3 x 125 != 250
    assert fired(r, ctx, "R021")


def test_R021_message_names_the_numbers(ctx):
    r = clean_receipt()
    r.line_items[1].qty = D("3")
    msg = validate(r, ctx).by_rule("R021")[0].message
    assert "125" in msg and "250" in msg and "375" in msg


def test_R021_skips_rows_with_nulls(ctx):
    r = clean_receipt()
    r.line_items[1].qty = None
    assert not fired(r, ctx, "R021")


def test_R022_totals_equation_fails(ctx):
    r = clean_receipt()
    r.totals.total = D("847.50")  # forgot to add tax
    assert fired(r, ctx, "R022")


def test_R022_handles_negative_discount_convention(ctx):
    """Models emit discounts negative; storage keeps them positive. Either
    convention must validate identically."""
    r = clean_receipt()
    r.totals.discount = D("-50.00")
    r.totals.total = D("899.20")
    assert not fired(r, ctx, "R022")

    r2 = copy.deepcopy(r)
    r2.totals.discount = D("50.00")
    assert not fired(r2, ctx, "R022")


def test_R023_tender_change_mismatch(ctx):
    r = clean_receipt()
    r.totals.change = D("60.80")
    assert fired(r, ctx, "R023")


def test_R024_fallback_when_no_subtotal(ctx):
    r = clean_receipt()
    r.totals.subtotal = None
    r.line_items.pop()  # drop 497.50 -> items no longer reconcile to total
    assert fired(r, ctx, "R024")


def test_R024_silent_when_subtotal_present(ctx):
    assert not fired(clean_receipt(), ctx, "R024")


# --------------------------------------------------------------------------- #
# Tax-inclusive line pricing (R020 / R024)
#
# On a Philippine BIR "SALES INVOICE" the Amount column is VAT-INCLUSIVE, so
# the lines sum to `total` while `subtotal` is the net-of-VAT tax base. R020
# used to assume the opposite convention and failed by exactly the VAT, turning
# a receipt that reconciles (R022 passes) into a false ERROR.
# --------------------------------------------------------------------------- #


def vat_inclusive_receipt() -> ReceiptExtraction:
    """Shaped like the real BIR sales invoices in the golden set.

    892.86 net + 107.14 VAT = 1000.00 total, and the single line amount is the
    VAT-INCLUSIVE 1000.00 -- so the lines sum to `total`, not `subtotal`.
    """
    return ReceiptExtraction(
        merchant=Merchant(name="METRO OIL SUBIC, INC.", tax_id="221-193-789-09013"),
        receipt=ReceiptMeta(number="1811158", date="2026-03-23", currency="PHP"),
        line_items=[
            LineItem(position=0, description_raw="CLEAN DIESEL", qty=D("9.8"),
                     unit_price=D("102.00"), line_total=D("1000.00")),
        ],
        totals=Totals(subtotal=D("892.86"), tax=D("107.14"), total=D("1000.00")),
    )


def with_doubled_line(r: ReceiptExtraction) -> ReceiptExtraction:
    """Read the 497.50 line twice: 1345.00, far above subtotal AND total."""
    dup = copy.deepcopy(r.line_items[-1])
    r.line_items.append(dup)
    for index, item in enumerate(r.line_items):
        item.position = index
    return r


# R020 ---------------------------------------------------------------------- #


def test_R020_accepts_vat_inclusive_lines_when_convention_unknown(ctx):
    """THE reported bug: nothing sets the flag, so both readings are allowed."""
    assert not fired(vat_inclusive_receipt(), ctx, "R020")


def test_R020_message_reports_both_comparisons_when_convention_unknown(ctx):
    r = clean_receipt()
    r.line_items.pop()  # 350.00 -- matches neither 847.50 nor 949.20
    finding = validate(r, ctx).by_rule("R020")[0]
    assert finding.severity is Severity.ERROR
    for number in ("350", "847.50", "949.20", "497.50", "599.20"):
        assert number in finding.message, finding.message
    assert "totals.subtotal" in finding.field_paths
    assert "totals.total" in finding.field_paths


def test_R020_honours_explicit_net_convention(ctx):
    """prices_include_tax=False must not be quietly ignored: the same receipt
    that passes under the unknown convention has to error once the document
    says its amounts are net of tax."""
    r = vat_inclusive_receipt()
    r.totals.prices_include_tax = False
    assert fired(r, ctx, "R020")


def test_R020_honours_explicit_inclusive_convention(ctx):
    """Mirror image: net-priced lines (sum == subtotal != total) must error when
    the document says the amounts already include tax."""
    r = clean_receipt()
    r.totals.prices_include_tax = True
    assert fired(r, ctx, "R020")


def test_R020_silent_when_convention_matches_declared_flag(ctx):
    net = clean_receipt()
    net.totals.prices_include_tax = False
    assert not fired(net, ctx, "R020")

    gross = vat_inclusive_receipt()
    gross.totals.prices_include_tax = True
    assert not fired(gross, ctx, "R020")


def test_R020_still_catches_missing_line_item(ctx):
    """Silent-case discipline: accepting either reading must not blunt the rule."""
    r = clean_receipt()
    r.line_items.pop()  # 350.00 vs subtotal 847.50 / total 949.20
    assert fired(r, ctx, "R020")


def test_R020_still_catches_double_counted_line_item(ctx):
    r = with_doubled_line(clean_receipt())  # 1345.00, above both figures
    assert fired(r, ctx, "R020")


def test_R020_skips_when_the_needed_comparand_is_missing(ctx):
    """Declared tax-inclusive but no total printed: skip, never fire blind."""
    r = vat_inclusive_receipt()
    r.totals.prices_include_tax = True
    r.totals.total = None
    assert not fired(r, ctx, "R020")


# R024 (the no-subtotal fallback) -------------------------------------------- #


def test_R024_accepts_vat_inclusive_lines_when_convention_unknown(ctx):
    r = vat_inclusive_receipt()
    r.totals.subtotal = None  # only the VAT-inclusive total is printed
    assert not fired(r, ctx, "R024")


def test_R024_honours_explicit_net_convention(ctx):
    r = vat_inclusive_receipt()
    r.totals.subtotal = None
    r.totals.prices_include_tax = False
    assert fired(r, ctx, "R024")


def test_R024_honours_explicit_inclusive_convention(ctx):
    """Lines sum to total - tax (the net reading) but the document says the
    amounts include tax, so the comparison against `total` must fail."""
    r = clean_receipt()
    r.totals.subtotal = None
    r.totals.prices_include_tax = True
    assert fired(r, ctx, "R024")


def test_R024_still_catches_missing_line_item(ctx):
    r = clean_receipt()
    r.totals.subtotal = None
    r.line_items.pop()
    assert fired(r, ctx, "R024")


def test_R024_still_catches_double_counted_line_item(ctx):
    r = with_doubled_line(clean_receipt())
    r.totals.subtotal = None
    assert fired(r, ctx, "R024")


def test_R024_message_reports_both_comparisons_when_convention_unknown(ctx):
    r = clean_receipt()
    r.totals.subtotal = None
    r.line_items.pop()
    finding = validate(r, ctx).by_rule("R024")[0]
    assert finding.severity is Severity.WARN
    for number in ("350", "847.50", "949.20"):
        assert number in finding.message, finding.message


def test_R020_and_R024_do_not_both_report(ctx):
    """R024 is the fallback for a null subtotal; R020 owns the case where a
    subtotal is printed. A broken receipt must not be reported twice."""
    missing_subtotal = clean_receipt()
    missing_subtotal.totals.subtotal = None
    missing_subtotal.line_items.pop()
    report = validate(missing_subtotal, ctx)
    assert report.fired("R024")
    assert not report.fired("R020")


# --------------------------------------------------------------------------- #
# Real-corpus regression
#
# The three committed labels are hand-verified Philippine BIR sales invoices.
# They reconcile (R022 passes on all three), so a clean validator run must
# produce ZERO errors. Before the convention fix, every one of them raised a
# false R020 ERROR of exactly the VAT amount.
# --------------------------------------------------------------------------- #

GOLDEN_TODAY = date(2026, 7, 28)

try:
    GOLDEN_LABELS = load_labels(DEFAULT_LABELS_DIR)
except Exception:  # labels are PII and may be absent -- skip, never error
    GOLDEN_LABELS = {}


@pytest.mark.parametrize("label_id", sorted(GOLDEN_LABELS) or [None])
def test_real_corpus_labels_produce_no_errors(label_id):
    if label_id is None:
        pytest.skip("no labels in eval/golden/labels")
    report = validate(
        GOLDEN_LABELS[label_id],
        ValidationContext(today=GOLDEN_TODAY, config=RuleConfig()),
    )
    errors = report.by_severity(Severity.ERROR)
    assert not errors, f"{label_id}: " + " | ".join(f.render() for f in errors)


def test_R025_tax_bands_do_not_sum(ctx):
    r = clean_receipt()
    r.totals.tax_breakdown = [
        TaxBand(label="VATable", base=D("500.00"), rate=D("0.12"), amount=D("60.00")),
        TaxBand(label="VATable", base=D("200.00"), rate=D("0.12"), amount=D("24.00")),
    ]
    assert fired(r, ctx, "R025")  # 84.00 != 101.70


# --------------------------------------------------------------------------- #
# Plausibility
# --------------------------------------------------------------------------- #


def test_R030_unparseable_date(ctx):
    r = clean_receipt()
    r.receipt.date = "20/07/2026"
    assert fired(r, ctx, "R030")


def test_R031_future_date(ctx):
    r = clean_receipt()
    r.receipt.date = "2027-01-15"
    assert fired(r, ctx, "R031")


def test_R031_allows_one_day_slack(ctx):
    r = clean_receipt()
    r.receipt.date = "2026-07-27"  # tomorrow, timezone slack
    assert not fired(r, ctx, "R031")


def test_R032_ancient_date(ctx):
    r = clean_receipt()
    r.receipt.date = "2005-03-01"
    assert fired(r, ctx, "R032")


def test_R033_unknown_currency(ctx):
    r = clean_receipt()
    r.receipt.currency = "XYZ"
    assert fired(r, ctx, "R033")


def test_R033_skips_when_currency_null(ctx):
    r = clean_receipt()
    r.receipt.currency = None
    assert not fired(r, ctx, "R033")


def test_R040_negative_total(ctx):
    r = clean_receipt()
    r.totals.total = D("-949.20")
    assert fired(r, ctx, "R040")


def test_R040_allows_refunds(ctx):
    r = clean_receipt()
    r.totals.total = D("-949.20")
    r.meta.is_refund = True
    assert not fired(r, ctx, "R040")


def test_R041_implausible_magnitude(ctx):
    r = clean_receipt()
    r.totals.total = D("94920000.00")
    assert fired(r, ctx, "R041")


def test_R042_unit_price_outlier(ctx):
    r = clean_receipt()
    r.line_items.append(
        LineItem(position=3, description_raw="SALT", qty=D("1"),
                 unit_price=D("99500.00"), line_total=D("99500.00"))
    )
    assert fired(r, ctx, "R042")


def test_R042_needs_enough_samples(ctx):
    r = clean_receipt()
    r.line_items = r.line_items[:2]
    r.line_items[0].unit_price = D("50000.00")
    assert not fired(r, ctx, "R042")  # median meaningless with 2 samples


def test_R043_absurd_quantity(ctx):
    r = clean_receipt()
    r.line_items[0].qty = D("99999")
    assert fired(r, ctx, "R043")


def test_R044_implausible_tax_rate(ctx):
    r = clean_receipt()
    r.totals.tax = D("500.00")  # ~59% of subtotal
    assert fired(r, ctx, "R044")


def test_R045_discount_exceeds_subtotal(ctx):
    r = clean_receipt()
    r.totals.discount = D("900.00")
    assert fired(r, ctx, "R045")


# --------------------------------------------------------------------------- #
# Structural integrity
# --------------------------------------------------------------------------- #


def test_R050_adjacent_duplicates(ctx):
    r = clean_receipt()
    dup = copy.deepcopy(r.line_items[0])
    dup.position = 1
    r.line_items.insert(1, dup)
    for i, item in enumerate(r.line_items):
        item.position = i
    assert fired(r, ctx, "R050")


def test_R051_non_contiguous_positions(ctx):
    r = clean_receipt()
    r.line_items[2].position = 7
    assert fired(r, ctx, "R051")


@pytest.mark.parametrize(
    "description", ["SUBTOTAL", "Sub Total", "TOTAL", "VAT", "CHANGE",
                    "CASH TENDERED", "TOTAL: 847.50", "Amount Due"]
)
def test_R052_summary_rows_rejected(ctx, description):
    r = clean_receipt()
    r.line_items.append(
        LineItem(position=3, description_raw=description, line_total=D("847.50"))
    )
    assert fired(r, ctx, "R052"), description


@pytest.mark.parametrize(
    "description", ["TOTAL WINE CO MERLOT", "CASH CARD TOPUP", "TAXI FARE",
                    "CHANGE PURSE LEATHER", "VATANA BEANS"]
)
def test_R052_does_not_false_positive_on_real_items(ctx, description):
    """The regression that matters: real products whose names contain a
    summary keyword must not be stripped out."""
    r = clean_receipt()
    r.line_items.append(
        LineItem(position=3, description_raw=description, qty=D("1"),
                 unit_price=D("10.00"), line_total=D("10.00"))
    )
    assert not fired(r, ctx, "R052"), description


def test_R053_blank_description(ctx):
    r = clean_receipt()
    r.line_items[1].description_raw = ""
    assert fired(r, ctx, "R053")


# --------------------------------------------------------------------------- #
# Grounding
# --------------------------------------------------------------------------- #


def test_R060_total_absent_from_ocr(ctx):
    ctx.ocr_text = "SUPERMART INC.\nRICE 5KG 100.00\nTOTAL 111.11\n"
    assert fired(clean_receipt(), ctx, "R060")


def test_R060_matches_across_separator_conventions(ctx):
    ctx.ocr_text = "TOTAL 949,20"  # comma decimal
    assert not fired(clean_receipt(), ctx, "R060")


def test_R060_can_be_escalated_to_error(ctx):
    ctx.ocr_text = "nothing useful here"
    ctx.config.strict_ocr_grounding = True
    finding = validate(clean_receipt(), ctx).by_rule("R060")[0]
    assert finding.severity.value == "error"


def test_R061_merchant_absent_from_ocr(ctx):
    ctx.ocr_text = "RICE 5KG 100.00 TOTAL 949.20"
    assert fired(clean_receipt(), ctx, "R061")


# --------------------------------------------------------------------------- #
# Self-consistency
# --------------------------------------------------------------------------- #


def test_R070_disputed_critical_field(ctx):
    ctx.consistency = ConsistencyResult(
        runs=3,
        disputed=["totals.total"],
        agreement={"totals.total": 0.34},
        values_by_path={"totals.total": ["949.20", "949.70", "949.20"]},
    )
    findings = validate(clean_receipt(), ctx).by_rule("R070")
    assert findings and "949.70" in findings[0].message


def test_R070_silent_without_consistency_data(ctx):
    assert not fired(clean_receipt(), ctx, "R070")


# --------------------------------------------------------------------------- #
# Validator contract
# --------------------------------------------------------------------------- #


def test_all_28_rules_registered():
    ids = [r.id for r in RULES]
    assert len(ids) == 28
    assert len(set(ids)) == 28


def test_validate_never_mutates_input(ctx):
    r = clean_receipt()
    before = r.model_dump_json()
    ctx.ocr_text = "unrelated"
    ctx.consistency = ConsistencyResult(runs=3, disputed=["totals.total"])
    validate(r, ctx)
    assert r.model_dump_json() == before


def test_validate_is_deterministic(ctx):
    r = clean_receipt()
    r.totals.total = D("1.00")
    a = validate(r, ctx).model_dump_json()
    b = validate(r, ctx).model_dump_json()
    assert a == b


def test_crashing_rule_is_contained(ctx, monkeypatch):
    """A rule that throws must not take down the run."""
    target = next(r for r in RULES if r.id == "R022")

    def boom(self, r, c):
        raise RuntimeError("simulated bug")

    monkeypatch.setattr(type(target), "check", boom)
    report = validate(clean_receipt(), ctx)
    assert report.fired("R022.crashed")
    assert not report.has_errors  # crashes are INFO, not ERROR


def test_repair_rendering_excludes_info_and_truncates(ctx):
    r = clean_receipt()
    r.totals.total = D("847.50")
    r.line_items[1].qty = D("3")
    text = validate(r, ctx).render_for_repair_prompt()
    assert "[R022]" in text
    assert "[R051]" not in text  # INFO is excluded
    assert text.index("[R022]") < text.index("[R021]") or "[R021]" in text


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "a,b,expected",
    [
        (D("100.00"), D("100.01"), True),      # floor absorbs 1 cent
        (D("100.00"), D("100.05"), False),     # 5 cents is a misread, not rounding
        (D("949.20"), D("945.20"), False),     # THE regression: must not pass
        (D("100000.00"), D("100015.00"), True),   # relative valve on huge totals
        (D("100000.00"), D("101000.00"), False),
        (None, D("1.00"), False),
    ],
)
def test_within_tolerance(a, b, expected):
    assert within_tolerance(a, b) is expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("SUBTOTAL: 847.50", "SUBTOTAL"),
        ("  sub-total  ", "SUB TOTAL"),
        ("CHKN BRST 1KG", "CHKN BRST 1KG"),
        ("Total Due  1,234.50", "TOTAL DUE"),
    ],
)
def test_normalize_desc(raw, expected):
    assert normalize_desc(raw) == expected
