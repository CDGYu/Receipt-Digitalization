"""Runtime configuration, loaded from the environment (spec §17).

No secrets in code and none in ``rules.yaml`` — every knob that varies between a
laptop, CI, and production arrives as an environment variable. Field names are
the lowercase form of the documented UPPER_CASE variable; matching is
case-insensitive, so ``VLM_PROVIDER`` and ``vlm_provider`` both bind here.

Money magnitudes (the confidence thresholds and the plausibility ceiling) are
``Decimal``. That is deliberate and load-bearing: a ``float`` threshold would
reintroduce the exact rounding drift the validator exists to catch. The
sampling temperature, by contrast, is a genuine float — it is a model knob, not
an amount of money.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Model provider (§17: Model) ------------------------------------- #
    vlm_provider: str = "fake"
    vlm_api_key: str | None = None
    # Maps VLM_BASE_URL; overrides the provider default for OpenAI-compatible endpoints.
    vlm_base_url: str | None = None
    vlm_model_extract: str | None = None
    vlm_model_triage: str | None = None
    vlm_max_tokens: int = 4096
    vlm_timeout_s: int = 120

    # --- Pipeline (§17: Pipeline) ---------------------------------------- #
    max_repair_attempts: int = 1
    consistency_runs: int = 3
    consistency_temperature: float = 0.3
    auto_approve_threshold: Decimal = Decimal("0.85")
    review_threshold: Decimal = Decimal("0.60")

    # --- Images (§17: Images) -------------------------------------------- #
    max_image_edge_px: int = 2048
    max_upload_mb: int = 25
    tall_receipt_aspect: float = 3.0
    strip_overlap_px: int = 120

    # --- Plausibility (§17: Plausibility) -------------------------------- #
    max_plausible_total: Decimal = Decimal("1000000")
    max_receipt_age_years: int = 10
    default_currency: str | None = None

    # --- Infra (§17: Infra) ---------------------------------------------- #
    database_url: str | None = None
    redis_url: str | None = None
    storage_backend: str = "local"
    s3_bucket: str | None = None


def get_settings() -> Settings:
    """Construct settings from the current environment.

    Kept as a function (not a module-level singleton) so tests can build
    isolated instances and so a long-running process can re-read after an
    environment change without import-time surprises.
    """
    return Settings()
