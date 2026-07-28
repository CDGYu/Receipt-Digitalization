"""Tests for session auth, role guards, and the machine upload key (P4.T3).

``pytest.importorskip("fastapi")`` keeps the base test suite offline and free
of the optional ``api`` extra, matching how ``test_process_receipt.py`` guards
on ``PIL``.

A *minimal* probe app is built inside this module -- it mounts the real
``build_auth_router()`` plus three routes wired to the real dependencies
(``require_user``, ``require_role``, ``require_upload``) -- so the guards are
proven end to end without waiting on Task 4's actual review app.

The load-bearing behaviours pinned down below:

  * no session cookie -> 401; the wrong role on a role-gated route -> 403.
  * a login sets the session cookie (username only) and logout clears it.
  * an unknown username and a wrong password produce byte-identical 401
    responses -- ``verify_credentials`` already guarantees this; this module
    proves the web layer does not leak the distinction back in.
  * deactivating a user invalidates their *live* session immediately, because
    the role and ``is_active`` are re-read from the database on every request
    rather than trusted from the cookie.
  * the machine API key authorizes ``require_upload`` but is never accepted by
    ``require_user`` -- a key is not a person and must not show up as one.
  * an unset ``RECEIPTS_API_KEY`` rejects every ``X-API-Key`` header,
    including an empty one.
  * ``sign_url``/``verify_signature`` expire on schedule, reject a payload
    swap, and reject a signature made with a different secret -- all without
    sleeping, via the injectable ``now``.
  * ``install_session_middleware`` refuses to start without ``SESSION_SECRET``.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import Depends, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from config.settings import Settings  # noqa: E402
from receipts.persist.models import Base  # noqa: E402
from receipts.persist.session import make_engine, make_session_factory  # noqa: E402
from receipts.persist.users import (  # noqa: E402
    ROLE_ADMIN,
    ROLE_REVIEWER,
    create_user,
    deactivate,
)
from receipts.review.auth import (  # noqa: E402
    SessionUser,
    build_auth_router,
    install_session_middleware,
    require_role,
    require_upload,
    require_user,
    sign_url,
    verify_signature,
)


@pytest.fixture()
def session_factory(tmp_path):
    """A file-backed SQLite database (shared across threads, unlike ``:memory:``)

    seeded with a reviewer (alice) and an admin (bob).
    """
    engine = make_engine(f"sqlite:///{(tmp_path / 'receipts.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        create_user(session, "alice", "pw-alice", ROLE_REVIEWER)
        create_user(session, "bob", "pw-bob", ROLE_ADMIN)
        session.commit()
    return factory


@pytest.fixture()
def settings() -> Settings:
    """Hermetic settings: a developer's ``.env`` must not steer these tests."""
    return Settings(_env_file=None, session_secret="test-secret", session_cookie_secure=False)


def _probe_app(session_factory, settings):
    app = FastAPI()
    app.state.session_factory = session_factory
    app.state.settings = settings
    install_session_middleware(app, settings)
    app.include_router(build_auth_router())

    @app.get("/probe/any")
    def any_role(user: SessionUser = Depends(require_user)):
        return {"username": user.username, "role": user.role}

    @app.get("/probe/admin")
    def admin_only(user: SessionUser = Depends(require_role(ROLE_ADMIN))):
        return {"ok": True}

    @app.post("/probe/upload")
    def upload(user=Depends(require_upload)):
        return {"ok": True}

    return app


@pytest.fixture()
def client(session_factory, settings) -> TestClient:
    return TestClient(_probe_app(session_factory, settings))


@pytest.fixture()
def client_with_key(session_factory) -> TestClient:
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        session_cookie_secure=False,
        receipts_api_key="s3cret-machine-key",
    )
    return TestClient(_probe_app(session_factory, settings))


def test_no_credentials_is_401(client):
    assert client.get("/probe/any").status_code == 401


def test_reviewer_on_an_admin_route_is_403(client):
    client.post("/auth/login", json={"username": "alice", "password": "pw-alice"})
    assert client.get("/probe/admin").status_code == 403


def test_login_sets_a_session_and_logout_clears_it(client):
    assert (
        client.post("/auth/login", json={"username": "alice", "password": "pw-alice"}).status_code
        == 200
    )
    assert client.get("/probe/any").json()["role"] == "reviewer"
    assert client.post("/auth/logout").status_code == 204
    assert client.get("/probe/any").status_code == 401


def test_wrong_password_and_unknown_user_are_indistinguishable(client):
    wrong = client.post("/auth/login", json={"username": "alice", "password": "nope"})
    missing = client.post("/auth/login", json={"username": "nobody", "password": "nope"})
    assert wrong.status_code == missing.status_code == 401
    assert wrong.json() == missing.json()


def test_deactivating_a_user_invalidates_their_live_session(client, session_factory):
    client.post("/auth/login", json={"username": "alice", "password": "pw-alice"})
    with session_factory() as session:
        deactivate(session, "alice")
        session.commit()
    # The role is re-read per request, so this takes effect now, not at expiry.
    assert client.get("/probe/any").status_code == 401


def test_api_key_uploads_but_cannot_read(client_with_key):
    headers = {"X-API-Key": "s3cret-machine-key"}
    assert client_with_key.post("/probe/upload", headers=headers).status_code == 200
    assert client_with_key.get("/probe/any", headers=headers).status_code == 401


def test_an_unset_api_key_rejects_every_key_header(client):  # settings.receipts_api_key is None
    assert client.post("/probe/upload", headers={"X-API-Key": ""}).status_code == 401
    assert client.post("/probe/upload", headers={"X-API-Key": "anything"}).status_code == 401


def test_signed_urls_expire_and_detect_tampering():
    """``now`` is injected so expiry is proven without sleeping."""
    secret, payload = "test-secret", "receipt-a|original"
    signature, exp = sign_url(payload, secret=secret, ttl_s=300, now=1_000)

    assert verify_signature(payload, secret=secret, signature=signature, exp=exp, now=1_000)
    # One second past the expiry.
    assert not verify_signature(payload, secret=secret, signature=signature, exp=exp, now=1_301)
    # Same signature, different receipt.
    assert not verify_signature(
        "receipt-b|original", secret=secret, signature=signature, exp=exp, now=1_000
    )
    # Same payload, someone else's secret.
    assert not verify_signature(
        payload, secret="other-secret", signature=signature, exp=exp, now=1_000
    )


def test_create_app_refuses_to_start_without_a_session_secret(session_factory, tmp_path):
    """A random per-process default would sign users out on every restart."""
    from receipts.review.auth import install_session_middleware

    app = FastAPI()
    with pytest.raises(ValueError, match="SESSION_SECRET"):
        install_session_middleware(app, Settings(session_secret=None))
