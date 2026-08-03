You are continuing work on the **Receipt Digitization System**, a VLM pipeline
that turns receipt photos into accounting-grade structured data. Pick up exactly
where the last session left off.

**Read these first, then confirm the state back to me — and verify the snapshot
below against the repo rather than trusting it.** It has been stale at the start
of several sessions, once by a whole milestone. ADR-0019 made the refresh part
of closing a milestone; **ADR-0021 makes it part of ending any session** (its
2026-08-02 correction widened the freshness check to include `docs`). This
verification step is permanent.

**No branch is in flight.** Two milestones were closed and merged on
2026-08-03 in one session: the currency bound & fixture race
(`b81ba34 → f04aa65`), then failure-egress redaction (`3c5a86d → 1035fd3`,
ADR-0022). The one loose end is whether `main` may be pushed — **Blocked #1
below; do not push without the answer.**

## Reading order

1. **`docs/MEMORY.md`** — current state, decisions already made, environment,
   blockers, deferred and parked items. Its "Failure-egress redaction —
   complete and merged" section records the last milestone; the deferred
   list's first two bullets (the accepted raw-chain residual, and the items
   parked at that close) are the freshest.
2. **The ledgers** —
   `.superpowers/sdd/2026-08-03-failure-egress-redaction/progress.md`
   (complete: four task entries with controller re-verification, plan
   defects #9/#10, and "THE CLOSE" — the whole-branch review, the fix wave,
   the re-review, the breaker adjudications).
   `2026-08-02-currency-bound-and-fixture-race/progress.md`,
   `2026-07-31-pan-grouping/progress.md`, `2026-07-31-pan-hardening/progress.md`
   are the completed prior milestones; `2026-07-29-review-ui/progress.md`
   holds Phase 5's parked items. **`.superpowers/` is gitignored — open
   ledgers by path; nothing in them is findable by searching the tracked
   tree.**
3. **`docs/adr/README.md`, then the ADRs (0001–0022).** Mandatory before
   touching the matching area. Session-relevant highlights:
   - **0022 + its same-day dated correction** — failure text is redacted at
     every process egress; the correction records the two sinks the original
     inventory missed (the enqueue twin print, fixed; the reprocess/stderr
     raw-chain residual, accepted with mechanism). Read before touching
     `_persist_failure`, `make_engine`, either failed-job print, or any new
     failure-text egress — **the standing rule: a new egress extends the
     inventory and goes through `redact_pan`.**
   - **0018 + its two dated corrections** — the §18 walk's two named
     structural exclusions (`card_last4`, `currency`), each with its named
     guarantee test. **0020 + its correction** — detector shape, residual,
     the `{1,2}` separator surface. **0007** money integrity / bounded text.
     **0006** the ValueError boundary. **0017** the gate runner. **0019 +
     0021 (with correction)** session continuity and this snapshot's
     verification.
4. **`.kiro/steering/receipt-system.md`** — always-on rules (gitignored,
   untracked, still on disk).
5. **`IMPLEMENTATION_PLAN.md`** · **`docs/KNOWN_ISSUES.md`** (ISSUE-001 — do
   not re-derive) · **`RECEIPT_SYSTEM_SPEC.md`** §§ as needed.

## Where we are

- **`main` @ `1035fd3`**, with this handoff refresh riding on top as a
  docs-only commit. The check:

  ```
  git log --oneline 1035fd3..main -- src tests frontend docs ":(exclude)docs/MEMORY.md" ":(exclude)docs/NEXT_SESSION_PROMPT.md"
  ```

  **Empty means this prompt is current.** Any output means the tree moved
  after it was written.
- **`main` is NOT pushed as of this stamp** — eleven commits ahead of
  `origin/main @ 3c5a86d` counting this refresh. A fresh one-time
  authorization was requested at the failure-egress close. If it was granted
  and the push happened later that same session, a same-session amendment to
  this pair records it — trust the amendment, then `git status -sb`, over
  this line.
- Gates at `1035fd3`, controller-run on `main` post-merge:
  `python scripts/verify.py` **all five PASS**; pytest **926/0/0/0**; Vitest
  **170**; outside-repo imports OK (pipeline, session, cli — plus both
  failed-job prints verified redacting at runtime from outside the repo).
  `feat/failure-egress-redaction` is merged, kept, and pushed at `1035fd3`;
  `feat/currency-bound-and-fixture-race` likewise at `f04aa65`.

### What the last milestone shipped (details in MEMORY.md and the ledger)

**ADR-0022's four egress guarantees:** `_persist_failure` redacts
`str(failure)` **before** truncating (order measured load-bearing, pinned by
a PAN-straddling-char-400 test); the failure log renders the traceback,
redacts it as text, drops `exc_info`; `make_engine` passes
`hide_parameters=True` (the `[parameters: …]` echo measured leaking and
closed at the one factory); both of `cmd_process`'s failed-job prints go
through `redact_pan(str(exc))` — the `str()` is load-bearing. **The close:**
whole-branch review on the strongest model — 0 Critical / 1 Important
(ADR-0022's own inventory falsified; fixed by dated correction) / 3 Minor;
ONE fix wave (`50992f5`, `fa25013`, `1035fd3`); one scoped re-review — all
four findings ADDRESSED; residuals adjudicated at the breaker and parked
with rulings.

## Non-negotiables

Unchanged: `Decimal` money path; pure validation; stable rule IDs; null over
confident-wrong; **a full PAN never persisted**; nothing silently dropped;
a machine run never overwrites a `reviewed` row; optional-import discipline;
tool-use structured output; few-shot images first; consistency never cached;
`python -m pytest` offline and Node-free. **PAN:** ADR-0018 + 0020 + their
corrections; any `_PAN_RE` change replays the committed battery both ways,
two-instance-tests, keeps the structural guards green. **Egress (ADR-0022):**
failure text goes through `redact_pan` at every place it leaves the process;
a new egress extends the inventory. **Frontend (ADR-0015):** money is a
string; no `<input type="number">`; no `CORSMiddleware`; `/app/*` only.

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
`merchant_default_currency` at the plug-in point (`pipeline.py:227` at its
baseline — re-verify, the file has since grown); the `image_phash` gap (see
MEMORY.md's dated correction for the mechanism); `Merchant.receipt_count`
(nothing writes it — verified). `VAT Reg. TIN` is the strongest fingerprint
on this corpus.

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
pre-printed template rows (sibling of R052). (The unredacted failure-reason
path that used to sit here was CLOSED by the failure-egress milestone; what
remains of it is the accepted raw-chain residual recorded in ADR-0022's
dated correction — a decision, not a task.)

### 6. Parked, with rulings (see the ledgers)

- **Two queued PAN scoped decisions** — the grouping residual (ADR-0020: 76
  of 97 band shapes; two priced routes) and the `{1,2}` separator surface
  (36 spellings, 30 mixed, pinned; narrow or keep). Raise each as its own
  decision.
- **Parked at the failure-egress close:** the straddle test's one-character
  margin — bundle `assert result.failed_stage == "persist"` with the next
  legitimate edit of `tests/test_process_receipt.py`; ADR-0022 nowhere
  names the straddle test (append-only consequence; design + ledger carry
  it); the milestone's 12 remaining task minors are in its ledger with
  triage verdicts.
- **Parked from the PAN grouping close** (bundle with the next legitimate
  edit of `tests/test_repository.py`): the range-guard docstring's "about
  30x" (measured 19.6x); the mixed-pairs "width changing mid-run" rationale;
  pin `len(_ALL_SEPARATOR_SPELLINGS) == 42`; the module docstring's "reaches
  thirteen" 16-hex-domain nuance; ADR-0018's References naming the
  nonexistent `MUST_MASK` battery.
- **Parked at the currency-bound close:** `_PNG_SEEDS` starting at 0
  (measured harmless; worth a comment on the next
  `tests/test_cli_pipeline.py` edit); design §2.2's terse mechanism; the
  plan's self-review note (plans don't self-amend).
- ADR-0018's accepted false positives (now also rendering masked in
  operator diagnostics via the failed-job prints — priced in ADR-0022);
  leak (b); the auto-approving reprocess closing a claimed task; no login
  rate limiting (scrypt amplifier); `receipts eval`/`calibrate` traceback
  without the `pipeline` extra; reviewed-receipt reprocess records no
  `extraction_runs`; the `superclaude` stdout-clipping attribution still
  unproven.

### 7. LAST — ISSUE-001, deferred by the user until the system is built

Unchanged: read `docs/KNOWN_ISSUES.md`, do not re-derive; hosted
tool-capable model needed (rotate the echoed Gemini key first); until it
runs, no measured accuracy numbers and no real precision claim.

## Running it

- Two suites: `python -m pytest` (**926** on `main`) and Vitest in
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
controller dispatch prompt); currency bound two (#7, #8); failure-egress
**two (#9, #10), both the controller's sink map**: #9 the enqueue loop's
twin failed-job print (found by the Task-4 implementer stopping at its
brief's boundary; fixed under ADR-0022's standing rule); #10 `receipts
reprocess`'s un-netted re-raise rendering the raw `_StageFailure` chain to
stderr (found by the whole-branch review EXECUTING the escape path; accepted
residual with mechanism recorded). The pattern across five milestones: the
plan's prose is reliable; its claims about existing artefacts are not — and
sink/caller maps miss twins and transitive paths unless swept by command.

## Review standards this project learned the hard way — hold all of them

1–12 unchanged (reproduce, don't reason · RED proofs · revert each guarantee
separately · single-variable mutations · no rotting numbers in comments ·
grep-don't-recall · don't credit unasked tools · stub-reflects-write ·
two instances in one input · replay the committed battery both ways ·
coverage and cross-boundary risk move together · a grown prose table changes
every sentence quantifying over it), plus:

13. **A prose claim about what a test would do under a mutation needs the
    same revert-proof discipline as an assertion — or it does not carry
    "(measured)".**

And: **a green suite is not evidence that installed software works** — run
entry points from outside the repository.

## Blocked on me (the user) — surface these, do not guess

1. **May `main` be pushed?** Asked at the 2026-08-03 failure-egress close
   (both merged milestones are local-only until then). Every prior
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
"pick the next named piece of work": the Phase 5 follow-ups (§1) or Phase 6
(§2) are the natural candidates. Brainstorm → design → plan before touching
code.>
