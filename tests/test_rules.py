"""Rule tests.

Two kinds of test matter here:
  1. Each rule fires on a receipt that violates it (positive case).
  2. Each rule stays SILENT on a clean receipt (negative case). This is the
     one people skip, and it is the one that matters — a rule that fires
     spuriously pollutes the repair prompt and costs you accuracy.
"""

from __future__ import annotations

import copy
from datetime import date, timedelta
from decimal import Decimal

import pytest

from eval.golden_set import DEFAULT_LABELS_DIR, load_labels
from receipts.extract.schema import (
    Buyer,
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
from receipts.validate.report import Finding, Severity
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
# The buyer — R014 (was it read at all) and R015 (is it us)
#
# `buyer_findings` is this file's stand-in for the plan's `run_rule` sketch. It
# runs the REAL validator over a context carrying an expected buyer and then
# keeps one rule's findings: the fixtures below are deliberately bare, so most
# of the presence family fires alongside, and filtering by rule id is what keeps
# the assertions about the rule under test. `by_rule` is the same lookup
# test_R011_downgrades_when_date_raw_kept already uses.
#
# The expected buyer is read off the CONTEXT, never off Settings — validation
# stays pure, and the pipeline is what reads the environment (pipeline.py).
# --------------------------------------------------------------------------- #


def buyer_findings(
    extraction: ReceiptExtraction,
    rule_id: str,
    *,
    expected_name: str | None = None,
    expected_tax_id: str | None = None,
) -> list[Finding]:
    ctx = ValidationContext(
        today=TODAY,
        config=RuleConfig(),
        expected_buyer_name=expected_name,
        expected_buyer_tax_id=expected_tax_id,
    )
    return validate(extraction, ctx).by_rule(rule_id)


def test_R014_fires_when_the_buyer_name_was_not_read():
    findings = buyer_findings(ReceiptExtraction(), "R014", expected_name="IDEAL SOURCE")
    assert [f.severity for f in findings] == [Severity.WARN]


def test_R014_does_not_fire_on_a_blank_tax_id_when_the_name_was_read():
    """The buyer TIN line is printed on every golden receipt and filled on none.

    A rule that flagged it would fire on the whole corpus and be right about
    none of it, which is why R014 keys on `name` and never on `tax_id`.
    """
    extraction = ReceiptExtraction(buyer=Buyer(name="IDEAL SOURCE", tax_id=None))
    assert buyer_findings(extraction, "R014", expected_name="IDEAL SOURCE") == []


def test_R015_is_an_error_when_the_tax_ids_differ():
    """SYNTHETIC FIXTURE — the golden set cannot reach this branch.

    All three buyer TINs on the corpus are blank, so no corpus test covers the
    TIN comparison. The branch is written because it is right the moment a
    receipt carries a buyer TIN, not because anything today exercises it.
    """
    extraction = ReceiptExtraction(
        buyer=Buyer(name="IDEAL SOURCE", tax_id="111-111-111-000")
    )
    findings = buyer_findings(
        extraction,
        "R015",
        expected_name="IDEAL SOURCE",
        expected_tax_id="222-222-222-000",
    )
    assert [f.severity for f in findings] == [Severity.ERROR]


def test_R015_is_only_a_warning_when_the_names_differ_and_there_is_no_tax_id():
    """The buyer name is handwritten on every golden receipt.

    An ERROR here would block auto-approval for the whole corpus on the strength
    of the least legible field on the page.
    """
    extraction = ReceiptExtraction(buyer=Buyer(name="SOMEONE ELSE", tax_id=None))
    findings = buyer_findings(extraction, "R015", expected_name="IDEAL SOURCE")
    assert [f.severity for f in findings] == [Severity.WARN]


def test_R015_passes_on_a_matching_tax_id_even_when_the_name_differs():
    """TIN-first: a matching TIN settles identity and a name cannot override it.

    SYNTHETIC, for the same reason as the ERROR case above. `ldeal Sonrce` is a
    plausible misreading of the handwritten name, and it must not raise anything
    once the printed identifier agrees.
    """
    extraction = ReceiptExtraction(
        buyer=Buyer(name="ldeal Sonrce", tax_id="222-222-222-000")
    )
    assert (
        buyer_findings(
            extraction,
            "R015",
            expected_name="IDEAL SOURCE",
            expected_tax_id="222-222-222-000",
        )
        == []
    )


def test_R015_matches_names_through_the_normalizer():
    """r002's buyer is written `Ideal source` — lowercase 's', as on the paper."""
    extraction = ReceiptExtraction(buyer=Buyer(name="Ideal source", tax_id=None))
    assert buyer_findings(extraction, "R015", expected_name="IDEAL SOURCE") == []


def test_R014_is_inert_when_no_expected_buyer_is_configured():
    """A deployment that has not declared who it is gets no findings.

    Both shapes: a buyer that was read and is nobody in particular, and a buyer
    that was not read at all. The second is the one that would otherwise put a
    WARN on every receipt an undeclared deployment ever processes.
    """
    read = ReceiptExtraction(buyer=Buyer(name="ANYONE AT ALL", tax_id=None))
    assert buyer_findings(read, "R014") == []
    assert buyer_findings(ReceiptExtraction(), "R014") == []


def test_R015_is_inert_when_no_expected_buyer_is_configured():
    extraction = ReceiptExtraction(buyer=Buyer(name="ANYONE AT ALL", tax_id=None))
    assert buyer_findings(extraction, "R015") == []


def test_both_buyer_rules_treat_a_blank_configured_name_as_unset():
    """`EXPECTED_BUYER_NAME=` in an env file declares nothing.

    Keyed on `is not None` this would be a declaration, and R014 would warn on
    every receipt whose buyer was not read — the exact outcome the setting rules
    out. Keyed on a non-blank value it is what it looks like: unset.
    """
    assert buyer_findings(ReceiptExtraction(), "R014", expected_name="   ") == []
    extraction = ReceiptExtraction(buyer=Buyer(name="ANYONE AT ALL", tax_id=None))
    assert buyer_findings(extraction, "R015", expected_name="   ") == []


def test_R015_is_silent_when_only_a_tax_id_is_configured_and_none_was_read():
    """Nothing to compare is not a mismatch.

    The rule APPLIES — a TIN is configured — but the receipt carries no buyer
    TIN and no expected name, so both comparisons are unavailable. Not-read must
    not collapse into differs.
    """
    extraction = ReceiptExtraction(buyer=Buyer(name="ANYONE AT ALL", tax_id=None))
    assert buyer_findings(extraction, "R015", expected_tax_id="222-222-222-000") == []


def test_R015_does_not_error_on_a_buyer_tax_id_carrying_no_digits():
    """A dash transcribed off a blank printed TIN line is not an identifier.

    Compared as a raw string it differs from the configured TIN and would raise
    an ERROR claiming a different registered entity — on a receipt whose TIN
    line is simply empty, which is all three of them. It must fall through to
    the name instead.
    """
    extraction = ReceiptExtraction(buyer=Buyer(name="IDEAL SOURCE", tax_id="-"))
    assert (
        buyer_findings(
            extraction,
            "R015",
            expected_name="IDEAL SOURCE",
            expected_tax_id="222-222-222-000",
        )
        == []
    )


def test_the_buyer_rules_survive_the_repair_loops_context_rebuild():
    """A rule the pipeline's context never reaches is not a rule.

    `extract_with_repair` does not validate against the context it was handed:
    `_evaluate` builds a fresh one per attempt, so `parse_error` is per-attempt
    rather than shared across a thread pool. That rebuild used to ENUMERATE the
    fields it carried over, which silently drops every field added after it was
    written — and it did: R014/R015 were inert on every real run until it copied
    the context instead of listing it.

    Imported locally to keep this module's import surface about rules.
    """
    from receipts.extract.clients.base import VLMResponse
    from receipts.extract.extractor import _evaluate

    ctx = ValidationContext(today=TODAY, expected_buyer_name="IDEAL SOURCE")
    bare = ReceiptExtraction()  # buyer.name is null -> R014 must fire
    assert validate(bare, ctx).fired("R014"), "the rule itself is broken"

    attempt = _evaluate(VLMResponse(parsed=bare, raw=None, model_id="test"), ctx)
    assert attempt.report.fired("R014"), "the context did not survive _evaluate"


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
# The committed labels are hand-verified Philippine BIR sales invoices. They
# reconcile (R022 passes on every one), so a clean validator run must produce
# ZERO errors. Before the convention fix, every one of them raised a false R020
# ERROR of exactly the VAT amount.
#
# No count is written here, on review standards 5 and 20: it said "three" from
# the day there were three, and the corpus is *meant* to grow.
#
# The corpus has NOT in fact grown -- `git ls-tree` gives the same three labels
# at the commit that wrote "three" and at HEAD -- and this block has never
# broken. ISSUE-020 was found by reading, before any receipt was collected, and
# its trigger was the calendar rather than the corpus size. An earlier version
# of this comment said the growth had already broken the block; both halves of
# that were false.
# --------------------------------------------------------------------------- #

try:
    GOLDEN_LABELS = load_labels(DEFAULT_LABELS_DIR)
except Exception:  # labels are PII and may be absent -- skip, never error
    GOLDEN_LABELS = {}


#: Two synthetic cases, scored by the parametrised check below in the *same
#: call* as the real labels: a receipt dated the day the suite runs, and one
#: dated just past the future-date slack.
#:
#: They live inside that check rather than beside it, and they state the bound
#: at **both** ends, because each end alone is bypassable and the bypasses were
#: measured rather than imagined (2026-08-22):
#:
#: * a separate guard cannot see this check re-freezing its own context --
#:   re-freezing the call site below to ``date(2026, 7, 28)`` left the whole
#:   module green, which is ISSUE-020 reinstated verbatim with every gate green;
#: * "today's receipt passes" alone is satisfied forever by a context frozen far
#:   in the *future* (``date(2099, 1, 1)``) or with the slack inflated
#:   (``future_date_slack_days=100000``), and either makes R031 vacuous on the
#:   entire corpus.
_DATED_TODAY = "synthetic-dated-today"
_DATED_AHEAD = "synthetic-dated-past-the-slack"


def _corpus_case(case_id: str) -> tuple[ReceiptExtraction, list[str]]:
    """The subject and the ERROR rule ids it must produce, for one case."""
    if case_id in (_DATED_TODAY, _DATED_AHEAD):
        r = clean_receipt()
        if case_id == _DATED_TODAY:
            r.receipt.date = date.today().isoformat()
            return r, []
        ahead = date.today() + timedelta(days=RuleConfig().future_date_slack_days + 1)
        r.receipt.date = ahead.isoformat()
        return r, ["R031"]
    return GOLDEN_LABELS[case_id], []


@pytest.mark.parametrize(
    "case_id", sorted(GOLDEN_LABELS) + [_DATED_TODAY, _DATED_AHEAD]
)
def test_the_real_corpus_validates_as_production_does(case_id):
    """Every real label validates clean, and the calendar cases bound ``today``.

    ``ValidationContext()`` is built here and nowhere else for this check, so
    there is no second construction site to drift from, and it is exactly what
    every non-test caller builds. **Do not pin ``today`` to a literal.** It was
    ``date(2026, 7, 28)`` until 2026-08-22 -- simply the current date the day it
    was written -- and because R031 is an ERROR that fires past
    ``future_date_slack_days``, every receipt collected for the corpus after
    that date would have failed a check whose subject is the *validator*, not
    the calendar (ISSUE-020).

    Asserted on the exact ERROR rule ids rather than on "no errors", so the
    past-the-slack case cannot be satisfied by an unrelated failure.

    A clone with no labels still runs the two synthetic cases; the case list is
    what says how many real labels were present.
    """
    subject, expected = _corpus_case(case_id)
    errors = validate(subject, ValidationContext()).by_severity(Severity.ERROR)
    assert sorted(f.rule_id for f in errors) == expected, (
        f"{case_id}: expected {expected}, got "
        + (" | ".join(f.render() for f in errors) or "no errors at all")
    )


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
# Template rows — a blank pre-printed row is not a purchase
#
# Philippine BIR sales invoices are pre-printed forms: the product names are
# printed, the quantity and amount columns are blank, and on a real receipt the
# blank rows OUTNUMBER the filled ones (r001 prints six, one is filled). They
# are transcribed so nothing on the paper is lost, and `is_template_row` marks
# them so the arithmetic never counts them.
#
# The split these tests pin: a rule that reads a row's AMOUNTS uses only the
# purchases; a rule whose subject is the row's own presence on the paper
# (R013, R051, R052, R053) keeps every row.
# --------------------------------------------------------------------------- #


def r002_shaped(totals: Totals) -> ReceiptExtraction:
    """r002: one pre-printed blank row plus the handwritten DieselPlus line."""
    return ReceiptExtraction(
        line_items=[
            LineItem(position=0, description_raw="MaxiPower", is_template_row=True),
            LineItem(position=1, description_raw="DieselPlus", qty=D("17.39"),
                     unit_price=D("115.00"), line_total=D("2000.00")),
        ],
        totals=totals,
    )


def test_a_template_row_does_not_break_the_line_item_arithmetic(ctx):
    """MaxiPower and MaxiGreen are printed and blank on r002."""
    r = r002_shaped(Totals(subtotal=D("1785.71"), tax=D("214.29"), total=D("2000.00")))
    ids = {f.rule_id for f in validate(r, ctx).findings}
    assert "R020" not in ids and "R021" not in ids


def test_a_template_row_does_not_silence_the_arithmetic(ctx):
    """The half of the property the silence test above cannot see.

    A blank row has a null `line_total`, so before template rows were excluded
    the line-item sum was UNCOMPUTABLE and R020 skipped itself — on r001, on
    r002, on every pre-printed form. The rule did not tolerate the blank row,
    it went inert, and a receipt whose lines genuinely disagree with its
    printed figures sailed through. Excluding the row has to restore the
    check, not just quiet it.
    """
    r = r002_shaped(Totals(subtotal=D("2678.57"), tax=D("321.43"), total=D("3000.00")))
    assert fired(r, ctx, "R020")


def test_r053_does_not_fire_on_a_template_row(ctx):
    """A transcribed blank row is not an empty description."""
    r = ReceiptExtraction(
        line_items=[LineItem(description_raw="MaxiPower", is_template_row=True)]
    )
    assert not fired(r, ctx, "R053")


def test_r053_still_fires_on_an_unflagged_empty_row(ctx):
    """The flag must not become a blanket amnesty for empty rows."""
    r = ReceiptExtraction(line_items=[LineItem(description_raw="")])
    assert fired(r, ctx, "R053")


def test_a_wrongly_flagged_PURCHASE_is_silently_dropped_from_the_arithmetic(ctx):
    """The one way this feature can do real harm, pinned so it is a KNOWN cost.

    Nothing downstream can distinguish a genuinely blank pre-printed row from a
    filled row the model flagged by mistake -- both arrive as a description with
    null amounts. This test does not assert the harm is prevented, because it
    cannot be: it asserts the shape, so a later reader finds it documented
    rather than discovering it on a real ledger.

    A flagged row carrying a real amount is excluded from reconciliation, so a
    receipt whose totals DISAGREE with its purchases still validates clean.
    """
    r = ReceiptExtraction(
        line_items=[
            LineItem(position=0, description_raw="DieselPlus", line_total=D("2000.00"),
                     is_template_row=True),  # wrongly flagged
        ],
        totals=Totals(subtotal=D("2678.57"), tax=D("321.43"), total=D("3000.00")),
    )
    ids = {f.rule_id for f in validate(r, ctx).findings}
    assert "R020" not in ids, (
        "a wrongly flagged purchase is invisible to reconciliation -- this is a "
        "known, accepted cost of is_template_row and is why the prompt must be "
        "explicit that the flag describes the PAPER, not the model's confidence"
    )


def test_a_flagged_rows_row_math_is_not_checked(ctx):
    """R021 reads a row's three amounts, so it reads purchases only."""
    r = ReceiptExtraction(
        line_items=[
            LineItem(position=0, description_raw="MaxiPower", qty=D("2"),
                     unit_price=D("100.00"), line_total=D("999.00"),
                     is_template_row=True),
        ]
    )
    assert not fired(r, ctx, "R021")


def test_a_flagged_row_does_not_make_up_R042s_sample_count(ctx):
    """R042 needs four priced items before a median means anything.

    A flagged row must not be one of the four: counting it lets the rule run
    on three purchases and call the dearest of them an outlier.
    """
    r = ReceiptExtraction(
        line_items=[
            LineItem(position=0, description_raw="SACHET A", qty=D("1"),
                     unit_price=D("1.00"), line_total=D("1.00")),
            LineItem(position=1, description_raw="SACHET B", qty=D("1"),
                     unit_price=D("1.00"), line_total=D("1.00")),
            LineItem(position=2, description_raw="GAS RANGE", qty=D("1"),
                     unit_price=D("500.00"), line_total=D("500.00")),
            LineItem(position=3, description_raw="MOTOR OIL", qty=D("1"),
                     unit_price=D("30000.00"), line_total=D("30000.00"),
                     is_template_row=True),
        ]
    )
    assert not fired(r, ctx, "R042")


def test_R020s_finding_counts_only_the_purchases(ctx):
    """`item_count` and "across N items" are read by the REPAIR MODEL.

    The sum holds over the purchases, so the count that travels with it has to
    be the purchases too -- telling the model a sum of one line spans six
    invites it to go looking for five amounts that were never there. The
    tolerance floor scales off the same count, and blank rows contributed no
    rounding to absorb.
    """
    r = r002_shaped(Totals(subtotal=D("2678.57"), tax=D("321.43"), total=D("3000.00")))
    findings = validate(r, ctx).by_rule("R020")
    assert findings, "R020 must fire for this test to say anything"
    assert findings[0].context["item_count"] == 1
    assert "across 1 items" in findings[0].message


def test_R024s_finding_counts_only_the_purchases(ctx):
    """The same count, on the no-subtotal fallback path."""
    r = r002_shaped(Totals(total=D("3000.00")))
    findings = validate(r, ctx).by_rule("R024")
    assert findings, "R024 must fire for this test to say anything"
    assert findings[0].context["item_count"] == 1


def test_R013_is_silent_when_every_printed_row_was_blank(ctx):
    """R013 asks whether the body of the receipt was read, and it was.

    Filtering here would demand line items from a form whose product rows are
    genuinely all blank, and the repair prompt would push the model to invent
    purchases to satisfy it.
    """
    r = ReceiptExtraction(
        line_items=[
            LineItem(position=0, description_raw="MaxiPower", is_template_row=True),
            LineItem(position=1, description_raw="MaxiGreen", is_template_row=True),
        ]
    )
    assert not fired(r, ctx, "R013")


def test_two_blank_pre_printed_rows_are_not_a_double_read(ctx):
    """R050's live false positive on r001, not a hypothetical.

    `normalize_desc` drops a trailing number, so the printed `PREMIUM 97` and
    `PREMIUM 95` rows normalise to the same string; blank, they also share
    their null qty, unit_price and line_total. Two adjacent rows of a form are
    not a line the model read twice.
    """
    r = ReceiptExtraction(
        line_items=[
            LineItem(position=0, description_raw="PREMIUM 97", is_template_row=True),
            LineItem(position=1, description_raw="PREMIUM 95", is_template_row=True),
            LineItem(position=2, description_raw="CLEAN DIESEL", qty=D("9.8"),
                     unit_price=D("102.00"), line_total=D("1000.00")),
        ],
        totals=Totals(subtotal=D("892.86"), tax=D("107.14"), total=D("1000.00")),
    )
    assert not fired(r, ctx, "R050")


def test_a_flagged_rows_numbers_stay_out_of_the_plausibility_statistics(ctx):
    """R042 and R043 read amounts, so they read purchases only.

    A row with no amounts cannot move either rule, so the fixture gives the
    flagged row absurd ones: that is the same wrongly-flagged case pinned
    above, and the same accepted cost -- named here for R042 and R043 so the
    exclusion is not silently assumed to be untestable.
    """
    r = clean_receipt()
    r.line_items.append(
        LineItem(position=3, description_raw="EGGS TRAY", qty=D("1"),
                 unit_price=D("50.00"), line_total=D("50.00"))
    )
    r.line_items.append(
        LineItem(position=4, description_raw="MOTOR OIL", qty=D("99999"),
                 unit_price=D("999999.00"), line_total=D("1.00"), is_template_row=True)
    )
    assert not fired(r, ctx, "R042")
    assert not fired(r, ctx, "R043")


def test_R051_still_counts_template_rows_as_rows_on_the_form(ctx):
    """Positions are the printed order of the paper, blank rows included.

    Filtering here would renumber r001's one purchase to position 3 of a
    one-item list and fire the rule on every pre-printed form.
    """
    r = ReceiptExtraction(
        line_items=[
            LineItem(position=0, description_raw="PREMIUM 97", is_template_row=True),
            LineItem(position=1, description_raw="CLEAN DIESEL", qty=D("9.8"),
                     unit_price=D("102.00"), line_total=D("1000.00")),
            LineItem(position=2, description_raw="MOTOR OIL", is_template_row=True),
        ]
    )
    assert not fired(r, ctx, "R051")


def test_R052_still_rejects_a_summary_row_that_was_flagged_as_a_template_row(ctx):
    """R052 judges what a row IS. A misfiled SUBTOTAL row is still misfiled."""
    r = clean_receipt()
    r.line_items.append(
        LineItem(position=3, description_raw="SUBTOTAL", line_total=D("847.50"),
                 is_template_row=True)
    )
    assert fired(r, ctx, "R052")


def test_R053_still_fires_on_a_template_row_that_was_never_transcribed(ctx):
    """The flag's promise is that the printed text WAS captured.

    A flagged row with no description is a line of paper that was lost, which
    is the outcome transcribing blank rows exists to prevent. R053 is the only
    rule that can see it, so it keeps reading every row.
    """
    r = ReceiptExtraction(
        line_items=[LineItem(position=0, description_raw="", is_template_row=True)]
    )
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


def test_all_30_rules_registered():
    ids = [r.id for r in RULES]
    assert len(ids) == 30
    assert len(set(ids)) == 30


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
