"""One-command baseline runner: settings -> client -> pipeline -> harness.

Offline like the rest of the suite -- an injected FakeVLMClient replays scripted
responses (triage then extraction, mirroring tests/test_pipeline.py) and every
image is synthetic, so no provider or network is touched. The provider-guard
test drives the ``client=None`` path with ``VLM_PROVIDER`` pinned to ``"fake"``
via monkeypatch, proving the runner refuses the response-less default before it
ever reaches the pipeline.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from eval.metrics import EvalReport, FieldBreakdown
from eval.run_baseline import format_breakdown, format_report, run_baseline
from receipts.extract.clients.factory import PassClients
from receipts.extract.clients.fake import FakeVLMClient
from receipts.extract.schema import (
    DocumentType,
    Legibility,
    LineItem,
    Merchant,
    ReceiptExtraction,
    ReceiptMeta,
    Totals,
    TriageResult,
)
from receipts.validate.context import ValidationContext

CTX = ValidationContext(today=date(2026, 7, 26))


def _good() -> ReceiptExtraction:
    """A clean, self-consistent extraction (mirrors test_pipeline.good())."""
    return ReceiptExtraction(
        merchant=Merchant(name="SUPERMART INC."),
        receipt=ReceiptMeta(date="2026-07-20", currency="PHP"),
        line_items=[
            LineItem(position=0, description_raw="RICE 5KG", qty=D("1"),
                     unit_price=D("100.00"), line_total=D("100.00")),
            LineItem(position=1, description_raw="OIL 1L", qty=D("2"),
                     unit_price=D("50.00"), line_total=D("100.00")),
        ],
        totals=Totals(subtotal=D("200.00"), tax=D("24.00"), discount=D("0.00"),
                      total=D("224.00")),
    )


def _no_currency() -> ReceiptExtraction:
    """The clean extraction with no currency printed (mirrors PH BIR invoices)."""
    extraction = _good()
    extraction.receipt.currency = None
    return extraction


def _triage() -> TriageResult:
    # GOOD legibility keeps the clean receipt at a perfect confidence so it
    # stays auto-approved under real scoring.
    return TriageResult(document_type=DocumentType.POS_RECEIPT,
                        legibility=Legibility.GOOD,
                        estimated_line_item_count=2)


def _unparseable() -> str:
    """A scripted response body that will not coerce to ReceiptExtraction.

    ``FakeVLMClient`` treats a string entry as a ``parse_error``, and
    ``_evaluate`` resolves a failed parse to a default ``ReceiptExtraction()``,
    which is exactly what ``read_nothing`` calls "read nothing". Mirrors
    ``tests/test_pipeline.py``.
    """
    return "not json at all"


def _write_png(path: Path) -> None:
    """A synthetic RGB PNG, sized so resize_for_model logs no legibility warning."""
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (900, 1400), (240, 240, 240)).save(path)


def _write_golden(golden: Path) -> None:
    """One labelled receipt (label + matching image) under a tmp golden dir.

    The optional ``pipeline`` extra (Pillow + HEIF) is needed here and nowhere
    else in this file, so the guard sits on the fixture that needs it. It used
    to open the module::

        pytest.importorskip("PIL")
        pytest.importorskip("pillow_heif")

    which took every test in the file with it — including the
    ``format_breakdown`` tests at the bottom, covering the renderer this module
    shares with ``scripts/try_one_receipt.py``, which needs neither an image
    nor the pipeline. Measured with ``pillow_heif`` blocked: the module-level
    form reported ``1 skipped`` and ran nothing.

    Attached to the fixture rather than listed against test names, because a
    list of names is an enumeration a test added next year escapes: a test that
    builds a golden set is guarded because it built one.

    **What this does not buy, measured.** ``eval.run_baseline`` imports
    ``receipts.pipeline``, whose module-top import graph reaches Pillow (in
    ``receipts.pipeline`` itself) and ``pillow_heif`` (in
    ``receipts.preprocess.image_ops``), so this file cannot be *collected*
    without either — guard or no guard, the narrowed form turns a skip into a
    collection error there. That
    costs nothing today: blocking ``pillow_heif`` and collecting
    ``tests/test_cli_reports.py`` and ``tests/test_preprocess_cv.py`` one at a
    time errors on each, so a run without the extra is already interrupted
    before this file is reached. The guard was buying a tidy skip inside a
    suite that could not start. What the narrowing does buy is that the file no
    longer says the formatting tests need an image library, and that they stop
    being hidden the day that import chain is untangled.
    """
    pytest.importorskip("PIL")
    pytest.importorskip("pillow_heif")

    labels = golden / "labels"
    images = golden / "images"
    labels.mkdir(parents=True)
    images.mkdir(parents=True)
    (labels / "r1.json").write_text(_good().model_dump_json(), encoding="utf-8")
    _write_png(images / "r1.png")


# --------------------------------------------------------------------------- #
# run_baseline: injected client, fully offline
# --------------------------------------------------------------------------- #


def test_run_baseline_with_injected_client_scores_golden_set(tmp_path):
    golden = tmp_path / "golden"
    _write_golden(golden)
    client = FakeVLMClient([_triage(), _good()])

    report = run_baseline(
        golden_dir=golden,
        client=client,
        ctx=CTX,
        results_dir=tmp_path / "results",
    )

    assert isinstance(report, EvalReport)
    assert report.n_receipts == 1
    # The scripted extraction matches the label, so the run is clean end to end.
    assert report.critical_field_accuracy == 1.0
    # Real confidence scoring: the clean receipt scores 1.000 and auto-approves.
    assert report.n_auto_approved == 1
    # A results file was written under the injected results_dir.
    assert list((tmp_path / "results").glob("*.json"))


def test_run_baseline_applies_configured_default_currency(monkeypatch, tmp_path):
    # The label says PHP; the model returns no currency at all (PH BIR invoices
    # never print one). DEFAULT_CURRENCY has to close that gap or every receipt
    # in the corpus scores a currency miss. VLM_PROVIDER is pinned to the
    # response-less "fake" default to prove the injected-client path still needs
    # no real provider even though settings are now read for the currency.
    monkeypatch.setenv("DEFAULT_CURRENCY", "PHP")
    monkeypatch.setenv("VLM_PROVIDER", "fake")
    golden = tmp_path / "golden"
    _write_golden(golden)
    client = FakeVLMClient([_triage(), _no_currency()])

    report = run_baseline(
        golden_dir=golden,
        client=client,
        ctx=CTX,
        results_dir=tmp_path / "results",
    )

    assert report.results[0].field_acc["receipt.currency"] is True


# --------------------------------------------------------------------------- #
# run_baseline: client=None refuses the response-less fake provider
# --------------------------------------------------------------------------- #


def test_run_baseline_refuses_fake_provider(monkeypatch, tmp_path):
    # Pin the resolved provider to "fake" regardless of ambient env / .env.
    monkeypatch.setenv("VLM_PROVIDER", "fake")

    with pytest.raises(RuntimeError, match="(?i)provider"):
        run_baseline(golden_dir=tmp_path, client=None)


# --------------------------------------------------------------------------- #
# run_baseline: the extract ladder, and who is allowed to get one
# --------------------------------------------------------------------------- #


def test_run_baseline_wires_the_ladder_and_reports_the_rung_that_was_kept(
    monkeypatch, tmp_path
):
    """The ladder reaches a run, and the report says which rung produced it.

    ``make_pass_clients`` is stubbed here rather than exercised -- Task 4's
    tests own what it builds; what is pinned here is that ``run_baseline``
    *calls* it and forwards **both** rungs plus the triage client into
    ``build_eval_pipeline``. ``monkeypatch.setattr`` on the dotted name also
    asserts that ``eval.run_baseline`` has that attribute at all: swap the
    module back to ``make_client`` and this fails at setup.

    ``VLM_PROVIDER`` is pinned to a non-``fake`` id so the ``client=None``
    branch reaches the builder instead of the response-less-provider refusal;
    no real client is ever constructed, because the builder is stubbed.

    The first rung returns an unparseable body, so it reads nothing and is
    discarded, and the fallback produces the kept extraction. A run that never
    passed ``extract_fallback_client`` would keep the first rung's empty
    extraction and count ``local``.
    """
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)

    triage_client = FakeVLMClient([_triage()], model_id="triage-model")
    # The surplus second response is never consumed by correct behaviour (the
    # call count below pins that). It is there so that dropping the triage
    # forwarding reddens on an assertion here rather than on "FakeVLMClient
    # exhausted", which is a test-authoring failure wearing a pin's clothes.
    local = FakeVLMClient([_unparseable(), _unparseable()], model_id="local")
    cloud = FakeVLMClient([_good()], model_id="cloud")
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients",
        lambda settings: PassClients(
            triage=triage_client, extract_rungs=(local, cloud)
        ),
    )

    report = run_baseline(
        golden_dir=golden, ctx=CTX, results_dir=tmp_path / "results"
    )

    # Loud when the wiring breaks: a raised run is recorded as a failure rather
    # than surfacing, so without this a broken ladder reads as "no counts".
    assert report.n_failed == 0, report.failures
    assert len(triage_client.calls) == 1
    assert len(local.calls) == 1
    assert len(cloud.calls) == 1

    # Only the kept extract rung is counted: not the triage pass, and not the
    # rung that was discarded. Both ran, and neither produced the extraction
    # this report scored.
    assert report.extract_rung_counts == {"cloud": 1}


def test_the_committed_results_file_records_which_rung_produced_it(
    monkeypatch, tmp_path
):
    """ISSUE-012: the counts reached the printed report and never the artefact.

    `run_eval`'s last two statements were `_write_report(...)` then
    `return report`, and `run_baseline` folded the rung counts in *after* it
    returned — so a key added to `_report_to_dict` would have been `null` in
    every file that function ever produced, whatever the run measured. Probed
    2026-08-21: a run whose report carried `{'cloud': 1}` wrote `null`.

    **Spec §16 commits the results file so regressions show in a diff, and
    ISSUE-001's stated fear is a good accuracy number hiding the fact that
    everything escalated.** An artefact that omits which model produced what
    does not record the thing that step exists to record.

    This asserts against the file on disk, not the returned report. The
    returned report was always right; the file was the defect.
    """
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)

    triage_client = FakeVLMClient([_triage()], model_id="triage-model")
    local = FakeVLMClient([_unparseable(), _unparseable()], model_id="local")
    cloud = FakeVLMClient([_good()], model_id="cloud")
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients",
        lambda settings: PassClients(
            triage=triage_client, extract_rungs=(local, cloud)
        ),
    )

    results = tmp_path / "results"
    report = run_baseline(golden_dir=golden, ctx=CTX, results_dir=results)
    assert report.n_failed == 0, report.failures

    written = json.loads(
        next(iter(sorted(results.glob("*.json")))).read_text(encoding="utf-8")
    )
    assert written["extract_rung_counts"] == {"cloud": 1}
    assert written["extract_discard_counts"] == {"local": {"read_nothing": 1}}


def test_two_rungs_of_one_model_are_counted_as_two_tiers(monkeypatch, tmp_path):
    """ISSUE-013: design §2.2 defines a tier as `(model, use_tools)`, not a model.

    Nothing forbids `VLM_MODEL_EXTRACT_FALLBACK` naming the same model as
    `VLM_MODEL_EXTRACT` with a different tools answer, and
    `make_pass_clients` builds exactly that ladder — measured 2026-08-21 as
    `[('m', False), ('m', True)]`. Keyed by `model_id` alone both rungs landed
    in one count and **the escalation was invisible in the very figure
    ISSUE-001 asked for so that a good number could not hide one.**

    **This pins `PassAttempt.rung` as a side effect, and that is deliberate
    (ISSUE-015).** When two rungs share a `model_id`, the attempt's `model_id`
    cannot say which rung it was — only `rung` can, because it is the index
    into `extract_rungs`. So resolving the tier *requires* reading `rung`, and
    a ladder that numbered every rung `0` would key both rungs to the first
    rung's tools answer and redden here.
    """
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)

    triage_client = FakeVLMClient([_triage()], model_id="triage-model")
    # One model, two tools answers -- the constructible ladder ISSUE-013 names.
    # `use_tools` is set on the instance rather than passed to the constructor
    # because `FakeVLMClient` does not carry one; that is exactly why
    # `run_repeats.rung_identity` reads it with `getattr`, and this test drives
    # the same optional attribute the same way.
    first = FakeVLMClient([_unparseable(), _unparseable()], model_id="m")
    first.use_tools = False
    second = FakeVLMClient([_good()], model_id="m")
    second.use_tools = True
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients",
        lambda settings: PassClients(
            triage=triage_client, extract_rungs=(first, second)
        ),
    )

    report = run_baseline(
        golden_dir=golden, ctx=CTX, results_dir=tmp_path / "results"
    )

    assert report.n_failed == 0, report.failures
    # The kept rung and the discarded rung are the same MODEL and different
    # TIERS, and the report says so.
    assert report.extract_rung_counts == {"m +tools": 1}
    assert report.extract_discard_counts == {"m -tools": {"read_nothing": 1}}


def test_an_injected_client_gets_no_ladder(monkeypatch, tmp_path):
    """An injected ``client`` is one rung for every pass, as it always was.

    ``run_baseline``'s ``client`` seam is what the two offline tests above this
    one use, and what ``cli.cmd_eval`` forwards its own injectable ``client``
    into; passing a client is not opting into an escalation. Building the ladder
    unconditionally would override the injected client and break every one of
    them, so the builder is made to explode here: reaching it at all is the
    failure. (Measured: with the ladder built on both branches, this test and
    both of those two go red.)

    ``VLM_PROVIDER`` is ``fake`` on purpose. The response-less-provider refusal
    also belongs to the ``client is None`` branch, so this run reaching a report
    at all says that check did not migrate out of it either.
    """
    monkeypatch.setenv("VLM_PROVIDER", "fake")
    golden = tmp_path / "golden"
    _write_golden(golden)

    def _must_not_run(settings):
        raise AssertionError(
            "run_baseline built a ladder for an injected client, overriding it"
        )

    monkeypatch.setattr("eval.run_baseline.make_pass_clients", _must_not_run)

    client = FakeVLMClient([_triage(), _good()], model_id="only")
    report = run_baseline(
        golden_dir=golden,
        client=client,
        ctx=CTX,
        results_dir=tmp_path / "results",
    )

    assert report.n_failed == 0, report.failures
    # Two calls, not three: the triage pass and one extract, both on the one
    # client that was handed in.
    assert len(client.calls) == 2
    assert report.extract_rung_counts == {"only": 1}


def test_a_one_rung_ladder_does_not_hand_its_only_rung_back_as_its_own_fallback(
    monkeypatch, tmp_path
):
    """One rung means no fallback, and the rung that read nothing is not re-run.

    ``run_baseline`` chooses the fallback with ``extract_rungs[1] if
    len(extract_rungs) > 1 else None``. Written as ``extract_rungs[-1]`` it
    reads the same on a two-rung ladder and hands a one-rung ladder its own only
    rung back as the fallback -- which the test above cannot see, because its
    rung reads *something* and a fallback is never reached. Here the rung reads
    nothing, so a wired fallback runs, and the run costs two extract calls
    instead of one.

    The third scripted response is deliberately surplus: correct behaviour never
    reaches it, and its presence is what makes the re-run redden on the count
    below rather than on ``FakeVLMClient exhausted`` from inside the runner.

    ``make_pass_clients`` is made to explode for the same reason the test above
    does it -- an injected client must not reach the builder at all.
    """
    monkeypatch.setenv("VLM_PROVIDER", "fake")
    golden = tmp_path / "golden"
    _write_golden(golden)

    def _must_not_run(settings):
        raise AssertionError(
            "run_baseline built a ladder for an injected client, overriding it"
        )

    monkeypatch.setattr("eval.run_baseline.make_pass_clients", _must_not_run)

    client = FakeVLMClient(
        [_triage(), _unparseable(), _good()], model_id="only"
    )
    report = run_baseline(
        golden_dir=golden,
        client=client,
        ctx=CTX,
        results_dir=tmp_path / "results",
    )

    assert report.n_failed == 0, report.failures
    assert len(client.calls) == 2, (
        "the sole rung was called twice for one receipt: a one-rung ladder was "
        "wired as its own fallback"
    )
    # It read nothing and is the final rung, so its empty extraction is what the
    # report scored -- counted, because it is what was kept, and scored at zero,
    # which is the measurement. A second call would have scored the *good*
    # response instead and hidden the whole thing.
    assert report.extract_rung_counts == {"only": 1}
    assert report.results[0].field_acc["merchant.name"] is False


def test_a_run_that_scored_nothing_reports_no_counts_rather_than_empty_ones(
    monkeypatch, tmp_path
):
    """Zero receipts leaves the counts ``None``, not ``{}``.

    ``{}`` would read as "measured, and no rung ran", which is a claim; nothing
    ran, so nothing was measured. The same "null over confident-wrong" rule
    ``auto_approval_precision`` learned in P8.T3, on the field this milestone
    adds -- and the one line (``counts or None``) that enforces it.
    """
    monkeypatch.setenv("VLM_PROVIDER", "fake")
    golden = tmp_path / "golden"
    (golden / "labels").mkdir(parents=True)
    (golden / "images").mkdir(parents=True)

    report = run_baseline(
        golden_dir=golden,
        client=FakeVLMClient([], model_id="never-called"),
        ctx=CTX,
        results_dir=tmp_path / "results",
    )

    assert report.n_receipts == 0
    assert report.extract_rung_counts is None


# --------------------------------------------------------------------------- #
# format_report
# --------------------------------------------------------------------------- #


def test_format_report_contains_metric_labels():
    report = EvalReport(
        n_receipts=2,
        n_auto_approved=1,
        n_critical_correct=2,
        auto_approve_threshold=D("0.85"),
        auto_approval_precision=1.0,
        auto_approval_rate=0.5,
        critical_field_accuracy=1.0,
        breakdown=FieldBreakdown(
            transcription_correct=19, transcription_total=20,
            core_correct=9, core_total=10,
            line_items_correct=10, line_items_total=10,
            self_report_correct=2, self_report_total=4,
            hallucinated=2, correctly_empty=11,
        ),
        line_item_precision=1.0,
        line_item_recall=1.0,
        line_item_f1=1.0,
    )

    text = format_report(report)

    assert isinstance(text, str) and text.strip()
    for label in (
        "Auto-approval precision",
        "Auto-approval rate",
        "Critical-field accuracy",
        "Transcription accuracy",
        "Line-item F1",
        "Hallucinated fields",
    ):
        assert label in text


def test_format_report_shows_failed_count():
    # A run that partially failed must say so on screen, not just in the JSON.
    report = EvalReport(
        n_receipts=3,
        n_auto_approved=1,
        n_critical_correct=1,
        auto_approve_threshold=D("0.85"),
        auto_approval_precision=1.0,
        auto_approval_rate=1 / 3,
        critical_field_accuracy=1 / 3,
        breakdown=FieldBreakdown(
            transcription_correct=19, transcription_total=20,
            core_correct=9, core_total=10,
            line_items_correct=10, line_items_total=10,
            self_report_correct=2, self_report_total=4,
            hallucinated=2, correctly_empty=11,
        ),
        line_item_precision=1.0,
        line_item_recall=1.0,
        line_item_f1=1.0,
        n_failed=2,
        failures=[("r2", "RuntimeError: boom"), ("r3", "RuntimeError: boom")],
    )

    text = format_report(report)

    assert "Failed" in text
    failed_line = next(line for line in text.splitlines() if "Failed" in line)
    assert "2" in failed_line


def _rung_counts_report(counts: dict[str, int] | None) -> EvalReport:
    """A renderer fixture whose one interesting field is ``extract_rung_counts``.

    Hand-built, like the two ``format_report`` fixtures above it: these tests
    are about what the renderer puts on screen, so the report is an input, not
    a specimen of what the harness returns.
    """
    return EvalReport(
        n_receipts=3,
        n_auto_approved=3,
        n_critical_correct=3,
        auto_approve_threshold=D("0.85"),
        auto_approval_precision=1.0,
        auto_approval_rate=1.0,
        critical_field_accuracy=1.0,
        breakdown=FieldBreakdown(
            transcription_correct=19, transcription_total=20,
            core_correct=9, core_total=10,
            line_items_correct=10, line_items_total=10,
            self_report_correct=2, self_report_total=4,
            hallucinated=2, correctly_empty=11,
        ),
        line_item_precision=1.0,
        line_item_recall=1.0,
        line_item_f1=1.0,
        extract_rung_counts=counts,
    )


def test_format_report_prints_the_rung_counts_beside_the_accuracy_figures():
    """Design §6.2: the placement is the requirement, not a nicety.

    ISSUE-001's stated fear is a good accuracy number hiding the fact that
    everything escalated, and a figure in a trailing section at the bottom of
    the page does not answer it. So this is pinned as an *ordering* over the
    rendered lines rather than as "the counts appear somewhere": appending the
    block at the end of the report -- after cost and latency, or after the
    failure list -- reddens it.

    Each row is checked for its own count, not merely for a count, which is the
    lesson ``test_format_breakdown_renders_every_class`` records: a substring
    assertion passes under any permutation of the rows.
    """
    text = format_report(
        _rung_counts_report({"granite3.2-vision:2b": 1, "gemma4:cloud": 2})
    )
    lines = text.splitlines()

    def _at(fragment: str) -> int:
        return next(i for i, line in enumerate(lines) if fragment in line)

    assert _at("Critical-field accuracy") < _at("Extraction by rung")
    assert _at("Line-item F1") < _at("Extraction by rung")
    assert _at("Extraction by rung") < _at("Cost per receipt")

    assert lines[_at("granite3.2-vision:2b")].split()[-1] == "1"
    assert lines[_at("gemma4:cloud")].split()[-1] == "2"


def test_format_report_prints_no_rung_block_when_the_counts_are_unmeasured():
    """``None`` prints nothing, not an empty heading.

    An offline run through an injected ``pipeline_fn`` never measures a rung,
    and a bare "Extraction by rung:" with no rows under it would read as a
    measurement that came back empty.
    """
    text = format_report(_rung_counts_report(None))

    assert "by rung" not in text


# --------------------------------------------------------------------------- #
# format_breakdown
# --------------------------------------------------------------------------- #


def _row(text: str, label: str) -> str:
    """The one rendered line carrying ``label``.

    Raises ``StopIteration`` when the label is absent, so asserting on a row
    also asserts the row exists.
    """
    return next(line for line in text.splitlines() if label in line)


def test_format_breakdown_renders_every_class():
    """Each labelled row carries *its own* value, not merely a value.

    Asserted per row rather than as substrings of the block, because a
    substring test passes under any permutation of its rows. Measured, on
    the substring version this replaces: swapping ``hallucinated`` with
    ``correctly_empty``, and swapping the transcription and core rows, both
    left it green. ``"2" in text`` was satisfied by the self-report row's
    ``25.00%`` whatever the hallucinated count rendered as, and ``"90.00%" in
    text`` did not care which row carried the 90. The two counts are the novel
    part of this design and nothing was checking which one printed where.
    """
    text = format_breakdown(FieldBreakdown(
        transcription_correct=9, transcription_total=10,
        core_correct=5, core_total=5,
        line_items_correct=4, line_items_total=5,
        self_report_correct=1, self_report_total=4,
        hallucinated=2, correctly_empty=11, structural_mismatch=3,
    ))

    assert _row(text, "Transcription accuracy").split()[-2:] == ["90.00%", "(9/10)"]
    assert _row(text, "core:").split()[-2:] == ["100.00%", "(5/5)"]
    assert _row(text, "line items:").split()[-2:] == ["80.00%", "(4/5)"]
    assert _row(text, "Self-report agreement").split()[-2:] == ["25.00%", "(1/4)"]
    assert _row(text, "Hallucinated fields").split()[-1] == "2"
    assert _row(text, "Correctly empty fields").split()[-1] == "11"
    assert _row(text, "Structural mismatches").split()[-1] == "3"


def test_format_breakdown_renders_an_empty_denominator_as_na_not_zero():
    """A ratio over no paths is undefined, not 0% — the P8.T3 rule, on screen.

    Every ratio row is checked, not just one: ``"n/a" in text`` would pass on a
    block where a single row got the ``None`` treatment and the other three
    printed ``0.00%``.
    """
    text = format_breakdown(FieldBreakdown())

    for label in ("Transcription accuracy", "core:", "line items:",
                  "Self-report agreement"):
        assert _row(text, label).split()[-2:] == ["n/a", "(0/0)"]
    assert "0.00%" not in text
