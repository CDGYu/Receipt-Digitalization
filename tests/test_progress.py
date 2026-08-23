"""The progress vocabulary: a value, a wire form, and a key.

Pure by design -- this module is what lets the pipeline describe progress
without importing `redis`, which the offline suite could not tolerate.
"""

from __future__ import annotations

import uuid

import pytest

from receipts.progress import ProgressEvent, decode, encode, progress_key


def test_an_event_round_trips_through_the_wire_form() -> None:
    event = ProgressEvent(stage="extract", detail="attempt 2: 1 error")
    assert decode(encode(event)) == event


def test_an_event_with_no_detail_round_trips_as_none_not_as_empty() -> None:
    # `null` is not `""`. A detail-less event means "no commentary", and a
    # reader that turned it into an empty string would render a blank line
    # where there should be nothing at all.
    assert decode(encode(ProgressEvent(stage="triage"))).detail is None


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "not json",
        "[]",
        '{"detail": "no stage"}',
        '{"stage": 4}',
        # The only one of these that reaches the `detail` guard -- every other
        # input is already rejected by the JSON parse, the non-dict check or
        # the stage check. Without this case that guard is deletable with the
        # whole file green, which is to say it is not a pin at all.
        '{"stage": "extract", "detail": 4}',
    ],
)
def test_text_that_is_not_an_event_raises_rather_than_returning_a_default(bad: str) -> None:
    # Silence is the failure mode this whole design is built against: a reader
    # that swallowed a bad record would show a stale stage forever.
    with pytest.raises(ValueError):
        decode(bad)


def test_the_key_is_namespaced_and_carries_the_id() -> None:
    receipt_id = uuid.UUID("11111111-2222-3333-4444-555555555555")
    key = progress_key(receipt_id)
    assert str(receipt_id) in key
    assert key.startswith("receipt-progress:")


def test_two_receipts_never_share_a_key() -> None:
    assert progress_key(uuid.uuid4()) != progress_key(uuid.uuid4())
