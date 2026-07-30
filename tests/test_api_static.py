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
from starlette.staticfiles import StaticFiles  # noqa: E402

from config.settings import Settings  # noqa: E402
from receipts.ingest.storage import LocalStorage  # noqa: E402
from receipts.persist.models import Base  # noqa: E402
from receipts.persist.session import make_engine, make_session_factory  # noqa: E402
from receipts.review.api import create_app  # noqa: E402

INDEX_HTML = "<!doctype html><title>Review</title><div id=root></div>"
# No trailing newline: ``write_text`` translates "\n" to the platform line
# ending, which would not match the bytes the client reads back on Windows.
ASSET_JS = "console.log('the real bundle');"


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
    """A stand-in for ``npm run build``: a shell plus one hashed asset."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (dist / "assets" / "index-abc123.js").write_text(ASSET_JS, encoding="utf-8")
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

    What this test actually catches was established by mutating each
    guarantee separately and observing which mutation trips it:

    * mount at ``/app``, registered last (as shipped) -- ``/health`` is
      ``200 application/json``: **passes**
    * mount moved to ``/``, still registered last -- ``/health`` is still
      ``200 application/json``: **still passes**
    * mount moved to ``/`` *and* registered before the read routes --
      ``/health`` becomes ``200 text/html`` carrying the shell: **fails**

    So this test does not catch a move to ``/`` on its own, and it does not
    catch a reordering on its own; only the conjunction of the two trips it.
    Two independent things keep the SPA off ``/health``, and either alone is
    sufficient: the ``/app`` prefix (a Starlette mount only ever intercepts
    paths under its own prefix) and registration order (Starlette matches
    routes in registration order, so a mount installed after ``/health``
    loses to it even at ``/``). This test goes red only once **both** are
    gone.
    """
    app = _build(session_factory, tmp_path, _built_dist(tmp_path))
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert "<div id=root></div>" not in response.text


def test_a_built_asset_is_served_from_the_mount(session_factory, tmp_path):
    """The companion to the narrowing below: real files must still be served.

    Cannot be proven by a RED run -- it asserts the absence of breakage, and
    it passes both before and after the fallback was narrowed. It was proven
    instead by mutation: gating ``_SpaFiles.get_response`` on the
    navigation check (rather than only the 404 fallback) turns this into a
    404 and fails it.
    """
    app = _build(session_factory, tmp_path, _built_dist(tmp_path))
    client = TestClient(app)
    response = client.get("/app/assets/index-abc123.js")
    assert response.status_code == 200
    assert response.text == ASSET_JS


@pytest.mark.parametrize(
    "path",
    ["/app/assets/index-deadbeef.js", "/app/assets/index-deadbeef.css", "/app/favicon.ico"],
)
def test_a_missing_file_under_app_is_a_404_not_the_shell(session_factory, tmp_path, path):
    """A request that names a file can never be a client-side route.

    Task 2 puts a content-hashed Vite build behind this mount. A browser
    holding a cached ``index.html`` asks for an asset hash that has since
    been purged; answering *that* with ``200`` and the HTML shell turns a
    missing file into ``Unexpected token '<'`` in the console, with no 404
    anywhere for the reviewer to point at. The history fallback is therefore
    restricted to navigations -- paths with no file extension.
    """
    app = _build(session_factory, tmp_path, _built_dist(tmp_path))
    client = TestClient(app)
    response = client.get(path)
    assert response.status_code == 404
    assert "<div id=root></div>" not in response.text


def test_a_404_html_in_the_build_cannot_shadow_the_spa_shell(session_factory, tmp_path):
    """The deep-link fallback must not depend on the build's file list.

    The mount is ``html=True``. Measured against Starlette rather than read off
    its documentation: with a ``404.html`` sitting in the served directory, a
    miss is **returned** as that file with status 404 instead of raising
    ``HTTPException``, so the ``except`` branch in ``_SpaFiles.get_response``
    never runs and every client-side route answers with the 404 page.

    Nothing in the repository puts that file there today -- ``frontend/public/``
    holds ``favicon.svg`` and nothing else -- but Vite copies ``public/``
    verbatim into ``dist/``, so adding the single most conventional file in
    static-site publishing would have broken every bookmark and every hard
    refresh under ``/app`` with no test going red. This is that test.
    """
    dist = _built_dist(tmp_path)
    (dist / "404.html").write_text("<!doctype html><title>Gone</title>", encoding="utf-8")

    app = _build(session_factory, tmp_path, dist)
    client = TestClient(app)

    response = client.get("/app/review")
    assert response.status_code == 200
    assert "<div id=root></div>" in response.text
    assert "Gone" not in response.text

    # ...and the narrowing survives it: a request that names a file is still a
    # 404, which is what the 404 page is for.
    missing = client.get("/app/assets/index-deadbeef.js")
    assert missing.status_code == 404
    assert "<div id=root></div>" not in missing.text


def test_a_half_built_dist_is_treated_as_not_built(session_factory, tmp_path):
    """An interrupted ``npm run build`` must not mount at all.

    A directory that exists but holds no ``index.html`` -- an interrupted
    build, or ``FRONTEND_DIST`` pointed at some other real directory -- would
    otherwise mount and serve whatever happens to be in it while answering
    every SPA page with a 404.
    """
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "assets" / "index-abc123.js").write_text(ASSET_JS, encoding="utf-8")

    app = _build(session_factory, tmp_path, dist)
    client = TestClient(app)

    assert client.get("/health").status_code == 200
    assert client.get("/app/").status_code == 404
    stray = client.get("/app/assets/index-abc123.js")
    assert stray.status_code == 404
    assert stray.headers["content-type"].startswith("application/json")


def test_a_non_404_from_the_mount_still_propagates(session_factory, tmp_path, monkeypatch):
    """``_SpaFiles`` swallows a 404 and nothing else.

    Cannot be proven by a RED run -- the behaviour already worked before this
    test existed. It was proven by mutation: collapsing ``if exc.status_code
    != 404: raise`` into a bare swallow must make it fail.

    ``POST /app/`` does **not** prove that, though it looks like it should.
    ``StaticFiles`` rejects a non-GET/HEAD before it looks at the path, so
    the fallback's own ``get_response("index.html", scope)`` raises the very
    same 405 -- under a bare swallow ``POST /app/`` still answers 405
    (reproduced). It is asserted here anyway, because landing in the API's
    JSON envelope is a real contract, but it is not what pins the guard.

    A ``PermissionError`` is. ``StaticFiles`` turns it into a 401 and the
    fallback would then happily serve a perfectly readable ``index.html``
    instead, so a bare swallow turns "unreadable on disk" into ``200`` plus
    the shell. That is the assertion the mutation trips.
    """
    real_lookup = StaticFiles.lookup_path

    def deny_one(self, path):
        if "denied" in path:
            raise PermissionError(path)
        return real_lookup(self, path)

    monkeypatch.setattr(StaticFiles, "lookup_path", deny_one)

    app = _build(session_factory, tmp_path, _built_dist(tmp_path))
    client = TestClient(app)

    denied = client.get("/app/denied")
    assert denied.status_code == 401
    assert "<div id=root></div>" not in denied.text

    posted = client.post("/app/")
    assert posted.status_code == 405
    assert posted.headers["content-type"].startswith("application/json")
    assert posted.json()["error"]["message"]
    assert "<div id=root></div>" not in posted.text
