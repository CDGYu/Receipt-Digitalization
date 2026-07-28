# P4.T5 / P4.T6 — `cli.py`

**Date:** 2026-07-29 · **Base:** `master @ 700d775` · **Status:** approved, not yet implemented
**Implements:** SPEC §14.10 (`receipts ingest|process|export|eval|calibrate|merchants|reprocess`) and IMPLEMENTATION_PLAN P4.T5/P4.T6. Finishes Phase 4.

---

## 1. Context

Everything the CLI drives already exists: `ingest_file`/`ingest_bytes`,
`create_pending_receipt`, `process_receipt`/`process_batch`, the RQ worker,
`export_workbook` with the API's export builders, `run_baseline`,
`calibration_curve`, the repository, and `persist/users.py`. What is missing is
the operator-facing entry point — the way a person who is not making an HTTP
request gets work into and out of the system.

Three decisions were taken with the user before design (§2). Everything else
follows from the spec and existing conventions.

## 2. Decisions

| # | Decision | Rationale |
|---|---|---|
| C1 | **`reprocess` re-runs and keeps history, but never overwrites a human review** — `--force` included | The branch review's Critical was a machine run silently replacing a reviewer's hand-keyed numbers. A flag that re-enables it would reintroduce the defect through the front door. The attempt is still recorded and a human still decides. |
| C2 | **`process` enqueues to RQ by default; `--inline` runs locally** | The command that drives production must take production's path, or worker-only bugs stay invisible until deployment. |
| C3 | **`merchants` ships thin now** — `list` against the table, `hints` to show and set the JSON column | Real and small. Phase 6 adds fingerprinting and few-shot injection on top rather than starting from nothing. |

## 3. Architecture

### 3.1 Shape

`src/receipts/cli.py`, stdlib `argparse` — no new dependency, and the same
library `persist/users.py`'s bootstrap already uses. Exposed two ways:

- `[project.scripts]` → `receipts = receipts.cli:main`, so §14.10's `receipts
  ingest …` syntax is literal;
- `python -m receipts.cli`, which needs no reinstall and is what the tests use.

Every subcommand is a function taking parsed arguments plus its collaborators
(`session_factory`, `storage`, `client_factory`, `settings`), defaulting to the
real ones built from the environment. Tests call those functions directly with a
fake client and a SQLite session factory; nothing shells out.

`main(argv=None) -> int` returns the exit code rather than calling `sys.exit`, so
a test can assert on it. The console-script wrapper does the `SystemExit`.

**Exit codes:** `0` the command completed; `1` it could not (unreachable
database, refused provider, missing `REDIS_URL` when enqueueing, an unknown id);
`2` usage error (argparse's own). **A receipt routed to review is not a failure**
— it is the system working as designed and must not change the exit code.

If `cli.py` passes ~500 lines it splits by command group rather than becoming the
module that does everything.

### 3.2 What each command reuses

| Command | Calls |
|---|---|
| `ingest` | `validate_upload`, `ingest_file`, `create_pending_receipt` |
| `process` | `query_receipts(status=PENDING)`, then `enqueue_receipt`/`make_queue` or `process_batch` |
| `export` | `review.serializers` export builders + `export_workbook` |
| `eval` | `eval.run_baseline.run_baseline` + `format_report` |
| `calibrate` | `eval.metrics.calibration_curve` over a results file |
| `merchants` | `Merchant` queries via the session |
| `reprocess` | `get_receipt`, `process_receipt`, `enqueue_review` |
| `users` | `persist.users` |

## 4. The commands

### 4.1 `receipts ingest <path> [--source upload]`

A single file or a directory (non-recursive; `--recursive` to descend). For each
file: validate, store the original bytes, write the `pending` row, print
`<receipt_id>  <filename>`. A rejected file prints its reason and is counted, not
silently skipped — the run continues and the summary reports both totals.

Ingest does **not** enqueue. `receipts process` is what picks the work up, which
keeps one work list rather than two.

### 4.2 `receipts process [--limit N] [--inline] [--workers 4]`

Selects receipts with `status = pending` (oldest first), `--limit` capping how
many. Default enqueues each to RQ; `--inline` runs `process_batch` in-process.

**A missing `REDIS_URL` when enqueueing is a hard failure with a message naming
`--inline`** — never a silent fallback, because a silent fallback means the
operator believes work is queued when it is running in a terminal they are about
to close.

Rebuilding a `ReceiptJob` from a row is lossy by construction: `source`,
`original_filename` and `content_type` are not §6 columns. `process_receipt` uses
`id` and `image_key`; the other three get documented placeholders
(`source="cli"`, the filename derived from `image_key`). Note this in the
function's docstring — a future reader will otherwise assume the round trip is
faithful.

Prints a per-receipt line and a closing summary: counts by terminal status and
the batch's total cost as an exact `Decimal`.

### 4.3 `receipts export --out book.xlsx [--from DATE] [--to DATE] [--status S]`

Reuses `review/serializers.py`'s export builders rather than growing a second
ORM→workbook mapping. Same rule as the API route: **`PENDING` and `REJECTED` are
excluded unless `--status` names them**, and the same row cap applies with the
same refusal — narrow the filter, never truncate.

### 4.4 `receipts eval [--golden-dir DIR]`

Wraps `run_baseline`, prints the six-metric §16 table, writes
`eval/results/{date}-{prompt_version}.json`. Inherits `run_baseline`'s refusal of
the `fake` provider, whose message already explains what to configure.

### 4.5 `receipts calibrate [--results FILE] [--target 0.99]`

Loads the newest results file (or `--results`), prints the calibration curve as
`threshold | auto-approve rate | precision`, and recommends the lowest threshold
whose precision clears `--target`.

**It refuses a result set with zero receipts**, exiting `1` with an explanation
rather than reporting precision `1.0`. This project has already produced exactly
that artifact once — a 0/0 precision of `1.0` on an empty golden directory — and
the command whose entire job is choosing an auto-approval threshold is the worst
possible place to repeat it. If no threshold clears the target it says so and
recommends nothing; it never returns the least-bad number as though it passed.

### 4.6 `receipts merchants list|hints`

`list` prints id, canonical name, tax id, receipt count. `hints <id>` prints the
hints array; `hints <id> --add "…"` appends and `--clear` empties it. Per §18 a
merchant hint must end with "trust the image", so `--add` appends that sentence
when the supplied text does not already end with it, and says it did.

### 4.7 `receipts reprocess <id> [--force]`

Re-runs the pipeline for one receipt with current prompts and rules.

- Always writes new `extraction_runs` and `validation_findings`, so the attempt
  is on record whatever happens to the row.
- Updates the receipt row **only when the receipt is not `reviewed`**.
- On a `reviewed` receipt the run still happens, the row is left alone, and a
  review task is opened saying a re-run produced different values — a human
  decides.

**What `--force` actually does.** Without it, `reprocess` re-runs only receipts
where re-running is unambiguously safe — `pending`, `needs_review`, and
`rejected` — and refuses an `auto_approved` receipt, because overwriting a
result the system already stands behind should be deliberate. `--force` adds
`auto_approved` to that set. It does **not** and cannot extend to `reviewed`: no
flag overwrites values a human keyed. The help text says exactly that, so nobody
reaches for `--force` expecting an override it does not grant.

There is no interactive prompt anywhere in the CLI — it must be usable from a
script and from CI.

Two known interactions, both already handled in the code it calls, and both to be
covered by tests here: a receipt whose stage failed carries `image_phash = ""`
(so it cannot be matched as a dedupe original — the parked finding), and the
dedupe skip added for the branch review's Finding 2 is what stops a reprocess
turning a duplicate-linked original into an empty `rejected` row.

### 4.8 `receipts users add|list|deactivate|set-role`

Wraps `persist/users.py`. The password is read from stdin, never `argv` — an
argument lands in shell history and in `ps`. `add` defaults to `reviewer`.

## 5. Testing

Offline throughout: SQLite, a temp-directory `LocalStorage`, a fake client, a
fake queue object. No Redis, no network, no subprocess.

- **Per command**, called as a function with injected collaborators: the happy
  path, plus the failure that command is most likely to get wrong — a rejected
  file for `ingest`, a missing `REDIS_URL` for `process`, a zero-receipt result
  set for `calibrate`, a `reviewed` receipt for `reprocess`, an unknown id for
  `merchants hints`.
- **Through `main(argv)`** for a few commands, to pin argv parsing and the exit
  codes (`0` completed, `1` could not, `2` usage). Includes one test asserting a
  receipt routed to review still exits `0`.
- **`reprocess` against a `reviewed` receipt** asserts the money columns are
  byte-for-byte unchanged, a new `extraction_runs` row exists, and a review task
  was opened. This is C1's guarantee, and it is the one test in this task that
  protects a number a human typed.
- `--inline` exercises the real `process_batch`; the enqueue path asserts the
  fake queue received one job per pending receipt.

## 6. Docs to update when this lands

- §14.10 gains the flags actually implemented (`--limit`, `--inline`,
  `--workers`, `--recursive`, `--target`, `--force`) and the `users` command.
- `api.py`'s and `process_receipt`'s docstrings currently describe re-enqueueing
  because no CLI existed; point them at `receipts reprocess` once it does.
- `docs/MEMORY.md` and the progress ledger.

## 7. Out of scope

Frontend (P5), merchant fingerprinting and few-shot injection (P6),
self-consistency (P7), calibration *of the weights* (P8 — blocked on ISSUE-001).
`receipts calibrate` builds the curve; it cannot produce a trustworthy threshold
until a real baseline exists, and it says so rather than implying otherwise.
