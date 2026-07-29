"""``process_receipt`` -- the one function the queue worker calls (spec §14.10).

Everything here is offline: a scripted in-process client, a temp-directory
:class:`LocalStorage`, and a file-backed SQLite database. No provider, no Redis,
no network.

The load-bearing behaviours pinned down below:

  * **Nothing is silently dropped** (§18). A failure injected into *every* stage
    still leaves a receipt row in a terminal state, ``needs_review``, with the
    failing stage named in the reason and a review task waiting -- one test per
    stage, because "the pipeline is wrapped" is exactly the claim that rots.
  * The stored report and the stored score describe the **same object**:
    validation runs on the normalized extraction, so an ambiguous date that the
    normalizer parks in ``date_raw`` is scored and explained consistently.
  * Money round-trips as ``Decimal`` (ADR-0001) and a full PAN never reaches
    ``extraction_runs.raw_response`` (ADR-0007).
  * ``save_extraction`` does not write findings, so the pipeline calls
    ``save_findings`` itself; one audit row per model call is written too.
"""

from __future__ import annotations

import io
import json
import random
import uuid
from datetime import date
from decimal import Decimal as D

import pytest

pytest.importorskip("PIL")
pytest.importorskip("pillow_heif")

from PIL import Image, ImageDraw  # noqa: E402
from sqlalchemy import select  # noqa: E402

from config.settings import Settings  # noqa: E402
from receipts import pipeline as pipeline_module  # noqa: E402
from receipts.extract.clients.base import VLMClient, VLMResponse  # noqa: E402
from receipts.extract.clients.limits import CostGuard, VLMGate, reset_vlm_gate  # noqa: E402
from receipts.extract.schema import (  # noqa: E402
    DocumentType,
    Legibility,
    Merchant,
    ReceiptExtraction,
    ReceiptMeta,
    Totals,
    TriageResult,
)
from receipts.extract.schema import LineItem as ExtractedLineItem  # noqa: E402
from receipts.ingest.ingest import ReceiptJob  # noqa: E402
from receipts.ingest.storage import LocalStorage, make_image_key  # noqa: E402
from receipts.persist.models import (  # noqa: E402
    Base,
    Correction,
    ExtractionRun,
    Receipt,
    ReviewState,
    ReviewTask,
    ValidationFinding,
)
from receipts.persist.repository import (  # noqa: E402
    apply_corrections,
    create_pending_receipt,
)
from receipts.persist.session import make_engine, make_session_factory  # noqa: E402
from receipts.pipeline import STAGES, ProcessResult, process_batch, process_receipt  # noqa: E402
from receipts.score.confidence import ReceiptStatus  # noqa: E402
from receipts.validate.context import ValidationContext  # noqa: E402

CTX = ValidationContext(today=date(2026, 7, 26))


# --------------------------------------------------------------------------- #
# Fixtures and doubles
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _fresh_global_gate():
    reset_vlm_gate()
    yield
    reset_vlm_gate()


@pytest.fixture()
def settings() -> Settings:
    """Hermetic settings: a developer's ``.env`` must not steer these tests."""
    return Settings(_env_file=None, max_repair_attempts=1)


@pytest.fixture()
def session_factory(tmp_path):
    """A file-backed SQLite database, so several sessions (and threads) share it."""
    engine = make_engine(f"sqlite:///{(tmp_path / 'receipts.db').as_posix()}")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)


@pytest.fixture()
def storage(tmp_path) -> LocalStorage:
    return LocalStorage(tmp_path / "blobs")


def _png_bytes(seed: int = 0, size: tuple[int, int] = (900, 1400)) -> bytes:
    """A deterministic PNG with enough structure to have a distinctive dHash.

    A flat image is useless here: every uniform bitmap hashes to the same 64
    zero bits, so two unrelated receipts would look like duplicates.
    """
    rng = random.Random(seed)
    image = Image.new("RGB", size, (240, 240, 240))
    draw = ImageDraw.Draw(image)
    for _ in range(24):
        left = rng.randrange(0, size[0] - 120)
        top = rng.randrange(0, size[1] - 120)
        shade = rng.randrange(0, 200)
        draw.rectangle(
            [left, top, left + rng.randrange(20, 120), top + rng.randrange(20, 120)],
            fill=(shade, shade, shade),
        )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture(params=["insert", "update"])
def existing_row(request, session_factory):
    """Whether the receipt already has the ``pending`` row ``POST /upload`` writes.

    Returns a callable that takes a job and hands it back, having created that
    row (or not) first, so a test reads ``job = existing_row(_job(storage))``.

    Both branches of ``save_extraction`` must behave identically, and only one of
    them used to be exercised: every stage-failure test built a fresh id, so all
    eight took the **insert** branch -- while production, ever since the pending
    row landed at upload, always takes the **update** branch. That gap is where
    three separate defects hid (a reviewed row silently overwritten, a
    duplicate-linked receipt destroyed on reprocess, and stale
    ``confidence_reasons`` left beside a score the row no longer had).
    """

    def prepare(job: ReceiptJob) -> ReceiptJob:
        if request.param == "update":
            with session_factory() as session:
                create_pending_receipt(session, job)
                session.commit()
        return job

    return prepare


def _job(storage: LocalStorage, data: bytes | None = None) -> ReceiptJob:
    receipt_id = uuid.uuid4()
    key = make_image_key(receipt_id, "original")
    storage.put(key, _png_bytes() if data is None else data, "image/png")
    return ReceiptJob(
        id=receipt_id,
        image_key=key,
        source="test",
        original_filename="receipt.png",
        content_type="image/png",
    )


class _Client(VLMClient):
    """Scripted client.

    Each script entry is a pydantic model (returned as ``parsed``), a ``str``
    (returned as ``parse_error``), or a ``BaseException`` (raised, which is how
    a stage failure is injected).
    """

    def __init__(self, script, *, raw=None, cost: D = D("0.01")) -> None:
        self.model_id = "fake-vlm"
        self.script = list(script)
        self.raw = raw
        self.cost = cost
        self.calls: list[str] = []

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        images,
        schema,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        tool_name: str = "record_extraction",
        tool_description: str = "",
    ) -> VLMResponse:
        index = len(self.calls)
        self.calls.append(schema.__name__)
        if index >= len(self.script):
            raise AssertionError(f"client exhausted at call {index + 1}")
        item = self.script[index]
        if isinstance(item, BaseException):
            raise item

        response = VLMResponse(
            parsed=None,
            raw={"scripted": index} if self.raw is None else self.raw,
            model_id=self.model_id,
            input_tokens=1500,
            output_tokens=400,
            latency_ms=10,
            cost_usd=self.cost,
        )
        if isinstance(item, str):
            response.parse_error = item
        else:
            response.parsed = item
        return response


def _triage() -> TriageResult:
    return TriageResult(
        document_type=DocumentType.POS_RECEIPT,
        legibility=Legibility.GOOD,
        estimated_line_item_count=2,
    )


def _good() -> ReceiptExtraction:
    """A clean, self-consistent extraction (mirrors tests/test_pipeline.py)."""
    return ReceiptExtraction(
        merchant=Merchant(name="SUPERMART INC."),
        receipt=ReceiptMeta(date="2026-07-20", currency="PHP"),
        line_items=[
            ExtractedLineItem(position=0, description_raw="RICE 5KG", qty=D("1"),
                              unit_price=D("100.00"), line_total=D("100.00")),
            ExtractedLineItem(position=1, description_raw="OIL 1L", qty=D("2"),
                              unit_price=D("50.00"), line_total=D("100.00")),
        ],
        totals=Totals(subtotal=D("200.00"), tax=D("24.00"), discount=D("0.00"),
                      total=D("224.00")),
    )


def _ambiguous_date() -> ReceiptExtraction:
    """Clean apart from a DD/MM-vs-MM/DD date the normalizer must park."""
    extraction = _good()
    extraction.receipt.date = "03/04/2026"
    return extraction


def _broken_totals() -> ReceiptExtraction:
    """Totals that cannot reconcile -- guaranteed ERROR findings."""
    extraction = _good()
    extraction.totals.total = D("999.00")
    return extraction


def _run(job, client, session_factory, storage, settings, **kwargs) -> ProcessResult:
    return process_receipt(
        job,
        client=client,
        storage=storage,
        session_factory=session_factory,
        ctx=CTX,
        settings=settings,
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


def test_clean_receipt_is_persisted_and_auto_approved(session_factory, storage, settings):
    job = _job(storage)
    client = _Client([_triage(), _good()])

    result = _run(job, client, session_factory, storage, settings)

    assert isinstance(result, ProcessResult)
    assert result.receipt_id == job.id
    assert result.status is ReceiptStatus.AUTO_APPROVED
    assert result.failed_stage is None
    assert client.calls == ["TriageResult", "ReceiptExtraction"]

    with session_factory() as session:
        receipt = session.get(Receipt, job.id)
        assert receipt is not None
        assert receipt.status is ReceiptStatus.AUTO_APPROVED
        assert receipt.merchant_name_raw == "SUPERMART INC."
        assert receipt.txn_date == date(2026, 7, 20)
        assert receipt.image_key == job.image_key
        assert receipt.image_phash  # dedupe needs it on every row
        assert len(receipt.line_items) == 2
        # Money survives as an exact Decimal (ADR-0001).
        assert receipt.total == D("224.00")
        assert isinstance(receipt.total, D)
        assert isinstance(receipt.line_items[0].line_total, D)
        # Auto-approved work never reaches the review queue.
        assert session.scalars(select(ReviewTask)).all() == []


def test_every_model_call_gets_an_audit_row(session_factory, storage, settings):
    job = _job(storage)
    client = _Client([_triage(), _good()])

    _run(job, client, session_factory, storage, settings)

    with session_factory() as session:
        runs = session.scalars(
            select(ExtractionRun).where(ExtractionRun.receipt_id == job.id)
        ).all()
        assert [run.pass_name.value for run in runs] == ["triage", "extract"]
        assert all(run.prompt_hash for run in runs)
        assert all(run.cost_usd == D("0.01") for run in runs)
        assert all(isinstance(run.cost_usd, D) for run in runs)


def test_full_pan_never_reaches_the_raw_response(session_factory, storage, settings):
    # ADR-0007: redaction happens inside save_extraction_run and the pipeline
    # must not route around it.
    job = _job(storage)
    client = _Client([_triage(), _good()], raw={"text": "CARD NO.4111111111111111"})

    _run(job, client, session_factory, storage, settings)

    with session_factory() as session:
        runs = session.scalars(
            select(ExtractionRun).where(ExtractionRun.receipt_id == job.id)
        ).all()
        blob = json.dumps([run.raw_response for run in runs])
        assert "4111111111111111" not in blob
        assert "1111" in blob  # the last four survive


def test_findings_are_written_and_a_review_task_is_opened(session_factory, storage, settings):
    job = _job(storage)
    # An unreconcilable total produces ERROR findings, so a repair round runs.
    client = _Client([_triage(), _broken_totals(), _broken_totals()])

    result = _run(job, client, session_factory, storage, settings)

    assert result.status is ReceiptStatus.NEEDS_REVIEW
    with session_factory() as session:
        findings = session.scalars(
            select(ValidationFinding).where(ValidationFinding.receipt_id == job.id)
        ).all()
        # save_extraction does NOT write findings; the pipeline must.
        assert findings
        # Rule ids are stored verbatim and never renumbered.
        assert all(finding.rule_id.startswith("R") for finding in findings)

        task = session.scalars(select(ReviewTask)).one()
        assert task.receipt_id == job.id
        assert task.priority >= 0


def test_repair_resolved_findings_are_kept_as_history(session_factory, storage, settings):
    """Findings accumulate across passes via ``resolved_by_repair``.

    The best attempt here is the repair, which is clean -- so the only findings
    worth storing are the originals the repair fixed. Storing them (rather than
    letting the successful pass erase the record) is what makes the repair loop
    measurable later.
    """
    job = _job(storage)
    client = _Client([_triage(), _broken_totals(), _good()])

    result = _run(job, client, session_factory, storage, settings)

    assert result.status is ReceiptStatus.AUTO_APPROVED
    with session_factory() as session:
        findings = session.scalars(
            select(ValidationFinding).where(ValidationFinding.receipt_id == job.id)
        ).all()
        assert findings
        assert all(finding.resolved_by_repair for finding in findings)

        runs = session.scalars(
            select(ExtractionRun).where(ExtractionRun.receipt_id == job.id)
        ).all()
        assert [run.pass_name.value for run in runs] == ["triage", "extract", "repair"]
        # Each pass logs the hash of the prompt it actually used, so the repair
        # row must not simply repeat the extraction prompt's hash.
        assert runs[1].prompt_hash != runs[2].prompt_hash


def test_reprocessing_a_persisted_job_updates_the_row_in_place(
    session_factory, storage, settings
):
    """A re-run of an id that already has a row must not vanish -- or duplicate.

    ``save_extraction`` is update-or-insert (P4.T3): a pending row written at
    upload, or a previous run's row, is updated rather than re-inserted, so a
    retry writes fresh data over the old row instead of colliding on the
    primary key. That collision used to route a retry to ``needs_review``
    purely because it had already been processed once -- an update in place is
    strictly better, since the second run's own result (here, a clean
    auto-approval) is what ends up stored. (``receipts reprocess <id>`` is the
    operator-facing form of this same re-run; it adds a status gate -- refusing
    an ``auto_approved`` row without ``--force`` -- on top of the refusal
    exercised here, which no flag can lift, see
    ``test_a_worker_run_never_overwrites_a_reviewed_receipt``.)
    """
    job = _job(storage)
    _run(job, _Client([_triage(), _good()]), session_factory, storage, settings)

    again = _run(job, _Client([_triage(), _good()]), session_factory, storage, settings)

    assert again.status is ReceiptStatus.AUTO_APPROVED
    with session_factory() as session:
        rows = session.scalars(select(Receipt).where(Receipt.id == job.id)).all()
        assert len(rows) == 1


# --------------------------------------------------------------------------- #
# The raw-report / normalized-extraction reconciliation
# --------------------------------------------------------------------------- #


def test_report_and_score_describe_the_same_normalized_extraction(
    session_factory, storage, settings
):
    """An ambiguous date is parked by ``normalize``; validation must see that.

    Validating the *raw* extraction would report R030 ("not ISO 8601") -- an
    ERROR that both triggers a pointless repair round and leaves the stored
    score's date-null penalty unexplained by the stored report. Validating the
    normalized extraction instead yields R011 at INFO ("acceptable if the
    printed date is genuinely ambiguous"), which is what the persisted row
    actually looks like.
    """
    job = _job(storage)
    client = _Client([_triage(), _ambiguous_date()])

    result = _run(job, client, session_factory, storage, settings)

    # No ERROR, so no repair round was spent second-guessing a parked date.
    assert client.calls == ["TriageResult", "ReceiptExtraction"]

    with session_factory() as session:
        receipt = session.get(Receipt, job.id)
        assert receipt.txn_date is None
        assert receipt.date_raw == "03/04/2026"

        rule_ids = {
            finding.rule_id
            for finding in session.scalars(
                select(ValidationFinding).where(ValidationFinding.receipt_id == job.id)
            )
        }
        assert "R011" in rule_ids  # explains the missing date
        assert "R030" not in rule_ids  # never validated the pre-normalization value

    # Only the date-null penalty (-0.10) applies, so the receipt still clears
    # the auto-approve threshold -- the score and the report agree.
    assert result.confidence == D("0.900")
    assert result.status is ReceiptStatus.AUTO_APPROVED


# --------------------------------------------------------------------------- #
# Dedupe
# --------------------------------------------------------------------------- #


def test_duplicate_image_is_linked_without_spending_a_model_call(
    session_factory, storage, settings, existing_row
):
    data = _png_bytes()
    first = _run(existing_row(_job(storage, data)), _Client([_triage(), _good()]),
                 session_factory, storage, settings)

    second_job = existing_row(_job(storage, data))
    second_client = _Client([])  # any model call would raise
    second = _run(second_job, second_client, session_factory, storage, settings)

    assert second_client.calls == []
    assert second.duplicate_of == first.receipt_id
    assert second.status is ReceiptStatus.REJECTED

    with session_factory() as session:
        row = session.get(Receipt, second_job.id)
        assert row.duplicate_of == first.receipt_id
        # The *row* is terminal, not just the returned result -- over a pending
        # row that means save_extraction's update branch actually applied the
        # rejected status rather than leaving the upload's `pending`.
        assert row.status is ReceiptStatus.REJECTED
        assert row.image_phash
        # A duplicate is terminal and must not clutter the review queue.
        assert session.scalars(select(ReviewTask)).all() == []


def test_reprocessing_a_receipt_that_already_has_a_duplicate_keeps_it_intact(
    session_factory, storage, settings
):
    """``A`` processed, ``B`` uploaded as the same image, then ``A`` re-run.

    Dedupe used to exclude only ``job.id``, and it ran even for a receipt that
    already held an extraction -- so the reprocessed original matched the copy
    pointing *at* it and was itself marked a duplicate of it: ``A`` became
    ``rejected`` with no total, no merchant and no line items, ``duplicate_of =
    B``. That is the ``A <-> B`` cycle ``mark_duplicate``'s docstring promises
    cannot happen, and since both rows are then ``rejected`` **both** drop out
    of ``GET /export/xlsx`` by default: the transaction leaves the ledger with
    nothing left pointing at it.
    """
    data = _png_bytes()
    original = _job(storage, data)
    first = _run(original, _Client([_triage(), _good()]), session_factory, storage, settings)
    assert first.status is ReceiptStatus.AUTO_APPROVED

    copy = _run(_job(storage, data), _Client([]), session_factory, storage, settings)
    assert copy.duplicate_of == original.id

    again = _run(original, _Client([_triage(), _good()]), session_factory, storage, settings)

    assert again.status is ReceiptStatus.AUTO_APPROVED
    assert again.duplicate_of is None
    with session_factory() as session:
        receipt = session.get(Receipt, original.id)
        assert receipt.status is ReceiptStatus.AUTO_APPROVED
        assert receipt.duplicate_of is None
        assert receipt.total == D("224.00")
        assert receipt.merchant_name_raw == "SUPERMART INC."
        assert len(receipt.line_items) == 2
        # The copy is untouched, and the chain still runs copy -> original.
        assert session.get(Receipt, copy.receipt_id).duplicate_of == original.id


def test_reprocessing_a_duplicate_re_establishes_the_same_link(
    session_factory, storage, settings
):
    """The other side of the skip rule: a ``rejected`` row is still deduped.

    ``rejected`` is the pipeline's own marking for a copy, not an extraction of
    that receipt's own content, so re-running one must find the original again
    (and spend no model call) rather than skip dedupe and extract over the link.
    """
    data = _png_bytes()
    original = _job(storage, data)
    _run(original, _Client([_triage(), _good()]), session_factory, storage, settings)

    copy_job = _job(storage, data)
    _run(copy_job, _Client([]), session_factory, storage, settings)

    client = _Client([])  # any model call would raise
    again = _run(copy_job, client, session_factory, storage, settings)

    assert client.calls == []
    assert again.status is ReceiptStatus.REJECTED
    assert again.duplicate_of == original.id
    with session_factory() as session:
        assert session.get(Receipt, copy_job.id).duplicate_of == original.id


# --------------------------------------------------------------------------- #
# A machine run never overwrites a human's review
# --------------------------------------------------------------------------- #


def test_a_worker_run_never_overwrites_a_reviewed_receipt(
    session_factory, storage, settings
):
    """The upload -> review -> worker race, end to end.

    ``POST /upload`` commits the ``pending`` row *before* it queues, and
    ``GET /receipts`` lists pending rows -- that visibility is the point of the
    row. So with the queue backed up a reviewer can open the receipt and re-key
    it off the paper, and the worker then arrives holding a machine extraction
    of the same id. Applying it would break three invariants at once: the
    correction is silently dropped, a receipt a human reviewed reverts to
    ``auto_approved`` (and exports as an approved transaction carrying a number
    the reviewer rejected), and the ``corrections`` audit trail contradicts the
    row it describes.
    """
    job = _job(storage)
    with session_factory() as session:
        create_pending_receipt(session, job)
        session.commit()

    with session_factory() as session:
        apply_corrections(
            session,
            job.id,
            {"totals": {"total": "999.99"}, "merchant": {"name": "HAND-KEYED CO"}},
            corrected_by="alice",
        )

    result = _run(job, _Client([_triage(), _good()]), session_factory, storage, settings)

    with session_factory() as session:
        receipt = session.get(Receipt, job.id)
        # Exactly as the human left it.
        assert receipt.status is ReceiptStatus.REVIEWED
        assert receipt.total == D("999.99")
        assert receipt.merchant_name_raw == "HAND-KEYED CO"
        corrections = session.scalars(select(Correction)).all()
        assert len(corrections) == 2
        assert {row.value_after for row in corrections} == {"999.99", "HAND-KEYED CO"}

        # ...and the attempt is visible, not silent: a task naming the stage,
        # why the write was refused, and what the run produced.
        task = session.scalars(select(ReviewTask).where(ReviewTask.receipt_id == job.id)).one()
        assert task.state is ReviewState.OPEN
        assert "persist" in task.reason
        assert "reviewed" in task.reason
        assert "224" in task.reason

    # The receipt is still terminal, and the result describes the actual row
    # rather than claiming a needs_review it is not in.
    assert result.status is ReceiptStatus.REVIEWED
    assert result.failed_stage == "persist"


# --------------------------------------------------------------------------- #
# No silent drops: one injected failure per stage (§18)
# --------------------------------------------------------------------------- #


def _assert_terminal_needs_review(result, session_factory, stage: str) -> None:
    assert result.status is ReceiptStatus.NEEDS_REVIEW, f"{stage}: not terminal"
    assert result.failed_stage == stage
    assert stage in result.reason
    with session_factory() as session:
        receipt = session.get(Receipt, result.receipt_id)
        assert receipt is not None, f"{stage}: the receipt vanished"
        assert receipt.status is ReceiptStatus.NEEDS_REVIEW
        task = session.scalars(
            select(ReviewTask).where(ReviewTask.receipt_id == result.receipt_id)
        ).one()
        assert stage in task.reason


def test_stage_names_are_declared_in_order():
    assert STAGES == (
        "load", "preprocess", "dedupe", "triage", "extract", "normalize", "score", "persist",
    )


def test_load_failure_reaches_needs_review(session_factory, storage, settings, existing_row):
    class _BrokenStorage(LocalStorage):
        def get(self, key: str) -> bytes:
            raise OSError("blob store unreachable")

    broken = _BrokenStorage(storage.root)
    job = existing_row(_job(storage))
    result = _run(job, _Client([]), session_factory, broken, settings)

    _assert_terminal_needs_review(result, session_factory, "load")


def test_preprocess_failure_reaches_needs_review(
    session_factory, storage, settings, existing_row
):
    job = existing_row(_job(storage, b"this is not an image"))
    result = _run(job, _Client([]), session_factory, storage, settings)

    _assert_terminal_needs_review(result, session_factory, "preprocess")


def test_dedupe_failure_reaches_needs_review(
    session_factory, storage, settings, monkeypatch, existing_row
):
    def boom(*args, **kwargs):
        raise RuntimeError("phash index offline")

    monkeypatch.setattr(pipeline_module, "find_duplicate_by_phash", boom)
    job = existing_row(_job(storage))
    result = _run(job, _Client([]), session_factory, storage, settings)

    _assert_terminal_needs_review(result, session_factory, "dedupe")


def test_triage_failure_reaches_needs_review(
    session_factory, storage, settings, existing_row
):
    job = existing_row(_job(storage))
    result = _run(job, _Client([RuntimeError("triage exploded")]),
                  session_factory, storage, settings)

    _assert_terminal_needs_review(result, session_factory, "triage")


def test_extract_failure_reaches_needs_review(
    session_factory, storage, settings, existing_row
):
    job = existing_row(_job(storage))
    client = _Client([_triage(), RuntimeError("extract exploded")])
    result = _run(job, client, session_factory, storage, settings)

    _assert_terminal_needs_review(result, session_factory, "extract")


def test_normalize_failure_reaches_needs_review(
    session_factory, storage, settings, monkeypatch, existing_row
):
    def boom(*args, **kwargs):
        raise RuntimeError("normalizer exploded")

    monkeypatch.setattr(pipeline_module, "normalize", boom)
    job = existing_row(_job(storage))
    result = _run(job, _Client([_triage(), _good()]), session_factory, storage, settings)

    # The failure happened inside the repair loop's normalize hook, and it is
    # still attributed to `normalize` rather than to the enclosing stage.
    _assert_terminal_needs_review(result, session_factory, "normalize")


def test_score_failure_reaches_needs_review(
    session_factory, storage, settings, monkeypatch, existing_row
):
    def boom(*args, **kwargs):
        raise RuntimeError("scorer exploded")

    monkeypatch.setattr(pipeline_module, "score_confidence", boom)
    job = existing_row(_job(storage))
    result = _run(job, _Client([_triage(), _good()]), session_factory, storage, settings)

    _assert_terminal_needs_review(result, session_factory, "score")


def test_persist_failure_reaches_needs_review(
    session_factory, storage, settings, monkeypatch, existing_row
):
    def boom(*args, **kwargs):
        raise RuntimeError("findings table gone")

    monkeypatch.setattr(pipeline_module, "save_findings", boom)
    job = existing_row(_job(storage))
    result = _run(job, _Client([_triage(), _good()]), session_factory, storage, settings)

    # Even a half-written transaction is rolled back and replaced by a terminal
    # row -- a job that fails is far better than one that vanishes.
    _assert_terminal_needs_review(result, session_factory, "persist")


def test_a_job_is_never_dropped_silently_when_the_database_is_unreachable(storage, settings):
    """The only case that may raise: nothing could be written at all.

    Raising hands the job back to the queue's failed registry. Returning
    "success" here would be the silent drop §18 forbids.
    """

    def no_session():
        raise RuntimeError("database unreachable")

    job = _job(storage)
    with pytest.raises(RuntimeError, match="database unreachable"):
        _run(job, _Client([_triage(), _good()]), no_session, storage, settings)


# --------------------------------------------------------------------------- #
# Concurrency cap and cost guard
# --------------------------------------------------------------------------- #


def test_every_model_call_goes_through_the_concurrency_gate(
    session_factory, storage, settings
):
    gate = VLMGate(limit=1)
    job = _job(storage)

    _run(job, _Client([_triage(), _good()]), session_factory, storage, settings, gate=gate)

    # Zero would mean the gate was never entered, i.e. the cap is decorative.
    assert gate.peak_in_flight == 1


def test_cost_ceiling_stops_the_run_cleanly_at_needs_review(
    session_factory, storage, settings
):
    job = _job(storage)
    client = _Client([_triage(), _good()], cost=D("0.01"))
    guard = CostGuard(ceiling=D("0.005"))

    result = _run(job, client, session_factory, storage, settings, cost_guard=guard)

    # Triage was paid for; the extract call is refused before it is made.
    assert client.calls == ["TriageResult"]
    assert guard.spent == D("0.01")
    _assert_terminal_needs_review(result, session_factory, "extract")
    assert "cost" in result.reason.lower()


def test_result_reports_what_the_run_cost(session_factory, storage, settings):
    job = _job(storage)
    result = _run(job, _Client([_triage(), _good()], cost=D("0.02")),
                  session_factory, storage, settings)

    assert result.cost_usd == D("0.04")
    assert isinstance(result.cost_usd, D)


# --------------------------------------------------------------------------- #
# process_batch (§14.10)
# --------------------------------------------------------------------------- #


def test_process_batch_processes_every_path_and_reports_rejects(
    tmp_path, session_factory, storage, settings
):
    good_paths = []
    for index in range(3):
        path = tmp_path / f"receipt_{index}.png"
        # Distinct pixel content so the perceptual hashes differ and nothing is
        # mistaken for a duplicate.
        path.write_bytes(_png_bytes(seed=index))
        good_paths.append(path)

    bad = tmp_path / "notes.txt"
    bad.write_text("not a receipt", encoding="utf-8")

    def client_factory() -> VLMClient:
        return _Client([_triage(), _good()])

    batch = process_batch(
        [*good_paths, bad],
        client_factory=client_factory,
        storage=storage,
        session_factory=session_factory,
        ctx=CTX,
        settings=settings,
        workers=2,
    )

    assert len(batch.processed) == 3
    assert all(isinstance(item, ProcessResult) for item in batch.processed)
    assert len(batch.rejected) == 1
    assert batch.rejected[0][0].endswith("notes.txt")
    assert batch.total_cost_usd == D("0.06")
    assert batch.counts[ReceiptStatus.AUTO_APPROVED] == 3


# --------------------------------------------------------------------------- #
# confidence_reasons (P4.T3)
# --------------------------------------------------------------------------- #


def test_persisted_reasons_sum_to_the_persisted_confidence(session_factory, storage, settings):
    """The breakdown a reviewer is shown must add up to the score it explains."""
    job = _job(storage)
    penalised = _good()
    penalised.meta.legibility = Legibility.POOR
    penalised.meta.is_handwritten = True
    client = _Client([_triage(), penalised])

    _run(job, client, session_factory, storage, settings)

    with session_factory() as session:
        receipt = session.get(Receipt, job.id)
        assert receipt.confidence_reasons  # non-empty: this receipt lost points
        penalties = [D(entry["penalty"]) for entry in receipt.confidence_reasons]
        expected = min(D("1"), max(D("0"), D("1") + sum(penalties)))
        assert expected.quantize(D("0.001")) == receipt.confidence


def test_a_clean_receipt_records_an_empty_reason_list(session_factory, storage, settings):
    job = _job(storage)
    _run(job, _Client([_triage(), _good()]), session_factory, storage, settings)

    with session_factory() as session:
        # [] means "nothing lowered the score", which is not the same claim as
        # NULL ("never recorded").
        assert session.get(Receipt, job.id).confidence_reasons == []


def test_a_failed_stage_records_no_reasons(session_factory, storage, settings):
    job = _job(storage)
    client = _Client([RuntimeError("triage exploded")])

    result = _run(job, client, session_factory, storage, settings)

    assert result.failed_stage == "triage"
    with session_factory() as session:
        receipt = session.get(Receipt, job.id)
        assert receipt.status is ReceiptStatus.NEEDS_REVIEW
        # Nothing was ever scored, so NULL is the truthful value.
        assert receipt.confidence_reasons is None


def test_a_failed_reprocess_clears_the_reasons_for_the_score_it_replaced(
    session_factory, storage, settings
):
    """D2: the breakdown must always explain the score sitting next to it.

    ``_persist_failure``'s update branch set ``status`` and ``confidence`` but
    not ``confidence_reasons``, so a retry that died in ``extract`` left the row
    -- and ``GET /receipts/{id}`` -- showing ``confidence "0.000"`` beside a
    breakdown that still summed to the score of the run before it.
    """
    job = _job(storage)
    penalised = _good()
    penalised.meta.legibility = Legibility.POOR
    penalised.meta.is_handwritten = True
    first = _run(job, _Client([_triage(), penalised]), session_factory, storage, settings)

    with session_factory() as session:
        stale = session.get(Receipt, job.id).confidence_reasons
        assert stale, "the first run must record a breakdown for this to be a regression"
        assert sum(D(entry["penalty"]) for entry in stale) != D("0")
        assert first.confidence > D("0")

    result = _run(job, _Client([_triage(), RuntimeError("extract exploded")]),
                  session_factory, storage, settings)

    assert result.failed_stage == "extract"
    with session_factory() as session:
        receipt = session.get(Receipt, job.id)
        assert receipt.confidence == D("0")
        assert receipt.confidence_reasons is None


def test_a_reprocess_that_auto_approves_closes_the_open_review_task(
    session_factory, storage, settings
):
    """A resolved receipt must not leave its old task behind.

    ``_persist_outcome`` enqueued when the receipt was not auto-approved but
    never closed an existing task when it was, so ``GET /review/next`` could
    hand a reviewer an auto-approved receipt and ``/metrics`` overstated the
    backlog for as long as the row lived.
    """
    job = _job(storage)
    first = _run(job, _Client([_triage(), _broken_totals(), _broken_totals()]),
                 session_factory, storage, settings)
    assert first.status is ReceiptStatus.NEEDS_REVIEW
    with session_factory() as session:
        assert session.scalars(select(ReviewTask)).one().state is ReviewState.OPEN

    again = _run(job, _Client([_triage(), _good()]), session_factory, storage, settings)

    assert again.status is ReceiptStatus.AUTO_APPROVED
    with session_factory() as session:
        task = session.scalars(select(ReviewTask)).one()
        assert task.state is ReviewState.DONE
        assert task.closed_at is not None
