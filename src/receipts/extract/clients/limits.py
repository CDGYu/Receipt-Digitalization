"""Two guards around model calls: a global concurrency cap and a cost ceiling.

Both are review fixes for P4.T4 and both exist for the same reason -- a queue
worker draining a backlog can, unsupervised, either hammer a provider into rate
limiting the whole fleet or spend an unbounded amount of money on one pathological
receipt. Neither guard belongs inside the pipeline's sequencing logic, so they are
implemented as a :class:`VLMClient` decorator: *every* model call (triage, extract,
repair, and later self-consistency) passes through them without
:mod:`receipts.extract.extractor` knowing they exist.

:class:`VLMGate`
    A **process-global** semaphore. The cap is on concurrent calls across every
    receipt the process is working -- not one cap per receipt, which is the bug
    a per-run semaphore would quietly be. :func:`get_vlm_gate` hands out the one
    instance, built once from ``VLM_MAX_CONCURRENCY``.

    A cap *across processes* (several RQ workers on several hosts) is not
    something a semaphore can express; that needs a distributed lease in Redis and
    is deliberately left for when the fleet is more than one worker. Until then
    the fleet-wide bound is ``VLM_MAX_CONCURRENCY x worker count``, which is at
    least a number an operator can compute.

:class:`CostGuard`
    A per-run accumulator of :attr:`VLMResponse.cost_usd`. Money is ``Decimal``
    (ADR-0001), so a ``float`` ceiling or a ``float`` charge is refused rather
    than silently coerced -- that is the exact class of bug ADR-0001 exists to
    prevent. The ceiling is checked *before* each call and the charge is added
    after, because the cost of a call is not knowable until it returns: the run
    may exceed the ceiling by one call, and then stops.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, TypeVar

from pydantic import BaseModel

from .base import ImagePart, VLMClient, VLMPermanentError, VLMResponse

if TYPE_CHECKING:  # pragma: no cover - import-time typing only
    from config.settings import Settings

__all__ = [
    "CostCeilingExceeded",
    "CostGuard",
    "GuardedVLMClient",
    "VLMGate",
    "get_vlm_gate",
    "reset_vlm_gate",
]

T = TypeVar("T", bound=BaseModel)

_ZERO = Decimal("0")


class CostCeilingExceeded(VLMPermanentError):
    """The per-run spend ceiling was reached; no further call will be made.

    A subclass of :class:`VLMPermanentError` on purpose: it must never be
    retried by :func:`~receipts.extract.clients.base.with_retry`. Retrying a
    budget stop would spend exactly the money the guard exists to protect.
    """

    def __init__(self, spent: Decimal, ceiling: Decimal) -> None:
        super().__init__(
            f"cost ceiling reached: spent ${spent} of a ${ceiling} budget for this run"
        )
        self.spent = spent
        self.ceiling = ceiling


# --------------------------------------------------------------------------- #
# Concurrency
# --------------------------------------------------------------------------- #


class VLMGate:
    """A counting semaphore over in-flight model calls.

    Used as a context manager (``with gate:``). ``limit <= 0`` means unlimited,
    which is how a deployment opts out without the call sites growing a branch.
    ``in_flight`` and ``peak_in_flight`` are observability only -- they are what
    a test asserts on to prove the cap is real rather than decorative.
    """

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._semaphore = threading.BoundedSemaphore(limit) if limit > 0 else None
        self._lock = threading.Lock()
        self.in_flight = 0
        self.peak_in_flight = 0

    def __enter__(self) -> VLMGate:
        if self._semaphore is not None:
            self._semaphore.acquire()
        with self._lock:
            self.in_flight += 1
            self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        with self._lock:
            self.in_flight -= 1
        if self._semaphore is not None:
            self._semaphore.release()

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"VLMGate(limit={self.limit}, in_flight={self.in_flight})"


_GLOBAL_GATE: VLMGate | None = None
_GLOBAL_GATE_LOCK = threading.Lock()


def get_vlm_gate(settings: "Settings | None" = None) -> VLMGate:
    """The one gate for this process, created on first use.

    The cap has to be shared by every receipt in flight, so it cannot be built
    per call; it is memoised here behind a lock. ``settings`` supplies
    ``VLM_MAX_CONCURRENCY`` the first time and is ignored afterwards -- changing
    the cap at runtime means calling :func:`reset_vlm_gate` first, which is a
    test/reconfiguration affordance rather than an operational one.
    """
    global _GLOBAL_GATE
    with _GLOBAL_GATE_LOCK:
        if _GLOBAL_GATE is None:
            if settings is None:
                from config.settings import Settings as _Settings

                settings = _Settings()
            _GLOBAL_GATE = VLMGate(settings.vlm_max_concurrency)
        return _GLOBAL_GATE


def reset_vlm_gate() -> None:
    """Drop the process-global gate so the next lookup rebuilds it.

    Tests need this (a gate leaking between tests would make the cap look
    smaller or larger than configured); nothing in production should call it
    while calls are in flight.
    """
    global _GLOBAL_GATE
    with _GLOBAL_GATE_LOCK:
        _GLOBAL_GATE = None


# --------------------------------------------------------------------------- #
# Cost
# --------------------------------------------------------------------------- #


@dataclass
class CostGuard:
    """Running spend for one pipeline run, against an optional ``Decimal`` ceiling.

    ``ceiling`` of ``None`` -- or anything ``<= 0`` -- disables the guard, so a
    deployment that does not want a per-receipt budget sets the env var to ``0``
    rather than needing a separate feature flag.
    """

    ceiling: Decimal | None = None
    spent: Decimal = field(default=_ZERO)
    calls: int = 0

    def __post_init__(self) -> None:
        self.ceiling = _as_money(self.ceiling, "ceiling")
        self.spent = _as_money(self.spent, "spent") or _ZERO

    @classmethod
    def from_settings(cls, settings: "Settings") -> CostGuard:
        """A guard for one run, using ``MAX_COST_USD_PER_RECEIPT``."""
        return cls(ceiling=settings.max_cost_usd_per_receipt)

    @property
    def enabled(self) -> bool:
        return self.ceiling is not None and self.ceiling > _ZERO

    @property
    def remaining(self) -> Decimal | None:
        """What is left of the budget, or ``None`` when there is no ceiling."""
        ceiling = self.ceiling
        if ceiling is None or ceiling <= _ZERO:
            return None
        return ceiling - self.spent

    def check(self) -> None:
        """Raise :class:`CostCeilingExceeded` when the budget is already spent."""
        ceiling = self.ceiling
        if ceiling is not None and ceiling > _ZERO and self.spent >= ceiling:
            raise CostCeilingExceeded(self.spent, ceiling)

    def add(self, cost: Decimal) -> None:
        """Charge one model call. ``float`` is refused (ADR-0001)."""
        amount = _as_money(cost, "cost")
        if amount is not None:
            self.spent += amount
        self.calls += 1


def _as_money(value, label: str) -> Decimal | None:
    """Coerce an amount to a **finite** ``Decimal``, refusing ``float`` outright.

    Mirrors ``persist.repository._coerce_money``: a ``float`` cannot represent an
    exact amount, and a budget that drifts by a fraction of a cent per call is a
    bug that only shows up as an unexplained early stop months later. ``NaN`` and
    ``Infinity`` are legal ``Decimal``s but are refused too, for the same reason
    ``_coerce_money`` refuses them there.
    """
    if value is None:
        return None
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError(
            f"{label} must be a Decimal, not {type(value).__name__} ({value!r}); "
            "a float cannot represent an exact amount (ADR-0001)"
        )
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, int):
        amount = Decimal(value)
    else:
        amount = Decimal(str(value))

    if not amount.is_finite():
        raise ValueError(
            f"{label} must be a finite amount, not {value!r}; a NaN cost makes "
            "`spent` NaN, and `NaN >= ceiling` is always False -- the ceiling "
            "would silently never fire"
        )
    return amount


# --------------------------------------------------------------------------- #
# The decorator client
# --------------------------------------------------------------------------- #


class GuardedVLMClient(VLMClient):
    """Wraps any :class:`VLMClient` with the concurrency gate and cost guard.

    Deliberately a decorator rather than a change to the extractor: the pipeline
    swaps one client for another and every pass -- triage, extract, repair,
    consistency -- is covered with no further call sites to keep in step.
    Either guard may be ``None``, in which case that check is skipped.
    """

    def __init__(
        self,
        inner: VLMClient,
        *,
        gate: VLMGate | None = None,
        guard: CostGuard | None = None,
    ) -> None:
        self.inner = inner
        self.model_id = inner.model_id
        self.gate = gate
        self.guard = guard

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
        # Check the budget before the call: a refused call costs nothing, and
        # stopping *after* an overspend would defeat the point of a ceiling.
        if self.guard is not None:
            self.guard.check()

        if self.gate is None:
            response = self.inner.complete_json(
                system=system, user=user, images=images, schema=schema,
                temperature=temperature, max_tokens=max_tokens,
                tool_name=tool_name, tool_description=tool_description,
            )
        else:
            with self.gate:
                response = self.inner.complete_json(
                    system=system, user=user, images=images, schema=schema,
                    temperature=temperature, max_tokens=max_tokens,
                    tool_name=tool_name, tool_description=tool_description,
                )

        if self.guard is not None:
            self.guard.add(response.cost_usd)
        return response
