"""The processing-mode setting: persistence, the ladder mapping, and the routes.

Three layers, tested where each one lives:

* :mod:`receipts.persist.app_settings` -- the store (get/set default, upsert,
  attribution) and the two pure functions the run paths call
  (``apply_processing_mode`` rewrites the settings; ``available_modes`` reports
  which modes are distinct for a deployment).
* The ladder mapping is checked against ``make_extract_ladder`` directly, so the
  test proves the *rungs* a mode produces, not just the field edits: local is one
  rung, hybrid is two, cloud is one rung pointed at the cloud model.
* The API -- ``GET /processing-mode`` readable by any user, ``PATCH`` admin-only,
  an unknown mode a 400, a write attributed and reflected by the next read.

Offline throughout: a SQLite file DB (``:memory:`` does not survive the separate
connections a ``TestClient`` opens) and the ``fake`` provider, so no network and
no model.
"""

from __future__ import annotations

import pytest

from config.settings import Settings

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from receipts.extract.clients.factory import make_extract_ladder  # noqa: E402
from receipts.extract.clients.fake import FakeVLMClient  # noqa: E402
from receipts.ingest.storage import LocalStorage  # noqa: E402
from receipts.persist.app_settings import (  # noqa: E402
    DEFAULT_PROCESSING_MODE,
    MODE_CLOUD,
    MODE_HYBRID,
    MODE_LOCAL,
    apply_processing_mode,
    available_modes,
    get_processing_mode,
    set_processing_mode,
    settings_for_run,
)
from receipts.persist.models import AppSetting, Base  # noqa: E402
from receipts.persist.session import make_engine, make_session_factory  # noqa: E402
from receipts.persist.users import ROLE_ADMIN, ROLE_REVIEWER, create_user  # noqa: E402
from receipts.review.api import create_app  # noqa: E402

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture()
def session_factory(tmp_path):
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
    """Hermetic settings with a configured cloud tier, so all three modes differ."""
    return Settings(
        _env_file=None,
        session_secret="test-secret",
        session_cookie_secure=False,
        vlm_provider="fake",
        vlm_model_extract="local-model",
        vlm_model_triage="local-triage",
        vlm_model_extract_fallback="cloud-model",
        vlm_model_triage_fallback="cloud-triage",
    )


@pytest.fixture()
def app(session_factory, settings, tmp_path):
    return create_app(
        session_factory=session_factory,
        storage=LocalStorage(tmp_path / "blobs"),
        submit=lambda job: None,
        settings=settings,
    )


def _logged_in(app, username: str, password: str) -> TestClient:
    client = TestClient(app)
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return client


@pytest.fixture()
def reviewer_client(app) -> TestClient:
    return _logged_in(app, "alice", "pw-alice")


@pytest.fixture()
def admin_client(app) -> TestClient:
    return _logged_in(app, "bob", "pw-bob")


# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #


def test_an_unset_mode_reads_as_the_default(session_factory):
    """A deployment that has never opened the setting is not an error: it is the
    default, and the default is the pre-feature behaviour (hybrid)."""
    with session_factory() as session:
        assert get_processing_mode(session) == DEFAULT_PROCESSING_MODE
        assert DEFAULT_PROCESSING_MODE == MODE_HYBRID


def test_set_then_get_round_trips_and_attributes(session_factory):
    with session_factory() as session:
        set_processing_mode(session, MODE_LOCAL, updated_by="bob")
        session.commit()
    with session_factory() as session:
        assert get_processing_mode(session) == MODE_LOCAL
        row = session.get(AppSetting, "processing_mode")
        assert row is not None
        assert row.updated_by == "bob"


def test_set_upserts_the_singleton_rather_than_inserting_twice(session_factory):
    with session_factory() as session:
        set_processing_mode(session, MODE_LOCAL, updated_by="bob")
        set_processing_mode(session, MODE_CLOUD, updated_by="alice")
        session.commit()
    with session_factory() as session:
        rows = session.query(AppSetting).all()
        assert len(rows) == 1
        assert rows[0].value == MODE_CLOUD
        assert rows[0].updated_by == "alice"


def test_an_unknown_mode_is_refused_at_the_store_boundary(session_factory):
    with session_factory() as session:
        with pytest.raises(ValueError, match="unknown processing mode"):
            set_processing_mode(session, "sideways")


def test_an_unrecognised_stored_value_degrades_to_the_default(session_factory):
    """A value this build no longer understands (a downgrade after a future mode
    was added, say) reads as the default rather than propagating a token the
    ladder cannot map."""
    with session_factory() as session:
        session.add(AppSetting(key="processing_mode", value="quantum"))
        session.commit()
    with session_factory() as session:
        assert get_processing_mode(session) == DEFAULT_PROCESSING_MODE


# --------------------------------------------------------------------------- #
# The ladder mapping -- rungs, not just fields
# --------------------------------------------------------------------------- #


def test_hybrid_builds_a_local_primary_and_a_cloud_fallback(settings):
    """Hybrid is unchanged: two rungs, the local one probing and the cloud one
    behind it -- exactly what a configured fallback already produces."""
    tuned = apply_processing_mode(settings, MODE_HYBRID)
    _t, _tf, extract, extract_fb = make_extract_ladder(tuned)
    assert isinstance(extract, FakeVLMClient)
    assert extract_fb is not None  # the cloud rung exists


def test_local_builds_a_single_rung_with_no_cloud_fallback(settings):
    """Local drops the fallback: the ladder is one local rung and never
    escalates to the cloud."""
    tuned = apply_processing_mode(settings, MODE_LOCAL)
    assert tuned.vlm_model_extract == "local-model"
    assert tuned.vlm_model_extract_fallback is None
    assert tuned.vlm_model_triage_fallback is None
    _t, _tf, _extract, extract_fb = make_extract_ladder(tuned)
    assert extract_fb is None


def test_cloud_promotes_the_cloud_model_to_the_only_rung(settings):
    """Cloud makes the cloud model the sole rung: no local attempt, no
    fallback."""
    tuned = apply_processing_mode(settings, MODE_CLOUD)
    assert tuned.vlm_model_extract == "cloud-model"
    assert tuned.vlm_model_triage == "cloud-triage"
    assert tuned.vlm_model_extract_fallback is None
    assert tuned.vlm_model_triage_fallback is None
    _t, _tf, _extract, extract_fb = make_extract_ladder(tuned)
    assert extract_fb is None


def test_cloud_degrades_to_local_when_no_cloud_model_is_configured():
    """A deployment that never configured a cloud tier cannot be pointed at one.
    Cloud keeps the local model rather than clearing the primary and building a
    ladder with no rungs at all."""
    local_only = Settings(
        _env_file=None,
        vlm_provider="fake",
        vlm_model_extract="local-model",
    )
    tuned = apply_processing_mode(local_only, MODE_CLOUD)
    assert tuned.vlm_model_extract == "local-model"


def test_available_modes_reports_distinctness(settings):
    """All three are distinct when a cloud model is configured; only local is
    distinct when none is, because the other two would build the same rung."""
    assert set(available_modes(settings)) == {MODE_HYBRID, MODE_LOCAL, MODE_CLOUD}
    local_only = Settings(_env_file=None, vlm_provider="fake", vlm_model_extract="m")
    assert available_modes(local_only) == (MODE_LOCAL,)


def test_settings_for_run_folds_the_stored_mode_in(session_factory, settings):
    """The one call the run paths make: the stored mode is applied to the
    settings before the ladder is built."""
    with session_factory() as session:
        set_processing_mode(session, MODE_LOCAL)
        session.commit()
    tuned = settings_for_run(settings, session_factory)
    assert tuned.vlm_model_extract_fallback is None


def test_apply_rejects_an_unknown_literal(settings):
    with pytest.raises(ValueError, match="unknown processing mode"):
        apply_processing_mode(settings, "sideways")


# --------------------------------------------------------------------------- #
# The routes
# --------------------------------------------------------------------------- #


def test_a_reviewer_may_read_the_mode(reviewer_client):
    response = reviewer_client.get("/processing-mode")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == MODE_HYBRID  # the default, nothing set yet
    assert body["modes"] == [MODE_HYBRID, MODE_LOCAL, MODE_CLOUD]
    assert set(body["available"]) == {MODE_HYBRID, MODE_LOCAL, MODE_CLOUD}


def test_a_reviewer_may_not_write_the_mode(reviewer_client):
    response = reviewer_client.patch("/processing-mode", json={"mode": MODE_LOCAL})
    assert response.status_code == 403


def test_an_admin_writes_the_mode_and_the_next_read_reflects_it(admin_client):
    write = admin_client.patch("/processing-mode", json={"mode": MODE_CLOUD})
    assert write.status_code == 200
    assert write.json()["mode"] == MODE_CLOUD

    read = admin_client.get("/processing-mode")
    assert read.json()["mode"] == MODE_CLOUD


def test_an_admin_write_is_attributed(admin_client, session_factory):
    admin_client.patch("/processing-mode", json={"mode": MODE_LOCAL})
    with session_factory() as session:
        row = session.get(AppSetting, "processing_mode")
        assert row is not None
        assert row.updated_by == "bob"


def test_an_unknown_mode_is_a_400_with_the_servers_message(admin_client):
    response = admin_client.patch("/processing-mode", json={"mode": "sideways"})
    assert response.status_code == 400
    assert "unknown processing mode" in response.json()["error"]["message"]


def test_reading_the_mode_requires_a_session(app):
    """Signed out is a 401, like every other ``require_user`` route."""
    anonymous = TestClient(app)
    assert anonymous.get("/processing-mode").status_code == 401
