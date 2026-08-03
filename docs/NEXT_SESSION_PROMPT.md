You are continuing work on the **Receipt Digitization System**, a VLM pipeline
that turns receipt photos into accounting-grade structured data. Pick up exactly
where the last session left off.

**Read these first, then confirm the state back to me — and verify the snapshot
below against the repo rather than trusting it.** It has been stale at the start
of several sessions, once by a whole milestone. ADR-0019 made the refresh part
of closing a milestone; **ADR-0021 makes it part of ending any session** (its
2026-08-02 correction widened the freshness check to include `docs`). This
verification step is permanent.

**No branch is in flight.** The currency bound & fixture race milestone was
closed and merged on 2026-08-03 (whole-branch review → one fix wave → one
scoped re-review → true ff-merge → this refresh, all in one session). The one
loose end is whether `main` may be pushed — **Blocked #1 below; do not push
without the answer.**

## Reading order

1. **`docs/MEMORY.md`** — current state, decisions already made, environment,
   blockers, deferred and parked items. Its "Currency bound & fixture race —
   complete and merged" section records the last milestone; its deferred list
   gained one **new named item** (the unredacted failure-reason path) at the
   2026-08-03 close.
2. **The ledgers** — `.superpowers/sdd/2026-08-02-currency-bound-and-fixture-race/progress.md`
   (complete: both task entries, both user rulings, plan defects #7/#8, the
   fix round, and "THE CLOSE (2026-08-03)" — the whole-branch review's
   findings and reproductions, the breaker adjudication, the fix wave, the
   re-review, the merge). `2026-07-31-pan-grouping/progress.md` and
   `2026-07-31-pan-hardening/progress.md` are the completed PAN milestones;
   `2026-07-29-review-ui/progress.md` holds Phase 5's parked items.
   **`.superpowers/` is gitignored — open ledgers by path; nothing in them is
   findable by searching the tracked tree.**
3. **`docs/adr/README.md`, then the ADRs (0001–0021).** Mandatory before
   touching the matching area. Session-relevant highlights:
   - **0018 + its two dated corrections** — the §18 walk has **two** named
     structural exclusions (`card_last4`, `currency`), each with its named
     guarantee test on the excluded side (`currency`'s was added at the
     2026-08-03 close: `test_save_extraction_bounds_the_machine_path_currency`).
     Read before touching `save_extraction`, the walk test, or anything
     PAN-adjacent.
   - **0020 + its correction** — detector shape, residual, the `{1,2}`
     separator surface. **0007** money integrity / bounded text. **0006** the
     ValueError boundary. **0017** the gate runner. **0019 + 0021 (with
     correction)** session continuity and this snapshot's verification.
4. **`.kiro/steering/receipt-system.md`** — always-on rules (gitignored,
   untracked, still on disk).
5. **`IMPLEMENTATION_PLAN.md`** · **`docs/KNOWN_ISSUES.md`** (ISSUE-001 — do
   not re-derive) · **`RECEIPT_SYSTEM_SPEC.md`** §§ as needed.

## Where we are

- **`main` @ `f04aa65`**, with this handoff refresh riding on top as a
  docs-only commit. The check:

  ```
  git log --oneline f04aa65..main -- src tests frontend docs ":(exclude)docs/MEMORY.md" ":(exclude)docs/NEXT_SESSION_PROMPT.md"
  ```

  **Empty means this prompt is current.** Any output means the tree moved
  after it was written.
- **`main` is NOT pushed as of this stamp** — ten commits ahead of
  `origin/main @ b81ba34` counting this refresh. The 2026-08-02 push
  authorization was one-time and consumed by the PAN grouping merge; a fresh
  one was requested at the 2026-08-03 close. If it was granted and the push
  happened later that same session, a same-session amendment to this pair
  records it — trust the amendment, then `git status -sb`, over this line.
- Gates at `f04aa65`, controller-run: `python scripts/verify.py` **all five
  PASS**; pytest **920/0/0/0**; Vitest **170**; outside-repo import of the
  changed module OK. `feat/currency-bound-and-fixture-race` is merged, kept,
  and pushed at `f04aa65`.

### What the last milestone shipped (details in MEMORY.md and the ledger)

**Task 1.** `save_extraction` bounds its `currency` write through the shared
`_CURRENCY_BOUND = _bounded_optional_text("currency")` (ValueError on
over-long text, ADR-0006/0007); the §18 walk's second named structural
exclusion (user ruling; ADR-0018 dated correction, which now also names the
guarantee test). **Task 2.** `tests/test_cli_pipeline.py` draws seeded random
rectangles per call (the uniform-PNG all-zero-dHash dedupe race is dead);
the two byte-identity-dependent tests pass one shared blob via `_job`'s
`data=` override. **The close:** whole-branch review on the strongest model —
0 Critical / 0 Important / 4 Minor; five queued minors triaged (1–3 fixed,
4–5 deferred); ONE fix wave (`43a79ef`, `22639cd`, `f04aa65` — six
prose/fixture-internal fixes, fixture bytes proven identical); one scoped
re-review — all six ADDRESSED, no residuals; gates re-verified at every step.

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
pre-printed template rows (sibling of R052). **New (2026-08-03, found by the
whole-branch review; pre-existing, live-reachable): the unredacted
failure-reason path** — the reviewed-row guard (`repository.py:613-618`)
quotes raw `merchant.name` in its `ValueError`; that text reaches
`pipeline.py:761`'s `log.warning` and the CLI's stdout via
`ProcessResult.reason` unredacted. Only `review_tasks.reason` is redacted at
a sink (ADR-0018), and `enqueue_review`'s redaction is a local rebinding
that never reaches the caller (measured). A candidate small hardening
branch; see MEMORY.md's deferred list for the full mechanism.

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
- **Parked from the currency-bound close (2026-08-03):** the `_PNG_SEEDS`
  counter starts at 0, overlapping the explicit `seed=0` blob (measured
  harmless — neither seed-0 test makes a default call, DBs are per-test;
  worth a comment on the next legitimate edit of `tests/test_cli_pipeline.py`);
  design §2.2 keeps the crash-guard conclusion with only a terse mechanism
  (the upstream fact lives in `find_duplicate_by_phash`'s docstring); the
  plan's self-review note still resolves §2.2's conditional the falsified
  way (plans don't self-amend — design §2.2's dated note is the record).
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

- Two suites: `python -m pytest` (**920** on `main`) and Vitest in
  `frontend/` (**170**). `npm test` does NOT type-check — run
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
(every `main` push authorization is one-time). `.kiro/`,
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
controller dispatch prompt); currency bound & fixture race **two (#7, #8),
both the controller's, both caught by implementers who stopped at their
briefs' own stop conditions** — #7 the §18 walk seeding a PAN through
`currency` (resolved by user ruling — second named exclusion); #8 two
*transitive* callers of `_job` via `_pending_receipt` depending on
byte-identical images (the plan swept only direct callers). Plus the
near-miss that became review standard 13: an unmeasured "(measured)"
counterfactual survived two authors until review executed it — and the
close's own fix round then had to strip a volatile "31 bits" the *reworded*
docstring had restated (review standard 5, in the sentence written to satisfy
standard 13).

## Review standards this project learned the hard way — hold all of them

1–12 unchanged (reproduce, don't reason · RED proofs · revert each guarantee
separately · single-variable mutations · no rotting numbers in comments ·
grep-don't-recall · don't credit unasked tools · stub-reflects-write ·
two instances in one input · replay the committed battery both ways ·
coverage and cross-boundary risk move together · a grown prose table changes
every sentence quantifying over it), plus:

13. **A prose claim about what a test would do under a mutation needs the
    same revert-proof discipline as an assertion — or it does not carry
    "(measured)".** A docstring's counterfactual survived two authors
    unexecuted; running it showed the mutation *raises* rather than passes,
    and the mutation the premise actually guards is a different one. The
    correct fact had been in the tree all along, two files away.

And: **a green suite is not evidence that installed software works** — run
entry points from outside the repository.

## Blocked on me (the user) — surface these, do not guess

1. **May `main` be pushed?** Asked at the 2026-08-03 close (the merged
   currency-bound milestone is local-only until then). Every prior
   authorization was one-time.
2. **Do the public golden labels need scrubbing?** (Real third-party names,
   TINs, addresses — also the values the PAN silent-case tests pin.)
3. **A hosted tool-capable provider + freshly rotated key** (ISSUE-001 → all
   calibration).
4. **R060/R061 grounding (P2.T2)** — also gates bbox highlighting.
5. **GitHub Actions again?** If yes, the workflow calls `scripts/verify.py`.
6. **Close the PAN grouping residual?** Which priced route?
7. **Narrow the `{1,2}` separator** now that its 36-spelling surface is
   measured and pinned?

**Today's goal:** <FILL THIS IN — with no branch in flight, the default is
"pick the next named piece of work": the Phase 5 follow-ups (§1) or the
unredacted failure-reason hardening (§5) are the smallest well-scoped
candidates. Brainstorm → design → plan before touching code.>
