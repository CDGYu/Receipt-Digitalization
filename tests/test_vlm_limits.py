"""Global VLM concurrency cap and per-run cost guard (P4.T4).

Two independent guards sit between the pipeline and any provider, and both are
tested here without a network, a Redis, or a real model:

  * :class:`VLMGate` -- a **process-global** semaphore. The cap is on concurrent
    model calls across every receipt the process is working, not one cap per
    receipt, so the test proves a second gate handed out by
    :func:`get_vlm_gate` is the *same* object and that the (limit + 1)-th caller
    genuinely blocks.
  * :class:`CostGuard` -- a per-run accumulator of ``VLMResponse.cost_usd``.
    Money is ``Decimal`` (ADR-0001), so a ``float`` ceiling or a ``float`` cost
    is refused outright rather than silently coerced.
"""

from __future__ import annotations

import threading
from decimal import Decimal

import pytest

from receipts.extract.clients.base import ImagePart, VLMClient, VLMResponse
from receipts.extract.clients.limits import (
    CostCeilingExceeded,
    CostGuard,
    GuardedVLMClient,
    VLMGate,
    get_vlm_gate,
    reset_vlm_gate,
)
from receipts.extract.schema import TriageResult


@pytest.fixture(autouse=True)
def _fresh_global_gate():
    """The gate is process-global by design, so tests must not inherit one."""
    reset_vlm_gate()
    yield
    reset_vlm_gate()


class _CountingClient(VLMClient):
    """Records how many calls are in flight at once, and what it charged."""

    def __init__(self, *, hold_s: float = 0.0, cost: Decimal = Decimal("0.01")) -> None:
        self.model_id = "counting-vlm"
        self.cost = cost
        self.hold_s = hold_s
        self.calls = 0
        self.in_flight = 0
        self.peak_in_flight = 0
        self._lock = threading.Lock()

    def complete_json(self, **kwargs) -> VLMResponse:
        with self._lock:
            self.calls += 1
            self.in_flight += 1
            self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
        try:
            if self.hold_s:
                threading.Event().wait(self.hold_s)
        finally:
            with self._lock:
                self.in_flight -= 1
        return VLMResponse(
            parsed=TriageResult(), raw={}, model_id=self.model_id, cost_usd=self.cost
        )


def _call(client: VLMClient) -> VLMResponse:
    return client.complete_json(
        system="s", user="u", images=[ImagePart(b64="x")], schema=TriageResult
    )


# --------------------------------------------------------------------------- #
# VLMGate
# --------------------------------------------------------------------------- #


def test_gate_blocks_beyond_the_limit_and_releases():
    gate = VLMGate(limit=2)
    gate.__enter__()
    gate.__enter__()

    entered = threading.Event()

    def third() -> None:
        with gate:
            entered.set()

    thread = threading.Thread(target=third, daemon=True)
    thread.start()
    # The third caller must wait: the cap is a real semaphore, not a counter.
    assert not entered.wait(timeout=0.3)

    gate.__exit__(None, None, None)
    assert entered.wait(timeout=5.0)
    thread.join(timeout=5.0)
    gate.__exit__(None, None, None)


def test_gate_limit_zero_means_unlimited():
    gate = VLMGate(limit=0)
    with gate, gate, gate:
        assert gate.in_flight == 3


def test_guarded_client_never_exceeds_the_cap():
    client = _CountingClient(hold_s=0.05)
    gate = VLMGate(limit=2)
    guarded = GuardedVLMClient(client, gate=gate)

    threads = [threading.Thread(target=_call, args=(guarded,)) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30.0)

    assert client.calls == 8
    assert client.peak_in_flight <= 2
    assert gate.peak_in_flight <= 2


def test_get_vlm_gate_is_global_not_per_call():
    from config.settings import Settings

    settings = Settings(_env_file=None, vlm_max_concurrency=3)
    first = get_vlm_gate(settings)
    second = get_vlm_gate(settings)

    # One cap for the whole process: two lookups hand back the same semaphore.
    assert first is second
    assert first.limit == 3


# --------------------------------------------------------------------------- #
# CostGuard
# --------------------------------------------------------------------------- #


def test_cost_guard_accumulates_decimal_and_stops_at_the_ceiling():
    guard = CostGuard(ceiling=Decimal("0.03"))

    guard.check()
    guard.add(Decimal("0.02"))
    guard.check()  # still under the ceiling
    guard.add(Decimal("0.02"))

    assert guard.spent == Decimal("0.04")
    assert isinstance(guard.spent, Decimal)
    with pytest.raises(CostCeilingExceeded):
        guard.check()


def test_cost_guard_without_a_ceiling_never_stops():
    guard = CostGuard(ceiling=None)
    for _ in range(100):
        guard.check()
        guard.add(Decimal("1.00"))
    assert guard.spent == Decimal("100.00")


def test_cost_guard_refuses_float_money():
    # ADR-0001: money is Decimal end to end. A float ceiling or a float charge
    # is a bug at the call site, not something to coerce.
    with pytest.raises(TypeError):
        CostGuard(ceiling=0.25)  # type: ignore[arg-type]
    guard = CostGuard(ceiling=Decimal("1"))
    with pytest.raises(TypeError):
        guard.add(0.01)  # type: ignore[arg-type]


def test_guarded_client_charges_the_guard_and_then_refuses():
    client = _CountingClient(cost=Decimal("0.01"))
    guard = CostGuard(ceiling=Decimal("0.015"))
    guarded = GuardedVLMClient(client, guard=guard)

    _call(guarded)
    assert guard.spent == Decimal("0.01")
    _call(guarded)  # 0.01 < 0.015, so this one is still allowed
    assert guard.spent == Decimal("0.02")

    with pytest.raises(CostCeilingExceeded):
        _call(guarded)
    # The refused call never reached the provider.
    assert client.calls == 2


def test_guarded_client_forwards_model_id_and_response():
    client = _CountingClient()
    guarded = GuardedVLMClient(client)

    assert guarded.model_id == client.model_id
    response = _call(guarded)
    assert isinstance(response.parsed, TriageResult)


def test_cost_guard_from_settings_reads_the_configured_ceiling():
    from config.settings import Settings

    settings = Settings(_env_file=None, max_cost_usd_per_receipt=Decimal("0.5"))
    guard = CostGuard.from_settings(settings)
    assert guard.ceiling == Decimal("0.5")

    # A non-positive ceiling disables the guard rather than blocking every call.
    disabled = CostGuard.from_settings(
        Settings(_env_file=None, max_cost_usd_per_receipt=Decimal("0"))
    )
    disabled.add(Decimal("999"))
    disabled.check()
