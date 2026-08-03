# Failure-Egress Redaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** No raw model text leaves the process in a failure — the reason
carrier, the failure log, SQLAlchemy error text, and the CLI's uncontained
print are all redacted, per ADR-0022.

**Architecture:** Four point edits at the egresses, one task each, zero
control-flow change: `_persist_failure` redacts `str(failure)` before
truncating (covers CLI stdout, RQ's Redis result store, and every future
`ProcessResult.reason` consumer); the failure log logs the redacted text plus
a rendered-and-redacted traceback instead of `exc_info`; `make_engine` passes
`hide_parameters=True`; `cmd_process`'s failed-job line prints through
`redact_pan`. Producers and `enqueue_review`'s own sink redaction stay
untouched.

**Tech Stack:** Python 3.14, SQLAlchemy 2.x, pytest (stdlib `traceback`,
pytest's `caplog`/`capsys`).

**Design doc:** `docs/superpowers/specs/2026-08-03-failure-egress-redaction-design.md`
**Decision record:** `docs/adr/0022-failure-egress-redaction.md` (already
committed on this branch)

## Global Constraints

- **A full PAN is never persisted.** Nothing here may touch `_PAN_RE`,
  `_mask_pan`, `redact_pan`'s body, the §18 blanket pass in
  `save_extraction`, or `src/receipts/review/queue.py`. This branch only
  **calls** `redact_pan` at new sites.
- **Zero control-flow change.** Every edit replaces text with redacted text
  on an existing path. ADR-0011's terminal-state semantics, ADR-0006's raise
  convention, `_MAX_REASON_CHARS`, `STAGES`, and `route()`'s reason strings
  are byte-identical after this branch.
- **`Decimal` on the money path, never `float`** (ADR-0001). Nothing here
  touches money.
- **Two test suites**; `python -m pytest` stays offline and Node-free. No
  frontend file moves, so Vitest must stay untouched at its current count.
- **Piped pytest output can lose its final summary line** — use
  `--junitxml` and read counts from the XML. Delete junit files after
  reading (PowerShell `Remove-Item var/<file>.xml` — the hook false-blocks
  `rm` under the repo).
- Lint is `python -m ruff check .` — bare `ruff` is not on PATH.
- **Every failing-capable test is proven to fail with exactly its own
  guarantee reverted** (review standards 2–4); one variable per revert.
- **Volatile numbers never go in code comments or docstrings** (review
  standard 5). PAN literals and their masks inside test bodies are fixture
  values, not measurements — those are fine.
- **Stage only the files your task names.** Never stage anything under
  `var/`, `.superpowers/`, `.kiro/`, `.github/`, `eval/golden/images/`. Do
  not push. Do not touch `docs/MEMORY.md` or `docs/NEXT_SESSION_PROMPT.md`.
- The Grep TOOL mangles `/` in content output in this environment — verify
  slash-sensitive claims with Read, `git grep` via Bash, or by executing.

## File Structure

| File | Responsibility in this change |
|---|---|
| `src/receipts/pipeline.py` | Tasks 1–2: the two-line reason mint and the rewritten `log.warning` in `_persist_failure`; `redact_pan` joins the `.persist.repository` import block, `traceback` joins the stdlib imports. |
| `src/receipts/persist/session.py` | Task 3: `hide_parameters=True` on the one `create_engine` call. |
| `src/receipts/cli.py` | Task 4: the failed-job print at the end of `cmd_process`'s inline loop; `redact_pan` joins the `.persist.repository` import. |
| `tests/test_process_receipt.py` | Tasks 1–2: the carrier test and the log test, mirroring the existing reviewed-race test's setup. |
| `tests/test_repository.py` | Task 3: the engine-error test. |
| `tests/test_cli_pipeline.py` | Task 4: the uncontained-print test, mirroring the existing inline-containment test's driver. |

No new files. No new dependencies. Task 2 depends on Task 1 (it consumes the
`redacted` local); Tasks 3 and 4 are independent of everything else.

---

### Task 1: Redact the reason at its minting point

**Files:**
- Modify: `src/receipts/pipeline.py` — line 761 (the reason mint in
  `_persist_failure`) and the `.persist.repository` import block at 62–69
- Test: `tests/test_process_receipt.py` (append after
  `test_a_garbage_currency_never_reaches_the_bounded_column`)

**Interfaces:**
- Consumes: `redact_pan(value: Any) -> Any` from
  `receipts.persist.repository` (str in → str out, PAN-shaped runs masked);
  `_truncate(text: str, limit: int) -> str`; `_MAX_REASON_CHARS = 400`.
- Produces: a local `redacted: str` bound in `_persist_failure` **before**
  the `log.warning` call — **Task 2 consumes this exact name**; and a
  `ProcessResult.reason` that is redacted for every consumer (CLI stdout at
  `cli.py:857/:957/:960`, `result_to_payload` at `worker.py:122`).

- [ ] **Step 1: Read the real code before changing it**

Read `src/receipts/pipeline.py` lines 740–800 (`_persist_failure` in full),
62–69 (the `.persist.repository` import block), 103–105
(`_MAX_REASON_CHARS`), 356–358 (`_StageFailure.__init__`), 844–845
(`_truncate`). Read `tests/test_process_receipt.py` lines 140–270 (the
`_job`/`_Client`/`_triage`/`_good`/`_run` helpers and the module's import
block) and lines 580–640 (the reviewed-race test whose setup this task's
test mirrors: `create_pending_receipt` + `apply_corrections` +
`_run` with a scripted client). Read design §1–§2.1 and §4. **Stop
condition:** if line 761 is not
`reason = _truncate(str(failure), _MAX_REASON_CHARS)` or the race test's
setup differs from what Step 2 mirrors, stop and report instead of adapting.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_process_receipt.py`:

```python
def test_a_failed_run_never_leaks_raw_model_text_through_its_reason(
    session_factory, storage, settings
):
    """What escapes a failed run is redacted at the carrier, not just the DB sink.

    The reviewed-row guard quotes ``merchant.name`` raw into its
    ``ValueError`` (that is recorded policy -- the review task should say
    what the refused run produced), and ``_persist_failure`` used to hand
    that text to ``ProcessResult.reason`` unredacted -- from where it reached
    CLI stdout and RQ's result store, while only ``review_tasks.reason`` was
    covered. Two PANs in one value (review standard 9): a scanner's failure
    mode lives between two hits.
    """
    job = _job(storage)
    with session_factory() as session:
        create_pending_receipt(session, job)
        session.commit()
    with session_factory() as session:
        apply_corrections(
            session, job.id, {"totals": {"total": "999.99"}}, corrected_by="alice"
        )

    bad = _good()
    bad.merchant.name = "SUPERMART 4111111111111111 AND 5555555555554444"

    result = _run(job, _Client([_triage(), bad]), session_factory, storage, settings)

    assert result.failed_stage == "persist"
    assert "************1111" in result.reason
    assert "************4444" in result.reason
    assert "4111111111111111" not in result.reason
    assert "5555555555554444" not in result.reason
    assert len(result.reason) <= _MAX_REASON_CHARS
```

Add to the module's import block only what is missing (check first):
`_MAX_REASON_CHARS` alongside the module's existing `receipts.pipeline`
imports. `create_pending_receipt` and `apply_corrections` are already
imported (the race test uses them); do not re-import.

- [ ] **Step 3: Run it and confirm the RED is the right RED**

```
python -m pytest tests/test_process_receipt.py -k "never_leaks_raw_model_text" -q
```

Expected: **FAILS** at `assert "************1111" in result.reason` — the
reason today carries the raw PANs and no masks. If it fails anywhere else
(setup error, wrong stage), stop and report.

- [ ] **Step 4: Implement — two lines and one import**

In `src/receipts/pipeline.py`, add `redact_pan` to the existing import
(lines 62–69), keeping the block sorted:

```python
from .persist.repository import (
    find_duplicate_by_phash,
    get_receipt,
    mark_duplicate,
    redact_pan,
    save_extraction,
    save_extraction_run,
    save_findings,
)
```

Replace line 761:

```python
    reason = _truncate(str(failure), _MAX_REASON_CHARS)
```

with:

```python
    redacted = redact_pan(str(failure))
    reason = _truncate(redacted, _MAX_REASON_CHARS)
```

Redact **before** truncate: truncating first can cut a PAN mid-shape into
something `_PAN_RE` no longer matches, so the surviving digits would pass
every later redaction in the clear. Do not touch the `log.warning` on the
next lines — that is Task 2, and until then it still (correctly, for now)
references `failure.cause`.

- [ ] **Step 5: Run the new test and the module**

```
python -m pytest tests/test_process_receipt.py -k "never_leaks_raw_model_text" -q
python -m pytest tests/test_process_receipt.py --junitxml=var/junit_t1.xml -q
```

Expected: the new test PASSES; the module is all green (read the counts from
the XML; the swept assertions `stage in result.reason` and
`"cost" in result.reason.lower()` must not move — design §4). Delete the
junit file after reading it.

- [ ] **Step 6: Prove the test discriminates — revert only the mint**

Put line 761 back to `reason = _truncate(str(failure), _MAX_REASON_CHARS)`
(keep the import and the test; delete the `redacted =` line). Run the Step 3
selection: **must FAIL** with the raw PAN present. Restore the committed
two-line form; run again: PASS. Record both outputs in your report.

- [ ] **Step 7: Lint and commit**

```
python -m ruff check .
git add src/receipts/pipeline.py tests/test_process_receipt.py
git commit -m "fix(pipeline): redact the failure reason at its minting point

_persist_failure handed str(failure) to ProcessResult.reason raw, so
exception text quoting model values (the reviewed-row guard quotes
merchant.name and totals.total by design) reached CLI stdout and RQ's
Redis result store unredacted -- only review_tasks.reason was covered,
at its own sink. Redact before truncating: a truncation cut can leave a
PAN mid-shape and invisible to _PAN_RE, so order is load-bearing. One
line covers every present and future consumer of the carrier (ADR-0022)."
```

---

### Task 2: Render a redacted traceback in the failure log

**Files:**
- Modify: `src/receipts/pipeline.py` — the `log.warning` at lines 762–763
  (as renumbered after Task 1: directly below the two-line mint) and the
  stdlib import block
- Test: `tests/test_process_receipt.py` (append after Task 1's test)

**Interfaces:**
- Consumes: the local `redacted: str` Task 1 bound directly above the log
  call; `redact_pan`; stdlib `traceback.format_exception(exc)` (Python 3.14
  single-argument form); `_StageFailure.cause: BaseException`.
- Produces: the failure log record format
  `"Receipt %s failed at stage %r: %s\n%s"` with no `exc_info` — nothing
  else consumes it, but the format is what T2 pins.

- [ ] **Step 1: Read the real code before changing it**

Read `src/receipts/pipeline.py`: the `_persist_failure` head as Task 1 left
it (the two-line mint, then the `log.warning` still carrying
`failure.cause` and `exc_info=failure.cause`), and the stdlib import block
at lines 30–39. Read `tests/test_image_ops.py` lines 157–168 — the house
`caplog.at_level` pattern this task's test follows. Read design §2.2.
**Stop condition:** if Task 1's `redacted` local is not in place directly
above the log call, stop and report (this task consumes it).

- [ ] **Step 2: Write the failing test**

Append to `tests/test_process_receipt.py`:

```python
def test_the_failure_log_renders_a_redacted_traceback(
    session_factory, storage, settings, caplog
):
    """The log keeps its stack trace and loses the raw model text.

    ``exc_info`` renders the exception's own message into the log, so
    redacting the ``%s`` alone still leaked the guard's ``merchant.name``
    quote into log files. The ruling (2026-08-03): render the traceback,
    redact it as text, drop ``exc_info`` -- full fidelity, nothing raw.
    """
    job = _job(storage)
    with session_factory() as session:
        create_pending_receipt(session, job)
        session.commit()
    with session_factory() as session:
        apply_corrections(
            session, job.id, {"totals": {"total": "999.99"}}, corrected_by="alice"
        )

    bad = _good()
    bad.merchant.name = "SUPERMART 4111111111111111 AND 5555555555554444"

    with caplog.at_level(logging.WARNING, logger=process_receipt.__module__):
        _run(job, _Client([_triage(), bad]), session_factory, storage, settings)

    text = caplog.text
    assert "persist" in text
    assert "Traceback (most recent call last)" in text
    assert "************1111" in text
    assert "************4444" in text
    assert "4111111111111111" not in text
    assert "5555555555554444" not in text
```

Add to the module's import block only what is missing (check first):
`logging` (stdlib), and `process_receipt` if the module currently imports
only helpers around it — `process_receipt.__module__` is how the logger
name is read off the real artifact instead of restated.

- [ ] **Step 3: Run it and confirm the RED is the right RED**

```
python -m pytest tests/test_process_receipt.py -k "renders_a_redacted_traceback" -q
```

Expected: **FAILS** at `assert "4111111111111111" not in text` — today
`exc_info` renders the raw cause (and the `%s` logs it again). The
`Traceback (most recent call last)` assertion is expected to already hold
via `exc_info`'s rendering; if pre-fix it does not, report which assertions
failed — the required RED is the raw-PAN one.

- [ ] **Step 4: Implement — rewrite the log call**

Add `import traceback` to `src/receipts/pipeline.py`'s stdlib import block
(sorted). Replace the `log.warning` (the lines directly below Task 1's
mint):

```python
    log.warning("Receipt %s failed at stage %r: %s", job.id, failure.stage, failure.cause,
                exc_info=failure.cause)
```

with:

```python
    log.warning(
        "Receipt %s failed at stage %r: %s\n%s",
        job.id,
        failure.stage,
        redacted,
        redact_pan("".join(traceback.format_exception(failure.cause))),
    )
```

The message logs the **untruncated** `redacted` text (truncation is a
review-UI concern, not a log concern) plus the full rendered traceback,
redacted as text. No `exc_info`.

- [ ] **Step 5: Run the new test and the module**

```
python -m pytest tests/test_process_receipt.py -k "renders_a_redacted_traceback" -q
python -m pytest tests/test_process_receipt.py --junitxml=var/junit_t2.xml -q
```

Expected: PASS, module green (counts from the XML; delete the file after).

- [ ] **Step 6: Prove the test discriminates — revert only the log call**

With Task 1's mint **intact**, put the original `log.warning(...)`
(`failure.cause` + `exc_info=failure.cause`) back and remove
`import traceback`. Run this task's selection: **must FAIL** with raw PAN in
`caplog.text` — and Task 1's test must still PASS (run its selection too):
that pair is the proof the two guarantees are independent. Restore the
committed form; both selections PASS. Record all four outputs.

- [ ] **Step 7: Lint and commit**

```
python -m ruff check .
git add src/receipts/pipeline.py tests/test_process_receipt.py
git commit -m "fix(pipeline): render a redacted traceback in the failure log

The failure log carried the raw cause twice: in the message and through
exc_info, whose rendered traceback embeds the exception's own message --
so the reviewed-row guard's merchant.name quote landed raw in log files
even after the reason carrier was redacted. Render the traceback with
traceback.format_exception, redact it as text, and log the untruncated
redacted failure text in its place: full stack fidelity, no raw model
text on disk (ADR-0022, ruling of 2026-08-03)."
```

---

### Task 3: Hide statement parameters in engine error text

**Files:**
- Modify: `src/receipts/persist/session.py` — line 37 (`create_engine`)
- Test: `tests/test_repository.py` (append at the end of the module)

**Interfaces:**
- Consumes: `make_engine(url: str | None = None) -> Engine` from
  `receipts.persist.session`.
- Produces: every engine `make_engine` builds renders SQLAlchemy error text
  without `[parameters: (...)]`. No API change; no caller changes.

- [ ] **Step 1: Read the real code before changing it**

Read `src/receipts/persist/session.py` lines 17–48 (`make_engine` and its
SQLite pragma listener) and `tests/test_repository.py`'s import block. Read
design §1.1 (the measured echo) and §2.3. **Stop condition:** if
`create_engine` at line 37 already carries any keyword arguments, stop and
report.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_repository.py`:

```python
def test_engine_error_text_hides_statement_parameters() -> None:
    """SQLAlchemy's parameter echo is a PAN egress, closed at the one factory.

    A wrapped DBAPI error appends ``[parameters: (...)]`` -- raw statement
    values, which on this schema are model text -- and that string reaches
    the failure reason, the failure log's traceback, and RQ's failed
    registry (the one durable sink this project cannot redact from its own
    side). ``hide_parameters=True`` removes the echo at the source for every
    runtime engine, all of which are built here (ADR-0022). Measured both
    directions on 2026-08-03 before this test pinned it.
    """
    engine = make_engine("sqlite://")
    with engine.connect() as conn:
        conn.execute(sa.text("CREATE TABLE egress_probe (value TEXT UNIQUE)"))
        conn.execute(
            sa.text("INSERT INTO egress_probe VALUES (:v)"),
            {"v": "4111111111111111"},
        )
        with pytest.raises(sa.exc.IntegrityError) as excinfo:
            conn.execute(
                sa.text("INSERT INTO egress_probe VALUES (:v)"),
                {"v": "4111111111111111"},
            )
    message = str(excinfo.value)
    assert "4111111111111111" not in message
    assert "hidden" in message.lower()
```

Add to the module's import block only what is missing (check first):
`from receipts.persist.session import make_engine`. `sa` and `pytest` are
already imported.

- [ ] **Step 3: Run it and confirm the RED is the right RED**

```
python -m pytest tests/test_repository.py -k "hides_statement_parameters" -q
```

Expected: **FAILS** at `assert "4111111111111111" not in message` — the
plain engine echoes the parameter (measured during the design's brainstorm,
both directions). If it fails at the `IntegrityError` expectation instead,
stop and report.

- [ ] **Step 4: Implement — one keyword**

In `src/receipts/persist/session.py`, replace line 37:

```python
    engine = create_engine(resolved)
```

with:

```python
    engine = create_engine(resolved, hide_parameters=True)
```

- [ ] **Step 5: Run the new test, then the persistence neighbourhood**

```
python -m pytest tests/test_repository.py -k "hides_statement_parameters" -q
python -m pytest tests/test_repository.py tests/test_migrations.py tests/test_models.py tests/test_dedupe_db.py tests/test_worker.py --junitxml=var/junit_t3.xml -q
```

Expected: PASS, neighbourhood green (counts from the XML; delete after).
Nothing in the suite reads `[parameters:` from error text (design §4), so
the only test that may move is the new one.

- [ ] **Step 6: Prove the test discriminates — revert only the keyword**

Put `create_engine(resolved)` back (keep the test). Run the Step 3
selection: **must FAIL** with the PAN present in the message. Restore
`hide_parameters=True`; PASS. Record both outputs.

- [ ] **Step 7: Lint and commit**

```
python -m ruff check .
git add src/receipts/persist/session.py tests/test_repository.py
git commit -m "fix(persist): hide statement parameters in engine error text

SQLAlchemy appends [parameters: (...)] to every wrapped DBAPI error, and
on this schema statement parameters are model text -- so a DataError or
IntegrityError quoted raw values into the failure reason, the failure
log's traceback, and RQ's failed registry, the one durable sink this
project cannot redact from its own side. Every runtime engine funnels
through make_engine, so one keyword closes the echo everywhere; the
error message itself names the flag when parameters are wanted for
debugging (ADR-0022)."
```

---

### Task 4: Redact the uncontained failed-job print

**Files:**
- Modify: `src/receipts/cli.py` — the failed-job print near line 860 and
  the `.persist.repository` import at line 140
- Test: `tests/test_cli_pipeline.py` (append at the end of the module)

**Interfaces:**
- Consumes: `redact_pan` from `receipts.persist.repository`; the existing
  test-driver pattern for `cmd_process` (`build_parser().parse_args(...)` +
  keyword-injected `session_factory`/`storage`/`settings`/`client_factory`,
  exactly as the inline-containment test uses).
- Produces: the failed-job stdout line
  `f"{job.id}  failed  {redact_pan(str(exc))}"`. Nothing else consumes it.

- [ ] **Step 1: Read the real code before changing it**

Read `src/receipts/cli.py` lines 828–870 (the inline run loop:
`run()` catches `BaseException` outside `_UNCONTAINED` and the loop prints
`f"{job.id}  failed  {exc}"` for it), line 240 (`_UNCONTAINED`), and line
140 (the `.persist.repository` import). Read
`tests/test_cli_pipeline.py` lines 405–462 — the inline-containment test
whose driver this task's test mirrors (a `client_factory` that raises is
caught by `run()` and lands on exactly the print under test) — plus the
module's import block and the `_pending_receipt` helper. Read design §2.4.
**Stop condition:** if the failed print's f-string differs from
`f"{job.id}  failed  {exc}"`, stop and report.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_cli_pipeline.py`:

```python
def test_an_uncontained_batch_failure_prints_a_redacted_reason(
    session_factory, storage, settings, capsys
):
    """The inline loop's failed-job line is an egress too (ADR-0022).

    ``run()`` catches everything outside ``_UNCONTAINED`` and the loop
    prints the exception straight to stdout -- which a service manager
    journals to disk. A provider error can quote the payload it rejected,
    so the print goes through ``redact_pan`` like every other egress. Two
    PANs in one value (review standard 9).
    """
    _pending_receipt(session_factory, storage)
    args = build_parser().parse_args(["process", "--inline"])

    def client_factory():
        raise RuntimeError(
            "provider rejected payload holding 4111111111111111 and 5555555555554444"
        )

    code = cmd_process(args, session_factory=session_factory, storage=storage,
                       settings=settings, client_factory=client_factory)

    assert code == EXIT_FAILED
    out = capsys.readouterr().out
    assert "failed" in out
    assert "************1111" in out
    assert "************4444" in out
    assert "4111111111111111" not in out
    assert "5555555555554444" not in out
```

Everything this test names (`_pending_receipt`, `build_parser`,
`cmd_process`, `EXIT_FAILED`, the fixtures) is already imported by the
module — check first, add nothing that exists.

- [ ] **Step 3: Run it and confirm the RED is the right RED**

```
python -m pytest tests/test_cli_pipeline.py -k "uncontained_batch_failure" -q
```

Expected: **FAILS** at `assert "************1111" in out` — the print is
verbatim today. If it fails before reaching the print (driver error), stop
and report.

- [ ] **Step 4: Implement — one print and one import**

In `src/receipts/cli.py`, extend line 140:

```python
from .persist.repository import create_pending_receipt, get_receipt, query_receipts
```

to:

```python
from .persist.repository import (
    create_pending_receipt,
    get_receipt,
    query_receipts,
    redact_pan,
)
```

Replace the failed-job print near line 860:

```python
            print(f"{job.id}  failed  {exc}")
```

with:

```python
            print(f"{job.id}  failed  {redact_pan(str(exc))}")
```

- [ ] **Step 5: Run the new test and the module**

```
python -m pytest tests/test_cli_pipeline.py -k "uncontained_batch_failure" -q
python -m pytest tests/test_cli_pipeline.py --junitxml=var/junit_t4.xml -q
```

Expected: PASS, module green (counts from the XML — the existing
containment tests print PAN-free exception text and must not move; delete
the file after).

- [ ] **Step 6: Prove the test discriminates — revert only the print**

Put `print(f"{job.id}  failed  {exc}")` back (keep the import and the
test). Run the Step 3 selection: **must FAIL** with the raw PAN on stdout.
Restore the committed print; PASS. Record both outputs.

- [ ] **Step 7: Lint and commit**

```
python -m ruff check .
git add src/receipts/cli.py tests/test_cli_pipeline.py
git commit -m "fix(cli): redact the uncontained failed-job print

The inline loop prints exceptions that escaped process_receipt straight
to stdout, which service managers journal to disk. _UNCONTAINED is only
(KeyboardInterrupt, SystemExit), so every nothing-could-be-written
re-raise lands on this line; with hide_parameters closing the SQLAlchemy
echo, this print is the remaining belt for an infra exception that
embeds model text some other way (ADR-0022)."
```

---

## Verification, after all four tasks

- [ ] `python scripts/verify.py` — all five gates PASS (pytest, ruff,
      typecheck, vitest, build). Vitest count unchanged — no frontend file
      moved.
- [ ] `python -m pytest --junitxml=var/junit_final.xml -q` — read the
      counts from the XML (expect the baseline 920 plus the four new tests,
      zero failures/errors/skips; report the exact total); delete the file
      after.
- [ ] Outside-repo import (the environment lesson): from a directory
      outside the repo,
      `python -c "from receipts.pipeline import process_receipt; from receipts.persist.session import make_engine"`
      imports cleanly.
- [ ] `git status` clean; nothing under `var/` ever staged; the branch
      touches exactly the six files this plan names plus the three docs
      commits already on it (design, ADR-0022, this plan).

## Self-review notes

Spec coverage: design §1 (the map) → each task's docstrings and Step 1
readings; §2.1 → Task 1 (redact-before-truncate order in Step 4's note and
the commit message); §2.2 → Task 2 (untruncated `redacted`, rendered
traceback, no `exc_info`); §2.3 → Task 3 (one keyword, the measured echo as
the RED); §2.4 → Task 4 (the mirrored driver — the design's "session
factory that serves ingest, then raises" seam was simplified to the
`client_factory` seam the existing containment test already proves reaches
the same print; the deliverable line is identical); §3 (what must not
change) → Global Constraints; §4 (the assertion sweep) → Task 1/3/4 Step 5
notes; §6's T1–T4 → Tasks 1–4 Steps 2/3/6 (each guarantee reverted alone;
Task 2's Step 6 additionally proves independence from Task 1); §7 → the
verification block; §8 → ADR-0022, already committed (`e95215f`).
