"""The review API's app factory and read routes (P4.T4, spec §14.9).

:func:`create_app` is the one place that assembles the service: it wires the
four pieces of state Task 3's guards already read off ``app.state``
(``session_factory``, ``storage``, ``settings``, ``submit``), installs the
signed-cookie session middleware (:func:`~receipts.review.auth.
install_session_middleware`, which refuses to start without
``SESSION_SECRET`` -- see its docstring for why that is a hard failure and
not a generated default), mounts the auth router
(:func:`~receipts.review.auth.build_auth_router`), installs the error
handlers, and installs this task's read routes: ``GET /health``,
``GET /receipts``, ``GET /receipts/{id}``, ``GET /metrics``.

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

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from starlette.exceptions import HTTPException as StarletteHTTPException

from config.settings import Settings, get_settings

from ..ingest.ingest import ReceiptJob
from ..persist.models import Receipt
from ..persist.repository import get_findings, get_receipt, query_receipts
from ..score.confidence import ReceiptStatus
from ..score.thresholds import AUTO_APPROVE_THRESHOLD, REVIEW_THRESHOLD
from .auth import SessionUser, build_auth_router, install_session_middleware, require_user
from .queue import queue_stats
from .schemas import ErrorBody, ErrorDetail, HealthStatus, MetricsResponse, ReceiptListResponse
from .serializers import receipt_detail, receipt_summary

__all__ = ["create_app"]


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
                "auto_approve": str(AUTO_APPROVE_THRESHOLD),
                "review": str(REVIEW_THRESHOLD),
            },
        }


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
    session auth, the auth router, the error handlers, and this task's read
    routes, in that order.

    ``install_session_middleware`` is called unconditionally: an app with no
    ``SESSION_SECRET`` must fail at construction, not serve unauthenticated
    traffic (see its docstring).
    """
    settings = settings or get_settings()
    app = FastAPI(title="Receipt review API")
    app.state.session_factory = session_factory
    app.state.storage = storage
    app.state.settings = settings
    app.state.submit = submit or _default_submit
    install_session_middleware(app, settings)
    app.include_router(build_auth_router())
    _install_error_handlers(app)
    _install_read_routes(app)
    return app
