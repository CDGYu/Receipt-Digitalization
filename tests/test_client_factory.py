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
from receipts.extract.clients.factory import make_client
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
