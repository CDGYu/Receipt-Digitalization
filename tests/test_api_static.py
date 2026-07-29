"""The SPA static mount (P5.T0, design §3.3).

``pytest.importorskip("fastapi")`` keeps the base suite offline, matching
``tests/test_api_read.py``.

The mount must be invisible until the frontend has actually been built: a
base install, a fresh CI checkout, and every developer who has never run
``npm`` must still be able to construct the app.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from config.settings import Settings  # noqa: E402
from receipts.ingest.storage import LocalStorage  # noqa: E402
from receipts.persist.models import Base  # noqa: E402
from receipts.persist.session import make_engine, make_session_factory  # noqa: E402
from receipts.review.api import create_app  # noqa: E402

INDEX_HTML = "<!doctype html><title>Review</title><div id=root></div>"


@pytest.fixture()
def session_factory(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'receipts.db').as_posix()}")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)


def _build(session_factory, tmp_path, dist_dir):
    """An app whose ``frontend_dist`` points at ``dist_dir`` (built or not)."""
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        session_cookie_secure=False,
        frontend_dist=str(dist_dir),
    )
    return create_app(
        session_factory=session_factory,
        storage=LocalStorage(tmp_path / "blobs"),
        submit=lambda job: None,
        settings=settings,
    )


def _built_dist(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    return dist


def test_create_app_succeeds_when_the_frontend_was_never_built(session_factory, tmp_path):
    """The guard: an absent dist directory must not break app construction."""
    app = _build(session_factory, tmp_path, tmp_path / "does-not-exist")
    client = TestClient(app)
    assert client.get("/health").status_code == 200


def test_app_path_is_not_served_when_the_frontend_was_never_built(session_factory, tmp_path):
    app = _build(session_factory, tmp_path, tmp_path / "does-not-exist")
    client = TestClient(app)
    assert client.get("/app/").status_code == 404


def test_built_frontend_is_served_at_app(session_factory, tmp_path):
    app = _build(session_factory, tmp_path, _built_dist(tmp_path))
    client = TestClient(app)
    response = client.get("/app/")
    assert response.status_code == 200
    assert "<div id=root></div>" in response.text


def test_spa_deep_link_falls_back_to_the_shell(session_factory, tmp_path):
    """A hard refresh on a client-side route must return index.html, not 404."""
    app = _build(session_factory, tmp_path, _built_dist(tmp_path))
    client = TestClient(app)
    response = client.get("/app/review")
    assert response.status_code == 200
    assert "<div id=root></div>" in response.text


def test_the_spa_never_shadows_an_api_path(session_factory, tmp_path):
    """``/health`` stays the API's JSON even with a built frontend mounted.

    This is a **structural** property of the ``/app`` prefix, not an
    ordering dependency: a Starlette mount only ever intercepts paths under
    its own prefix, so a mount at ``/app`` cannot compete with ``/health``
    at any registration order -- reproduced by hand: moving ``_install_spa``
    to run *before* the read routes still leaves this test (and the whole
    file) green. It stays in the suite as a guard against a real, narrower
    risk: a future change that moves the mount to ``/`` instead of ``/app``,
    where registration order would start to matter.
    """
    app = _build(session_factory, tmp_path, _built_dist(tmp_path))
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert "<div id=root></div>" not in response.text
