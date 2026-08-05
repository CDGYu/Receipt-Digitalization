"""Session auth, role guards, and the machine upload key (P4.T3, spec §14/§17).

Session auth over a shared API key for one structural reason:
``corrections.corrected_by`` must name a real person. A shared key cannot
attribute a correction to a reviewer, which would hollow out the audit trail
the review UI depends on. The machine key that this module also issues exists
only for unattended upload (:func:`require_upload`) and must be able to do
nothing else -- it is never accepted by :func:`require_user`.

The session cookie carries the **username only**. The role and ``is_active``
are re-read from the database (:mod:`receipts.persist.users`) on every
request, so a demotion or a deactivation takes effect on the very next
request rather than whenever a signed cookie happens to expire.

Two building blocks live here for :mod:`receipts.review.images` (Task 5) to
reuse: :func:`sign_url` and :func:`verify_signature`, HMAC-SHA256 over
``payload|exp`` with an injectable clock so expiry is provable without
sleeping in a test.
"""

from __future__ import annotations

import hmac
import logging
from dataclasses import dataclass
from typing import Annotated, Callable

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from config.settings import Settings
from receipts.persist.users import get_user, verify_credentials

from .signing import sign_url, verify_signature

__all__ = [
    "SessionUser",
    "build_auth_router",
    "install_session_middleware",
    "require_role",
    "require_upload",
    "require_user",
    "sign_url",
    "verify_signature",
]

logger = logging.getLogger(__name__)

#: The one thing the signed cookie stores. Everything else about the user is
#: re-read from the database per request; see the module docstring.
_SESSION_KEY = "username"


@dataclass(frozen=True)
class SessionUser:
    username: str
    role: str


def install_session_middleware(app: FastAPI, settings: Settings) -> None:
    """Signed-cookie sessions. Raises when SESSION_SECRET is unset.

    A random per-process fallback would sign every reviewer out on each
    restart and hide the misconfiguration instead of surfacing it -- so this
    is a hard failure, not a generated default.

    The cookie is honoured for ``settings.session_ttl_s`` seconds, enforced
    server-side by ``itsdangerous``'s ``TimestampSigner`` -- not just a
    browser-side expiry a client could ignore. Sessions are stateless signed
    cookies, so ``POST /auth/logout`` only tells the *presenting* client to
    drop its copy; it cannot revoke a cookie that has already been
    exfiltrated, which stays valid (and any request replaying it keeps
    succeeding) until ``session_ttl_s`` elapses. The actual revocation path
    for a compromised or reassigned account is
    :func:`receipts.persist.users.deactivate`, checked on every request by
    :func:`_current_user` -- see the module docstring.
    """
    if not settings.session_secret:
        raise ValueError(
            "SESSION_SECRET is required to run the review API; a random "
            "per-process default would sign users out on every restart and "
            "hide the misconfiguration"
        )
    if not settings.session_cookie_secure:
        logger.warning(
            "SESSION_COOKIE_SECURE is false: the session cookie is sent "
            "without the Secure flag and can travel in cleartext over plain "
            "HTTP. Fine for local development; never for anything reachable "
            "over the network."
        )
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        https_only=settings.session_cookie_secure,
        same_site="lax",
        max_age=settings.session_ttl_s,
    )


def _current_user(request: Request) -> SessionUser | None:
    """Resolve the session cookie against the database, or ``None``.

    The cookie carries the username only; the role and ``is_active`` are read
    fresh on every request, so a demotion or a deactivation takes effect
    immediately rather than whenever a cookie happens to expire.
    """
    username = request.session.get(_SESSION_KEY)
    if not username:
        return None
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        user = get_user(session, username)
        if user is None or not user.is_active:
            return None
        return SessionUser(username=user.username, role=user.role)


def require_user(request: Request) -> SessionUser:
    user = _current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return user


def require_role(*roles: str) -> Callable[..., SessionUser]:
    def dependency(request: Request) -> SessionUser:
        user = require_user(request)
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="insufficient role")
        return user

    return dependency


def require_upload(request: Request) -> SessionUser | None:
    """The API key OR any signed-in user. The key authorizes nothing else.

    Returns ``None`` for a valid key (a machine, not a person) and a
    :class:`SessionUser` for a signed-in human; a caller distinguishes them by
    the return value. If ``RECEIPTS_API_KEY`` is unset, every ``X-API-Key``
    header is rejected -- including an empty one -- so "unset config" can
    never mean "unset header authenticates".
    """
    configured = request.app.state.settings.receipts_api_key
    presented = request.headers.get("X-API-Key")
    # Compared as bytes, not str: hmac.compare_digest() raises TypeError on a
    # non-ASCII str, and Starlette decodes header bytes as latin-1, so any
    # header byte >= 0x80 produces a non-ASCII str. A malformed key must be a
    # 401, not a 500 with a traceback, on an authentication boundary -- bytes
    # comparison never raises regardless of what was on the wire.
    if configured and presented and hmac.compare_digest(configured.encode(), presented.encode()):
        return None  # a machine, not a person
    return require_user(request)


class _LoginBody(BaseModel):
    username: str
    password: str


def build_auth_router() -> APIRouter:
    """``POST /auth/login``, ``GET /auth/me`` and ``POST /auth/logout``."""
    router = APIRouter()

    @router.post("/auth/login")
    def login(body: _LoginBody, request: Request) -> dict[str, str]:
        session_factory = request.app.state.session_factory
        with session_factory() as session:
            user = verify_credentials(session, body.username, body.password)
            if user is None:
                # Identical detail for an unknown user, a wrong password, and
                # a deactivated account -- verify_credentials() already makes
                # the three indistinguishable; this layer must not leak the
                # difference back via the response body.
                raise HTTPException(status_code=401, detail="invalid credentials")
            request.session[_SESSION_KEY] = user.username
            return {"username": user.username, "role": user.role}

    @router.get("/auth/me")
    def me(user: Annotated[SessionUser, Depends(require_user)]) -> dict[str, str]:
        """Who the caller is -- the reload path for what login already returns.

        The session cookie carries the username only and the browser cannot
        read it, so after a reload a page knows it *has* a session but not
        whose. ``POST /auth/login`` has always returned this exact body; this
        route is what makes it reachable a second time.

        Guarded by :func:`require_user`, so an anonymous caller and the
        machine key both get 401 rather than a ``{"user": null}`` body. Two
        consequences, both wanted (ADR-0026): the route stays inside
        :func:`require_user` -- the same guard every other
        *session*-authenticated route uses (:func:`require_role` builds on
        it; the machine-key and signed-blob paths are the two that do not) --
        and joins ``READ_ROUTES``; and the frontend's global 401 handler
        already turns that 401 into "signed out" with no new client logic.
        The cost is a 401 in the log on every anonymous cold load, which is
        accepted and recorded.
        """
        return {"username": user.username, "role": user.role}

    @router.post("/auth/logout")
    def logout(request: Request) -> Response:
        request.session.clear()
        return Response(status_code=204)

    return router
