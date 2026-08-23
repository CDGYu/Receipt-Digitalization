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
import types
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
# Progress: the wiring, not the transport
# --------------------------------------------------------------------------- #


class _FakeRedis:
    """Records ``set`` calls. Stands in for what :func:`make_redis` opens."""

    def __init__(self) -> None:
        self.sets: list[tuple] = []

    def set(self, key, value, ex=None):
        self.sets.append((key, value, ex))


def test_the_progress_writer_overwrites_one_keyed_record_with_a_ttl(monkeypatch):
    """Where it writes, what it writes, and how long the record lasts.

    The key has to be ``progress_key``'s, because that is the only place the
    reader (``receipts.review.api._default_read_progress``) looks: a writer
    that spelled a key of its own would be silent in a way no other gate sees.
    The value has to be the wire form the reader decodes -- checked here as
    JSON rather than by calling ``encode``, so a changed ``encode`` cannot
    carry this assertion along with it. And ``ex`` has to be set, or an
    abandoned run leaves its record behind for good.

    One key for both writes is the "current stage, not a history" claim in
    ``make_progress_writer``'s docstring, stated as something that can fail.
    """
    from receipts.progress import ProgressEvent, progress_key

    fake = _FakeRedis()
    monkeypatch.setattr(worker_module, "make_redis", lambda **kwargs: fake)
    receipt_id = uuid.uuid4()

    write = worker_module.make_progress_writer(receipt_id)
    write(ProgressEvent(stage="triage"))
    write(ProgressEvent(stage="extract", detail="attempt 1"))

    assert {key for key, _value, _ttl in fake.sets} == {progress_key(receipt_id)}
    assert [json.loads(value) for _key, value, _ttl in fake.sets] == [
        {"stage": "triage", "detail": None},
        {"stage": "extract", "detail": "attempt 1"},
    ]
    assert {ttl for _key, _value, ttl in fake.sets} == {worker_module.PROGRESS_TTL_S}


def test_the_progress_connection_asks_for_a_bounded_wait(monkeypatch):
    """The narration never costs the extraction more than a moment.

    A socket call that *blocks* does not raise, so the ``except Exception``
    around every emit in :mod:`receipts.pipeline` cannot end it: the receipt
    would sit until RQ's death penalty and reach no terminal state, which is
    the cosmetic half of the system taking the load-bearing half down with it.
    A bound on the connection is what makes that impossible, and this asserts
    the writer asks for one.

    What a green run here does **not** establish: that ``redis`` honours the
    argument, or that an unreachable Redis blocks rather than failing fast.
    ``redis`` is not installed in this environment (see
    ``test_importing_the_worker_does_not_import_rq_or_redis``), so nothing
    here has watched the failure this bound is for. It pins the argument.
    """
    seen: dict = {}

    def _recording_make_redis(**kwargs):
        seen.update(kwargs)
        return _FakeRedis()

    monkeypatch.setattr(worker_module, "make_redis", _recording_make_redis)

    worker_module.make_progress_writer(uuid.uuid4())

    assert "socket_timeout" in seen, f"no read bound was asked for: {seen}"
    assert "socket_connect_timeout" in seen, f"no connect bound was asked for: {seen}"
    assert seen["socket_timeout"] == worker_module.PROGRESS_SOCKET_TIMEOUT_S
    assert seen["socket_connect_timeout"] == worker_module.PROGRESS_SOCKET_TIMEOUT_S
    # Anti-vacuity: a `None` or `0` constant would satisfy both equalities above
    # while asking for no bound at all.
    assert worker_module.PROGRESS_SOCKET_TIMEOUT_S > 0


def _fake_redis_module(calls: list):
    """A stand-in for the ``redis`` module, recording ``Redis.from_url`` calls.

    :func:`~receipts.worker.make_redis` imports ``redis`` inside its body, so
    putting an object in ``sys.modules`` is enough to intercept the call
    without the optional extra installed -- the same technique
    ``test_make_progress_writer_without_redis_installed_says_so`` uses to make
    that import fail.
    """

    def from_url(url, **kwargs):
        calls.append((url, kwargs))
        return _FakeRedis()

    return types.SimpleNamespace(Redis=types.SimpleNamespace(from_url=from_url))


def test_make_redis_forwards_the_bounds_it_is_given(monkeypatch):
    """The half of the bound that *delivers* it, not the half that asks for it.

    ``test_the_progress_connection_asks_for_a_bounded_wait`` pins what
    ``make_progress_writer`` hands to ``make_redis``, and it monkeypatches
    ``make_redis`` itself -- so it never reaches this body. Measured 2026-08-24,
    before this test was written: reverting the forwarding to a bare
    ``redis.Redis.from_url(resolved)`` left ``tests/test_worker.py`` green at 16
    tests, so the bound the writer asks for was discardable in silence -- which
    is the hung-Redis failure it exists for.

    What a green run here does **not** establish: that ``redis`` honours either
    argument, or that an unreachable Redis fails fast rather than blocking.
    ``redis`` is not installed in this environment (see
    ``test_importing_the_worker_does_not_import_rq_or_redis``); this pins that
    the caller's values reach ``from_url``.
    """
    calls: list = []
    monkeypatch.setitem(sys.modules, "redis", _fake_redis_module(calls))

    worker_module.make_redis(
        url="redis://localhost:6379/0",
        socket_timeout=1.5,
        socket_connect_timeout=2.5,
    )

    assert len(calls) == 1, f"from_url was not called exactly once: {calls}"
    url, kwargs = calls[0]
    assert url == "redis://localhost:6379/0"
    # Equality, not containment, and two distinct values -- so a dropped
    # argument, a swapped pair, or a `None` in place of either goes red.
    assert kwargs == {"socket_timeout": 1.5, "socket_connect_timeout": 2.5}


def test_make_redis_omits_the_bounds_it_is_not_given(monkeypatch):
    """The other half: a caller that asks for nothing forwards nothing.

    ``make_redis``'s docstring says the two timeouts reach ``from_url`` **only
    when a caller gives one**, rather than being forwarded as ``None``. This
    states that half as something that can fail. ``make_queue`` and
    ``run_worker`` both call ``make_redis`` with neither timeout, so what they
    get is whatever ``redis.Redis.from_url`` does on its own.
    """
    calls: list = []
    monkeypatch.setitem(sys.modules, "redis", _fake_redis_module(calls))

    worker_module.make_redis(url="redis://localhost:6379/0")

    assert len(calls) == 1, f"from_url was not called exactly once: {calls}"
    url, kwargs = calls[0]
    assert url == "redis://localhost:6379/0"
    assert kwargs == {}


def _recording_process_receipt(seen: dict):
    """A ``process_receipt`` stand-in that files away its keyword arguments."""

    def fake(job, **kwargs):
        seen["kwargs"] = kwargs
        return worker_module.ProcessResult(
            receipt_id=job.id,
            status=ReceiptStatus.AUTO_APPROVED,
            confidence=D("0.950"),
            reason="auto-approved",
        )

    return fake


def test_the_job_function_narrates_through_the_sink_its_deps_built(monkeypatch, deps):
    """The sink ``deps`` built for *this* receipt is the one the pipeline gets.

    This suite cannot reach Redis, so the live path (worker -> Redis ->
    ``GET /receipts/{id}/progress``) is not what is pinned here. What is pinned
    is the wiring on either side of it: ``process_receipt_job`` asks
    ``deps.progress_factory`` for a sink keyed to the receipt it is about to
    process, and hands *that* sink -- not another one, and not ``None`` -- to
    ``process_receipt``. Measured, one mutation at a time: replacing
    ``progress=progress`` with ``progress=None`` reddens the second assertion
    below and nothing else in this module, and building the writer for some
    other id reddens the first.
    """

    def sink(event) -> None:
        """The identity that has to arrive; what it does is beside the point."""

    asked: list[uuid.UUID] = []

    def factory(receipt_id):
        asked.append(receipt_id)
        return sink

    seen: dict = {}
    monkeypatch.setattr(worker_module, "process_receipt", _recording_process_receipt(seen))
    deps.progress_factory = factory
    job = _job(deps.storage)

    process_receipt_job(job_to_payload(job), deps=deps)

    # Keyed to this receipt, and asked for once: a writer built for some other
    # id would narrate under a key nobody is reading.
    assert asked == [job.id]
    assert seen["kwargs"]["progress"] is sink


def test_the_job_function_narrates_nothing_when_its_deps_built_no_writer(monkeypatch, deps):
    """No factory, no sink -- which is what keeps this whole module off Redis.

    :func:`~receipts.worker.build_deps` is the only thing that fills
    ``progress_factory`` in, and it fills it in with something that opens a
    Redis connection. A ``process_receipt_job`` that reached for a writer of its
    own instead would need one right here -- and ``redis`` is not installed in
    this environment at all, which is what
    ``test_importing_the_worker_does_not_import_rq_or_redis`` below records.
    """
    # Anti-vacuity: the `None` below is the fixture's, not one this test staged.
    assert deps.progress_factory is None

    seen: dict = {}
    monkeypatch.setattr(worker_module, "process_receipt", _recording_process_receipt(seen))
    job = _job(deps.storage)

    process_receipt_job(job_to_payload(job), deps=deps)

    assert seen["kwargs"]["progress"] is None


def test_the_job_function_survives_a_writer_it_cannot_build(monkeypatch, deps, caplog):
    """A receipt is never lost because nothing could narrate it.

    ``deps.progress_factory(job.id)`` opens a Redis connection, and
    :func:`~receipts.worker.make_redis` raises when ``REDIS_URL`` is unset or
    the ``worker`` extra is missing. Unguarded, that aborts the job one line
    before ``process_receipt`` -- so the receipt reaches no terminal state at
    all and nothing is ever extracted from it.

    ``run_worker`` takes the connection as a public keyword -- ``url=``, and
    ``settings=`` beside it -- so a worker can be serving a queue while the
    ambient environment ``build_deps`` reads inside each job has no
    ``REDIS_URL``. Unguarded, such a worker would accept jobs and leave every
    receipt it touched exactly as it was queued -- the ``pending`` row its
    ingest committed, still there and still re-runnable -- while the job
    itself fails out of this function the way ``process_receipt``'s one
    re-raise does. The cost is a worker that extracts nothing while looking
    healthy, not a lost receipt.
    """

    def _cannot_build(_receipt_id):
        raise RuntimeError("A Redis connection needs REDIS_URL to be set")

    seen: dict = {}
    monkeypatch.setattr(worker_module, "process_receipt", _recording_process_receipt(seen))
    deps.progress_factory = _cannot_build
    job = _job(deps.storage)

    summary = process_receipt_job(job_to_payload(job), deps=deps)

    # The receipt was processed, and processed *unnarrated* -- not processed
    # with some half-built sink that would raise again on the first stage.
    assert summary["receipt_id"] == str(job.id)
    assert seen["kwargs"]["progress"] is None

    # An operator has to be able to see *why* a whole worker went quiet, so the
    # traceback has to survive the swallow.
    swallowed = [record for record in caplog.records if record.name == "receipts.worker"]
    assert swallowed, "the swallowed failure was never logged"
    assert swallowed[-1].levelname == "WARNING"
    assert swallowed[-1].exc_info is not None, "logged without the traceback"


def test_build_deps_wires_a_progress_factory_that_writes_where_the_reader_looks(
    monkeypatch, tmp_path
):
    """The seam between the wiring and production, which nothing else covers.

    Measured 2026-08-24, one mutation against the whole suite: deleting the
    ``progress_factory=`` argument from :func:`~receipts.worker.build_deps`
    reddens **this test and no other**, while no key is ever written and the
    route reports a null stage forever.

    Two claims, because "it is wired" is not enough on its own: the factory
    exists, *and* what it builds writes under ``progress_key`` -- the only
    place ``receipts.review.api._default_read_progress`` looks.
    """
    from receipts.progress import ProgressEvent, progress_key

    settings = Settings(_env_file=None, storage_root=str(tmp_path / "blobs"))
    # `build_deps` resolves both of these from the environment. Patched here so
    # the test needs no provider and no database file; the engine is real but
    # in-memory, so `make_session_factory` still gets something it can bind to.
    # (The module-level `make_engine` this lambda calls is the unpatched one --
    # `monkeypatch.setattr` rebinds the name in `worker_module`, not here.)
    monkeypatch.setattr(worker_module, "make_client", lambda _settings: object())
    monkeypatch.setattr(worker_module, "make_engine", lambda _url: make_engine("sqlite://"))

    deps = worker_module.build_deps(settings)

    assert deps.progress_factory is not None

    fake = _FakeRedis()
    monkeypatch.setattr(worker_module, "make_redis", lambda **kwargs: fake)
    receipt_id = uuid.uuid4()

    deps.progress_factory(receipt_id)(ProgressEvent(stage="triage"))

    assert [key for key, _value, _ttl in fake.sets] == [progress_key(receipt_id)]


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


def test_make_progress_writer_without_redis_installed_says_so(monkeypatch):
    """Narration is optional, but *asking* for it is not silently optional.

    The connection is opened when the writer is built rather than on the first
    event, so a worker with no ``worker`` extra says so at once and names the
    install -- instead of looking healthy until the first receipt reaches the
    triage stage.
    """
    monkeypatch.setitem(sys.modules, "redis", None)

    with pytest.raises(RuntimeError, match="worker"):
        worker_module.make_progress_writer(uuid.uuid4(), url="redis://localhost:6379/0")
