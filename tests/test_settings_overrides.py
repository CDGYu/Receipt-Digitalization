"""Operator-editable system settings: the override store, the overlay, the routes.

The feature that lets an admin change tuning knobs (thresholds, buyer identity,
the spend ceiling) from the UI and have them take effect with no restart. Tested
where each layer lives:

* :mod:`receipts.persist.overrides` -- coercion, allow-list enforcement,
  type/bounds validation, the ``apply_overrides`` overlay, and the reset path.
* The overlay reaching a run through :func:`~receipts.persist.app_settings.
  settings_for_run`, so an edit is what the worker would actually use.
* The routes -- ``GET /settings`` (any user), ``PATCH /settings`` (admin only),
  atomic all-or-nothing writes, operator-facing 400s, and the API reflecting an
  override live on ``/metrics``.

Offline throughout: a SQLite file DB (``:memory:`` does not survive the separate
connections a ``TestClient`` opens) and the ``fake`` provider.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from config.settings import Settings

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from receipts.ingest.storage import LocalStorage  # noqa: E402
from receipts.persist.app_settings import settings_for_run  # noqa: E402
from receipts.persist.models import AppSetting, Base  # noqa: E402
from receipts.persist.overrides import (  # noqa: E402
    EDITABLE,
    apply_overrides,
    clear_override,
    coerce_value,
    get_overrides,
    list_effective,
    set_override,
)
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
    return Settings(
        _env_file=None,
        session_secret="test-secret",
        session_cookie_secure=False,
        vlm_provider="fake",
        auto_approve_threshold=Decimal("0.95"),
        review_threshold=Decimal("0.75"),
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
# Coercion and the store
# --------------------------------------------------------------------------- #


def test_coerce_maps_strings_to_the_field_type():
    assert coerce_value("auto_approve_threshold", "0.99") == Decimal("0.99")
    assert isinstance(coerce_value("auto_approve_threshold", "0.99"), Decimal)
    assert coerce_value("consistency_enabled", "true") is True
    assert coerce_value("consistency_enabled", "off") is False
    assert coerce_value("consistency_runs", "5") == 5
    # A blank text field means "unset".
    assert coerce_value("expected_buyer_name", "") is None
    assert coerce_value("expected_buyer_name", "Acme") == "Acme"


def test_a_decimal_override_never_becomes_a_float(session_factory, settings):
    """ADR-0001: the money path is Decimal end to end. A stored threshold must
    round-trip as a Decimal, not a float that could drift."""
    with session_factory() as session:
        set_override(session, "auto_approve_threshold", "0.925")
        session.commit()
    with session_factory() as session:
        effective = apply_overrides(settings, get_overrides(session))
    assert effective.auto_approve_threshold == Decimal("0.925")
    assert isinstance(effective.auto_approve_threshold, Decimal)


def test_set_rejects_a_field_outside_the_allow_list(session_factory):
    with session_factory() as session:
        with pytest.raises(ValueError, match="not an editable setting"):
            set_override(session, "session_secret", "hunter2")


def test_set_enforces_bounds_in_operator_terms(session_factory):
    with session_factory() as session:
        with pytest.raises(ValueError, match="at most 1"):
            set_override(session, "auto_approve_threshold", "2.0")
        with pytest.raises(ValueError, match="at least 2"):
            set_override(session, "consistency_runs", "1")


def test_set_rejects_text_that_is_not_the_type(session_factory):
    with session_factory() as session:
        with pytest.raises(ValueError, match="must be a number"):
            set_override(session, "auto_approve_threshold", "high")
        with pytest.raises(ValueError, match="whole number"):
            set_override(session, "consistency_runs", "3.5")


def test_clear_reverts_to_default(session_factory, settings):
    with session_factory() as session:
        set_override(session, "auto_approve_threshold", "0.99")
        session.commit()
    with session_factory() as session:
        clear_override(session, "auto_approve_threshold")
        session.commit()
    with session_factory() as session:
        assert get_overrides(session) == {}
        effective = apply_overrides(settings, get_overrides(session))
    assert effective.auto_approve_threshold == Decimal("0.95")  # the base value


def test_list_effective_marks_source_and_default(session_factory, settings):
    with session_factory() as session:
        set_override(session, "expected_buyer_name", "Acme Inc", updated_by="bob")
        session.commit()
    with session_factory() as session:
        rows = {row["field"]: row for row in list_effective(session, settings)}
    assert rows["expected_buyer_name"]["value"] == "Acme Inc"
    assert rows["expected_buyer_name"]["source"] == "override"
    # A threshold nobody set is the default, reported as a string (ADR-0001).
    assert rows["auto_approve_threshold"]["source"] == "default"
    assert rows["auto_approve_threshold"]["value"] == "0.95"


def test_apply_overrides_skips_an_unreadable_row(session_factory, settings):
    """A stored value that no longer coerces must never stop a receipt or a page:
    it is skipped, not raised."""
    with session_factory() as session:
        # Write a bad value directly, bypassing set_override's validation.
        session.add(AppSetting(key="override:consistency_runs", value="not-a-number"))
        session.commit()
    with session_factory() as session:
        effective = apply_overrides(settings, get_overrides(session))
    # Fell back to the base, did not raise.
    assert effective.consistency_runs == settings.consistency_runs


# --------------------------------------------------------------------------- #
# The overlay reaches a run
# --------------------------------------------------------------------------- #


def test_settings_for_run_applies_an_override(session_factory, settings):
    """The seam the worker calls per receipt: an admin's edit is what the next
    run's settings carry."""
    with session_factory() as session:
        set_override(session, "auto_approve_threshold", "0.90")
        set_override(session, "expected_buyer_name", "Acme Inc")
        session.commit()
    tuned = settings_for_run(settings, session_factory)
    assert tuned.auto_approve_threshold == Decimal("0.90")
    assert tuned.expected_buyer_name == "Acme Inc"


# --------------------------------------------------------------------------- #
# The model fields, and how they compose with the processing mode
# --------------------------------------------------------------------------- #


def test_a_model_override_reaches_the_run(session_factory, settings):
    """Switching the reading model in the UI is what the next run's ladder is
    built from -- the whole point of making it editable."""
    with session_factory() as session:
        set_override(session, "vlm_model_extract", "granite3.2-vision:9b")
        set_override(session, "vlm_model_triage", "granite3.2-vision:9b")
        session.commit()
    tuned = settings_for_run(settings, session_factory)
    assert tuned.vlm_model_extract == "granite3.2-vision:9b"
    assert tuned.vlm_model_triage == "granite3.2-vision:9b"


def test_a_blank_model_clears_back_to_the_configured_value(session_factory, settings):
    """A model field is text: blank means unset, which falls back to the .env
    value rather than an empty model id that would build a broken rung."""
    base = settings.model_copy(update={"vlm_model_extract": "configured-local"})
    with session_factory() as session:
        set_override(session, "vlm_model_extract", "")
        session.commit()
    with session_factory() as session:
        effective = apply_overrides(base, get_overrides(session))
    # The blank override is None, so the base value stands.
    assert effective.vlm_model_extract == "configured-local"


def test_model_overrides_compose_with_each_mode(settings):
    """The override sets *which* models exist; the mode decides which run. The two
    controls are complementary, and the overlay order (override then mode) is what
    makes that true."""
    from receipts.persist.app_settings import apply_processing_mode

    overridden = apply_overrides(
        settings.model_copy(
            update={
                "vlm_model_extract": "local-x",
                "vlm_model_extract_fallback": "cloud-x",
                "vlm_model_triage": "local-x",
                "vlm_model_triage_fallback": "cloud-x",
            }
        ),
        {},
    )
    hybrid = apply_processing_mode(overridden, "hybrid")
    assert (hybrid.vlm_model_extract, hybrid.vlm_model_extract_fallback) == ("local-x", "cloud-x")

    local = apply_processing_mode(overridden, "local")
    assert (local.vlm_model_extract, local.vlm_model_extract_fallback) == ("local-x", None)

    cloud = apply_processing_mode(overridden, "cloud")
    assert (cloud.vlm_model_extract, cloud.vlm_model_extract_fallback) == ("cloud-x", None)


# --------------------------------------------------------------------------- #
# The routes
# --------------------------------------------------------------------------- #


def test_an_admin_changes_a_model_through_the_route(admin_client):
    write = admin_client.patch(
        "/settings", json={"overrides": {"vlm_model_extract": "granite3.2-vision:9b"}}
    )
    assert write.status_code == 200
    row = next(r for r in write.json()["settings"] if r["field"] == "vlm_model_extract")
    assert row["value"] == "granite3.2-vision:9b"
    assert row["source"] == "override"
    assert row["kind"] == "model"
    assert row["group"] == "Models (advanced)"


def test_a_reviewer_reads_settings_but_cannot_edit(reviewer_client):
    response = reviewer_client.get("/settings")
    assert response.status_code == 200
    body = response.json()
    assert body["editable"] is False
    assert any(row["field"] == "auto_approve_threshold" for row in body["settings"])


def test_an_admin_reads_settings_as_editable(admin_client):
    body = admin_client.get("/settings").json()
    assert body["editable"] is True
    # Every editable field is present, and none is a secret.
    fields = {row["field"] for row in body["settings"]}
    assert fields == {item.field for item in EDITABLE}
    assert "session_secret" not in fields


def test_a_reviewer_may_not_patch_settings(reviewer_client):
    response = reviewer_client.patch(
        "/settings", json={"overrides": {"auto_approve_threshold": "0.99"}}
    )
    assert response.status_code == 403


def test_an_admin_patch_reflects_on_the_next_read_and_on_metrics(admin_client):
    write = admin_client.patch(
        "/settings", json={"overrides": {"auto_approve_threshold": "0.90"}}
    )
    assert write.status_code == 200
    row = next(r for r in write.json()["settings"] if r["field"] == "auto_approve_threshold")
    assert row["value"] == "0.90"
    assert row["source"] == "override"

    # The API surfaces the effective value live, no restart: /metrics agrees.
    metrics = admin_client.get("/metrics").json()
    assert metrics["thresholds"]["auto_approve"] == "0.90"


def test_a_bad_value_is_a_400_and_writes_nothing(admin_client):
    response = admin_client.patch(
        "/settings", json={"overrides": {"auto_approve_threshold": "2.0"}}
    )
    assert response.status_code == 400
    assert "at most 1" in response.json()["error"]["message"]
    # Nothing was written: the read still shows the default.
    row = next(
        r for r in admin_client.get("/settings").json()["settings"]
        if r["field"] == "auto_approve_threshold"
    )
    assert row["source"] == "default"


def test_a_patch_is_atomic_when_one_field_is_bad(admin_client):
    """A good field and a bad field in one patch: the good one must not persist,
    because the whole patch is one transaction that only commits if all validate."""
    response = admin_client.patch(
        "/settings",
        json={
            "overrides": {
                "expected_buyer_name": "Acme Inc",  # valid
                "auto_approve_threshold": "2.0",  # invalid
            }
        },
    )
    assert response.status_code == 400
    rows = {r["field"]: r for r in admin_client.get("/settings").json()["settings"]}
    # The valid field did NOT stick -- the bad one rolled the whole thing back.
    assert rows["expected_buyer_name"]["source"] == "default"


def test_clearing_via_the_route_reverts_to_default(admin_client):
    admin_client.patch("/settings", json={"overrides": {"expected_buyer_name": "Acme Inc"}})
    admin_client.patch("/settings", json={"overrides": {"expected_buyer_name": None}})
    rows = {r["field"]: r for r in admin_client.get("/settings").json()["settings"]}
    assert rows["expected_buyer_name"]["source"] == "default"
    assert rows["expected_buyer_name"]["value"] is None


def test_reading_settings_requires_a_session(app):
    assert TestClient(app).get("/settings").status_code == 401
