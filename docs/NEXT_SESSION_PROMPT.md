You are continuing work on the **Receipt Digitization System**, a VLM pipeline
that turns receipt photos into accounting-grade structured data. Pick up exactly
where the last session left off.

**Read these first, then confirm the state back to me — and verify the snapshot
below against the repo rather than trusting it.** It has been stale at the start
of several sessions, once by a whole milestone. ADR-0019 made the refresh part
of closing a milestone; **ADR-0021 makes it part of ending any session** (its
2026-08-02 correction widened the freshness check to include `docs`). This
verification step is permanent.

**There is a feature branch in flight. Do not start anything new until it is
finished and merged.** See task 0. Both its implementation tasks are DONE and
independently reviewed; what remains is the close: whole-branch review → one
fix wave → one scoped re-review → ff-merge → handoff refresh.

## Reading order

1. **`docs/MEMORY.md`** — current state, decisions already made, environment,
   blockers, deferred and parked items. Its **"Currency bound & fixture race —
   the branch in flight"** section matters most this session.
2. **`.superpowers/sdd/2026-08-02-currency-bound-and-fixture-race/progress.md`**
   — the ledger of the branch you are finishing: both task entries with what
   the controller re-verified, both user rulings, the two plan-versus-reality
   defects (#7, #8), the fix round, and the deferred minors awaiting triage.
   `.superpowers/sdd/2026-07-31-pan-grouping/progress.md` is the completed
   previous milestone. **`.superpowers/` is gitignored — open ledgers by path;
   nothing in them is findable by searching the tracked tree.**
3. **`docs/adr/README.md`, then the ADRs (0001–0021).** Mandatory before
   touching the matching area — unchanged list from before, with these
   session-relevant highlights:
   - **0018 + its two dated corrections** — the §18 walk now has **two** named
     structural exclusions (`card_last4`, and `currency` as of this branch,
     because the `String(3)` bound is stronger than redaction). Read before
     touching `save_extraction`, the walk test, or anything PAN-adjacent.
   - **0020 + its correction** — detector shape, residual, the `{1,2}`
     separator surface. **0007** money integrity / bounded text (the decision
     this branch's Task 1 implements on the machine path, under **0006**'s
     ValueError convention). **0017** the gate runner. **0019 + 0021 (with
     correction)** session continuity and this snapshot's verification.
4. **`.kiro/steering/receipt-system.md`** — always-on rules (gitignored,
   untracked, still on disk).
5. **`docs/superpowers/plans/2026-08-02-currency-bound-and-fixture-race.md`**
   and **`docs/superpowers/specs/2026-08-02-currency-bound-and-fixture-race-design.md`**
   — the plan/design of the branch in flight, including three dated
   correction notes added during execution (§1.4 walk ruling, §1.5 collision
   note, §2.2 transitive-caller correction).
6. **`IMPLEMENTATION_PLAN.md`** · **`docs/KNOWN_ISSUES.md`** (ISSUE-001 — do
   not re-derive) · **`RECEIPT_SYSTEM_SPEC.md`** §§ as needed (as before).

## Where we are

**Two positions, and they are different — do not conflate them (ADR-0021).**

- **`main` @ `b81ba34`** (last code commit `0d6cea2`), **pushed, in sync with
  `origin/main`**. pytest on `main` is **916**.
- **`feat/currency-bound-and-fixture-race`, PUSHED. This is where the work
  is.** Off `main @ b81ba34`. Its last *code* commit is `9efeffb`; this
  handoff refresh rides on top as a docs-only commit. The check:

  ```
  git log --oneline 9efeffb..feat/currency-bound-and-fixture-race -- src tests frontend docs ":(exclude)docs/MEMORY.md" ":(exclude)docs/NEXT_SESSION_PROMPT.md"
  ```

  **Empty means this prompt is current.** Any output means the branch moved
  after it was written.

**Branch commits:** `a71c902` design · `9a36d42` plan · `ce4bf9e` **Task 1**
(the currency bound + the walk reconciliation + ADR-0018's dated correction) ·
`022b4fa` **Task 2** (distinct fixture images + the `data=` override) ·
`9efeffb` **fix round 1** (the counterfactual reworded, prose-only, proven by
AST identity).

**Gates at `9efeffb`, controller-run, not taken from reports:**
`python scripts/verify.py` **all five PASS**; pytest **920/0/0/0** read from
junitxml; Vitest **170**; outside-repo import of the changed module OK; no
forbidden path staged anywhere on the branch.

**Per-task state (ADR-0021: who verified what):**

| task | state |
|---|---|
| 1 — machine-path currency bound | complete, `ce4bf9e`; controller re-ran gates (919/0/0/0 at its sha); task review spec ✅ Approved — reviewer reproduced the bound from the real function, shared-coercer by object identity, ADR append-only by numstat, blast radius at all three pipeline call sites; 3 minors deferred |
| 2 — structurally distinct fixture images | complete, `022b4fa`+`9efeffb` after 1 fix round; controller re-ran (920/0/0/0); reviewer reproduced the 12-image sweep (pairwise dHash min 21 / max 44 vs threshold 5, read via inspect), both pin halves' revert-proofs, and the discriminating mutation; re-review ADDRESSED with AST-identity proof; 1 minor deferred |
| whole-branch review → one fix wave → scoped re-review → ff-merge → refresh | **not started** (a review dispatch was prepared last session and interrupted at the user's stop — it never ran) |

### What the branch does, in two sentences each

**Task 1.** `save_extraction` now runs `currency` through
`_CURRENCY_BOUND = _bounded_optional_text("currency")` — one instance, shared
with `_RECEIPT_FIELDS`, so machine and human paths cannot drift — raising
`ValueError` on over-long text where SQLite silently stored it and Postgres
raised `DataError` mid-transaction. The live pipeline never delivers such a
value (normalize whitelists to ISO-or-None; the failure and duplicate paths
save empty extractions), pinned by
`test_a_garbage_currency_never_reaches_the_bounded_column`; the §18 column
walk seeds `currency` bounded and excludes it structurally (**user ruling**,
second named exclusion after `card_last4` — a `String(3)` value cannot hold a
13-digit PAN, so the bound is the stronger guarantee; ADR-0018 dated
correction 2026-08-02).

**Task 2.** `tests/test_cli_pipeline.py`'s fixture now draws seeded random
rectangles per call (mirroring `tests/test_process_receipt.py`) instead of a
uniform PNG whose all-zero dHash raced concurrent receipts into dedupe's
5-bit window — the diagnosed intermittent `REJECTED`-for-`AUTO_APPROVED`.
Pinned by `test_fixture_images_are_distinct_beyond_the_dedupe_threshold`
(threshold read via `inspect.signature`, never restated); the two tests that
*depend* on byte-identical images pass one shared blob explicitly through
`_job`'s sibling-style `data=` override, with docstrings naming the
discriminating mutation (a failed run storing its hash — measured in review;
the empty-phash filter guards against a *crash*, not a false match).

## Non-negotiables

Unchanged: `Decimal` money path; pure validation; stable rule IDs; null over
confident-wrong; **a full PAN never persisted**; nothing silently dropped;
a machine run never overwrites a `reviewed` row; optional-import discipline;
tool-use structured output; few-shot images first; consistency never cached;
`python -m pytest` offline and Node-free. **PAN:** ADR-0018 + 0020 + their
corrections; any `_PAN_RE` change replays the committed battery both ways,
two-instance-tests, keeps the structural guards green. **Frontend
(ADR-0015):** money is a string; no `<input type="number">`; no
`CORSMiddleware`; `/app/*` only.

## The work, in order

### 0. FINISH `feat/currency-bound-and-fixture-race` — before anything else

Both tasks are done and reviewed; only the close remains:

1. **Whole-branch review on the strongest model.** Range `b81ba34..9efeffb`
   (regenerate the package with the skill's `review-package` script — do not
   trust a stale one). Hand it the plan, design (with its three dated notes),
   ADR-0018's new correction, the ledger path, and **these five deferred
   minors to triage** (fix-before-merge | defer, one line why each):
   1. `repository.py:1075` — `_CURRENCY_BOUND`'s comment says "the one
      length-limited column model text reaches"; off by one (`card_last4` is
      `String(4)` model text, guarded by `_last4`). Wording came verbatim
      from the plan.
   2. ADR-0018's new appendix names no guarantee test for the excluded
      column; the card_last4 passage it mirrors names one for its excluded
      side (fix = name `test_save_extraction_bounds_the_machine_path_currency`).
   3. `tests/test_repository.py:734` — the walk docstring's "only fields left
      unseeded" list is stale by one (`currency` is a third
      not-seeded-with-a-PAN field) — the drift class the test exists to
      prevent, in its own docstring.
   4. `tests/test_cli_pipeline.py` — `_PNG_SEEDS = itertools.count()` starts
      at 0, overlapping the explicit `seed=0` blob the two identical-bytes
      tests share; harmless today (per-test DBs), but the seed spaces
      overlap (e.g. start the counter at a disjoint offset, or note it).
   5. Design §2.2's note keeps the crash-guard conclusion without its
      mechanism (which lives in task-2-report Part 3) — legibility nit.
2. **ONE consolidated fix wave** (single dispatch, complete findings list),
   then **one scoped re-review**, adjudicate residuals at the breaker.
3. **ff-merge into `main`**, gates on main, **refresh this pair in the same
   session (ADR-0019/0021)** — and **ASK before pushing `main`**: the
   2026-08-02 one-time push authorization was consumed by the PAN grouping
   merge. Pushing `feat/*` remains authorised. Merged branches and SDD
   workspaces are **kept**.

### 1. Phase 5 follow-ups, each a named piece of work

Unchanged from before: the five design §5 error-recovery behaviours (no
logout control, no 401 return-to-receipt, no inline 400 field errors, no 503
state, no re-fetch on 403/404); a read route for `corrections` (auth
question); an ASGI entry point / deployment story (`create_app` — verified,
nothing under `src/` calls it); an admin release for a claimed task
(`IN_PROGRESS` → `OPEN`); the smaller parked items in the Phase 5 ledger.

### 2. Phase 6 — merchants & few-shot (P6.T1)

Unchanged: `merchants/{fingerprint,registry}.py` is greenfield (verified);
few-shot images first, target last; hints end "trust the image"; measure
top-10-merchant accuracy before/after. Five things unblock here: semantic
dedupe into `process_receipt`; the same hints into `_attempt_prompt_hash`;
`merchant_default_currency` at the plug-in point (`pipeline.py:227`,
verified); the `image_phash` gap (see MEMORY.md's dated correction for the
mechanism); `Merchant.receipt_count` (nothing writes it — verified).
`VAT Reg. TIN` is the strongest fingerprint on this corpus.

### 3. Phase 7 — self-consistency (P7.T1)

Unchanged: wire `run_consistency` (`extract/extractor.py:295`, zero
references in `pipeline.py` — verified) for handwritten/low-legibility;
**gate on `triage.is_handwritten`, never `document_type`**; consistency runs
never cached.

### 4. Phase 8 — calibration & eval-harness honesty

Unchanged: P3.T6/P8.T1 threshold sweep + weights into `config/rules.yaml`
(**blocked on ISSUE-001**); P8.T2 grow the held-out set; P8.T3 the all-failed
eval run still persists `"auto_approval_precision": 1.0` to JSON.

### 5. Still open from earlier phases

Unchanged: R060/R061 grounding decision (also gates bbox); score
`is_handwritten` from triage too; `is_receipt` has no consumer
(`extract/schema.py:201`, verified — never hard-reject on it); blank
pre-printed template rows (sibling of R052).

### 6. Parked, with rulings (see the ledgers)

- **Two queued PAN scoped decisions** — the grouping residual (ADR-0020: 76
  of 97 band shapes; two priced routes) and the `{1,2}` separator surface
  (36 spellings, 30 mixed, pinned; narrow or keep). Raise each as its own
  decision.
- **Parked from the PAN grouping close** (bundle with the next legitimate
  edit of `tests/test_repository.py`): the range-guard docstring's "about
  30x" (measured 19.6x); the mixed-pairs "width changing mid-run" rationale;
  pin `len(_ALL_SEPARATOR_SPELLINGS) == 42`; the module docstring's "reaches
  thirteen" 16-hex-domain nuance; ADR-0018's References naming the
  nonexistent `MUST_MASK` battery.
- ADR-0018's accepted false positives; leak (b); the auto-approving
  reprocess closing a claimed task; no login rate limiting (scrypt
  amplifier); `receipts eval`/`calibrate` traceback without the `pipeline`
  extra; reviewed-receipt reprocess records no `extraction_runs`; the
  `superclaude` stdout-clipping attribution still unproven.

### 7. LAST — ISSUE-001, deferred by the user until the system is built

Unchanged: read `docs/KNOWN_ISSUES.md`, do not re-derive; hosted
tool-capable model needed (rotate the echoed Gemini key first); until it
runs, no measured accuracy numbers and no real precision claim.

## Running it

- Two suites: `python -m pytest` (**920** on the branch, **916** on `main`)
  and Vitest in `frontend/` (**170**). `npm test` does NOT type-check — run
  `npm run typecheck` too. `python scripts/verify.py` is what "passing"
  means (ADR-0017).
- Piped pytest output can lose its final summary line — `--junitxml`, read
  counts from the XML. Lint is `python -m ruff check .`.
- **The Grep tool mangles `/` in content output** — verify slash-sensitive
  claims with Read, `git grep` via Bash, or by executing. It nearly produced
  a false `_PAN_RE` defect report once already.
- The destructive-commands hook false-positives: `rm` under the repo
  ("outside working directory"), and read-only `git grep` whose *pattern*
  names a sensitive file. PowerShell `Remove-Item` / the Read tool work.
- CLI: `python -m receipts.cli <command>`. E2E deliberate:
  `python scripts/seed_review_e2e.py --reset` then
  `cd frontend && npx playwright test`.

## Git

Default branch **`main`**; `origin` → `CDGYu/Receipt-Digitalization`,
**public**. **Pushing `feat/*` is authorised; ask before pushing `main`**
(the 2026-08-02 authorization was one-time and is consumed). `.kiro/`,
`.github/workflows/`, `.superpowers/`, `var/`, `eval/golden/images/` are
gitignored — never stage anything under `var/` (real receipt images).

## Workflow

brainstorm → design doc → ADR for anything load-bearing → implementation
plan → subagent-driven execution (one fresh `general-purpose` implementer
per task, briefed to read the real signatures first; controller reviews the
diff, re-runs gates independently, dispatches a task review, appends to the
ledger). Milestone close: whole-branch review on the strongest model → ONE
fix wave → one scoped re-review → ff-merge → refresh this pair in the same
session. Mid-branch session end: refresh anyway and push (ADR-0021).

**Probe before dispatching — and sweep transitively.** The plan-defect count
by milestone: Phase 5 eleven; PAN hardening five; PAN grouping six (+1 in a
controller dispatch prompt); **this branch two (#7, #8), both the
controller's, both caught by implementers who stopped at their briefs' own
stop conditions**: #7 the §18 walk seeding a PAN through `currency`
(resolved by user ruling — second named exclusion); #8 two *transitive*
callers of `_job` via `_pending_receipt` depending on byte-identical images
(the plan swept only direct callers; resolved via the design's own
pre-authorized conditional). A ninth near-miss: an unmeasured "(measured)"
counterfactual survived two authors before review executed it and found it
wrong — see review standard 13.

## Review standards this project learned the hard way — hold all of them

1–12 unchanged (reproduce, don't reason · RED proofs · revert each guarantee
separately · single-variable mutations · no rotting numbers in comments ·
grep-don't-recall · don't credit unasked tools · stub-reflects-write ·
two instances in one input · replay the committed battery both ways ·
coverage and cross-boundary risk move together · a grown prose table changes
every sentence quantifying over it), plus:

13. **A prose claim about what a test would do under a mutation needs the
    same revert-proof discipline as an assertion — or it does not carry
    "(measured)".** A docstring's counterfactual ("would pass even with the
    skip deleted (measured)") survived two authors unexecuted; running it
    showed the mutation *raises* rather than passes, and the mutation the
    premise actually guards is a different one. The correct fact had been in
    the tree all along, two files away, in the docstring of the function
    being described.

And: **a green suite is not evidence that installed software works** — run
entry points from outside the repository.

## Blocked on me (the user) — surface these, do not guess

1. **May `main` be pushed after this branch's merge?** The prior
   authorization was one-time and consumed.
2. **Do the public golden labels need scrubbing?** (Real third-party names,
   TINs, addresses — also the values the PAN silent-case tests pin.)
3. **A hosted tool-capable provider + freshly rotated key** (ISSUE-001 → all
   calibration).
4. **R060/R061 grounding (P2.T2)** — also gates bbox highlighting.
5. **GitHub Actions again?** If yes, the workflow calls `scripts/verify.py`.
6. **Close the PAN grouping residual?** Which priced route?
7. **Narrow the `{1,2}` separator** now that its 36-spelling surface is
   measured and pinned?

**Today's goal:** <FILL THIS IN — the default is "finish
`feat/currency-bound-and-fixture-race`: whole-branch review, one fix wave,
one scoped re-review, ff-merge, refresh the handoff pair.">
