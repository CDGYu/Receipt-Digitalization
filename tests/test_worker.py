"""The RQ worker (spec §14.10, task P4.T4).

Two properties are worth a test and both are checked without Redis:

  * the worker's dispatch surface is exactly one function -- it enqueues and
    runs :func:`receipts.worker.process_receipt_job`, which calls
    :func:`receipts.pipeline.process_receipt` and nothing else;
  * ``rq``/``redis`` are an optional extra, imported lazily. Importing
    :mod:`receipts.worker` must work without them (this whole module would fail
    to import otherwise, since neither is installed in the test environment),
    and asking for a live queue without them must say so clearly.

The queue itself is injected, so nothing here opens a socket.
"""

from __future__ import annotations

import io
import json
import sys
import uuid
from datetime import date
from decimal import Decimal as D

import pytest

pytest.importorskip("PIL")
pytest.importorskip("pillow_heif")

from PIL import Image  # noqa: E402

from config.settings import Settings  # noqa: E402
from receipts import worker as worker_module  # noqa: E402
from receipts.extract.clients.fake import FakeVLMClient  # noqa: E402
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
from receipts.persist.models import Base, Receipt  # noqa: E402
from receipts.persist.session import make_engine, make_session_factory  # noqa: E402
from receipts.score.confidence import ReceiptStatus  # noqa: E402
from receipts.validate.context import ValidationContext  # noqa: E402
from receipts.worker import (  # noqa: E402
    DEFAULT_QUEUE_NAME,
    WorkerDeps,
    enqueue_receipt,
    job_from_payload,
    job_to_payload,
    make_queue,
    process_receipt_job,
    run_worker,
)

CTX = ValidationContext(today=date(2026, 7, 26))


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (900, 1400), (240, 240, 240)).save(buffer, format="PNG")
    return buffer.getvalue()


def _job(storage: LocalStorage | None = None) -> ReceiptJob:
    receipt_id = uuid.uuid4()
    key = make_image_key(receipt_id, "original")
    if storage is not None:
        storage.put(key, _png_bytes(), "image/png")
    return ReceiptJob(
        id=receipt_id,
        image_key=key,
        source="upload",
        original_filename="receipt.png",
        content_type="image/png",
    )


def _triage() -> TriageResult:
    return TriageResult(
        document_type=DocumentType.POS_RECEIPT,
        legibility=Legibility.GOOD,
        estimated_line_item_count=2,
    )


def _good() -> ReceiptExtraction:
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


class _FakeQueue:
    """Stands in for ``rq.Queue``: records what would have been dispatched."""

    def __init__(self) -> None:
        self.enqueued: list[tuple] = []

    def enqueue(self, func, *args, **kwargs):
        self.enqueued.append((func, args, kwargs))
        return f"job-{len(self.enqueued)}"


@pytest.fixture()
def deps(tmp_path) -> WorkerDeps:
    engine = make_engine(f"sqlite:///{(tmp_path / 'receipts.db').as_posix()}")
    Base.metadata.create_all(engine)
    return WorkerDeps(
        client=FakeVLMClient([_triage(), _good()]),
        storage=LocalStorage(tmp_path / "blobs"),
        session_factory=make_session_factory(engine),
        settings=Settings(_env_file=None),
        ctx=CTX,
    )


# --------------------------------------------------------------------------- #
# Payload
# --------------------------------------------------------------------------- #


def test_job_payload_round_trips_through_json():
    job = _job()
    payload = job_to_payload(job)

    # RQ has to serialise this, so it must survive a JSON round trip -- the
    # UUID included.
    restored = job_from_payload(json.loads(json.dumps(payload)))

    assert restored == job
    assert isinstance(restored.id, uuid.UUID)


def test_job_payload_rejects_an_unusable_payload():
    with pytest.raises(ValueError):
        job_from_payload({"id": "not-a-uuid", "image_key": "k"})


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #


def test_enqueue_receipt_dispatches_only_process_receipt_job():
    queue = _FakeQueue()
    job = _job()

    handle = enqueue_receipt(job, queue)

    assert handle == "job-1"
    func, args, kwargs = queue.enqueued[0]
    # The worker's entire surface: one function, one JSON-safe argument.
    assert func is process_receipt_job
    assert args == (job_to_payload(job),)
    assert kwargs["job_timeout"] == worker_module.DEFAULT_JOB_TIMEOUT_S


def test_the_job_function_calls_process_receipt_and_nothing_else(monkeypatch, deps):
    seen: dict = {}

    def fake_process_receipt(job, **kwargs):
        seen["job"] = job
        seen["kwargs"] = kwargs
        return worker_module.ProcessResult(
            receipt_id=job.id,
            status=ReceiptStatus.AUTO_APPROVED,
            confidence=D("0.950"),
            reason="auto-approved",
        )

    monkeypatch.setattr(worker_module, "process_receipt", fake_process_receipt)
    job = _job(deps.storage)

    summary = process_receipt_job(job_to_payload(job), deps=deps)

    assert seen["job"] == job
    assert seen["kwargs"]["client"] is deps.client
    assert seen["kwargs"]["storage"] is deps.storage
    assert seen["kwargs"]["session_factory"] is deps.session_factory
    assert summary["receipt_id"] == str(job.id)
    assert summary["status"] == "auto_approved"


def test_the_job_function_runs_the_real_pipeline_offline(deps):
    job = _job(deps.storage)

    summary = process_receipt_job(job_to_payload(job), deps=deps)

    assert summary["status"] == "auto_approved"
    assert summary["failed_stage"] is None
    # Money and scores cross the queue boundary as strings, never floats
    # (ADR-0001): RQ's result store is JSON/pickle, not a Decimal-aware column.
    assert summary["confidence"] == "1.000"
    assert isinstance(summary["cost_usd"], str)
    json.dumps(summary)  # must be storable as an RQ result

    with deps.session_factory() as session:
        receipt = session.get(Receipt, job.id)
        assert receipt is not None
        assert receipt.status is ReceiptStatus.AUTO_APPROVED


def test_the_job_function_never_loses_a_receipt_to_a_broken_stage(deps, tmp_path):
    # No blob was ever written for this job, so the load stage fails.
    job = _job(storage=None)

    summary = process_receipt_job(job_to_payload(job), deps=deps)

    assert summary["status"] == "needs_review"
    assert summary["failed_stage"] == "load"
    with deps.session_factory() as session:
        assert session.get(Receipt, job.id) is not None


# --------------------------------------------------------------------------- #
# The optional rq/redis extra
# --------------------------------------------------------------------------- #


def test_importing_the_worker_does_not_import_rq_or_redis():
    # Neither is installed in the test environment, so a module-level import
    # would have made this file un-importable; the assertion documents the rule.
    assert "rq" not in sys.modules
    assert "redis" not in sys.modules
    assert DEFAULT_QUEUE_NAME == "receipts"


def test_make_queue_without_rq_installed_says_so(monkeypatch):
    monkeypatch.setitem(sys.modules, "rq", None)
    monkeypatch.setitem(sys.modules, "redis", None)

    with pytest.raises(RuntimeError, match="rq"):
        make_queue(url="redis://localhost:6379/0")


def test_run_worker_without_rq_installed_says_so(monkeypatch):
    monkeypatch.setitem(sys.modules, "rq", None)
    monkeypatch.setitem(sys.modules, "redis", None)

    with pytest.raises(RuntimeError, match="rq"):
        run_worker(url="redis://localhost:6379/0")
