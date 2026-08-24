# The terminal-state guarantee: heartbeat, sweep, and a derived ceiling

**Date:** 2026-08-24
**Status:** Design, approved section by section. Not yet built.
**Closes:** ISSUE-030 (the centre), ISSUE-029, ISSUE-031.
**Owner rulings taken:** five, recorded in "Decisions" below.

---

## 1. Context

`docs/MEMORY.md` states a guarantee: *"Nothing is silently dropped -- every
receipt reaches a terminal state."* ISSUE-030 records that it is false. An
interrupted run leaves a receipt at `pending` forever, and it was reproduced on
two unrelated paths on 2026-08-24: a SIGKILLed RQ work-horse, and a synchronous
`receipts reprocess` process that simply ended.

Three issues were filed as three owner rulings. They are one mechanism seen from
three sides.

- `ProgressSink` is `Callable[[ProgressEvent], None]` (`pipeline.py:94`), and
  `progress.py` is pure by construction -- no Redis, no pipeline import. So a
  sink that writes *durably* rather than to Redis is a drop-in, not a redesign.
- That durable write **is** a heartbeat. The signal ISSUE-030's reaper needs to
  tell *slow* from *stranded* is exactly the signal ISSUE-031 says is missing on
  three of four paths.
- Once a sweep exists, ISSUE-029's ceiling stops carrying the guarantee and
  becomes a resource guard, so it can be derived and generous.

This design therefore has one centre -- ISSUE-030 -- and the other two fall out
of it rather than being fixed alongside it.

### 1.1 What was measured for this design, with the instrument beside it

Everything below was re-derived here rather than relayed from the register
(ADR-0045: a relayed claim becomes yours).

| fact | instrument |
|---|---|
| Four `process_receipt(` call sites in `src/`; exactly one supplies `progress=` | `git grep -n 'process_receipt(' -- src` and `git grep -n 'progress=' -- src` |
| `review/queue.py:599` is `in_progress=`, a substring false positive | same greps, read |
| `eval/` never calls `process_receipt` -- its only mention is inside a docstring naming a test | `git grep -n 'process_receipt' -- eval`, with the pattern proven to match elsewhere |
| `receipts.updated_at` is read by no code: 3 hits in `src/`, all definitions in `models.py`, none in the API, serializers or frontend | `git grep -c 'updated_at' -- src`, then tree-wide excluding `models.py` |
| `_report(progress, attempts)` fires per model call: `extractor.py:252`, `:275` (inside the repair loop), `:284` | read `extractor.py:240-295` |
| `vlm_timeout_s` default `120`; `max_repair_attempts` default `1` | `git show HEAD:config/settings.py` |
| `DEFAULT_JOB_TIMEOUT_S = 900` at `worker.py:71` | `git grep -n` |
| One `complete_json` can take up to `3 x VLM_TIMEOUT_S`; the SDK's `max_retries` defaults to 2 and is never set here | ADR-0047 lines 222-224 |
| Whether to pin `max_retries` is explicitly **not decided** | ADR-0047 line 232 |
| No scheduler exists in the tree -- no rq-scheduler, no APScheduler, no FastAPI `lifespan` | `git grep -niE 'rq_scheduler\|apscheduler\|lifespan\|on_event'` over `src` and `pyproject.toml` |
| `_persist_outcome` closes a review task on auto-approval and updates the one existing row otherwise; `review_tasks.receipt_id` is UNIQUE | read `_persist_outcome`'s enqueue/close branch and `enqueue_review`'s docstring |
| `enqueue_review` keeps the more urgent priority and keeps `reason` in step with it | `enqueue_review` docstring |
| Tests build `session_factory` from a **file-based** SQLite in `tmp_path`, not in-memory; there is no `tests/conftest.py` | read the fixture in `tests/test_pipeline_merchant_hints.py`; `ls tests/conftest.py` fails |

Two notes on numbers that look like they disagree and do not. The compose
comment cites **590 s** triage at `max_edge=2048`, matching ADR-0047 line 55;
ISSUE-029 cites **696 s** triage from the container run. Different runs, both
real. And ADR-0047 lines 227-229 warn that any timing measured through the
client covers an unknown number of attempts, so neither is a per-call figure.

---

## 2. The property

> For every receipt row, if the process that was working on it stops without
> writing a terminal status, the row reaches a terminal status within a bounded
> time -- on every path, and for every cause of stopping.

Terminal means any `ReceiptStatus` other than `PENDING`. `PENDING` is the only
non-terminal member.

The falsifier is a single row: `status='pending'`, heartbeat cold, and no sweep
that would touch it. One query. That is what makes this pinnable rather than
argued, and it is deliberately **one bounded property enforced at both ends**
rather than an enumeration of interruption causes (review standard 19).

**The guarantee has two halves and they carry different kinds of evidence.**
That an interruption leaves a cold row is established by *observation* --
ISSUE-030 recorded it on two unrelated paths -- and by no gate, because a
SIGKILL cannot be simulated in-process. That a cold row reaches a terminal
status is established by tests. Section 7 says so again where it matters.

---

## 3. Decisions

1. **Liveness is a heartbeat**, written as the run works, not an age threshold
   on the row and not a lease. Only a heartbeat separates *slow* from
   *stranded*, which is the gap the register names.
2. **Two runners.** An explicit sweep command bears the guarantee; a single-row
   sweep on the progress route bears the latency. Neither alone is sufficient:
   the command alone leaves a waiting screen polling until the next interval,
   and the route alone never reaches a receipt nobody looks at -- which is the
   silent drop the guarantee exists to forbid.
3. **A swept receipt becomes `needs_review`**, following `_persist_failure`'s
   convention. No new `ReceiptStatus` member: its own docstring calls the
   values stable, and the review UI, serializers and export filter on them.
   Automatic requeue was rejected for now -- it needs an attempt counter and
   risks a poison receipt looping, and deriving the ceiling (decision 5)
   removes most of the transient-timeout case that motivates it.
4. **The heartbeat lives in two columns on `receipts`**, not a side table.
   `updated_at` is provably inert (section 1.1), so the cost of it coming to
   mean "last heartbeat" is documentation rather than breakage.
5. **The job ceiling is derived from settings at enqueue time**, not a constant.
   A constant that fits one model does not fit another, and this value has now
   been wrong by exactly that mechanism.

---

## 4. Components

| # | component | closes |
|---|---|---|
| 1 | A heartbeat sink -- a `ProgressSink` that stamps the receipt row | ISSUE-031's signal, ISSUE-030's discriminator |
| 2 | A sweep predicate plus a `_persist_failure`-convention write | **ISSUE-030** |
| 3 | Two runners: a CLI command, and the progress route's existing session | ISSUE-030's time bound |
| 4 | A derived job ceiling | **ISSUE-029** |

What does **not** change: `progress.py` stays pure, `ProgressEvent` gains
nothing, and the Redis sink and `GET /progress`'s Redis read stay as they are.
The heartbeat is an *additional* sink, so the queue path narrates to both and
nothing that works today stops working.

---

## 5. The heartbeat

### 5.1 Granularity, which is the keystone

A stage-entry-only heartbeat would be useless: `extract` dominates a run
(ADR-0039's figure for this box is ~1896 s per receipt), so the mark would go
cold for tens of minutes during entirely normal work and the threshold would
degrade back into the age-guess that decision 1 rejected.

It does not. `extract_with_repair` calls `_report(progress, attempts)` at
`extractor.py:252` after the first extract, **at `:275` inside the repair
loop** -- once per repair or re-extract -- and once more at `:284` choosing the
best attempt.

> **The maximum gap between two heartbeats is one model call.**

This is the keystone. The sweep threshold and the job ceiling now derive from
the same quantity, so they cannot drift into disagreeing about what "too long"
means.

### 5.2 Schema

Two columns on `receipts`, written as a pair:

| column | type | meaning |
|---|---|---|
| `progress_stage` | `text`, nullable | what the run was doing when last seen alive |
| `progress_at` | `timestamptz`, nullable | when that was |

The stage earns its place twice: it lets the sweep's reason name the stage the
run died in, matching `_persist_failure` rather than saying a bare
"interrupted"; and it is the durable narration the no-Redis paths currently
lack.

**No `progress_detail` column.** Both existing details are structurally
content-free today -- `f"attempt {n} ({pass_name}): {k} error(s)"` and
`f"kept attempt {k} of {n}"`, counts plus a closed-set pass name. But
persisting detail would bring a new write path under the non-negotiable that a
full PAN is never persisted, for a future detail nobody has written. And it is
not needed: ISSUE-031's own resume says the open repair-loop question needs the
queue path with a raised ceiling, which section 8 delivers.

### 5.3 The writer

A `ProgressSink` that opens its **own short session** per event, writes the two
columns, commits, and closes. It never reuses the pipeline's session: that one
may be mid-stage or already rolled back, which is the same reasoning
`_persist_failure` documents for using a fresh session.

**On ADR-0006.** Its decision 2 is scoped to `persist/repository.py`: functions
`flush()`, the *caller* owns the transaction, with `apply_corrections` as a
documented committing exception. The sink is the caller. A repository function
that flushes plus a sink that commits satisfies the ADR as written, and no new
exception is needed.

**A raising sink cannot take down a run, and this is already true.** Three
independent guards exist and all three were read: the `try`/`except` inside
`_stage`, the one inside `_report`, and the one guarding the best-attempt event
in `extract_with_repair`. A database blip during a heartbeat
costs narration, never the extraction. This design adds a sink to already
guarded call sites; it does not add a failure path.

### 5.4 Cost

Roughly 8 stage events plus 1-3 extract events, so about **10 short
transactions per receipt**. Against a run measured in tens of minutes that is
noise.

### 5.5 Composition

The worker needs both sinks -- Redis for the live screen, the row for the
sweep. That is one small `fan_out(*sinks)` helper. Making the Redis writer also
write the row was rejected: it would put a database dependency inside the
transport and break `progress.py`'s purity.

### 5.6 The consequence, stated rather than buried

`Receipt.updated_at` carries `onupdate=now()`, so heartbeats advance it and it
comes to mean "last heartbeat" rather than "content last changed". Nothing
reads it today (section 1.1), so the cost now is zero and the cost later is
documentation. The rejected alternative was a side table, which would have kept
`updated_at`'s meaning at the price of a join in the sweep and a cascade to
maintain.

---

## 6. The sweep

### 6.1 The predicate, and the defect in the obvious version

The naive form is `status='pending' AND COALESCE(progress_at, created_at) <
cutoff`. It is wrong, and the reason is structural.

A `pending` row with no heartbeat has three causes, not one:

| cause | stranded? |
|---|---|
| started, process died | **yes** -- sweep it |
| enqueued, still waiting behind a backlog | **no** -- healthy, do not touch |
| ingested, never enqueued at all | yes -- this is the silent drop |

The naive predicate sweeps a healthy queued receipt as soon as the backlog
exceeds the threshold. So the sweep needs **two thresholds, because these are
two failure modes on two natural timescales**:

```
-- started, then went cold
status = 'pending' AND progress_at IS NOT NULL AND progress_at < now() - :started_cutoff

-- never started at all
status = 'pending' AND progress_at IS NULL     AND created_at  < now() - :unstarted_cutoff
```

`started_cutoff` is one model call times `STRAND_MARGIN` -- the section 5.1
keystone. `unstarted_cutoff` is deliberately much longer: long enough that a
real backlog has drained, because nothing on the row distinguishes "queued"
from "never enqueued" without asking Redis, and asking Redis would surrender
the path-independence that is the whole point.

### 6.2 The bound this accepts

A queue backlog longer than `unstarted_cutoff` produces a spurious sweep. It
self-corrects, because `needs_review` is not `reviewed` and the worker's own
write overwrites it.

**The review task self-corrects too.** Verified by reading `_persist_outcome`: when the
later run auto-approves it calls `close_review_for_receipt`, whose docstring
gives exactly this reason -- a task left open after auto-approval would be
handed out by `GET /review/next` and would inflate the `/metrics` backlog. When
the later run routes to review instead, `enqueue_review` updates the one row
rather than adding a second, because `review_tasks.receipt_id` is UNIQUE. So a
spurious sweep leaves neither a duplicate task nor a stale approved-but-queued
one.

**One residual it does leave.** `enqueue_review` keeps the *more urgent*
priority and keeps `reason` in step with it. The sweep writes
`_FAILURE_PRIORITY` (1, the most urgent), so a receipt swept and then
legitimately re-processed to `needs_review` at a calmer priority keeps the
sweep's priority **and its reason** -- a reviewer would read "interrupted"
where the real finding was something else. This is accepted rather than fixed:
in the genuine stranded case, which is the case this exists for, both the
priority and the reason are correct.

### 6.3 The reviewed-row refusal is structural

A machine run never overwrites a `reviewed` row. Here `reviewed` is excluded by
`status='pending'` -- *the same clause that defines the work set*. There is no
separate check that could drift out of agreement with the selection. This is
the one-property-enforced-at-both-ends shape rather than two rules that must
agree.

### 6.4 The write

Follows `_persist_failure`'s convention: fresh session, a reason naming the
stage taken from `progress_stage`, a review task opened, and the reason routed
through `redact_pan`. The redaction is free and provably unnecessary today --
the reason is authored here and contains no receipt content -- but routing it
anyway means nobody later has to reason about whether this path is exempt from
ADR-0022.

**This design does not promise to reuse `_persist_failure` verbatim.** That
function takes a `_StageFailure`, a `ReceiptJob` and a `phash`; a sweep has a
row instead. Either the shared part is extracted or a sibling is written and
pinned to match on what matters. That is an implementation decision, and
claiming reuse here would be a rationale this document cannot cash (ADR-0048).

### 6.5 Concurrency

The command and the route can race the same row, so the update is conditional
-- `UPDATE ... WHERE id = :id AND status = 'pending'` -- and the loser updates
zero rows and does nothing. Idempotent by construction.

### 6.6 The two runners

1. **A sweep CLI command.** Bears the guarantee. Idiomatic here -- the CLI is
   already `add_parser`-structured -- needs no new dependency, and matches
   ADR-0036's "an operator step, not an entrypoint". It takes `--dry-run`,
   because a command that marks receipts should be inspectable before it is
   trusted.
2. **The progress route.** `get_receipt_progress` already opens a session and
   loads the row to read `status`, so the row and the session are in hand and
   the hook costs no extra query. **Single-row only**: a table-wide sweep on a GET
   would put unbounded work on a request path. It sweeps *this* receipt if it
   is `pending` and cold, then answers -- so the screen stops polling the
   moment somebody is actually waiting.

No periodic runner is introduced, because no scheduler exists in the tree
(section 1.1) and adding one is a larger decision than this design needs.

---

## 7. The sink wiring

ISSUE-031 reads as "three call sites are missing an argument", and the obvious
fix is to add `progress=` to three more. **That fix is an enumerated defence**:
it closes the three that exist, and the fifth call site somebody adds later is
silent again, which is how the guarantee gets its hole back.

Two different things are being threaded and they differ in kind:

| | heartbeat | Redis narration |
|---|---|---|
| purpose | carries the **guarantee** | cosmetic, for a waiting screen |
| may a call site omit it? | **no** | yes, and three do |
| needs | the `session_factory` already required | a Redis connection that may not exist |

So they are wired differently:

- **The heartbeat is built inside `process_receipt`**, from the
  `session_factory` that is already a required keyword argument. Always on, not
  injected. A caller cannot construct a silent run, so the property is enforced
  at the one place all four paths already pass through rather than at four call
  sites that each have to remember.
- **`progress=` stays exactly as it is** -- optional, default `None`, injected,
  carrying the Redis transport. The worker keeps passing it. `process_receipt`
  fans out internally to the heartbeat plus `progress` when given.

**What this changes.** Every existing caller now performs about ten short
writes per receipt where it previously performed none. Eval is unaffected: it
goes through `run_receipt` (ADR-0047) and never calls `process_receipt`
(section 1.1). The offline suite already supplies a `session_factory`, so
nothing breaks by construction -- but the implementation **pins that heartbeat
sessions never nest inside a pipeline session**. The ordering was read and they
do not (`_stage` fires the sink before `try: yield`, so before any stage body
opens its own session), but nested sessions on in-memory SQLite is a classic
trap and deserves a pin rather than a belief.

**The route falls back to the row.** `GET /receipts/{id}/progress` reads Redis
first and, when Redis has nothing to say, reports `progress_stage` from the row
it has already loaded. This is what turns ISSUE-031 from "the signal now
exists" into closed: `--inline`, `reprocess` and `process_batch` narrate to the
screen instead of showing an empty STEPS list forever. The contract is
unchanged -- `status` is still the truth, `stage` is still only narration.

---

## 8. The ceiling

### 8.1 The derivation

```
one model call    = vlm_timeout_s x 3                (ADR-0047 decision 8)
calls per receipt = 2 + max_repair_attempts          (triage, extract, repairs)
ceiling           = (one model call x calls per receipt) + NON_MODEL_BUDGET_S
```

**Two margins, deliberately different in kind, and they must not be conflated
under one word.**

| name | kind | what it covers | why |
|---|---|---|---|
| `NON_MODEL_BUDGET_S` | additive, seconds | image decode, perceptual hash, dedupe and merchant reads, scoring, the persist write | this work is bounded and small regardless of the model, so it adds rather than scales |
| `STRAND_MARGIN` | multiplicative, dimensionless | the gap between "a call is taking its full budget" and "the process is gone" | a live run mid-call must never be swept, and that risk scales with the call, so it multiplies |

Both are named constants defined once, and neither is written as a bare literal
at a use site.

`enqueue_receipt` already accepts a `job_timeout` parameter while the default
submit path uses the constant, so the wiring point exists.

### 8.2 The sharpest statement of ISSUE-029

At **code defaults** -- `vlm_timeout_s=120`, `max_repair_attempts=1` -- the
derived worst case is **1080 s** and the constant is **900**. So
`DEFAULT_JOB_TIMEOUT_S` is below its own worst case on default settings, on any
hardware. ISSUE-029 is not a property of this box; granite only made it
visible.

### 8.3 The premise that must be pinned rather than asserted

The `x 3` rests on the OpenAI SDK's default `max_retries`, which **nothing in
this repository fixes**, and ADR-0047 line 232 says explicitly that whether to
pin it is not decided. Today, if that default changes, the ceiling and the
sweep threshold both go silently wrong and **nothing fails**. Naming what would
fail is the ADR-0048 test and the answer is "nothing", which makes it a
finding.

So: **add a test asserting the observed default.** That is cheap and
non-behavioural. Actually *setting* `max_retries` changes retry behaviour and
remains ADR-0047's undecided question; this design does not take it.

### 8.4 Both bounds derive from one quantity

| bound | formula | purpose |
|---|---|---|
| sweep `started_cutoff` | one model call x `STRAND_MARGIN` | how fast a strand is noticed |
| job ceiling | (one model call x calls per receipt) + `NON_MODEL_BUDGET_S` | resource guard on a worker slot |

They cannot drift into disagreeing, because there is one number underneath.

### 8.5 The honest floor on detection latency

There is no heartbeat *inside* a model call, so nothing can conclude "dead"
sooner than one call can legitimately take. At this box's configured
`VLM_TIMEOUT_S` that is tens of minutes. This is not a weakness to fix later;
it is what the hardware buys, and shortening it means lowering
`VLM_TIMEOUT_S`, not tightening the sweep.

### 8.6 A flag on the held compose change

The uncommitted `docker-compose.yml` sets `VLM_TIMEOUT_S: "3600"`, which
implies a derived ceiling of nine hours and a detection latency of three. The
derivation's real value is making that visible. The lever is that setting, not
the ceiling, and it is worth revisiting when the compose env lands.

---

## 9. Testing

The rule shaping this section is **ADR-0051: a guard must not share its
derivation with its subject.**

### 9.1 The ADR-0051 instance in this design

The obvious ceiling test computes its expected value by calling the same
derivation the subject calls. Change the formula and both sides move together:
the test stays green while the ceiling goes wrong. **The ceiling tests
therefore assert literal numbers** -- `settings(vlm_timeout_s=120,
max_repair_attempts=1)` against a written-out `1080 + NON_MODEL_BUDGET_S`,
with that constant's value also written out rather than imported. The mutation goes
where the subject computes the ceiling, and the literal is what refuses to move
with it.

### 9.2 The discriminating fixture

A mutation kills nothing when the discriminating case is in none of the
supplied tests. Every sweep test therefore runs against **one fixture holding
all six shapes**: stranded-started, warm-started, old-never-started,
recent-never-started, a terminal row, and a `reviewed` row. A fixture of only
stranded rows would stay green with the entire `progress_at` clause deleted.

### 9.3 Guarantees and their mutations

| # | guarantee | mutation, in the subject |
|---|---|---|
| 1 | `process_receipt` heartbeats with no `progress=` supplied | delete the sink construction inside `process_receipt` |
| 2 | a stranded row reaches `needs_review` naming its stage | break the `progress_at < cutoff` clause |
| 3 | a `reviewed` row is never touched | drop `status='pending'` -- reddens 2 and 3 together, demonstrating section 6.3 |
| 4 | the two thresholds are distinct (the backlog case) | collapse them into one |
| 5 | sweeping twice opens one task, not two | drop the conditional `AND status='pending'` on the UPDATE |
| 6 | the ceiling derives from settings | change the formula; literals refuse to follow |
| 7 | the SDK's `max_retries` default really is 2 | section 8.3's premise, asserted directly |
| 8 | the route prefers Redis and falls back to the row | remove the fallback; separately, remove the preference |
| 9 | the route sweeps this row only | make it table-wide -- a second cold row must stay untouched |

On #1: a test that builds the sink itself and calls it proves the *sink* works,
not that `process_receipt` uses it -- precisely the guard-shares-derivation
shape. The load-bearing test must never mention the sink and must only call
`process_receipt`.

#1 is also why section 7's shape pays off: because the heartbeat is built
inside `process_receipt` rather than passed by callers, the universal claim
needs no AST enumeration of call sites the way `run_receipt`'s does. One test
covers every present and future caller by construction.

A migration for the two columns is covered by the existing
`tests/test_migrations.py`.

### 9.4 What no gate here will see

- **A real interruption cannot be simulated in-process.** These tests pin what
  the sweep does *given* a cold row. That a SIGKILL *produces* a cold row is
  established by observation (ISSUE-030, two unrelated paths) and by no gate.
- **`worker -> Redis -> route -> screen` stays unexercised**, because `redis`
  is not installed in this environment. This design does not close that. It
  does make the *database* path testable end to end offline, which is strictly
  more than exists today.
- **Nobody will have looked at the screen** narrating an `--inline` receipt.
  jsdom lays nothing out and Vitest sets `css: false`. If that matters before a
  demo, it is a browser pass, not a test.

---

## 10. What this design does not decide

- **Whether to pin the SDK's `max_retries`.** Section 8.3 adds a test asserting
  the observed default; changing the value stays ADR-0047's open question.
- **Whether a swept receipt is ever requeued automatically.** Decision 3 takes
  `needs_review` and leaves retry to a human. Layering retry on later does not
  require redoing this.
- **Whether the upload screen should say "this receipt has stopped making
  progress"** rather than reporting a terminal status like any other.
  ISSUE-030's resume item 4. The screen becomes correct either way once the
  status goes terminal.
- **Whether the compose `VLM_*` env lands**, and at what `VLM_TIMEOUT_S`.
  Section 8.6 flags it; it is a separate change.
- **Whether a periodic runner is introduced.** None exists in the tree and this
  design adds none; scheduling the sweep command is an operator's choice.

---

## 11. References

- ISSUE-029, ISSUE-030, ISSUE-031 in `docs/KNOWN_ISSUES.md` -- the diagnoses
  and the resume steps.
- **ADR-0006** -- injected session, caller commits. Section 5.3.
- **ADR-0013** -- ingest does not enqueue; `--inline` is the no-Redis path.
- **ADR-0022** -- failure-text egress. Section 6.4.
- **ADR-0036** -- an operator step, not an entrypoint. Section 6.6.
- **ADR-0039** -- the local path is a liveness check; ~1896 s per receipt here.
- **ADR-0045** -- a relayed claim becomes yours. Section 1.1 exists because of it.
- **ADR-0047** -- decision 8 and lines 222-232. Sections 8.1 and 8.3.
- **ADR-0048** -- a rationale is a second claim. Sections 6.4 and 8.3.
- **ADR-0051** -- a guard must not share its derivation with its subject. Section 9.
