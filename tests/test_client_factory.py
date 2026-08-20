"""The factory turns a `Settings` into a live `VLMClient`.

The `fake` path is network-free. The `openai` family constructs a real
`OpenAICompatClient` — the `openai` SDK is installed and its constructor makes
no network call, so we can assert the endpoint the client was wired to. The
`anthropic` SDK is not installed, so that path must fail loudly with a clear
RuntimeError and never import its SDK at module load.
"""

from __future__ import annotations

import pytest

from config.settings import Settings
from receipts.extract.clients.factory import make_client, resolve_use_tools
from receipts.extract.clients.fake import FakeVLMClient
from receipts.extract.clients.openai_compat import OpenAICompatClient


def test_fake_provider_builds_fake_client():
    client = make_client(Settings(vlm_provider="fake"))
    assert isinstance(client, FakeVLMClient)


def test_anthropic_without_key_raises_runtime_error():
    # Missing key OR missing `anthropic` package — either surfaces as RuntimeError.
    with pytest.raises(RuntimeError):
        make_client(Settings(vlm_provider="anthropic", vlm_api_key=None))


def test_unknown_provider_raises_value_error():
    with pytest.raises(ValueError):
        make_client(Settings(vlm_provider="nope"))


def test_openai_provider_honors_configured_base_url(monkeypatch):
    # An explicitly configured VLM_BASE_URL must win over the provider default,
    # so a user pointing at a local OpenAI-compatible server is not silently
    # redirected to api.openai.com.
    monkeypatch.delenv("VLM_BASE_URL", raising=False)
    client = make_client(
        Settings(
            _env_file=None,
            vlm_provider="openai",
            vlm_api_key="k",
            vlm_model_extract="m",
            vlm_base_url="http://localhost:11435/v1",
        )
    )
    assert isinstance(client, OpenAICompatClient)
    # base_url is propagated to the openai SDK client; the SDK appends a
    # trailing slash, so compare on the stripped form.
    assert str(client._client.base_url).rstrip("/") == "http://localhost:11435/v1"


def test_openai_provider_falls_back_to_default_base_url(monkeypatch):
    # Without VLM_BASE_URL, the provider id selects the default endpoint.
    monkeypatch.delenv("VLM_BASE_URL", raising=False)
    client = make_client(
        Settings(
            _env_file=None,
            vlm_provider="openai",
            vlm_api_key="k",
            vlm_model_extract="m",
        )
    )
    assert isinstance(client, OpenAICompatClient)
    assert str(client._client.base_url).rstrip("/") == "https://api.openai.com/v1"


def _client(**overrides) -> OpenAICompatClient:
    """An OpenAI-family client built from an isolated Settings."""
    kwargs = {
        "_env_file": None,
        "vlm_api_key": "k",
        "vlm_model_extract": "m",
        **overrides,
    }
    client = make_client(Settings(**kwargs))
    assert isinstance(client, OpenAICompatClient)
    return client


def test_ollama_provider_disables_tools_by_default():
    # Ollama answers a `tools` payload with a hard 400 for any model that does
    # not declare the capability, which kills the first call of the pipeline.
    assert _client(vlm_provider="ollama").use_tools is False


def test_hosted_openai_provider_keeps_tools_by_default():
    # The default must stay on everywhere else -- tool use is the reliable path
    # for structured output, and only Ollama is known to reject it.
    assert _client(vlm_provider="openai").use_tools is True
    assert _client(vlm_provider="vllm").use_tools is True


def test_explicit_use_tools_overrides_provider_default():
    # The escape hatch for a provider id that does not identify the server:
    # VLM_PROVIDER=openai pointed at a local Ollama via VLM_BASE_URL.
    assert _client(vlm_provider="openai", vlm_use_tools=False).use_tools is False
    assert _client(vlm_provider="ollama", vlm_use_tools=True).use_tools is True


# --------------------------------------------------------------------------- #
# resolve_use_tools: the one precedence chain, stated once
# --------------------------------------------------------------------------- #


def test_an_explicit_per_rung_value_wins_over_everything() -> None:
    assert resolve_use_tools("ollama", explicit=True, global_default=False) is True
    assert resolve_use_tools("vllm", explicit=False, global_default=True) is False


def test_the_global_default_wins_when_the_rung_says_nothing() -> None:
    assert resolve_use_tools("ollama", explicit=None, global_default=True) is True
    assert resolve_use_tools("vllm", explicit=None, global_default=False) is False


def test_the_provider_decides_when_nothing_is_configured() -> None:
    # Ollama is the one provider whose servers cannot be assumed to accept a
    # tools payload, so it alone defaults off.
    assert resolve_use_tools("ollama", explicit=None, global_default=None) is False
    assert resolve_use_tools("vllm", explicit=None, global_default=None) is True


# --------------------------------------------------------------------------- #
# VLM_TIMEOUT_S propagation
# --------------------------------------------------------------------------- #


def test_openai_provider_honors_configured_timeout():
    # A CPU-bound local vision model can take minutes for a single call. If the
    # factory drops VLM_TIMEOUT_S the client silently falls back to its own
    # 180s default and the very first call dies with a transient timeout.
    client = _client(vlm_provider="ollama", vlm_timeout_s=900)
    # timeout is propagated to the openai SDK client, same shape as base_url.
    assert float(client._client.timeout) == 900.0


def test_openai_provider_propagates_default_timeout():
    # The configured value must reach the client even when it is the Settings
    # default -- otherwise the SDK's own (longer) default masks the config.
    client = _client(vlm_provider="openai")
    assert float(client._client.timeout) == float(Settings(_env_file=None).vlm_timeout_s)


def test_anthropic_provider_honors_configured_timeout(monkeypatch):
    # The `anthropic` SDK is not installed, so a real client cannot be built.
    # `make_client` resolves AnthropicVLMClient through a lazy
    # `from .anthropic_client import ...` at call time, so patching the module
    # attribute captures exactly the kwargs the factory passes.
    from receipts.extract.clients import anthropic_client

    captured: dict[str, object] = {}

    class _Recorder:
        def __init__(self, model_id: str, **kwargs: object) -> None:
            captured["model_id"] = model_id
            captured.update(kwargs)

    monkeypatch.setattr(anthropic_client, "AnthropicVLMClient", _Recorder)
    make_client(
        Settings(
            _env_file=None,
            vlm_provider="anthropic",
            vlm_api_key="k",
            vlm_model_extract="m",
            vlm_timeout_s=900,
        )
    )
    assert captured["timeout_s"] == 900.0
