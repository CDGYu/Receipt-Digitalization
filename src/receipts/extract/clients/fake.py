"""Deterministic client for tests and offline development.

Keep this in the package rather than in tests/ — being able to run the whole
pipeline end to end with zero API spend is what makes the validation and
routing layers cheap to iterate on.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Callable, TypeVar

from pydantic import BaseModel

from .base import ImagePart, VLMClient, VLMResponse

T = TypeVar("T", bound=BaseModel)


class FakeVLMClient(VLMClient):
    """Replays scripted responses in order.

    Each entry is either a model instance (returned as `parsed`), a string
    (treated as a parse_error), or a callable taking the call index.
    """

    def __init__(self, responses: list, model_id: str = "fake-vlm") -> None:
        self.responses = list(responses)
        self.model_id = model_id
        self.calls: list[dict] = []

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
        tool_description: str = "",
    ) -> VLMResponse:
        index = len(self.calls)
        self.calls.append(
            {
                "system": system,
                "user": user,
                "images": len(images),
                "schema": schema.__name__,
                "temperature": temperature,
            }
        )

        if index >= len(self.responses):
            raise AssertionError(
                f"FakeVLMClient exhausted: call {index + 1} but only "
                f"{len(self.responses)} response(s) scripted."
            )

        item = self.responses[index]
        if isinstance(item, Callable) and not isinstance(item, type):
            item = item(index)

        response = VLMResponse(
            parsed=None,
            raw={"scripted": index},
            model_id=self.model_id,
            input_tokens=1500,
            output_tokens=400,
            latency_ms=10,
            cost_usd=Decimal("0.01"),
        )
        if isinstance(item, str):
            response.parse_error = item
        else:
            response.parsed = item
        return response
