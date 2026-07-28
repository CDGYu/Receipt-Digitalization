"""Turn a :class:`Settings` into a live :class:`VLMClient`.

This is the single place that maps a provider id to a concrete client and
decides where its API key and model come from. The vendor SDKs (``anthropic``,
``openai``) are optional extras, so their clients are imported *and* constructed
lazily inside the matching branch — importing this module never drags a SDK into
the process. The client constructors themselves raise ``RuntimeError`` when the
SDK is absent; we raise an equally clear ``RuntimeError`` when configuration is
missing the key or model needed to build a working client, and ``ValueError``
for a provider id we do not recognise.
"""

from __future__ import annotations

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

# Providers whose servers cannot be assumed to accept a tool-use request, so
# they default to JSON mode. Ollama rejects `tools` with a hard 400 for any
# model that does not declare the capability -- most vision models, including
# moondream and granite3.2-vision -- and that 400 kills the very first (triage)
# call. vLLM, by contrast, supports tool-calling across its served models, so
# only Ollama is listed. VLM_USE_TOOLS overrides this either way, which is what
# a VLM_PROVIDER=openai id pointed at a local Ollama needs.
_TOOLS_OFF_BY_DEFAULT: frozenset[str] = frozenset({"ollama"})


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

        return AnthropicVLMClient(model_id=model, api_key=key)

    if provider in _OPENAI_BASE_URLS:
        key = _require(settings.vlm_api_key, provider, "VLM_API_KEY")
        model = _require(settings.vlm_model_extract, provider, "VLM_MODEL_EXTRACT")
        from .openai_compat import OpenAICompatClient  # lazy: optional SDK

        # An explicitly configured base URL wins; otherwise fall back to the
        # provider's default endpoint.
        base_url = settings.vlm_base_url or _OPENAI_BASE_URLS[provider]
        # Same precedence for tool use: an explicit VLM_USE_TOOLS wins, else the
        # provider id decides.
        use_tools = (
            settings.vlm_use_tools
            if settings.vlm_use_tools is not None
            else provider not in _TOOLS_OFF_BY_DEFAULT
        )
        return OpenAICompatClient(
            model_id=model,
            base_url=base_url,
            api_key=key,
            use_tools=use_tools,
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
