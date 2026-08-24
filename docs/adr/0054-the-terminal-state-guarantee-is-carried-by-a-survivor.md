# ADR 0054 — The terminal-state guarantee is carried by a survivor

**Status:** Accepted (2026-08-25)
**Closes:** ISSUE-029 (`c08b718`), ISSUE-030 (`63084b6`, `41d2933`, `d1e446b`),
ISSUE-031 (`2d1bea9`, `d1e446b`)
**Rests on:** ADR-0006 (repository functions take a session, flush, and do not
commit), ADR-0013 (exit codes; a receipt routed to review still exits 0),
ADR-0047 (the SDK's default `max_retries`), ADR-0051 (a guard must not share its
derivation with its subject)

---

## Context

The system states a guarantee: **every receipt reaches a terminal state.** In
the pipeline that is carried by normal return and by exception handling.

**An interruption is neither.** A SIGKILLed RQ work-horse raises nothing in its
own process. A CLI run that is simply stopped executes no handler at all. A
container restart does not politely unwind. So no amount of `try`/`except`
anywhere inside a run can close this: the process that would have to notice is
the one that died.

This was not theoretical. ISSUE-029 — a job ceiling shorter than one receipt on
this hardware — fired on the first pipeline run that ever reached a real model,
and every receipt it killed sat `pending` forever. A screen polling one of them
would poll until someone closed the tab.

**Whatever carries the guarantee has to survive the run, and it has to work
without knowing which of the four entry points died.** That rules out a reaper
keyed on RQ, which would cover exactly one of them.

---

## Decision

**1. Liveness is a heartbeat**, written as the run works — not an age threshold
on the row, and not a lease. Only a heartbeat separates *slow* from *stranded*.
On this box a single legitimate model call has been measured in the hundreds of
seconds, so an age threshold sharp enough to catch a dead run would kill live
ones. Two nullable columns on `receipts` carry it (`progress_stage`,
`progress_at`) rather than a side table: `updated_at` is provably inert, so the
cost of it coming to mean "last heartbeat" is documentation, not breakage.

**2. Two runners, because neither alone is sufficient.** `receipts sweep` bears
the guarantee; a single-row sweep on the progress route bears the latency. The
command alone leaves a waiting screen polling until the next interval. The route
alone never reaches a receipt nobody is looking at — which is precisely the
silent drop the guarantee exists to forbid. The route's sweep is deliberately
**single-row**: a table-wide sweep on a GET would put unbounded work on a
request path.

**3. A swept receipt becomes `needs_review`**, following `_persist_failure`'s
convention, with the stage it died in named in the reason. No new
`ReceiptStatus` member — its own docstring calls the values stable, and the
review API, its serializers and the export all branch on them. Automatic
requeue was rejected for now: it needs an attempt counter, it risks a poison
receipt looping, and decision 5 removes most of the transient-timeout case that
motivates it.

**4. The heartbeat is built by `process_receipt` itself**, not passed in. A run
cannot be constructed without one, whichever entry point started it. This is
what closed ISSUE-031's signal half: narration had existed on exactly one of
four paths precisely because three call sites did not pass an argument.

**5. The job ceiling is derived from settings at enqueue time**, not a constant.
A constant that fits one model does not fit another, and this value had already
been wrong by exactly that mechanism. The sweep's cutoffs are derived from the
same quantity, and deliberately so: that is what stops the ceiling and the sweep
disagreeing about what "too long" means.

---

## Consequences

**A sweep nobody runs closes nothing.** Nothing in this work schedules
`receipts sweep`. The guarantee holds only where an operator schedules it, and
ISSUE-030's resolution says so rather than leaving it to be discovered.

**Two rules enforce "only touch a pending row", not one** — `find_stranded`'s
SQL clause and `strand_receipt`'s own guard. That redundancy is safe but it is
not free: on the write path each masks the other's deletion, so all three
mutations of the first implementation survived a green ten-test module. The
repair was one bounded property rather than three patches — *every rule
enforcing the refusal is pinned on a path where it is the only thing standing*:
the SQL clause via the dry run's exact row set, the guard via a direct call. An
earlier version of the design claimed there was "no separate check that could
drift out of agreement with the selection"; that was measured false and has been
corrected.

**Test expectations are derived independently of the subject** (ADR-0051). The
six-shape fixture writes its arithmetic out by hand rather than calling
`_cutoffs`, so a defect in the derivation moves the subject without moving the
expectation.

**Re-entrancy is sequential-only.** Two concurrent sweepers could each read
`PENDING` and each write. The outcome is benign — both write the same status,
and `enqueue_review` is idempotent on a UNIQUE `receipt_id` — but nothing here
claims to be race-proof. A genuinely concurrent guarantee is a conditional
`UPDATE ... WHERE status = 'pending'` and its own test.

**Stored timestamps are read as UTC explicitly.** SQLite has no native timezone
type: `12:00+00:00` goes in and a naive `12:00` comes out, and comparing that
against an aware cutoff raises `TypeError` — on SQLite only. Code without that
normalisation would pass review on Postgres and redden the suite.

---

## What this does not establish

- **The Redis join is unexercised.** `worker -> Redis -> route -> screen` stays
  untested because `redis` is not installed in this environment. The database
  path is now testable end to end offline, which is more than existed before.
- **Nobody has watched a screen.** Both halves of ISSUE-031 are pinned at the
  API and pipeline level. No browser pass has seen an `--inline` receipt
  narrate, and jsdom cannot see one. That is a browser pass, not a test.
- **The compose `VLM_*` environment is not landed.** It remains uncommitted; its
  `VLM_TIMEOUT_S: "3600"` implies a nine-hour derived ceiling under decision 5,
  which is worth deciding before it lands.
  **Correction, 2026-08-25 (`dbc1365`): it landed the same day, and the
  decision was taken.** Measured by calling the functions: `one_call` 10800s,
  job ceiling **32580s (9.05h)**, sweep `started_cutoff` 21600s (6h), sweep
  `unstarted_cutoff` **388800s (4.5 days)** — every window 30x its value at the
  120s default. The nine-hour ceiling is accepted on decision 2's terms: with
  the sweep carrying the guarantee, the ceiling is a resource guard on a worker
  slot and can be generous. **The 4.5-day unstarted window is the real cost**,
  and it is UNSTARTED_MARGIN's stated trade rather than a defect — a receipt
  enqueued and never picked up waits that long, and the progress route sweeps
  its own row on the same clock, so a waiting screen waits with it.
- **The SDK's `max_retries` is asserted, not set.** Setting it changes retry
  behaviour and remains ADR-0047's open question.
