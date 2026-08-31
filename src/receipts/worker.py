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
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from sqlalchemy.orm import Session

from config.settings import Settings, get_settings

from .extract.clients.base import VLMClient
from .extract.clients.factory import make_extract_ladder
from .ingest.ingest import ReceiptJob
from .ingest.storage import LocalStorage, S3Storage, StorageBackend
from .persist.session import make_engine, make_session_factory
from .pipeline import ProcessResult, ProgressSink, process_receipt
from .validate.context import ValidationContext

log = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_QUEUE_NAME",
    "NON_MODEL_BUDGET_S",
    "PROGRESS_SOCKET_TIMEOUT_S",
    "PROGRESS_TTL_S",
    "WorkerDeps",
    "build_deps",
    "enqueue_receipt",
    "job_from_payload",
    "job_timeout_for",
    "job_to_payload",
    "make_progress_writer",
    "make_queue",
    "make_redis",
    "process_receipt_job",
    "run_worker",
]

#: The queue receipts are dispatched to. One queue, one job type.
DEFAULT_QUEUE_NAME = "receipts"

#: HTTP attempts the OpenAI SDK makes per call: the initial one plus its default
#: ``max_retries`` of 2. The retries are silent, so one ``complete_json`` can
#: take three times ``VLM_TIMEOUT_S``.
#:
#: **ADR-0047's open question -- whether to set ``max_retries`` rather than
#: derive from its default -- was taken on 2026-08-25, and only for the probe
#: rung.** ``OpenAICompatClient`` now accepts ``max_retries``, and the factory
#: that builds the extract ladder passes 0 to a first rung that has an
#: escalation deadline, because three silent retries turn a five-minute
#: deadline into a fifteen-minute one. So the sentence this comment used to
#: carry -- "which
#: ``OpenAICompatClient`` never overrides" -- is no longer true and has been
#: deleted rather than softened.
#:
#: **This constant stays 3, and stays correct, for what it is used for.**
#: :func:`job_timeout_for` bounds a worker slot, and every rung that is *not* a
#: bounded probe still runs at the SDK default -- ``vlm_max_retries``, which
#: defaults to 2. A probe rung makes the ceiling generous rather than wrong,
#: which is the safe direction for a resource guard.
#:
#: Pinned by ``test_the_sdk_retry_default_this_derivation_rests_on`` rather than
#: trusted: without that test a change to the SDK default would make this
#: derivation wrong and nothing would fail.
_SDK_ATTEMPTS = 3

#: Everything in a receipt that is not a model call -- reading the original
#: bytes, decoding and hashing the image, the dedupe and merchant reads,
#: scoring, and the persist write. Additive rather than a multiplier, because
#: this work is bounded and small whatever model is configured.
NON_MODEL_BUDGET_S = 180


def job_timeout_for(settings: Settings) -> int:
    """The ceiling for one receipt's job, derived from what its model can cost.

    A receipt is a triage call, an extract call, and up to
    ``MAX_REPAIR_ATTEMPTS`` repairs; each can take ``_SDK_ATTEMPTS`` HTTP
    attempts of ``VLM_TIMEOUT_S``.

    **Derived rather than a constant** because a constant that fits one model
    does not fit another, and this value was previously 900 -- below its own
    worst case of 1080 even at code defaults, on any hardware (ISSUE-029).

    Since ``receipts.sweep`` now carries the terminal-state guarantee, this
    ceiling no longer decides whether an interrupted receipt is recoverable.
    It is a resource guard on a worker slot, and can therefore be generous.
    """
    one_call = settings.vlm_timeout_s * _SDK_ATTEMPTS
    calls = 2 + max(0, settings.max_repair_attempts)
    return one_call * calls + NON_MODEL_BUDGET_S


#: How long a progress record outlives its last write. Long enough to survive a
#: slow extract pass, short enough that an abandoned run disappears on its own.
PROGRESS_TTL_S = 900

#: The bound the narration connection asks for, on connecting and on waiting.
#:
#: **Derived from reading, not measured here** -- ``redis`` is not installed in
#: this environment, so nothing in this repository has watched a hung Redis
#: stall a receipt. The reasoning: this branch puts a Redis round-trip on the
#: hot path of every stage of every receipt, where there were none; a socket
#: call that blocks never raises, so the ``except Exception`` guarding each emit
#: in :mod:`receipts.pipeline` cannot catch it; and the receipt would then sit
#: until RQ's death penalty without reaching a terminal state. A bound is the
#: right shape whether or not that is what an unreachable Redis actually does.
#:
#: Small on purpose. Narration is cosmetic, so waiting on it is never worth more
#: than a moment, and the pipeline swallows whatever a timed-out write raises.
PROGRESS_SOCKET_TIMEOUT_S = 2.0


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
    #: The second extract rung, or ``None`` for one rung. Defaulted so every
    #: existing construction of this object -- the offline suite builds it with
    #: a fake client and no fallback -- keeps working unchanged.
    extract_fallback_client: VLMClient | None = None
    #: The triage-pass client. Built as a probe (short ``VLM_PRIMARY_TIMEOUT_S``
    #: deadline) when a triage fallback is configured, else with the full
    #: ``VLM_TIMEOUT_S``. ``None`` reuses ``client`` for triage -- correct for
    #: the offline suite (a single fake). See
    #: :func:`~receipts.pipeline.process_receipt`'s ``triage_client``.
    triage_client: VLMClient | None = None
    #: The cloud triage rung, or ``None`` for one triage rung. When set, triage
    #: escalates to it after the probe deadline (``VLM_MODEL_TRIAGE_FALLBACK``).
    triage_fallback_client: VLMClient | None = None
    ctx: ValidationContext | None = None
    #: Builds the progress sink for one receipt, the way ``session_factory``
    #: builds one session -- per job, because the key is the receipt's. ``None``
    #: means nothing narrates, which is what the offline suite gets: only
    #: :func:`build_deps` fills this in, and only with something that talks to
    #: Redis. Narration is optional by construction, so a test that drives
    #: :func:`process_receipt_job` still needs no queue.
    progress_factory: Callable[[uuid.UUID], ProgressSink] | None = None


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
    # **All three rungs are built here now, not just in the eval path.** The
    # builder had no code caller anywhere -- it was named in one `pipeline.py`
    # docstring and nothing else -- so `VLM_MODEL_EXTRACT_FALLBACK` was a setting
    # that could be set and would change nothing for an uploaded receipt.
    # `fallback` is `None` unless a fallback model is configured.
    #
    # **Triage gets its OWN client, and that is load-bearing.** When a fallback
    # is configured the primary extract rung is a probe -- a short
    # `VLM_PRIMARY_TIMEOUT_S` deadline with `max_retries=0` so the ladder can
    # escalate on time. Triage has no fallback to escalate to and, on a local
    # model, runs far longer than that probe deadline; running it through the
    # primary rung timed out every receipt at ~300s and parked it in
    # `needs_review` (`triage: VLMTransientError: connection: Request timed
    # out`). `make_extract_ladder` returns the triage rungs alongside the
    # extract rungs, so triage is not bound by the extract probe -- and the whole
    # ladder still has one construction site. Triage now has its own fallback:
    # when `VLM_MODEL_TRIAGE_FALLBACK` is set, `triage` is a probe and
    # `triage_fallback` is the cloud rung it escalates to after
    # `VLM_PRIMARY_TIMEOUT_S`, so a slow local box does not hold a receipt for
    # the full local triage time before it can be routed.
    triage, triage_fallback, primary, fallback = make_extract_ladder(settings)
    return WorkerDeps(
        client=primary,
        extract_fallback_client=fallback,
        triage_client=triage,
        triage_fallback_client=triage_fallback,
        storage=storage,
        session_factory=make_session_factory(engine),
        settings=settings,
        # A real worker reached this process through Redis, so the same
        # connection is available to narrate what it is doing. Bound to these
        # settings rather than read from the ambient environment later, for the
        # reason `make_redis` gives.
        progress_factory=lambda receipt_id: make_progress_writer(
            receipt_id, settings=settings
        ),
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
    around *the processing* on purpose: ``process_receipt`` already guarantees a
    terminal state for every stage failure, and a second, weaker net here would
    only make it unclear which one was doing the work. What does reach the queue
    as a failed job is the case ``process_receipt`` re-raises -- nothing could be
    written at all -- and that is precisely the case a human must see.

    ``deps`` is injected by tests and built from the environment otherwise.

    The progress sink is built here rather than in :func:`build_deps` because
    its key is the receipt's, and ``deps`` is built once per worker. It stays
    ``None`` when ``deps.progress_factory`` is -- narration is optional, and
    that is what lets the offline tests drive this function with no Redis.

    The one ``except`` below is not a second net around the processing: it
    guards *building the narration*, which must never be load-bearing. Failing
    to open a Redis connection would otherwise abort the job before
    ``process_receipt`` ever ran. Unnarrated is a fine outcome; lost is not.
    """
    deps = deps or build_deps()
    job = job_from_payload(payload)
    log.info("Processing receipt %s from %s", job.id, job.source)

    progress = None
    if deps.progress_factory is not None:
        try:
            progress = deps.progress_factory(job.id)
        except Exception:
            # Narration is never load-bearing. Building the writer opens a
            # Redis connection, and `make_redis` raises when REDIS_URL is unset
            # or the extra is missing -- unguarded, that would abort the job one
            # line before `process_receipt` and leave the receipt in no terminal
            # state at all. `exc_info` so the cause is still in the log: an
            # operator has to be able to see why a whole worker went quiet.
            log.warning(
                "could not build a progress writer for %s; continuing unnarrated",
                job.id,
                exc_info=True,
            )

    result = process_receipt(
        job,
        client=deps.client,
        triage_client=deps.triage_client,
        triage_fallback_client=deps.triage_fallback_client,
        extract_fallback_client=deps.extract_fallback_client,
        storage=deps.storage,
        session_factory=deps.session_factory,
        ctx=deps.ctx,
        settings=deps.settings,
        progress=progress,
    )
    return result_to_payload(result)


def enqueue_receipt(
    job: ReceiptJob,
    queue: Any,
    *,
    job_timeout: int | None = None,
    settings: Settings | None = None,
) -> Any:
    """Push one receipt onto ``queue`` and return the queue's handle.

    ``queue`` is anything with RQ's ``enqueue(func, *args, **kwargs)`` signature,
    which is what lets the dispatch path be tested without a live Redis. The
    enqueued callable is always :func:`process_receipt_job` -- the worker has one
    job type, and that is the invariant a test pins.

    ``job_timeout`` defaults to :func:`job_timeout_for` over ``settings`` rather
    than to a constant, so every caller gets a ceiling that fits the configured
    model. An explicit value still wins: an operator override is not overridden.
    """
    if job_timeout is None:
        job_timeout = job_timeout_for(settings or get_settings())
    return queue.enqueue(
        process_receipt_job,
        job_to_payload(job),
        job_timeout=job_timeout,
    )


# --------------------------------------------------------------------------- #
# Live Redis wiring (lazy imports -- the extra may not be installed)
# --------------------------------------------------------------------------- #


def make_redis(
    *,
    url: str | None = None,
    settings: Settings | None = None,
    socket_timeout: float | None = None,
    socket_connect_timeout: float | None = None,
):
    """A Redis connection from ``url`` or ``REDIS_URL``.

    Imported here rather than at module scope so this file stays importable
    without the ``worker`` extra.

    Public, and named for what it builds rather than for the queue, because the
    queue is no longer its only caller: :func:`make_progress_writer` needs the
    same connection, and so does the review API's ``_default_read_progress``.
    A second way to open the same connection would be a second thing to keep in
    agreement with ``REDIS_URL``.

    The two timeouts are passed through to ``from_url`` **only when a caller
    gives one**, rather than forwarded as ``None``. A caller that wants a bound
    says so; a caller that says nothing gets whatever ``redis.Redis.from_url``
    does on its own, unchanged -- which is what keeps this a bound added to the
    narration connection rather than a behaviour change for the queue.
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
    options: dict[str, Any] = {}
    if socket_timeout is not None:
        options["socket_timeout"] = socket_timeout
    if socket_connect_timeout is not None:
        options["socket_connect_timeout"] = socket_connect_timeout
    return redis.Redis.from_url(resolved, **options)


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
    connection = make_redis(url=url, settings=settings)
    try:
        from rq import Queue
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise RuntimeError(
            "The queue needs the optional 'worker' extra: pip install -e '.[worker]' "
            "(installs rq and redis)."
        ) from exc
    return Queue(name, connection=connection)


def make_progress_writer(
    receipt_id: uuid.UUID,
    *,
    url: str | None = None,
    settings: Settings | None = None,
    ttl_s: int = PROGRESS_TTL_S,
) -> Callable[[Any], None]:
    """A sink for :func:`receipts.pipeline.process_receipt`'s ``progress``.

    Each event overwrites the last: a waiting screen wants the current stage,
    not a history, and one key per receipt with a TTL means an abandoned run
    cleans itself up with no sweeper.

    Uses :func:`make_redis`, so a missing optional extra raises the same
    ``RuntimeError`` naming ``.[worker]`` that the queue does -- but **asking
    for a bounded wait**, which :func:`make_queue`'s connection does not. This
    one sits on the hot path of every stage of every receipt, so an unbounded
    wait here would be the extraction paying for the narration. See
    :data:`PROGRESS_SOCKET_TIMEOUT_S` for which part of that is reasoning and
    which part is measurement.
    """
    from .progress import encode, progress_key

    connection = make_redis(
        url=url,
        settings=settings,
        socket_timeout=PROGRESS_SOCKET_TIMEOUT_S,
        socket_connect_timeout=PROGRESS_SOCKET_TIMEOUT_S,
    )
    key = progress_key(receipt_id)

    def write(event: Any) -> None:
        connection.set(key, encode(event), ex=ttl_s)

    return write


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
    connection = make_redis(url=url, settings=settings)
    try:
        from rq import Queue, SimpleWorker, Worker
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise RuntimeError(
            "The queue needs the optional 'worker' extra: pip install -e '.[worker]' "
            "(installs rq and redis)."
        ) from exc

    # RQ's default Worker forks a work-horse per job (`os.fork`), which does not
    # exist on Windows -- a forking worker there dies with `AttributeError:
    # module 'os' has no attribute 'fork'` the moment it dequeues. SimpleWorker
    # runs the job in the worker process instead, which is RQ's own answer for
    # platforms without fork. The job's own `job_timeout` still bounds it; what
    # is lost is process isolation between jobs, which a single local worker
    # does not need. Everywhere fork exists, keep the isolating default.
    worker_cls = SimpleWorker if not hasattr(os, "fork") else Worker

    worker = worker_cls(
        [Queue(name, connection=connection) for name in queues], connection=connection
    )
    log.info(
        "Worker starting on queues %s (%s)", ", ".join(queues), worker_cls.__name__
    )
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
