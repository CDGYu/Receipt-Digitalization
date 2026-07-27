"""OpenAI-compatible endpoint: vLLM, SGLang, Ollama, LM Studio, or a hosted
OpenAI-format API.

This is the self-hosting path (spec milestone M7). Serving Qwen3-VL or
dots.ocr behind vLLM gives you the same interface as the hosted client:

    vllm serve Qwen/Qwen3-VL-8B-Instruct \
        --limit-mm-per-prompt image=4 \
        --max-model-len 32768

    client = OpenAICompatClient(
        model_id="Qwen/Qwen3-VL-8B-Instruct",
        base_url="http://localhost:8000/v1",
        price=PricePer1M(input=Decimal(0), output=Decimal(0)),
    )

Caveat worth knowing before you plan around it: open-weight servers vary in how
well they honour a JSON schema. vLLM supports guided decoding, but coverage of
`anyOf` and nullable fields is patchier than a hosted provider's tool-use. Set
`use_tools=False` to fall back to JSON-mode plus the tolerant parser in
json_io, and expect a slightly higher parse-failure rate.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any, TypeVar

from pydantic import BaseModel

from ..json_io import JsonParseError, build_tool_schema, parse_model_json
from .base import (
    ImagePart,
    PricePer1M,
    VLMClient,
    VLMPermanentError,
    VLMResponse,
    VLMTransientError,
)

T = TypeVar("T", bound=BaseModel)


class OpenAICompatClient(VLMClient):
    def __init__(
        self,
        model_id: str,
        *,
        base_url: str,
        api_key: str = "not-needed",
        price: PricePer1M | None = None,
        timeout_s: float = 180.0,
        use_tools: bool = True,
    ) -> None:
        try:
            import openai  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pip install openai to use OpenAICompatClient") from exc

        self._sdk = openai
        self._client = openai.OpenAI(base_url=base_url, api_key=api_key, timeout=timeout_s)
        self.model_id = model_id
        self.use_tools = use_tools
        # Self-hosted inference is not free, but it is not per-token either.
        # Zero here keeps the accounting honest; track GPU-hours separately.
        self.price = price or PricePer1M(input=Decimal(0), output=Decimal(0))

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
        content: list[dict[str, Any]] = []
        for part in images:
            if part.label:
                content.append({"type": "text", "text": part.label})
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{part.media_type};base64,{part.b64}"},
                }
            )
        content.append({"type": "text", "text": user})

        kwargs: dict[str, Any] = {
            "model": self.model_id,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
        }

        if self.use_tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": tool_description,
                        "parameters": build_tool_schema(schema),
                    },
                }
            ]
            kwargs["tool_choice"] = {"type": "function", "function": {"name": tool_name}}
        else:
            kwargs["response_format"] = {"type": "json_object"}

        started = time.perf_counter()
        try:
            completion = self._client.chat.completions.create(**kwargs)
        except self._sdk.RateLimitError as exc:
            raise VLMTransientError(f"rate limited: {exc}") from exc
        except (self._sdk.APITimeoutError, self._sdk.APIConnectionError) as exc:
            raise VLMTransientError(f"connection: {exc}") from exc
        except self._sdk.APIStatusError as exc:
            if exc.status_code >= 500:
                raise VLMTransientError(f"server error {exc.status_code}") from exc
            raise VLMPermanentError(f"status {exc.status_code}: {exc}") from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        usage = completion.usage
        in_tok = getattr(usage, "prompt_tokens", 0) or 0
        out_tok = getattr(usage, "completion_tokens", 0) or 0

        response = VLMResponse(
            parsed=None,
            raw=completion.model_dump(),
            model_id=self.model_id,
            input_tokens=in_tok,
            output_tokens=out_tok,
            latency_ms=latency_ms,
            cost_usd=self.price.cost(in_tok, out_tok),
        )

        choice = completion.choices[0]
        if choice.finish_reason == "length":
            response.parse_error = (
                f"Response hit the {max_tokens}-token limit and was truncated."
            )
            return response

        payload: str | dict | None = None
        if choice.message.tool_calls:
            payload = choice.message.tool_calls[0].function.arguments
        elif choice.message.content:
            payload = choice.message.content

        if payload is None:
            response.parse_error = "Model returned no usable content."
            return response

        try:
            response.parsed = parse_model_json(payload, schema)
        except JsonParseError as exc:
            response.parse_error = str(exc)

        return response
