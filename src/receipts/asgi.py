"""The ASGI entry point: the supported way to serve the review API (ADR-0035).

    uvicorn receipts.asgi:app

Everything the service needs is built from :class:`~config.settings.Settings`,
and **nothing is built at import time**. Importing this module opens no
database, reads no ``.env`` and touches no filesystem; ``app`` is resolved by
the module-level ``__getattr__`` below, on first access. ADR-0014 exists
because two shipped defects put optional dependencies on an import path, and a
module whose *import* requires a configured database is the same shape --
``python -c "import receipts.asgi"`` works on a base install with no
configuration at all.

**This module's job is to refuse, not merely to construct.** ``make_engine``
resolves its URL as ``url or Settings().database_url or DEFAULT_URL``, and
``DEFAULT_URL`` is ``sqlite:///receipts.db`` -- so the obvious entry point
serves production off a local file when ``DATABASE_URL`` is unset, with nothing
logged and nothing failing. :func:`_check_boot_config` is the answer to that,
and every other check here earns its place the same way: the misconfiguration
is silent, and the symptom appears somewhere far from the cause.

What this module deliberately does **not** decide: host, port, workers, proxy
headers, TLS, process supervision, and migrations. Those belong to the
``uvicorn`` invocation or the platform around it. This exposes an ASGI app and
nothing else.

``scripts/serve_review_e2e.py`` is unaffected and stays what it is -- a
loopback launcher for the Playwright acceptance run, with a published secret
and uploads that refuse. Its docstring lists the choices a real deployment must
revisit; this module is where they were made.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from config.settings import Settings, get_settings

from .ingest.storage import make_storage
from .persist.session import DEFAULT_URL, make_engine, make_session_factory
from .review.api import create_app

if TYPE_CHECKING:  # pragma: no cover - typing only
    from fastapi import FastAPI

__all__ = ["create_asgi_app"]


def _check_boot_config(settings: Settings) -> None:
    """Refuse to start on a misconfiguration whose symptom would be silent.

    **Collects every failure and raises once.** A misconfigured deployment
    should learn everything that is wrong from one attempt rather than one item
    per restart, which is what a chain of early returns would give it.

    Raises ``ValueError``, matching
    :func:`~receipts.review.auth.install_session_middleware`, which already
    raises it for a missing ``SESSION_SECRET``. One type for every boot failure
    means a caller wrapping :func:`create_asgi_app` catches all of them with one
    ``except``. That type is also the API's 400 currency (ADR-0006), which is
    safe here: these raise during app *construction*, before any request exists
    and before the error handlers are installed.

    ``SESSION_SECRET`` is deliberately not re-checked --
    ``install_session_middleware`` refuses without it a few frames later, and
    two checks of one condition is two places to keep in agreement.
    """
    problems: list[str] = []

    if not settings.database_url:
        problems.append(
            # The default is interpolated rather than quoted, so this sentence
            # cannot drift from the value it warns about (ADR-0032 section 3).
            f"DATABASE_URL is not set. Without it the service would run on "
            f"{DEFAULT_URL!r}, a local file, and say nothing about it."
        )

    if not settings.session_cookie_secure and not settings.allow_insecure_session_cookie:
        problems.append(
            "SESSION_COOKIE_SECURE is false, so session cookies would travel in "
            "cleartext. Set it true, or set ALLOW_INSECURE_SESSION_COOKIE=true "
            "to say that is intended."
        )

    if not settings.redis_url:
        problems.append(
            "REDIS_URL is not set, so POST /upload could not queue work. The "
            "failure would otherwise appear at the first upload rather than here."
        )

    if settings.serve_spa:
        dist = Path(settings.frontend_dist)
        if not dist.is_dir() or not (dist / "index.html").is_file():
            problems.append(
                f"SERVE_SPA is true but FRONTEND_DIST ({settings.frontend_dist!r}) "
                "holds no index.html -- run `npm run build` in frontend/, point "
                "FRONTEND_DIST at the build, or set SERVE_SPA=false for an "
                "API-only deployment. Otherwise /app/* would 404 with no "
                "explanation."
            )

    if problems:
        raise ValueError(
            "receipts.asgi refuses to start:\n"
            + "\n".join(f"  - {problem}" for problem in problems)
        )


def create_asgi_app(settings: Settings | None = None) -> FastAPI:
    """Build the served application, or raise explaining why it cannot be.

    ``settings`` is injectable so the boot contract is unit-testable without an
    environment: every test constructs :class:`Settings` explicitly rather than
    discovering one. Left ``None``, it reads the process environment and
    ``.env`` through :func:`~config.settings.get_settings`, which is what
    ``uvicorn receipts.asgi:app`` does.

    ``submit`` is left at ``create_app``'s default, so uploads reach the real
    RQ queue via its lazily-imported ``_default_submit``. ``REDIS_URL`` having
    been checked above is what makes that default reasonable here.
    """
    resolved = settings if settings is not None else get_settings()
    _check_boot_config(resolved)

    engine = make_engine(resolved.database_url)
    return create_app(
        session_factory=make_session_factory(engine),
        storage=make_storage(resolved),
        settings=resolved,
    )


def __getattr__(name: str) -> Any:
    """Resolve ``app`` lazily, so importing this module builds nothing.

    PEP 562. ``uvicorn receipts.asgi:app`` resolves its target with ``getattr``,
    so this is enough to make the documented invocation work while keeping the
    import side-effect free. Anything else raises ``AttributeError`` normally,
    so a typo stays a typo rather than becoming a confusing failure elsewhere.
    """
    if name == "app":
        return create_asgi_app()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
