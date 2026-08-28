"""Turn a :class:`Settings` into a live :class:`VLMClient`.

This is the single place that maps a provider id to a concrete client and
decides where its API key and model come from. The vendor SDKs (``anthropic``,
``openai``) are optional extras, so their clients are imported *and* constructed
lazily inside the matching branch — importing this module never drags a SDK into
the process. The client constructors themselves raise ``RuntimeError`` when the
SDK is absent; we raise an equally clear ``RuntimeError`` when configuration is
missing the key or model needed to build a working client, and ``ValueError``
for a provider id we do not recognise.

Every setting a client can honour has to be forwarded here explicitly. Both
client constructors carry their own ``timeout_s`` default (180s and 120s), so a
factory that omitted ``VLM_TIMEOUT_S`` would leave the configured value
silently ignored — the same shape of gap ``VLM_BASE_URL`` once had. That is not
cosmetic: CPU inference can spend minutes on a single call, and the fallback
default aborts the very first one with a transient timeout.
"""

from __future__ import annotations

from dataclasses import dataclass

from config.settings import Settings

from .base import VLMClient
from .fake import FakeVLMClient

# VLM_BASE_URL, when set, selects the endpoint for any OpenAI-family provider;
# otherwise the provider id picks a default: a hosted OpenAI key talks to OpenAI,
# and the self-hosted ids point at their usual local ports (vLLM :8000,
# Ollama :11434).
_OPENAI_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "openai_compat": "http://localhost:8000/v1",
    "vllm": "http://localhost:8000/v1",
    "ollama": "http://localhost:11434/v1",
}

# Ollama defaults to JSON mode. vLLM, by contrast, supports tool-calling across
# its served models, so only Ollama is listed.
#
# The reason is MEASURED OUTPUT, and it is the only one that has survived.
# ADR-0002's 2026-08-18 correction and docs/KNOWN_ISSUES.md ISSUE-001: on
# `granite3.2-vision:2b` the endpoint accepts the payload and the extraction
# comes back identical either way, but triage loses `merchant_name_guess`, which
# `merchants.registry.lookup` keys off -- so enabling tool-use silently disables
# ADR-0043 decision 1's hint-retrieval path.
#
# Two earlier reasons stood here and are deleted rather than reworded, because
# both are recorded as false: that Ollama answers a `tools` payload with a hard
# 400 (it does not reproduce), and that the shim's behaviour "has not been
# measured here for any model" (it has, on two).
#
# This is the LAST step of the chain, not the whole of it. VLM_USE_TOOLS
# overrides it either way, which is what a VLM_PROVIDER=openai id pointed at a
# local Ollama needs -- and a per-rung VLM_USE_TOOLS_TRIAGE/_FALLBACK overrides
# that in turn, since `make_pass_clients` passes one. `resolve_use_tools` states
# the full precedence and is the only place that does.
_TOOLS_OFF_BY_DEFAULT: frozenset[str] = frozenset({"ollama"})


def resolve_use_tools(
    provider: str, *, explicit: bool | None, global_default: bool | None
) -> bool:
    """Whether one rung sends a ``tools`` payload.

    Precedence, and the only precedence: the rung's own explicit value, then the
    process-wide ``VLM_USE_TOOLS``, then the provider default. ``make_client``
    calls this with ``explicit=None``, which is exactly the two-level chain it
    applied inline before; one level is added in front so a per-model exception
    can be expressed -- ``granite3.2-vision:2b`` and ``gemma4:cloud`` are both
    provider ``ollama`` and want opposite answers (ADR-0002's 2026-08-18
    correction, which left the fix for this milestone).

    ``provider`` is the normalized id -- ``vlm_provider.strip().lower()`` --
    because ``_TOOLS_OFF_BY_DEFAULT`` is keyed that way.
    """
    if explicit is not None:
        return explicit
    if global_default is not None:
        return global_default
    return provider not in _TOOLS_OFF_BY_DEFAULT


def make_client(settings: Settings) -> VLMClient:
    """Build the client named by ``settings.vlm_provider``.

    ``fake`` returns a deterministic, network-free client with no scripted
    responses — the offline/dev wiring and ``isinstance`` path. Tests that need
    scripted model output construct :class:`FakeVLMClient` with an explicit
    response list directly.
    """
    provider = settings.vlm_provider.strip().lower()

    if provider == "fake":
        return FakeVLMClient([])

    if provider == "anthropic":
        key = _require(settings.vlm_api_key, provider, "VLM_API_KEY")
        model = _require(settings.vlm_model_extract, provider, "VLM_MODEL_EXTRACT")
        from .anthropic_client import AnthropicVLMClient  # lazy: optional SDK

        return AnthropicVLMClient(
            model_id=model,
            api_key=key,
            timeout_s=float(settings.vlm_timeout_s),
        )

    if provider in _OPENAI_BASE_URLS:
        key = _require(settings.vlm_api_key, provider, "VLM_API_KEY")
        model = _require(settings.vlm_model_extract, provider, "VLM_MODEL_EXTRACT")
        from .openai_compat import OpenAICompatClient  # lazy: optional SDK

        # An explicitly configured base URL wins; otherwise fall back to the
        # provider's default endpoint.
        base_url = settings.vlm_base_url or _OPENAI_BASE_URLS[provider]
        # Same precedence for tool use: an explicit VLM_USE_TOOLS wins, else the
        # provider id decides. One client is one rung with nothing per-rung to
        # say, so `explicit` is None here.
        use_tools = resolve_use_tools(
            provider, explicit=None, global_default=settings.vlm_use_tools
        )
        return OpenAICompatClient(
            model_id=model,
            base_url=base_url,
            api_key=key,
            use_tools=use_tools,
            timeout_s=float(settings.vlm_timeout_s),
            max_retries=settings.vlm_max_retries,
        )

    raise ValueError(
        f"Unknown VLM provider {settings.vlm_provider!r}. Expected one of: "
        f"fake, anthropic, {', '.join(_OPENAI_BASE_URLS)}."
    )


def _require(value: str | None, provider: str, env_var: str) -> str:
    """Return ``value`` unchanged, or raise a clear error naming the missing var.

    Both the key and the model are required to construct a hosted client, and
    the constructor signatures type ``model_id`` as ``str`` — so a ``None`` here
    is a configuration error, surfaced now with a readable message rather than
    later as an opaque SDK failure.
    """
    if not value:
        raise RuntimeError(
            f"The {provider!r} provider requires {env_var} to be set."
        )
    return value


@dataclass(frozen=True)
class PassClients:
    """One client per pass, with the extract pass carrying a rung ladder.

    **Built by the worker as well as the eval path, since 2026-08-25.** This
    docstring used to say "built **only** by the eval path", and that was the
    problem rather than the design: ``make_pass_clients`` had *no code caller
    anywhere* -- it appeared in one ``pipeline.py`` docstring and nothing else --
    while ``receipts.worker`` built a single client with ``make_client``. So
    ``VLM_MODEL_EXTRACT_FALLBACK`` was a setting an operator could set, that
    validated, and that changed nothing whatsoever for an uploaded receipt.
    ``build_deps`` now constructs the ladder here and hands both rungs to
    ``process_receipt``.

    ``extract_rungs`` is a tuple so the shape generalises, but this milestone
    builds **at most two** rungs. A third is a new decision and is not earned by
    anything measured.

    ``triage`` is the primary triage rung and ``triage_fallback`` its optional
    cloud escalation, the exact parallel of ``extract_rungs[0]`` and
    ``extract_rungs[1]``. ``triage_fallback`` is ``None`` unless
    ``VLM_MODEL_TRIAGE_FALLBACK`` names a model; when it is set, ``triage``
    becomes a probe (short ``vlm_primary_timeout_s`` deadline, ``max_retries=0``)
    so a slow local box escalates triage after that deadline instead of holding
    a receipt for the full local triage time (~10m45s measured for granite).
    Kept as two fields rather than a rung tuple so every existing reader of
    ``.triage`` -- the eval path and its tests -- is unchanged.
    """

    triage: VLMClient
    extract_rungs: tuple[VLMClient, ...]
    #: The cloud triage rung, or ``None`` for one triage rung. Defaulted so
    #: every existing construction of this object keeps working unchanged.
    triage_fallback: VLMClient | None = None


def make_extract_ladder(
    settings: Settings,
) -> tuple[VLMClient, VLMClient | None, VLMClient, VLMClient | None]:
    """All production rungs as
    ``(triage_primary, triage_fallback_or_None, extract_primary, extract_fallback_or_None)``.

    **Exists because wiring one entry point is not wiring the feature.** On
    2026-08-25 the ladder was wired into ``worker.build_deps`` and left out of
    ``cli.cmd_process`` and ``cli.cmd_reprocess``, both of which build a single
    client with :func:`make_client`. The gap was found the only way it could
    be -- by running a real receipt through ``receipts reprocess`` and reading
    ``extraction_runs`` afterwards: three ``granite3.2-vision:2b`` rows, a
    1154s extract against a 300s deadline, a repair round a probe rung is not
    given, and no ``gemma4:cloud`` row at all. Every one of those is what "the
    ladder was not on this path" looks like.

    **Both passes are ladders now, and both are returned here.** Triage escalates
    on the same ``VLM_PRIMARY_TIMEOUT_S`` deadline as extract: its primary is a
    probe (short deadline, ``max_retries=0``) built from ``VLM_MODEL_TRIAGE``,
    and its fallback is ``VLM_MODEL_TRIAGE_FALLBACK`` when set. Without a triage
    fallback the triage primary keeps the full ``VLM_TIMEOUT_S`` and no probe
    deadline -- the behaviour that fixed the earlier bug where triage rode the
    *extract* probe and timed every receipt out at ~300s
    (``triage: VLMTransientError: connection: Request timed out``). Returning all
    four rungs here keeps **one** construction site for the whole thing rather
    than letting ``worker`` and ``cli`` reach past this wrapper to the raw
    builder.

    So the escalation now has **one** construction site that every runner
    shares, rather than a correct one and two that quietly do not escalate.
    """
    pass_clients = make_pass_clients(settings)
    extract = pass_clients.extract_rungs
    return (
        pass_clients.triage,
        pass_clients.triage_fallback,
        extract[0],
        (extract[1] if len(extract) > 1 else None),
    )


def _client_for(
    settings: Settings,
    *,
    model: str | None,
    use_tools: bool,
    #: Override the rung's deadline. ``None`` keeps ``settings.vlm_timeout_s``.
    timeout_s: int | None = None,
    #: Override the rung's SDK retries. ``None`` keeps ``settings.vlm_max_retries``.
    max_retries: int | None = None,
) -> VLMClient:
    """One rung, built through ``make_client`` rather than beside it.

    Reusing the factory means the provider dispatch, the lazy SDK imports and
    the missing-configuration errors have exactly one implementation. Only the
    model and the tools flag differ between rungs — on Ollama both rungs share
    the endpoint, because the local daemon proxies ``:cloud`` models.

    The rung's tools answer is already resolved by the caller, so it arrives
    here as a plain ``bool``. ``make_client`` re-runs the chain over it with
    ``explicit=None``, and a non-``None`` ``global_default`` short-circuits the
    provider default — so the value set here is the value the client gets.
    """
    update: dict[str, object] = {"vlm_model_extract": model, "vlm_use_tools": use_tools}
    # Only override what the caller actually named. Writing the current value
    # back would look identical here and stop a future default from reaching
    # this path.
    if timeout_s is not None:
        update["vlm_timeout_s"] = timeout_s
    if max_retries is not None:
        update["vlm_max_retries"] = max_retries
    return make_client(settings.model_copy(update=update))


def make_pass_clients(settings: Settings) -> PassClients:
    """Build the per-pass clients for an eval run.

    With no new settings configured this returns one triage client and one
    extract rung, both equivalent to ``make_client(settings)``: the fallback
    rung exists only when ``VLM_MODEL_EXTRACT_FALLBACK`` names a model, and the
    triage rung falls back to ``VLM_MODEL_EXTRACT`` when ``VLM_MODEL_TRIAGE``
    is unset.
    """
    provider = settings.vlm_provider.strip().lower()

    # **The triage pass is now a ladder, exactly like extract.** The primary is
    # the local triage model (falling back to the extract model when
    # VLM_MODEL_TRIAGE is unset); the fallback is VLM_MODEL_TRIAGE_FALLBACK when
    # set. The probe/deadline reasoning below is identical for both passes, so
    # it lives in `_build_ladder` and is applied to each.
    #
    # Triage's own tool-use flag stays `vlm_use_tools_triage` for the primary
    # (granite loses `merchant_name_guess` with tools on -- ISSUE-001) and
    # `vlm_use_tools_fallback` for the cloud triage rung, the same two flags the
    # extract ladder reads for its two rungs.
    triage_rungs = _build_ladder(
        settings,
        provider,
        primary_model=settings.vlm_model_triage or settings.vlm_model_extract,
        primary_use_tools=resolve_use_tools(
            provider,
            explicit=settings.vlm_use_tools_triage,
            global_default=settings.vlm_use_tools,
        ),
        fallback_model=settings.vlm_model_triage_fallback,
    )

    extract_rungs = _build_ladder(
        settings,
        provider,
        primary_model=settings.vlm_model_extract,
        primary_use_tools=resolve_use_tools(
            provider, explicit=None, global_default=settings.vlm_use_tools
        ),
        fallback_model=settings.vlm_model_extract_fallback,
    )

    return PassClients(
        triage=triage_rungs[0],
        triage_fallback=triage_rungs[1] if len(triage_rungs) > 1 else None,
        extract_rungs=extract_rungs,
    )


def _build_ladder(
    settings: Settings,
    provider: str,
    *,
    primary_model: str | None,
    primary_use_tools: bool,
    fallback_model: str | None,
) -> tuple[VLMClient, ...]:
    """A pass's rungs as ``(primary,)`` or ``(primary, fallback)``.

    Shared by the triage and extract passes because their escalation shape is
    identical: a probe primary that gives up at ``vlm_primary_timeout_s`` when a
    fallback exists, then the cloud fallback.

    **The primary's deadline is conditional on there being a second rung.**
    `vlm_primary_timeout_s` turns the primary into a probe that gives up at a
    known time so the ladder can escalate (owner ruling 2026-08-25: five minutes
    on local, then cloud). With no fallback configured there is nowhere to
    escalate to, and cutting the only attempt short would convert a slow success
    into a hard failure -- so the deadline is simply not applied.
    """
    escalates = bool(fallback_model)
    probe_timeout = settings.vlm_primary_timeout_s if escalates else None
    rungs = [
        _client_for(
            settings,
            model=primary_model,
            use_tools=primary_use_tools,
            timeout_s=probe_timeout,
            # Retries would multiply the deadline by three and make a "five
            # minute" escalation fire at fifteen. Only when a deadline is
            # actually in force -- otherwise this rung keeps the SDK's own
            # resilience, which is what it has today.
            max_retries=0 if probe_timeout is not None else None,
        )
    ]
    if fallback_model:
        rungs.append(
            _client_for(
                settings,
                model=fallback_model,
                use_tools=resolve_use_tools(
                    provider,
                    explicit=settings.vlm_use_tools_fallback,
                    global_default=settings.vlm_use_tools,
                ),
            )
        )
    return tuple(rungs)
