"""The review API's app factory and routes (P4.T4/T5, spec §14.9).

:func:`create_app` is the one place that assembles the service: it wires the
four pieces of state Task 3's guards already read off ``app.state``
(``session_factory``, ``storage``, ``settings``, ``submit``), installs the
signed-cookie session middleware (:func:`~receipts.review.auth.
install_session_middleware`, which refuses to start without
``SESSION_SECRET`` -- see its docstring for why that is a hard failure and
not a generated default), mounts the auth router
(:func:`~receipts.review.auth.build_auth_router`), installs the error
handlers, and installs the read routes (Task 4: ``GET /health``,
``GET /receipts``, ``GET /receipts/{id}``, ``GET /metrics``) and the write
routes (Task 5: ``POST /upload``, ``PATCH /receipts/{id}``, the signed image
routes, the review queue routes, ``GET /export/xlsx``), and finally -- after
every one of those -- the SPA static mount (P5.T0: ``_install_spa``), which
serves the built review UI under ``/app`` when ``Settings.frontend_dist``
holds a built ``index.html`` and is otherwise a silent no-op.

Error handling lives in one place (:func:`_install_error_handlers`) so every
route gets it for free instead of repeating a ``try/except`` per handler:
``ValueError`` (the repository layer's error currency, ADR-0006) becomes 400,
a database that has gone away (``sqlalchemy.exc.DBAPIError`` -- which
``OperationalError`` already subclasses, so one handler covers both) becomes
503, and every ``HTTPException`` -- ours or Starlette's own routing errors --
keeps its status code but is reshaped into the same ``{"error": {"message":
...}}`` body. No handler echoes ``str(exc)`` for a database error: that can
carry the failing statement and its bound parameters, and this project does
not put SQL, a traceback, or a storage path in a response body.
"""

from __future__ import annotations

import logging
import mimetypes
import shutil
import tempfile
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles

from config.settings import Settings, get_settings

from ..export.xlsx import export_workbook
from ..ingest.ingest import ReceiptJob, ingest_bytes
from ..persist.models import Receipt, ReviewTask
from ..persist.repository import (
    apply_corrections,
    create_pending_receipt,
    get_findings,
    get_receipt,
    query_receipts,
)
from ..persist.users import ROLE_ADMIN
from ..score.confidence import ReceiptStatus
from .auth import (
    SessionUser,
    build_auth_router,
    install_session_middleware,
    require_role,
    require_upload,
    require_user,
    sign_url,
    verify_signature,
)
from .queue import close_task, next_task, queue_stats, release_task
from .schemas import (
    CorrectionPatch,
    ErrorBody,
    ErrorDetail,
    HealthStatus,
    MetricsResponse,
    ReceiptListResponse,
)
from .serializers import build_export_rows, query_export_receipts, receipt_detail, receipt_summary

__all__ = ["create_app"]

logger = logging.getLogger(__name__)

#: The image blob route's signed payload is ``f"{receipt_id}|{variant}"``,
#: joined with a bare ``|`` (see ``auth.sign_url``'s docstring). That is only
#: unambiguous if ``variant`` cannot itself contain ``|`` or otherwise shift
#: the join boundary, so it is typed as a closed set rather than a free
#: string -- FastAPI rejects anything outside it with 422 before either
#: image route ever builds or checks a signature.
ImageVariant = Literal["original", "processed"]

#: Past this many matching receipts, ``GET /export/xlsx`` refuses rather than
#: truncating (see that route's docstring). A module global, not a local
#: constant inside the route, specifically so a test can lower it with
#: ``monkeypatch.setattr(api_module, "_EXPORT_MAX_ROWS", ...)`` without a
#: database of five thousand receipts.
_EXPORT_MAX_ROWS = 5000


def _default_submit(job: ReceiptJob) -> Any:
    """Enqueue ``job`` on the real RQ queue backed by ``REDIS_URL``.

    ``receipts.worker`` needs the optional ``worker`` extra (``rq`` and
    ``redis``) -- imported here, inside the function body, so importing this
    module (and therefore calling :func:`create_app`) needs neither package.
    The offline test suite never calls this function: every test passes an
    explicit ``submit`` that appends to a list instead.
    """
    from ..worker import enqueue_receipt, make_queue

    return enqueue_receipt(job, make_queue())


# --------------------------------------------------------------------------- #
# Error handlers
# --------------------------------------------------------------------------- #


def _error_body(message: str) -> dict[str, Any]:
    return ErrorBody(error=ErrorDetail(message=message)).model_dump(mode="json")


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ValueError)
    async def _handle_value_error(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content=_error_body(str(exc)))

    @app.exception_handler(DBAPIError)
    async def _handle_database_error(request: Request, exc: DBAPIError) -> JSONResponse:
        # A generic message, not str(exc): a DBAPIError's text commonly
        # includes the failing statement and its bound parameters.
        return JSONResponse(status_code=503, content=_error_body("database unavailable"))

    # Registered on Starlette's own HTTPException (the base FastAPI's is a
    # subclass of) so this catches both a route's `raise HTTPException(...)`
    # and Starlette's routing errors (an unmatched path, a wrong method) --
    # not just the subset raised through fastapi.HTTPException.
    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(str(exc.detail)),
            headers=exc.headers,
        )


# --------------------------------------------------------------------------- #
# Read routes
# --------------------------------------------------------------------------- #


def _install_read_routes(app: FastAPI) -> None:
    @app.get("/health", response_model=HealthStatus)
    def health(request: Request) -> Any:
        """Liveness only -- no auth, and nothing about the deployment leaks."""
        try:
            with request.app.state.session_factory() as session:
                session.execute(text("SELECT 1"))
        except DBAPIError:
            return JSONResponse(status_code=503, content={"status": "degraded"})
        return {"status": "ok"}

    @app.get("/receipts", response_model=ReceiptListResponse)
    def list_receipts(
        request: Request,
        user: Annotated[SessionUser, Depends(require_user)],
        status: ReceiptStatus | None = None,
        merchant_id: uuid.UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        min_confidence: Decimal | None = None,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> Any:
        """Fetches ``limit + 1`` rows and reports ``has_more`` from the extra
        one, rather than a ``COUNT(*)`` per page -- see the brief's ambiguity
        resolution #4.
        """
        with request.app.state.session_factory() as session:
            rows = query_receipts(
                session,
                status=status,
                merchant_id=merchant_id,
                date_from=date_from,
                date_to=date_to,
                min_confidence=min_confidence,
                limit=limit + 1,
                offset=offset,
            )
            items = [receipt_summary(receipt) for receipt in rows[:limit]]
        return {"items": items, "has_more": len(rows) > limit}

    @app.get("/receipts/{receipt_id}")
    def get_one_receipt(
        receipt_id: uuid.UUID,
        request: Request,
        user: Annotated[SessionUser, Depends(require_user)],
    ) -> dict[str, Any]:
        with request.app.state.session_factory() as session:
            receipt = get_receipt(session, receipt_id)
            if receipt is None:
                raise HTTPException(status_code=404, detail=f"no receipt with id {receipt_id}")
            findings = get_findings(session, receipt_id)
            return receipt_detail(receipt, findings)

    @app.get("/metrics", response_model=MetricsResponse)
    def metrics(
        request: Request,
        user: Annotated[SessionUser, Depends(require_user)],
    ) -> Any:
        """Counts, the queue, and **this deployment's** thresholds (§6.2).

        The thresholds come off ``app.state.settings`` -- the very objects
        ``process_receipt`` routes on -- not off the
        :mod:`receipts.score.thresholds` defaults they happen to be seeded
        from. An operator reads this endpoint to reason about auto-approval
        precision, so echoing ``0.85``/``0.60`` at a deployment configured for
        ``0.95``/``0.75`` is a wrong number on exactly the screen that must not
        carry one -- and it would mislead precisely when P8 calibration moves
        the cut-off.
        """
        settings: Settings = request.app.state.settings
        with request.app.state.session_factory() as session:
            stats = queue_stats(session)
            counts = dict(
                session.execute(select(Receipt.status, func.count()).group_by(Receipt.status))
                .tuples()
                .all()
            )

        counts_by_status = {receipt_status.value: count for receipt_status, count in counts.items()}
        auto_approved = counts_by_status.get(ReceiptStatus.AUTO_APPROVED.value, 0)
        needs_review = counts_by_status.get(ReceiptStatus.NEEDS_REVIEW.value, 0)
        reviewed = counts_by_status.get(ReceiptStatus.REVIEWED.value, 0)
        denominator = auto_approved + needs_review + reviewed
        # An undefined rate is null, never a confident 0 or 1.0 on an empty
        # denominator -- see the module docstring and schemas.MetricsResponse.
        auto_approval_rate = (
            None
            if denominator == 0
            else str((Decimal(auto_approved) / Decimal(denominator)).quantize(Decimal("0.001")))
        )

        return {
            "counts_by_status": counts_by_status,
            "auto_approval_rate": auto_approval_rate,
            "queue": {
                "open": stats.open,
                "in_progress": stats.in_progress,
                "done": stats.done,
                "total": stats.total,
                "by_priority": stats.by_priority,
            },
            "thresholds": {
                "auto_approve": str(settings.auto_approve_threshold),
                "review": str(settings.review_threshold),
            },
        }


# --------------------------------------------------------------------------- #
# Write routes (P4.T5)
# --------------------------------------------------------------------------- #


def _task_summary(task: ReviewTask) -> dict[str, Any]:
    """A :class:`~receipts.persist.models.ReviewTask` row as JSON."""
    return {
        "id": str(task.id),
        "receipt_id": str(task.receipt_id),
        "reason": task.reason,
        "priority": task.priority,
        "assigned_to": task.assigned_to,
        "state": task.state.value,
        "opened_at": task.opened_at.isoformat(),
        "closed_at": task.closed_at.isoformat() if task.closed_at is not None else None,
    }


def _image_key_for(receipt: Receipt, variant: ImageVariant) -> str:
    """The blob key for ``variant`` of ``receipt``, falling back to the original.

    ``processed_image_key`` is only ever set once a preprocessing pass has
    actually run; a receipt still awaiting (or that never got) one has no
    processed variant, and the original is always the honest fallback rather
    than a 404 on a perfectly valid receipt.
    """
    if variant == "processed" and receipt.processed_image_key:
        return receipt.processed_image_key
    return receipt.image_key


def _install_write_routes(app: FastAPI) -> None:
    @app.post("/upload", status_code=202)
    async def upload(
        request: Request,
        file: UploadFile,
        user: Annotated[SessionUser | None, Depends(require_upload)],
    ) -> Any:
        """Store the upload, write a ``pending`` row, then queue it (§14.1, D4).

        The row is committed *before* ``submit`` is called, on purpose: a
        job the queue loses (an evicted Redis entry, a worker that dies
        before it persists) must be a visible stuck ``pending`` row, not a
        blob on disk with nothing in the database (ambiguity resolution --
        "nothing is silently dropped"). If ``submit`` itself raises, the row
        already exists and is visible, so this returns 503 naming the
        receipt id and logs the failure -- it does not undo the commit. What
        is left is a stuck ``pending`` row, which ``GET /receipts?status=
        pending`` lists. Recovery is ``receipts process``, which drains
        exactly those rows -- an upload that arrived here and a file passed
        to ``receipts ingest`` share one work list, which is why ``ingest``
        deliberately does not enqueue (ADR-0013). ``receipts reprocess
        <id>`` re-runs a single receipt; note it refuses an
        ``auto_approved`` row without ``--force`` and never overwrites a
        ``reviewed`` one, so it is not a way to redo a human's work.

        The read is bounded at ``max_bytes + 1``, not unbounded (fix round
        1, F2): ``UploadFile.read()`` with no argument buffers the *entire*
        body into one ``bytes`` object regardless of ``settings.
        max_upload_mb``, so a caller -- any reviewer session, or the machine
        API key -- could force an allocation of arbitrary size per
        concurrent request before ``ingest_bytes`` ever got a chance to
        reject it. Reading one byte past the cap is enough for
        ``ingest_bytes``'s own size check (which runs before the extension
        or content-type checks) to still see and reject an oversized upload
        with the same message it always has; the allocation this route
        itself performs is now bounded by config, not by whatever the
        client chooses to send.
        """
        settings = request.app.state.settings
        storage = request.app.state.storage
        max_bytes = settings.max_upload_mb * 1024 * 1024
        data = await file.read(max_bytes + 1)

        try:
            job = ingest_bytes(
                data,
                file.filename or "upload",
                storage,
                source="api",
                max_mb=settings.max_upload_mb,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        with request.app.state.session_factory() as session:
            create_pending_receipt(session, job)
            session.commit()

        try:
            request.app.state.submit(job)
        except Exception:
            logger.exception(
                "receipt %s was accepted and stored but could not be queued", job.id
            )
            raise HTTPException(
                status_code=503,
                detail=(
                    f"receipt {job.id} was accepted and stored, but could not be "
                    "queued for processing; it is safe to retry"
                ),
            ) from None

        return {"receipt_id": str(job.id), "image_key": job.image_key, "status": "pending"}

    @app.patch("/receipts/{receipt_id}")
    def patch_receipt(
        receipt_id: uuid.UUID,
        patch: CorrectionPatch,
        request: Request,
        user: Annotated[SessionUser, Depends(require_user)],
    ) -> dict[str, Any]:
        """Apply a reviewer's edits, attributed to the **session** user.

        ``corrected_by=user.username`` -- not a shared key, not a client-
        supplied field -- is the entire reason session auth exists (see
        ``auth.py``'s module docstring): a correction must be traceable to a
        real account. ``apply_corrections`` owns its own transaction (it
        commits or rolls back itself), so this route does not wrap it in a
        second one, and its return value is the already-committed, already
        re-read ``Receipt`` -- serializing it directly here avoids a second,
        redundant fetch for data ``apply_corrections`` just finished writing.
        """
        raw_patch = patch.model_dump(exclude_unset=True, mode="json")
        with request.app.state.session_factory() as session:
            receipt = apply_corrections(
                session, receipt_id, raw_patch, corrected_by=user.username
            )
            findings = get_findings(session, receipt_id)
            return receipt_detail(receipt, findings)

    @app.get("/receipts/{receipt_id}/image")
    def get_image_url(
        receipt_id: uuid.UUID,
        request: Request,
        user: Annotated[SessionUser, Depends(require_user)],
        variant: ImageVariant = "original",
    ) -> dict[str, str]:
        """An app-signed, expiring link to the blob sub-route (§6.1).

        Not ``storage.url()``: ``LocalStorage`` returns a ``file://`` URI
        (unusable in a browser and a disclosure of a server path) while
        ``S3Storage`` presigns properly, so the two backends would behave
        differently in the review UI. Signing ``f"{receipt_id}|{variant}"``
        here, independent of the storage backend, is what keeps the two
        deployments identical from a client's point of view.
        """
        with request.app.state.session_factory() as session:
            receipt = get_receipt(session, receipt_id)
            if receipt is None:
                raise HTTPException(status_code=404, detail=f"no receipt with id {receipt_id}")

        settings = request.app.state.settings
        signature, exp = sign_url(
            f"{receipt_id}|{variant}",
            secret=settings.session_secret,
            ttl_s=settings.image_url_ttl_s,
        )
        return {
            "url": f"/receipts/{receipt_id}/image/blob?variant={variant}&exp={exp}&sig={signature}"
        }

    @app.get("/receipts/{receipt_id}/image/blob")
    def get_image_blob(
        receipt_id: uuid.UUID,
        request: Request,
        variant: ImageVariant = "original",
        exp: int = Query(...),
        sig: str = Query(...),
    ) -> Response:
        """Stream the actual bytes. No session dependency, on purpose.

        This has to work from a bare ``<img src="...">`` tag, which sends no
        cookie and no header a caller controls -- the HMAC signature over
        ``(receipt_id, variant, exp)`` is what authorizes the request
        instead. ``receipt_id`` is parsed as a ``uuid.UUID`` path parameter
        and ``variant`` is a closed set (see :data:`ImageVariant`) *before*
        the signed message is rebuilt -- both are what keep the ``|``-joined
        construction in ``sign_url``/``verify_signature`` unambiguous (see
        their docstrings).

        A valid signature for a receipt whose blob is missing from storage
        (fix round 1, F5) is a 404, the same as an unknown receipt -- not an
        unhandled ``FileNotFoundError`` surfacing as a 500. This is the one
        unauthenticated route in the service; it must never leak a
        traceback to a caller who only had to forge nothing but guess an
        id.
        """
        settings = request.app.state.settings
        if not verify_signature(
            f"{receipt_id}|{variant}",
            secret=settings.session_secret,
            signature=sig,
            exp=exp,
        ):
            raise HTTPException(status_code=403, detail="invalid or expired image link")

        with request.app.state.session_factory() as session:
            receipt = get_receipt(session, receipt_id)
            if receipt is None:
                raise HTTPException(status_code=404, detail=f"no receipt with id {receipt_id}")
            key = _image_key_for(receipt, variant)

        try:
            data = request.app.state.storage.get(key)
        except FileNotFoundError:
            raise HTTPException(
                status_code=404, detail=f"no image stored for receipt {receipt_id}"
            ) from None
        media_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
        return Response(content=data, media_type=media_type)

    @app.get("/review/next")
    def review_next(
        request: Request,
        user: Annotated[SessionUser, Depends(require_user)],
    ) -> dict[str, Any]:
        """Resume the caller's own task, or claim the next one (ADR-0016).

        **A caller who already holds an ``IN_PROGRESS`` task gets that one
        back**, unchanged and without touching the queue; only a caller
        holding none claims. That is what makes a reload, a crashed browser,
        or a claim whose response never arrived recoverable, and it is the
        only thing that does so unaided: ``POST /review/{id}/complete``
        closes a task, which is not a release, and the one route that does
        release a claim -- ``POST /review/{id}/release`` (ADR-0025) -- is
        admin-only and answers a different question, a task stranded under
        someone who has stopped polling. Without resume, the reloading
        reviewer's own task would leave the queue until an admin noticed.
        Per-user by construction (the resume query matches on
        ``assigned_to``), and it outranks priority: a held task comes back
        even when a priority-0 one is waiting. See
        :func:`receipts.review.queue.next_task`.

        ``{"task": null}`` (200, not 204) on an empty queue -- one response
        shape for the client to parse rather than an empty-body special
        case. The receipt payload is deliberately the light
        ``receipt_summary`` (id, status, confidence, merchant, date,
        currency, total), not the full ``receipt_detail`` with line items
        and findings: enough for a reviewer to triage which task they picked
        up, with the detail screen (``GET /receipts/{id}``) one click away.
        """
        with request.app.state.session_factory() as session:
            task = next_task(session, assignee=user.username)
            if task is None:
                session.commit()
                return {"task": None}
            receipt = get_receipt(session, task.receipt_id)
            payload = {
                "task": _task_summary(task),
                "receipt": receipt_summary(receipt) if receipt is not None else None,
            }
            session.commit()
            return payload

    @app.post("/review/{task_id}/complete")
    def review_complete(
        task_id: uuid.UUID,
        request: Request,
        user: Annotated[SessionUser, Depends(require_user)],
    ) -> dict[str, Any]:
        """Close a task. Only its assignee or an admin may.

        ``{task_id}`` is a **review task** id, not a receipt id -- it
        follows ``GET /review/next`` in the spec (ambiguity resolution #1).
        Checked before ``close_task`` runs, so an unauthorized caller cannot
        move ``closed_at`` even once: ``close_task`` is itself idempotent
        (a second close on an already-closed task does not move the
        timestamp), but that idempotency is not a substitute for the
        permission check.
        """
        with request.app.state.session_factory() as session:
            task = session.get(ReviewTask, task_id)
            if task is None:
                raise HTTPException(status_code=404, detail=f"no review task with id {task_id}")
            if task.assigned_to != user.username and user.role != ROLE_ADMIN:
                raise HTTPException(
                    status_code=403,
                    detail="only the assignee or an admin may complete this task",
                )
            task = close_task(session, task_id)
            session.commit()
            return _task_summary(task)

    @app.post("/review/{task_id}/release")
    def review_release(
        task_id: uuid.UUID,
        request: Request,
        admin: Annotated[SessionUser, Depends(require_role(ROLE_ADMIN))],
    ) -> dict[str, Any]:
        """Return a claimed task to the queue. Admin only (ADR-0025).

        The inverse of a claim, and the case ``GET /review/next``'s resume
        cannot cover: resume hands back *the holder's own* task, so a task held
        by someone who has stopped polling stays out of the queue forever.
        ADR-0016 named that gap and left closing it as a policy decision; this
        is it. Resume is unchanged.

        ``{task_id}`` is a **review task** id, not a receipt id -- the same
        convention as ``POST /review/{task_id}/complete``.

        Authorization is declarative rather than in-body. ``/complete`` checks
        inside its body only because *assignee-or-admin* needs the task row
        first; this is a pure role test, so it belongs in the dependency, where
        it is enforced before the body runs.

        The unknown-task 404 is raised here rather than left to
        :func:`release_task`'s ``ValueError``, which the handler renders as
        400. A *closed* task does come back as 400 through that handler, and
        the split is the point: "no such task" and "that task cannot be
        released" are different answers.

        ``released_from`` sits beside ``assigned_to`` rather than replacing it:
        ``assigned_to`` is now ``null`` -- who holds it, nobody -- and
        ``released_from`` says who held it. On an already-open task it is
        ``null`` too, so an admin can tell a real release from a no-op -- and
        the log line below draws the same distinction, because ADR-0025 §3
        makes it the only *durable* half of that answer.
        """
        with request.app.state.session_factory() as session:
            task = session.get(ReviewTask, task_id)
            if task is None:
                raise HTTPException(status_code=404, detail=f"no review task with id {task_id}")
            task, released_from = release_task(session, task_id)
            payload = {**_task_summary(task), "released_from": released_from}
            session.commit()

        # Logged here rather than in release_task for two reasons: only the
        # route knows who acted, and queue.py imports no logger at all. Emitted
        # after the commit, so a rolled-back release is never announced as one.
        #
        # The idempotent path gets its own line for the same reason a
        # rolled-back one gets none: ADR-0025 §3 makes this log the only durable
        # trace of a release, and "released from None" reads as a release that
        # happened. The admin still acted, so the attempt is recorded -- as the
        # no-op it was. The task's `reason` is deliberately absent from both
        # lines -- see ADR-0022.
        if released_from is None:
            logger.info(
                "review task %s was already open; nothing released, requested by admin %s",
                task_id,
                admin.username,
            )
        else:
            logger.info(
                "review task %s released from %s by admin %s",
                task_id,
                released_from,
                admin.username,
            )
        return payload

    @app.get("/export/xlsx")
    def export_xlsx(
        request: Request,
        admin: Annotated[SessionUser, Depends(require_role(ROLE_ADMIN))],
        status: ReceiptStatus | None = None,
        merchant_id: uuid.UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        min_confidence: Decimal | None = None,
    ) -> Response:
        """Build the §13 workbook and return it whole, in memory. Admin only (D3).

        Fetches ``_EXPORT_MAX_ROWS + 1`` rows -- the same "fetch one past
        the limit" trick ``GET /receipts`` uses for ``has_more`` -- and
        refuses with 400 rather than truncating when that many actually
        come back: a silently shortened export reads as a complete ledger,
        which is worse than making the caller narrow the filter and ask
        again.

        **Returns a plain ``Response`` holding the whole file's bytes, not
        a ``FileResponse`` streaming a path (fix round 1, F1).** The
        original version wrote the workbook under ``tempfile.mkdtemp()``
        and returned a ``FileResponse`` with a ``BackgroundTask`` to clean
        it up after the response was sent -- correct on the happy path, but
        in starlette 1.3.1 ``FileResponse.__call__`` returns early for a
        malformed or unsatisfiable ``Range`` header (and for a client that
        disconnects mid-stream), and that early return **skips
        ``await self.background()`` entirely**. A caller sending
        ``Range: bytes=abc`` (or an out-of-bounds range, or just dropping
        the connection) left a complete financial workbook -- image links
        signed for 24 hours included -- behind in the shared OS temp
        directory forever, once per request. Building the response body
        fully in memory before it is ever handed to Starlette removes the
        deferred cleanup step altogether: the temp directory this route
        still uses to call ``export_workbook`` (which takes a path, not a
        stream) is read and deleted synchronously, in a ``finally``, before
        ``return`` -- there is no cleanup path left to miss, and no
        partial-content support to lose it through. The trade-off is that
        this route no longer honours ``Range`` requests (a plain
        ``Response`` always sends the whole body); for a bounded, at most
        ``_EXPORT_MAX_ROWS``-row workbook, that is a fair price for never
        leaking one.
        """
        settings = request.app.state.settings
        with request.app.state.session_factory() as session:
            rows = query_export_receipts(
                session,
                status=status,
                merchant_id=merchant_id,
                date_from=date_from,
                date_to=date_to,
                min_confidence=min_confidence,
                limit=_EXPORT_MAX_ROWS + 1,
            )
            if len(rows) > _EXPORT_MAX_ROWS:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"this export matches more than {_EXPORT_MAX_ROWS} receipts; "
                        "narrow the filter (status, merchant, or date range) and try again"
                    ),
                )
            extractions, export_rows = build_export_rows(
                session,
                rows,
                secret=settings.session_secret,
                image_url_ttl_s=settings.export_image_url_ttl_s,
            )

        tmpdir = tempfile.mkdtemp(prefix="receipts-export-")
        try:
            out_path = Path(tmpdir) / "receipts-export.xlsx"
            export_workbook(extractions, out_path, rows=export_rows)
            content = out_path.read_bytes()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="receipts-export.xlsx"'},
        )


# --------------------------------------------------------------------------- #
# SPA static mount (P5.T0, design §3.3)
# --------------------------------------------------------------------------- #


def _names_a_file(path: str) -> bool:
    """True when the last segment of ``path`` carries a file extension.

    ``StaticFiles`` hands ``get_response`` an OS-joined *relative* path --
    ``assets\\index-abc123.js`` on Windows, ``assets/index-abc123.js``
    elsewhere. ``Path(...).suffix`` reads the same last component either way:
    on POSIX a backslash is an ordinary character inside a single segment, so
    the dot it looks for is still the last one. Verified by executing both
    forms rather than assumed.
    """
    return bool(Path(path).suffix)


class _SpaFiles(StaticFiles):
    """``StaticFiles`` with a history fallback for client-side routes.

    The SPA owns its own routing under ``/app``: a hard refresh on
    ``/app/review``, or a bookmarked link to it, must return the shell rather
    than a 404 (ADR-0015).

    **The fallback is restricted to navigations** -- requests whose final
    path segment has no file extension. That is a constraint this mount
    *imposes* on the SPA's routes, not a fact about them: measured through
    the mount, ``/app/v1.2`` and ``/app/user@example.com`` are 404s while
    ``/app/.env`` returns the shell, because ``Path.suffix`` is empty for a
    name that is all extension. ``frontend/src/main.tsx`` states the
    obligation the right way round -- every client-side path must keep its
    final segment free of a dot -- and anything built from receipt data
    belongs in a query string. A request that names a file
    (``/app/assets/index-abc123.js``, ``/app/favicon.ico``) keeps its 404.
    An unconditional fallback answers *every* miss under ``/app`` with
    ``200 text/html``, and once a content-hashed build sits here that is a
    trap: a browser holding a cached ``index.html`` asks for an asset hash
    that has since been purged, gets HTML where JavaScript was expected, and
    fails with ``Unexpected token '<'`` -- with no 404 anywhere for anyone
    to point at.

    Only a 404 is swallowed. A 405 (``StaticFiles`` rejects a non-GET/HEAD
    before it ever looks at the path) or a 401 from a permission error is a
    real failure and still propagates to the app's error handlers.

    **A miss arrives here in two shapes, and both are handled.** Normally
    ``StaticFiles`` raises ``HTTPException(404)``. With ``html=True`` and a
    ``404.html`` in the served directory it *returns* that file with status
    404 instead -- measured against Starlette, not read off its docs -- so an
    ``except`` clause alone leaves the fallback at the mercy of the build's
    file list. Vite copies ``frontend/public/`` verbatim into ``dist/``, which
    put every deep link one conventional filename away from breaking.
    ``test_a_404_html_in_the_build_cannot_shadow_the_spa_shell`` is what binds
    the second shape.
    """

    def _is_navigation(self, path: str) -> bool:
        return not _names_a_file(path)

    async def get_response(self, path: str, scope):
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or not self._is_navigation(path):
                raise
            return await super().get_response("index.html", scope)
        if response.status_code == 404 and self._is_navigation(path):
            return await super().get_response("index.html", scope)
        return response


def _install_spa(app: FastAPI, settings: Settings) -> None:
    """Serve the built review UI under ``/app``, when it has been built.

    ``/health`` stays the API's JSON and ``/review/next`` stays an API route
    rather than a page. **Two independent things** keep it that way, and
    either one on its own is enough:

    * the ``/app`` prefix -- a Starlette mount only ever intercepts paths
      under its own prefix, so a mount here cannot compete with an API path
      at *any* registration order;
    * registration order -- Starlette matches routes in the order they were
      added, so a mount installed after ``/health`` loses to ``/health``
      even from the root.

    Established by mutating each one separately and watching what breaks:
    moving this mount to ``/`` while it stays registered last leaves
    ``/health`` at ``200 application/json``; only moving it to ``/`` **and**
    registering it before the read routes turns ``/health`` into the HTML
    shell. So ``test_the_spa_never_shadows_an_api_path`` goes red on the
    conjunction alone -- it does not catch either change by itself, and
    should not be described as if it did.

    ``/app`` is a prefix the API does not use, which is why the SPA lives
    there instead of at the root -- the alternative was moving the API under
    ``/api``, which would break every existing test and the contract
    ADR-0012 documents.

    Not built -> no mount at all, silently: CI and a base install take that
    path normally. **"Built" means the directory exists and holds an
    ``index.html``.** An interrupted ``npm run build``, or a
    ``FRONTEND_DIST`` aimed at some other real directory, otherwise mounts
    and serves whatever happens to be in it while every SPA page 404s. See
    ``Settings.frontend_dist``.
    """
    dist = Path(settings.frontend_dist)
    if not dist.is_dir() or not (dist / "index.html").is_file():
        return
    app.mount("/app", _SpaFiles(directory=dist, html=True), name="spa")


# --------------------------------------------------------------------------- #
# App factory
# --------------------------------------------------------------------------- #


def create_app(
    *,
    session_factory: Any,
    storage: Any,
    submit: Any = None,
    settings: Settings | None = None,
) -> FastAPI:
    """Build the review service.

    Populates the four ``app.state`` attributes Task 3's guards already read
    (``session_factory``, ``storage``, ``settings``, ``submit``), then wires
    session auth, the auth router, the error handlers, and the read and
    write routes, in that order -- and, last of all, the SPA static mount
    (:func:`_install_spa`, P5.T0). Registering it last is one of the two
    independent reasons it can never shadow an API path; the other is that
    ``/app`` is a prefix the API itself never uses. Either alone suffices --
    see :func:`_install_spa` for the mutation that establishes that.

    ``install_session_middleware`` is called unconditionally: an app with no
    ``SESSION_SECRET`` must fail at construction, not serve unauthenticated
    traffic (see its docstring).

    **The interactive docs are off unless ``DOCS_ENABLED`` says otherwise.**
    FastAPI's defaults publish ``/openapi.json``, ``/docs`` and ``/redoc`` to
    anyone who can reach the port, with no session and no key -- which hands an
    unauthenticated caller the complete write surface: every route path, every
    request body schema, and the name of the ``X-API-Key`` header. None of that
    is a secret on its own, and none of it should be free either. Passing
    ``None`` for the three URLs is what actually unregisters the routes (a
    dependency on the docs endpoints would still leave the schema reachable
    through ``/openapi.json``); a deployment that wants them opts in.
    """
    settings = settings or get_settings()
    docs = settings.docs_enabled
    app = FastAPI(
        title="Receipt review API",
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.session_factory = session_factory
    app.state.storage = storage
    app.state.settings = settings
    app.state.submit = submit or _default_submit
    install_session_middleware(app, settings)
    app.include_router(build_auth_router())
    _install_error_handlers(app)
    _install_read_routes(app)
    _install_write_routes(app)
    _install_spa(app, settings)
    return app
