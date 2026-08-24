"""The pipeline runners: the M1 straight-line path and the full service path.

Both tie existing stages into a single call and neither owns prompt text,
validation rules, or provider details -- they only *sequence* pieces that are
each tested in isolation. That is what lets the same code drive a real hosted
model or the offline ``FakeVLMClient`` unchanged: everything talks to the
:class:`VLMClient` interface, an injected ``StorageBackend``, and an injected
session factory, and nothing reaches for a global.

Three entry points, in increasing order of how much of the system they touch:

  * :func:`run_receipt` -- M1: preprocess, triage, extract(+repair), normalize.
    No database, no dedupe, no routing. Used by the eval harness, where a
    database would only add noise to an accuracy measurement.
  * :func:`process_receipt` -- the whole thing, and the **only** function the
    queue worker calls (§14.10). Adds storage, dedupe, confidence routing,
    persistence, and the review queue, and it wraps every stage so that no
    receipt can vanish (§18).
  * :func:`process_batch` -- :func:`process_receipt` over a list of paths, on a
    thread pool that shares one global VLM concurrency cap.

:func:`build_eval_pipeline` adapts :func:`run_receipt` to
:func:`eval.harness.run_eval`'s injected-pipeline contract -- the glue that lets
``receipts eval`` produce a real baseline once a provider and golden images
exist.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import logging
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import date as date_cls
from decimal import Decimal
from pathlib import Path
from typing import Callable, Iterable

from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from config.settings import Settings

from .extract import prompts as P
from .extract.clients.base import VLMClient, VLMError, VLMResponse
from .extract.clients.limits import CostGuard, GuardedVLMClient, VLMGate, get_vlm_gate
from .extract.extractor import (
    Attempt,
    ExtractionOutcome,
    PreparedImage,
    extract_with_repair,
    triage,
)
from .extract.paths import read_nothing
from .extract.schema import ReceiptExtraction, TriageResult
from .ingest.dedupe import compute_phash
from .ingest.ingest import ReceiptJob, ingest_file
from .ingest.storage import StorageBackend
from .merchants import registry
from .normalize import normalize
from .persist.models import PassName
from .persist.repository import (
    find_duplicate_by_content,
    find_duplicate_by_phash,
    get_receipt,
    mark_duplicate,
    record_progress,
    redact_pan,
    save_extraction,
    save_extraction_run,
    save_findings,
)
from .preprocess.image_ops import (
    UnsupportedFormat,
    fix_orientation,
    load_image,
    resize_for_model,
    to_base64,
    to_rgb,
)
from .progress import ProgressEvent
from .review.queue import close_review_for_receipt, enqueue_review
from .score.confidence import ReceiptStatus, explain_confidence, route, score_confidence
from .validate.context import ValidationContext
from .validate.report import ValidationReport

log = logging.getLogger(__name__)

#: A callable the pipeline hands progress to. ``None`` everywhere by default:
#: the sink is for a waiting screen, and no existing caller wants one.
ProgressSink = Callable[[ProgressEvent], None]

#: Extensions the eval adapter searches, in order, to match a label by stem.
DEFAULT_IMAGE_SUFFIXES: tuple[str, ...] = (".jpg", ".jpeg", ".png", ".webp")

#: The stages of :func:`process_receipt`, in order. A failure in any of them
#: routes the receipt to ``needs_review`` with that name as the reason (§18), so
#: these strings are operational vocabulary: they land in ``review_tasks.reason``
#: and in the logs, and renaming one changes what an operator greps for.
STAGES: tuple[str, ...] = (
    "load",
    "preprocess",
    "dedupe",
    "triage",
    "merchant",
    "extract",
    "normalize",
    "score",
    "persist",
)

#: How much of a failure's text reaches ``review_tasks.reason``. Long enough to
#: identify the fault, short enough that the review UI stays readable.
_MAX_REASON_CHARS = 400

#: Priority for a receipt that failed a stage. **Not** ``0``: ``0`` is the §12
#: "errors *and* no total" case, and :func:`~receipts.review.queue.enqueue_review`
#: never demotes a task, so parking every transient provider outage at the front
#: of the queue would permanently outrank genuinely urgent work. A failed run
#: leaves no data at all, which is exactly what priority ``1`` (full re-key)
#: describes.
_FAILURE_PRIORITY = 1

#: Statuses that mean the row already holds an extraction of its **own** image,
#: so a re-run of that id is a reprocess rather than a fresh upload and image
#: dedupe must not run again (see :func:`_find_duplicate_image`).
#:
#: ``PENDING`` is absent because that is exactly the row ``POST /upload`` writes
#: before the worker has looked at the image -- the ordinary first run, which
#: must still be deduped. ``REJECTED`` is absent for the opposite reason: it is
#: the pipeline's own marking for a duplicate, and re-running one must
#: re-establish the same link rather than skip dedupe and extract over it.
_ALREADY_EXTRACTED = frozenset(
    {ReceiptStatus.AUTO_APPROVED, ReceiptStatus.NEEDS_REVIEW, ReceiptStatus.REVIEWED}
)


def prepare_image(image_path: Path, *, max_edge: int = 2048) -> PreparedImage:
    """Preprocess ``image_path`` into the :class:`PreparedImage` the extractor
    consumes.

    Pixels only, in order: open -> apply and strip EXIF orientation -> flatten
    to RGB -> fit the longest edge to ``max_edge`` -> JPEG base64. ``image_hash``
    is a digest of the transported bytes so a response cache (when one is later
    wired in) keys correctly; it is harmless when no cache is used.
    """
    return _encode_for_model(_normalize_pixels(load_image(Path(image_path))), max_edge)


def prepare_image_bytes(
    data: bytes, *, max_edge: int = 2048
) -> tuple[PreparedImage, str]:
    """The bytes-in twin of :func:`prepare_image`, plus the perceptual hash.

    The service path reads blobs from an injected ``StorageBackend``, so it never
    has a filesystem path to hand to :func:`prepare_image`. The extra return
    value is the dHash of the *pre-resize* RGB image, which is what dedupe stores
    in ``receipts.image_phash`` and compares against.

    Raises :class:`~receipts.preprocess.image_ops.UnsupportedFormat` for bytes
    Pillow cannot identify, matching :func:`~receipts.preprocess.image_ops.load_image`
    so callers have one failure type to handle.
    """
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except UnidentifiedImageError as exc:
        raise UnsupportedFormat("Not a recognized image (from storage bytes)") from exc

    rgb = _normalize_pixels(image)
    return _encode_for_model(rgb, max_edge), compute_phash(rgb)


def _normalize_pixels(image: Image.Image) -> Image.Image:
    """Apply and strip EXIF orientation, then flatten to RGB."""
    return to_rgb(fix_orientation(image))


def _encode_for_model(rgb: Image.Image, max_edge: int) -> PreparedImage:
    """Fit an already-RGB image to the model window and base64-encode it."""
    resized = resize_for_model(rgb, max_edge=max_edge)
    b64 = to_base64(resized)
    image_hash = hashlib.sha256(b64.encode("ascii")).hexdigest()
    return PreparedImage(b64=b64, media_type="image/jpeg", image_hash=image_hash)


@dataclass(frozen=True)
class PassAttempt:
    """One model call's provenance: which pass, which rung, which model, kept or not.

    ``extraction_runs.model_id`` already records the model for every call the
    *service* path makes. The eval path touches no database, so attribution
    travels out through the return value instead.
    """

    pass_name: str
    model_id: str
    rung: int
    kept: bool


@dataclass(frozen=True)
class RunOutcome:
    """What one eval-path run produced, plus who produced it.

    Replaces the ``(extraction, report, triage)`` triple: a fourth positional
    element is where a tuple stops being readable, and this module already uses
    result dataclasses (``ProcessResult``, ``BatchResult``) for the same reason.
    """

    extraction: ReceiptExtraction
    report: ValidationReport
    triage: TriageResult
    attribution: tuple[PassAttempt, ...]


def run_receipt(
    image_path: Path,
    client: VLMClient,
    ctx: ValidationContext,
    *,
    max_attempts: int = 1,
    default_currency: str | None = None,
    triage_client: VLMClient | None = None,
    extract_fallback_client: VLMClient | None = None,
) -> RunOutcome:
    """Run one receipt end to end: preprocess -> triage -> extract(+repair) ->
    normalize.

    ``max_attempts`` is the total number of extraction attempts the model is
    given: the initial extract plus up to ``max_attempts - 1`` repair rounds, so
    the default of 1 is a single extract with no repair. It is spent by the
    **final** rung only; see the ladder note below.

    ``triage_client`` and ``extract_fallback_client`` are the eval path's rung
    ladder (design §2). Left ``None`` -- which is every production caller, and
    the default -- ``client`` serves both passes and the extract ladder has
    exactly one rung, so this function behaves exactly as it did before the
    ladder existed. ``process_receipt`` deliberately has no such parameter:
    design §5 keeps the escalation off the production path.

    ``default_currency`` is the configured system default (``DEFAULT_CURRENCY``)
    handed to :func:`~receipts.normalize.normalize` as the last link of the §9
    chain: it fills the currency only when the receipt printed no ISO code, which
    is the norm for PH BIR invoices. Left ``None`` the currency stays ``None``
    rather than becoming a guess. A merchant's own ``default_currency`` outranks
    it and is applied by :func:`process_receipt`; this path has no database, so
    there is no merchant here to ask.

    Returns a :class:`RunOutcome`: the normalized winning extraction, the
    validation report for that attempt, the triage result, and the per-rung
    attribution. The report reflects what the model produced and the repair loop
    reasoned about (normalization is safe canonicalization applied on top); the
    triage result is returned so callers can fold its legibility and issue
    signals into confidence scoring without re-running triage; the attribution
    is how the eval path learns which model produced the kept extraction, since
    it writes no ``extraction_runs`` row to read it back from (design §6).

    **The report here describes the pre-normalization extraction**, which is a
    deliberate difference from :func:`process_receipt`. Nothing is persisted on
    this path -- it exists to measure raw model accuracy for the eval harness --
    so validating what the model actually said is the honest measurement, and
    changing it would silently move the committed eval baseline. The service
    path, which *does* store the report next to a score, reconciles the two;
    see :func:`process_receipt`.

    Works with any :class:`VLMClient` -- a real client from the factory or the
    offline ``FakeVLMClient``.
    """
    image = prepare_image(image_path)

    triage_source = triage_client or client
    triage_result, _triage_response = triage(image, triage_source)
    attribution = [PassAttempt("triage", triage_source.model_id, rung=0, kept=True)]

    rungs: list[VLMClient] = [client]
    if extract_fallback_client is not None:
        rungs.append(extract_fallback_client)

    outcome: ExtractionOutcome | None = None
    for index, rung in enumerate(rungs):
        is_last = index == len(rungs) - 1
        try:
            candidate = extract_with_repair(
                image,
                rung,
                triage_result=triage_result,
                ctx=ctx,
                # Design §2.1: a non-final rung is a probe. `extract_with_repair`
                # bundles the extract and its repair rounds into one call, so
                # there is no way to keep a rung first and repair it after --
                # and repairs on a rung that may be discarded are spent
                # re-asking a model that already failed. With no fallback
                # configured there is one rung, it is final, and it gets the
                # configured budget: today's behaviour, unchanged.
                max_repairs=max(0, max_attempts - 1) if is_last else 0,
            )
        except VLMError:
            # The last rung's failure is the run's failure: there is nothing
            # left to fall back to, and swallowing it would report a success
            # nobody achieved.
            if is_last:
                raise
            attribution.append(
                PassAttempt("extract", rung.model_id, rung=index, kept=False)
            )
            continue

        # `read_nothing` runs on the pre-normalization extraction (design §3.2):
        # `normalize` fills `currency` from DEFAULT_CURRENCY, and granite's
        # measured output was every field null with `currency: PHP` supplied
        # that way -- judged after normalization that PHP reads as content the
        # model produced, and the fallback would never fire.
        if is_last or not read_nothing(candidate.extraction):
            outcome = candidate
            attribution.append(
                PassAttempt("extract", rung.model_id, rung=index, kept=True)
            )
            break

        attribution.append(
            PassAttempt("extract", rung.model_id, rung=index, kept=False)
        )

    # Not reachable as a failure: `rungs` is never empty, and the final rung
    # either returns (taking the `is_last` branch above) or re-raises. It is
    # here to narrow the type for a reader and for a checker.
    assert outcome is not None

    # merchant_default_currency stays unset: this path takes no session, so the
    # registry cannot be reached from here. process_receipt supplies it.
    normalized = normalize(
        outcome.extraction, system_default_currency=default_currency
    )
    return RunOutcome(
        extraction=normalized,
        report=outcome.report,
        triage=triage_result,
        attribution=tuple(attribution),
    )


def _find_image(images_dir: Path, stem: str, suffixes: tuple[str, ...]) -> Path | None:
    """First existing ``{stem}{suffix}`` under ``images_dir``, or ``None``."""
    for suffix in suffixes:
        candidate = images_dir / f"{stem}{suffix}"
        if candidate.is_file():
            return candidate
    return None


def build_eval_pipeline(
    client: VLMClient,
    ctx: ValidationContext,
    images_dir: Path,
    *,
    image_suffixes: tuple[str, ...] = DEFAULT_IMAGE_SUFFIXES,
    default_currency: str | None = None,
    triage_client: VLMClient | None = None,
    extract_fallback_client: VLMClient | None = None,
    attribution_sink: list[PassAttempt] | None = None,
) -> Callable[[Path], tuple[ReceiptExtraction, Decimal]]:
    """Adapt the runner to :func:`eval.harness.run_eval`'s ``PipelineFn``.

    Returns ``pipeline_fn(label_path)`` that locates the image whose stem matches
    the label file's stem under ``images_dir``, runs it through
    :func:`run_receipt`, folds the validation report and triage signals into a
    confidence via :func:`receipts.score.confidence.score_confidence`, and
    returns ``(extraction, confidence)``. A missing image raises a clear
    :class:`FileNotFoundError`.

    ``default_currency`` is forwarded to :func:`run_receipt`, so an eval run
    resolves the currency the same way a production run does -- otherwise a
    corpus whose receipts print no ISO code scores a currency miss on every
    single one.

    ``triage_client`` and ``extract_fallback_client`` are forwarded to
    :func:`run_receipt` unchanged, and this is the **only** route from a built
    ladder into a run: ``make_pass_clients`` constructs the rungs and
    ``run_receipt`` consumes them, and nothing joins the two anywhere else.
    Left ``None`` -- the default, and what every caller that has not opted in
    passes -- ``client`` serves both passes and the extract ladder has one rung.

    ``attribution_sink``, when given, is extended with every
    :class:`PassAttempt` each run produces. A caller-owned collector rather than
    a widened return type, because ``run_eval``'s ``PipelineFn`` contract is
    ``(extraction, confidence)`` and changing it would touch every fake pipeline
    in the suite; ``cost_per_receipt`` and the latency percentiles take the same
    route out for the same reason (design §6.1). It is appended to, never
    cleared, so one sink accumulates a whole golden-set run.

    Self-consistency is not run in the straight-line M1 path, so ``consistency``
    is ``None`` here; when self-consistency lands (M6) its result should be
    threaded through to lower confidence on disputed fields.
    """
    images_dir = Path(images_dir)

    def pipeline_fn(label_path: Path) -> tuple[ReceiptExtraction, Decimal]:
        stem = Path(label_path).stem
        image_path = _find_image(images_dir, stem, image_suffixes)
        if image_path is None:
            raise FileNotFoundError(
                f"No image for label {stem!r} under {images_dir} "
                f"(tried suffixes: {', '.join(image_suffixes)})"
            )
        run = run_receipt(
            image_path,
            client,
            ctx,
            default_currency=default_currency,
            triage_client=triage_client,
            extract_fallback_client=extract_fallback_client,
        )
        if attribution_sink is not None:
            attribution_sink.extend(run.attribution)
        confidence = score_confidence(run.extraction, run.report, run.triage, consistency=None)
        return run.extraction, confidence

    return pipeline_fn


# =========================================================================== #
# The service path: process_receipt (spec §14.10)
# =========================================================================== #


@dataclass(frozen=True)
class ProcessResult:
    """What one :func:`process_receipt` run decided, safe to hand around.

    Spec §14.10 types the return as a ``ReceiptRecord``. The concrete row is
    :class:`receipts.persist.models.Receipt`, and returning that ORM object would
    be a trap: sessions here are opened and closed per phase (a connection must
    not be held across a multi-second model call), and the project's session
    factory uses the default ``expire_on_commit=True``, so every attribute of the
    returned object would raise ``DetachedInstanceError`` for the caller. This is
    the same information, detached and immutable, plus the two things only the
    runner knows -- which stage failed, and what the run cost. Load the row with
    :func:`receipts.persist.repository.get_receipt` when the full record is
    wanted.
    """

    receipt_id: uuid.UUID
    status: ReceiptStatus
    confidence: Decimal
    reason: str
    review_priority: int = -1
    failed_stage: str | None = None
    duplicate_of: uuid.UUID | None = None
    cost_usd: Decimal = Decimal("0")


@dataclass(frozen=True)
class BatchResult:
    """Outcome of :func:`process_batch`.

    ``rejected`` holds ``(path, reason)`` for uploads that never became receipts
    -- a ``.txt`` in the directory, a truncated download. They are reported
    rather than dropped, but they are not receipts and so have no id and no
    terminal state to reach.
    """

    processed: list[ProcessResult] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)

    @property
    def total_cost_usd(self) -> Decimal:
        """What the batch spent, as an exact ``Decimal`` (ADR-0001)."""
        return sum((result.cost_usd for result in self.processed), Decimal("0"))

    @property
    def counts(self) -> dict[ReceiptStatus, int]:
        """How many receipts landed in each terminal status."""
        counts: dict[ReceiptStatus, int] = {}
        for result in self.processed:
            counts[result.status] = counts.get(result.status, 0) + 1
        return counts


class _StageFailure(Exception):
    """Internal: an exception, tagged with the stage that actually raised it.

    Carrying the stage on the exception (rather than inferring it from where it
    was caught) is what lets a failure inside a nested hook -- normalization runs
    inside the repair loop, not after it -- still be reported as ``normalize``
    instead of as the enclosing ``extract``.
    """

    def __init__(self, stage: str, cause: BaseException) -> None:
        super().__init__(f"{stage}: {type(cause).__name__}: {cause}")
        self.stage = stage
        self.cause = cause


@contextlib.contextmanager
def _stage(name: str, progress: "ProgressSink | None" = None):
    """Tag anything raised inside the block with ``name``, and report entry.

    An inner :class:`_StageFailure` passes through untouched, so the innermost
    (most specific) stage wins.

    ``progress`` is optional and defaults to ``None``. A sink that raises must
    not take the receipt down with it: a waiting screen is a nicety and the
    extraction is not.
    """
    if progress is not None:
        # Built before the ``try`` on purpose: a failure constructing the event
        # is a bug in this module, and reporting it as a broken sink would send
        # an operator looking in the wrong place.
        event = ProgressEvent(stage=name)
        try:
            progress(event)
        except Exception:
            log.warning(
                "progress sink raised on stage %s; continuing", name, exc_info=True
            )
    try:
        yield
    except _StageFailure:
        raise
    except Exception as exc:
        raise _StageFailure(name, exc) from exc


def _heartbeat_sink(
    session_factory: Callable[[], Session], receipt_id: uuid.UUID
) -> ProgressSink:
    """A :data:`ProgressSink` that records liveness on the receipt row.

    Its own short session per event, opened and closed around a single write.
    It deliberately does not reuse the pipeline's session: that one may be
    mid-stage or already rolled back, which is the same reason
    :func:`_persist_failure` takes a fresh one.

    It commits, because a heartbeat no other process can see is not a
    heartbeat. That is consistent with ADR-0006, which puts the transaction in
    the caller's hands -- here the sink is the caller.

    It may raise. Every call site is already guarded (:func:`_stage`,
    :func:`~receipts.extract.extractor._report`, and the best-attempt block in
    ``extract_with_repair``), so a database blip costs narration and never the
    extraction.
    """

    def sink(event: ProgressEvent) -> None:
        session = session_factory()
        try:
            record_progress(session, receipt_id, event.stage)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return sink


def fan_out(*sinks: "ProgressSink | None") -> ProgressSink:
    """One sink that delivers to several, isolating each from the others.

    ``None`` entries are dropped, so a caller can pass an optional sink
    without a conditional.

    **Each delivery is guarded separately, and that is load-bearing rather
    than defensive.** The worker fans out to a Redis writer and the heartbeat;
    if a broken Redis writer could abort the fan-out, an outage would stop the
    heartbeat too and silently reopen the stranded-receipt hole. Isolation is
    what keeps the guarantee independent of the narration.
    """
    live = [sink for sink in sinks if sink is not None]

    def sink(event: ProgressEvent) -> None:
        for one in live:
            try:
                one(event)
            except Exception:
                log.warning("progress sink raised; continuing", exc_info=True)

    return sink


def process_receipt(
    job: ReceiptJob,
    *,
    client: VLMClient,
    storage: StorageBackend,
    session_factory: Callable[[], Session],
    ctx: ValidationContext | None = None,
    settings: Settings | None = None,
    gate: VLMGate | None = None,
    cost_guard: CostGuard | None = None,
    progress: "ProgressSink | None" = None,
) -> ProcessResult:
    """The whole thing, end to end. The only function the queue worker calls.

    Stages, in order (:data:`STAGES`): read the original bytes from storage ->
    preprocess and perceptually hash them -> check for a duplicate image ->
    triage -> look the merchant up for its hints and its currency -> extract
    with the repair loop (normalization applied inside it) -> score -> route ->
    persist, resolving the merchant again from the finished extraction, writing
    it to ``receipts.merchant_id``, and checking that merchant plus the date and
    the total against the receipts already stored. Dependencies
    are injected exactly the way :func:`run_receipt` and
    :func:`build_eval_pipeline` take theirs, which is what keeps the whole suite
    offline.

    **Nothing is ever silently dropped** (§18). Every stage is wrapped: any
    exception marks the receipt ``needs_review`` with the failing stage as the
    reason, writes the row, and opens a review task, so the receipt still reaches
    a terminal state. The single case that raises is one where *nothing at all*
    could be written -- an unreachable database. Swallowing that would be the
    silent drop the rule forbids; raising hands the job back to the queue's
    failed registry, where an operator can see it.

    **A run never overwrites a human's review.** ``POST /upload`` writes the
    ``pending`` row before it queues, so a reviewer can re-key a receipt off the
    paper while the queue is backed up and the worker then arrives holding a
    machine extraction of that same id. Applying it would silently drop the
    correction and re-approve a number the reviewer rejected, so
    :func:`~receipts.persist.repository.save_extraction` refuses the write; the
    run lands in :func:`_persist_failure`, which leaves the reviewed row exactly
    as the human left it and opens a review task naming the stage and what the
    run produced. The receipt stays terminal, and the attempt is visible.

    **The stored report and the stored score describe the same object.**
    :func:`run_receipt` validates what the model produced and normalizes
    afterwards, so an ambiguous date that the normalizer correctly parks in
    ``date_raw`` leaves the persisted confidence carrying a date-null penalty
    that the persisted report does not explain -- and, worse, an ERROR (R030)
    that spends a repair round arguing with a decision normalization already
    made. Here, normalization is handed to
    :func:`~receipts.extract.extractor.extract_with_repair` as its
    ``normalize_fn``, so validation, the repair loop's ranking, the score, and
    the persisted row all see one object: the normalized extraction.

    Transactions follow ADR-0006 from the other side: the repository functions
    flush and this function, as their caller, commits. Sessions are opened per
    phase from ``session_factory`` and closed immediately, because holding a
    connection across a model call would tie up the pool for the length of an
    inference.

    ``gate`` defaults to the process-global VLM concurrency cap
    (``VLM_MAX_CONCURRENCY``) and ``cost_guard`` to a fresh per-run budget
    (``MAX_COST_USD_PER_RECEIPT``); both wrap ``client`` so every pass -- triage,
    extract, repair -- is covered. Passing a shared ``cost_guard`` deliberately
    turns it into a budget across several runs, and then ``cost_usd`` below
    reports that shared running total rather than this receipt's.

    ``job`` must name a blob holding **one image**. A PDF upload is expanded into
    one image (and one job) per page by ingest -- see
    :func:`~receipts.ingest.ingest.expand_pdf` -- because one job maps to one
    receipt id here; a PDF that reached this function would fail cleanly at
    ``preprocess`` rather than silently extracting only its first page.

    **Semantic (merchant + date + total) dedupe runs inside the ``persist``
    stage, not beside the image check.** It cannot run where image dedupe runs:
    that stage is pre-extraction, and none of ``merchant_id``, ``txn_date`` or
    ``total`` exists until the model has answered. It therefore **saves no model
    call** -- by the time a semantic duplicate is detectable the extraction has
    already been paid for in full, so the §18 cost-control argument that covers
    a re-uploaded *image* does not reach this path. What it buys is a ledger
    that does not hold two rows for one purchase. See
    :func:`_find_duplicate_content` for the guard that keeps the merge narrow
    and :func:`_persist_outcome` for what the rejected row keeps.

    Self-consistency (M6) and few-shot examples plug in at the marked points.
    """
    settings = settings or Settings()
    # A fresh context per run: extract_with_repair assigns ctx.triage, and a
    # context shared across a thread pool would otherwise be written from
    # several receipts at once.
    ctx = replace(ctx) if ctx is not None else ValidationContext()
    # Who this deployment's receipts should be addressed to. Read from the
    # environment HERE and handed to the rules on the context, because
    # validation is pure: R014/R015 never import Settings, so a report stays
    # reproducible from the extraction plus the context alone. A context that
    # already carries an expected buyer keeps it — that was declared by the
    # caller, and this is not the place to overrule it.
    if ctx.expected_buyer_name is None and ctx.expected_buyer_tax_id is None:
        ctx = replace(
            ctx,
            expected_buyer_name=settings.expected_buyer_name,
            expected_buyer_tax_id=settings.expected_buyer_tax_id,
        )
    gate = gate if gate is not None else get_vlm_gate(settings)
    cost_guard = cost_guard if cost_guard is not None else CostGuard.from_settings(settings)
    guarded = GuardedVLMClient(client, gate=gate, guard=cost_guard)

    # The heartbeat is built here rather than accepted from the caller: it
    # carries the terminal-state guarantee, and a guarantee a call site can
    # forget is not one. `progress` stays optional and injected because it
    # carries Redis narration, which is cosmetic and genuinely absent on the
    # no-Redis deployments.
    progress = fan_out(_heartbeat_sink(session_factory, job.id), progress)

    phash = ""
    try:
        with _stage("load", progress):
            data = storage.get(job.image_key)

        with _stage("preprocess", progress):
            image, phash = prepare_image_bytes(
                data, max_edge=settings.max_image_edge_px
            )

        with _stage("dedupe", progress):
            duplicate_id = _find_duplicate_image(session_factory, job, phash)
        if duplicate_id is not None:
            # §18 cost control: a re-upload costs nothing beyond the hash.
            with _stage("persist", progress):
                return _persist_duplicate(
                    session_factory, job, phash, duplicate_id, cost_guard.spent
                )

        with _stage("triage", progress):
            triage_result, triage_response = triage(image, guarded)

        with _stage("merchant", progress):
            hints: P.MerchantHints | None = None
            merchant_currency: str | None = None
            with session_factory() as session:
                merchant = registry.lookup(session, triage_result.merchant_name_guess)
                if merchant is not None:
                    # Read inside the session: the object detaches on the way out.
                    merchant_currency = merchant.default_currency
                    if merchant.hints:
                        hints = P.MerchantHints(
                            merchant_name=merchant.canonical_name,
                            hints=list(merchant.hints),
                        )
            # Few-shot IMAGES are Cloud-tier only (spec D1): on the local model
            # each example multiplies inference cost by one whole image. The
            # selector exists (registry.few_shots_for) and is deliberately not
            # called here -- the local-to-Cloud escalation is its own milestone
            # (spec §10), so there is no Cloud tier here to attach images to.
            few_shots: list[P.FewShot] = []

        with _stage("extract", progress):
            outcome = extract_with_repair(
                image,
                guarded,
                triage_result=triage_result,
                ctx=ctx,
                hints=hints,
                few_shots=few_shots,
                max_repairs=max(0, settings.max_repair_attempts),
                normalize_fn=_normalizer(settings.default_currency, merchant_currency),
                progress=progress,
            )

        with _stage("score", progress):
            # consistency stays None until self-consistency lands (M6).
            confidence = score_confidence(
                outcome.extraction, outcome.report, triage_result, consistency=None
            )
            # Same inputs, same order: the stored breakdown provably sums to the
            # stored score, which is what the review UI shows a human.
            reasons = explain_confidence(
                outcome.extraction, outcome.report, triage_result, consistency=None
            )
            status, priority, reason = route(
                confidence,
                outcome.report,
                outcome.extraction,
                auto_threshold=settings.auto_approve_threshold,
                review_threshold=settings.review_threshold,
            )

        with _stage("persist", progress):
            return _persist_outcome(
                session_factory,
                job,
                phash=phash,
                outcome=outcome,
                triage_result=triage_result,
                triage_response=triage_response,
                confidence=confidence,
                reasons=reasons,
                status=status,
                priority=priority,
                reason=reason,
                cost=cost_guard.spent,
                hints=hints,
                few_shots=few_shots,
                merchant_currency=merchant_currency,
            )
    except _StageFailure as failure:
        return _persist_failure(session_factory, job, failure, phash, cost_guard.spent)


def _normalizer(
    default_currency: str | None, merchant_currency: str | None = None
) -> Callable[[ReceiptExtraction], ReceiptExtraction]:
    """The ``normalize_fn`` hook, tagged as its own stage.

    :func:`~receipts.extract.extractor.extract_with_repair` applies this before
    validating each attempt, which is how the report and the extraction end up
    describing the same object.

    The two currencies are handed over **separately**, not collapsed with an
    ``or``: :func:`~receipts.normalize.normalize` owns the §9 precedence (an ISO
    code printed on the receipt -> the merchant's ``default_currency`` -> the
    system ``DEFAULT_CURRENCY`` -> ``None``), and collapsing them here would
    lose its last link. A merchant row holding an *unrecognised* code would
    then resolve to ``None`` instead of falling through to the system default,
    because ``normalize_currency`` only continues down a chain it can see.
    """

    def run(extraction: ReceiptExtraction) -> ReceiptExtraction:
        with _stage("normalize"):
            return normalize(
                extraction,
                merchant_default_currency=merchant_currency,
                system_default_currency=default_currency,
            )

    return run


def _find_duplicate_image(
    session_factory: Callable[[], Session], job: ReceiptJob, phash: str
) -> uuid.UUID | None:
    """The id of an existing receipt whose image matches, or ``None``.

    Read-only and on its own short-lived session: this runs *before* any model
    call precisely so a re-upload never reaches a provider.

    **Dedupe is skipped entirely for a receipt that already holds its own
    extraction** (:data:`_ALREADY_EXTRACTED`). That job is a reprocess, not an
    upload: its image is by definition already in the table under this very id,
    and every row that copied it is a *later* duplicate of it. Running dedupe
    anyway is how a reprocessed original used to be marked a duplicate of its
    own copy -- emptied of its amounts, flipped to ``rejected``, and dropped out
    of the export along with the copy, taking the transaction with it.
    :func:`~receipts.persist.repository.find_duplicate_by_phash` refuses the
    same link from the other side (it drops candidates whose ``duplicate_of``
    is this id), so neither defence is load-bearing alone.
    """
    session = session_factory()
    try:
        current = get_receipt(session, job.id)
        if current is not None and current.status in _ALREADY_EXTRACTED:
            return None
        existing = find_duplicate_by_phash(session, phash, exclude_id=job.id)
        return existing.id if existing is not None else None
    finally:
        session.close()


def _find_duplicate_content(
    session: Session,
    job: ReceiptJob,
    merchant_id: uuid.UUID | None,
    txn_date: date_cls | None,
    total: Decimal | None,
) -> uuid.UUID | None:
    """The id of an already-stored receipt this one duplicates, or ``None``.

    The twin of :func:`_find_duplicate_image`, and deliberately unlike it in
    three ways.

    **It runs after the model call, not before**, on the caller's session rather
    than one of its own. ``merchant_id``, ``txn_date`` and ``total`` are all
    products of the extraction, so this cannot be moved earlier and cannot save
    a call: the image check saves an inference, this one saves a duplicated row
    in the ledger.

    **A NULL ``merchant_id`` matches nothing here.** That is the one restriction
    the pipeline adds over
    :func:`~receipts.persist.repository.find_duplicate_by_content`, whose own
    contract permits NULL-to-NULL and is right to -- an unresolved merchant
    matching only other unresolved merchants is a coherent rule for a lookup.
    It is the wrong rule for a **merge**. Merchant resolution is
    exact-match-only, so early receipts routinely have no merchant at all, and
    without this guard two genuinely different shops that happened to share a
    date and a total would be merged on the strength of the two keys that say
    nothing about *which shop*. The repository's NULL-merchant rule is left
    alone; the restriction lives here, next to the consequence.

    **There is no reprocess skip here.** The failure its twin's skip exists for
    -- a reprocessed original marked a duplicate of its own copy -- is closed on
    the other side instead:
    :func:`~receipts.persist.repository.find_duplicate_by_content` will not offer
    a candidate that already resolves back to ``job.id``.

    **The keys are read off the row that was just written**, not derived a
    second time from the extraction. A second derivation is how the stored
    ``txn_date`` and the dedupe key come to disagree:
    :func:`~receipts.persist.repository.save_extraction` stores NULL and parks
    an unparseable date in ``date_raw``, and a re-parse that decided otherwise
    would key a merge on a date the row does not hold.
    """
    if merchant_id is None:
        return None
    existing = find_duplicate_by_content(
        session, merchant_id, txn_date, total, exclude_id=job.id
    )
    return existing.id if existing is not None else None


def _persist_duplicate(
    session_factory: Callable[[], Session],
    job: ReceiptJob,
    phash: str,
    existing_id: uuid.UUID,
    cost: Decimal,
) -> ProcessResult:
    """Record a re-uploaded image as a duplicate of the receipt already stored.

    The new upload still gets a row -- it happened, and its blob exists, so
    pretending otherwise would lose the fact of the upload -- but it is
    ``rejected``, which is terminal, keeps it out of exports, and keeps it out
    of the review queue. ``duplicate_of`` points at the original, so nothing is
    lost and the link is inspectable. The row itself carries no extraction: no
    model was called, and inventing amounts for it would be worse than leaving
    them null.
    """
    session = session_factory()
    try:
        receipt = save_extraction(
            session,
            job,
            ReceiptExtraction(),
            ValidationReport(),
            Decimal("0"),
            ReceiptStatus.REJECTED,
            image_phash=phash,
        )
        mark_duplicate(session, receipt.id, existing_id)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    log.info("Receipt %s is a duplicate of %s; no model call made", job.id, existing_id)
    return ProcessResult(
        receipt_id=job.id,
        status=ReceiptStatus.REJECTED,
        confidence=Decimal("0"),
        reason=f"duplicate of receipt {existing_id}",
        duplicate_of=existing_id,
        cost_usd=cost,
    )


def _persist_outcome(
    session_factory: Callable[[], Session],
    job: ReceiptJob,
    *,
    phash: str,
    outcome: ExtractionOutcome,
    triage_result: TriageResult,
    triage_response: VLMResponse,
    confidence: Decimal,
    reasons: list[tuple[str, Decimal]],
    status: ReceiptStatus,
    priority: int,
    reason: str,
    cost: Decimal,
    hints: P.MerchantHints | None = None,
    few_shots: list[P.FewShot] | None = None,
    merchant_currency: str | None = None,
) -> ProcessResult:
    """Write the receipt, its findings, its audit rows, and its review task.

    **The merchant is resolved first, and deliberately so.**
    :func:`_resolve_merchant` rolls its own session back on failure, and that
    rollback is only free because nothing else has been staged yet. Moving it
    after :func:`~receipts.persist.repository.save_extraction` would make the
    rollback discard the receipt as well -- the extraction this run already paid
    a model for.

    ``merchant_currency`` is the ``default_currency`` of the merchant the
    ``merchant`` stage found (the one the normalizer was built from), carried
    here only to compare against the merchant the extraction actually resolved
    to. They can differ; see the warning below.

    **A semantic duplicate keeps everything it paid for.** The check runs
    *after* :func:`~receipts.persist.repository.save_extraction`, so the
    duplicate branch decorates a stored extraction rather than replacing one --
    the row is flipped to ``rejected`` and given a ``duplicate_of``, and it
    keeps its amounts, its line items, its findings and its ``extraction_runs``.
    That is the whole reason this design was accepted: image dedupe writes an
    empty row because no model was called, but here one was and the money is
    spent either way, so storing the extraction costs nothing and is what lets a
    human read a **wrong** merge -- see the amounts that were merged over and
    disagree -- instead of only being able to undo one. ``priority`` drops to
    ``-1`` with it: ``rejected`` is terminal, and a duplicate is not work for a
    reviewer. The transient window in which the row carries the routed status
    before being flipped is inside this function's single transaction, so
    nothing outside it observes that state.

    The merchant is still credited for a receipt that turns out to be a
    duplicate -- ``_resolve_merchant`` has already run and incremented by the
    time the duplicate is known. That leaves ``merchants.receipt_count`` one
    high per duplicate caught *here*: the same bounded imprecision in a
    display-only counter that :func:`_resolve_merchant` documents from the other
    side, and cheaper than the decrement path it declines for the same reason. A
    re-uploaded **image** adds nothing to the count and never could:
    :func:`_persist_duplicate` returns before this function is reached, so no
    merchant is resolved for it at all.

    Three details are easy to get wrong and are therefore spelled out:

      * :func:`~receipts.persist.repository.save_extraction` takes the report but
        **does not write findings** -- they live in their own table so a repair
        pass can append to them. :func:`~receipts.persist.repository.save_findings`
        is called separately here.
      * Findings are written twice over on purpose: the best attempt's report
        (what the stored extraction still fails), then only those findings from
        the *first* attempt that repair actually resolved. The unresolved
        originals are not repeated, so the table reads as "what is still wrong"
        plus "what repair fixed" with nothing duplicated.
      * Every model call gets an ``extraction_runs`` row, whose ``raw_response``
        goes through ``redact_pan`` inside
        :func:`~receipts.persist.repository.save_extraction_run` (§18, ADR-0007).
        That function is never bypassed.
      * An auto-approval **closes** any review task the receipt still has. The
        queue is keyed on the receipt (``review_tasks.receipt_id`` is UNIQUE),
        so a re-run that resolves what an earlier run flagged has to say so;
        otherwise the task outlives the reason for it.

    The caller commits (ADR-0006, from the caller's side): one transaction covers
    the row, its children, the findings, the audit trail, and the review task, so
    a receipt can never exist without the queue entry that makes a human look at
    it.
    """
    session = session_factory()
    try:
        merchant_id, resolved_currency = _resolve_merchant(
            session, job, outcome.extraction
        )
        receipt = save_extraction(
            session, job, outcome.extraction, outcome.report, confidence, status,
            image_phash=phash, merchant_id=merchant_id, confidence_reasons=reasons,
        )

        # Semantic dedupe, keyed on what the row now actually holds. The write
        # above is unconditional and already done, which is the point: the
        # branch below can only ever *add* a rejection and a link on top of a
        # stored extraction, never stand in place of storing one.
        duplicate_id = _find_duplicate_content(
            session, job, merchant_id, receipt.txn_date, receipt.total
        )
        if duplicate_id is not None:
            status = ReceiptStatus.REJECTED
            priority = -1
            reason = f"duplicate of receipt {duplicate_id}"
            receipt.status = status
            mark_duplicate(session, receipt.id, duplicate_id)

        save_findings(session, receipt.id, outcome.report)

        repaired = [
            finding
            for finding in outcome.attempts[0].report.findings
            if finding.resolved_by_repair
        ]
        if repaired:
            save_findings(session, receipt.id, ValidationReport(findings=repaired))

        save_extraction_run(
            session, receipt.id, PassName.TRIAGE, 1, triage_response,
            P.prompt_hash(P.build_triage_prompt()),
        )
        for attempt_number, attempt in enumerate(outcome.attempts, start=1):
            save_extraction_run(
                session,
                receipt.id,
                _pass_name(attempt.pass_name),
                attempt_number,
                attempt.response,
                _attempt_prompt_hash(
                    attempt, outcome.attempts, attempt_number, triage_result,
                    hints, few_shots or [],
                ),
            )

        if status is not ReceiptStatus.AUTO_APPROVED and priority >= 0:
            enqueue_review(session, receipt.id, reason, priority)
        elif status is ReceiptStatus.AUTO_APPROVED:
            # A re-run that auto-approves has answered the question the old task
            # was asking. Left open, `/review/next` would hand a reviewer an
            # already-approved receipt and `/metrics` would overstate the
            # backlog. A receipt with no task is the common case and a no-op.
            close_review_for_receipt(session, receipt.id)

        # Read before the commit expires it: the warning below describes what
        # was stored, not what a re-read would say.
        stored_currency = receipt.currency
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    if not _same_currency(resolved_currency, merchant_currency):
        # The one seam the ordering leaves. The normalizer is built at the
        # `merchant` stage, from the merchant *triage* named; the merchant
        # stored below comes from the completed extraction's TIN, and those can
        # be different rows -- so the currency chain may have consulted a
        # merchant that is not this receipt's. Re-normalizing now is not the
        # fix: the report, the score and the row describe one object by
        # construction, and rewriting the currency after scoring would break
        # that. Say so instead. Every clause here is a fact, not a verdict --
        # the two may well agree on the currency that was printed.
        log.warning(
            "Receipt %s normalized against merchant default currency %r but "
            "resolved to merchant %s, whose default is %r; stored currency is %r",
            job.id, merchant_currency, merchant_id, resolved_currency, stored_currency,
        )

    log.info(
        "Receipt %s -> %s (confidence %s, %s)", job.id, status.value, confidence, reason
    )
    return ProcessResult(
        receipt_id=job.id,
        status=status,
        confidence=confidence,
        reason=reason,
        review_priority=priority,
        duplicate_of=duplicate_id,
        cost_usd=cost,
    )


def _same_currency(left: str | None, right: str | None) -> bool:
    """Whether two currency columns say the same thing. ``None`` == ``""``."""
    return (left or "").strip().upper() == (right or "").strip().upper()


def _resolve_merchant(
    session: Session, job: ReceiptJob, extraction: ReceiptExtraction
) -> tuple[uuid.UUID | None, str | None]:
    """Which merchant issued this receipt, from the **completed** extraction.

    Returns ``(merchant_id, default_currency)``, both ``None`` when no merchant
    could be established. A NULL ``merchant_id`` is a correct answer, not a gap.

    **A populated one means "resolved to a known merchant", not "the TIN was
    read".** Nothing here creates a merchant without a ``tax_id`` -- that is
    :func:`~receipts.merchants.registry.register`'s rule -- but the ``lookup``
    fallback below matches on the name alone, so a TIN-less extraction whose
    name is already registered is attributed to that merchant and counts toward
    it.

    **The TIN is asked first, and the name only as a fallback.** That order is
    not interchangeable with the reverse, for two separate reasons:

      * ``lookup`` matches on the normalized *name*, and two businesses can
        share one. Asking it first attributes a receipt to whichever of them was
        registered earlier and -- because ``register`` is then never reached --
        leaves the real issuer permanently unregisterable, which is exactly the
        outcome :func:`~receipts.merchants.registry.register`'s own docstring
        refuses to produce from the other side.
      * ``confirm`` is the only path that widens matching, and it discards a
        spelling the merchant already answers to. Reached only after a
        successful ``lookup``, every call it ever got would be discarded by that
        guard: the registry could never learn a second spelling for anybody.

    **A receipt is counted once, not once per run.** ``process_receipt`` is
    re-runnable by design (a retried job, a reprocess), and each pass arrives
    here with the same receipt id; incrementing unconditionally would make
    ``merchants.receipt_count`` a count of runs. A reprocess that resolves to a
    *different* merchant credits the new one and does not debit the old, which
    leaves the losing merchant one high -- a bounded imprecision in a
    display-only counter, and cheaper than a decrement path that has to reason
    about a merchant row that may since have been merged away.

    **One bounded property, not a list of anticipated failures: no failure in
    here may cost the receipt its extraction.** That extraction has already been
    paid for at a provider, validated and scored; a merchants-table problem is
    bookkeeping. Anything raised is logged with its traceback and the receipt is
    stored with no merchant. The ``merchant`` stage still fails *loudly* for a
    registry that is down (§18) -- it runs before the model call, where failing
    costs nothing -- so this bound covers what that stage cannot see, such as a
    constraint violation on the ``register`` flush.

    The rollback is what makes the bound safe rather than merely quiet: a failed
    flush leaves the session unusable, so continuing on it would take the
    receipt down anyway. It is free only because this runs first in
    :func:`_persist_outcome`'s transaction, with nothing else yet staged.
    """
    try:
        merchant = registry.register(session, extraction)
        if merchant is None:
            merchant = registry.lookup(session, extraction.merchant.name)
        else:
            registry.confirm(
                session, merchant, extraction.merchant.tax_id, extraction.merchant.name
            )
        if merchant is None:
            return None, None

        previous = get_receipt(session, job.id)
        if previous is None or previous.merchant_id != merchant.id:
            registry.increment(session, merchant)
        return merchant.id, merchant.default_currency
    except Exception:  # noqa: BLE001 -- the bound IS "everything"; see docstring
        log.warning(
            "Receipt %s: could not resolve a merchant; storing the extraction "
            "without one",
            job.id,
            exc_info=True,
        )
        session.rollback()
        return None, None


def _persist_failure(
    session_factory: Callable[[], Session],
    job: ReceiptJob,
    failure: _StageFailure,
    phash: str,
    cost: Decimal,
) -> ProcessResult:
    """Land a failed run in ``needs_review`` naming the stage that broke (§18).

    Runs on a *new* session: the one the failing stage was using may be poisoned
    (a flush that half-applied, a connection that dropped), and it has already
    been rolled back by the stage that owned it.

    An existing row is updated rather than re-inserted, so a retry of a job that
    had already persisted something cannot fail on the primary key and lose the
    receipt on the way to recording that it failed. Anything raised from here
    propagates: at that point nothing can be written at all, and letting the
    queue record a failed job is the only remaining way not to drop it.

    Two things the update branch must **not** do:

      * ``confidence_reasons`` is cleared alongside the score. Leaving the old
        breakdown next to the new ``0.000`` puts a reviewer in front of an
        explanation that sums to a number the row no longer has -- exactly what
        D2 (and :func:`_persist_outcome`'s "provably sums to" property) exists
        to prevent.
      * A row a human has already **reviewed** keeps its status, its score and
        its reasons. This function is where
        :func:`~receipts.persist.repository.save_extraction`'s refusal to
        overwrite a reviewed row lands, so downgrading it to ``needs_review``
        with a zero score here would destroy precisely what that refusal was
        protecting. The task opened below is what makes the attempt visible
        instead -- its reason carries the stage and what the run produced.
    """
    redacted = redact_pan(str(failure))
    reason = _truncate(redacted, _MAX_REASON_CHARS)
    log.warning(
        "Receipt %s failed at stage %r: %s\n%s",
        job.id,
        failure.stage,
        redacted,
        redact_pan("".join(traceback.format_exception(failure.cause))),
    )

    session = session_factory()
    try:
        receipt = get_receipt(session, job.id)
        if receipt is None:
            # No extraction survived, and inventing one would be worse than a
            # row of nulls that a reviewer can re-key.
            receipt = save_extraction(
                session, job, ReceiptExtraction(), ValidationReport(),
                Decimal("0"), ReceiptStatus.NEEDS_REVIEW, image_phash=phash,
            )
        elif receipt.status is not ReceiptStatus.REVIEWED:
            receipt.status = ReceiptStatus.NEEDS_REVIEW
            receipt.confidence = Decimal("0")
            receipt.confidence_reasons = None
        enqueue_review(session, receipt.id, reason, _FAILURE_PRIORITY)
        # Read back before the commit expires them: these describe the row, and
        # for a reviewed receipt that is not "needs_review at 0.000".
        status, confidence = receipt.status, receipt.confidence
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return ProcessResult(
        receipt_id=job.id,
        status=status,
        confidence=confidence,
        reason=reason,
        review_priority=_FAILURE_PRIORITY,
        failed_stage=failure.stage,
        cost_usd=cost,
    )


#: ``Attempt.pass_name`` -> the closed §6.4 ``extraction_runs.pass_name``
#: vocabulary. A re-extract *is* an extract call with the same prompt (the loop
#: re-extracts instead of repairing when nothing parsed), and the enum has no
#: member for it; the attempt number is what tells the two apart.
_PASS_NAMES: dict[str, PassName] = {
    "extract": PassName.EXTRACT,
    "re_extract": PassName.EXTRACT,
    "repair": PassName.REPAIR,
    "consistency": PassName.CONSISTENCY,
}


def _pass_name(name: str) -> PassName:
    return _PASS_NAMES.get(name, PassName.EXTRACT)


def _attempt_prompt_hash(
    attempt: Attempt,
    attempts: list[Attempt],
    attempt_number: int,
    triage_result: TriageResult,
    hints: P.MerchantHints | None = None,
    few_shots: list[P.FewShot] | None = None,
) -> str:
    """Reconstruct the ``prompt_hash`` for one attempt.

    Prompt building is pure, so rebuilding the prompt from what produced it
    gives the same 16-char hash the call used -- cheaper than threading prompts
    back out of the repair loop, and it cannot drift as long as the arguments
    match those in :func:`~receipts.extract.extractor.extract`. **The hints and
    few-shots passed here must be the identical objects passed to**
    :func:`~receipts.extract.extractor.extract_with_repair` -- a mismatch
    produces a hash for a prompt that was never sent, and nothing else in the
    system would notice.
    """
    if attempt.pass_name == "repair":
        previous = attempts[attempt_number - 2]
        return P.prompt_hash(
            P.build_repair_prompt(
                previous.extraction, previous.report.render_for_repair_prompt()
            )
        )
    return P.prompt_hash(
        P.build_extraction_prompt(triage_result, hints, few_shots or [])
        + P.SYSTEM_EXTRACTION
    )


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def process_batch(
    paths: Iterable[Path],
    *,
    client_factory: Callable[[], VLMClient],
    storage: StorageBackend,
    session_factory: Callable[[], Session],
    ctx: ValidationContext | None = None,
    settings: Settings | None = None,
    workers: int = 4,
    gate: VLMGate | None = None,
) -> BatchResult:
    """Ingest and process a list of files, ``workers`` at a time (§14.10).

    Ingest runs serially and first: it is cheap, it fails loudly for a file that
    is not a receipt at all, and doing it up front means a rejected upload never
    occupies a worker. Processing then fans out over a thread pool.

    ``workers`` bounds how many *receipts* are in flight; the cap on concurrent
    **model calls** is separate and global (``VLM_MAX_CONCURRENCY``), shared by
    every thread here and by anything else running in the process. Those are
    genuinely different limits: one is about how much of the pipeline (image
    decoding, database work) runs at once, the other about how hard a provider
    is being hit.

    ``client_factory`` rather than a client because a thread pool needs one
    client per worker to be safe with any implementation that keeps per-call
    state; a thread-safe client is simply ``lambda: shared_client``.

    Every path is accounted for: a receipt that failed appears in ``processed``
    with its ``failed_stage`` set, and a file that never became a receipt appears
    in ``rejected`` with the reason.
    """
    settings = settings or Settings()
    gate = gate if gate is not None else get_vlm_gate(settings)

    jobs: list[ReceiptJob] = []
    rejected: list[tuple[str, str]] = []
    for path in paths:
        path = Path(path)
        try:
            jobs.extend(ingest_file(path, storage))
        except Exception as exc:
            log.warning("Rejected %s at ingest: %s", path, exc)
            rejected.append((str(path), f"ingest: {type(exc).__name__}: {exc}"))

    def run(job: ReceiptJob) -> ProcessResult:
        return process_receipt(
            job,
            client=client_factory(),
            storage=storage,
            session_factory=session_factory,
            ctx=ctx,
            settings=settings,
            gate=gate,
        )

    if workers <= 1 or len(jobs) <= 1:
        processed = [run(job) for job in jobs]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            processed = list(pool.map(run, jobs))

    return BatchResult(processed=processed, rejected=rejected)
