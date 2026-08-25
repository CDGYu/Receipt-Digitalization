"""M1 pipeline runner tests. Offline: FakeVLMClient replays scripted responses
and every image is synthetic -- no provider, no network.

The runner's call order is load-bearing, so the FakeVLMClient script mirrors it
exactly: response[0] answers the triage call (schema ``TriageResult``) and
response[1] answers the extraction call (schema ``ReceiptExtraction``). A clean
extraction means no repair call fires, so two scripted responses are enough.
"""

from __future__ import annotations

import ast
import inspect
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

# The preprocess layer needs the optional "pipeline" extras (Pillow + HEIF).
# Skip the whole module rather than erroring at collection when absent.
pytest.importorskip("PIL")
pytest.importorskip("pillow_heif")

from PIL import Image  # noqa: E402

from config.settings import Settings  # noqa: E402
from eval.harness import run_eval  # noqa: E402
from eval.metrics import EvalReport  # noqa: E402
from receipts import cli, pipeline, worker  # noqa: E402
from receipts.extract.clients.base import VLMClient, VLMResponse, VLMTransientError  # noqa: E402
from receipts.extract.clients.fake import FakeVLMClient  # noqa: E402
from receipts.extract.schema import (  # noqa: E402
    DocumentType,
    Legibility,
    LineItem,
    Merchant,
    ReceiptExtraction,
    ReceiptMeta,
    Totals,
    TriageResult,
)
from receipts.pipeline import (  # noqa: E402
    DiscardReason,
    PassAttempt,
    build_eval_pipeline,
    prepare_image,
    run_receipt,
)
from receipts.validate.context import ValidationContext  # noqa: E402
from receipts.validate.report import ValidationReport  # noqa: E402

CTX = ValidationContext(today=date(2026, 7, 26))


def _good() -> ReceiptExtraction:
    """A clean, self-consistent extraction (mirrors test_extractor.good())."""
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
    """The clean extraction with no currency printed on the receipt.

    Mirrors the real corpus: PH BIR invoices never print an ISO code, so the
    configured system default is the only thing that can supply one.
    """
    extraction = _good()
    extraction.receipt.currency = None
    return extraction


def _triage() -> TriageResult:
    # GOOD legibility keeps the clean receipt at a perfect confidence so it
    # stays auto-approved under real scoring.
    return TriageResult(document_type=DocumentType.POS_RECEIPT,
                        legibility=Legibility.GOOD,
                        estimated_line_item_count=2)


def _write_png(path: Path) -> None:
    """A synthetic RGB PNG, sized so resize_for_model logs no legibility warning."""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (900, 1400), (240, 240, 240)).save(path)


class _RaisingClient(VLMClient):
    """A client whose every call is a transport failure."""

    def __init__(self, model_id: str = "raiser") -> None:
        self.model_id = model_id
        self.calls: list[dict] = []

    def complete_json(self, **kwargs: object) -> VLMResponse:
        self.calls.append(dict(kwargs))
        raise VLMTransientError("the endpoint is unreachable")


def _unparseable() -> str:
    """A scripted response body that will not coerce to ReceiptExtraction.

    ``FakeVLMClient`` treats a string entry as a ``parse_error``, and
    ``_evaluate`` resolves a failed parse to a default ``ReceiptExtraction()``,
    which is exactly what ``read_nothing`` calls "read nothing".
    """
    return "not json at all"


# --------------------------------------------------------------------------- #
# prepare_image
# --------------------------------------------------------------------------- #


def test_prepare_image_returns_transportable_prepared_image(tmp_path):
    png = tmp_path / "receipt.png"
    _write_png(png)

    prepared = prepare_image(png)

    assert prepared.b64  # non-empty base64 payload
    assert prepared.media_type == "image/jpeg"
    assert prepared.image_hash  # stable digest for cache-keying
    # The extractor turns it into an ImagePart; the payload must survive.
    assert prepared.as_part().b64 == prepared.b64


# --------------------------------------------------------------------------- #
# run_receipt
# --------------------------------------------------------------------------- #


def test_run_receipt_returns_normalized_extraction_and_report(tmp_path):
    png = tmp_path / "receipt.png"
    _write_png(png)
    client = FakeVLMClient([_triage(), _good()])

    outcome = run_receipt(png, client, CTX)
    extraction, report, triage_result = outcome.extraction, outcome.report, outcome.triage

    assert isinstance(extraction, ReceiptExtraction)
    assert isinstance(report, ValidationReport)
    # The triage result is returned too, so callers can score confidence
    # without re-running triage.
    assert isinstance(triage_result, TriageResult)
    # Call order: triage first, extraction second (proves the fake script maps
    # to the real sequence).
    assert len(client.calls) == 2
    assert client.calls[0]["schema"] == "TriageResult"
    assert client.calls[1]["schema"] == "ReceiptExtraction"
    # The scripted extraction survives normalization -- spot-check critical fields.
    assert extraction.merchant.name == "SUPERMART INC."
    assert extraction.receipt.date == "2026-07-20"
    assert extraction.totals.total == D("224.00")
    assert not report.has_errors


def test_run_receipt_applies_configured_default_currency(tmp_path):
    png = tmp_path / "receipt.png"
    _write_png(png)
    client = FakeVLMClient([_triage(), _no_currency()])

    extraction = run_receipt(
        png, client, CTX, default_currency="PHP"
    ).extraction

    assert extraction.receipt.currency == "PHP"


def test_run_receipt_without_default_currency_leaves_it_null(tmp_path):
    # No default configured means no currency: null beats a guess.
    png = tmp_path / "receipt.png"
    _write_png(png)
    client = FakeVLMClient([_triage(), _no_currency()])

    extraction = run_receipt(png, client, CTX).extraction

    assert extraction.receipt.currency is None


# --------------------------------------------------------------------------- #
# run_receipt: the extract ladder
# --------------------------------------------------------------------------- #


def test_the_fallback_is_not_called_when_the_first_rung_reads_something(tmp_path):
    png = tmp_path / "receipt.png"
    _write_png(png)
    first = FakeVLMClient([_triage(), _good()], model_id="local")
    fallback = FakeVLMClient([_good()], model_id="cloud")

    outcome = run_receipt(png, first, CTX, extract_fallback_client=fallback)

    assert fallback.calls == []
    assert outcome.extraction.merchant.name == "SUPERMART INC."
    kept = [a for a in outcome.attribution if a.pass_name == "extract" and a.kept]
    assert [a.model_id for a in kept] == ["local"]


def test_the_fallback_runs_when_the_first_rung_reads_nothing(tmp_path):
    png = tmp_path / "receipt.png"
    _write_png(png)
    # An unparseable extract response leaves `ReceiptExtraction()`, which is
    # exactly what "read nothing" means.
    first = FakeVLMClient([_triage(), _unparseable()], model_id="local")
    fallback = FakeVLMClient([_good()], model_id="cloud")

    outcome = run_receipt(png, first, CTX, extract_fallback_client=fallback)

    assert len(fallback.calls) == 1
    assert outcome.extraction.merchant.name == "SUPERMART INC."
    kept = [a for a in outcome.attribution if a.pass_name == "extract" and a.kept]
    assert [a.model_id for a in kept] == ["cloud"]
    # ...and the discarded rung is still recorded, so an eval can see it ran.
    discarded = [a for a in outcome.attribution if a.pass_name == "extract" and not a.kept]
    assert [a.model_id for a in discarded] == ["local"]


def test_the_ladder_numbers_its_extract_rungs(tmp_path):
    """ISSUE-015: `rung` was written at four sites and read at none.

    `git grep "\\.rung\\b" -- src eval` returned nothing, so **a ladder that
    recorded `rung=0` for every rung left every gate green.** One test read it
    — the triage one below — which pins the triage pass's value and nothing
    about the extract rungs, where the number is the one that carries
    information.

    **`rung` now has a production reader**: `run_baseline` resolves each
    attempt's tier through `extract_rungs[entry.rung]`, because when two rungs
    share a `model_id` and differ only in their tools answer, `rung` is the
    only thing that says which one ran (ISSUE-013). So this is no longer a
    field nothing consumes — and this pin is what stops the numbering itself
    from being wrong underneath that reader.

    **The issue offered deleting it instead, on the grounds that "`attribution`
    is a tuple in ladder order, so the index is recoverable". That is not
    true as stated** and the assertion below shows why: `attribution` holds the
    triage entry first, so a tuple index is offset from the rung index by the
    number of preceding non-extract entries. Recovering it means knowing how
    many passes precede the ladder, which is exactly the coupling storing the
    number avoids.
    """
    png = tmp_path / "receipt.png"
    _write_png(png)
    first = FakeVLMClient([_triage(), _unparseable()], model_id="local")
    fallback = FakeVLMClient([_good()], model_id="cloud")

    outcome = run_receipt(png, first, CTX, extract_fallback_client=fallback)

    extract = [a for a in outcome.attribution if a.pass_name == "extract"]
    assert [(a.model_id, a.rung) for a in extract] == [("local", 0), ("cloud", 1)]
    # The offset the docstring describes, asserted rather than asserted-about:
    # the extract rungs do not start at tuple index 0.
    assert outcome.attribution[0].pass_name == "triage"


def test_triage_runs_on_its_own_client_when_one_is_given(tmp_path):
    png = tmp_path / "receipt.png"
    _write_png(png)
    triage_client = FakeVLMClient([_triage()], model_id="triage-model")
    extract_client = FakeVLMClient([_good()], model_id="extract-model")

    outcome = run_receipt(png, extract_client, CTX, triage_client=triage_client)

    assert len(triage_client.calls) == 1
    assert triage_client.calls[0]["schema"] == "TriageResult"
    assert len(extract_client.calls) == 1
    assert extract_client.calls[0]["schema"] == "ReceiptExtraction"
    # Beyond the plan: without this the triage attribution entry is pinned by
    # nothing and could be deleted with every gate green.
    triage_entries = [a for a in outcome.attribution if a.pass_name == "triage"]
    assert [(a.model_id, a.rung, a.kept) for a in triage_entries] == [
        ("triage-model", 0, True)
    ]


def test_a_raising_first_rung_falls_back_rather_than_propagating(tmp_path):
    png = tmp_path / "receipt.png"
    _write_png(png)
    first = _RaisingClient(model_id="local")
    fallback = FakeVLMClient([_good()], model_id="cloud")

    outcome = run_receipt(png, first, CTX, triage_client=FakeVLMClient([_triage()]),
                          extract_fallback_client=fallback)

    assert outcome.extraction.merchant.name == "SUPERMART INC."
    # Beyond the plan: without this the raise branch's own attribution entry is
    # pinned by nothing -- a rung that failed would vanish from the record.
    discarded = [a for a in outcome.attribution if a.pass_name == "extract" and not a.kept]
    assert [a.model_id for a in discarded] == ["local"]


def test_a_discarded_rung_records_which_clause_discarded_it(tmp_path):
    """ISSUE-018: the record said a rung was discarded, never why.

    ADR-0047 decision 3 discards on **two** clauses -- the call raised, or the
    extraction read nothing -- and they are different facts about the local
    model. A raise says the box is too slow; a read-nothing says the model
    cannot read the page. `extract_rung_counts` in a real ladder run showed
    granite discarded and the cloud rung kept, and which clause fired was
    unrecoverable from the artifact.

    **Do not infer it from elapsed time.** `VLM_TIMEOUT_S` bounds one HTTP
    attempt and the SDK retries (decision 8), so any elapsed figure covers an
    unknown number of attempts.
    """
    png = tmp_path / "receipt.png"
    _write_png(png)
    first = _RaisingClient(model_id="local")
    fallback = FakeVLMClient([_good()], model_id="cloud")

    outcome = run_receipt(png, first, CTX, triage_client=FakeVLMClient([_triage()]),
                          extract_fallback_client=fallback)

    discarded = [a for a in outcome.attribution if a.pass_name == "extract" and not a.kept]
    assert [(a.model_id, a.discarded) for a in discarded] == [
        ("local", DiscardReason.RAISED)
    ]


def test_a_rung_that_read_nothing_is_distinguishable_from_one_that_raised(tmp_path):
    """The other clause, and the reason this pin is two tests rather than one.

    A single test on one clause would stay green with both construction sites
    setting the same reason -- which is exactly the defect ISSUE-018 describes,
    one step along. These two fail differently.
    """
    png = tmp_path / "receipt.png"
    _write_png(png)
    first = FakeVLMClient([_triage(), _unparseable()], model_id="local")
    fallback = FakeVLMClient([_good()], model_id="cloud")

    outcome = run_receipt(png, first, CTX, extract_fallback_client=fallback)

    discarded = [a for a in outcome.attribution if a.pass_name == "extract" and not a.kept]
    assert [(a.model_id, a.discarded) for a in discarded] == [
        ("local", DiscardReason.READ_NOTHING)
    ]


def test_kept_and_discarded_cannot_disagree(tmp_path):
    """One stored field, not two, so the invariant has nothing to police.

    `kept` was a stored `bool` beside which a reason field would have been a
    second source of the same fact -- and two sources of one fact drift. It is
    now derived: a rung is kept exactly when nothing discarded it. This pins
    the equivalence over every entry a real run produces, including triage.
    """
    png = tmp_path / "receipt.png"
    _write_png(png)
    first = _RaisingClient(model_id="local")
    fallback = FakeVLMClient([_good()], model_id="cloud")

    outcome = run_receipt(png, first, CTX, triage_client=FakeVLMClient([_triage()]),
                          extract_fallback_client=fallback)

    assert outcome.attribution, "no attribution entries -- this would pass vacuously"
    for entry in outcome.attribution:
        assert entry.kept == (entry.discarded is None), (
            f"{entry.pass_name}/{entry.model_id} says kept={entry.kept} with "
            f"discarded={entry.discarded}"
        )


def test_a_raising_last_rung_still_propagates(tmp_path):
    png = tmp_path / "receipt.png"
    _write_png(png)
    with pytest.raises(VLMTransientError):
        run_receipt(png, _RaisingClient(model_id="only"), CTX,
                    triage_client=FakeVLMClient([_triage()]))


def test_only_the_final_rung_spends_its_repair_budget(tmp_path):
    # Spec §2.1. The first rung reads nothing, so it is discarded -- and it must
    # not have spent a repair round getting there. One extract call, no repair.
    png = tmp_path / "receipt.png"
    _write_png(png)
    # The third scripted response is deliberately surplus: with the budget
    # correctly withheld it is never reached, and its presence is what makes a
    # ladder that spends the budget fail on *this* test's assertion rather than
    # on `FakeVLMClient exhausted` from inside the runner.
    first = FakeVLMClient([_triage(), _unparseable(), _good()], model_id="local")
    fallback = FakeVLMClient([_good()], model_id="cloud")

    run_receipt(png, first, CTX, extract_fallback_client=fallback, max_attempts=3)

    # Two calls on the first client: the triage and exactly one extract. A
    # repair round (or a re-extract) would make it three.
    assert len(first.calls) == 2, (
        "the discarded rung spent a repair budget it was never going to use"
    )


def test_with_no_fallback_the_only_rung_still_repairs(tmp_path):
    # The other half of the same rule, reverted separately: one rung is the
    # final rung, so `max_attempts` still buys repair rounds. This is the
    # "nothing configured means today's behaviour" guarantee at the repair level.
    png = tmp_path / "receipt.png"
    _write_png(png)
    client = FakeVLMClient([_triage(), _unparseable(), _good()], model_id="only")

    outcome = run_receipt(png, client, CTX, max_attempts=2)

    assert len(client.calls) == 3, "the sole rung did not get its repair round"
    assert outcome.extraction.merchant.name == "SUPERMART INC."


def test_the_final_rung_is_kept_even_when_it_read_nothing(tmp_path):
    """A receipt neither rung can read comes back empty, not as a raise.

    ``is_last`` is the first half of the keep condition and every other ladder
    test hands the last rung a *good* response, so until this test nothing
    exercised a final rung that read nothing. Deleting ``is_last or`` from
    ``run_receipt`` left the whole suite green: the loop then falls out with
    nothing kept and trips the ``assert outcome is not None`` below it, so an
    unreadable receipt raises a bare ``AssertionError`` where it used to return
    the model's empty answer.

    The empty answer is the one the eval path needs. It scores as a receipt
    nothing was read from, which is a measurement; a raise is a failed run,
    which is a different number in a different column.
    """
    png = tmp_path / "receipt.png"
    _write_png(png)
    first = FakeVLMClient([_triage(), _unparseable()], model_id="local")
    fallback = FakeVLMClient([_unparseable()], model_id="cloud")

    outcome = run_receipt(png, first, CTX, extract_fallback_client=fallback)

    assert len(fallback.calls) == 1
    assert outcome.extraction.merchant.name is None
    assert outcome.extraction.line_items == []
    # The last rung is kept although it read nothing, and the first is still
    # recorded as discarded, so the record says the escalation happened.
    extract_entries = [a for a in outcome.attribution if a.pass_name == "extract"]
    assert [(a.model_id, a.kept) for a in extract_entries] == [
        ("local", False),
        ("cloud", True),
    ]


def test_a_sole_rung_that_read_nothing_is_still_kept(tmp_path):
    """The same guarantee where there is no fallback to escalate to.

    One rung is the final rung, so its empty extraction is the run's answer.
    This is the shape an unconfigured deployment runs in -- the "nothing set
    means today's behaviour" requirement -- and before this test that behaviour
    was a raise away with every gate green.
    """
    png = tmp_path / "receipt.png"
    _write_png(png)
    client = FakeVLMClient([_triage(), _unparseable()], model_id="only")

    outcome = run_receipt(png, client, CTX)

    assert outcome.extraction.merchant.name is None
    extract_entries = [a for a in outcome.attribution if a.pass_name == "extract"]
    assert [(a.model_id, a.kept) for a in extract_entries] == [("only", True)]


def test_the_first_rung_is_judged_before_normalization_fills_the_currency(tmp_path):
    """Design §3.2: the trigger reads the extraction, not the normalized copy.

    ``normalize`` fills ``receipt.currency`` from the configured default, and
    granite's measured output was every field null with ``currency: PHP``
    supplied exactly that way. Judged after normalization that ``PHP`` reads as
    content the model produced: the rung that read nothing is kept, the fallback
    never runs, and the escalation is dead in the one configuration it was built
    for.

    ``default_currency`` is passed here rather than left to the environment. A
    pin that only reddens on a machine whose untracked ``.env`` happens to set
    ``DEFAULT_CURRENCY`` is not a pin -- no ``.env`` is tracked, and this test
    supplies the value that arms the mutation itself.
    """
    png = tmp_path / "receipt.png"
    _write_png(png)
    first = FakeVLMClient([_triage(), _unparseable()], model_id="local")
    fallback = FakeVLMClient([_good()], model_id="cloud")

    outcome = run_receipt(
        png, first, CTX, extract_fallback_client=fallback, default_currency="PHP"
    )

    assert len(fallback.calls) == 1
    assert outcome.extraction.merchant.name == "SUPERMART INC."
    kept = [a for a in outcome.attribution if a.pass_name == "extract" and a.kept]
    assert [a.model_id for a in kept] == ["cloud"]


# --------------------------------------------------------------------------- #
# build_eval_pipeline + eval.harness.run_eval
# --------------------------------------------------------------------------- #


def test_build_eval_pipeline_runs_end_to_end_via_run_eval(tmp_path):
    golden = tmp_path / "golden"
    labels = golden / "labels"
    images = golden / "images"
    labels.mkdir(parents=True)
    images.mkdir(parents=True)

    (labels / "r1.json").write_text(_good().model_dump_json(), encoding="utf-8")
    _write_png(images / "r1.png")

    client = FakeVLMClient([_triage(), _good()])
    pipeline_fn = build_eval_pipeline(client, CTX, images)

    report = run_eval(golden, pipeline_fn, results_dir=tmp_path / "results")

    assert isinstance(report, EvalReport)
    assert report.n_receipts == 1
    assert report.critical_field_accuracy == 1.0
    assert report.line_item_f1 == 1.0
    # The clean receipt scores a perfect 1.000 under real confidence scoring,
    # clearing the auto-approve threshold.
    assert report.n_auto_approved == 1
    assert report.auto_approval_precision == 1.0


def test_build_eval_pipeline_threads_default_currency(tmp_path):
    images = tmp_path / "images"
    _write_png(images / "r1.png")
    client = FakeVLMClient([_triage(), _no_currency()])

    pipeline_fn = build_eval_pipeline(client, CTX, images, default_currency="PHP")
    extraction, _confidence = pipeline_fn(tmp_path / "labels" / "r1.json")

    assert extraction.receipt.currency == "PHP"


def test_build_eval_pipeline_missing_image_raises(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    # No image is written, so the lookup fails before the client is ever called.
    pipeline_fn = build_eval_pipeline(FakeVLMClient([]), CTX, images)

    with pytest.raises(FileNotFoundError):
        pipeline_fn(tmp_path / "labels" / "missing.json")


def test_build_eval_pipeline_records_which_rung_was_kept(tmp_path):
    """The sink is how attribution leaves the adapter.

    ``run_eval``'s ``PipelineFn`` contract is ``(extraction, confidence)`` and
    stays that way (design §6.1), so provenance travels out through a
    caller-owned collector instead of widening it.

    No label file is written: ``pipeline_fn`` reads only the *stem* of the path
    it is handed, and the label itself is ``run_eval``'s business.
    """
    sink: list[PassAttempt] = []
    pipeline_fn = build_eval_pipeline(
        FakeVLMClient([_triage(), _good()], model_id="local"),
        CTX,
        tmp_path,
        attribution_sink=sink,
    )
    _write_png(tmp_path / "r001.png")

    pipeline_fn(tmp_path / "r001.json")

    kept = [a for a in sink if a.pass_name == "extract" and a.kept]
    assert [a.model_id for a in kept] == ["local"]


def test_build_eval_pipeline_forwards_both_rung_clients(tmp_path):
    """The adapter is the only route from a built ladder into a run.

    ``make_pass_clients`` builds the rungs and ``run_receipt`` consumes them;
    nothing joins the two unless this function forwards them. Dropping either
    forwarding leaves the ladder built and never reached -- the shape this
    milestone's own self-review flagged -- so both are pinned here, in one
    assertion over the whole attribution record rather than three loose ones.

    The first rung's response is unparseable, so it reads nothing and is
    discarded; the fallback produces the kept extraction.
    """
    sink: list[PassAttempt] = []
    # Two scripted responses, and correct behaviour consumes exactly one. The
    # surplus is what lets this test print its own message: with the triage
    # forwarding dropped, the triage pass lands on this client, and a
    # one-response script would redden on "FakeVLMClient exhausted" -- a
    # test-authoring failure -- instead of on the attribution below.
    first = FakeVLMClient([_unparseable(), _unparseable()], model_id="local")
    fallback = FakeVLMClient([_good()], model_id="cloud")
    triage_client = FakeVLMClient([_triage()], model_id="triage-model")
    pipeline_fn = build_eval_pipeline(
        first,
        CTX,
        tmp_path,
        triage_client=triage_client,
        extract_fallback_client=fallback,
        attribution_sink=sink,
    )
    _write_png(tmp_path / "r001.png")

    extraction, _confidence = pipeline_fn(tmp_path / "r001.json")

    assert extraction.merchant.name == "SUPERMART INC."
    # One call on the first rung: its extract, and not the triage pass.
    assert len(first.calls) == 1
    assert [(a.pass_name, a.model_id, a.kept) for a in sink] == [
        ("triage", "triage-model", True),
        ("extract", "local", False),
        ("extract", "cloud", True),
    ]


# --------------------------------------------------------------------------- #
# The egress boundary (design §5)
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# THE 2026-08-20 EGRESS RULING WAS REVERSED BY THE OWNER ON 2026-08-25.
#
# The ruling was: "a production upload must not be able to reach the cloud
# through the escalation", and two tests here enforced it -- one over
# `process_receipt`'s signature, one over the source text of `cli` and `worker`.
# Both are replaced below rather than deleted, because the reversal is a
# decision and a deleted test looks like an oversight.
#
# **What changed the owner's mind is measured, and it is in the tree.** On this
# deployment `granite3.2-vision:2b` took 32m12s on one receipt and read its
# printed total of 2,000 as `2.0000`, with a null currency; `gemma4:cloud` read
# the same image correctly in 17.2s. The owner's instruction on 2026-08-25 was
# to keep granite as the first rung and escalate to the cloud when it has not
# answered in five minutes.
#
# **The boundary did not disappear; it moved.** It used to be "the mechanism is
# unreachable". It is now "the mechanism is inert unless a fallback model is
# named in configuration". The tests below pin the new one, and the difference
# matters: a deployment that names no fallback must still be provably incapable
# of a cloud call, which is what `test_no_fallback_configured_means_no_second_rung`
# holds.
# --------------------------------------------------------------------------- #


def test_process_receipt_keeps_a_closed_signature() -> None:
    """The half of the old guard that survives its own ruling.

    ``process_receipt`` now HAS ``extract_fallback_client`` -- that is the
    reversal. What must not come back is ``**kwargs``: with a variadic keyword
    parameter, any rung, client or knob can be passed by name without appearing
    in the signature at all, and every signature-level statement anyone makes
    about this function stops meaning anything. That was true under the old
    ruling and is true under the new one, for different reasons.
    """
    signature = inspect.signature(pipeline.process_receipt)
    assert "extract_fallback_client" in signature.parameters, (
        "process_receipt lost its fallback rung: the owner's 2026-08-25 ruling "
        "is that a slow local model escalates to the cloud"
    )
    kinds = {parameter.kind for parameter in signature.parameters.values()}
    assert inspect.Parameter.VAR_KEYWORD not in kinds, (
        "process_receipt grew **kwargs: anything can be passed by name and no "
        "statement about this signature means anything"
    )


def test_no_fallback_configured_means_no_second_rung() -> None:
    """**The boundary as it now stands, and the one that still protects a
    deployment that wants no cloud egress at all.**

    Escalation is opt-in through `VLM_MODEL_EXTRACT_FALLBACK`. A deployment that
    does not name a fallback model gets exactly one rung, so there is nothing
    for `process_receipt` to escalate *to* and no cloud call it can make through
    this mechanism -- which is what the 2026-08-20 ruling was really protecting,
    and it is preserved for anyone who leaves the setting empty.

    `_env_file=None` is load-bearing: this repository's own `.env` now names a
    fallback, so a Settings built without it would be testing this machine's
    deployment rather than the unconfigured default.
    """
    from receipts.extract.clients.factory import make_pass_clients

    unconfigured = Settings(
        _env_file=None, vlm_provider="ollama", vlm_api_key="k", vlm_model_extract="local"
    )
    assert len(make_pass_clients(unconfigured).extract_rungs) == 1

    configured = unconfigured.model_copy(
        update={"vlm_model_extract_fallback": "cloud-b"}
    )
    assert len(make_pass_clients(configured).extract_rungs) == 2


def test_the_ladder_is_built_in_one_place() -> None:
    """`make_pass_clients` is the only builder, so there is one thing to audit.

    The old guard read `cli` and `worker` as text and forbade the name outright.
    `worker` now names it deliberately. What replaces the ban is a narrower
    claim that is still worth holding: `cli` does NOT build a ladder, so the
    escalation has exactly one construction site in production code and an
    auditor has one place to look.

    Its own 2026-08-21 note applies unchanged and is worth repeating: this reads
    source as text, so a comment naming the builder trips it, and it checks one
    spelling rather than every route to a second rung. That was called an
    enumerated defence then and it still is -- it is kept because one bounded
    place to look is worth something, not because it is airtight.
    """
    assert "make_pass_clients" not in inspect.getsource(cli), (
        "cli.py builds a tier ladder: the escalation should have one "
        "construction site in production code, and it is worker.build_deps"
    )
    assert "make_pass_clients" in inspect.getsource(worker), (
        "worker.py stopped building the ladder, so VLM_MODEL_EXTRACT_FALLBACK "
        "is a setting that changes nothing again -- which is the exact defect "
        "the 2026-08-25 wiring fixed"
    )


# --------------------------------------------------------------------------- #
# The egress boundary, over the whole call graph (design §5)
# --------------------------------------------------------------------------- #

_REPO_ROOT = Path(__file__).resolve().parents[1]

#: The trees the enumeration below reads. Together with ``tests/`` they hold
#: every tracked ``.py`` in the repository -- ``git ls-files "*.py"`` on
#: 2026-08-21: 114 files, 70 under these five roots, 44 under ``tests/``, none
#: anywhere else. ``tests/`` is deliberately excluded: the tests above call
#: ``run_receipt`` with a ladder on purpose, which is what makes it testable.
_NON_TEST_ROOTS: tuple[str, ...] = ("src", "eval", "scripts", "config", "alembic")

#: The permitted call sites, as ``(path from the repo root, name of the
#: outermost def enclosing the call)``. Outermost, not innermost: the call
#: physically sits in the closure ``build_eval_pipeline`` builds and returns,
#: and anything nested inside that function is reachable only *through* it, so
#: it is eval-only for the same reason the function is. Pinning the inner name
#: was tried on 2026-08-21 and reverted -- it made a rename of the closure fail
#: with a message accusing the developer of breaking the user's ruling, which
#: would have been a false claim of exactly the kind ADR-0032 is about.
_PERMITTED_RUN_RECEIPT_CALLERS: frozenset[tuple[str, str]] = frozenset(
    {("src/receipts/pipeline.py", "build_eval_pipeline")}
)


def _run_receipt_aliases(tree: ast.Module) -> set[str]:
    """Every local name in one module that is bound to ``run_receipt``.

    Any import of that name counts, whatever module it is taken from and
    whatever it is renamed to, so ``from receipts.pipeline import run_receipt as
    r`` binds ``r``. ``run_receipt`` is always in the set: it is the name in the
    module that defines the function, and the name a plain import binds.
    """
    aliases = {"run_receipt"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "run_receipt":
                    aliases.add(alias.asname or alias.name)
    return aliases


def _names_run_receipt(func: ast.expr, aliases: set[str]) -> bool:
    """Does this callee expression statically name ``run_receipt``?"""
    if isinstance(func, ast.Name):
        return func.id in aliases
    if isinstance(func, ast.Attribute):
        # ``pipeline.run_receipt(...)`` and every other object it could hang
        # off. Over-broad on purpose -- see the test's docstring.
        return func.attr == "run_receipt"
    return False


def _collect_calls(
    node: ast.AST,
    chain: tuple[str, ...],
    aliases: set[str],
    found: list[tuple[tuple[str, ...], int]],
) -> None:
    """Walk one tree, recording each ``run_receipt`` call with its def chain."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            _collect_calls(child, chain + (child.name,), aliases, found)
            continue
        if isinstance(child, ast.Call) and _names_run_receipt(child.func, aliases):
            found.append((chain, child.lineno))
        _collect_calls(child, chain, aliases, found)


def _run_receipt_call_sites() -> list[tuple[str, str, str, int]]:
    """Every static ``run_receipt`` call site in the non-test trees.

    Returns ``(path from the repo root, outermost enclosing def, full dotted
    chain of enclosing defs, line number)``. Both name fields are
    ``"<module>"`` for a call at module level. The property is compared on the
    outermost name; the chain and the line are there so a failure says where.
    """
    sites: list[tuple[str, str, str, int]] = []
    for root in _NON_TEST_ROOTS:
        for path in sorted((_REPO_ROOT / root).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            found: list[tuple[tuple[str, ...], int]] = []
            _collect_calls(tree, (), _run_receipt_aliases(tree), found)
            relative = path.relative_to(_REPO_ROOT).as_posix()
            sites.extend(
                (relative, chain[0] if chain else "<module>", ".".join(chain) or "<module>", line)
                for chain, line in found
            )
    return sites


def test_run_receipt_is_called_only_by_build_eval_pipeline() -> None:
    """The egress boundary's second claim, pinned over the call graph.

    Design §5 makes two claims. ``test_process_receipt_has_no_ladder_parameter``
    above pins the first; this pins the second, which until 2026-08-21 was
    pinned by nothing: **the set of non-test call sites of ``run_receipt`` is
    exactly ``{build_eval_pipeline}``**.

    ``run_receipt`` is where the ladder parameters live, so any production
    module that calls it reaches the cloud escalation regardless of what
    ``process_receipt``'s signature says -- and one could: a function added to
    ``src/receipts/worker.py`` calling ``run_receipt(...,
    extract_fallback_client=...)`` left the whole suite green. Measured
    2026-08-21 with that function present and this test deselected: 1278
    passed, the signature pin and this file's own text guard included.

    Enumerated from the **AST** of every ``.py`` under ``src/``, ``eval/``,
    ``scripts/``, ``config/`` and ``alembic/``, not from a text search. A call
    counts when its callee is a bare name bound to ``run_receipt`` -- including
    through a rename, ``from receipts.pipeline import run_receipt as r`` -- or
    any attribute named ``run_receipt``, which is how ``pipeline.run_receipt``
    reads. Prose is invisible to it: a comment or a docstring naming the
    function is not a call, so it does not fail this test -- demonstrated by
    mutation, and by ``pipeline.py``'s own docstrings, which name
    ``run_receipt`` repeatedly while this stays green.

    That is the difference an AST walk makes over a text search, and it is the
    cost ``test_the_production_modules_do_not_build_a_ladder`` accepts and
    states. That guard is not replaced or subsumed here: it reads for a
    *different* name, ``make_pass_clients``, and neither test would catch what
    the other does. Two properties, side by side.

    What this cannot see
    --------------------
    Static reach ends at a name. ``getattr(pipeline, "run_" + "receipt")``,
    ``globals()["run_receipt"]``, an ``importlib`` lookup, or the function
    handed in as an argument all pass this test. Also flagging the *string
    literal* ``"run_receipt"`` in these modules would cost nothing measurable
    today -- probed 2026-08-21 over the 70 modules these five roots hold, as an
    ``ast.Constant`` string equal to ``run_receipt``: zero occurrences, so zero
    false positives -- and is deliberately not done. It would close one spelling
    of a route that has unboundedly many, which is the enumerated defence review
    standard 19 names, and imply a class was closed that is not. The bound is
    stated instead, and it is: **every route that names ``run_receipt``
    statically**.

    Over-approximation is deliberate in the other direction. Any attribute call
    named ``run_receipt`` counts, whatever object it hangs off, so an unrelated
    method of that name anywhere in these trees would fail here. There is none
    today; the cost of that being wrong is one rename, and the cost of missing
    one is the production path reaching the cloud with every gate green.

    As with §5.1, this does not claim production cannot reach a cloud model at
    all -- configuration can still point its single client at one. The claim is
    only that *this mechanism* has no non-eval caller.
    """
    for root in _NON_TEST_ROOTS:
        assert (_REPO_ROOT / root).is_dir(), (
            f"{root}/ is gone, so this enumeration silently reads no files "
            f"there and would pass over anything it contains"
        )

    sites = _run_receipt_call_sites()
    found = {(module, outermost) for module, outermost, _chain, _line in sites}

    unexpected = sorted(
        f"{module}:{line} in {chain}"
        for module, outermost, chain, line in sites
        if (module, outermost) not in _PERMITTED_RUN_RECEIPT_CALLERS
    )
    assert not unexpected, (
        "run_receipt carries the extract ladder, so every caller of it is a way "
        "to the cloud. The 2026-08-20 ruling permits exactly one -- "
        f"build_eval_pipeline -- and these are not it: {'; '.join(unexpected)}. "
        "If a new caller is genuinely eval-only, add it to "
        "_PERMITTED_RUN_RECEIPT_CALLERS deliberately; if it is on the "
        "production path, it is the thing the ruling forbids"
    )
    missing = sorted(_PERMITTED_RUN_RECEIPT_CALLERS - found)
    assert not missing, (
        f"build_eval_pipeline no longer calls run_receipt at {missing}: either "
        f"the eval path was rewired, in which case update this enumeration, or "
        f"the walk stopped reading that file, in which case it now proves "
        f"nothing at all"
    )
