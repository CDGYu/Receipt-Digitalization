You are continuing work on the **Receipt Digitization System**, a VLM pipeline
that turns receipt photos into accounting-grade structured data. Pick up exactly
where the last session left off.

**Read these first, then confirm the state back to me — and verify the snapshot
below against the repo rather than trusting it.** This file has been stale at
the start of several sessions: once by a whole milestone; once rewritten
*mid-milestone* by a subagent working outside its lane; once carrying two
sentences that contradicted each other about whether `main` was pushed; and on
**2026-08-06 the prompt handed to the session was a whole milestone out of date
*and the same stale text had been restored over the correct one in the working
tree*** — the tracked file was right and the working copy was wrong. Only `git`
settled it. ADR-0019 made the refresh part of closing a milestone; **ADR-0021
makes it part of ending any session.** This verification step is permanent.

**On 2026-08-07 a second failure mode joined it, and it is why ADR-0030 exists:
two of the six findings the last session was handed were false.** One instructed
it to "fix" a correct sentence in an Accepted ADR to match a wrong measurement.
**Verify a finding before acting on it — including every finding in this file.**

---

# ONE BRANCH IN FLIGHT: `feat/corrections-read-route`. PUSHED, NOT merged, NOT reviewed.

**This header said "NO BRANCH IN FLIGHT" for three days while that branch
existed** — true when written on 2026-08-07 and rotted on 2026-08-10, which is
the failure mode the paragraphs above describe, happening again. **Do not quote
a hash or a count from this file; run it** (ADR-0028 §1):

```
git status --short                        # must be empty
git log --oneline -6
git rev-parse main origin/main            # must be identical
git branch --no-merged main               # names feat/corrections-read-route, and nothing else
git ls-remote --heads origin feat/corrections-read-route   # pushed: expect a SHA
git log --oneline @{u}..feat/corrections-read-route        # expect empty
```

## `main` is merged and pushed. The BRANCH is neither.

`main` and `origin/main` are both at the commit `docs/MEMORY.md`'s stamp names,
and the review-UI styling milestone merged into it at `be6d7c0` on 2026-08-07,
pushed with an explicit authorization **that push consumed**. **The next `main`
push needs its own fresh ask** — and the corrections milestone is **not ready to
ask**, because it has had no whole-branch review and no merge.

**`feat/corrections-read-route` was pushed at the 2026-08-10 session close**
under the standing `feat/*` authorisation (ADR-0021 decision 4), so the work no
longer exists on one machine only. **Run the two commands above rather than
believing this sentence** — if the refresh commit that wrote it is ahead of
`origin`, push it.

**Freshness check.** `docs/MEMORY.md`'s stamp now names **two** positions,
because mid-branch there are two. Run both forms it gives; both must be empty
except for the single docs commit that writes the pair.

```
git log --oneline <BRANCH-STAMP>..feat/corrections-read-route -- src tests frontend docs ":(exclude)docs/MEMORY.md" ":(exclude)docs/NEXT_SESSION_PROMPT.md"
git log --oneline <MAIN-STAMP>..main -- src tests frontend docs ":(exclude)docs/MEMORY.md" ":(exclude)docs/NEXT_SESSION_PROMPT.md"
```

Gates on `main` at the styling merge, controller-run: `python scripts/verify.py`
**all five PASS**; pytest **979**; Vitest **346 across 25 files**.

**On the branch: `python scripts/verify.py` — all five gates PASS at the tip
`983f57c`, controller-run 2026-08-10 at the session close.** pytest **1004**;
Vitest **346 across 25 files, unmoved**, because no frontend file is in any
task's file set.

**All four tasks are complete**, each with a task review and a scoped
re-review. **What remains is the close and nothing else:** whole-branch review →
fix wave → one scoped re-review → ff-merge → refresh this pair → ask before
pushing `main`. See §0.

---

## Reading order

1. **`docs/MEMORY.md`** — state, decisions already made, environment, blockers,
   deferred items, and **review standards 1–24**.
2. **The ledgers** — `.superpowers/sdd/*/progress.md`, one per milestone.
   **`.superpowers/sdd/2026-08-10-corrections-read-route/progress.md` is the one
   that matters now**: it holds the nine fix rounds, the nine controller
   defects, every ruling, **the deferred minor findings and the whole-branch
   review's triage of them** (every one: ships). The review-UI
   styling one records twenty-five plan defects and "THE CLOSE".
   **`.superpowers/` is gitignored — open ledgers by path; nothing in them is
   findable by searching the tracked tree.**
3. **`docs/adr/README.md`, then the ADRs (0001–0032** — count the files rather
   than trusting that range**).** *This* file's range has tracked each ADR as it
   landed; it was **`docs/MEMORY.md`'s** copy that sat at `0001–0026` while four
   more ADRs shipped, and it was corrected on 2026-08-10. Derived per-commit
   with `git show <sha>:docs/NEXT_SESSION_PROMPT.md | grep -oE "0001.00[23][0-9]"`.
   Mandatory before touching the matching area:
   - **0032** — *a document cannot certify itself, and a derived claim can rot
     inside its own commit.* **Read before writing a fix wave's prose, or any
     sentence about how well something was checked.** Five of nine false-claim
     defects on the last branch were introduced *by fix rounds*. Gives the bound
     that closed it, and why an anchor is where the next rot lives.
   - **0031** — the corrections read route. **Read before changing who can see
     correction attribution, and before scoping `GET /receipts/{receipt_id}`:
     that route being *unscoped* is the premise its 403-not-404 rests on.** It
     also carries the schema-forced limit (a released or reopened task takes a
     reviewer's own history away) and the `offset` 500 measured on three routes.
   - **0030** — *a finding is a claim, and a fix wave verifies before it fixes.*
     **Read before acting on any review output, including this document.** Two
     of six findings in one wave were false. Corollaries: check **membership,
     not cardinality**, and state a query's **anchor** beside its number.
   - **0029** — *what the gates certify, and what they cannot.* **Read before
     saying "the gates pass" about anything visual.** **Its §4 list is known
     incomplete** — see §1.1 below.
   - **0028 + its `## Correction (2026-08-07)`** — claims about the tree are
     re-derived. **The correction withdraws the ADR's own motivating story**,
     which was false, and records `require_upload` as a third guard qualname.
   - **0027 + its TWO corrections (2026-08-06, 2026-08-07)** — the design
     system: light default, CSS Modules, `@fontsource` never a CDN, a pathname
     switch not React Router, and **`null` ≠ `0` ≠ empty**. The 2026-08-07
     correction fixes decision 4's two false counts **and records one review
     finding as falsified rather than applying it**.
   - **0026** — `/auth/me` and `/review/tasks`. The privacy property is
     *derived, not structural*, and **not closed**.
   - **0025** — the admin release. `close_task` deliberately leaves
     `assigned_to` set on a `DONE` task.
   - **0024** — the error-recovery contract. Inline field errors carry
     `role="alert"` and are additive; the summary always renders; the
     **backend-down sentence deliberately carries none.**
   - **0023 + its THREE dated corrections** — parallel agents share one
     worktree. The 2026-08-06 correction widens rule 2: serialise on files **or**
     on a shared global gate.
   - **0015** money is a string, `/app/*` only · **0012** auth and roles ·
     **0022** failure-text egress · **0018 + 0020** PAN · **0007** money
     integrity · **0006** the ValueError boundary · **0017** the gate runner ·
     **0019 + 0021** session continuity.
4. **`docs/superpowers/specs/`** — the design docs.
   **`2026-08-10-corrections-read-route-design.md` is the current one** — read
   its **three dated notes** (§1.1's wrong membership breakdown, §2.3/§8's
   ADR-0027 section number, §2.4's superseded tiebreaker) **before re-deriving
   anything from its body.**
   `2026-08-05-review-ui-design-system.md` (§2's three overrides, §4's null
   rule, **§5.1's dated note parking the currency prefix**, §9's rulings and its
   note that §9 is *not* an index of every decision since, and a 2026-08-07
   dated note correcting §4's three wrong supporting facts).
   `2026-08-05-review-ui-browser-pass.md` — **read the dated status note at the
   head of §3 FIRST**; it says which findings are closed, and for a day the
   report advertised four fixed defects as open.
5. **`docs/superpowers/plans/`** — dated historical records that **do not
   self-amend**. **Read each one's "Dated defect log" at the bottom FIRST.**
6. **`.kiro/steering/receipt-system.md`** — always-on rules (gitignored,
   untracked, still on disk).
7. **`IMPLEMENTATION_PLAN.md`** · **`docs/KNOWN_ISSUES.md`** (ISSUE-001 — do not
   re-derive) · **`RECEIPT_SYSTEM_SPEC.md`** §§ as needed.

---

# THE WORK, IN ORDER

## 0. FIRST — close `feat/corrections-read-route`. Nothing else starts until this does.

The branch is **built, fully task-reviewed, and green at the tip**. It has had
**a whole-branch review, which HAS now run** on the strongest model, 2026-08-10.

**Verdict: MERGE AFTER FIXES. No Critical. Every finding was prose — nothing in
behaviour.** It ran **17 mutations, 15 killed**; one survivor was equivalent and
one was the known `GET /receipts` `has_more` gap on a different route. It
confirmed the PAN pin holds end-to-end and that the scope fails closed.

**The three Important findings were fixed in the same session** (see §0.2), so
what remains is:

1. **One scoped re-review of that fix wave.** It touched `queue.py`'s docstring,
   ADR-0031, ADR-0032 and `docs/MEMORY.md` — no logic.
2. **ff-merge to `main`**, kept as a true fast-forward with a single parent.
3. **Refresh this pair in the same session** (ADR-0019 + ADR-0021).
4. **Ask before pushing `main`.** Every authorization is one-time and the
   2026-08-07 one was consumed. Pushing `feat/*` is standing-authorised and
   this branch is already pushed; keep it that way as the close adds commits.

### 0.1 The deferred minors — ALL TRIAGED AS *SHIPS*

Recorded under review standard 19's report-don't-fix, with rulings, in the
ledger. **The whole-branch review triaged every one as *ships*; none blocks the
merge.** **No count is given here** — two anchors were tried and both were
wrong, the second because the ledger's record of that very finding quotes the
phrase it searched for. Read the ledger's list.

Some were resolved before or during the review; those below are the ones still
open, and they are real:

- **The `offset` 500 — the only one that is a live defect.** See §7 and
  "Blocked on me": it is pre-existing on three routes and needs **your** call,
  not the reviewer's.
- The **inverse** null/empty direction is unpinned in
  `correction_summary` — a different shape from the closed class; belongs with
  the column's write-time contract.
- `created_at` is exercised only with `UTC` tzinfo.
- The fixture guard's `set(values)` assumes hashable rendered values — degrades
  the diagnostic, not the guarantee.
- Six new queue tests omit the `-> None` annotation their siblings carry.
- `test_an_unknown_receipt_is_404_even_for_an_admin` is subsumed verbatim by a
  later parametrised case; only the `[reviewer]` half is load-bearing.
- The `require_user`-vs-`require_upload` pin is the **third** per-route example
  of a universal claim; the converging form is a table over every non-upload
  route.
- Two suite counts anchored to a milestone *name* rather than a SHA
  (`tests/test_api_read.py`'s "all 979", and ADR-0031's `has_more` sentence),
  plus a pre-existing "all 116" in `tests/test_api_write.py`. **All three are
  currently true**; the objection is the anchor, per ADR-0032 §3.
- `items: list[dict]` loosened to `list[Any]` survives, and envelope field order
  is unpinned — both **pre-existing**, inherited by the reparent.
- **Tree-wide, not this branch's:** every `__all__` entry in `src/` is
  unkillable by any test, because the tree has **zero star-imports**. 182 names
  across 21 modules. Needs its own decision if anyone wants it closed.

### 0.2 What the whole-branch review found, and what was done about it

Three Important, all prose, **all fixed 2026-08-10 before the handoff was
written**. Each was verified before being acted on (ADR-0030); none was refuted.

- **ADR-0031 decision 2 claimed a boundary the queue does not hold.** It said
  including `OPEN` in the scope "would disclose every unclaimed receipt's
  attribution to every reviewer" — but `GET /review/next` converts an `OPEN`
  task into one assigned to the caller, and `close_task` never clears
  `assigned_to`, so the access is **permanent** once taken. Measured: a reviewer
  holding nothing got `403/403/403`; after looping next → read → complete three
  times, `200/200/200`, retained. **Fixed by stating the limit**: the difference
  is friction and an audit trail, not confidentiality.
- **`docs/MEMORY.md`'s review standard 24 was the last surviving copy of the
  rounds-vs-instances conflation** — the milestone summary and the handoff had
  both been corrected, and the standards list, which is where every session is
  sent, had not. **Fixed.**
- **`"exactly one task row"` was in three shipped places, not the two the
  handoff named** (`queue.py`, ADR-0031 decision 3, `docs/MEMORY.md`), while
  `api.py` correctly said "at most one" — `unique=True` permits **zero**, and
  zero is the case the route 403s. **All three fixed.**

Minors it raised that were also fixed: ADR-0032's own instance count used the
anchor `INSTANCE [A-Z]+`, which silently drops the ledger's plural `INSTANCES
TEN THROUGH THIRTEEN`; and its deferred-minor count used `minor \(deferred\)`,
whose closing `\)` drops one entry. **Both were wrong anchors in the ADR that
legislates about anchors**, and this brief inherited the second one.

Minors it raised and left standing, worth knowing: `mypy` is configured in
`pyproject.toml` but **invoked by nothing in the tree**, so the "killed by mypy"
claim in ADR-0031 names a check no gate runs; and `created_at` reaches the wire
**without a timezone offset** on SQLite, while Postgres would emit one — every
fixture supplies an explicit tz-aware value, so the shape a deployment actually
emits is unasserted.

### 0.3 Two things the branch deliberately did not do

- **`RECEIPT_SYSTEM_SPEC.md` §14.9's route inventory has no
  `GET /receipts/{receipt_id}/corrections` row.** Marked OUTSTANDING in three
  documents rather than done. That same `# api.py  (FastAPI routes)` header also
  heads three routes that live in `auth.py` — the design puts both in remit
  together whenever that line is next edited.
- **No frontend.** The reviewer-facing view of correction history is its own
  milestone, and will need ADR-0027's token vocabulary and its decision 5 null
  rule for the `value_before is None` case.

---

## 1. What the styling milestone left behind

Nothing here blocks on a ruling except where marked. All of it is measured.

### 1.1 Three things a mutation proved, and no gate catches

Found by the scoped re-review at the close, all **reported not fixed**, all
recorded in `frontend/tests/stylesheets.test.ts`'s docblock:

1. **The declaration census is SILENT on a value containing `;` or `{}`.**
   Proven: `FindingsPanel.module.css`'s `content: '+'` → `content: '+;XX'`
   splits on the embedded `;` into a fragment whose census key is still
   `content`, plus a colon-less fragment that is dropped. The census entry comes
   out byte-identical — **346/346 green, typecheck clean, build clean, and the
   changed glyph ships to `dist`.** **ADR-0029 §4 does not list this blind
   spot**: it is neither layout, nor cascade, nor one of the three narrower
   surfaces. Either the parser is replaced or §4 gains a bullet. **User
   decision.**
2. **The duplicate-selector guard is not exercised by the test named for it.**
   `it('refuses a stylesheet that declares one selector twice')` calls
   `rulesIn`, not `censusFor`. Replacing the guard's condition with `if (false)`
   leaves that test green. The guard still fires through the `it.each` over the
   real files, so this is a *pin* defect, not a hole.
3. **Rule source-order is unpinned.** Swapping `.row:nth-child(even)` and
   `.rowActive:nth-child(even), .rowActive` in `LineItemsTable.module.css` — two
   (0,2,0) rules whose order that file's own comment says decides the winner —
   leaves **all five gates PASS**. The census compares an object with `toEqual`,
   which is order-insensitive *between* rules. ADR-0029 already says a per-rule
   census cannot see two rules fighting, so this sits in the overlap between a
   claim and its own disclaimer.

### 1.2 The citation residual — measured, bounded, and explicitly unaudited

**71 line-number citations remain in live files** (`frontend/src`,
`frontend/tests`, `docs/adr`, `docs/MEMORY.md`). **32 are in files the close
never opened; 39 are in files it did.** The close removed ~31 stale ones.

**"Unaudited" is not "accurate."** The re-review resolved 15 of the survivors and
**6 were stale** — so the stale share of what remains is unknown, not zero. An
earlier draft of this file claimed the survivors were accurate and lived only in
untouched files; **both halves were false**, and that is the worked example in
ADR-0030 §5. ADR-0028 §5 forbids the form regardless of accuracy.

Method: extract every `path:NNN`, resolve the path, print the line it points at,
and read whether it still says what the citing sentence claims. **A bare grep
cannot tell accurate from stale.**

### 1.3 Residuals that shipped with the merge — reported, not fixed

1. **§5.3's confidence band hardcodes `0.85` / `0.60`** while `/metrics` ships
   the authoritative values. **The wire names are `thresholds.auto_approve` /
   `thresholds.review`** — *not* the `Settings` attribute names, which would
   read `undefined`.
2. **`.screen > div`** is positional. The browser pass confirmed the shell lands
   correctly, so this is a maintainability hazard, not a live defect.
3. **The layout half is ungated.** `cellOverflow` lives in the **ungated**
   Playwright run, and the money-width revert is caught only because `display`
   is a *keyword* — **a width regression expressed as a length still passes.**
   Proven at the close: `.cell`'s `width: 100%` → `width: 246px`, the exact
   intrinsic width that caused C1, leaves **346/346 green**.
4. **Per-row labels ("Qty 0") duplicate the column headers** inside cells.
   Hiding them violates §6; changing them needs a `MoneyInput` API change.
5. **`--color-null` is 4.27:1 on `--color-surface-active`** — not live today,
   one `background: transparent` away from being live.
6. **`SignOutControl.module.css`'s `.error` is 4.39:1 in dark**, below AA: it
   renders inside `.confirm`, which paints `--color-surface-raised`. Found by
   the census, **missed by the browser pass because no capture puts it on
   screen.** A source change, so a finding rather than a sweep item.
7. **Chromium only**; no `prefers-reduced-motion`, no `prefers-contrast`, no
   touch device, no screen reader.
8. **43 undersized hit targets** recorded and unasserted — mostly 20px
   checkboxes that are 44px via their label. **No threshold decision exists in
   the repo**, so asserting one would put an implementer's judgement in place of
   the design's.

### 1.4 The browser pass's open findings

In `docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md` §3, each
measured. **C1, C2, C3 and I4 are CLOSED and the status note says so.** Open:

- **I5 — re-triaged to CRITICAL, not fixed.** At 1440×900 the terminal states,
  the summary alert and Approve are below the fold, so **a 403 or a 404 — where
  the write LANDED and the task is GONE — produces no visible change at all.**
- **I6** the inline field error renders three grid columns from the field it
  blames; **I7** a 401 swaps in the login form with no message and repaints
  restored edits identically to stored data; **I8** the admin tiles tell a
  reviewer "9 open" directly above "No open tasks"; **I9** the 503 says the same
  sentence twice. Every Minor (m10–m16) untouched.
- **I5 and I7 touch ADR-0024's contract**, so neither is a drive-by fix.

### 1.5 Test-shape debt from the same milestone

- **`receipt-form.test.tsx` pins the row highlight through
  `rows[1].style.background`** — the *mechanism*, not the behaviour — which
  actively blocks moving the paint to a class.
- **`getByText(/carol/)` in the release round-trip is vacuous**: scoped to
  `within(table)`, satisfied by the assignee cell, green even if moved above the
  click. Fixing it needs a query scoped to the confirm, or
  `getAllByText(...).length === 2`. `TaskTable.tsx`'s comment now says plainly
  that **nothing constrains** the visible-name choice — it used to claim a test
  did.
- The class-name guard's three parked selector-axis leaks
  (harmless-but-inexact `:is`/`:where`, harmful-but-absurd self-contradictory
  `:not`, loud-and-safe `@import`); token *values* unpinned in the light block;
  `block()` assumes flat rule bodies.

### 1.6 One environment gap found at the merge

`pyproject.toml` declares `[project.scripts] receipts = "receipts.cli:_console_main"`
and the installed distribution records that entry point, **but no generated
wrapper exists in `C:\Python314\Scripts`, so `receipts --help` does not run as a
command.** `_console_main` imports fine and `python -m receipts.cli --help`
exits 0 from outside the repo. **Earlier records claiming `receipts --help`
exits 0 are not reproducible here** — use `python -m receipts.cli` for the
outside-repo check until the install state is settled. Not a regression from any
branch.

## 2. Phase 5 follow-ups — one BUILT-NOT-MERGED, one untouched

1. **The `corrections` read route is BUILT, on an unmerged and unpushed
   branch.** ~~Nothing does `select(Correction)`~~ — false at the branch tip:
   `git grep -nE 'select\(\s*Correction' -- src` returns exactly one hit,
   `review/queue.py`'s `list_corrections`. It was **zero** at the branch point
   `e2ec316`, which is still true of `main`.

   **The auth ruling is CONFIRMED, 2026-08-10, and is no longer blocked on
   you:** *"both, scoped differently: reviewers see corrections for the receipt
   they hold, admins see any receipt's."* The same words were given 2026-08-05
   beside a system notice disclaiming them as user input, so they were **not**
   acted on; they were put back verbatim and confirmed. The 2026-08-10
   confirmation is the authority. **ADR-0031** records it, what "hold" means,
   why 403 rather than 404 or an empty 200, and the schema-forced limit
   (`review_tasks.receipt_id` is UNIQUE, so a released or reopened task takes a
   reviewer's own correction history away from them).

   `GET /receipts/{receipt_id}/corrections` ships with `list_corrections`,
   `correction_summary`, and a `_PageResponse` base shared by all three page
   envelopes. Four tasks, all complete and reviewed. **What remains is the
   close: whole-branch review on the strongest model → one fix wave → one
   scoped re-review → ff-merge → refresh this pair.** Read
   `docs/superpowers/plans/2026-08-10-corrections-read-route.md`'s **"Dated
   defect log"** first — six plan defects, two of them reproduced rather than
   quoted.

   **Two things this milestone deliberately did not do**, both recorded rather
   than forgotten: `RECEIPT_SYSTEM_SPEC.md` §14.9's route inventory has **no**
   `GET /receipts/{id}/corrections` row (verified by reading the table — its
   only corrections-mentioning line is `PATCH /receipts/{id} -> apply
   corrections`, the write route, already there), and the same
   `# api.py  (FastAPI routes)` header also heads `/auth/login`, `/auth/me` and
   `/auth/logout`, which live in `auth.py`; the design puts both in remit
   together whenever that line is next edited. And the offset defect below.

2. **An ASGI entry point / deployment story.** `create_app` is a factory nothing
   under `src/` calls. `scripts/serve_review_e2e.py` is deliberately e2e-scoped
   — inheriting a deployment policy from an e2e launcher is the mistake to
   avoid. **The only item here that can start with no ruling** — and §1.6 is
   adjacent to it.

## 3. Phase 6 — merchants & few-shot (P6.T1)

`merchants/{fingerprint,registry}.py` is greenfield; few-shot images first,
target last; hints end "trust the image"; measure top-10-merchant accuracy
before/after — **blocked on ISSUE-001**, so Phase 6 can be built but not
validated. Five things unblock here: semantic dedupe into `process_receipt`; the
same hints into `_attempt_prompt_hash`; `merchant_default_currency` at its
plug-in point in `pipeline.py` (**locate it by symbol, not by line — the file
has grown**); the `image_phash` gap; `Merchant.receipt_count` (nothing writes
it). `VAT Reg. TIN` is the strongest fingerprint on this corpus.

## 4. Phase 7 — self-consistency (P7.T1)

Wire `run_consistency` (`extract/extractor.py`, zero references in
`pipeline.py`) for handwritten/low-legibility; **gate on
`triage.is_handwritten`, never `document_type`**; consistency runs never cached.

## 5. Phase 8 — calibration & eval-harness honesty

P3.T6/P8.T1 threshold sweep + weights into `config/rules.yaml` (**blocked on
ISSUE-001**); P8.T2 grow the held-out set; P8.T3 the all-failed eval run still
persists `"auto_approval_precision": 1.0` to JSON.

## 6. Still open from earlier phases

R060/R061 grounding decision (also gates bbox); score `is_handwritten` from
triage too; `is_receipt` has no consumer (never hard-reject on it); blank
pre-printed template rows (sibling of R052).

## 7. Deferred, with rulings

- **From the admin-UI-routes milestone:** 20 Minor findings triaged as safe.
  `GET /receipts`' `has_more` is **unpinned in the `True` direction** — a
  constant `has_more: False` survived the whole suite when it was measured at
  that milestone's close (the suite was 979 then; it is 1004 on the corrections
  branch, so re-measure rather than comparing to the old total).
- **Layer-wide, measured:** nothing pins the queue's caller-commits rule.
- **ADR-0025's accepted residuals:** the re-claim, and the third race order.
- **Parked at the error-recovery close:** the `42/42` comment; `edit()` not
  resetting `submit`; no `aria-invalid`; the comment-only select/checkbox
  invariant; the sign-out confirm's wording; keystrokes during an in-flight
  submit not stashed.
- **Two queued PAN scoped decisions** — the grouping residual (76 of 97 band
  shapes) and the `{1,2}` separator surface (36 spellings, pinned).
- Plus MEMORY.md's "Deferred follow-ups".

## 8. LAST — ISSUE-001

Read `docs/KNOWN_ISSUES.md`, do not re-derive; a hosted tool-capable model is
needed (rotate the echoed Gemini key first); until it runs, no measured accuracy
numbers and no real precision claim.

---

## Non-negotiables

`Decimal` money path; pure validation; stable rule IDs; null over
confident-wrong; **a full PAN never persisted**; nothing silently dropped; a
machine run never overwrites a `reviewed` row; optional-import discipline;
tool-use structured output; few-shot images first; consistency never cached;
`python -m pytest` offline and Node-free.

**PAN:** ADR-0018 + 0020 + corrections; any `_PAN_RE` change replays the
committed battery both ways, two-instance-tests, keeps the structural guards
green. **Egress (0022):** failure text goes through `redact_pan` at every
process exit. **Queue (0006):** explicit `Session` first, flush, **never
commit**, `ValueError` at the boundary; `list_tasks` is a pure read.
**Frontend (0015):** money is a string; no `<input type="number">`; no
`valueAsNumber`; no `CORSMiddleware`; `/app/*` only. **Error recovery (0024):**
the summary alert always renders; the classifier never invents copy; the stash
never touches browser storage; `PATCH /receipts/{id}` stays claim-unaware.
**Scope (0026):** the role mapping must not fail open. **UI (0027):** `null` ≠
`0` ≠ empty; severity colours are reserved; no raw hex outside `tokens.css`; no
CDN fonts. **Claims (0028):** a sentence that quantifies over the codebase is
derived at the moment of writing, with its method recorded. **Findings (0030):**
so is a sentence *about* one.

---

## Running it

- Two suites: `python -m pytest` (**979** on `main`, **1004** on
  `feat/corrections-read-route`) and Vitest in `frontend/` (**346** across 25
  files, the same on both). `npm test` does **not** type-check — run
  `npm run typecheck` too. `python scripts/verify.py` is what "passing" means
  (ADR-0017).
- **`pyproject.toml` sets `addopts = "-q"`.** So `python -m pytest -q` is `-qq`
  and prints **no pass count**; `-v` nets to dot output. **Use bare
  `python -m pytest`,** or `--junitxml`.
- **`scripts/verify.py` exceeds a 2-minute tool timeout.** Background it — and
  **do not edit source or tests while it runs.** Backgrounded during an edit it
  caught a half-applied refactor and reported `FAIL build` on a `TS6133` that no
  longer existed. A phantom failure looks exactly like a real one.
- Lint: `python -m ruff check .`. The frontend linter is **oxlint**; there is
  **no formatter config anywhere** in the tracked tree.
- **`pytest -k` matches substrings, not words.** `-k tasks` does not match
  `test_an_admin_sees_a_task_assigned_to_someone_else`. **It has now bitten two
  plans**: the corrections plan's `-k corrections` selected **4 of its own 8**
  route tests, because four of the names it supplies never contain the word.
  A `-k` filter in a plan is a claim about the names in that same plan.
- **The working tree is MIXED, not uniformly CRLF.** `tokens.css` and
  `LineItemsTable.module.css` are CRLF; `ReceiptForm.module.css` is LF.
  `core.autocrlf=true` keeps the index content identical so diffs stay
  line-level — but a script that assumes *either* ending matches nothing and
  still reports success. **Read the bytes before anchoring on them.** And a
  non-empty `git diff --stat` is not enough — `api.py` carries `limit=limit + 1`
  twice, and two runs landed on the **wrong route** and reported the suite
  passing. Confirm it landed **where you meant** (standard 16).
- **Comparing a blob to a worktree file will manufacture a fake diff.** The tree
  is CRLF and the blobs are LF, and `git show` decoded as the console codepage
  turns every em dash into mojibake. Decode both sides as UTF-8 and compare like
  with like — this bit two separate agents on 2026-08-07, in opposite ways.
- **Grep one distinctive word, never the phrase.** `git grep "one
  unauthenticated route"` returns nothing — the sentence wraps mid-phrase.
  **`git log -S` fails on the same strings**; measured 2026-08-07 hunting three
  route registrations it could not find. **`-G` found all three.**
- **PowerShell `Get-Content`/`Set-Content` mangles em dashes and `§`.**
  `Get-Content` defaults to ANSI without a BOM, so corruption happens on the
  **read**. **Use the Read/Write/Edit tools for anything non-ASCII** — which is
  nearly every file here.
- **Vitest sets `css: false`** — a `.module.css` import returns a proxy whose
  keys echo back, so **class names are unpinnable by rendering tests**; a
  renamed class ships as `class="undefined"` with every gate green. Guard by
  reading the stylesheet as text (`frontend/tests/stylesheets.test.ts` is the
  census; `review-null-rule.test.tsx` has the simpler example).
- **Vitest's environment pragma is matched ANYWHERE in a file**, including
  inside a docblock that merely quotes it. It silently moved a suite to Node and
  killed 11 rendering tests.
- **`dirname(fileURLToPath(import.meta.url))` DOES work under jsdom.** It is the
  `new URL(specifier, import.meta.url)` *pattern* Vite rewrites.
  `no-float-in-money-path.test.ts`'s attribution is still wrong and still
  uncorrected — it has been outside every task's permitted set.
- **Enumerating routes:** build the app and walk `app.routes` **recursing
  through `.original_router.routes`** — a flat walk yields 13 routes with
  **zero** `/auth/*` paths. Detect a transitively-called guard by qualname, and
  **match `require_` rather than hard-coding names**: there are three
  (`require_user`, `require_role.<locals>.dependency`, `require_upload`) and
  assuming two is what made ADR-0028 §4's corroboration fail to reproduce.
- **The Grep tool mangles `/` in content output** — verify slash-sensitive
  claims with Read, `git grep` via Bash, or by executing.
- The destructive-commands hook false-positives on: `rm` under the repo;
  read-only `git grep` whose *pattern* names a sensitive file (including
  `vite.config`); heredocs containing slash-separated config filenames; reading
  `vite.config.ts` via `cat`/`sed`; and **`awk` programs containing escaped
  slashes**. Use the Read tool and rephrase patterns.
- CLI: `python -m receipts.cli <command>` (**not** `receipts` — see §1.6).
  E2E: `python scripts/seed_review_e2e.py --reset` then
  `cd frontend && npx playwright test`.

## Git

Default branch **`main`**; `origin` → `CDGYu/Receipt-Digitalization`, **public**.
**Pushing `feat/*` is authorised; ask before pushing `main`** (every `main` push
authorization is one-time, and the 2026-08-07 one **was consumed by that
push**). Merged
`feat/*` branches and SDD workspaces are **kept, never cleaned up** — this
overrides the superpowers skills, which would delete both. `.kiro/`,
`.github/workflows/`, `.superpowers/`, `var/`, `eval/golden/images/` are
gitignored — never stage anything under `var/`.

**Stage by explicit path, never `git add -A`.** Verify with
`git diff --cached --stat` *before* committing.

## Workflow

brainstorm → design doc → ADR for anything load-bearing → implementation plan →
subagent-driven execution (one fresh implementer per task, briefed to read the
real signatures first; controller reviews the diff, **re-runs gates
independently**, **reproduces the headline mutation personally**, dispatches a
task review, appends to the ledger). Milestone close: whole-branch review on the
strongest model → fix wave → one scoped re-review → ff-merge → refresh this pair
in the same session → ask before pushing `main`.

**Dispatch discipline (ADR-0023, as corrected 2026-08-06):** tasks that share a
file run strictly serially — **and so do tasks that share a global gate.** Two
agents with disjoint file sets can still sabotage each other if one's plan has a
deliberate RED phase and the other's definition of done is a whole-suite result.

**Brief the property, not the fix.** An enumerated list of permitted edits is an
enumerated defence and fails the same way: it produced defect #12, then its own
repair produced #16. Give a bound ("all N existing tests pass unmodified;
anything needing a test changed is a stop-and-report") and let the implementer
find the shape.

**Brief a fix wave to verify before it fixes (ADR-0030).** Two of six findings
in the last wave were false. **"This finding is wrong" is a valid resolution**,
and it gets recorded with its measurement rather than dropped.

**Never put test files outside an implementer's permitted set when the task's
deliverable needs pinning.** That was defect #15, and it recurred twice more.

**Probe before dispatching.** Plan-defect count by milestone: Phase 5 eleven;
PAN hardening five; PAN grouping six; currency bound two; failure-egress two;
review-UI error recovery four; admin release seven; admin UI backend routes
nine; **review-UI styling twenty-five**; corrections read route **six**. Every
one across those ten milestones was the controller's, and every one was caught
by an implementer or reviewer who checked instead of trusting. **The plan's
prose is reliable; its claims about existing artefacts are not.**

**Two shapes from the corrections milestone worth carrying into the next plan:**
a mutation that kills nothing because the discriminating fixture is in none of
the supplied tests (the scope predicate survived all five), and a RED phase that
proves nothing because the framework produces the asserted status code on its
own (FastAPI 404s an unregistered path, so a 404 test passes before the route
exists). Both were reproduced in an isolated copy rather than taken on trust.

## Review standards — hold all of them

The full text is in **`docs/MEMORY.md` § "Review standards"**. In brief:

1–15 (reproduce don't reason · RED proofs · revert each guarantee separately ·
single-variable mutations · no rotting numbers in comments · grep-don't-recall ·
don't credit unasked tools · stub-reflects-write · two instances in one input ·
replay the committed battery both ways · coverage and cross-boundary risk move
together · a grown prose table changes every sentence quantifying over it · a
prose claim about a mutation needs revert-proof discipline · **a pin never
proven red is not a pin** · a mutation that kills the right test for the wrong
reason proves nothing), plus:

16. **Confirming a mutation landed is not confirming it landed where you meant.**
17. **A universal claim is answered by an enumeration, not an argument.**
18. **A substring can answer for a declaration.**
19. **An enumerated defence never converges.** State one bounded, checkable
    property, enforce it at both ends, move the enumerations into the tests as
    examples, and **report further shapes rather than fixing them**.
20. **A list in prose is read as complete, so writing one is a claim.**
    ADR-0028.
21. **A citation is a claim too.** Closing a prose defect ages every sentence
    that *cited* it. **Grep by one distinctive word after every change; quote
    text or name a symbol rather than a line.**
22. **A universal pin can still not measure what you care about.** The
    complement of 14: `placeholder="—"` was pinned over every control, proven
    red, and invisible in a browser — **jsdom cannot see a clipped box.**
    ADR-0029 states the blind spot for the gate set.
23. **A finding is a claim, and a fix wave verifies before it fixes.**
    ADR-0030. Two of six were false. **Check membership, not cardinality** —
    two matching counts are the weakest evidence of a shared cause and read as
    the strongest. **State a query's anchor beside its number** — `^\s*--[a-z]`
    answers "how many *begin a line*".
24. **A document cannot certify itself, and a derived claim can rot inside its
    own commit.** ADR-0032. The last branch recorded **nine false-claim
    instances**, every one a sentence rather than a defect in behaviour, with
    every gate green throughout — and **five of the nine were written while
    fixing one of the other four**. *(Do not confuse that nine with the nine
    fix **rounds**; those changed real behaviour and added real tests. Merging
    the two nines was itself one of the corrected claims.)* Three rules: a
    sentence whose subject
    is the document's own trustworthiness gets **deleted, not corrected**
    (rewriting it is the enumerated defence, and **headings are sentences**); a
    correctly-derived claim can be falsified by the very commit that carries it;
    and **anchors are where rot lives**, so prefer no number to a well-anchored
    one, and where a stamp is genuinely needed hand over **the command, not the
    answer**.

And: **a green suite is not evidence that installed software works** — run entry
points from outside the repository. §1.6 is the current example.

---

## Blocked on me (the user) — surface these, do not guess

1. **`?offset=9223372036854775808` is an unhandled 500 on THREE auth-scoped
   routes.** ~~Re-confirm the `corrections` auth ruling~~ — **done, confirmed
   2026-08-10, ADR-0031**; this replaces it, and it is a live pre-existing
   defect rather than a design question.

   `offset` is declared `Query(0, ge=0)` with **no upper bound**, so `2**63`
   passes validation, reaches SQLite and raises `OverflowError`. The body is
   Starlette's plain `Internal Server Error`, **not** this service's
   `{"error": {"message": ...}}` shape, because `OverflowError` is not a
   `ValueError` and none of `_install_error_handlers`' three handlers catches
   it. Controls: `offset=-1` → 422 (so `ge=0` does fire), `2**63-1` → 200,
   `2**63` → 500.

   Measured per caller class on all three paginated routes, independently
   reproduced twice:

   | caller | `/receipts` | `/review/tasks` | `/receipts/{id}/corrections` |
   |---|---|---|---|
   | anonymous | 401 | 401 | 401 |
   | machine key | 401 | 401 | 401 |
   | reviewer, no task row | 500 | 500 | **403 at every offset** |
   | reviewer holding it | 500 | 500 | 500 |
   | admin | 500 | 500 | 500 |

   **Two of the three are reachable by any signed-in caller.** Left unfixed
   deliberately under review standard 19 (report further shapes rather than
   fixing them) — the declaration is pre-existing on the two older routes and
   the third inherited it from a plan that specified the parameter verbatim.
   **The decision is yours:** a one-line `le=` on three routes, or a shared page
   bound. Either changes shipped contracts. Full record in **ADR-0031**'s
   closing section, deliberately in the tracked tree because the ledger is
   gitignored.
2. **A hosted tool-capable provider + freshly rotated key** (ISSUE-001 → all
   calibration, and Phase 6's success metric).
3. **The theme control.** ADR-0027 ships dark as a full second theme and **the
   application has no way for a user to choose it** — the only routes in are the
   OS preference and setting `data-theme` by hand. Every token and the
   precedence rule are correct and browser-verified; the decision is
   half-delivered. It needs a home for the control, which ADR-0027 deliberately
   did not open.
4. **The currency prefix**, parked in design §5.1 with *the browser pass* named
   as its resolver. **The pass ran and never addressed it** — grepping the
   report for "currency", "prefix" or "symbol" returns nothing. **Its designated
   resolver has been spent; it needs a new one.**
5. **Should the Playwright visual run become a sixth gate?** ADR-0029 leaves it
   open. It would need a headless-stable config, a policy for the 43 recorded
   undersized hit targets, and a way to establish a first baseline without
   pinning current defects.
6. **Does the census parser get replaced?** §1.1 item 1: a `;` or `{}` inside a
   value is silently mis-parsed and ships. Replacing it is real work; adding a
   bullet to ADR-0029 §4 is honest but leaves the hole.
7. **Should the citation sweep become a repo script?** §1.2. ADR-0028
   deliberately declined to propose a CI check for prose, and that stands until
   you say otherwise.
8. **Do the public golden labels need scrubbing?** (Real third-party names,
   TINs, addresses — also the values the PAN silent-case tests pin.)
9. **R060/R061 grounding (P2.T2)** — also gates bbox highlighting.
10. **GitHub Actions again?** If yes, the workflow calls `scripts/verify.py`.
11. **Close the PAN grouping residual?** Which priced route?
12. **Narrow the `{1,2}` separator** now that its surface is measured?

## Today's goal

**Something IS in flight: `feat/corrections-read-route` — four tasks done, all
five gates PASS at the tip, pushed, no whole-branch review, not merged.**
**§0 is the work.** Finishing it is the default first move and the only item
here with work already banked.

`verify.py` was run at the tip `983f57c` at the last session's close, so unless
the tree has moved you do not need to re-run it before the review — **but run
the freshness commands in `docs/MEMORY.md`'s stamp first, and if either lists
anything, re-run the gates before trusting any of this.**

**Only then** pick from §2.2 onward, or answer the questions above and let that
pick for you.

**The one item that needs no ruling from anybody** is §2.2, the ASGI entry point
and deployment story — and §1.6 sits right beside it: the declared `receipts`
console script is not installed, so the packaging story is unfinished in a way
that is now measured rather than suspected.

**If you would rather clear the decision backlog first**, items 3–7 above are all
consequences of the last milestone and all of them are one answer each: the theme
control, the currency prefix, Playwright as a sixth gate, the census parser, and
the citation sweep.

**If anything in this document disagrees with the repo, the repo wins.** This
file has been wrong at the start of several sessions, including one where the
correct version was in git and the stale one was in the working tree. Verify
before trusting, and say what you found — **and per ADR-0030, that applies to
the findings in §1 as much as to the state in the header.**
