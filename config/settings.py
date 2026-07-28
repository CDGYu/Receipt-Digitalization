"""Runtime configuration, loaded from the environment (spec §17).

No secrets in code and none in ``rules.yaml`` — every knob that varies between a
laptop, CI, and production arrives as an environment variable. Field names are
the lowercase form of the documented UPPER_CASE variable; matching is
case-insensitive, so ``VLM_PROVIDER`` and ``vlm_provider`` both bind here.

Money magnitudes (the confidence thresholds, the plausibility ceiling, and the
per-run spend ceiling) are ``Decimal``. That is deliberate and load-bearing: a
``float`` threshold would reintroduce the exact rounding drift the validator
exists to catch. The sampling temperature, by contrast, is a genuine float — it
is a model knob, not an amount of money.

Three knobs go beyond the §17 list, all added with the worker (P4.T4) and all
documented at their field below: ``VLM_MAX_CONCURRENCY`` and
``MAX_COST_USD_PER_RECEIPT`` are the review-mandated guards on model calls, and
``STORAGE_ROOT`` is what a worker rebuilding a local storage backend from the
environment needs. Every one has a working default, so nothing new is required
to start the system.
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
    # Maps VLM_USE_TOOLS. Whether an OpenAI-compatible endpoint gets a tool-use
    # request or plain JSON mode. ``None`` means "decide from the provider id",
    # which is what :func:`~receipts.extract.clients.factory.make_client` does;
    # set it explicitly when the provider id does not identify the server, e.g.
    # VLM_PROVIDER=openai pointed at a local Ollama via VLM_BASE_URL. Servers
    # that reject a ``tools`` payload outright need this false.
    vlm_use_tools: bool | None = None
    # Maps VLM_MAX_CONCURRENCY. The ceiling on model calls in flight at once
    # *for this process*, shared by every receipt it is working — not a cap per
    # receipt, which would be no cap at all once a batch or a worker pool is
    # draining a backlog. Enforced by
    # :class:`~receipts.extract.clients.limits.VLMGate`, which
    # :func:`~receipts.extract.clients.limits.get_vlm_gate` builds once per
    # process. ``0`` means unlimited. Four keeps a single worker comfortably
    # inside a typical hosted rate limit while still overlapping latency; a
    # fleet-wide bound is this value times the worker count (a cap *across*
    # processes needs a Redis lease and is deliberately not attempted here).
    vlm_max_concurrency: int = 4

    # --- Pipeline (§17: Pipeline) ---------------------------------------- #
    max_repair_attempts: int = 1
    consistency_runs: int = 3
    consistency_temperature: float = 0.3
    auto_approve_threshold: Decimal = Decimal("0.85")
    review_threshold: Decimal = Decimal("0.60")
    # Maps MAX_COST_USD_PER_RECEIPT. The spend ceiling for one `process_receipt`
    # run, accumulated from ``VLMResponse.cost_usd`` by
    # :class:`~receipts.extract.clients.limits.CostGuard`. Once it is reached the
    # run stops cleanly and the receipt lands in review rather than continuing to
    # spend — a pathological image that fails to parse can otherwise burn a
    # repair round per attempt forever. ``Decimal``, never ``float`` (ADR-0001).
    # ``0`` disables the ceiling. The default is deliberately generous: a triage
    # call plus an extract plus a repair on a frontier model is cents, so 0.25
    # only ever fires on something genuinely pathological.
    max_cost_usd_per_receipt: Decimal = Decimal("0.25")

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
    # Maps STORAGE_ROOT. Where ``STORAGE_BACKEND=local`` puts blobs. Only the
    # worker needs it (it has to rebuild a storage backend from the environment
    # with nothing injected); every other caller passes a backend in.
    storage_root: str = "var/blobs"


def get_settings() -> Settings:
    """Construct settings from the current environment.

    Kept as a function (not a module-level singleton) so tests can build
    isolated instances and so a long-running process can re-read after an
    environment change without import-time surprises.
    """
    return Settings()
