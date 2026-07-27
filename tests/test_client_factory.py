"""The factory turns a `Settings` into a live `VLMClient`.

Only the offline `fake` path constructs successfully here: the real SDKs are
optional extras and are not installed in the test environment, so the hosted
paths must fail loudly (a clear RuntimeError), never import at module load.
"""

from __future__ import annotations

import pytest

from config.settings import Settings
from receipts.extract.clients.factory import make_client
from receipts.extract.clients.fake import FakeVLMClient


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
