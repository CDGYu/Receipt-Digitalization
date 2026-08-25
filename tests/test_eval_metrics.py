"""Eval metrics + harness tests. Pure and offline — synthetic fixtures only,
no golden data, no network. The pipeline is a stub callable."""

from __future__ import annotations

import json
from decimal import Decimal as D

import pytest

from eval.harness import run_eval
from eval.metrics import (
    EvalReport,
    EvalResult,
    FieldBreakdown,
    calibration_curve,
    critical_field_accuracy,
    field_accuracy,
    field_breakdown,
    line_item_f1,
    wilson_interval,
)
from receipts.extract.schema import (
    LineItem,
    Merchant,
    ReceiptExtraction,
    ReceiptMeta,
    TaxBand,
    Totals,
)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def _items() -> list[LineItem]:
    return [
        LineItem(position=0, description_raw="RICE 5KG", qty=D("1"),
                 unit_price=D("100.00"), line_total=D("100.00")),
        LineItem(position=1, description_raw="COOKING OIL 1L", qty=D("2"),
                 unit_price=D("50.00"), line_total=D("100.00")),
        LineItem(position=2, description_raw="EGGS DOZEN", qty=D("1"),
                 unit_price=D("80.00"), line_total=D("80.00")),
    ]


def _extraction(
    *,
    total: str | None = "224.00",
    name: str = "SUPERMART INC.",
    date: str = "2026-07-20",
    items: list[LineItem] | None = None,
) -> ReceiptExtraction:
    return ReceiptExtraction(
        merchant=Merchant(name=name),
        receipt=ReceiptMeta(date=date, currency="PHP"),
        line_items=_items() if items is None else items,
        totals=Totals(subtotal=D("200.00"), tax=D("24.00"), discount=D("0.00"),
                      total=D(total) if total is not None else None),
    )


# --------------------------------------------------------------------------- #
# field_accuracy
# --------------------------------------------------------------------------- #


def test_field_accuracy_total_within_floor_is_true():
    acc = field_accuracy(_extraction(total="949.20"), _extraction(total="949.21"))
    assert acc["totals.total"] is True


def test_field_accuracy_total_beyond_tolerance_is_false():
    acc = field_accuracy(_extraction(total="949.20"), _extraction(total="945.20"))
    assert acc["totals.total"] is False


def test_field_accuracy_text_is_case_and_whitespace_insensitive():
    acc = field_accuracy(
        _extraction(name="Supermart   Inc."), _extraction(name="SUPERMART INC.")
    )
    assert acc["merchant.name"] is True


def test_field_accuracy_none_equals_none():
    acc = field_accuracy(_extraction(total=None), _extraction(total=None))
    assert acc["totals.total"] is True


def test_field_accuracy_path_present_in_one_only_is_false():
    both_items = _items()
    predicted = _extraction(items=both_items)
    truth = _extraction(items=both_items[:2])  # one fewer line item
    acc = field_accuracy(predicted, truth)
    assert acc["line_items[2].line_total"] is False


# --------------------------------------------------------------------------- #
# field_breakdown
# --------------------------------------------------------------------------- #


def test_breakdown_counts_a_filled_truth_path_as_transcription():
    bd = field_breakdown(_extraction(), _extraction())
    # merchant.name, receipt.date, totals.total ... are all filled in truth.
    assert bd.transcription_total > 0
    assert bd.transcription_correct == bd.transcription_total


def test_breakdown_never_counts_an_empty_truth_path_as_transcription():
    # receipt.cashier is None in both fixtures: absent, not transcription.
    bd = field_breakdown(_extraction(), _extraction())
    assert bd.correctly_empty > 0
    assert bd.hallucinated == 0


def test_breakdown_puts_meta_paths_in_self_report_not_transcription():
    bd = field_breakdown(_extraction(), _extraction())
    assert bd.self_report_total > 0


def test_breakdown_classifies_an_unseen_meta_field_by_its_prefix():
    """A meta path the classifier has never been told about still lands in
    self_report. The prefix half of the grouping is what this pins: a `meta`
    field added to the schema next year needs no edit here (review standard
    19). The self-reports that do not live under `meta.` are a separate,
    declared set and are pinned separately -- the old name for this test said
    "not by a list of names", which stopped being true of the module when that
    set was introduced."""
    from eval.metrics import _group

    assert _group("meta.some_field_added_next_year") == "self_report"
    assert _group("line_items[7].qty") == "line_items"
    assert _group("line_items") == "line_items"
    assert _group("totals.total") == "core"


def test_the_grouping_reads_the_declared_leaf_set_rather_than_names_of_its_own():
    """The self-report leaves outside ``meta.`` are declared once and looked up.

    Driven by the set itself, not by a name spelled here: an implementation
    that hard-codes ``path.endswith(".is_template_row")`` passes today and
    fails the moment the set gains a second member, which is the difference
    between one declaration and an enumeration growing in two places.
    """
    from eval.metrics import _SELF_REPORT_LEAVES, _group

    # Without this the loop below passes vacuously on an empty set.
    assert _SELF_REPORT_LEAVES

    for leaf in _SELF_REPORT_LEAVES:
        assert _group(f"line_items[3].{leaf}") == "self_report"
        assert _group(f"totals.{leaf}") == "self_report"


def test_is_template_row_is_scored_as_a_self_report_not_a_transcription() -> None:
    """A False-defaulting bool in an averaged group is a free point per row.

    Measured before this routing existed: a prediction that got r001's row
    count right and read nothing scored 2/17, and adding this one field alone
    took it to 3/18.
    """
    one = _extraction(items=[LineItem(position=0, description_raw="CLEAN DIESEL")])
    two = _extraction(items=[LineItem(position=0, description_raw="CLEAN DIESEL"),
                             LineItem(position=1, description_raw="PREMIUM 97")])

    # The defect scales at one free point per row, so the per-row delta is
    # what this pins -- not a whole-receipt total that shifts for other reasons.
    per_row = (field_breakdown(two, two).line_items_total
               - field_breakdown(one, one).line_items_total)

    # Measured on 2026-08-18, both numbers read off the failing assertion.
    # Before the routing: per_row 3 (position, description_raw, is_template_row)
    # and self_report_total 4 (the four meta.* bools/enums at their defaults).
    assert per_row == 2
    assert field_breakdown(one, one).self_report_total == 5


def test_breakdown_counts_an_invented_value_as_hallucination():
    truth = _extraction()
    predicted = _extraction()
    predicted.receipt.cashier = "MARIA"   # truth leaves this None
    bd = field_breakdown(predicted, truth)
    assert bd.hallucinated == 1


def test_breakdown_treats_an_empty_container_as_absent():
    """flatten emits ``[]`` as a leaf on purpose, so "had none" stays visible.
    But a receipt whose tax_breakdown is empty has no tax breakdown to read, so
    it must not be a point a model can earn.

    Differential, not introspective: it compares two truths differing only in
    that one field. A test that asked the classifier which paths it counted
    would mirror the rule under test and could never fail.

    Measured: core_total is 8 with the empty container and 11 with one band
    (label/base/rate/amount, of which base is None).
    """
    empty_truth = _extraction()
    filled_truth = _extraction()
    filled_truth.totals.tax_breakdown = [
        TaxBand(label="VAT", rate=D("0.12"), amount=D("24.00"))
    ]

    bd_empty = field_breakdown(_extraction(), empty_truth)
    bd_filled = field_breakdown(_extraction(), filled_truth)

    assert bd_empty.core_total < bd_filled.core_total


def test_breakdown_an_extra_predicted_row_is_hallucination_not_a_miss():
    both = _items()
    extra = LineItem(position=3, description_raw="ZZZ NOVELTY WIDGET",
                     qty=D("1"), unit_price=D("5.00"), line_total=D("5.00"))
    bd = field_breakdown(_extraction(items=both + [extra]), _extraction(items=both))
    # The invented row's paths are absent in truth, so they are hallucination.
    assert bd.hallucinated > 0


_Sides = tuple[ReceiptExtraction, ReceiptExtraction]


def _an_invented_row() -> _Sides:
    """Prediction-only paths: a line-item row the truth does not have.

    The invented row contributes sub-paths that exist on the prediction side
    only and are empty there (a row's ``sku``/``bbox``/``modifiers`` default to
    nothing), so ``_is_filled`` reads "empty" on both sides while
    ``field_accuracy`` scores them ``False`` for being present on one side only.
    """
    both = _items()
    extra = LineItem(position=3, description_raw="ZZZ NOVELTY WIDGET",
                     qty=D("1"), unit_price=D("5.00"), line_total=D("5.00"))
    return _extraction(items=both + [extra]), _extraction(items=both)


def _a_row_never_produced() -> _Sides:
    """Truth-only paths: the same shape from the other side.

    Kept as its own case because the two directions are not interchangeable.
    Measured: a partial revert reading
    ``elif ok or (path in tru and path not in pred)`` — which re-admits exactly
    the truth-only paths, and so re-admits three of the four the original defect
    was reported on — leaves a prediction-only fixture, and the floor pin,
    entirely green.
    """
    both = _items()
    return _extraction(items=both[:2]), _extraction(items=both)


def _an_empty_list_against_a_null() -> _Sides:
    """Neither direction: the same path on both sides, ``[]`` here, ``None`` there.

    ``LineItem.bbox`` is typed ``list[float] | None``, so both values are legal
    on one path. Neither is filled, both sides carry the path, and
    ``_values_equal([], None)`` is ``False`` — so this reaches the residue
    without anybody disagreeing about which paths *exist*. It is the case that
    keeps the class's description honest.
    """
    truth_items = _items()
    truth_items[0].bbox = []
    predicted_items = _items()          # bbox defaults to None
    return _extraction(items=predicted_items), _extraction(items=truth_items)


#: Every shape that reaches ``structural_mismatch``. Both pins run over all of
#: them: a fixture covering one direction leaves a one-directional revert green.
_DISAGREEING_SIDES = [
    _an_invented_row,
    _a_row_never_produced,
    _an_empty_list_against_a_null,
]


@pytest.mark.parametrize("case", _DISAGREEING_SIDES, ids=lambda f: f.__name__)
def test_no_class_named_for_agreement_holds_a_path_scored_wrong(case):
    """``correctly_empty`` may not contain a path ``field_accuracy`` calls wrong.

    Checked as an identity against the per-path map rather than by re-deriving
    the classifier's own membership rule, which would mirror the code under
    test and could never fail: the paths the map scores ``True`` are exactly
    the ones that may land in a *correct* bucket, and there are only three such
    buckets. ``hallucinated`` and ``structural_mismatch`` are named for
    disagreement, so a ``True`` path hiding in either would break the identity
    from the other side.

    Measured before the fix, on ``eval/golden/labels/r001.json`` scored against
    an empty extraction: 4 of the 18 paths counted as ``correctly_empty`` were
    scored ``False`` by the same map the harness commits to the artefact.
    """
    predicted, truth = case()
    acc = field_accuracy(predicted, truth)
    bd = field_breakdown(predicted, truth)

    assert (
        bd.transcription_correct + bd.self_report_correct + bd.correctly_empty
    ) == sum(acc.values())

    # Without this the identity above is vacuous: on a fixture where nothing
    # falls in the residue, the old membership rule satisfies it too.
    assert bd.structural_mismatch > 0


@pytest.mark.parametrize("case", _DISAGREEING_SIDES, ids=lambda f: f.__name__)
def test_the_classes_tile_the_path_set(case):
    """Every path lands in exactly one class, and none is dropped.

    The bound on ``correctly_empty`` is only safe if the paths it sheds have
    somewhere to go; this is the half that says they were not simply discarded.
    ``len(acc)`` is the old every-path denominator, so the sum also shows the
    classifier still accounts for the whole path set it replaced.
    """
    predicted, truth = case()
    acc = field_accuracy(predicted, truth)
    bd = field_breakdown(predicted, truth)

    assert (
        bd.transcription_total
        + bd.self_report_total
        + bd.hallucinated
        + bd.correctly_empty
        + bd.structural_mismatch
    ) == len(acc)


def test_breakdown_sums_with_plus():
    # Sides that disagree, so every class carries a nonzero value: on two
    # identical extractions `structural_mismatch` is 0, and `0 == 0 * 2` holds
    # under any mutation of `__add__` at all (review standard 14).
    predicted, truth = _an_invented_row()
    a = field_breakdown(predicted, truth)
    b = field_breakdown(predicted, truth)
    total = a + b
    assert total.transcription_total == a.transcription_total * 2
    assert total.correctly_empty == a.correctly_empty * 2
    # Every field folds, including the ones added after `__add__` was written:
    # it builds from `fields(self)` rather than a list of names.
    assert a.structural_mismatch > 0
    assert total.structural_mismatch == a.structural_mismatch * 2


def test_ratio_is_none_on_an_empty_denominator_never_zero():
    from eval.metrics import ratio

    assert ratio(0, 0) is None
    assert ratio(0, 4) == 0.0
    assert ratio(1, 4) == 0.25


# --------------------------------------------------------------------------- #
# line_item_f1
# --------------------------------------------------------------------------- #


def test_line_item_f1_identical_lists_is_perfect():
    items = _items()
    assert line_item_f1(items, items) == (1.0, 1.0, 1.0)


def test_line_item_f1_extra_predicted_row_lowers_precision_only():
    truth = _items()
    extra = LineItem(position=3, description_raw="ZZZ NOVELTY WIDGET",
                     qty=D("1"), unit_price=D("5.00"), line_total=D("5.00"))
    precision, recall, _f1 = line_item_f1(truth + [extra], truth)
    assert recall == 1.0
    assert precision < 1.0


def test_line_item_f1_empty_lists_are_zero_not_crash():
    assert line_item_f1([], []) == (0.0, 0.0, 0.0)


# --------------------------------------------------------------------------- #
# critical_field_accuracy
# --------------------------------------------------------------------------- #


def test_critical_field_accuracy_all_correct():
    assert critical_field_accuracy(_extraction(), _extraction()) is True


def test_critical_field_accuracy_wrong_total_is_false():
    assert critical_field_accuracy(
        _extraction(total="224.00"), _extraction(total="999.00")
    ) is False


def test_critical_field_accuracy_wrong_date_is_false():
    assert critical_field_accuracy(
        _extraction(date="2026-07-20"), _extraction(date="2026-01-01")
    ) is False


def test_critical_field_accuracy_both_null_total_agrees():
    # Two null totals agree, consistent with the date field's null==null.
    assert critical_field_accuracy(
        _extraction(total=None), _extraction(total=None)
    ) is True


def test_critical_field_accuracy_one_null_total_is_false():
    # A null total against a real one is still a mismatch, not agreement.
    assert critical_field_accuracy(
        _extraction(total="224.00"), _extraction(total=None)
    ) is False


# --------------------------------------------------------------------------- #
# calibration_curve
# --------------------------------------------------------------------------- #


def test_calibration_curve_rate_is_monotonic_and_high_conf_error_hurts_precision():
    results = [
        EvalResult(receipt_id="a", confidence=D("0.95"), critical_correct=True,
                   field_acc={}),
        EvalResult(receipt_id="b", confidence=D("0.97"), critical_correct=False,
                   field_acc={}),
        EvalResult(receipt_id="c", confidence=D("0.50"), critical_correct=True,
                   field_acc={}),
    ]
    curve = calibration_curve(results)

    # auto-approve rate never increases as the threshold rises
    rates = [rate for _thr, rate, _prec in curve]
    assert all(a >= b for a, b in zip(rates, rates[1:]))

    # at 0.95 both a and b are approved; b is wrong -> precision drops below 1.0
    at_095 = [prec for thr, _rate, prec in curve if thr == D("0.95")]
    assert at_095 and at_095[0] < 1.0

    # nothing approved above the top confidence -> precision defined as 1.0
    at_100 = [prec for thr, _rate, prec in curve if thr == D("1.0")]
    assert at_100 and at_100[0] == 1.0


# --------------------------------------------------------------------------- #
# run_eval (harness)
# --------------------------------------------------------------------------- #


def test_run_eval_counts_and_writes_results_file(tmp_path):
    golden = tmp_path / "golden"
    labels = golden / "labels"
    labels.mkdir(parents=True)

    truth1 = _extraction(total="224.00")
    truth2 = _extraction(total="500.00", name="OTHER STORE")
    (labels / "r1.json").write_text(truth1.model_dump_json(), encoding="utf-8")
    (labels / "r2.json").write_text(truth2.model_dump_json(), encoding="utf-8")

    def pipeline_fn(path):
        if path.stem == "r1":
            return _extraction(total="224.00"), D("0.95")          # correct
        return _extraction(total="499.00", name="OTHER STORE"), D("0.90")  # wrong total

    results_dir = tmp_path / "results"
    report = run_eval(golden, pipeline_fn, results_dir=results_dir)

    assert isinstance(report, EvalReport)
    assert report.n_receipts == 2
    assert report.n_auto_approved == 2          # both >= 0.85
    assert report.n_critical_correct == 1       # only r1 fully correct
    assert report.auto_approval_rate == 1.0
    assert report.auto_approval_precision == 0.5

    written = list(results_dir.glob("*.json"))
    assert len(written) == 1


# --------------------------------------------------------------------------- #
# The results file identifies the prompt it measured (ISSUE-007)
#
# `prompts.py` rule 1 requires PROMPT_VERSION to be bumped on any prompt change
# and rule 5 extends that to a reworded schema `description=`, because the
# harness names its output file from PROMPT_VERSION. Nothing enforced it:
# measured 2026-08-19, reverting PROMPT_VERSION 1.1.0 -> 1.0.0 passed the whole
# suite. An un-bumped change made the same day as an earlier run OVERWROTE that
# run's artefact.
#
# `prompt_bundle_hash()` already moves on its own -- it covers every prompt
# constant and the tool-schema JSON -- so the fix is to put it where the
# collision happens rather than to add a discipline test nobody can enforce.
# --------------------------------------------------------------------------- #


def _one_label_golden(tmp_path):
    golden = tmp_path / "golden"
    labels = golden / "labels"
    labels.mkdir(parents=True)
    (labels / "r1.json").write_text(
        _extraction(total="224.00").model_dump_json(), encoding="utf-8"
    )
    return golden


def _reworded_prompt():
    """Change what the model is shown WITHOUT touching PROMPT_VERSION.

    Rule 5's exact case, and the real mechanism rather than a patched hash:
    `_bundle_text` hashes the tool schema, so rewording a live `description=`
    moves `prompt_bundle_hash()`. Mirrors
    `test_the_bundle_hash_moves_when_a_description_the_model_sees_changes`.
    """
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        field = LineItem.model_fields["is_template_row"]
        original = field.description
        try:
            field.description = "SENTINEL: a materially different instruction"
            LineItem.model_rebuild(force=True)
            ReceiptExtraction.model_rebuild(force=True)
            yield
        finally:
            field.description = original
            LineItem.model_rebuild(force=True)
            ReceiptExtraction.model_rebuild(force=True)

    return _ctx()


def test_an_unbumped_prompt_change_cannot_overwrite_the_previous_run(tmp_path):
    """ISSUE-007's concrete consequence, as a property of the artefact.

    Two runs on one day, PROMPT_VERSION untouched, the prompt text different.
    Before the fix both named the same file and the second silently replaced
    the first, so the committed results said one prompt had been measured when
    two had. `PROMPT_VERSION` staying put is the *premise* here, not an
    oversight -- it is precisely the honour-system failure the issue records.
    """
    golden = _one_label_golden(tmp_path)
    results_dir = tmp_path / "results"

    def pipeline_fn(path):
        return _extraction(total="224.00"), D("0.95")

    from receipts.extract.prompts import PROMPT_VERSION

    run_eval(golden, pipeline_fn, results_dir=results_dir)
    assert len(list(results_dir.glob("*.json"))) == 1

    with _reworded_prompt():
        run_eval(golden, pipeline_fn, results_dir=results_dir)

    written = sorted(p.name for p in results_dir.glob("*.json"))
    assert len(written) == 2, (
        "the second run overwrote the first: two different prompts, one "
        f"artefact. Files: {written}"
    )
    # And the version really did stay put, so the distinguishing part is the
    # prompt identity rather than a bump that quietly happened.
    assert all(PROMPT_VERSION in name for name in written), written


def test_the_results_payload_names_the_prompt_bundle_it_measured(tmp_path):
    """A figure has to carry what produced it, not just when it ran.

    `prompt_version` alone is honour-system; the bundle hash is derived from
    the text actually shipped to the model, so it cannot be forgotten.
    """
    from receipts.extract.prompts import prompt_bundle_hash

    golden = _one_label_golden(tmp_path)
    results_dir = tmp_path / "results"
    run_eval(
        golden,
        lambda path: (_extraction(total="224.00"), D("0.95")),
        results_dir=results_dir,
    )

    written = list(results_dir.glob("*.json"))
    assert len(written) == 1
    payload = json.loads(written[0].read_text(encoding="utf-8"))

    assert payload["prompt_bundle_hash"] == prompt_bundle_hash()
    # The old key stays: this is additive, and two committed runs already
    # carry `prompt_version`.
    assert "prompt_version" in payload


def test_an_all_failed_run_reports_no_precision_rather_than_a_perfect_one(tmp_path):
    """A run where every receipt failed must not claim perfect precision.

    ``_build_report`` defined ``auto_approval_precision`` as ``1.0`` when
    nothing was auto-approved -- a ratio over zero decisions, asserted as
    certainty. Two guards were built for that value and **neither covers this
    case**: ``calibrate`` refuses a zero-receipt *result set*, and ``eval``
    refuses a zero-receipt *run*. Here ``n_receipts`` is 3, so both stand down,
    and ``n_auto_approved`` is 0 because every receipt failed.

    Measured before the fix: the report said ``1.0`` and
    ``_report_to_dict`` persisted ``1.0`` into the committed JSON artifact --
    a run that read nothing successfully, recorded as flawless.

    ``None``, not ``0.0``: no receipt was approved, so precision is undefined
    rather than bad. This is the project's "null over confident-wrong"
    invariant at the one place that writes the number down, and ADR-0027
    decision 5's rule -- ``null`` must never look like ``0`` -- applied to the
    artifact instead of the screen.

    The console path was already honest (``run_baseline`` prints ``n/a`` when
    nothing was approved); only the persisted value lied.
    """
    golden = tmp_path / "golden"
    labels = golden / "labels"
    labels.mkdir(parents=True)
    for name in ("r1", "r2", "r3"):
        (labels / f"{name}.json").write_text(
            _extraction(total="224.00").model_dump_json(), encoding="utf-8"
        )

    def pipeline_fn(path):
        raise RuntimeError("the provider is down")

    results_dir = tmp_path / "results"
    report = run_eval(golden, pipeline_fn, results_dir=results_dir)

    # The zero-receipt guards cannot fire here: receipts were read, and failed.
    assert report.n_receipts == 3
    assert report.n_failed == 3
    assert report.n_auto_approved == 0

    assert report.auto_approval_precision is None

    written = json.loads(
        next(results_dir.glob("*.json")).read_text(encoding="utf-8")
    )
    assert written["metrics"]["auto_approval_precision"] is None


def test_a_metric_over_no_fields_is_none_rather_than_zero(tmp_path):
    """The ``None``-over-zero rule, pinned on the report *and* on the JSON.

    The same pair of pins ``auto_approval_precision`` carries directly above,
    applied to the four ratios that replaced the old scalar. Every receipt
    fails here, so ``n_receipts`` is 3 -- this is not the zero-receipt case --
    while every breakdown denominator is 0. A ratio over no decisions is
    undefined, not bad: a ``0.0`` would read as "measured, and the model read
    nothing correctly", which is a different and false claim, and it is the
    claim ``auto_approval_precision`` actually persisted to a committed
    artifact once.
    """
    golden = tmp_path / "golden"
    labels = golden / "labels"
    labels.mkdir(parents=True)
    for name in ("r1", "r2", "r3"):
        (labels / f"{name}.json").write_text(
            _extraction(total="224.00").model_dump_json(), encoding="utf-8"
        )

    def pipeline_fn(path):
        raise RuntimeError("the provider is down")

    results_dir = tmp_path / "results"
    report = run_eval(golden, pipeline_fn, results_dir=results_dir)

    assert report.n_receipts == 3
    assert report.transcription_accuracy is None
    assert report.transcription_accuracy_core is None
    assert report.transcription_accuracy_line_items is None
    assert report.self_report_agreement is None

    metrics = json.loads(
        next(results_dir.glob("*.json")).read_text(encoding="utf-8")
    )["metrics"]
    assert metrics["transcription_accuracy"] is None
    assert metrics["transcription_accuracy_core"] is None
    assert metrics["transcription_accuracy_line_items"] is None
    assert metrics["self_report_agreement"] is None


def test_run_eval_survives_a_failing_receipt(tmp_path):
    # A single receipt that raises must not abort the batch. At minutes per call
    # that would throw away the whole run and write no results file at all --
    # the one artifact §16 treats as non-negotiable.
    golden = tmp_path / "golden"
    labels = golden / "labels"
    labels.mkdir(parents=True)

    (labels / "r1.json").write_text(
        _extraction(total="224.00").model_dump_json(), encoding="utf-8"
    )
    (labels / "r2.json").write_text(
        _extraction(total="500.00", name="OTHER STORE").model_dump_json(),
        encoding="utf-8",
    )

    def pipeline_fn(path):
        if path.stem == "r2":
            raise RuntimeError("connection: Request timed out.")
        return _extraction(total="224.00"), D("0.95")

    results_dir = tmp_path / "results"
    report = run_eval(golden, pipeline_fn, results_dir=results_dir)

    # The run completes and the failure is counted, not dropped.
    assert report.n_receipts == 2
    assert report.n_failed == 1
    assert report.failures == [("r2", "RuntimeError: connection: Request timed out.")]

    # A receipt the system could not read is processed but never a success.
    failed = next(r for r in report.results if r.receipt_id == "r2")
    assert failed.critical_correct is False
    assert failed.confidence == D("0")
    assert failed.field_acc == {}
    assert report.n_critical_correct == 1
    assert report.n_auto_approved == 1  # only r1; confidence 0 can never approve

    # The empty field map keeps the transcription denominator honest: r1 read
    # perfectly, so the aggregate stays 1.0 rather than being halved by a
    # receipt that produced nothing.
    assert report.transcription_accuracy == 1.0

    # The error detail reaches the committed artifact.
    written = list(results_dir.glob("*.json"))
    assert len(written) == 1
    payload = json.loads(written[0].read_text(encoding="utf-8"))
    assert payload["counts"]["receipts"] == 2
    assert payload["counts"]["failed"] == 1
    assert payload["failures"] == [
        ["r2", "RuntimeError: connection: Request timed out."]
    ]


def test_run_eval_records_an_unreadable_label_as_a_failure(tmp_path):
    # Resilience covers the label load too: corrupt golden data is recorded and
    # the remaining receipts still get scored.
    golden = tmp_path / "golden"
    labels = golden / "labels"
    labels.mkdir(parents=True)

    (labels / "r1.json").write_text(
        _extraction(total="224.00").model_dump_json(), encoding="utf-8"
    )
    (labels / "r2.json").write_text("{not json", encoding="utf-8")

    def pipeline_fn(path):
        return _extraction(total="224.00"), D("0.95")

    report = run_eval(golden, pipeline_fn, results_dir=tmp_path / "results")

    assert report.n_receipts == 2
    assert report.n_failed == 1
    assert [rid for rid, _detail in report.failures] == ["r2"]
    assert report.n_auto_approved == 1


def test_the_report_carries_each_class_separately(tmp_path):
    golden = tmp_path / "golden"
    labels = golden / "labels"
    labels.mkdir(parents=True)
    (labels / "r1.json").write_text(
        _extraction(total="224.00").model_dump_json(), encoding="utf-8"
    )

    def pipeline_fn(path):
        return _extraction(total="224.00"), D("0.95")

    report = run_eval(golden, pipeline_fn, results_dir=tmp_path / "results")

    assert report.transcription_accuracy == 1.0
    assert report.transcription_accuracy_core == 1.0
    assert report.transcription_accuracy_line_items == 1.0
    assert report.self_report_agreement == 1.0
    assert report.hallucinated_fields == 0
    assert report.correctly_empty_fields > 0
    # The two sides carry identical path sets here, so nothing is left over.
    assert report.structural_mismatch_fields == 0


def test_a_hallucinated_field_is_counted_and_does_not_touch_transcription(tmp_path):
    golden = tmp_path / "golden"
    labels = golden / "labels"
    labels.mkdir(parents=True)
    truth = _extraction(total="224.00")
    (labels / "r1.json").write_text(truth.model_dump_json(), encoding="utf-8")

    def pipeline_fn(path):
        invented = _extraction(total="224.00")
        invented.receipt.cashier = "MARIA"      # truth leaves this None
        return invented, D("0.95")

    report = run_eval(golden, pipeline_fn, results_dir=tmp_path / "results")

    assert report.hallucinated_fields == 1
    # Inventing a field must not enlarge the denominator the model is scored on.
    assert report.transcription_accuracy == 1.0


def test_the_artifact_keeps_the_per_path_map_sorted(tmp_path):
    """Spec §16 says metric 4 exists to show 'where to focus prompt work'. Two
    integers cannot answer that; the map can. Sorted so a diff is legible."""
    golden = tmp_path / "golden"
    labels = golden / "labels"
    labels.mkdir(parents=True)
    (labels / "r1.json").write_text(
        _extraction(total="224.00").model_dump_json(), encoding="utf-8"
    )

    def pipeline_fn(path):
        return _extraction(total="999.00"), D("0.95")     # wrong total

    results_dir = tmp_path / "results"
    run_eval(golden, pipeline_fn, results_dir=results_dir)
    payload = json.loads(
        next(results_dir.glob("*.json")).read_text(encoding="utf-8")
    )

    row = payload["results"][0]
    assert row["field_results"]["totals.total"] is False
    assert list(row["field_results"]) == sorted(row["field_results"])
    assert row["transcription_correct"] < row["transcription_total"]
    assert payload["metrics"]["transcription_accuracy"] < 1.0
    assert "field_accuracy" not in payload["metrics"]


# --------------------------------------------------------------------------- #
# extract_rung_counts (design §6)
# --------------------------------------------------------------------------- #


def test_the_rung_counts_default_to_none_when_unobservable(tmp_path):
    """``run_eval`` cannot see which rung ran, so it must not invent a number.

    Same rule as ``cost_per_receipt`` and the latency percentiles, and for the
    same stated reason: the injected ``pipeline_fn`` returns only an extraction
    and a confidence, so a caller that measures the real pipeline fills these
    in (design §6.1). ``None``, never ``{}`` -- an empty dict would read as
    "measured, and no rung ran", which is a different fact.

    The report is built the way this file builds them, through ``run_eval``
    with a stub ``pipeline_fn``, and never by calling the constructor: a
    hand-built ``EvalReport`` pins the constructor rather than the rule.
    """
    golden = tmp_path / "golden"
    labels = golden / "labels"
    labels.mkdir(parents=True)
    (labels / "r1.json").write_text(
        _extraction().model_dump_json(), encoding="utf-8"
    )

    def pipeline_fn(path):
        return _extraction(), D("0.95")

    report = run_eval(golden, pipeline_fn, results_dir=tmp_path / "results")

    assert report.extract_rung_counts is None


class _Rung:
    """A duck-typed rung. `use_tools` is omitted entirely when `None`, which is
    the shape `FakeVLMClient` really has -- not `use_tools = None`."""

    def __init__(self, model_id: str, use_tools: bool | None) -> None:
        self.model_id = model_id
        if use_tools is not None:
            self.use_tools = use_tools


def test_the_tier_key_and_the_rung_identity_agree():
    """The bound on a deliberate duplication (ISSUE-013).

    `eval.metrics.tier_key` keys the counts and `eval.run_repeats.rung_identity`
    writes the ladder into the aggregate's `config`. Both render the same
    `(model, use_tools)` pair, and a reader joins the two by it. They are not
    shared code, because `run_repeats` calls `run_baseline` and importing back
    would be a cycle -- so the duplication is bound here instead.

    **The property is injectivity, not string equality.** Asserting a rendered
    format would re-implement `tier_key` in its own test and pass by
    construction. What must hold is that the key distinguishes exactly the
    rungs the identity distinguishes: two rungs share a key if and only if they
    share an identity. A `tier_key` that dropped `use_tools` merges a pair the
    identity separates, and fails here.
    """
    from eval.metrics import tier_key
    from eval.run_repeats import rung_identity

    rungs = [
        _Rung(model, tools)
        for model in ("m", "n")
        for tools in (True, False, None)
    ]
    assert len(rungs) == 6, "the matrix below is vacuous if this is not 6"

    for left in rungs:
        for right in rungs:
            same_identity = rung_identity(left) == rung_identity(right)
            same_key = tier_key(left) == tier_key(right)
            assert same_key == same_identity, (
                f"tier_key and rung_identity disagree about "
                f"{rung_identity(left)} vs {rung_identity(right)}: "
                f"keys {tier_key(left)!r} / {tier_key(right)!r}"
            )


# --------------------------------------------------------------------------- #
# The precision interval (P8.T2)
# --------------------------------------------------------------------------- #


def test_a_perfect_run_on_three_receipts_cannot_support_the_99_percent_claim():
    """The spec's headline number, against the corpus that exists.

    `RECEIPT_SYSTEM_SPEC.md` line 70 asks for **>= 99% precision on
    auto-approved receipts**. The golden set is three. A *perfect* three-of-three
    run reports 100% and its 95% interval is roughly [44%, 100%] -- so the point
    estimate clears 99% and the evidence does not come close.

    This is the whole reason the interval is reported: without it, "100%" off
    three receipts reads as the criterion being met.
    """
    low, high = wilson_interval(3, 3)
    assert high == 1.0
    assert low < 0.5
    assert low < 0.99, "a 3-of-3 run must not be able to support the >=99% claim"


def test_the_interval_narrows_as_the_sample_grows():
    """Monotonic in n, which is the property that makes it worth printing.

    Asserted as a *sequence* rather than at one size: a function returning a
    constant wide band would satisfy any single-size assertion and say nothing
    about sample size, which is the only thing this measures.
    """
    lows = [wilson_interval(n, n)[0] for n in (3, 30, 100, 300, 1000)]
    assert lows == sorted(lows), f"lower bound is not monotonic in n: {lows}"
    assert lows[0] < 0.5
    # Roughly a thousand clean receipts before the EVIDENCE clears 99%, against
    # the 50 P0.T1 asks for. Recorded because it re-scopes that task.
    assert lows[-1] >= 0.99
    assert wilson_interval(300, 300)[0] < 0.99


def test_an_interval_over_no_samples_is_undefined_not_perfect():
    """`None`, never `(0.0, 1.0)` and never `(1.0, 1.0)`.

    A ratio over nothing is undefined, which is the rule
    `auto_approval_precision` already follows -- it is `None` when nothing was
    approved. An interval that rendered as a number here would be a measurement
    of a run that measured nothing.
    """
    assert wilson_interval(0, 0) is None


def test_the_reports_interval_brackets_its_own_point_estimate():
    """The bound on storing a count and a ratio separately.

    `auto_approval_precision` is stored; the interval is derived from
    `n_auto_approved_correct` over `n_auto_approved`. Two sources for one fact
    can drift, so this is the assertion that they have not: whatever the report
    says its precision is, its interval must contain it.
    """
    report = EvalReport(
        n_receipts=10,
        n_auto_approved=8,
        n_auto_approved_correct=7,
        n_critical_correct=9,
        auto_approve_threshold=D("0.85"),
        auto_approval_precision=7 / 8,
        auto_approval_rate=8 / 10,
        critical_field_accuracy=9 / 10,
        breakdown=FieldBreakdown(),
        line_item_precision=1.0,
        line_item_recall=1.0,
        line_item_f1=1.0,
    )
    low, high = report.auto_approval_precision_interval
    assert low <= report.auto_approval_precision <= high
    crit_low, crit_high = report.critical_field_accuracy_interval
    assert crit_low <= 9 / 10 <= crit_high


def test_a_report_built_by_run_eval_carries_a_bracketing_interval(tmp_path):
    """The wiring, not the arithmetic.

    `wilson_interval` is pinned above on numbers handed straight to it. This
    pins that `_build_report` fills `n_auto_approved_correct` from the run --
    left at its `0` default, every real report would compute an interval whose
    numerator is zero, report something like [0%, 37%] beside a precision of
    100%, and no test touching the function directly would notice.

    An end-to-end path is the only place that can see it, because the defect is
    a field nobody populated rather than a formula anybody got wrong.
    """
    golden = tmp_path / "golden"
    (golden / "labels").mkdir(parents=True)
    truth = _extraction()
    (golden / "labels" / "r001.json").write_text(
        truth.model_dump_json(), encoding="utf-8"
    )

    def pipeline_fn(_path):
        return _extraction(), D("0.99")

    report = run_eval(golden, pipeline_fn, results_dir=tmp_path / "results")

    assert report.n_auto_approved == 1
    assert report.n_auto_approved_correct == 1, (
        "_build_report left the interval's numerator at its default"
    )
    low, high = report.auto_approval_precision_interval
    assert low <= report.auto_approval_precision <= high
    # A single receipt says almost nothing, and the interval is how that shows.
    assert low < 0.5
