"""Settings parse the §17 environment variables into typed fields.

The money-magnitude thresholds must land as `Decimal`, never `float` — a stray
float here would reintroduce the tolerance drift the whole system guards against.
"""

from __future__ import annotations

from decimal import Decimal

from config.settings import Settings, get_settings


def test_env_vars_map_to_typed_fields(monkeypatch):
    monkeypatch.setenv("VLM_PROVIDER", "anthropic")
    monkeypatch.setenv("VLM_MAX_TOKENS", "8000")
    monkeypatch.setenv("AUTO_APPROVE_THRESHOLD", "0.9")

    settings = Settings()

    assert settings.vlm_provider == "anthropic"
    assert settings.vlm_max_tokens == 8000
    assert isinstance(settings.vlm_max_tokens, int)
    assert settings.auto_approve_threshold == Decimal("0.9")
    assert isinstance(settings.auto_approve_threshold, Decimal)


def test_case_insensitive_env_names(monkeypatch):
    # §17 documents UPPER names; the field is lowercase. Mapping is case-insensitive.
    monkeypatch.setenv("vlm_provider", "ollama")
    settings = Settings(_env_file=None)
    assert settings.vlm_provider == "ollama"


def test_defaults_when_unset(monkeypatch):
    # Hermetic: drop any ambient value and ignore a developer's local .env.
    for var in (
        "VLM_PROVIDER",
        "VLM_API_KEY",
        "VLM_MODEL_EXTRACT",
        "VLM_MAX_TOKENS",
        "AUTO_APPROVE_THRESHOLD",
    ):
        monkeypatch.delenv(var, raising=False)

    settings = Settings(_env_file=None)

    assert settings.vlm_provider == "fake"
    assert settings.vlm_api_key is None
    assert settings.vlm_max_tokens == 4096
    assert settings.consistency_runs == 3


def test_money_thresholds_are_decimal(monkeypatch):
    settings = Settings(_env_file=None)
    for value in (
        settings.auto_approve_threshold,
        settings.review_threshold,
        settings.max_plausible_total,
    ):
        assert isinstance(value, Decimal)
    # consistency_temperature is a sampling knob, not a money magnitude -> float.
    assert isinstance(settings.consistency_temperature, float)


def test_get_settings_returns_a_settings_instance():
    assert isinstance(get_settings(), Settings)


def test_vlm_base_url_maps_from_env(monkeypatch):
    # A custom/local OpenAI-compatible endpoint arrives via VLM_BASE_URL.
    monkeypatch.setenv("VLM_BASE_URL", "http://localhost:11435/v1")
    settings = Settings(_env_file=None)
    assert settings.vlm_base_url == "http://localhost:11435/v1"


def test_vlm_base_url_defaults_to_none(monkeypatch):
    # Unset -> None, so the factory falls back to the provider's default endpoint.
    monkeypatch.delenv("VLM_BASE_URL", raising=False)
    settings = Settings(_env_file=None)
    assert settings.vlm_base_url is None
