"""Tests for the ASGI entry point (``receipts.asgi``) and its boot contract.

``pytest.importorskip("fastapi")`` keeps the base test suite offline, matching
``tests/test_api_read.py``.

Every case here builds :class:`Settings` explicitly and passes it in. Nothing
reads the environment, nothing reads ``.env``, and nothing needs Postgres,
Redis or a built frontend -- the point of the entry point is that it *refuses*
on configuration, so the configuration has to be constructed rather than
discovered.
"""

from __future__ import annotations

import importlib
import sys

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402

from config.settings import Settings  # noqa: E402
from receipts import asgi  # noqa: E402


def _good(tmp_path, **overrides):
    """Settings that satisfy every boot check, before ``overrides`` are applied.

    The baseline has to pass on its own, or a test that flips one field to a
    bad value would be measuring the baseline instead of the field. That is
    what ``test_the_baseline_settings_boot`` exists to prove.
    """
    dist = tmp_path / "dist"
    dist.mkdir(exist_ok=True)
    (dist / "index.html").write_text("<!doctype html>", encoding="utf-8")

    values = {
        "_env_file": None,
        "database_url": f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        "redis_url": "redis://localhost:6379/0",
        "session_secret": "not-a-real-secret",
        "session_cookie_secure": True,
        "storage_backend": "local",
        "storage_root": str(tmp_path / "blobs"),
        "frontend_dist": str(dist),
    }
    values.update(overrides)
    return Settings(**values)


def test_the_baseline_settings_boot(tmp_path) -> None:
    """The control. Without it every refusal below could pass vacuously."""
    app = asgi.create_asgi_app(settings=_good(tmp_path))

    assert isinstance(app, FastAPI)


# --------------------------------------------------------------------------- #
# The four refusals, one reverted at a time
# --------------------------------------------------------------------------- #


def test_it_refuses_when_database_url_is_unset(tmp_path) -> None:
    """The hazard the whole module exists for.

    ``make_engine`` resolves ``url or Settings().database_url or DEFAULT_URL``,
    and ``DEFAULT_URL`` is ``sqlite:///receipts.db``. Unset, the service would
    run on a local file and say nothing.
    """
    with pytest.raises(ValueError, match="DATABASE_URL"):
        asgi.create_asgi_app(settings=_good(tmp_path, database_url=None))


def test_it_refuses_an_insecure_session_cookie(tmp_path) -> None:
    """``create_app`` only logs a warning for this; the entry point refuses."""
    with pytest.raises(ValueError, match="SESSION_COOKIE_SECURE"):
        asgi.create_asgi_app(settings=_good(tmp_path, session_cookie_secure=False))


def test_it_refuses_when_redis_url_is_unset(tmp_path) -> None:
    """Without a broker ``POST /upload`` cannot queue -- caught at boot."""
    with pytest.raises(ValueError, match="REDIS_URL"):
        asgi.create_asgi_app(settings=_good(tmp_path, redis_url=None))


def test_it_refuses_when_the_spa_is_requested_but_not_built(tmp_path) -> None:
    """``_install_spa`` skips silently, so ``/app/*`` would 404 unexplained."""
    empty = tmp_path / "not-built"
    empty.mkdir()

    with pytest.raises(ValueError, match="FRONTEND_DIST"):
        asgi.create_asgi_app(settings=_good(tmp_path, frontend_dist=str(empty)))


# --------------------------------------------------------------------------- #
# Collecting failures, rather than reporting the first
# --------------------------------------------------------------------------- #


def test_every_failure_is_reported_from_one_boot_attempt(tmp_path) -> None:
    """A misconfigured deployment learns everything wrong in one restart.

    Asserts on **membership**, not on a count: a message naming three problems
    when four are present would satisfy any assertion about "several", and
    counting is what review standard 23 warns against.
    """
    broken = _good(
        tmp_path,
        database_url=None,
        redis_url=None,
        session_cookie_secure=False,
        frontend_dist=str(tmp_path / "nope"),
    )

    with pytest.raises(ValueError) as caught:
        asgi.create_asgi_app(settings=broken)

    message = str(caught.value)
    for name in ("DATABASE_URL", "REDIS_URL", "SESSION_COOKIE_SECURE", "FRONTEND_DIST"):
        assert name in message, f"{name} missing from: {message}"


# --------------------------------------------------------------------------- #
# The two escape hatches
# --------------------------------------------------------------------------- #


def test_an_insecure_cookie_boots_when_it_is_declared(tmp_path) -> None:
    settings = _good(
        tmp_path, session_cookie_secure=False, allow_insecure_session_cookie=True
    )

    assert isinstance(asgi.create_asgi_app(settings=settings), FastAPI)


def test_an_api_only_deployment_boots_with_no_frontend(tmp_path) -> None:
    settings = _good(tmp_path, serve_spa=False, frontend_dist=str(tmp_path / "nope"))

    assert isinstance(asgi.create_asgi_app(settings=settings), FastAPI)


def test_serve_spa_false_leaves_app_unmounted_even_when_dist_exists(tmp_path) -> None:
    """"Do not serve the SPA" has to mean it, or the flag lies.

    The built ``dist`` from ``_good`` is present and valid here; only the flag
    differs. Without this case, ``serve_spa=False`` could be satisfied by the
    boot check alone while ``create_app`` mounted the SPA anyway.
    """
    served = asgi.create_asgi_app(settings=_good(tmp_path))
    unserved = asgi.create_asgi_app(settings=_good(tmp_path, serve_spa=False))

    # ``getattr``, not ``route.path``: ``include_router`` leaves an
    # ``_IncludedRouter`` in ``app.routes`` that has no ``path`` at all, and
    # reaching for the attribute directly raises before the comparison runs.
    # ADR-0028 section 3 names this trap; it caught this test on first run.
    def mounts_the_spa(app):
        return any(getattr(route, "path", None) == "/app" for route in app.routes)

    assert mounts_the_spa(served)
    assert not mounts_the_spa(unserved)


# --------------------------------------------------------------------------- #
# The lazy attribute
# --------------------------------------------------------------------------- #


def test_importing_the_module_builds_nothing(monkeypatch) -> None:
    """Importing must not open a database or read the environment.

    Proven in an environment where ``create_asgi_app()`` would raise: every
    relevant variable is cleared and ``.env`` cannot help, so an import that
    built the app would fail here. ADR-0014 is why this matters -- a module
    whose import needs a configured database is the same defect as one whose
    import needs an optional dependency.
    """
    for name in ("DATABASE_URL", "REDIS_URL", "SESSION_SECRET", "FRONTEND_DIST"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delitem(sys.modules, "receipts.asgi", raising=False)

    reimported = importlib.import_module("receipts.asgi")

    assert reimported.create_asgi_app is not None


def test_the_app_attribute_builds_an_app(tmp_path, monkeypatch) -> None:
    """``uvicorn receipts.asgi:app`` resolves through ``getattr``."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'a.db').as_posix()}")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SESSION_SECRET", "not-a-real-secret")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "true")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "blobs"))
    monkeypatch.setenv("FRONTEND_DIST", str(dist))

    # Attribute access, not `getattr(asgi, "app")`: both compile to the same
    # lookup and both land in `__getattr__`, and ruff's B009 rejects the
    # explicit form. Uvicorn resolves its target the same way.
    assert isinstance(asgi.app, FastAPI)


def test_an_unknown_attribute_still_raises(tmp_path) -> None:
    """The hook must not swallow typos into a confusing failure elsewhere."""
    with pytest.raises(AttributeError):
        asgi.aap  # noqa: B018
