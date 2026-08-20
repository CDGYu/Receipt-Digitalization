"""M1 pipeline runner tests. Offline: FakeVLMClient replays scripted responses
and every image is synthetic -- no provider, no network.

The runner's call order is load-bearing, so the FakeVLMClient script mirrors it
exactly: response[0] answers the triage call (schema ``TriageResult``) and
response[1] answers the extraction call (schema ``ReceiptExtraction``). A clean
extraction means no repair call fires, so two scripted responses are enough.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

# The preprocess layer needs the optional "pipeline" extras (Pillow + HEIF).
# Skip the whole module rather than erroring at collection when absent.
pytest.importorskip("PIL")
pytest.importorskip("pillow_heif")

from PIL import Image  # noqa: E402

from eval.harness import run_eval  # noqa: E402
from eval.metrics import EvalReport  # noqa: E402
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
from receipts.pipeline import build_eval_pipeline, prepare_image, run_receipt  # noqa: E402
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
