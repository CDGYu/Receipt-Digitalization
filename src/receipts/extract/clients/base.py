"""Provider abstraction.

Nothing outside `clients/` may import a vendor SDK. The pipeline talks to
`VLMClient` only, which is what makes swapping a hosted frontier model for a
self-hosted Qwen a config change rather than a rewrite.

Implementations live alongside this file:
  anthropic_client.py  - hosted, tool-use structured output
  openai_compat.py     - vLLM / Ollama / any OpenAI-compatible endpoint
  fake.py              - deterministic, for tests and offline development
"""

from __future__ import annotations

import logging
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, TypeVar

from pydantic import BaseModel

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class VLMError(Exception):
    """Base for all client errors."""


class VLMTransientError(VLMError):
    """Rate limit, timeout, 5xx — worth retrying."""


class VLMPermanentError(VLMError):
    """Bad request, auth failure, content refusal — retrying will not help."""


# --------------------------------------------------------------------------- #
# Data carriers
# --------------------------------------------------------------------------- #


@dataclass
class ImagePart:
    """One image in a message. `label` is emitted as a text block just before
    the image so a multi-image prompt is unambiguous to the model."""

    b64: str
    media_type: str = "image/jpeg"
    label: str | None = None


@dataclass
class VLMResponse:
    """Everything worth logging about one model call.

    `parsed` is None when the call succeeded but the output could not be
    coerced; `parse_error` then carries the reason, which feeds rule R001 and
    the repair prompt.
    """

    parsed: BaseModel | None
    raw: Any
    model_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    cost_usd: Decimal = Decimal(0)
    parse_error: str | None = None
    attempt: int = 1

    @property
    def ok(self) -> bool:
        return self.parsed is not None


@dataclass
class PricePer1M:
    """USD per million tokens. Keep this in config, not code — prices move."""

    input: Decimal
    output: Decimal

    def cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        million = Decimal(1_000_000)
        return (
            self.input * Decimal(input_tokens) / million
            + self.output * Decimal(output_tokens) / million
        )


# --------------------------------------------------------------------------- #
# Protocol
# --------------------------------------------------------------------------- #


class VLMClient(ABC):
    """One method. Deliberately narrow — a wide client interface leaks provider
    concepts into the pipeline."""

    model_id: str

    @abstractmethod
    def complete_json(
        self,
        *,
        system: str,
        user: str,
        images: list[ImagePart],
        schema: type[T],
        temperature: float = 0.0,
        max_tokens: int = 4096,
        tool_name: str = "record_extraction",
        tool_description: str = "Record the structured data read from the document.",
    ) -> VLMResponse:
        """Return a VLMResponse whose `parsed` is an instance of `schema`.

        Implementations MUST:
          - never raise on a malformed model response; set parse_error instead
          - raise VLMTransientError / VLMPermanentError for transport failures
          - populate token counts and cost
        """
        ...


# --------------------------------------------------------------------------- #
# Retry
# --------------------------------------------------------------------------- #


@dataclass
class RetryPolicy:
    max_attempts: int = 4
    base_delay_s: float = 1.0
    max_delay_s: float = 30.0
    jitter: bool = True

    def delay_for(self, attempt: int) -> float:
        raw = min(self.base_delay_s * (2 ** (attempt - 1)), self.max_delay_s)
        return raw * (0.5 + random.random() / 2) if self.jitter else raw


def with_retry(fn: Callable[[], VLMResponse], policy: RetryPolicy | None = None,
               sleep: Callable[[float], None] = time.sleep) -> VLMResponse:
    """Retry transient failures only.

    Note what is NOT retried: a response that came back fine but failed to
    parse. That is not a transport problem, and hammering the same prompt
    rarely fixes it — the repair pass is the right tool. Retrying here just
    burns money.
    """
    policy = policy or RetryPolicy()
    last: Exception | None = None

    for attempt in range(1, policy.max_attempts + 1):
        try:
            response = fn()
            response.attempt = attempt
            return response
        except VLMTransientError as exc:
            last = exc
            if attempt == policy.max_attempts:
                break
            delay = policy.delay_for(attempt)
            log.warning("Transient VLM error (attempt %d/%d), retrying in %.1fs: %s",
                        attempt, policy.max_attempts, delay, exc)
            sleep(delay)
        except VLMPermanentError:
            raise

    raise VLMTransientError(f"Exhausted {policy.max_attempts} attempts: {last}")


# --------------------------------------------------------------------------- #
# Response cache
# --------------------------------------------------------------------------- #


@dataclass
class ResponseCache:
    """Keyed on (image hash, prompt hash, model, temperature).

    Not a production optimisation — a development one. Iterating on validation
    rules against a 50-receipt golden set costs 50 API calls per run without
    this, and zero with it. Only cache temperature==0 calls; caching sampled
    calls would defeat the self-consistency mechanism.
    """

    store: dict[str, VLMResponse] = field(default_factory=dict)
    enabled: bool = True

    @staticmethod
    def key(image_hash: str, prompt_hash: str, model_id: str, temperature: float) -> str:
        return f"{model_id}:{temperature}:{prompt_hash}:{image_hash}"

    def get(self, key: str) -> VLMResponse | None:
        return self.store.get(key) if self.enabled else None

    def put(self, key: str, response: VLMResponse, temperature: float) -> None:
        if self.enabled and temperature == 0.0 and response.ok:
            self.store[key] = response
