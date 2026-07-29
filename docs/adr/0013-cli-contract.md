# ADR 0013 — The CLI contract: one work list, no overrides, no prompts

**Status:** Accepted (design agreed 2026-07-29; implemented by P4.T5/T6 —
`docs/superpowers/specs/2026-07-29-cli-design.md`)

## Context

`cli.py` is the last piece of Phase 4 and the operator-facing half of a system
that already has an HTTP half. Everything it drives exists: ingest,
`process_receipt`/`process_batch`, the RQ worker, export, the eval harness, the
repository, the user store. The decisions worth recording are not about wiring —
they are about what an operator is allowed to do, and what the machine is
allowed to do to an operator's work.

## Decision

### The `pending` row is the single work list

`receipts ingest` stores a blob and writes a `pending` receipt row. It does
**not** enqueue. `receipts process` drains the `pending` rows.

This is what makes ADR-0012's pending row earn its place twice: a receipt that
arrived over `POST /upload` and one that arrived through `receipts ingest` are
picked up by exactly the same command, from exactly the same query. Two entry
points, one work list, one place to look when something is stuck.

### `process` takes production's path by default

`receipts process` enqueues to RQ; `--inline` runs `process_batch` in-process for
a single machine or a box with no Redis. A missing `REDIS_URL` while enqueueing
is a **hard failure naming `--inline`**, never a silent fallback: a fallback
means the operator believes work is queued when it is running in a terminal they
are about to close.

The command that drives production must take production's path, or worker-only
bugs stay invisible until deployment.

### No flag overwrites a human review

`receipts reprocess <id>` re-runs the pipeline and updates the receipt row only
when the receipt is not `reviewed`. On a `reviewed` receipt the run still
happens, the row is left untouched, and a review task is opened naming what the
run produced — a human decides. **See the correction below for what "on record"
actually means.**

`--force` gates by status, not by permission: without it, `reprocess` re-runs
`pending`, `needs_review` and `rejected` receipts and refuses `auto_approved`,
because overwriting a result the system already stands behind should be
deliberate. `--force` adds `auto_approved`. **It does not extend to `reviewed`,
and no flag does.**

This follows directly from the Critical the whole-branch review found in P4.T3: a
machine run silently replaced a reviewer's hand-keyed numbers and re-labelled the
receipt `auto_approved`. A `--force` that reopened that path would reintroduce
the same defect through the front door, with the audit trail again disagreeing
with the row.

### `calibrate` refuses an empty result set

`receipts calibrate` prints the calibration curve and recommends the lowest
threshold clearing `--target`. This project has already produced a 0/0 precision
of `1.0` once, on an empty golden directory, and the command whose entire job is
choosing an auto-approval threshold is the worst possible place to repeat it — so
the recommendation passes **three** gates, each closing a different way of
returning a number that looks perfect and means nothing:

1. **Zero receipts → exit `1`**, with no precision figure printed at all.
2. **Never recommend a threshold that approves nothing.** `calibration_curve`
   defines precision as `1.0` for an empty approved set and its sweep always
   includes `1.0`, which sits above every observed confidence — so an
   all-incorrect result set still yields a `(1.0, rate=0.0, precision=1.0)` row.
3. **Never recommend below `REVIEW_THRESHOLD` (0.60), and never from fewer than
   `_MIN_APPROVED_SAMPLE` approved receipts.** Gate 2 alone guards only the
   fail-*safe* direction. The fail-*dangerous* one is worse and was found by the
   whole-branch review: when every golden receipt is critical-correct — the
   expected outcome of a first clean baseline — precision at threshold `0` is
   `1.0`, so the scan recommended `0`. `Settings.auto_approve_threshold` has no
   lower bound and `route()` approves on `confidence >= threshold`, so an
   operator following that recommendation would auto-approve every receipt at any
   confidence and no receipt would ever reach a human again.

The curve prints `approved`/`correct` counts per row, so the sample behind each
precision figure is visible rather than implied. When nothing qualifies it says so
and recommends nothing, rather than returning the least-bad number as though it
passed.

**`receipts eval` carries the same zero-receipt refusal**, and a nonexistent or
label-less `--golden-dir` is its own error. The first version guarded only
`calibrate`, the *reader* — leaving `eval`, the *producer*, free to print a
vacuous 100% with a green exit code and persist it, after which the poisoned file
won the `latest_results_file` mtime sort and shadowed the genuine baseline beside
it. Guard the producer, not just the reader.

### Exit codes, and what is not a failure

`0` the command completed; `1` it could not (unreachable database, refused
provider, missing `REDIS_URL` when enqueueing, unknown id); `2` usage error.

**A receipt routed to review does not change the exit code.** Review is the
system working as designed, not an error, and a CLI that exits non-zero on it
would train operators — and CI — to ignore its exit status.

### No interactive prompts

Anywhere. The CLI must be usable from a script and from CI. Confirmation is
expressed as a flag (`--force`), never as a question. Passwords are read from
stdin, never `argv`, because an argument lands in shell history and in `ps`.

### Correction (2026-07-29, measured before implementation)

The paragraph above originally claimed reprocess "always writes new
`extraction_runs` and `validation_findings`, so the attempt is on record." **That
was written from intent, not from the code, and it is false for exactly the case
it was written about.** A probe against the real pipeline:

```
ProcessResult.status       = REVIEWED      ProcessResult.failed_stage = persist
row.status = REVIEWED   row.total = 999.9900      (the human's number survives)
extraction_runs rows     = 0
validation_findings rows = 0
review task = OPEN / priority 1
review task reason = "persist: ValueError: receipt ... has already been reviewed
   by a human ... this run produced status=auto_approved, total=224.00,
   merchant='SUPERMART INC.'"
```

`save_extraction` refuses the write **first** in `_persist_outcome`, so the whole
transaction — audit rows included — rolls back. What survives is the review
task's reason, which names the run's status, total and merchant. That meets the
operator-facing need (a human can see what the re-run would have produced) but it
is **not** a structured audit trail.

The invariant itself is sound and was verified in the same probe: the row is
untouched, `process_receipt` returns rather than raising, and `ProcessResult`
reports the row's real status.

**Deferred, deliberately** (user decision, 2026-07-29): making the audit rows
survive means writing `extraction_runs` in their own transaction so a refused row
write cannot roll them back — a change to merged, safety-critical pipeline code
(ADR-0011/0012) that deserves its own task and its own review rather than riding
along with a new command. It is worth doing: `reviewed` receipts are the ones
carrying human-verified values, so a recorded re-run is free model-versus-truth
signal for prompt work (P6) and calibration (P8). Until then, §14.10's "keep
history" is honest only about the row and the review task.

Two consequences for the CLI, both verified in the same probe: `process_receipt`
**returns normally** on this path (`status=REVIEWED`, `failed_stage="persist"`),
so the CLI keys off the result rather than catching an exception; and
`_persist_failure` has **already** opened the review task, so the CLI must not
enqueue its own — `enqueue_review` would overwrite that specific reason with a
vaguer one.

## Consequences

- `merchants` ships thin — `list` against the existing table, `hints` to show,
  append to, and clear the JSON column, with §18's "trust the image" sentence
  appended when a supplied hint does not already end with it. Phase 6 adds
  fingerprinting and few-shot injection on top rather than starting from nothing.
- A `ReceiptJob` rebuilt from a row is **lossy by construction**: `source`,
  `original_filename` and `content_type` are not §6 columns. `process_receipt`
  uses `id` and `image_key`; the rest are documented placeholders. Anyone who
  later needs faithful provenance must add columns, not infer them.
- `receipts reprocess` is the first caller that will routinely hit the two parked
  findings from the P4.T3 branch review: a receipt whose stage failed carries
  `image_phash = ""` and so can never be matched as a dedupe original, and the
  dedupe skip added for that review's Finding 2 is what stops a reprocess turning
  a duplicate-linked original into an empty `rejected` row. **Both are now tested
  from the CLI side.** Note that neither dedupe defence is load-bearing alone —
  the ADR-faithful scenario fails only when both are reverted — so a third test
  covers a state only the `_ALREADY_EXTRACTED` skip protects: two `auto_approved`
  receipts holding the same image and linked to neither, which is reachable
  because two workers on one image each read `image_phash = ""` at dedupe time
  and neither sees the other.
- `receipts calibrate` cannot produce a trustworthy threshold until ISSUE-001
  runs. It builds the curve and says so; it does not imply otherwise.

## References

SPEC §14.10 (CLI), §16 (eval), §18 (traps); ADR-0011 (terminal-state contract),
ADR-0012 (the review API, the pending row, and the never-overwrite-a-review
invariant); `docs/superpowers/specs/2026-07-29-cli-design.md`;
`docs/KNOWN_ISSUES.md` (ISSUE-001).
