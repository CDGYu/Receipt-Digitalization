# ADR 0011 — The terminal-state contract, and the two guards on model calls

**Status:** Accepted (implements SPEC §14.10 and §18; introduced with P4.T4)

## Context

`process_receipt` is the only function the queue worker calls, which makes it the
single place where two rules become enforceable rather than aspirational:

- **Nothing is ever silently dropped** (SPEC §18). Every receipt must reach a
  terminal state. "A job that vanishes is worse than a job that fails."
- A worker draining a backlog is unsupervised. Left alone it can hammer a
  provider into rate-limiting the whole fleet, or spend without bound on one
  pathological image that never parses.

A third problem met the same function. `run_receipt` validates the extraction the
model produced and normalizes *afterwards*, so the report and the extraction
describe different objects. On the eval path that is harmless. On the service
path — which stores the report next to a confidence score derived from the
normalized object — it means a persisted score can carry a date-null penalty the
persisted report does not explain, and an ambiguous date raises R030 and spends a
repair round arguing with a decision the normalizer already made correctly.

## Decision

**Every stage is wrapped, and the stage name travels on the exception.** The
stages are a declared tuple, `STAGES = ("load", "preprocess", "dedupe", "triage",
"extract", "normalize", "score", "persist")`. An internal `_StageFailure` carries
the failing stage; an inner one passes through the wrapper untouched so the
*innermost* stage wins. This matters because normalization runs inside the repair
loop rather than after it — without the tag, a normalizer failure would be
reported as `extract`.

Any stage failure writes a `needs_review` row **and** a review task, naming the
stage as the reason. An existing row is updated rather than re-inserted, so a
retry of a job that already persisted something cannot fail on the primary key
while recording that it failed.

**Exactly one case raises: nothing could be written at all** (an unreachable
database). Swallowing that would be the silent drop the rule forbids; raising
hands the job to the queue's failed registry where an operator can see it. Every
stage, plus this case, has a test that asserts the terminal status, the stage
attribution, the persisted row, and the queued review task.

**Normalization is handed to `extract_with_repair` as its `normalize_fn`.**
Validation, the repair loop's best-attempt ranking, the score, and the persisted
row then all see one object: the normalized extraction. Measured on a receipt
printing `03/04/2026` — before: `[R030]` ERROR, confidence `0.550`, `needs_review`,
one repair round wasted; after: `[R011]` INFO, confidence `0.900`, `auto_approved`,
two model calls.

**`run_receipt` is deliberately left alone.** It feeds the committed eval
baseline, where validating what the model actually said is the honest
measurement; changing it would silently move the baseline. The two docstrings
state the difference and why.

**Both guards are a `VLMClient` decorator (`GuardedVLMClient`), not pipeline
logic.** Triage, extract, repair — and self-consistency when it lands (M6) — are
covered without `extractor.py` knowing the guards exist, and without a list of
call sites to keep in step.

- `VLM_MAX_CONCURRENCY` (default 4) is a **process-global** semaphore, shared by
  every receipt the process is working. A per-run semaphore would be no cap at
  all once a batch or worker pool is draining a backlog. A cap *across* processes
  needs a distributed lease in Redis and is deliberately not attempted; until
  then the fleet bound is this value times the worker count, which is at least a
  number an operator can compute.
- `MAX_COST_USD_PER_RECEIPT` (default `Decimal("0.25")`) accumulates
  `VLMResponse.cost_usd`, checked *before* each call and charged after — the cost
  of a call is not knowable until it returns, so a run may exceed by one call and
  then stops. It raises `CostCeilingExceeded`, a **`VLMPermanentError` subclass**,
  so `with_retry` can never retry a budget stop: retrying one would spend exactly
  the money the guard exists to protect.

## Consequences

- `process_receipt` returns a frozen `ProcessResult`, **not** the ORM row SPEC
  §14.10 names. Sessions are opened and closed per phase (a connection must not
  be held across a multi-second model call) and the session factory uses the
  default `expire_on_commit=True`, so a returned `Receipt` would raise
  `DetachedInstanceError` on every attribute. Use `get_receipt` for the full row.
- **Semantic (merchant + date + total) dedupe is deliberately not wired in.**
  `merchant_id` is NULL on every row until the merchant registry (M5), so
  `find_duplicate_by_content` would degenerate to "same date and same total"
  across all merchants and merge two genuinely different purchases. A missed
  duplicate is recoverable; a silent merge is not. Wire it with M5.
- A phash duplicate is terminal `REJECTED` with `duplicate_of` set, no review
  task, and zero model calls (§18 cost control).
- Failure review priority is `1`, not `0`. `enqueue_review` never demotes, so
  parking every transient provider outage at `0` would permanently outrank
  genuine §12-urgent work.
- Three settings exceed the §17 list — `VLM_MAX_CONCURRENCY`,
  `MAX_COST_USD_PER_RECEIPT`, `STORAGE_ROOT`. All have working defaults. §17
  should absorb them.
- `_attempt_prompt_hash` reconstructs each call's prompt rather than threading
  prompts out of the repair loop (prompt building is pure). **When merchant hints
  and few-shot examples land (M5), the same values must be passed there** or the
  stored hash drifts from the prompt actually sent.
- Known gap, not yet fixed: `CostGuard._as_money` refuses `float` but has no
  `is_finite()` gate, unlike `repository._coerce_money`. A `Decimal("NaN")` cost
  would make `spent` NaN, and `NaN >= ceiling` is always `False`, so the ceiling
  would silently never fire — the same shape of bug ADR-0007 records.

## References

SPEC §14.10 (`process_receipt`), §18 (silent drops, cost control); ADR-0001
(`Decimal`), ADR-0006 (caller commits), ADR-0007 (money integrity), ADR-0008
(review-queue idempotency); `docs/KNOWN_ISSUES.md` (ISSUE-001).
