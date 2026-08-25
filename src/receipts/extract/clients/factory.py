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
    """

    triage: VLMClient
    extract_rungs: tuple[VLMClient, ...]


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

    triage = _client_for(
        settings,
        model=settings.vlm_model_triage or settings.vlm_model_extract,
        use_tools=resolve_use_tools(
            provider,
            explicit=settings.vlm_use_tools_triage,
            global_default=settings.vlm_use_tools,
        ),
    )

    # **The first rung's deadline is conditional on there being a second one.**
    # `vlm_primary_timeout_s` turns the first rung into a probe that gives up at
    # a known time so the ladder can escalate (owner ruling 2026-08-25: ten
    # minutes on local, then cloud). With no fallback configured there is
    # nowhere to escalate to, and cutting the only attempt short would convert a
    # slow success into a hard failure -- so the deadline is simply not applied.
    escalates = bool(settings.vlm_model_extract_fallback)
    probe_timeout = settings.vlm_primary_timeout_s if escalates else None
    rungs = [
        _client_for(
            settings,
            model=settings.vlm_model_extract,
            use_tools=resolve_use_tools(
                provider, explicit=None, global_default=settings.vlm_use_tools
            ),
            timeout_s=probe_timeout,
            # Retries would multiply the deadline by three and make a "ten
            # minute" escalation fire at thirty. Only when a deadline is
            # actually in force -- otherwise this rung keeps the SDK's own
            # resilience, which is what it has today.
            max_retries=0 if probe_timeout is not None else None,
        )
    ]
    if settings.vlm_model_extract_fallback:
        rungs.append(
            _client_for(
                settings,
                model=settings.vlm_model_extract_fallback,
                use_tools=resolve_use_tools(
                    provider,
                    explicit=settings.vlm_use_tools_fallback,
                    global_default=settings.vlm_use_tools,
                ),
            )
        )

    return PassClients(triage=triage, extract_rungs=tuple(rungs))
