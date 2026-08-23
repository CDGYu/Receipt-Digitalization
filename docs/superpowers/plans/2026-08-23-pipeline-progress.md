# Pipeline progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A receipt being processed can report which stage it is on, and what
the extract loop is doing, without changing what any existing caller does.

**Architecture:** Three layers, each testable alone. A pure vocabulary module
that knows how to describe and serialise a progress event and nothing else. An
**optional, default-`None`** sink threaded through `extract_with_repair` and
`process_receipt`, so behaviour is unchanged by construction when nobody passes
one. And a Redis-backed writer that lives in `worker.py` beside the existing
lazy-import queue code, plus a read route injected the way `submit` already is.

**The pipeline never imports `redis`.** `rq` and `redis` are an optional extra
imported lazily (`worker.py`'s module docstring), and the whole suite runs
offline. Redis appears only in `worker.py` and behind `app.state.read_progress`.

**Tech Stack:** Python 3.11/3.13, FastAPI, SQLAlchemy, RQ + Redis (optional
extra), pytest.

**Spec:** `docs/superpowers/specs/2026-08-23-upload-and-visual-refresh-design.md`
— §2, decisions 1–4. This plan is **plan 1 of 3**; the upload/processing screen
and the visual refresh are separate plans and are **out of scope here**.

## Global Constraints

- **`python -m pytest` must stay offline and Node-free.** No test may require
  `redis`, `rq`, or a network.
- **Optional-import discipline:** `redis` is imported *inside a function body*,
  never at module import, and a missing install raises a `RuntimeError` naming
  the extra — copy the shape of `worker.py`'s `make_redis`.
- **Every existing caller of `extract_with_repair` and `process_receipt` must be
  unaffected.** The new parameter is keyword-only and defaults to `None`.
- **`STAGES` (`pipeline.py`) is the operational vocabulary.** Those strings land
  in `review_tasks.reason` and in logs. Progress reports those names and invents
  none.
- **No money crosses this boundary**, so ADR-0001 is not in play; but nothing
  here may serialise a `float` either.
- **Stage by explicit path, never `git add -A`.**
- Run the whole suite with bare `python -m pytest` — `pyproject.toml` sets
  `addopts = "-q"`, so `-q` becomes `-qq` and prints no pass count.

---

## File Structure

| file | responsibility |
|---|---|
| **Create** `src/receipts/progress.py` | The vocabulary: `ProgressEvent`, `encode`, `decode`, `progress_key`. Pure — no I/O, no Redis, no pipeline import. |
| **Create** `tests/test_progress.py` | Task 1's pins. |
| **Modify** `src/receipts/extract/extractor.py` | `extract_with_repair` gains `progress=None` and emits per attempt. |
| **Modify** `src/receipts/pipeline.py` | `_stage` gains `progress=None` and emits on entry; `process_receipt` gains `progress=None` and threads it. |
| **Modify** `tests/test_process_receipt.py` | Task 2's pins. |
| **Modify** `src/receipts/worker.py` | `make_progress_writer` — the only place `redis` is touched for progress. |
| **Modify** `src/receipts/review/api.py` | `read_progress` injection + `GET /receipts/{receipt_id}/progress`. |
| **Modify** `tests/test_api_read.py` | Task 3's route pins. |

---

## Task 1: The progress vocabulary

**Files:**
- Create: `src/receipts/progress.py`
- Test: `tests/test_progress.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `@dataclass(frozen=True) class ProgressEvent: stage: str; detail: str | None = None`
  - `encode(event: ProgressEvent) -> str`
  - `decode(text: str) -> ProgressEvent` — raises `ValueError` on anything it
    cannot read
  - `progress_key(receipt_id: uuid.UUID) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_progress.py`:

```python
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


def test_text_that_is_not_an_event_raises_rather_than_returning_a_default() -> None:
    # Silence is the failure mode this whole design is built against: a reader
    # that swallowed a bad record would show a stale stage forever.
    for bad in ("", "not json", "[]", '{"detail": "no stage"}', '{"stage": 4}'):
        with pytest.raises(ValueError):
            decode(bad)


def test_the_key_is_namespaced_and_carries_the_id() -> None:
    receipt_id = uuid.UUID("11111111-2222-3333-4444-555555555555")
    key = progress_key(receipt_id)
    assert str(receipt_id) in key
    assert key.startswith("receipt-progress:")


def test_two_receipts_never_share_a_key() -> None:
    assert progress_key(uuid.uuid4()) != progress_key(uuid.uuid4())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_progress.py -v`
Expected: FAIL at collection — `ModuleNotFoundError: No module named 'receipts.progress'`.

- [ ] **Step 3: Write the implementation**

Create `src/receipts/progress.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_progress.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 5: Prove the strictness pin is real**

In `src/receipts/progress.py`, replace the body of `decode`'s stage check with
a permissive one — change `if not isinstance(stage, str):` to
`if False:` — and re-run.

Run: `python -m pytest tests/test_progress.py -v`
Expected: FAIL on
`test_text_that_is_not_an_event_raises_rather_than_returning_a_default`.
**Revert the mutation before continuing.** The mutation goes in `decode`,
where the module computes its answer, not in the test's expectation
(ADR-0051).

- [ ] **Step 6: Commit**

```bash
git add src/receipts/progress.py tests/test_progress.py
git diff --cached --stat
git commit -m "feat(progress): a pure vocabulary for what a receipt is doing"
```

---

## Task 2: The optional sink through the pipeline

**Files:**
- Modify: `src/receipts/extract/extractor.py`
- Modify: `src/receipts/pipeline.py`
- Test: `tests/test_process_receipt.py`

**Interfaces:**
- Consumes: `receipts.progress.ProgressEvent` (Task 1).
- Produces:
  - `ProgressSink = Callable[[ProgressEvent], None]` (declared in `pipeline.py`)
  - `extract_with_repair(..., progress: Callable[[ProgressEvent], None] | None = None)`
  - `process_receipt(..., progress: Callable[[ProgressEvent], None] | None = None)`
  - `_stage(name: str, progress=None)` — emits on entry

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_process_receipt.py`:

```python
def test_progress_reports_only_real_pipeline_stages(
    session_factory, storage, settings
) -> None:
    """The vocabulary is bound to `STAGES`, not re-typed beside it.

    Those strings also land in `review_tasks.reason` and in the logs, so a
    progress name that is not a stage name would be a second vocabulary that
    can drift from the first.
    """
    from receipts.pipeline import STAGES

    seen: list = []
    job = _job(storage)
    process_receipt(
        job,
        client=_Client([_triage(), _good()]),
        storage=storage,
        session_factory=session_factory,
        settings=settings,
        progress=seen.append,
    )

    assert seen, "no progress was reported at all"
    assert [e.stage for e in seen if e.stage not in STAGES] == []
    # The stages a healthy run must pass through, in order of first sighting.
    order = [e.stage for e in seen]
    for name in ("load", "preprocess", "triage", "extract", "score", "persist"):
        assert name in order, f"{name} never reported"
    assert order.index("load") < order.index("extract") < order.index("persist")


def test_the_extract_stage_reports_each_attempt(
    session_factory, storage, settings
) -> None:
    """The repair loop is the only stage worth narrating, so it must say more
    than its own name. A broken first pass then a good repair is two attempts."""
    seen: list = []
    job = _job(storage)
    process_receipt(
        job,
        client=_Client([_triage(), _broken_totals(), _good()]),
        storage=storage,
        session_factory=session_factory,
        settings=settings,
        progress=seen.append,
    )

    details = [e.detail for e in seen if e.stage == "extract" and e.detail]
    assert len(details) >= 2, f"expected an event per attempt, got {details}"


def test_passing_no_sink_changes_nothing(
    session_factory, storage, settings
) -> None:
    """The property that makes this safe on the hot path.

    Same fixture, same client script, with and without a sink: the outcome
    must be identical. Asserted rather than assumed, because `progress` is
    threaded through the one function every receipt goes through.
    """
    def run(progress):
        return process_receipt(
            _job(storage),
            client=_Client([_triage(), _good()]),
            storage=storage,
            session_factory=session_factory,
            settings=settings,
            progress=progress,
        )

    without = run(None)
    with_sink = run([].append)
    assert without.status == with_sink.status
    assert without.failed_stage == with_sink.failed_stage
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_process_receipt.py -k progress -v`
Expected: FAIL with `TypeError: process_receipt() got an unexpected keyword
argument 'progress'`.

**Note:** `-k progress` matches by substring, and all three new test names
contain it. Confirm the selection is 3 tests before reading the result.

- [ ] **Step 3: Thread the sink through `pipeline.py`**

In `src/receipts/pipeline.py`, add the import and the alias near the top:

```python
from .progress import ProgressEvent

#: A callable the pipeline hands progress to. ``None`` everywhere by default:
#: the sink is for a waiting screen, and no existing caller wants one.
ProgressSink = Callable[[ProgressEvent], None]
```

Change `_stage` so entering a stage *is* reporting it — the emit cannot be
forgotten at a call site because it lives in the helper:

```python
@contextlib.contextmanager
def _stage(name: str, progress: "ProgressSink | None" = None):
    """Tag anything raised inside the block with ``name``, and report entry.

    An inner :class:`_StageFailure` passes through untouched, so the innermost
    (most specific) stage wins.

    ``progress`` is optional and defaults to ``None``. A sink that raises must
    not take the receipt down with it: a waiting screen is a nicety and the
    extraction is not.
    """
    if progress is not None:
        try:
            progress(ProgressEvent(stage=name))
        except Exception:  # pragma: no cover - a sink is never load-bearing
            log.warning("progress sink raised on stage %s; continuing", name)
    try:
        yield
    except _StageFailure:
        raise
    except Exception as exc:
        raise _StageFailure(name, exc) from exc
```

Add the parameter to `process_receipt`'s signature, after `cost_guard`:

```python
    progress: "ProgressSink | None" = None,
```

Then pass it at **every** `_stage(...)` call site in `process_receipt` —
`load`, `preprocess`, `dedupe`, the nested `persist`, `triage`, `merchant`,
`extract`, `score`, `persist`. For example:

```python
        with _stage("load", progress):
```

And hand it to the extractor at the `extract` site:

```python
        with _stage("extract", progress):
            outcome = extract_with_repair(
                image,
                guarded,
                triage_result=triage_result,
                ctx=ctx,
                hints=hints,
                few_shots=few_shots,
                max_repairs=max(0, settings.max_repair_attempts),
                normalize_fn=_normalizer(settings.default_currency, merchant_currency),
                progress=progress,
            )
```

- [ ] **Step 4: Emit per attempt in `extract_with_repair`**

In `src/receipts/extract/extractor.py`, add the import:

```python
from ..progress import ProgressEvent
```

Add the keyword-only parameter to `extract_with_repair`, after `cache`:

```python
    progress: "Callable[[ProgressEvent], None] | None" = None,
```

Add this helper just above `extract_with_repair`:

```python
def _report(progress, attempts: list[Attempt]) -> None:
    """Describe the attempt that just finished.

    Counted from `attempts` rather than from a counter variable, so the number
    cannot disagree with the list it describes. A sink that raises is swallowed:
    narration is never load-bearing.
    """
    if progress is None:
        return
    last = attempts[-1]
    errors = last.report.error_count
    detail = (
        f"attempt {len(attempts)} ({last.pass_name}): "
        f"{errors} error{'' if errors == 1 else 's'}"
    )
    try:
        progress(ProgressEvent(stage="extract", detail=detail))
    except Exception:  # pragma: no cover - a sink is never load-bearing
        log.warning("progress sink raised during extract; continuing")
```

Call it immediately after **each** `attempts.append(...)` — there are two, the
first pass and the one inside the repair loop:

```python
    attempts.append(_evaluate(response, ctx, normalize_fn, "extract"))
    _report(progress, attempts)
```

```python
        attempts.append(_evaluate(response, ctx, normalize_fn, pass_name))
        _report(progress, attempts)
```

And once more after the best attempt is chosen, so the screen can say which
one survived:

```python
    best = min(attempts, key=lambda a: a.rank())
    if progress is not None:
        kept = attempts.index(best) + 1
        try:
            progress(ProgressEvent(
                stage="extract", detail=f"kept attempt {kept} of {len(attempts)}"
            ))
        except Exception:  # pragma: no cover - a sink is never load-bearing
            log.warning("progress sink raised choosing best attempt; continuing")
```

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `python -m pytest tests/test_process_receipt.py -k progress -v`
Expected: PASS, 3 tests.

- [ ] **Step 6: Run the whole suite unmodified**

Run: `python -m pytest`
Expected: PASS. **No existing test may be edited to accommodate this task.**
If one needs changing, stop and report — that means the default is not
behaviour-preserving, which is the whole premise of Decision 4.

- [ ] **Step 7: Prove the stage pin red, in the subject**

Delete the emit from `_stage` — replace the `if progress is not None:` block
with `pass` — and re-run.

Run: `python -m pytest tests/test_process_receipt.py -k progress -v`
Expected: FAIL on `test_progress_reports_only_real_pipeline_stages` with
"no progress was reported at all".

**The mutation goes in `_stage`, where the pipeline computes what it reports —
not in the test.** Revert it, then mutate `_report` to emit
`ProgressEvent(stage="extracting")` (a name not in `STAGES`) and re-run:
expected FAIL on the same test's `not in STAGES` assertion. Revert that too.

- [ ] **Step 8: Commit**

```bash
git add src/receipts/pipeline.py src/receipts/extract/extractor.py tests/test_process_receipt.py
git diff --cached --stat
git commit -m "feat(pipeline): an optional progress sink, off by default"
```

---

## Task 3: The Redis writer and the read route

**Files:**
- Modify: `src/receipts/worker.py`
- Modify: `src/receipts/review/api.py`
- Test: `tests/test_api_read.py`

**Interfaces:**
- Consumes: `progress_key`, `encode`, `decode`, `ProgressEvent` (Task 1);
  `process_receipt(..., progress=...)` (Task 2).
- Produces:
  - `worker.make_progress_writer(receipt_id: uuid.UUID, *, url: str | None = None, settings: Settings | None = None, ttl_s: int = PROGRESS_TTL_S) -> Callable[[ProgressEvent], None]`
  - `worker.PROGRESS_TTL_S: int`
  - `create_app(..., read_progress: Callable[[uuid.UUID], ProgressEvent | None] | None = None)`
  - `GET /receipts/{receipt_id}/progress`

- [ ] **Step 1: Write the failing route tests**

Append to `tests/test_api_read.py`. These use the module's **real** fixtures --
`session_factory`, `settings`, `receipt_id` (`RECEIPT_B`), `pending_receipt_id`
(`RECEIPT_C`) -- and build their own app the way `empty_client` already does,
because they need a `read_progress` the shared `app` fixture does not pass:

```python
def _progress_client(session_factory, settings, tmp_path, reader) -> TestClient:
    """A signed-in client whose app reads progress from `reader`.

    Built inline rather than from the `app` fixture, following `empty_client`:
    this variant needs an argument the shared fixture does not pass. The
    injected reader is what keeps the suite offline -- `_default_read_progress`
    is the only thing that touches Redis and no test reaches it.
    """
    app = create_app(
        session_factory=session_factory,
        storage=LocalStorage(tmp_path / "progress-blobs"),
        submit=lambda job: None,
        settings=settings,
        read_progress=reader,
    )
    return _logged_in(app, "alice", "pw-alice")


def test_progress_reports_the_stage_a_reader_supplies(
    session_factory, settings, tmp_path, receipt_id
) -> None:
    from receipts.progress import ProgressEvent

    client = _progress_client(
        session_factory, settings, tmp_path,
        lambda _id: ProgressEvent(stage="extract", detail="attempt 1"),
    )
    reply = client.get(f"/receipts/{receipt_id}/progress")

    assert reply.status_code == 200
    body = reply.json()
    assert body["stage"] == "extract"
    assert body["detail"] == "attempt 1"


def test_progress_still_answers_when_there_is_no_record(
    session_factory, settings, tmp_path, pending_receipt_id
) -> None:
    """Silence is not an error, and it is not "still working" either.

    Progress is narration; the receipt's own status is the truth. A missing
    record answers 200 with a null stage and the real status, so a screen can
    tell "nothing to narrate" from "nothing happened".
    """
    client = _progress_client(session_factory, settings, tmp_path, lambda _id: None)
    reply = client.get(f"/receipts/{pending_receipt_id}/progress")

    assert reply.status_code == 200
    body = reply.json()
    assert body["stage"] is None
    assert body["detail"] is None
    assert body["status"] == "pending"


def test_progress_for_an_unknown_receipt_is_404(
    session_factory, settings, tmp_path
) -> None:
    from receipts.progress import ProgressEvent

    client = _progress_client(
        session_factory, settings, tmp_path,
        lambda _id: ProgressEvent(stage="extract"),
    )
    reply = client.get(f"/receipts/{uuid.uuid4()}/progress")

    assert reply.status_code == 404


def test_progress_needs_a_signed_in_caller(
    session_factory, settings, tmp_path, receipt_id
) -> None:
    """Same guard as every other receipt route: `require_user`."""
    from receipts.progress import ProgressEvent

    app = create_app(
        session_factory=session_factory,
        storage=LocalStorage(tmp_path / "progress-anon-blobs"),
        submit=lambda job: None,
        settings=settings,
        read_progress=lambda _id: ProgressEvent(stage="extract"),
    )
    reply = TestClient(app).get(f"/receipts/{receipt_id}/progress")

    assert reply.status_code == 401
```

**`pending_receipt_id` is `RECEIPT_C`, and its seeded status is
`ReceiptStatus.PENDING`** — verified by reading the seed, not assumed, so the
second test's `status == "pending"` is a fact about the fixture rather than a
hope. If that ever changes, assert what the seed gives it; do not edit the seed
to suit the test.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_api_read.py -k progress -v`
Expected: FAIL — 404 from FastAPI for an unregistered path on the first two.

**Careful:** the third test asserts 404 and **FastAPI 404s an unregistered
path on its own**, so that one passes before the route exists. That is a
RED phase that proves nothing (it has bitten a plan in this repo before).
Treat only the first two as the red proof, and re-check the third after the
route is registered.

- [ ] **Step 3: Add the reader injection and the route**

In `src/receipts/review/api.py`, add beside `_default_submit`:

```python
def _default_read_progress(receipt_id: uuid.UUID) -> Any:
    """Read one receipt's progress from the real Redis behind ``REDIS_URL``.

    ``redis`` is imported inside the body, the same way :func:`_default_submit`
    imports the queue, so importing this module needs neither package. The
    offline test suite never calls this: every test injects a reader.

    A record that will not decode is treated as no record. The alternative --
    letting a malformed value 500 the route -- would turn a cosmetic feature
    into an outage on a screen whose whole job is to look calm.
    """
    from ..progress import decode, progress_key
    from ..worker import make_redis

    raw = make_redis().get(progress_key(receipt_id))
    if raw is None:
        return None
    try:
        return decode(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    except (ValueError, UnicodeDecodeError):
        log.warning("undecodable progress record for %s; reporting none", receipt_id)
        return None
```

`create_app` is keyword-only — `session_factory`, `storage`, `submit=None`,
`settings=None`. Add a fifth beside `submit`:

```python
    read_progress: Any = None,
```

and wire it next to the existing assignments:

```python
    app.state.read_progress = read_progress or _default_read_progress
```

**And fix the count this rots.** `create_app`'s docstring says it *"Populates
the four ``app.state`` attributes Task 3's guards already read"* and then names
them. There are five now. Replace the number with the list it already carries —
`(``session_factory``, ``storage``, ``settings``, ``submit``, ``read_progress``)`
— rather than writing "five", because the next addition rots that too (review
standard 5).

Register the route beside `get_one_receipt`:

```python
    @app.get("/receipts/{receipt_id}/progress")
    def get_receipt_progress(
        receipt_id: uuid.UUID,
        request: Request,
        user: Annotated[SessionUser, Depends(require_user)],
    ) -> dict[str, Any]:
        """What this receipt is doing, if anything is narrating it.

        **Progress is narration; ``status`` is the truth.** A caller decides
        the work is finished from ``status``, never from ``stage`` going quiet
        -- a dead worker stops writing progress and a screen that waited for a
        terminal *stage* would wait forever.
        """
        with request.app.state.session_factory() as session:
            receipt = get_receipt(session, receipt_id)
            if receipt is None:
                raise HTTPException(
                    status_code=404, detail=f"no receipt with id {receipt_id}"
                )
            status = receipt.status.value if receipt.status else None
        event = request.app.state.read_progress(receipt_id)
        return {
            "status": status,
            "stage": event.stage if event else None,
            "detail": event.detail if event else None,
        }
```

- [ ] **Step 4: Add the writer to `worker.py`**

In `src/receipts/worker.py`:

```python
#: How long a progress record outlives its last write. Long enough to survive a
#: slow extract pass, short enough that an abandoned run disappears on its own.
PROGRESS_TTL_S = 900


def make_progress_writer(
    receipt_id: uuid.UUID,
    *,
    url: str | None = None,
    settings: Settings | None = None,
    ttl_s: int = PROGRESS_TTL_S,
) -> Callable[[Any], None]:
    """A sink for :func:`receipts.pipeline.process_receipt`'s ``progress``.

    Each event overwrites the last: a waiting screen wants the current stage,
    not a history, and one key per receipt with a TTL means an abandoned run
    cleans itself up with no sweeper.

    Uses :func:`make_redis`, so a missing optional extra raises the same
    ``RuntimeError`` naming ``.[worker]`` that the queue does.
    """
    from .progress import encode, progress_key

    connection = make_redis(url=url, settings=settings)
    key = progress_key(receipt_id)

    def write(event: Any) -> None:
        connection.set(key, encode(event), ex=ttl_s)

    return write
```

Then, in `process_receipt_job`, build one and pass it to `process_receipt` —
read that function first and follow its existing dependency-building shape.

- [ ] **Step 5: Run the route tests to verify they pass**

Run: `python -m pytest tests/test_api_read.py -k progress -v`
Expected: PASS, 3 tests.

- [ ] **Step 6: Re-check the 404 test now that the route exists**

Temporarily change the route's 404 to `status_code=410` and re-run.

Run: `python -m pytest tests/test_api_read.py -k progress -v`
Expected: FAIL on `test_progress_for_an_unknown_receipt_is_404`.
That is the proof the third test now measures **this route** rather than
FastAPI's unregistered-path behaviour. **Revert.**

- [ ] **Step 7: Run the whole suite and the gates**

Run: `python -m pytest`
Expected: PASS, with no existing test edited.

Then: `python scripts/verify.py` — **background it, and do not edit source
while it runs.** Expected: all five PASS.

- [ ] **Step 8: Commit**

```bash
git add src/receipts/worker.py src/receipts/review/api.py tests/test_api_read.py
git diff --cached --stat
git commit -m "feat(api): a receipt can say what it is doing"
```

---

## Self-Review

**Spec coverage.** §2 decision 1 (Redis, not a column) → Task 3, and no
migration appears anywhere in this plan. Decision 2 (a separate read route) →
Task 3 Step 3. Decision 3 (status is truth) → Task 3's route docstring, the
`status` key in the response, and
`test_progress_still_answers_when_there_is_no_record`. Decision 4 (an optional
sink) → Task 2, pinned by `test_passing_no_sink_changes_nothing` and by Step
6's "no existing test may be edited". §1's optional-import discipline → Task 1
is pure, and `redis` appears only in `worker.py` and `_default_read_progress`.

**Out of scope and deliberately absent:** no screen, no polling, no token
change. Those are plans 2 and 3.

**Placeholder scan.** None. An earlier draft of Task 3 Step 1 named
`client_factory` and `_seed_receipt` as placeholders "for whatever that module
already provides". **They do not exist** — `tests/test_api_read.py` provides
`session_factory`, `settings`, `submitted`, `app`, `client`, `reviewer_client`,
`admin_client`, `receipt_id`, `pending_receipt_id` and `clients`, and builds
variant apps inline the way `empty_client` does. The step now uses those names,
verified by reading the module. **A flagged placeholder is still a placeholder**
— the fixtures were one `grep` away and the flag was doing the work the grep
should have.

**Type consistency.** `ProgressEvent(stage, detail)` is spelled identically in
Tasks 1, 2 and 3. `progress_key` and `encode`/`decode` keep their Task 1
signatures at every call site. `progress` is the parameter name in both
`extract_with_repair` and `process_receipt`; `ProgressSink` is declared once,
in `pipeline.py`.

**Known soft spots, stated rather than hidden.**

1. **`_report` counts attempts from `len(attempts)`.** If a future change
   appends to that list without reporting, the count stays honest but an
   attempt goes unnarrated. That is the safe direction of the two.
2. **Task 3 Step 4 does not show the `process_receipt_job` edit.** Its
   dependency-building shape is not quoted here because this plan has not read
   that function closely enough to reproduce it, and a wrong code block is
   worse than an instruction to read it. **Read it first.**
3. **Nothing pins that the worker actually passes a writer.** The offline suite
   cannot reach Redis, so the end-to-end path (worker → Redis → route) is
   verified by neither task. It is the same class of gap ADR-0047 recorded for
   the escalation, and closing it needs the live stack — which the design's §9
   already flags as an unscheduled dry run.

---

## Dated defect log

**This plan does not self-amend.** Everything above is the text as written; this
log is what was wrong with it and when. Transcribed 2026-08-24 from
`.superpowers/sdd/2026-08-23-pipeline-progress/progress.md`, which is
gitignored (`.gitignore` excludes `.superpowers/`) and therefore reaches no one
who clones this repository. Nine defects were found during execution and every
one of them lived only there until this section existed.

### Still wrong in the text above, and not corrected there

Three things a reader following this plan today would be misled by. They are
listed rather than fixed, because a dated plan is a record of what was written.

- **Global Constraints, "copy the shape of `worker.py`'s `make_redis`"
  (Optional-import discipline).** There was no `make_redis`. At the plan's BASE
  the function was `def _redis_connection(url: str | None, settings: Settings |
  None = None)` — **private, and `url` positional** — so the name and the call
  form in Task 3's code blocks were both wrong. See defect 6.
- **Task 2 Step 2's "Confirm the selection is 3 tests."** `python -m pytest
  tests/test_process_receipt.py -k progress` selects **1**: only
  `test_progress_reports_only_real_pipeline_stages` carries the substring, and
  the other two are named `..._each_attempt` and `..._no_sink`. Re-measured
  2026-08-24 with `--collect-only -q`; still 1. See defect 3.
- **Every `Run:` line that names a module uses `-v`** — nine of them, in all
  three tasks. `pyproject.toml` sets `addopts = "-q"`, so `-v` nets to
  verbosity 0 and prints a dot line with no test names; `-vv` is what shows
  per-test IDs. This document's own Global Constraints explains that exact
  interaction for `-q`/`-qq`, and then the steps use `-v` as though it worked.
  See defect 1. *(The whole-branch review listed six of the nine,
  omitting Task 1's three — a list in prose read as complete, in a finding about
  lists in prose.)*

### 2026-08-23 — the nine defects, in the order they were found

**Defect 1 — `-v` nets to verbosity 0 in this repository.** Found by the Task 1
implementer. As above. **Ruling:** Tasks 2 and 3 were dispatched with `-vv`
spelled out rather than amending this document. *Cost if wrong: an implementer
reads a bare dot line and cannot see which test failed, costing one extra run.*

**Defect 2 — Task 2's third test could not have passed as written.** Found by
the Task 2 implementer. `test_passing_no_sink_changes_nothing` called
`_job(storage)` twice against one storage, and `_png_bytes` is deterministic —
so both jobs carry the same image and the same phash, the second run takes the
**image-dedupe** short circuit and comes back `rejected` without ever
extracting. The test compared `rejected` against `auto_approved` and would have
failed with or without a sink. The implementer proved the sink was not the cause
before touching anything: both runs with `progress=None` failed identically.
**Ruling:** the repair is accepted. Each run now gets its own database and blob
store, so the sink is the only difference between them — which is the property
the test exists to isolate. *Cost if wrong: the behaviour-preservation pin
measures something narrower than intended.*

**Defect 3 — `-k progress` selects 1 test, not 3.** As above. The plan's own
step told the implementer to confirm the selection first, and it did, which is
the only reason this was caught rather than silently under-running.
`-k "progress or each_attempt or no_sink"` is the working filter. This is the
species `docs/MEMORY.md` records: **a `-k` filter in a plan is a claim about the
names in that same plan**, and it has now bitten a third plan.

**Defect 4 — an annotation with no import in scope.** The brief's annotation on
`extract_with_repair` used `Callable` without importing it in `extractor.py`;
ruff's `F` ruleset would have caught it. The implementer added
`from typing import Callable`. **Ruling:** accepted, the minimal correct fix.

**Defect 5 — a wrong prediction about a mutation's failure message.** The brief
predicted Task 2's mutation 1 would fail with a specific message; it fails on
"load never reported" instead, because `_report` still emits from inside
`extract`. The prediction was wrong; the mutation still reddens the right test
for the right reason.

**Defect 6 — `make_redis` never existed, and this is the worst of the nine.**
At BASE the function was `_redis_connection`, private and positional, so
Task 3's `make_redis(url=url, settings=settings)` was wrong on the name *and*
on the call form. The controller produced that name by reading the function's
**body** during pre-flight — the lazy `import redis`, the `RuntimeError` naming
the extra, the `return redis.Redis.from_url` — and inferring the name from
context, never reading its `def` line. It then repeated the name in the
dispatch as "copy the shape of `worker.py`'s existing `make_redis`", turning a
relayed guess into an instruction. **Ruling:** the implementer's rename
(`_redis_connection` → `make_redis`, keyword-only to match `make_queue`, added
to `__all__`, both call sites updated) is accepted — a second module now
legitimately needs the connection, and importing a private cross-module name is
the worse of the two options. *Cost if wrong: a public name where a private one
would have done, and two call sites the brief did not list.*

**Defect 7 — a reasoning defect, not a factual one: the brief declared the
worker wiring unpinnable offline.** Soft spot 3 in the Self-Review above said
the worker→Redis→route path could not be verified without a live stack, and
Task 3's brief treated that as covering the wiring too. The implementer showed
this conflates **transport**
with **wiring**: the Redis round trip does need a live stack, but
`progress=progress`, the `progress_factory` field, the key, the wire form and
the TTL do not. As the brief specified it, **all five were deletable with five
green gates.** It added `tests/test_worker.py` to close them. **Ruling:**
accepted, and the added file is in scope. The soft spot was not a limitation
that was discovered, it was one that was assumed; `make_progress_writer` would
otherwise have shipped with zero coverage. *This is the shape ADR-0048 names —
a correct instruction (the end-to-end path does need a live stack) carrying a
reason that reads as coverage of more than it covers.*

**Defect 8 — Task 3 Step 5 says "3 tests"; the filter selected 4.** Same
species as defect 3, one task later. *(The number moves as tests are added; 4
is what it selected on 2026-08-23.)*

**Defect 9 — a wrong prediction about a RED phase's reason.** Task 3 Step 2
predicted the red would be a FastAPI 404 on an unregistered path. It is a
`create_app` **TypeError**, because the test passes `read_progress=` before the
parameter exists. The RED is honest either way; the predicted reason was wrong —
the same species as defect 5.

### Rulings taken during execution, which lived only in the ledger

- **No new git worktree; the feature branch is the isolation.** Standing
  practice is one worktree (ADR-0023), the three tasks are strictly serial, and
  the work is not on `main`. *Cost if wrong: none while serial.*
- **The `normalize` stage is not reported, and that is accepted.** All nine
  `_stage` calls the plan threads are inside `process_receipt`. The tenth,
  `_stage("normalize")`, lives in `_normalizer` — a closure `process_receipt`
  hands to `extract_with_repair` — so `progress` cannot reach it without
  changing that helper's signature. Normalization runs *inside* `extract`, which
  is already narrated per attempt, and the design never asked for a separate
  beat. *Cost if wrong: the screen cannot show "normalising" as its own row;
  adding it later is a one-signature change to one helper.*
- **Task 2's "every emitted stage is in `STAGES`" is a subset relation, not
  equality**, so the ruling above does not falsify it: `STAGES` contains
  `normalize` whether or not anything emits it. Equality would have been the
  wrong shape regardless, since `dedupe` and `merchant` are also conditional.
- **Commits on this branch carry no `Co-Authored-By` trailer**, against the
  harness's standing instruction. The repository has never used one, and
  `tests/test_sha_citations.py` requires every backticked seven-hex token in a
  tracked file to resolve to a commit some ref can reach — four branch commits
  are already cited in `docs/KNOWN_ISSUES.md`, `IMPLEMENTATION_PLAN.md` and the
  design document, so rewriting history to add trailers would orphan all four
  and turn that gate red. *Cost if wrong: authorship attribution is absent from
  this branch's commits.*
- **A count that does not match its own list, recorded against the
  controller.** A fix message said "seven Minor findings and I have deferred all
  of them" and then listed six. The true split of Task 1's seven Minors is one
  absorbed into the Important fix (the `parametrize` conversion) and six
  deferred. The mismatch started in the controller's message and was inherited
  by the implementer's report before a re-review caught it.
- **The tracked plan diverging from the implemented file is not a defect.**
  After Task 1's review-driven fix the plan still showed the loop form of a test
  that had become `pytest.mark.parametrize`. These plans are dated historical
  records that do not self-amend; this log is where that gets corrected.

### What the fix waves found that the reviews had not

Recorded because in both cases the review had established *less* than was true:

- **Task 2's Important 1 was worse than the review stated.** The review showed
  that one of the three per-attempt emits was individually deletable under
  `assert len(details) >= 2`. The implementer ran all three deletions before
  fixing: **all three passed**, with the whole suite green. Every emit in the
  task's headline deliverable was individually deletable.
- **Task 3's implementer found a further instance unprompted.** `exc_info=True`
  was mandated on both new logs and **nothing asserted it** — the same
  never-pinned shape as the finding it was fixing, one level down. It also
  reworded `process_receipt_job`'s docstring, which claimed the function "adds
  no error handling of its own on purpose": true before the fix, false after.

### 2026-08-24 — the whole-branch review, and what it left

Verdict **MERGE AFTER FIXES**: no Critical, eleven Important. Two findings were
reproduced by mutation with the whole suite green — the production reader was
unpinned, and `status` was deletable exactly in the narrating case, which is the
one case the field exists for. **Five of the eleven were false claims in prose**,
four of them written by the fix rounds that closed real defects. That is this
repository's most-recorded defect (ADR-0032, ADR-0042) and it recurred here.

One finding was explicitly **not** a measurement: that a hung Redis could stall
the pipeline, reasoned from `from_url` being built with no socket timeouts and a
blocked call never returning, so `except Exception` cannot catch it. **Neither
the reviewer nor the controller could measure it — `redis` is not installed on
this machine.** The defensive fix was taken anyway, because a bound is correct
whether or not the hypothesis holds, and the constant carries that distinction
in its own docstring rather than asserting what redis-py does by default
(review standard 27).

**Still open after the fix wave**, and deliberately: the end-to-end path
(worker → Redis → route) is verified by neither task. Each half is pinned; the
join is not, and closing it needs a live stack. The design's §9 flags it as an
unscheduled dry run, and soft spot 3 above states it — correctly, once the
wiring it wrongly covered was pinned separately.
