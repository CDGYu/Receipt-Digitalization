# Terminal-State Guarantee Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every receipt whose processing stops without writing a terminal
status reach one anyway, on every path and for every cause of stopping.

**Architecture:** A heartbeat sink stamps two new columns on `receipts` as a run
works; it is built *inside* `process_receipt` so no call site can be silent. A
sweep with two thresholds finds rows whose heartbeat has gone cold and lands
them in `needs_review` following `_persist_failure`'s convention. Two runners
drive it: a `receipts sweep` command bears the guarantee, and the progress route
sweeps the single row a screen is waiting on. The RQ job ceiling is derived from
the same quantity the sweep threshold uses.

**Tech Stack:** Python 3.11/3.13, SQLAlchemy 2.x ORM, Alembic, FastAPI, RQ,
argparse, pytest.

**Spec:** `docs/superpowers/specs/2026-08-24-terminal-state-guarantee-design.md`
(committed `9798c4d`, corrected `56932a6`). **Read it before Task 1** -- this
plan argues from it and does not restate its reasoning.

**Closes:** ISSUE-030 (the centre), ISSUE-029, ISSUE-031.

---

## Global Constraints

Every task's requirements implicitly include all of these.

- **Money is `Decimal`, never float.** No task here touches money; if one seems
  to, stop and report.
- **A full PAN is never persisted.** Task 5's reason goes through `redact_pan`.
- **Nothing is silently dropped.** This plan exists to make that true.
- **A machine run never overwrites a `reviewed` row.** In the sweep this is
  structural: `reviewed` is excluded by the same `status='pending'` clause that
  selects the work.
- **ADR-0006:** repository functions take `session` first, `flush()`, and do
  **not** `commit()`. The caller owns the transaction.
- **Optional-import discipline.** `src/receipts/sweep.py` must import only from
  `persist` and `review.queue`. It must **never** import `receipts.pipeline` or
  `receipts.worker`: both the CLI and the API import the sweep, and pulling
  `pipeline` in at module top drags the optional `pipeline` extra into every
  command. `cli.py`'s own comment above `cmd_process` records this trap.
- **Two named margins, never one word for both** (spec section 8.1):
  `NON_MODEL_BUDGET_S` is additive seconds; `STRAND_MARGIN` is a dimensionless
  multiplier. Neither is written as a bare literal at a use site.
- **`python -m pytest` runs offline and Node-free.** No test may need Redis,
  network, or a real model.
- **Stage by explicit path.** Never `git add -A`. `docker-compose.yml` carries
  an unrelated uncommitted change that must stay uncommitted -- if it appears
  in `git diff --cached --stat`, unstage it and report.
- Run the full suite with bare `python -m pytest` (`addopts = "-q"` is already
  set, so `-q` would suppress the count).

### On the RED steps in this plan

Every "expected: FAIL" below is the controller's **prediction, not a
measurement**. On this project those predictions have been wrong before -- once
for 3 of 4 tests in a single task. So:

> **Read the actual failure reason at every RED step.** If a test fails for a
> different reason than predicted, or passes when a failure was predicted,
> **stop and report**. Do not adjust the test to match the prediction. A test
> that passes before its implementation exists is a test that proves nothing.

### Permitted edits

Rather than an enumerated list of allowed files (which has produced defects on
this project twice), the bound is:

> **Every test that exists before your task must still pass, unmodified.**
> If your task appears to require changing or deleting an existing test,
> **stop and report** instead. Adding tests is always allowed.

---

## File Structure

| file | action | responsibility |
|---|---|---|
| `src/receipts/persist/models.py` | modify | two nullable columns on `Receipt` |
| `alembic/versions/<new>_receipt_progress_heartbeat.py` | create | the migration for them |
| `src/receipts/worker.py` | modify | `job_timeout_for`, wired into `enqueue_receipt` |
| `src/receipts/persist/repository.py` | modify | `record_progress`, `find_stranded` |
| `src/receipts/pipeline.py` | modify | `fan_out`, `_heartbeat_sink`, built inside `process_receipt` |
| `src/receipts/sweep.py` | create | `strand_receipt`, `sweep_stranded` -- the only new module |
| `src/receipts/cli.py` | modify | `_add_sweep`, `cmd_sweep`, dispatch |
| `src/receipts/review/api.py` | modify | route falls back to the row; sweeps this row |
| `tests/test_sweep.py` | create | the six-shape fixture and the sweep's guarantees |
| `tests/test_repository.py`, `test_worker.py`, `test_pipeline.py`, `test_api_read.py`, `test_cli_core.py` | modify | add cases only |

`sweep.py` is a new module rather than an addition to `pipeline.py` **because of
the optional-import constraint above**, not for tidiness.

### Task order and why

Tasks 1 and 2 are independent of each other. Task 2 closes ISSUE-029 on its own,
so if the milestone stalls after it, that value is already correct. Tasks 3-7
are strictly sequential. Tasks 3 and 5 both touch `repository.py`, so under
ADR-0023 they must not run in parallel -- and this plan runs everything serially
anyway, one implementer per task.

---

### Task 1: The heartbeat columns and their migration

**Files:**
- Modify: `src/receipts/persist/models.py` (class `Receipt`)
- Create: `alembic/versions/c7f1a9e4d208_receipt_progress_heartbeat.py`
- Test: `tests/test_migrations.py` (existing, unmodified -- it already guards this)

**Interfaces:**
- Consumes: nothing.
- Produces: `Receipt.progress_stage: str | None`, `Receipt.progress_at:
  datetime | None`. Every later task reads or writes these two names.

**Why the existing test suite is the test here.** `tests/test_migrations.py`
already contains `test_migration_schema_matches_orm_metadata`, which runs
Alembic's `compare_metadata` against `Base.metadata` and asserts there are no
pending diffs. Adding columns to the ORM without a migration therefore turns it
red by itself. That is a genuine RED, and it is free.

- [ ] **Step 1: Add the two columns to the ORM**

In `src/receipts/persist/models.py`, inside `class Receipt`, immediately **before**
its `created_at` column:

```python
    #: What the run was doing when it was last known alive, and when that was.
    #: Written by the heartbeat sink on every stage entry and once per model
    #: call inside extract, so the largest gap between two writes is one model
    #: call -- which is what lets a sweep tell a slow receipt from a stranded
    #: one.
    #:
    #: NULL means no run has ever reported on this receipt. That is a
    #: *different* failure mode from "started and went cold", on a different
    #: timescale, and `receipts.sweep` must not collapse the two: a receipt
    #: queued behind a backlog is healthy and has no heartbeat either.
    progress_stage: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    progress_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
```

- [ ] **Step 2: Run the drift guard and watch it fail**

Run: `python -m pytest tests/test_migrations.py::test_migration_schema_matches_orm_metadata -v`

Expected: FAIL, with the assertion message `migration has drifted from the ORM
models:` followed by a diff naming `add_column` for `progress_stage` and
`progress_at`.

**Read the message.** If it names different columns, or fails for another
reason, stop and report.

- [ ] **Step 3: Write the migration**

Create `alembic/versions/c7f1a9e4d208_receipt_progress_heartbeat.py`:

```python
"""receipt progress heartbeat

Revision ID: c7f1a9e4d208
Revises: f3ae0f86e0e6
Create Date: 2026-08-24 00:00:00.000000

Two nullable columns on ``receipts`` recording when a run was last known alive
and what it was doing:

* ``receipts.progress_stage`` -- a member of ``receipts.pipeline.STAGES``,
  written on stage entry and once per model call inside extract.
* ``receipts.progress_at`` -- when that write happened.

Both nullable and both without a server default, deliberately. NULL is
meaningful here: it means no run has ever reported on this receipt, which
``receipts.sweep`` treats as a different failure mode from "started and went
cold" on a different timescale. A backfill would erase exactly the distinction
the sweep depends on, and a ``NOT NULL`` column would need one.

Because both are nullable, this needs no ``server_default`` and therefore none
of the portability care ``f3ae0f86e0e6`` documents for its boolean.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7f1a9e4d208"
down_revision: str | Sequence[str] | None = "f3ae0f86e0e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add ``receipts.progress_stage`` and ``receipts.progress_at``."""
    with op.batch_alter_table("receipts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("progress_stage", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("progress_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    """Drop both columns, newest first."""
    with op.batch_alter_table("receipts", schema=None) as batch_op:
        batch_op.drop_column("progress_at")
        batch_op.drop_column("progress_stage")
```

- [ ] **Step 4: Run the whole migration module**

Run: `python -m pytest tests/test_migrations.py -v`

Expected: PASS, every test. This exercises more than the drift guard -- the
revision chain, application to a populated database, the round trip, and
Postgres DDL rendering.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest`

Expected: PASS. Two nullable columns nothing reads yet cannot change behaviour;
if anything fails, stop and report.

- [ ] **Step 6: Commit**

```bash
git add src/receipts/persist/models.py alembic/versions/c7f1a9e4d208_receipt_progress_heartbeat.py
git diff --cached --stat
git commit -m "feat(persist): a receipt records when it was last known alive"
```

Check `git diff --cached --stat` names exactly those two files before committing.

---

### Task 2: The derived job ceiling (closes ISSUE-029)

**Files:**
- Modify: `src/receipts/worker.py`
- Test: `tests/test_worker.py`

**Interfaces:**
- Consumes: nothing from Task 1. This task is independent.
- Produces: `job_timeout_for(settings: Settings) -> int`, and
  `enqueue_receipt(job, queue, *, job_timeout: int | None = None, settings:
  Settings | None = None)`.

**The ADR-0051 hazard, and it is the whole reason this task is written out in
full.** The obvious test computes its expected value by calling
`job_timeout_for`, which is the function under test. Then changing the formula
moves both sides together and the test stays green while the ceiling goes
wrong. **Every expected number below is a written-out literal.** Do not replace
one with a call, an f-string, or an imported constant.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_worker.py`:

```python
def test_job_timeout_is_derived_from_the_model_budget_not_a_constant() -> None:
    """At code defaults the ceiling is 1080 + 180, not DEFAULT_JOB_TIMEOUT_S.

    The numbers are written out rather than computed. A test that recomputed
    them with the function under test would follow any change to the formula
    and never fail (ADR-0051: a guard must not share its derivation with its
    subject).

    120 s per HTTP attempt x 3 attempts x (triage + extract + 1 repair) = 1080,
    plus a 180 s non-model budget.
    """
    settings = Settings(_env_file=None, vlm_timeout_s=120, max_repair_attempts=1)
    assert worker.job_timeout_for(settings) == 1260


def test_job_timeout_tracks_the_configured_timeout() -> None:
    """600 s per attempt x 3 x 3 calls = 5400, plus 180."""
    settings = Settings(_env_file=None, vlm_timeout_s=600, max_repair_attempts=1)
    assert worker.job_timeout_for(settings) == 5580


def test_job_timeout_tracks_the_repair_budget() -> None:
    """Two repairs is four calls, not three: 120 x 3 x 4 = 1440, plus 180."""
    settings = Settings(_env_file=None, vlm_timeout_s=120, max_repair_attempts=2)
    assert worker.job_timeout_for(settings) == 1620


def test_the_old_constant_was_below_its_own_worst_case() -> None:
    """ISSUE-029, stated as a pin rather than as prose.

    At code defaults the derived ceiling exceeds 900, which is what the
    constant used to be. This is why a fixed constant was wrong on any
    hardware, not merely on the box where it was noticed.
    """
    settings = Settings(_env_file=None, vlm_timeout_s=120, max_repair_attempts=1)
    assert worker.job_timeout_for(settings) > 900


def test_enqueue_uses_the_derived_ceiling_when_none_is_given() -> None:
    """The default submit path must not fall back to a constant."""
    calls: list[dict[str, object]] = []

    class RecordingQueue:
        def enqueue(self, func, *args, **kwargs):
            calls.append(kwargs)
            return "handle"

    job = ReceiptJob(
        id=uuid.uuid4(),
        image_key="k",
        source="test",
        original_filename="r.jpg",
        content_type="image/jpeg",
    )
    worker.enqueue_receipt(
        job, RecordingQueue(), settings=Settings(_env_file=None, vlm_timeout_s=120, max_repair_attempts=1)
    )
    assert calls[0]["job_timeout"] == 1260


def test_an_explicit_job_timeout_still_wins() -> None:
    """An operator override is not overridden by the derivation."""
    calls: list[dict[str, object]] = []

    class RecordingQueue:
        def enqueue(self, func, *args, **kwargs):
            calls.append(kwargs)
            return "handle"

    job = ReceiptJob(
        id=uuid.uuid4(),
        image_key="k",
        source="test",
        original_filename="r.jpg",
        content_type="image/jpeg",
    )
    worker.enqueue_receipt(job, RecordingQueue(), job_timeout=42)
    assert calls[0]["job_timeout"] == 42


def test_the_sdk_retry_default_this_derivation_rests_on() -> None:
    """The x3 above is the SDK's default max_retries, which nothing here pins.

    ADR-0047 decision 8 records that OpenAICompatClient never sets
    max_retries, and ADR-0047 leaves pinning it undecided. Without this
    assertion a change to that default would make both the ceiling and the
    sweep threshold silently wrong and nothing would fail -- which is the
    ADR-0048 test for a load-bearing rationale.
    """
    import openai

    assert openai.OpenAI(api_key="unused").max_retries == 2
```

Whatever `tests/test_worker.py` already imports, ensure `uuid`, `ReceiptJob`,
`Settings` and the `worker` module are available; add imports if they are not
there, and change nothing that exists.

- [ ] **Step 2: Run them and watch them fail**

Run: `python -m pytest tests/test_worker.py -v -k "job_timeout or sdk_retry or enqueue_uses or explicit_job_timeout or own_worst_case"`

Expected: the six `job_timeout_for` / `enqueue` tests FAIL with
`AttributeError: module 'receipts.worker' has no attribute 'job_timeout_for'`
or a `TypeError` about an unexpected `settings` keyword.

**`test_the_sdk_retry_default_this_derivation_rests_on` is expected to PASS
immediately** -- it asserts an existing third-party default and has no
implementation to wait for. That is correct and is not a defect. If it *fails*,
stop and report: the whole derivation is then wrong and this task's numbers
need redoing before anything is built.

- [ ] **Step 3: Implement the derivation**

In `src/receipts/worker.py`, replace the `DEFAULT_JOB_TIMEOUT_S` block with:

```python
#: HTTP attempts the OpenAI SDK makes per call: the initial one plus its default
#: ``max_retries`` of 2, which ``OpenAICompatClient`` never overrides (ADR-0047
#: decision 8). The retries are silent, so one ``complete_json`` can take three
#: times ``VLM_TIMEOUT_S``.
#:
#: Pinned by ``test_the_sdk_retry_default_this_derivation_rests_on`` rather than
#: trusted: without that test a change to the SDK default would make this
#: derivation wrong and nothing would fail. Whether to *set* ``max_retries``
#: instead is ADR-0047's open question and is not taken here.
_SDK_ATTEMPTS = 3

#: Everything in a receipt that is not a model call -- reading the original
#: bytes, decoding and hashing the image, the dedupe and merchant reads,
#: scoring, and the persist write. Additive rather than a multiplier, because
#: this work is bounded and small whatever model is configured.
NON_MODEL_BUDGET_S = 180


def job_timeout_for(settings: Settings) -> int:
    """The ceiling for one receipt's job, derived from what its model can cost.

    A receipt is a triage call, an extract call, and up to
    ``MAX_REPAIR_ATTEMPTS`` repairs; each can take ``_SDK_ATTEMPTS`` HTTP
    attempts of ``VLM_TIMEOUT_S``.

    **Derived rather than a constant** because a constant that fits one model
    does not fit another, and this value was previously 900 -- below its own
    worst case of 1080 even at code defaults, on any hardware (ISSUE-029).

    Since ``receipts.sweep`` now carries the terminal-state guarantee, this
    ceiling no longer decides whether an interrupted receipt is recoverable.
    It is a resource guard on a worker slot, and can therefore be generous.
    """
    one_call = settings.vlm_timeout_s * _SDK_ATTEMPTS
    calls = 2 + max(0, settings.max_repair_attempts)
    return one_call * calls + NON_MODEL_BUDGET_S
```

Then change `enqueue_receipt` to resolve it:

```python
def enqueue_receipt(
    job: ReceiptJob,
    queue: Any,
    *,
    job_timeout: int | None = None,
    settings: Settings | None = None,
) -> Any:
    """Push one receipt onto ``queue`` and return the queue's handle.

    ``queue`` is anything with RQ's ``enqueue(func, *args, **kwargs)`` signature,
    which is what lets the dispatch path be tested without a live Redis. The
    enqueued callable is always :func:`process_receipt_job` -- the worker has one
    job type, and that is the invariant a test pins.

    ``job_timeout`` defaults to :func:`job_timeout_for` over ``settings`` rather
    than to a constant, so every caller gets a ceiling that fits the configured
    model. An explicit value still wins: an operator override is not overridden.
    """
    if job_timeout is None:
        job_timeout = job_timeout_for(settings or get_settings())
    return queue.enqueue(
        process_receipt_job,
        job_to_payload(job),
        job_timeout=job_timeout,
    )
```

Remove `"DEFAULT_JOB_TIMEOUT_S"` from `__all__` and delete the constant.

**One existing test asserts that constant, and you are authorised to change
that one assertion — this is the single exception to the permitted-edits bound
in Global Constraints.** Pre-flighted: `tests/test_worker.py`, inside
`test_enqueue_receipt_dispatches_only_process_receipt_job`, ends with

```python
    assert kwargs["job_timeout"] == worker_module.DEFAULT_JOB_TIMEOUT_S
```

That assertion *is* the pin on the behaviour this task replaces, so it cannot
survive. Replace it, and pass explicit settings so the test stops depending on
whatever `.env` happens to hold:

```python
    handle = enqueue_receipt(
        job, queue, settings=Settings(_env_file=None, vlm_timeout_s=120, max_repair_attempts=1)
    )
    ...
    assert kwargs["job_timeout"] == 1260
```

Change **nothing else** in that test and no other existing test. If you find a
second existing test that references the constant, **stop and report** -- the
pre-flight found exactly one.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_worker.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Prove the guard by mutation**

Change `calls = 2 + max(0, settings.max_repair_attempts)` to `calls = 3` and run
`python -m pytest tests/test_worker.py -v`.

Expected: `test_job_timeout_tracks_the_repair_budget` FAILS (1620 vs 1620 would
still match at defaults, which is exactly why that third test exists).

**Then revert the mutation with the inverse edit, not `git checkout`** --
`git checkout -- <file>` would also discard the implementation you just wrote.
Confirm with `grep -n "calls = 2 + max" src/receipts/worker.py` before moving
on.

- [ ] **Step 6: Full suite, then commit**

Run: `python -m pytest`

```bash
git add src/receipts/worker.py tests/test_worker.py
git diff --cached --stat
git commit -m "fix(worker): derive the job ceiling from the model budget (ISSUE-029)"
```

---

### Task 3: `record_progress` and the heartbeat sink

**Files:**
- Modify: `src/receipts/persist/repository.py`
- Modify: `src/receipts/pipeline.py`
- Test: `tests/test_repository.py`

**Interfaces:**
- Consumes: `Receipt.progress_stage`, `Receipt.progress_at` (Task 1).
- Produces: `record_progress(session, receipt_id, stage, *, now=None) -> None`
  in `persist/repository.py`; `_heartbeat_sink(session_factory, receipt_id) ->
  ProgressSink` in `pipeline.py`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_repository.py`.

**Pre-flighted, so use these and do not invent alternatives:** that module
provides an **`engine`** fixture (in-memory SQLite with FK enforcement, at
`:89`) — there is **no** `session_factory` fixture — and a **`_job()`** helper
at `:109` that builds a `ReceiptJob`. Use both. Inlining your own
`ReceiptJob(...)` would repeat the duplication finding Task 2 already paid for.

The module imports `uuid`, `Session`, `sa`, `ReceiptJob`,
`create_pending_receipt` and `get_receipt` already. It imports
`from datetime import date, time` but **not** `datetime` or `UTC` — extend that
existing import line rather than adding a second one.

```python
def test_record_progress_stamps_stage_and_time(engine: sa.Engine) -> None:
    job = _job()
    with Session(engine) as session:
        create_pending_receipt(session, job)
        session.commit()

    stamped = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
    with Session(engine) as session:
        record_progress(session, job.id, "extract", now=stamped)
        session.commit()

    with Session(engine) as session:
        receipt = get_receipt(session, job.id)
        assert receipt.progress_stage == "extract"
        assert receipt.progress_at is not None


def test_record_progress_overwrites_the_previous_beat(engine: sa.Engine) -> None:
    """A heartbeat is the LAST time seen alive, not a log."""
    job = _job()
    with Session(engine) as session:
        create_pending_receipt(session, job)
        session.commit()

    with Session(engine) as session:
        record_progress(session, job.id, "triage")
        session.commit()
    with Session(engine) as session:
        record_progress(session, job.id, "extract")
        session.commit()

    with Session(engine) as session:
        assert get_receipt(session, job.id).progress_stage == "extract"


def test_record_progress_does_not_commit(engine: sa.Engine) -> None:
    """ADR-0006: the caller owns the transaction.

    Rolling back after the call must lose the write. If record_progress
    committed, the stage would survive the rollback.
    """
    job = _job()
    with Session(engine) as session:
        create_pending_receipt(session, job)
        session.commit()

    with Session(engine) as session:
        record_progress(session, job.id, "extract")
        session.rollback()

    with Session(engine) as session:
        assert get_receipt(session, job.id).progress_stage is None


def test_record_progress_on_an_unknown_receipt_writes_nothing(engine: sa.Engine) -> None:
    """A heartbeat for a row that is gone is a no-op, not an error.

    Narration must never be load-bearing, and a receipt deleted mid-run is not
    a reason to take an extraction down.
    """
    with Session(engine) as session:
        record_progress(session, uuid.uuid4(), "extract")
        session.commit()
```

- [ ] **Step 2: Run them and watch them fail**

Run: `python -m pytest tests/test_repository.py -v -k record_progress`

Expected: FAIL with `NameError` / `ImportError` for `record_progress`.

Read each reason. If any passes, stop and report.

- [ ] **Step 3: Implement `record_progress`**

In `src/receipts/persist/repository.py`, beside `get_receipt`:

```python
def record_progress(
    session: Session,
    receipt_id: uuid.UUID,
    stage: str,
    *,
    now: datetime | None = None,
) -> None:
    """Stamp ``receipt_id`` as last known alive at ``stage``.

    A heartbeat, not a log: it overwrites, because the only question anyone
    asks of it is "when was this last moving". ``receipts.sweep`` reads it to
    tell a slow receipt from a stranded one.

    An unknown ``receipt_id`` writes nothing and raises nothing. Narration is
    never load-bearing, and a heartbeat is not a reason to fail a run.

    Flushes; does not commit (ADR-0006).
    """
    session.execute(
        sa_update(Receipt)
        .where(Receipt.id == receipt_id)
        .values(progress_stage=stage, progress_at=now or datetime.now(UTC))
    )
    session.flush()
```

Add whatever imports are missing at the module top -- `from sqlalchemy import
update as sa_update`, and `UTC` from `datetime`. Match the module's existing
import style; it already imports `datetime` and several sqlalchemy names.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_repository.py -v -k record_progress`
Expected: PASS, all four.

- [ ] **Step 5: Add the sink to `pipeline.py`**

Near `_stage` in `src/receipts/pipeline.py`:

```python
def _heartbeat_sink(
    session_factory: Callable[[], Session], receipt_id: uuid.UUID
) -> ProgressSink:
    """A :data:`ProgressSink` that records liveness on the receipt row.

    Its own short session per event, opened and closed around a single write.
    It deliberately does not reuse the pipeline's session: that one may be
    mid-stage or already rolled back, which is the same reason
    :func:`_persist_failure` takes a fresh one.

    It commits, because a heartbeat no other process can see is not a
    heartbeat. That is consistent with ADR-0006, which puts the transaction in
    the caller's hands -- here the sink is the caller.

    It may raise. Every call site is already guarded (:func:`_stage`,
    :func:`~receipts.extract.extractor._report`, and the best-attempt block in
    ``extract_with_repair``), so a database blip costs narration and never the
    extraction.
    """

    def sink(event: ProgressEvent) -> None:
        session = session_factory()
        try:
            record_progress(session, receipt_id, event.stage)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return sink
```

Import `record_progress` alongside the other `persist.repository` names already
imported in `pipeline.py`.

- [ ] **Step 6: Full suite, then commit**

Run: `python -m pytest`

Expected: PASS. Nothing calls `_heartbeat_sink` yet, so behaviour is unchanged.

```bash
git add src/receipts/persist/repository.py src/receipts/pipeline.py tests/test_repository.py
git diff --cached --stat
git commit -m "feat(persist): record when a run was last known alive"
```

---

### Task 4: `process_receipt` heartbeats by construction (closes ISSUE-031's signal half)

**Files:**
- Modify: `src/receipts/pipeline.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_extractor.py` (add one case -- see Step 8)

**Interfaces:**
- Consumes: `_heartbeat_sink` (Task 3).
- Produces: `fan_out(*sinks: ProgressSink | None) -> ProgressSink`; and the
  guarantee that `process_receipt` heartbeats with no `progress=` supplied.

**This is the task the design's convergence argument rests on.** ISSUE-031's
obvious fix is to add `progress=` at three more call sites; that closes the
three that exist and leaves the next one silent. Building the heartbeat inside
`process_receipt` makes a silent run unconstructible, so no enumeration of call
sites is needed and none should be written.

**The ADR-0051 hazard here:** a test that builds the sink itself and calls it
proves the *sink* works, not that `process_receipt` uses it. **The load-bearing
test below never mentions `_heartbeat_sink`.**

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pipeline.py`, reusing that module's existing fixtures for a
fake client, storage, and session factory:

```python
def test_process_receipt_heartbeats_with_no_progress_argument(
    session_factory, storage, settings
) -> None:
    """The guarantee's signal does not depend on the caller remembering.

    This test never names the sink. It calls process_receipt exactly as
    `--inline`, `reprocess` and `process_batch` do -- with no `progress=` --
    and asserts the row was stamped anyway. Deleting the sink construction
    inside process_receipt is what turns it red.
    """
    job = _ingested_job(session_factory, storage)

    process_receipt(
        job,
        client=FakeVLMClient([_ok_response()]),
        storage=storage,
        session_factory=session_factory,
        settings=settings,
    )

    with session_factory() as session:
        receipt = get_receipt(session, job.id)
        assert receipt.progress_at is not None
        assert receipt.progress_stage is not None


def test_fan_out_delivers_to_every_sink() -> None:
    seen_a: list[str] = []
    seen_b: list[str] = []
    sink = fan_out(lambda e: seen_a.append(e.stage), lambda e: seen_b.append(e.stage))
    sink(ProgressEvent(stage="extract"))
    assert seen_a == ["extract"]
    assert seen_b == ["extract"]


def test_fan_out_ignores_none_sinks() -> None:
    seen: list[str] = []
    sink = fan_out(None, lambda e: seen.append(e.stage), None)
    sink(ProgressEvent(stage="triage"))
    assert seen == ["triage"]


def test_one_raising_sink_does_not_starve_the_other() -> None:
    """The heartbeat must survive a broken Redis writer.

    This is the whole reason fan_out isolates each sink rather than letting an
    exception escape to the outer guard: if a raising narration sink stopped
    the heartbeat, a Redis outage would silently reopen the stranded-receipt
    hole this milestone exists to close.
    """
    seen: list[str] = []

    def boom(event):
        raise RuntimeError("redis is down")

    sink = fan_out(boom, lambda e: seen.append(e.stage))
    sink(ProgressEvent(stage="persist"))
    assert seen == ["persist"]
```

`_ingested_job` and `_ok_response` stand for whatever that module already uses
to build an ingested receipt and a passing fake response. **Use the module's
existing helpers; do not invent new ones.** If no such helper exists, build the
job with `ingest_bytes` the way the neighbouring tests do.

- [ ] **Step 2: Run them and watch them fail**

Run: `python -m pytest tests/test_pipeline.py -v -k "heartbeat or fan_out or raising_sink"`

Expected: the three `fan_out` tests FAIL on `NameError: name 'fan_out' is not
defined`; the heartbeat test FAILS on `assert None is not None`.

**If the heartbeat test passes, stop and report** -- that would mean something
already writes those columns, and this task's premise is wrong.

- [ ] **Step 3: Implement `fan_out`**

In `src/receipts/pipeline.py`, beside `_heartbeat_sink`:

```python
def fan_out(*sinks: "ProgressSink | None") -> ProgressSink:
    """One sink that delivers to several, isolating each from the others.

    ``None`` entries are dropped, so a caller can pass an optional sink
    without a conditional.

    **Each delivery is guarded separately, and that is load-bearing rather
    than defensive.** The worker fans out to a Redis writer and the heartbeat;
    if a broken Redis writer could abort the fan-out, an outage would stop the
    heartbeat too and silently reopen the stranded-receipt hole. Isolation is
    what keeps the guarantee independent of the narration.
    """
    live = [sink for sink in sinks if sink is not None]

    def sink(event: ProgressEvent) -> None:
        for one in live:
            try:
                one(event)
            except Exception:
                log.warning("progress sink raised; continuing", exc_info=True)

    return sink
```

- [ ] **Step 4: Build the heartbeat inside `process_receipt`**

In `process_receipt`, before the first `with _stage(...)` block, add:

```python
    # The heartbeat is built here rather than accepted from the caller: it
    # carries the terminal-state guarantee, and a guarantee a call site can
    # forget is not one. `progress` stays optional and injected because it
    # carries Redis narration, which is cosmetic and genuinely absent on the
    # no-Redis deployments.
    progress = fan_out(_heartbeat_sink(session_factory, job.id), progress)
```

Leave the `progress` parameter and its `None` default exactly as they are.

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: PASS.

- [ ] **Step 6: Prove the headline guard by mutation**

Comment out the `progress = fan_out(...)` line and run
`python -m pytest tests/test_pipeline.py -v -k heartbeat`.

Expected: `test_process_receipt_heartbeats_with_no_progress_argument` FAILS on
the `progress_at is not None` assertion.

**Revert with the inverse edit, not `git checkout`.** Confirm with
`grep -n "fan_out(_heartbeat_sink" src/receipts/pipeline.py`.

- [ ] **Step 7: Pin the spec's keystone, which nothing currently guards**

The spec's section 5.1 rests on **the largest gap between two heartbeats being
one model call**, and both the sweep's `started_cutoff` and the job ceiling are
derived from that. It holds because `extract_with_repair` calls `_report` after
the first extract, again inside the repair loop, and once more choosing the best
attempt.

**Nothing pins it.** Measured while writing this plan: `tests/test_extractor.py`
holds 28 tests and the word `progress` appears in it **zero** times, so no test
passes a sink to `extract_with_repair` at all. Deleting the `_report` call
inside the repair loop would collapse the heartbeat to stage entry only --
cold for tens of minutes of ordinary work, so the sweep would start marking
live runs as stranded -- and the whole suite would stay green.

Add to `tests/test_extractor.py`, in its "The repair loop" section:

```python
def test_the_repair_loop_reports_every_attempt():
    """The keystone the sweep threshold and the job ceiling both rest on.

    Extract dominates a receipt, so if it narrated only on stage entry the
    heartbeat would go cold during entirely normal work and the sweep would
    presume a live run dead. Three reports: the first attempt, the repair, and
    the best-attempt choice.
    """
    seen: list[str | None] = []
    client = FakeVLMClient([broken(), good()])
    extract_with_repair(IMG, client, ctx=CTX, progress=lambda e: seen.append(e.detail))
    assert len(seen) == 3
    assert "attempt 1" in seen[0]
    assert "attempt 2" in seen[1]
    assert "kept attempt" in seen[2]
```

Run: `python -m pytest tests/test_extractor.py -v -k reports_every_attempt`
Expected: PASS immediately -- this pins behaviour that already exists.

**Then prove it can fail**, or it is not a pin: comment out the
`_report(progress, attempts)` call **inside the `for round_index` loop** (not
the one above it) and re-run. Expect FAIL on `len(seen) == 3` with 2. Revert
with the inverse edit and confirm both calls are present with
`grep -c "_report(progress, attempts)" src/receipts/extract/extractor.py`,
which must print `2`.

- [ ] **Step 8: Full suite, then commit**

Run: `python -m pytest`

Expected: PASS. Every existing caller now writes about ten rows per receipt
where it wrote none; the suite's session factories are file-backed SQLite and
handle this. **If a test fails on session nesting or a locked database, stop
and report** -- the spec flags that as a predicted trap worth a real pin.

```bash
git add src/receipts/pipeline.py tests/test_pipeline.py tests/test_extractor.py
git diff --cached --stat
git commit -m "feat(pipeline): a run cannot be constructed without a heartbeat"
```

---

### Task 5: The sweep (closes ISSUE-030)

**Files:**
- Modify: `src/receipts/persist/repository.py`
- Create: `src/receipts/sweep.py`
- Test: `tests/test_sweep.py` (create)

**Interfaces:**
- Consumes: Task 1's columns; `enqueue_review`, `redact_pan`, `get_receipt`.
- Produces: `find_stranded(session, *, started_cutoff, unstarted_cutoff) ->
  list[Receipt]` in `repository.py`; `strand_receipt(session, receipt) ->
  bool` and `sweep_stranded(session_factory, *, settings, now=None,
  dry_run=False) -> list[uuid.UUID]` in `sweep.py`.

**`sweep.py` must not import `receipts.pipeline` or `receipts.worker`.** See
Global Constraints. If you find yourself needing `STAGES` or
`job_timeout_for`, stop and report rather than adding the import.

**On concurrency, stated precisely rather than overclaimed.** The spec's
section 6.5 describes the re-entrancy guard as a conditional `UPDATE ... WHERE
id = :id AND status = 'pending'`. What `strand_receipt` below actually does is
check the status **in Python** before writing. These are not equivalent: two
processes could each load the row, each see `PENDING`, and each write. The
outcome is still benign -- both write the *same* status, and `enqueue_review`
is idempotent on a UNIQUE `receipt_id`, so the row and the task converge -- but
the test added here (`test_sweeping_twice_opens_one_task_not_two`) is
**sequential and pins only the sequential case**. Do not write a docstring or a
comment claiming this is race-proof. If a genuinely concurrent guarantee is
wanted later, that is a conditional UPDATE and its own test, and it is not in
this plan.

- [ ] **Step 1: Write the six-shape fixture and the failing tests**

Create `tests/test_sweep.py`. The fixture is the point: a mutation kills nothing
when the discriminating case is in none of the supplied tests, so **every test
below runs against a database holding all six shapes.**

```python
"""The terminal-state sweep.

Every test here runs against a fixture holding all six shapes at once --
stranded-started, warm-started, old-never-started, recent-never-started, a
terminal row, and a reviewed row. A fixture of only stranded rows would stay
green with the entire progress_at clause deleted, which is the shape that has
produced surviving mutants on this project before.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from config.settings import Settings
from receipts.ingest.ingest import ReceiptJob
from receipts.persist.models import Base, ReviewTask
from receipts.persist.repository import create_pending_receipt, get_receipt
from receipts.persist.session import make_engine, make_session_factory
from receipts.score.confidence import ReceiptStatus
from receipts.sweep import sweep_stranded

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


@pytest.fixture
def session_factory(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'receipts.db').as_posix()}")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)


def _job() -> ReceiptJob:
    return ReceiptJob(
        id=uuid.uuid4(), image_key="k", source="t",
        original_filename="r.jpg", content_type="image/jpeg",
    )


def _make(session, *, status, progress_at, created_at, stage="extract"):
    job = _job()
    receipt = create_pending_receipt(session, job)
    receipt.status = status
    receipt.progress_at = progress_at
    receipt.created_at = created_at
    receipt.progress_stage = stage if progress_at is not None else None
    session.flush()
    return job.id


@pytest.fixture
def six_shapes(session_factory):
    """All six, keyed by name. Cutoffs used by the tests: started 30m, unstarted 6h."""
    ids: dict[str, uuid.UUID] = {}
    with session_factory() as session:
        ids["stranded_started"] = _make(
            session, status=ReceiptStatus.PENDING,
            progress_at=NOW - timedelta(hours=2), created_at=NOW - timedelta(hours=3),
        )
        ids["warm_started"] = _make(
            session, status=ReceiptStatus.PENDING,
            progress_at=NOW - timedelta(minutes=1), created_at=NOW - timedelta(hours=3),
        )
        ids["old_never_started"] = _make(
            session, status=ReceiptStatus.PENDING,
            progress_at=None, created_at=NOW - timedelta(days=2),
        )
        ids["recent_never_started"] = _make(
            session, status=ReceiptStatus.PENDING,
            progress_at=None, created_at=NOW - timedelta(hours=1),
        )
        ids["terminal"] = _make(
            session, status=ReceiptStatus.AUTO_APPROVED,
            progress_at=NOW - timedelta(hours=5), created_at=NOW - timedelta(hours=6),
        )
        ids["reviewed"] = _make(
            session, status=ReceiptStatus.REVIEWED,
            progress_at=NOW - timedelta(hours=5), created_at=NOW - timedelta(hours=6),
        )
        session.commit()
    return ids


def _settings() -> Settings:
    return Settings(_env_file=None, vlm_timeout_s=600, max_repair_attempts=1)


def test_a_stranded_receipt_reaches_needs_review(session_factory, six_shapes) -> None:
    swept = sweep_stranded(session_factory, settings=_settings(), now=NOW)
    assert six_shapes["stranded_started"] in swept
    with session_factory() as session:
        receipt = get_receipt(session, six_shapes["stranded_started"])
        assert receipt.status is ReceiptStatus.NEEDS_REVIEW


def test_the_reason_names_the_stage_it_died_in(session_factory, six_shapes) -> None:
    sweep_stranded(session_factory, settings=_settings(), now=NOW)
    with session_factory() as session:
        task = session.query(ReviewTask).filter(
            ReviewTask.receipt_id == six_shapes["stranded_started"]
        ).one()
        assert "extract" in task.reason


def test_a_warm_receipt_is_left_alone(session_factory, six_shapes) -> None:
    """Slow is not stranded. This is what the heartbeat bought."""
    swept = sweep_stranded(session_factory, settings=_settings(), now=NOW)
    assert six_shapes["warm_started"] not in swept
    with session_factory() as session:
        assert get_receipt(session, six_shapes["warm_started"]).status is ReceiptStatus.PENDING


def test_a_receipt_that_never_started_is_swept_once_it_is_old(
    session_factory, six_shapes
) -> None:
    swept = sweep_stranded(session_factory, settings=_settings(), now=NOW)
    assert six_shapes["old_never_started"] in swept


def test_a_recently_queued_receipt_is_not_swept(session_factory, six_shapes) -> None:
    """A backlog is not a strand.

    This is the case that makes the two thresholds necessary: with one
    threshold, a healthy receipt waiting behind a queue would be marked
    needs_review while the worker was still going to process it.
    """
    swept = sweep_stranded(session_factory, settings=_settings(), now=NOW)
    assert six_shapes["recent_never_started"] not in swept


def test_a_terminal_receipt_is_never_touched(session_factory, six_shapes) -> None:
    swept = sweep_stranded(session_factory, settings=_settings(), now=NOW)
    assert six_shapes["terminal"] not in swept
    with session_factory() as session:
        assert get_receipt(session, six_shapes["terminal"]).status is ReceiptStatus.AUTO_APPROVED


def test_a_reviewed_receipt_is_never_touched(session_factory, six_shapes) -> None:
    """A machine run never overwrites a reviewed row.

    Structural here: `reviewed` is excluded by the same status='pending'
    clause that selects the work, so there is no second rule that could drift
    out of agreement with the selection.
    """
    swept = sweep_stranded(session_factory, settings=_settings(), now=NOW)
    assert six_shapes["reviewed"] not in swept
    with session_factory() as session:
        assert get_receipt(session, six_shapes["reviewed"]).status is ReceiptStatus.REVIEWED


def test_sweeping_twice_opens_one_task_not_two(session_factory, six_shapes) -> None:
    sweep_stranded(session_factory, settings=_settings(), now=NOW)
    second = sweep_stranded(session_factory, settings=_settings(), now=NOW)
    assert second == []
    with session_factory() as session:
        tasks = session.query(ReviewTask).filter(
            ReviewTask.receipt_id == six_shapes["stranded_started"]
        ).all()
        assert len(tasks) == 1


def test_dry_run_reports_without_writing(session_factory, six_shapes) -> None:
    swept = sweep_stranded(session_factory, settings=_settings(), now=NOW, dry_run=True)
    assert six_shapes["stranded_started"] in swept
    with session_factory() as session:
        assert get_receipt(session, six_shapes["stranded_started"]).status is ReceiptStatus.PENDING
```

- [ ] **Step 2: Run them and watch them fail**

Run: `python -m pytest tests/test_sweep.py -v`

Expected: every test FAILS at collection with
`ModuleNotFoundError: No module named 'receipts.sweep'`.

- [ ] **Step 3: Add `find_stranded` to the repository**

In `src/receipts/persist/repository.py`:

```python
def find_stranded(
    session: Session,
    *,
    started_cutoff: datetime,
    unstarted_cutoff: datetime,
) -> list[Receipt]:
    """Pending receipts whose processing has stopped, on either of two clocks.

    Two thresholds because there are two failure modes, not one. A receipt that
    *started* and went cold is stranded within about one model call. A receipt
    with no heartbeat at all is ambiguous -- it may have been enqueued and be
    waiting behind a backlog, which is healthy -- so it needs a much longer
    clock, and nothing on the row can tell the two apart without asking Redis.

    ``status == PENDING`` is the whole safety story: every terminal status,
    ``reviewed`` included, is excluded by the same clause that selects the
    work, so no second rule can drift out of agreement with this one.

    A pure read. The caller decides what to do with the rows.
    """
    return list(
        session.scalars(
            select(Receipt).where(
                Receipt.status == ReceiptStatus.PENDING,
                or_(
                    and_(
                        Receipt.progress_at.is_not(None),
                        Receipt.progress_at < started_cutoff,
                    ),
                    and_(
                        Receipt.progress_at.is_(None),
                        Receipt.created_at < unstarted_cutoff,
                    ),
                ),
            )
        )
    )
```

Add `and_` to the module's existing `from sqlalchemy import or_, select`.

- [ ] **Step 4: Write `src/receipts/sweep.py`**

```python
"""Bring interrupted receipts to a terminal state.

The terminal-state guarantee -- *every receipt reaches a terminal state* -- is
carried in the pipeline by normal return and by exception handling. **An
interruption is neither.** A SIGKILLed work-horse raises nothing in its own
process, and a CLI run that is simply stopped runs no handler at all, so no
amount of ``try``/``except`` anywhere can close this. Something that *survives*
has to notice, and it has to do so without knowing which runner died.

That is why this module reads the receipt row rather than the queue: a reaper
keyed on RQ would cover exactly one of the four ways a receipt is processed.

**Imports are deliberately narrow.** This module is imported by both the CLI
and the review API, and ``receipts.pipeline`` pulls in the optional ``pipeline``
extra. Importing it here would drag that extra into every command, which is the
trap ``cli.py`` documents above ``cmd_process``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Callable

from sqlalchemy.orm import Session

from config.settings import Settings

from .persist.models import Receipt
from .persist.repository import find_stranded, redact_pan
from .review.queue import enqueue_review
from .score.confidence import ReceiptStatus

__all__ = ["STRAND_MARGIN", "strand_receipt", "sweep_stranded"]

log = logging.getLogger(__name__)

#: HTTP attempts per model call -- the SDK's default ``max_retries`` of 2 plus
#: the initial attempt (ADR-0047 decision 8). Duplicated from
#: ``receipts.worker`` rather than imported: importing the worker here would
#: drag the optional extras this module exists to avoid. ``test_sweep.py`` pins
#: the two against each other so they cannot drift.
_SDK_ATTEMPTS = 3

#: How much longer than one model call a run may be silent before it is
#: presumed stranded. Multiplicative, not additive: the risk of sweeping a live
#: run scales with how long a legitimate call can take.
STRAND_MARGIN = 2

#: How much longer than a whole receipt a *never-started* row may sit before it
#: is presumed dropped. Deliberately generous: a receipt queued behind a
#: backlog looks exactly like one that was never enqueued, and marking a
#: healthy queued receipt is worse than noticing a dropped one late.
UNSTARTED_MARGIN = 12

#: Same urgency a failed stage gets. An interrupted receipt is not a lesser
#: problem than a broken one.
_STRANDED_PRIORITY = 1


def _cutoffs(settings: Settings, now: datetime) -> tuple[datetime, datetime]:
    """The two clocks, both derived from one model call.

    Deriving both from the same quantity is what stops the sweep and the job
    ceiling disagreeing about what "too long" means.
    """
    one_call = settings.vlm_timeout_s * _SDK_ATTEMPTS
    calls = 2 + max(0, settings.max_repair_attempts)
    started = now - timedelta(seconds=one_call * STRAND_MARGIN)
    unstarted = now - timedelta(seconds=one_call * calls * UNSTARTED_MARGIN)
    return started, unstarted


def strand_receipt(session: Session, receipt: Receipt) -> bool:
    """Land one interrupted receipt in ``needs_review``. Flushes; does not commit.

    Returns whether it changed anything, so a concurrent sweeper that lost the
    race reports nothing rather than reporting a receipt it did not move.

    Follows :func:`receipts.pipeline._persist_failure`'s convention -- the
    stage named in the reason, a review task opened at the same urgency -- but
    is a sibling rather than a caller: that function needs a ``_StageFailure``,
    a ``ReceiptJob`` and a phash, and a sweep has a row.
    """
    if receipt.status is not ReceiptStatus.PENDING:
        return False
    stage = receipt.progress_stage or "before any stage reported"
    reason = redact_pan(f"processing was interrupted at {stage} and never resumed")
    receipt.status = ReceiptStatus.NEEDS_REVIEW
    enqueue_review(session, receipt.id, reason, _STRANDED_PRIORITY)
    session.flush()
    return True


def sweep_stranded(
    session_factory: Callable[[], Session],
    *,
    settings: Settings,
    now: datetime | None = None,
    dry_run: bool = False,
) -> list[uuid.UUID]:
    """Bring every stranded receipt to a terminal state. Returns what moved.

    ``dry_run`` reports what *would* move and writes nothing: a command that
    marks receipts should be inspectable before it is trusted.
    """
    now = now or datetime.now(UTC)
    started_cutoff, unstarted_cutoff = _cutoffs(settings, now)
    moved: list[uuid.UUID] = []
    session = session_factory()
    try:
        for receipt in find_stranded(
            session, started_cutoff=started_cutoff, unstarted_cutoff=unstarted_cutoff
        ):
            if dry_run:
                moved.append(receipt.id)
            elif strand_receipt(session, receipt):
                moved.append(receipt.id)
                log.warning("receipt %s was stranded; sent to review", receipt.id)
        if dry_run:
            session.rollback()
        else:
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return moved
```

- [ ] **Step 5: Add the drift pin between the two `_SDK_ATTEMPTS`**

Append to `tests/test_sweep.py`:

```python
def test_the_two_attempt_constants_cannot_drift() -> None:
    """sweep.py duplicates worker.py's _SDK_ATTEMPTS to keep its imports narrow.

    A duplicated constant is a second source, so it is pinned rather than
    trusted. Importing worker here is fine: this is a test, not the module.
    """
    from receipts import sweep, worker

    assert sweep._SDK_ATTEMPTS == worker._SDK_ATTEMPTS
```

- [ ] **Step 6: Run the module**

Run: `python -m pytest tests/test_sweep.py -v`
Expected: PASS, all ten.

- [ ] **Step 7: Prove three guards by mutation, one at a time**

Run each mutation, confirm the expected test reddens, then **revert with the
inverse edit** and confirm with `grep` before the next one.

1. In `find_stranded`, delete the `Receipt.status == ReceiptStatus.PENDING`
   clause. Expect `test_a_reviewed_receipt_is_never_touched` **and**
   `test_a_terminal_receipt_is_never_touched` to FAIL. Two tests from one
   mutation is the structural claim being demonstrated, not a redundancy.
2. In `find_stranded`, change the never-started branch's `Receipt.created_at <
   unstarted_cutoff` to `Receipt.created_at < started_cutoff` -- collapsing the
   two thresholds. Expect `test_a_recently_queued_receipt_is_not_swept` to FAIL.
3. In `strand_receipt`, delete the `if receipt.status is not
   ReceiptStatus.PENDING: return False` guard. Expect
   `test_sweeping_twice_opens_one_task_not_two` to FAIL on `second == []`.

**A mutation that does not compile proves nothing.** If any of these produces a
`SyntaxError` or an import error rather than an assertion failure, the mutation
was malformed -- fix the mutation, not the test.

- [ ] **Step 8: Full suite, then commit**

Run: `python -m pytest`

```bash
git add src/receipts/persist/repository.py src/receipts/sweep.py tests/test_sweep.py
git diff --cached --stat
git commit -m "feat(sweep): an interrupted receipt reaches a terminal state (ISSUE-030)"
```

---

### Task 6: `receipts sweep`

**Files:**
- Modify: `src/receipts/cli.py`
- Test: `tests/test_cli_core.py`

**Interfaces:**
- Consumes: `sweep_stranded` (Task 5).
- Produces: the `sweep` subcommand and `cmd_sweep(args, *, session_factory,
  settings) -> int`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli_core.py`, matching how that module already invokes the
CLI (via `main([...])` or `build_parser()`):

```python
def test_sweep_is_a_registered_command() -> None:
    args = build_parser().parse_args(["sweep"])
    assert args.command == "sweep"
    assert args.dry_run is False


def test_sweep_accepts_dry_run() -> None:
    args = build_parser().parse_args(["sweep", "--dry-run"])
    assert args.dry_run is True


def test_cmd_sweep_reports_nothing_to_do(session_factory, capsys) -> None:
    args = build_parser().parse_args(["sweep"])
    code = cmd_sweep(
        args, session_factory=session_factory, settings=Settings(_env_file=None)
    )
    assert code == 0
    assert "0" in capsys.readouterr().out
```

**Pre-flighted:** `tests/test_cli_core.py` has `session_factory`, `storage` and
`tty_stdin` fixtures and **no `settings` fixture**. Its established pattern is
`Settings(_env_file=None)` constructed inline at the call site, which is what
the test above follows. `Settings` is already imported in that module.

- [ ] **Step 2: Run them and watch them fail**

Run: `python -m pytest tests/test_cli_core.py -v -k sweep`

Expected: FAIL. The parser tests fail with a `SystemExit` from argparse
(`invalid choice: 'sweep'`); `test_cmd_sweep_reports_nothing_to_do` fails on
`NameError`.

Note that argparse raises `SystemExit`, not an assertion error -- that is the
correct reason here, not a defect.

- [ ] **Step 3: Register the parser**

In `src/receipts/cli.py`, beside `_add_calibrate`:

```python
def _add_sweep(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "sweep",
        help="bring interrupted receipts to a terminal state",
        description=(
            "Find receipts whose processing stopped without reaching a "
            "terminal status and send them to review. An interruption -- a "
            "timeout, a container restart, an operator's Ctrl-C -- runs no "
            "handler in the process it kills, so nothing inside a run can "
            "close this; something that survives has to notice. Run it on a "
            "schedule. `--dry-run` reports what would move and writes nothing."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be swept without writing anything",
    )
```

Add `_add_sweep(sub)` to `build_parser()`, after `_add_calibrate(sub)`.

- [ ] **Step 4: Add the handler and dispatch**

Beside the other `cmd_` functions:

```python
def cmd_sweep(args: argparse.Namespace, *, session_factory, settings: Settings) -> int:
    """Bring interrupted receipts to a terminal state.

    Imported inside the body so `receipts sweep` costs no import for every
    other command, matching how this module treats the queue.
    """
    from .sweep import sweep_stranded

    moved = sweep_stranded(session_factory, settings=settings, dry_run=args.dry_run)
    verb = "would send" if args.dry_run else "sent"
    print(f"{verb} {len(moved)} stranded receipt(s) to review")
    for receipt_id in moved:
        print(f"  {receipt_id}")
    return 0
```

In `main`, beside the other dispatch branches:

```python
        if args.command == "sweep":
            return cmd_sweep(args, session_factory=session_factory, settings=settings)
```

Add `"cmd_sweep"` to `__all__` alongside `"cmd_process"` and `"cmd_reprocess"`.

- [ ] **Step 5: Run the tests, then the full suite**

Run: `python -m pytest tests/test_cli_core.py -v -k sweep`, then `python -m pytest`
Expected: PASS.

- [ ] **Step 6: Run it for real, from outside the repository**

A green suite is not evidence that an entry point works.

```bash
cd .. && python -m receipts.cli sweep --dry-run ; cd -
```

Expected: exits 0 and prints `would send 0 stranded receipt(s) to review`
against whatever database is configured. If it raises on import, **stop and
report** -- that is the class of defect a green suite has twice missed here.

- [ ] **Step 7: Commit**

```bash
git add src/receipts/cli.py tests/test_cli_core.py
git diff --cached --stat
git commit -m "feat(cli): receipts sweep, the runner that bears the guarantee"
```

---

### Task 7: The progress route falls back and sweeps its own row

**Files:**
- Modify: `src/receipts/review/api.py`
- Test: `tests/test_api_read.py`

**Interfaces:**
- Consumes: `sweep_stranded`, Task 1's columns.
- Produces: no new names; changed behaviour of
  `GET /receipts/{receipt_id}/progress`.

Two changes to one route: report the row's stage when Redis has nothing
(closing ISSUE-031's reader half), and sweep **this row only** if it is pending
and cold (giving the guarantee a latency a waiting screen can live with).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_api_read.py`, using that module's existing app-building and
auth fixtures:

```python
def test_progress_falls_back_to_the_row_when_redis_is_silent(client, session_factory):
    """--inline narrates too. This is ISSUE-031's reader half."""
    receipt_id = _pending_receipt(session_factory, progress_stage="triage")
    response = client.get(f"/receipts/{receipt_id}/progress")
    assert response.status_code == 200
    assert response.json()["stage"] == "triage"


def test_a_live_reader_still_wins_over_the_row(client, session_factory):
    """The fallback must not shadow the queue path's narration."""
    receipt_id = _pending_receipt(session_factory, progress_stage="triage")
    client.app.state.read_progress = lambda _id: ProgressEvent(stage="extract", detail="d")
    response = client.get(f"/receipts/{receipt_id}/progress")
    assert response.json()["stage"] == "extract"
    assert response.json()["detail"] == "d"


def test_reading_progress_sweeps_a_cold_receipt(client, session_factory):
    """The screen stops polling forever, which is ISSUE-030's visible symptom."""
    receipt_id = _pending_receipt(
        session_factory, progress_stage="extract", progress_at=_long_ago()
    )
    response = client.get(f"/receipts/{receipt_id}/progress")
    assert response.json()["status"] == "needs_review"


def test_reading_progress_does_not_sweep_other_rows(client, session_factory):
    """Single-row only: a GET must not become a table scan or a bulk write."""
    warm = _pending_receipt(session_factory, progress_stage="extract")
    cold = _pending_receipt(
        session_factory, progress_stage="extract", progress_at=_long_ago()
    )
    other_cold = _pending_receipt(
        session_factory, progress_stage="extract", progress_at=_long_ago()
    )
    client.get(f"/receipts/{cold}/progress")
    with session_factory() as session:
        assert get_receipt(session, other_cold).status is ReceiptStatus.PENDING
        assert get_receipt(session, warm).status is ReceiptStatus.PENDING
```

Write `_pending_receipt(...)` and `_long_ago()` as module-level helpers in that
test file, following its existing helper style.

- [ ] **Step 2: Run them and watch them fail**

Run: `python -m pytest tests/test_api_read.py -v -k "progress"`

Expected: the fallback test FAILS on `stage` being `None`; the sweep test FAILS
on `status` still being `"pending"`. `test_a_live_reader_still_wins_over_the_row`
and `test_reading_progress_does_not_sweep_other_rows` are **expected to pass
already** -- they pin behaviour that is currently correct and must stay correct.
That is not a defect; it is what makes them regression guards rather than
feature tests.

- [ ] **Step 3: Change the route**

In `get_receipt_progress`, replace the body's session block and return with:

```python
        with request.app.state.session_factory() as session:
            receipt = get_receipt(session, receipt_id)
            if receipt is None:
                raise HTTPException(
                    status_code=404, detail=f"no receipt with id {receipt_id}"
                )
            # Sweep this one row if it has gone cold. Single-row on purpose: a
            # table-wide sweep on a GET would put unbounded work on a request
            # path. The command in `receipts sweep` is what covers receipts
            # nobody is looking at; this is only the latency for one that
            # somebody is waiting on.
            try:
                strand_if_cold(session, receipt, settings=request.app.state.settings)
                session.commit()
            except Exception:
                session.rollback()
                logger.warning(
                    "could not sweep receipt %s while reading progress", receipt_id,
                    exc_info=True,
                )
            status = receipt.status.value if receipt.status else None
            row_stage = receipt.progress_stage
        try:
            event = request.app.state.read_progress(receipt_id)
        except Exception:
            logger.warning(
                "could not read progress for %s; reporting none", receipt_id, exc_info=True
            )
            event = None
        return {
            "status": status,
            # The live reader wins; the row is the fallback, which is what lets
            # a no-Redis deployment narrate at all (ISSUE-031).
            "stage": event.stage if event else row_stage,
            "detail": event.detail if event else None,
        }
```

Add `strand_if_cold` to `src/receipts/sweep.py`:

```python
def strand_if_cold(
    session: Session,
    receipt: Receipt,
    *,
    settings: Settings,
    now: datetime | None = None,
) -> bool:
    """Strand one already-loaded receipt if its heartbeat has gone cold.

    The single-row counterpart of :func:`sweep_stranded`, for a caller that has
    the row and the session in hand and must not pay for a table scan.
    Flushes; does not commit.
    """
    now = now or datetime.now(UTC)
    started_cutoff, unstarted_cutoff = _cutoffs(settings, now)
    if receipt.status is not ReceiptStatus.PENDING:
        return False
    if receipt.progress_at is not None:
        cold = receipt.progress_at < started_cutoff
    else:
        cold = receipt.created_at < unstarted_cutoff
    return strand_receipt(session, receipt) if cold else False
```

Add `"strand_if_cold"` to that module's `__all__`. Import it in `api.py` at
module top -- `sweep.py`'s imports are narrow by design, so this costs the API
no optional extra.

**If `request.app.state.settings` does not exist**, stop and report rather than
inventing an attribute; check how the route's neighbours reach settings and
follow that.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_api_read.py -v -k progress`
Expected: PASS, all four.

- [ ] **Step 5: Prove both halves by mutation**

1. Change `event.stage if event else row_stage` back to `event.stage if event
   else None`. Expect the fallback test to FAIL.
2. Delete the `strand_if_cold(...)` call. Expect
   `test_reading_progress_sweeps_a_cold_receipt` to FAIL.

Revert each with the inverse edit and confirm by `grep` before continuing.

- [ ] **Step 6: Full suite, then commit**

Run: `python -m pytest`

```bash
git add src/receipts/review/api.py src/receipts/sweep.py tests/test_api_read.py
git diff --cached --stat
git commit -m "feat(api): progress reports the row, and sweeps the row it reports on"
```

---

## Close

- [ ] **Run the gate runner**

Run: `python scripts/verify.py` -- **background it**, it exceeds a two-minute
tool timeout, and **do not edit source or tests while it runs**: a backgrounded
run during an edit has reported a phantom `FAIL build` here before.

Expected: all five PASS.

- [ ] **Update `docs/KNOWN_ISSUES.md`**

Mark ISSUE-029, ISSUE-030 and ISSUE-031 resolved, each citing the commit that
closed it. Leave every other entry alone. Do **not** touch
`docs/MEMORY.md` or `docs/NEXT_SESSION_PROMPT.md` in that commit -- the handoff
pair goes last and alone (ADR-0033), and bundling them makes the pair's own
freshness check report itself stale.

- [ ] **Write the ADR**

The five rulings in the spec's section 3 are load-bearing and an ADR is the
tracked-tree record of them. Follow the numbering in `docs/adr/README.md` and
add its index row in the same commit as the ADR.

- [ ] **Whole-branch review, then the close**

Whole-branch review on the strongest model, one fix wave, one scoped
re-review, then a fast-forward merge. **Every review this project has run has
found something real**, and the five gates were green on all of them.

---

## What this plan does not do

- **It does not run the join.** `worker -> Redis -> route -> screen` stays
  unexercised because `redis` is not installed here. The database path is now
  testable end to end offline, which is more than existed before, but the
  Redis path is not, and no task here claims otherwise.
- **It does not look at the screen.** jsdom lays nothing out and Vitest sets
  `css: false`, so nobody will have seen an `--inline` receipt narrate. That is
  a browser pass, not a test.
- **It does not land the compose `VLM_*` env.** That change is uncommitted and
  stays uncommitted; the spec's section 8.6 flags that its
  `VLM_TIMEOUT_S: "3600"` implies a nine-hour derived ceiling, which is worth
  revisiting before it lands.
- **It does not set the SDK's `max_retries`.** It asserts the default instead.
  Setting it changes retry behaviour and remains ADR-0047's open question.
