"""What a receipt is doing right now, as a value.

This module is deliberately pure: no Redis, no pipeline import, no I/O. It
exists so :func:`receipts.pipeline.process_receipt` can *describe* progress
without depending on a queue -- ``redis`` is an optional extra and the whole
test suite runs offline.

The transport lives in :mod:`receipts.worker`; the reader lives behind
``app.state.read_progress``. Neither is imported here.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

__all__ = ["ProgressEvent", "decode", "encode", "progress_key"]

#: Prefix for every progress key, so a shared Redis cannot collide with the
#: queue's own keys.
_KEY_PREFIX = "receipt-progress:"


@dataclass(frozen=True)
class ProgressEvent:
    """One thing worth telling a waiting screen.

    ``stage`` is a member of :data:`receipts.pipeline.STAGES` -- operational
    vocabulary that also lands in ``review_tasks.reason``, so it is reported
    rather than invented. ``detail`` is optional commentary, and ``None``
    means there is none: an empty string would render a blank line where
    nothing belongs.
    """

    stage: str
    detail: str | None = None


def encode(event: ProgressEvent) -> str:
    """``event`` as a JSON object, for whatever transport carries it."""
    return json.dumps({"stage": event.stage, "detail": event.detail})


def decode(text: str) -> ProgressEvent:
    """Read what :func:`encode` wrote.

    Raises ``ValueError`` for anything else. It never returns a default:
    a reader that swallowed a bad record would show a stale stage forever,
    which is the exact failure this design is built against.
    """
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not a progress record: {text!r}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"not a progress record: {text!r}")
    stage = raw.get("stage")
    if not isinstance(stage, str):
        raise ValueError(f"progress record has no stage: {text!r}")
    detail = raw.get("detail")
    if detail is not None and not isinstance(detail, str):
        raise ValueError(f"progress detail is not text: {text!r}")
    return ProgressEvent(stage=stage, detail=detail)


def progress_key(receipt_id: uuid.UUID) -> str:
    """Where one receipt's progress lives."""
    return f"{_KEY_PREFIX}{receipt_id}"
