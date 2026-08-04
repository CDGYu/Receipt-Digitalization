You are continuing work on the **Receipt Digitization System**, a VLM pipeline
that turns receipt photos into accounting-grade structured data. Pick up exactly
where the last session left off.

**Read these first, then confirm the state back to me — and verify the snapshot
below against the repo rather than trusting it.** It has been stale at the start
of several sessions, once by a whole milestone, and once it was rewritten
*mid-milestone* by a subagent working outside its lane, so it described a branch
that no longer existed. ADR-0019 made the refresh part of closing a milestone;
**ADR-0021 makes it part of ending any session** (its 2026-08-02 correction
widened the freshness check to include `docs`). This verification step is
permanent.

**No branch is in flight.** The admin-release milestone was closed and merged
(true fast-forward `c3a268c` → `9d31679`). **`main` is NOT pushed** — see below.

## Reading order

1. **`docs/MEMORY.md`** — current state, decisions already made, environment,
   blockers, deferred and parked items. Its "Admin release — complete and
   merged" section records the last milestone.
2. **The ledgers** — `.superpowers/sdd/2026-08-04-admin-release/progress.md`
   (complete: three task entries, **seven plan defects**, three controller
   rulings, and "THE CLOSE" — a whole-branch review that ran **25 mutations**,
   one fix wave, one scoped re-review, and two parked residuals).
   `2026-08-03-review-ui-error-recovery/progress.md`,
   `2026-08-03-failure-egress-redaction/progress.md`,
   `2026-08-02-currency-bound-and-fixture-race/progress.md`,
   `2026-07-31-pan-grouping/progress.md`, `2026-07-31-pan-hardening/progress.md`
   are completed prior milestones; `2026-07-29-review-ui/progress.md` holds
   Phase 5's parked items. **`.superpowers/` is gitignored — open ledgers by
   path; nothing in them is findable by searching the tracked tree.**
3. **`docs/adr/README.md`, then the ADRs (0001–0025).** Mandatory before
   touching the matching area. Session-relevant highlights:
   - **0025** — the admin release: admin-only, `OPEN` idempotent, `DONE`
     refused, log-plus-echo audit, the accepted re-claim residual, and the
     third release-vs-complete race order. **Read before touching
     `release_task`, `review_release`, or the queue's state machine.**
   - **0016 + its dated note** — resume-before-claim, which ADR-0025 does
     **not** replace. 0025 is the policy decision 0016 deferred.
   - **0024** — the review UI's error-recovery contract. Its terminal `taken`
     state is now driven by a real 403 from the release.
   - **0023 + its two dated corrections** — parallel task agents share one
     worktree: commit every green step; never dispatch two tasks that touch
     one file; never repair a peer's tree; **restore a mutation from a byte
     copy, never `git checkout --`, and re-take the copy after any commit to
     that file**; release an implementer explicitly when its task closes.
   - **0022** failure-text egress · **0018 + 0020 + corrections** PAN ·
     **0015** the review UI's same-origin/`/app` rules · **0007** money
     integrity · **0006** the ValueError boundary · **0017** the gate runner ·
     **0019 + 0021** session continuity and this snapshot's verification.
4. **`.kiro/steering/receipt-system.md`** — always-on rules (gitignored,
   untracked, still on disk).
5. **`IMPLEMENTATION_PLAN.md`** · **`docs/KNOWN_ISSUES.md`** (ISSUE-001 — do
   not re-derive) · **`RECEIPT_SYSTEM_SPEC.md`** §§ as needed.

## Where we are

- **`main` @ `9d31679`**, with this handoff refresh riding on top as a
  docs-only commit. The check:

  ```
  git log --oneline 9d31679..main -- src tests frontend docs ":(exclude)docs/MEMORY.md" ":(exclude)docs/NEXT_SESSION_PROMPT.md"
  ```

  **Empty means this prompt is current.** Any output means the tree moved
  after it was written.
- **`main` IS NOT PUSHED.** At the admin-release close the user chose "merge
  locally"; no `main` push was asked for or granted, so `origin/main` is still
  at `c3a268c` while local `main` is at `9d31679` plus this refresh. **Raise
  the push early** — the standing rule is that pushing `feat/*` is authorised
  and **every `main` push needs a fresh one-time ask.**
  `feat/admin-release` is merged, kept, and pushed at `9d31679`.
- Gates at `9d31679`, controller-run on `main` post-merge:
  `python scripts/verify.py` **all five PASS**; pytest **953**; Vitest **221**
  (19 files). **`src/` changed this milestone**, so the outside-repo import
  check applied and was run from `/c/Users` — keep applying it whenever a
  Python module changes.

### What the last milestone shipped

**Phase 5 follow-up #3 — the inverse of a claim**, which the system had never
had. `release_task` (`review/queue.py`) returns a claimed task to the queue:
`IN_PROGRESS` → `OPEN`, `assigned_to` cleared, `priority`/`opened_at`/`reason`/
`closed_at` untouched so it keeps its queue position. `OPEN` is idempotent;
**`DONE` is refused**, because on a receipt confirmed without edits
`review_tasks.assigned_to` is the only record in the system that a human looked
at it. `POST /review/{task_id}/release` is admin-only, 404s on an unknown task
from its own existence check, 400s on a closed one, and returns `_task_summary`
plus a `released_from` sibling key. Its log line names task, prior holder and
admin — and **not `reason`** (ADR-0022), pinned by test.

**ADR-0024's terminal `taken` state now has a live producer**, driven
end-to-end by a real admin release rather than a hand-set fixture.

**The close:** whole-branch review on the strongest model, **25 mutations** in
an isolated byte copy — 0 Critical, 6 Important, 11 Minor. **20 died, and
deleting the whole route turns SEVEN tests red.** ONE fix wave (ten items,
three commits), one scoped re-review, all ten addressed; two Minor residuals
parked.

## Non-negotiables

Unchanged: `Decimal` money path; pure validation; stable rule IDs; null over
confident-wrong; **a full PAN never persisted**; nothing silently dropped;
a machine run never overwrites a `reviewed` row; optional-import discipline;
tool-use structured output; few-shot images first; consistency never cached;
`python -m pytest` offline and Node-free. **PAN:** ADR-0018 + 0020 + their
corrections; any `_PAN_RE` change replays the committed battery both ways,
two-instance-tests, keeps the structural guards green. **Egress (ADR-0022):**
failure text goes through `redact_pan` at every place it leaves the process.
**Queue (ADR-0006):** explicit `Session` first, flush, **never commit**,
`ValueError` at the boundary. **Frontend (ADR-0015):** money is a string; no
`<input type="number">`; no `valueAsNumber`; no `CORSMiddleware`; `/app/*`
only. **Error recovery (ADR-0024):** the summary alert always renders; the
classifier never invents copy; the stash never touches browser storage; and
**`PATCH /receipts/{id}` stays claim-unaware** — a displaced reviewer's edits
still land and only the close fails. That is the contract's premise.

## The work, in order

### 1. Push `main` — ask first

Local `main` is two commits ahead of `origin/main` and unpushed. Raise it.

### 2. Phase 5 follow-ups — two left

1. **A read route for `corrections`.** Nothing does `select(Correction)`, so a
   reviewer cannot see the correction history of the receipt they are
   correcting and an auditor needs database access. Additive; **blocked on an
   auth ruling** — reviewer-visible, or admin-only?
2. **An ASGI entry point / deployment story.** `create_app` is a factory
   nothing under `src/` calls. `scripts/serve_review_e2e.py` is deliberately
   e2e-scoped — inheriting a deployment policy from an e2e launcher is the
   mistake to avoid.

### 3. The admin UI — a committed next milestone (user ruling, 2026-08-04)

The release shipped API-only by design. Driving it from a browser needs, in
order, **two backend routes that do not exist**:

- **`GET /auth/me`** — the frontend cannot learn a role after a reload.
  `LoginPage.tsx` discards the login response body, `session.ts` holds one
  boolean and no identity, and `build_auth_router()` has only `/auth/login`
  and `/auth/logout`.
- **A task-listing route** — nothing lists review tasks, so an admin has no
  way to find a task id. `/metrics` returns `QueueStats` (counts and the open
  backlog by priority), not rows.

Then the frontend's first role-awareness and a new `/app` admin surface. Each
new route is an API contract and deserves its own design.

### 4. Phase 6 — merchants & few-shot (P6.T1)

Unchanged: `merchants/{fingerprint,registry}.py` is greenfield; few-shot images
first, target last; hints end "trust the image"; measure top-10-merchant
accuracy before/after — **which is blocked on ISSUE-001**, so Phase 6 can be
built but not validated. Five things unblock here: semantic dedupe into
`process_receipt`; the same hints into `_attempt_prompt_hash`;
`merchant_default_currency` at its plug-in point in `pipeline.py` (**re-verify
the line — the file has grown**); the `image_phash` gap; `Merchant.receipt_count`
(nothing writes it). `VAT Reg. TIN` is the strongest fingerprint on this corpus.

### 5. Phase 7 — self-consistency (P7.T1)

Unchanged: wire `run_consistency` (`extract/extractor.py`, zero references in
`pipeline.py`) for handwritten/low-legibility; **gate on
`triage.is_handwritten`, never `document_type`**; consistency runs never cached.

### 6. Phase 8 — calibration & eval-harness honesty

Unchanged: P3.T6/P8.T1 threshold sweep + weights into `config/rules.yaml`
(**blocked on ISSUE-001**); P8.T2 grow the held-out set; P8.T3 the all-failed
eval run still persists `"auto_approval_precision": 1.0` to JSON.

### 7. Still open from earlier phases

Unchanged: R060/R061 grounding decision (also gates bbox); score
`is_handwritten` from triage too; `is_receipt` has no consumer (never
hard-reject on it); blank pre-printed template rows (sibling of R052).

### 8. Parked, with rulings (see the ledgers)

- **Parked at the admin-release close** — both introduced by the close's own
  fix wave, both single-sentence, bundle with the next legitimate edit:
  `tests/test_api_write.py`'s machine-key docstring generalizes falsely about
  where other routes get their key row; `tests/test_review_queue.py`'s race
  test gives a repair instruction that is wrong for one of its own red modes
  (the mechanism assertion can go red with the outcome unchanged).
- **Layer-wide, measured:** nothing pins the queue's caller-commits rule —
  deleting `release_task`'s `flush()` or turning it into a `commit()` leaves
  the suite green, and the same holds for `enqueue_review` and `next_task`.
- **The admin release's accepted residuals (ADR-0025):** the still-polling
  displaced reviewer can re-claim the task; and the third race order, where a
  release committing inside the holder's window lets their `close_task` write
  `DONE` over an already-cleared `assigned_to`. Both recorded with mechanism
  and reachability; the race is reproduced deterministically and pinned.
- **Parked at the review-UI error-recovery close:** the `42/42` comment in
  `frontend/tests/review-screen.test.tsx`; `edit()` not resetting `submit`;
  no `aria-invalid`; the comment-only select/checkbox invariant; the sign-out
  confirm's wording after a landed write; keystrokes during an in-flight
  submit not stashed. **Nobody has viewed any of that UI in a browser.**
- **Two queued PAN scoped decisions** — the grouping residual (76 of 97 band
  shapes; two priced routes) and the `{1,2}` separator surface (36 spellings,
  30 mixed, pinned; narrow or keep).
- Plus the standing list in MEMORY.md's "Deferred follow-ups".

### 9. LAST — ISSUE-001, deferred by the user until the system is built

Unchanged: read `docs/KNOWN_ISSUES.md`, do not re-derive; hosted tool-capable
model needed (rotate the echoed Gemini key first); until it runs, no measured
accuracy numbers and no real precision claim.

## Running it

- Two suites: `python -m pytest` (**953** on `main`) and Vitest in `frontend/`
  (**221**, 19 files). `npm test` does NOT type-check — run `npm run typecheck`
  too. `python scripts/verify.py` is what "passing" means (ADR-0017).
- Piped pytest output can lose its final summary line — `--junitxml`, read
  counts from the XML. Lint is `python -m ruff check .`.
- **`pytest -k` matches substrings, not words.** `-k release` does **not**
  match `test_releasing_*`. Measured: it collected 8 of 9.
- **The working tree is CRLF.** A mutation applied by a script anchored on
  `\n` matches nothing and reports "applied, tests green" — indistinguishable
  from a surviving mutant. Confirm every mutation landed (`git diff --stat`
  non-empty) before believing any result.
- **The Grep tool mangles `/` in content output** — verify slash-sensitive
  claims with Read, `git grep` via Bash, or by executing.
- The destructive-commands hook false-positives: `rm` under the repo,
  read-only `git grep` whose *pattern* names a sensitive file, and **any
  heredoc whose text contains a word like "erase"**. PowerShell
  `Add-Content` / `Remove-Item` and the Write tool work.
- CLI: `python -m receipts.cli <command>`. E2E deliberate:
  `python scripts/seed_review_e2e.py --reset` then
  `cd frontend && npx playwright test`.

## Git

Default branch **`main`**; `origin` → `CDGYu/Receipt-Digitalization`,
**public**. **Pushing `feat/*` is authorised; ask before pushing `main`**
(every `main` push authorization is one-time). Merged `feat/*` branches and
SDD workspaces are **kept, never cleaned up**. `.kiro/`, `.github/workflows/`,
`.superpowers/`, `var/`, `eval/golden/images/` are gitignored — never stage
anything under `var/` (real receipt images).

## Workflow

brainstorm → design doc → ADR for anything load-bearing → implementation plan
→ subagent-driven execution (one fresh implementer per task, briefed to read
the real signatures first; controller reviews the diff, re-runs gates
independently, dispatches a task review, appends to the ledger). Milestone
close: whole-branch review on the strongest model → ONE fix wave → one scoped
re-review → ff-merge → refresh this pair in the same session. Mid-branch
session end: refresh anyway and push (ADR-0021).

**Dispatch discipline (ADR-0023):** tasks that share a file run **strictly
serially**. Draw task boundaries so no two tasks share a file — the admin
release did this by folding each prose fix into the task that already owned
its file, and had zero collisions. An implementer whose task closes is
**explicitly released**. **Verify any wake-up from an agent outside the active
dispatch against `git` before acting on it.**

**Probe before dispatching — and sweep transitively.** Plan-defect count by
milestone: Phase 5 eleven; PAN hardening five; PAN grouping six; currency
bound two; failure-egress two; review-UI error recovery four; **admin release
seven**. Every one across seven milestones was the controller's, and every one
was caught by an implementer or reviewer who checked instead of trusting. **The
plan's prose is reliable; its claims about existing artefacts are not.**

## Review standards this project learned the hard way — hold all of them

1–14 unchanged (reproduce, don't reason · RED proofs · revert each guarantee
separately · single-variable mutations · **no rotting numbers in comments** ·
grep-don't-recall · don't credit unasked tools · stub-reflects-write · two
instances in one input · replay the committed battery both ways · coverage and
cross-boundary risk move together · a grown prose table changes every sentence
quantifying over it · a prose claim about a mutation needs revert-proof
discipline · **a pin never proven to fail is not a pin**), plus:

15. **A mutation that kills the right test for the wrong reason proves
    nothing.** The admin release shipped a table in which two of seven rows
    were worthless: deleting the route's `admin` parameter also deleted the
    binding its log line reads, so the route raised `NameError` before any
    authorization was tested; and "log `task.reason`" could not leak, because
    the log call sits outside the session and the attribute access raised
    `DetachedInstanceError` first. Both *looked* like proof — tests went red
    on cue. **Read the failure, not the colour.**

And: **a green suite is not evidence that installed software works** — run
entry points from outside the repository.

## Blocked on me (the user) — surface these, do not guess

1. **Push `main`?** Local `main` is ahead of `origin/main` and unpushed.
2. **Auth for the `corrections` read route** — reviewer-visible, or
   admin-only? (Gates Phase 5 follow-up #1.)
3. **A hosted tool-capable provider + freshly rotated key** (ISSUE-001 → all
   calibration, and Phase 6's success metric).
4. **Do the public golden labels need scrubbing?** (Real third-party names,
   TINs, addresses — also the values the PAN silent-case tests pin.)
5. **R060/R061 grounding (P2.T2)** — also gates bbox highlighting.
6. **GitHub Actions again?** If yes, the workflow calls `scripts/verify.py`.
7. **Close the PAN grouping residual?** Which priced route?
8. **Narrow the `{1,2}` separator** now that its surface is measured?
9. **Has anyone looked at the review UI in a browser?** Five error states
   shipped two milestones ago with no styling and no human ever viewing them.

**Today's goal:** <FILL THIS IN — with no branch in flight, the default is
"pick the next named piece of work". Pushing `main` (§1) is a one-minute ask
that should happen first. Then: the **admin UI** (§3) is the committed next
milestone and the largest well-scoped piece; the two Phase 5 follow-ups (§2)
are smaller, and the `corrections` route needs an auth ruling before it can
start. Phase 6 (§4) is the next substantial pipeline milestone but cannot be
validated until ISSUE-001 runs. Brainstorm → design → plan before touching
code.>
