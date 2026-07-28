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

import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Callable

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from config.settings import Settings
from receipts.persist.users import get_user, verify_credentials

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
    """
    if not settings.session_secret:
        raise ValueError(
            "SESSION_SECRET is required to run the review API; a random "
            "per-process default would sign users out on every restart and "
            "hide the misconfiguration"
        )
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        https_only=settings.session_cookie_secure,
        same_site="lax",
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
    if configured and presented and hmac.compare_digest(configured, presented):
        return None  # a machine, not a person
    return require_user(request)


class _LoginBody(BaseModel):
    username: str
    password: str


def build_auth_router() -> APIRouter:
    """``POST /auth/login`` and ``POST /auth/logout``."""
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

    @router.post("/auth/logout")
    def logout(request: Request) -> Response:
        request.session.clear()
        return Response(status_code=204)

    return router


def sign_url(payload: str, *, secret: str, ttl_s: int, now: int | None = None) -> tuple[str, int]:
    """Return ``(signature, exp)`` for ``payload``, valid for ``ttl_s`` seconds.

    ``now`` is injectable so a test can prove expiry without sleeping; a
    ``None`` default reads the wall clock.
    """
    exp = (now if now is not None else int(time.time())) + ttl_s
    message = f"{payload}|{exp}".encode()
    signature = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return signature, exp


def verify_signature(
    payload: str, *, secret: str, signature: str, exp: int, now: int | None = None
) -> bool:
    """Whether ``signature`` is valid for ``payload``/``exp`` and not expired."""
    current = now if now is not None else int(time.time())
    if exp < current:
        return False
    message = f"{payload}|{exp}".encode()
    expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
