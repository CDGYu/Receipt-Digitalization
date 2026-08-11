"""The RQ worker (spec §14.10, task P4.T4).

The worker's entire surface is one function. A queue job carries a JSON-safe
description of a :class:`~receipts.ingest.ingest.ReceiptJob` and nothing else;
:func:`process_receipt_job` rebuilds it, builds the pipeline's dependencies from
the environment, and calls :func:`receipts.pipeline.process_receipt`. Keeping the
surface that narrow is what makes the "no silent drops" guarantee checkable:
there is exactly one path from the queue into the system, and it is the path that
is wrapped.

**``rq`` and ``redis`` are an optional extra** (``pip install -e '.[worker]'``)
and are imported *lazily*, the same way ``clients/factory.py`` treats the vendor
SDKs and ``ingest/storage.py`` treats ``boto3``. Importing this module must not
require a queue to be installed -- the CLI imports it to enqueue work, tests
import it to check dispatch, and the offline test suite has neither package. A
missing install surfaces as a clear :class:`RuntimeError` naming the extra, not
as an ``ImportError`` at import time.

Payloads are plain JSON: a UUID as a string, money and confidence as decimal
*strings*. RQ's result store is not ``Decimal``-aware, and ADR-0001 does not stop
being true at a process boundary -- a ``float`` there is exactly the kind of drift
that later looks like a model error.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from sqlalchemy.orm import Session

from config.settings import Settings, get_settings

from .extract.clients.base import VLMClient
from .extract.clients.factory import make_client
from .ingest.ingest import ReceiptJob
from .ingest.storage import LocalStorage, S3Storage, StorageBackend
from .persist.session import make_engine, make_session_factory
from .pipeline import ProcessResult, process_receipt
from .validate.context import ValidationContext

log = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_JOB_TIMEOUT_S",
    "DEFAULT_QUEUE_NAME",
    "WorkerDeps",
    "build_deps",
    "enqueue_receipt",
    "job_from_payload",
    "job_to_payload",
    "make_queue",
    "process_receipt_job",
    "run_worker",
]

#: The queue receipts are dispatched to. One queue, one job type.
DEFAULT_QUEUE_NAME = "receipts"

#: Ceiling on a single job. A receipt is a triage call plus an extract plus up to
#: ``MAX_REPAIR_ATTEMPTS`` repairs, and CPU inference on a self-hosted model can
#: spend minutes on each -- a timeout shorter than the work would kill jobs that
#: were about to succeed and hand them back as failures.
DEFAULT_JOB_TIMEOUT_S = 900


# --------------------------------------------------------------------------- #
# Payload
# --------------------------------------------------------------------------- #


def job_to_payload(job: ReceiptJob) -> dict[str, str]:
    """A JSON-safe description of ``job`` for the queue.

    Deliberately not a pickled dataclass: a queued job may be picked up by a
    worker running a *different* build, and a field added to
    :class:`~receipts.ingest.ingest.ReceiptJob` between the two would turn a
    pickle into an unreadable job -- which is a silently dropped receipt.
    """
    return {
        "id": str(job.id),
        "image_key": job.image_key,
        "source": job.source,
        "original_filename": job.original_filename,
        "content_type": job.content_type,
    }


def job_from_payload(payload: Mapping[str, Any]) -> ReceiptJob:
    """Rebuild a :class:`~receipts.ingest.ingest.ReceiptJob` from a queue payload.

    Raises ``ValueError`` -- the layer's error currency (ADR-0006) -- for a
    payload that cannot be a job, so a malformed message fails loudly at the
    worker's front door instead of half-processing.
    """
    try:
        receipt_id = uuid.UUID(str(payload["id"]))
        return ReceiptJob(
            id=receipt_id,
            image_key=str(payload["image_key"]),
            source=str(payload.get("source", "queue")),
            original_filename=str(payload.get("original_filename", "")),
            content_type=str(payload.get("content_type", "application/octet-stream")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"not a usable receipt job payload: {payload!r}") from exc


def result_to_payload(result: ProcessResult) -> dict[str, Any]:
    """The job's return value, as something RQ's result store can hold.

    Money and confidence cross as strings (ADR-0001): a ``Decimal`` that made a
    detour through a JSON float would come back subtly wrong.
    """
    return {
        "receipt_id": str(result.receipt_id),
        "status": result.status.value,
        "confidence": str(result.confidence),
        "reason": result.reason,
        "review_priority": result.review_priority,
        "failed_stage": result.failed_stage,
        "duplicate_of": None if result.duplicate_of is None else str(result.duplicate_of),
        "cost_usd": str(result.cost_usd),
    }


# --------------------------------------------------------------------------- #
# Dependencies
# --------------------------------------------------------------------------- #


@dataclass
class WorkerDeps:
    """Everything :func:`process_receipt_job` needs, built once per worker.

    A queue job cannot carry a live client, a storage backend, or a session
    factory, so the worker rebuilds them from the environment. Keeping them in
    one injectable object is what lets the tests drive the job function with a
    fake client and a SQLite file -- no Redis, no provider, no network.
    """

    client: VLMClient
    storage: StorageBackend
    session_factory: Callable[[], Session]
    settings: Settings
    ctx: ValidationContext | None = None


def build_deps(settings: Settings | None = None) -> WorkerDeps:
    """Build the worker's dependencies from the environment (§17).

    ``STORAGE_BACKEND`` picks the blob store: ``local`` roots a
    :class:`~receipts.ingest.storage.LocalStorage` at ``STORAGE_ROOT``, ``s3``
    needs ``S3_BUCKET``. An unknown value is a ``ValueError`` rather than a
    silent fallback to the local disk, which in production would write receipts
    to a container filesystem that vanishes on restart.
    """
    settings = settings or get_settings()
    backend = settings.storage_backend.strip().lower()

    if backend == "local":
        storage: StorageBackend = LocalStorage(Path(settings.storage_root))
    elif backend == "s3":
        if not settings.s3_bucket:
            raise RuntimeError("STORAGE_BACKEND=s3 requires S3_BUCKET to be set.")
        storage = S3Storage(settings.s3_bucket)
    else:
        raise ValueError(
            f"Unknown STORAGE_BACKEND {settings.storage_backend!r}. Expected 'local' or 's3'."
        )

    engine = make_engine(settings.database_url)
    return WorkerDeps(
        client=make_client(settings),
        storage=storage,
        session_factory=make_session_factory(engine),
        settings=settings,
    )


# --------------------------------------------------------------------------- #
# The one job function
# --------------------------------------------------------------------------- #


def process_receipt_job(
    payload: Mapping[str, Any], *, deps: WorkerDeps | None = None
) -> dict[str, Any]:
    """The only function the RQ worker runs.

    Rebuilds the job, calls :func:`receipts.pipeline.process_receipt`, and
    returns a JSON-safe summary for the result store. It adds no error handling
    of its own on purpose: ``process_receipt`` already guarantees a terminal
    state for every stage failure, and a second, weaker net here would only make
    it unclear which one was doing the work. What does reach the queue as a
    failed job is the case ``process_receipt`` re-raises -- nothing could be
    written at all -- and that is precisely the case a human must see.

    ``deps`` is injected by tests and built from the environment otherwise.
    """
    deps = deps or build_deps()
    job = job_from_payload(payload)
    log.info("Processing receipt %s from %s", job.id, job.source)

    result = process_receipt(
        job,
        client=deps.client,
        storage=deps.storage,
        session_factory=deps.session_factory,
        ctx=deps.ctx,
        settings=deps.settings,
    )
    return result_to_payload(result)


def enqueue_receipt(job: ReceiptJob, queue: Any, *, job_timeout: int | None = None) -> Any:
    """Push one receipt onto ``queue`` and return the queue's handle.

    ``queue`` is anything with RQ's ``enqueue(func, *args, **kwargs)`` signature,
    which is what lets the dispatch path be tested without a live Redis. The
    enqueued callable is always :func:`process_receipt_job` -- the worker has one
    job type, and that is the invariant a test pins.
    """
    return queue.enqueue(
        process_receipt_job,
        job_to_payload(job),
        job_timeout=DEFAULT_JOB_TIMEOUT_S if job_timeout is None else job_timeout,
    )


# --------------------------------------------------------------------------- #
# Live queue wiring (lazy imports -- the extra may not be installed)
# --------------------------------------------------------------------------- #


def _redis_connection(url: str | None, settings: Settings | None = None):
    """A Redis connection from ``url`` or ``REDIS_URL``.

    Imported here rather than at module scope so this file stays importable
    without the ``worker`` extra.
    """
    # Settings are only read when the caller did not supply a url, so a test (or
    # a CLI flag) never depends on the ambient environment.
    resolved = url or (settings or get_settings()).redis_url
    if not resolved:
        raise RuntimeError(
            "A queue connection needs REDIS_URL to be set (or an explicit url=)."
        )
    try:
        import redis
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise RuntimeError(
            "The queue needs the optional 'worker' extra: pip install -e '.[worker]' "
            "(installs rq and redis)."
        ) from exc
    return redis.Redis.from_url(resolved)


def make_queue(
    name: str = DEFAULT_QUEUE_NAME,
    *,
    url: str | None = None,
    settings: Settings | None = None,
) -> Any:
    """An ``rq.Queue`` named ``name``, connected to ``REDIS_URL``.

    Raises :class:`RuntimeError` naming the extra when ``rq``/``redis`` are not
    installed, so the failure reads as a missing dependency rather than an
    import traceback.
    """
    connection = _redis_connection(url, settings)
    try:
        from rq import Queue
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise RuntimeError(
            "The queue needs the optional 'worker' extra: pip install -e '.[worker]' "
            "(installs rq and redis)."
        ) from exc
    return Queue(name, connection=connection)


def run_worker(
    queues: tuple[str, ...] = (DEFAULT_QUEUE_NAME,),
    *,
    url: str | None = None,
    settings: Settings | None = None,
    burst: bool = False,
) -> None:
    """Run an RQ worker over ``queues`` until it is stopped.

    ``burst=True`` drains what is queued and exits, which is what a batch
    (``receipts process``) wants; the default runs forever, which is what a
    service wants.
    """
    connection = _redis_connection(url, settings)
    try:
        from rq import Queue, Worker
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise RuntimeError(
            "The queue needs the optional 'worker' extra: pip install -e '.[worker]' "
            "(installs rq and redis)."
        ) from exc

    worker = Worker(
        [Queue(name, connection=connection) for name in queues], connection=connection
    )
    log.info("Worker starting on queues %s", ", ".join(queues))
    worker.work(burst=burst)


if __name__ == "__main__":  # pragma: no cover - process entry, not importable code
    # `python -m receipts.worker` -- what the container runs (ADR-0036), and
    # what anyone starting a worker by hand should run. Added when the
    # deployment story needed a command to name: `run_worker` existed but
    # nothing invoked it, so the queue had the same gap the review API had
    # before ADR-0035 gave it `receipts.asgi`.
    #
    # No argument parsing. Every knob `run_worker` takes is already an
    # environment variable read through Settings, and a second way to say the
    # same thing is a second thing to keep in agreement. Defaults are what a
    # long-running service wants: the default queue, and `burst=False` so it
    # runs until stopped rather than draining once and exiting.
    logging.basicConfig(level=logging.INFO)
    run_worker()
