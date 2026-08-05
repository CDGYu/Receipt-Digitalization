You are continuing work on the **Receipt Digitization System**, a VLM pipeline
that turns receipt photos into accounting-grade structured data. Pick up exactly
where the last session left off.

**Read these first, then confirm the state back to me — and verify the snapshot
below against the repo rather than trusting it.** It has been stale at the start
of several sessions, once by a whole milestone, and once it was rewritten
*mid-milestone* by a subagent working outside its lane, so it described a branch
that no longer existed. **Most recently (2026-08-05) it carried two sentences
that contradicted each other about whether `main` was pushed** — the header said
no, the body said yes, and only git settled it. ADR-0019 made the refresh part
of closing a milestone; **ADR-0021 makes it part of ending any session** (its
2026-08-02 correction widened the freshness check to include `docs`). This
verification step is permanent.

**No branch is in flight.** The admin-UI-backend-routes milestone was closed and
merged (true fast-forward `7aa0a22` → `b59f164`), then **`main` was pushed** on
an explicit one-time authorization. `main` and `origin/main` are in sync, and
all 14 `feat/*` branches are merged and pushed.

## Reading order

1. **`docs/MEMORY.md`** — current state, decisions already made, environment,
   blockers, deferred and parked items. Its "Admin UI backend routes —
   complete and merged" section records the last milestone.
2. **The ledgers** —
   `.superpowers/sdd/2026-08-05-admin-ui-backend-routes/progress.md`
   (complete: three task entries, **nine plan defects**, and "THE CLOSE" — a
   whole-branch review that ran **25 mutations** plus an exhaustive
   **1,554-path** reachability walk, one fix wave, one scoped re-review).
   `2026-08-04-admin-release/progress.md`,
   `2026-08-03-review-ui-error-recovery/progress.md`,
   `2026-08-03-failure-egress-redaction/progress.md`,
   `2026-08-02-currency-bound-and-fixture-race/progress.md`,
   `2026-07-31-pan-grouping/progress.md`, `2026-07-31-pan-hardening/progress.md`
   are completed prior milestones; `2026-07-29-review-ui/progress.md` holds
   Phase 5's parked items. **`.superpowers/` is gitignored — open ledgers by
   path; nothing in them is findable by searching the tracked tree.**
3. **`docs/adr/README.md`, then the ADRs (0001–0026).** Mandatory before
   touching the matching area. Session-relevant highlights:
   - **0026** — the two backend routes: `/auth/me` answers 401 not
     200-with-null; `/review/tasks` gives equal access with role-dependent
     content; and the privacy property is **derived, not structural**, with
     its limit stated. **Read before touching `/auth/me`, `/review/tasks`,
     `list_tasks`, or anything that can put a name on an `OPEN` task.**
   - **0025** — the admin release, whose `POST /review/{task_id}/release` is
     what `/review/tasks` exists to feed. `close_task` deliberately leaves
     `assigned_to` set on a `DONE` task; that is load-bearing.
   - **0016 + its dated note** — resume-before-claim, unchanged.
   - **0024** — the review UI's error-recovery contract.
   - **0023 + its two dated corrections** — parallel task agents share one
     worktree: commit every green step; never dispatch two tasks that touch
     one file; never repair a peer's tree; **restore a mutation from a byte
     copy, never `git checkout --`**; release an implementer explicitly.
   - **0022** failure-text egress · **0018 + 0020 + corrections** PAN ·
     **0015** the review UI's same-origin/`/app` rules · **0012** auth,
     roles and the machine key · **0007** money integrity · **0006** the
     ValueError boundary · **0017** the gate runner · **0019 + 0021**
     session continuity and this snapshot's verification.
4. **`.kiro/steering/receipt-system.md`** — always-on rules (gitignored,
   untracked, still on disk).
5. **`IMPLEMENTATION_PLAN.md`** · **`docs/KNOWN_ISSUES.md`** (ISSUE-001 — do
   not re-derive) · **`RECEIPT_SYSTEM_SPEC.md`** §§ as needed.
6. **If you open the last milestone's plan
   (`docs/superpowers/plans/2026-08-05-admin-ui-backend-routes.md`), read its
   "Dated defect log" at the bottom FIRST.** Five of that plan's nine defects
   are still in its body — plans are dated historical records here and do not
   self-amend, so the log is appended the way an ADR takes a dated
   correction. One of those five reached the shipped tree once already,
   precisely because it was re-derived from the plan instead of checked
   against the code.

## Where we are

- **`main` @ `eab0b26`**, with this handoff refresh riding on top as a
  docs-only commit. The check:

  ```
  git log --oneline eab0b26..main -- src tests frontend docs ":(exclude)docs/MEMORY.md" ":(exclude)docs/NEXT_SESSION_PROMPT.md"
  ```

  **Empty means this prompt is current.** Any output means the tree moved
  after it was written.
- **`main` is pushed and in sync with `origin/main`.** The one-time
  authorization asked for at this close was granted and consumed by that
  push. The standing rule continues: pushing `feat/*` is authorised;
  **every `main` push needs a fresh ask.**
- **All 14 `feat/*` branches are merged into `main` and pushed.** Audited
  2026-08-05: `git branch --no-merged main` is empty and every branch adds
  **+0** commits — they are historical merge points, kept, never cleaned up.
  There is nothing left to merge.
- Gates at `b59f164`, controller-run on `main` post-merge:
  `python scripts/verify.py` **all five PASS**; pytest **979**; Vitest **221**
  (19 files). **`src/` changed this milestone**, so the outside-repo import
  check applied and was run from `/c/Users` — keep applying it whenever a
  Python module changes.

### What the last milestone shipped

**The two backend contracts the admin UI needs**, both read routes, no
frontend change at all.

**`GET /auth/me`** returns `{"username", "role"}` for a signed-in caller and
**401 otherwise, including for the machine key** — guarded by `require_user`,
so it joins `READ_ROUTES` rather than inventing a 200-with-null shape. Bare
`dict[str, str]`, no Pydantic model, because `POST /auth/login` has returned
this body since `d255750`; a **drift test** pins the two equal.

**`GET /review/tasks`** lists the queue so an admin can find a task id for
`POST /review/{task_id}/release`. **Equal access, role-dependent content:**
both roles get 200; an admin sees every row, a reviewer sees `state == OPEN`
plus their own rows in any state. Ordered `priority, opened_at, id` — the
same total order `_claim_stmt` uses. `has_more` off a `limit + 1` fetch.
Backed by `list_tasks` in `queue.py`, exported from **both** `__all__` lists.

**The privacy property is derived, not structural** (ADR-0026): a reviewer
sees no other name only because `state == OPEN` implies `assigned_to IS
NULL`. **The class is NOT closed** — the route-level pin catches a fourth
`OPEN`-producer only if some test exercises it. Do not read it as closed.

**The close:** whole-branch review on the strongest model, **25 mutations** in
an isolated byte copy — 0 Critical, 2 Important, 11 Minor. **Deleting
`/review/tasks` turns 11 tests red, `/auth/me` 8, the scoping clause 3 — on
the subset bound itself.** The scope then survived an **exhaustive 1,554-path
reachability walk** with zero violations. ONE fix wave (two items), one scoped
re-review, both addressed. pytest 953 → 979.

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
`ValueError` at the boundary — and `list_tasks` is a pure read, so no flush
either. **Frontend (ADR-0015):** money is a string; no `<input type="number">`;
no `valueAsNumber`; no `CORSMiddleware`; `/app/*` only. **Error recovery
(ADR-0024):** the summary alert always renders; the classifier never invents
copy; the stash never touches browser storage; **`PATCH /receipts/{id}` stays
claim-unaware**. **Scope (ADR-0026):** `visible_to=None` means unrestricted;
the role mapping must not fail open; and nothing may put a name on an `OPEN`
task without a test that catches it.

## The work, in order

### 1. The admin UI's FRONTEND half — the committed next milestone

The two backend contracts shipped 2026-08-05 and **nothing under `frontend/`
consumes either one yet.** What remains:

- Read `GET /auth/me` on mount, and widen **`session.ts`** from one boolean
  to an identity. Today `session.ts:21` is
  `let signedIn = window.location.pathname !== '/app/login'` — a *guess*,
  corrected only by a rejected request. `/auth/me` replaces it with a fact.
- Give **`LoginPage.tsx`** somewhere to put the role it currently discards
  (`:15` awaits `request('/auth/login', …)` and throws the body away).
- A new **`/app` admin surface** that lists tasks via `GET /review/tasks` and
  drives `POST /review/{task_id}/release` from a browser.

**Nobody has viewed ANY of the review UI in a browser.** That risk is
inherited, not new; the design's §8 calls it out so this milestone does not
absorb it silently. Consider making a browser pass part of its done.

### 2. Phase 5 follow-ups — two left

1. **A read route for `corrections`.** Nothing does `select(Correction)`, so a
   reviewer cannot see the correction history of the receipt they are
   correcting and an auditor needs database access. Additive; **blocked on an
   auth ruling.** An answer was given on 2026-08-05 — *"both, scoped
   differently: reviewers see corrections for the receipt they hold, admins
   see any receipt's"* — **but it arrived alongside a system notice
   disclaiming it as user input and was never restated for confirmation.
   Re-confirm it verbatim before designing the route.**
2. **An ASGI entry point / deployment story.** `create_app` is a factory
   nothing under `src/` calls. `scripts/serve_review_e2e.py` is deliberately
   e2e-scoped — inheriting a deployment policy from an e2e launcher is the
   mistake to avoid. **This is the only item that can start with no ruling.**

### 3. THE ONE RESIDUAL — pre-existing, known false, NOT fixed

**`src/receipts/review/api.py`'s signed-blob handler claims: "This is the one
unauthenticated route in the service."** It is false. Measured at the
2026-08-05 close by building the route table from `create_app` and reading
each route's resolved dependant tree: **`GET /health`, `POST /auth/login`,
`POST /auth/logout` and the `/app` mount are also reachable with no session**
— five such routes, or **nine** with `DOCS_ENABLED=true`.

**Why it is called out here rather than buried in the deferred list:**

- It is the **same defect class** as the close's own Important #9 — a false
  universal about the auth surface — and it sits in the **very file** that
  finding cited as its counter-example. One was fixed; its twin was not.
- It is **pre-existing, not this branch's**: verified on `main` since
  `130b202`, and the admin-UI-routes branch never touches that docstring.
  That is why it was out of scope for a close whose fix wave is scoped to
  the branch diff, and why there was no second fix wave to catch it.
- Nothing depends on it and it changes no behaviour. It is a prose defect in
  a docstring that reads as an inventory — exactly the shape that has now
  misled a standard-12 re-read once on this project.

**Fix it with the next legitimate edit of `api.py`** (one sentence — name the
real set, or narrow the claim to "the one route that serves receipt data
without a session"). **Do not open a branch just for it**; do not let it
survive a milestone that edits that file. And when you fix it, apply review
standard 17: *answer the universal by enumerating, not by arguing* — the
enumeration script and its two traps are in the plan's dated defect log.

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

### 8. Deferred, with rulings (see the ledgers)

- **Nothing from the admin-UI-routes milestone is parked** — its close never
  hit the breaker. **20 Minor findings shipped**, triaged as safe by the
  whole-branch reviewer and listed in MEMORY.md's "Deferred follow-ups". The
  one a future editor will trip over: **`api.py`'s signed-blob docstring says
  it "is the one unauthenticated route in the service" — false and
  pre-existing** (five such routes, nine with `DOCS_ENABLED=true`), and it is
  the *same defect class* as the close's own Important #9, in the very file
  that finding cited. Fix with the next legitimate edit of `api.py`.
- **`GET /receipts`' `has_more` is unpinned in the `True` direction** — a
  constant `has_more: False` survives all 979 tests. Measured as a control;
  `GET /review/tasks` is strictly better than the route it was copied from.
- **Layer-wide, measured:** nothing pins the queue's caller-commits rule —
  deleting `release_task`'s `flush()` or turning it into a `commit()` leaves
  the suite green, and the same holds for `enqueue_review` and `next_task`.
- **The admin release's accepted residuals (ADR-0025):** the still-polling
  displaced reviewer can re-claim the task; and the third race order.
- **Parked at the review-UI error-recovery close:** the `42/42` comment;
  `edit()` not resetting `submit`; no `aria-invalid`; the comment-only
  select/checkbox invariant; the sign-out confirm's wording; keystrokes
  during an in-flight submit not stashed.
- **Two queued PAN scoped decisions** — the grouping residual (76 of 97 band
  shapes) and the `{1,2}` separator surface (36 spellings, pinned).
- Plus the standing list in MEMORY.md's "Deferred follow-ups".

### 9. LAST — ISSUE-001, deferred by the user until the system is built

Unchanged: read `docs/KNOWN_ISSUES.md`, do not re-derive; hosted tool-capable
model needed (rotate the echoed Gemini key first); until it runs, no measured
accuracy numbers and no real precision claim.

## Running it

- Two suites: `python -m pytest` (**979** on `main`) and Vitest in `frontend/`
  (**221**, 19 files). `npm test` does NOT type-check — run `npm run typecheck`
  too. `python scripts/verify.py` is what "passing" means (ADR-0017).
- **`pyproject.toml:61` already sets `addopts = "-q"`.** So `python -m pytest
  -q` is `-qq` and prints **no pass count** — green would rest on the exit
  code alone — and `-v` nets back to dot output (`-vv` gives a listing).
  **Use bare `python -m pytest`,** or `--junitxml` and read the XML.
- **`python scripts/verify.py` exceeds a 2-minute tool timeout.** Run it in
  the background or raise the timeout.
- Lint is `python -m ruff check .`.
- **`pytest -k` matches substrings, not words.** `-k tasks` does **not** match
  `test_an_admin_sees_a_task_assigned_to_someone_else` (`a_task`, not
  `tasks`). Measured: it would have collected 5 of 6.
- **The working tree is CRLF.** A mutation applied by a script anchored on
  `\n` matches nothing and reports "applied, tests green" — indistinguishable
  from a surviving mutant. **And a non-empty `git diff --stat` is not enough:
  `api.py` carries `limit=limit + 1` and the `has_more` return line TWICE,
  and two mutation runs landed cleanly on the wrong route and reported the
  suite passing.** Confirm the change landed *where you meant*.
- **Enumerating routes: `include_router` wraps the auth router in an
  `_IncludedRouter`,** so a flat walk of `app.routes` yields 13 routes with
  **zero** `/auth/*` paths — recurse through `.original_router.routes` for
  the real 17. A transitively-called guard (`require_role` → `require_user`)
  is invisible at runtime too; it is plain Python, not a nested `Depends`.
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
SDD workspaces are **kept, never cleaned up** — this overrides the
superpowers skills, which would delete both. `.kiro/`, `.github/workflows/`,
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
serially**. The last milestone's Tasks 1 and 2 both touched
`tests/test_api_read.py` and were serialised for exactly that reason — and
folding both matrix rows into one task was rejected, because it would assert
a route that does not exist at that commit.

**Probe before dispatching — and sweep transitively.** Plan-defect count by
milestone: Phase 5 eleven; PAN hardening five; PAN grouping six; currency
bound two; failure-egress two; review-UI error recovery four; admin release
seven; **admin UI backend routes NINE**. Every one across eight milestones
was the controller's, and every one was caught by an implementer or reviewer
who checked instead of trusting. **The plan's prose is reliable; its claims
about existing artefacts are not.**

## Review standards this project learned the hard way — hold all of them

1–15 unchanged (reproduce, don't reason · RED proofs · revert each guarantee
separately · single-variable mutations · **no rotting numbers in comments** ·
grep-don't-recall · don't credit unasked tools · stub-reflects-write · two
instances in one input · replay the committed battery both ways · coverage and
cross-boundary risk move together · a grown prose table changes every sentence
quantifying over it · a prose claim about a mutation needs revert-proof
discipline · a pin never proven to fail is not a pin · **a mutation that kills
the right test for the wrong reason proves nothing**), plus:

16. **Confirming a mutation landed is not confirming it landed where you
    meant.** `api.py` carries `limit=limit + 1` and the `has_more` return
    line twice. Two runs applied cleanly, with a correct non-empty byte
    delta, **to the wrong route**, and reported the full suite passing.

17. **A universal claim is answered by an enumeration, not an argument.**
    Defect #9 — "the guard every other authenticated route uses" — survived
    an explicit standard-12 re-read because the check reasoned about which
    guards call `require_user` instead of listing the routes. Two
    counter-examples were sitting in the tree, and **the ledger recorded the
    wrong answer as settled.** Enumerating took one script.

And: **a green suite is not evidence that installed software works** — run
entry points from outside the repository.

## Blocked on me (the user) — surface these, do not guess

1. **Re-confirm the `corrections` auth ruling** — "both, scoped differently"
   was answered on 2026-08-05 but never confirmed. (Gates §2.1.)
2. **A hosted tool-capable provider + freshly rotated key** (ISSUE-001 → all
   calibration, and Phase 6's success metric).
3. **Do the public golden labels need scrubbing?** (Real third-party names,
   TINs, addresses — also the values the PAN silent-case tests pin.)
4. **R060/R061 grounding (P2.T2)** — also gates bbox highlighting.
5. **GitHub Actions again?** If yes, the workflow calls `scripts/verify.py`.
6. **Close the PAN grouping residual?** Which priced route?
7. **Narrow the `{1,2}` separator** now that its surface is measured?
8. **Has anyone looked at the review UI in a browser?** Still nobody, and the
   frontend milestone is the natural moment.

*(The `main` push question is settled — it was granted and consumed on
2026-08-05, and `main` is in sync. The next push needs a fresh ask.)*

**Today's goal:** <FILL THIS IN — with no branch in flight, the default is
"pick the next named piece of work". The **admin UI's frontend half** (§1) is
the committed next milestone and now genuinely unblocked: both backend
contracts exist and nothing consumes them. It is also the first frontend work
since two UI milestones shipped without anyone opening a browser, so consider
making a browser pass part of its definition of done. The **ASGI entry point**
(§2.2) is the only smaller item that needs no ruling from me. The
`corrections` route (§2.1) needs its ruling re-confirmed first. **§3's
residual is not a milestone — it is one sentence, to be folded into whichever
milestone next edits `api.py`**; do not open a branch for it, and do not let
it survive a branch that touches that file. Phase 6 (§4) can be built but not
validated until ISSUE-001 runs. Brainstorm → design → plan before touching
code.>
