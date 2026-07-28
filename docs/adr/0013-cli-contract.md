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

`receipts reprocess <id>` always writes new `extraction_runs` and
`validation_findings`, so the attempt is on record. It updates the receipt row
only when the receipt is not `reviewed`. On a `reviewed` receipt the run still
happens, the row is left untouched, and a review task is opened saying a re-run
produced different values — a human decides.

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
threshold clearing `--target`. On a result set with **zero receipts it exits `1`
with an explanation** rather than reporting precision `1.0`, and when no
threshold clears the target it says so and recommends nothing rather than
returning the least-bad number as though it passed.

This project has already produced a 0/0 precision of `1.0` once, on an empty
golden directory. The command whose entire job is choosing an auto-approval
threshold is the worst possible place to repeat it.

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
  a duplicate-linked original into an empty `rejected` row. Both need tests here.
- `receipts calibrate` cannot produce a trustworthy threshold until ISSUE-001
  runs. It builds the curve and says so; it does not imply otherwise.

## References

SPEC §14.10 (CLI), §16 (eval), §18 (traps); ADR-0011 (terminal-state contract),
ADR-0012 (the review API, the pending row, and the never-overwrite-a-review
invariant); `docs/superpowers/specs/2026-07-29-cli-design.md`;
`docs/KNOWN_ISSUES.md` (ISSUE-001).
