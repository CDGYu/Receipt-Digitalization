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

from receipts.score.thresholds import AUTO_APPROVE_THRESHOLD, REVIEW_THRESHOLD


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
    # Maps VLM_MODEL_EXTRACT_FALLBACK. The second extract rung. Unset means
    # there is no fallback and the ladder has exactly one rung, which is
    # today's behaviour.
    vlm_model_extract_fallback: str | None = None
    # Maps VLM_USE_TOOLS_TRIAGE. Tool use for the triage rung. Not optional
    # convenience: ISSUE-001 tells a reader to set VLM_USE_TOOLS=true for the
    # cloud tier, and that is a process-wide default -- it would turn tools on
    # for triage too, where granite is measured to lose `merchant_name_guess`
    # entirely, which is the field ADR-0043 decision 1's hint path keys off.
    vlm_use_tools_triage: bool | None = None
    # Maps VLM_USE_TOOLS_FALLBACK. Tool use for the fallback rung.
    vlm_use_tools_fallback: bool | None = None
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

    # --- Who our receipts should be addressed to (§17) -------------------- #
    # Maps EXPECTED_BUYER_NAME / EXPECTED_BUYER_TAX_ID. The operator's own
    # registered identity, compared against the receipt's Sold To block by
    # R014/R015. A per-deployment constant like DEFAULT_CURRENCY, not a tuning
    # knob, which is why it lives here and not in rules.yaml.
    #
    # BOTH UNSET MEANS BOTH RULES ARE INERT. A deployment that has not declared
    # who it is gets no findings, rather than a finding on every receipt. A
    # blank value counts as unset: ``EXPECTED_BUYER_NAME=`` in an env file is a
    # placeholder nobody filled in, not a declaration.
    #
    # ``receipts.pipeline`` is what reads these and puts them on the
    # ``ValidationContext``; the rules never import ``Settings`` themselves.
    expected_buyer_name: str | None = None
    expected_buyer_tax_id: str | None = None

    # --- Pipeline (§17: Pipeline) ---------------------------------------- #
    max_repair_attempts: int = 1
    consistency_runs: int = 3
    consistency_temperature: float = 0.3
    auto_approve_threshold: Decimal = AUTO_APPROVE_THRESHOLD
    review_threshold: Decimal = REVIEW_THRESHOLD
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

    # Maps OCR_GROUNDING_ENABLED. Runs a second, independent reader over the same
    # pixels the model was shown, and puts what it read on
    # ``ValidationContext.ocr_text`` — which is the source R060 and R061 were
    # written against and which nothing produced until 2026-08-25 (P2.T2). Both
    # rules gate on ``bool(ctx.ocr_text)``, so with this OFF they skip exactly as
    # they always have.
    #
    # **Default OFF, and it is a cost decision rather than a correctness one.**
    # The pass needs the optional ``ocr`` extra, which is not installed by
    # default, and it adds a CPU pass per receipt — measured on this box at about
    # a second per small image plus a one-off ~1.2s to build the recogniser. On
    # hardware where a single receipt already costs minutes that is cheap; the
    # default stays OFF because a flag that silently starts spending on every
    # deployment that upgrades is not a flag anyone consented to.
    ocr_grounding_enabled: bool = False

    # Self-consistency (P7.T1): extract n times at a non-zero temperature and
    # score the disagreement, for receipts triage calls handwritten. Disagreement
    # across runs is an honest uncertainty estimate; a model's self-reported
    # confidence is not -- asked directly it will tell you it is confident about
    # a handwritten 1 that is actually a 7.
    #
    # **Default OFF, and this one is the most expensive flag in the file.** It
    # costs `consistency_runs` EXTRA extract calls on every handwritten receipt,
    # and ADR-0039 measures a single extract on this box in minutes -- so `n=3`
    # is roughly a fourfold cost on exactly the receipts that are already
    # slowest. Same reasoning as `ocr_grounding_enabled` above, one order of
    # magnitude up.
    #
    # **Its acceptance has never been met.** P7.T1 asks for handwritten
    # auto-approval rate and precision recorded before and after; that needs a
    # real model run over a golden set of three handwritten receipts, and
    # ISSUE-034 -- now ruled hermetic -- means the eval path measures a
    # different prompt than production sends anyway. Nobody has measured whether
    # turning this on improves precision. Turn it on deliberately, on a box that
    # can afford it, and measure.
    consistency_enabled: bool = False

    # How many independent extractions a consistency pass makes. Three is
    # `run_consistency`'s own default and the smallest number that can produce a
    # majority; two can only ever agree or disagree.
    consistency_runs: int = 3

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

    # --- Service (§17: Service) ------------------------------------------ #
    # Maps SESSION_SECRET. Signs the review session cookie and the expiring
    # image URLs. No default: create_app refuses to start without it. A random
    # per-process fallback would log every reviewer out on each restart and hide
    # the misconfiguration instead of surfacing it.
    session_secret: str | None = None
    # Maps RECEIPTS_API_KEY. The machine-upload key, authorizing POST /upload
    # and nothing else. Unset means the header path is rejected outright --
    # never "unset key equals unset header", which is how this becomes an open
    # door.
    receipts_api_key: str | None = None
    session_cookie_secure: bool = True
    # Maps ALLOW_INSECURE_SESSION_COOKIE. The escape hatch for the boot check in
    # ``receipts.asgi``, which refuses to start when SESSION_COOKIE_SECURE is
    # false (``create_app`` itself only logs a warning -- see
    # ``install_session_middleware``). Without a hatch there would be no way to
    # run the real entry point over plain HTTP at all; with one, doing so stops
    # being a default nobody noticed and becomes a line somebody wrote down.
    # It does not weaken the cookie by itself -- SESSION_COOKIE_SECURE still
    # does that. This only decides whether the service agrees to start.
    allow_insecure_session_cookie: bool = False
    # Maps SESSION_TTL_S. How long a signed session cookie is honoured,
    # enforced server-side via SessionMiddleware(max_age=...) and
    # itsdangerous's TimestampSigner -- not a browser-side expiry a client
    # could ignore. Starlette's own default is 14 days, sized for a generic
    # web app rather than a bearer credential in front of financial records;
    # 43200 (12h, one working day) is deliberately tighter. Logout only tells
    # the presenting client to drop its cookie -- it cannot revoke one already
    # exfiltrated -- so this ceiling, plus
    # :func:`receipts.persist.users.deactivate` for an immediate cutoff, is
    # the actual exposure window.
    session_ttl_s: int = 43200
    # Maps IMAGE_URL_TTL_S / EXPORT_IMAGE_URL_TTL_S. How long a signed image
    # link stays valid: minutes for the review screen, a day for links embedded
    # in an exported workbook (anyone holding that file can open them until it
    # expires).
    image_url_ttl_s: int = 300
    export_image_url_ttl_s: int = 86400
    # Maps DOCS_ENABLED. Whether ``create_app`` publishes ``/openapi.json``,
    # ``/docs`` and ``/redoc``. FastAPI serves all three by default and none of
    # them takes a session or a key, so the default here is False: the schema
    # names every write route, every request body, and the ``X-API-Key`` header
    # in front of financial records, and a deployment that wants that browsable
    # should have to say so. Turning it on unregisters nothing else.
    docs_enabled: bool = False
    # Maps FRONTEND_DIST. Where the built review UI lives, relative to the
    # working directory. The mount is skipped entirely when this directory is
    # absent -- StaticFiles checks its directory at construction, so an
    # unguarded mount would break create_app for a base install, for CI, and
    # for every developer who has never run npm.
    frontend_dist: str = "frontend/dist"
    # Maps SERVE_SPA. Whether this deployment serves the review UI at all.
    # ``frontend/dist`` is gitignored, so a fresh checkout has no ``index.html``
    # and every deployment that wants the UI must run ``npm run build`` first.
    # Left true, ``receipts.asgi`` enforces exactly that: an unbuilt frontend is
    # a refusal to start rather than ``/app/*`` 404ing with no explanation. Set
    # false, the mount is skipped as a declared choice and an API-only
    # deployment becomes possible -- and the mount is then skipped even if a
    # stale ``dist`` happens to be present, because "do not serve the SPA" has
    # to mean it.
    serve_spa: bool = True


def get_settings() -> Settings:
    """Construct settings from the current environment.

    Kept as a function (not a module-level singleton) so tests can build
    isolated instances and so a long-running process can re-read after an
    environment change without import-time surprises.
    """
    return Settings()
