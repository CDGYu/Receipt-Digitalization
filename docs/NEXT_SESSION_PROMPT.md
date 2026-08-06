You are continuing work on the **Receipt Digitization System**, a VLM pipeline
that turns receipt photos into accounting-grade structured data. Pick up exactly
where the last session left off.

**Read these first, then confirm the state back to me — and verify the snapshot
below against the repo rather than trusting it.** It has been stale at the start
of several sessions: once by a whole milestone; once rewritten *mid-milestone*
by a subagent working outside its lane; once carrying two sentences that
contradicted each other about whether `main` was pushed; and on **2026-08-06 the
prompt handed to the session was a whole milestone out of date *and the same
stale text had been restored over the correct one in the working tree*** — the
tracked file was right and the working copy was wrong, the inverse of the
earlier failure. Only `git` settled it. ADR-0019 made the refresh part of closing
a milestone; **ADR-0021 makes it part of ending any session.** This verification
step is permanent.

---

# ⚠️ A BRANCH IS IN FLIGHT. This is a mid-milestone handoff.

**`feat/review-ui-styling`**, off `main@1314485`, **pushed**. `main` is untouched
by it and in sync with `origin/main`.

The tip was `1bfacb4` when this was last edited, and **the edit itself commits
on top of that**, so the real tip is at least one commit later — a document
cannot name the commit that writes it (ADR-0019). **Do not quote a count from
this file; run it** (ADR-0028 §1):

```
git rev-list --count main..feat/review-ui-styling
git log --oneline main..feat/review-ui-styling | head -5
```

**ALL SIX TASKS ARE COMPLETE, AND SO IS THE WHOLE-BRANCH REVIEW AND HALF THE
FIX WAVE.** What remains is **fix wave B (the documentation sweep), one scoped
re-review, and the merge** — all three specified in full in §1. The review's
verdict was *merge after one fix wave*; **nothing it found is a runtime
defect**, and it verified the ff-merge is clean.

**First thing to run:**

```
git status --short          # dirty => a mutation may be mid-flight; do not "clean" it
git log --oneline -8
```

**If the tree is dirty, do not "clean" it** (ADR-0023). Restore from a byte copy
after checking the ledger, never with `git checkout --`.

---

## Reading order

1. **`docs/MEMORY.md`** — state, decisions already made, environment, blockers,
   deferred items, and **review standards 1–22**. Its "Review-UI styling — IN
   FLIGHT" section records this milestone.
2. **The in-flight ledger** —
   `.superpowers/sdd/2026-08-05-review-ui-styling/progress.md`. **Read before
   touching the branch.** Every plan defect, every mutation, every controller
   ruling. Completed milestone ledgers sit beside it. **`.superpowers/` is
   gitignored — open ledgers by path; nothing in them is findable by searching
   the tracked tree.**
3. **`docs/adr/README.md`, then the ADRs (0001–0029).** Mandatory before
   touching the matching area:
   - **0029** — *what the gates certify, and what they cannot.* **Read before
     saying "the gates pass" about anything visual.** Four fixes — three
     Critical — once reverted with all five gates green. It states what a green
     run now certifies and what it still does not (layout, cascade, quantities
     of the same kind).
   - **0028** — *claims about the tree are re-derived, not restated.* **Read
     before writing any sentence that quantifies over this codebase.** Four
     such claims were found false in one day; three were written by someone who
     *had* checked and asked the wrong question. Carries the enumeration
     methods and why citations here have no line numbers.
   - **0027 + its `## Correction (2026-08-06)`** — the design system: light
     default, CSS Modules, `@fontsource` never a CDN, a pathname switch not
     React Router, and **`null` ≠ `0` ≠ empty**. The correction fixes its false
     "all 17 are `<input>`" claim. **Read before writing any CSS or rendering
     any extracted value.**
   - **0026** — `/auth/me` and `/review/tasks`. The privacy property is
     *derived, not structural*, and **not closed**.
   - **0025** — the admin release, which `/review/tasks` exists to feed.
     `close_task` deliberately leaves `assigned_to` set on a `DONE` task.
   - **0024** — the error-recovery contract. Inline field errors carry
     `role="alert"` and are additive; the summary always renders; the
     **backend-down sentence deliberately carries none.**
   - **0023 + its THREE dated corrections** — parallel agents share one
     worktree. **The 2026-08-06 correction widens rule 2: serialise on files
     _or_ on a shared global gate.**
   - **0015** money is a string, `/app/*` only · **0012** auth and roles ·
     **0022** failure-text egress · **0018 + 0020** PAN · **0007** money
     integrity · **0006** the ValueError boundary · **0017** the gate runner ·
     **0019 + 0021** session continuity.
4. **`docs/superpowers/specs/2026-08-05-review-ui-design-system.md`** — the
   design. §2's three overrides; §4 the null rule; **§5.1's dated note parking
   the currency prefix**; §9's rulings (and its note that §9 is *not* an index
   of every decision since).
5. **`docs/superpowers/plans/2026-08-05-review-ui-styling.md`** — the plan under
   execution. **Read its "Dated defect log" at the bottom FIRST.** Twenty-five
   defects, all the controller's; several are still wrong in the body above it,
   and the log was appended mid-milestone precisely so the close does not
   re-derive them from the body.
6. **`.kiro/steering/receipt-system.md`** — always-on rules (gitignored,
   untracked, still on disk).
7. **`IMPLEMENTATION_PLAN.md`** · **`docs/KNOWN_ISSUES.md`** (ISSUE-001 — do not
   re-derive) · **`RECEIPT_SYSTEM_SPEC.md`** §§ as needed.

---

## Where we are

- **`main` @ `1314485`**, pushed, in sync with `origin/main`, untouched by the
  branch. Every `main` push needs a **fresh** ask.
- **All 13 merged `feat/*` branches are pushed**; `feat/review-ui-styling` is
  the fourteenth and is the one in flight.
- **Freshness check**, using the commit named in `docs/MEMORY.md`'s
  "Last updated" line:

  ```
  git log --oneline <STAMP>..main -- src tests frontend docs ":(exclude)docs/MEMORY.md" ":(exclude)docs/NEXT_SESSION_PROMPT.md"
  ```

  **Empty means this prompt is current.**
- Gates at `8ede47e`, controller-run: `python scripts/verify.py` **all five
  PASS**; pytest **979**; Vitest **346 across 25 files** (318 → 346 when fix
  wave A added the gated stylesheet census).
- **`src/` CHANGED on this frontend branch** (`bbb5366`). The whole-branch
  review has one Python file in scope, and the **outside-repo import check
  applies at the merge**.

---

# THE WORK, IN ORDER

## 1. CLOSE THE IN-FLIGHT MILESTONE — `feat/review-ui-styling`

**All six tasks are complete. The whole-branch review is done. Fix wave A is
done. What is left is fix wave B, one scoped re-review, and the merge.**

The review's verdict was **merge after one fix wave**, and it independently
re-ran pytest **979**, Vitest, Playwright **15/15**, the freshness check (empty),
and `git merge-base --is-ancestor main HEAD` → **the ff-merge is clean**.
**Nothing it found is a runtime defect.** Its report is not in the tracked tree;
its verified core is in the ledger under "THE CLOSE".

### 1.1 What fix wave A already did — `8ede47e`, DONE

**The one Critical (C-1): Task 5's entire fix round was unpinned.** Three
reverts, each leaving **all five gates green**, undid three Critical findings and
a WCAG failure that the browser pass had found and a fix round had repaired:

| Revert | Restores |
|---|---|
| `MoneyInput.module.css` `.field` → `inline-flex` | money controls overflow their cells; the null `—` is clipped out of sight |
| `tokens.css` `--color-null` → `#64748B`, both dark blocks | 3.91:1, below AA, on the glyph carrying the prime directive |
| `LoginPage.module.css` rule bodies emptied | login reverts to browser default |

Wave A added **`frontend/tests/stylesheets.test.ts`** — a gated declaration
census — and the corrected class guard. **Vitest 318 → 346 across 25 files**;
all three reverts now red. **ADR-0029 records what the gates certify and what
they still cannot.** Verified by the controller: revert 1 now reds the gated
suite (345/346) where before it left 318/318 green.

### 1.2 FIX WAVE B — the documentation sweep. **NOT DONE. Do this first.**

Six items. **It is a sweep, not a list of spot fixes** — repointing a stale
citation at fresh line numbers only schedules the next rot (ADR-0028 §5,
review standard 21).

1. **I-2 — the browser-pass report ships four dead findings as open.**
   `docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md` still lists
   **C1, C2, C3 under `### Critical` and I4 under `### Important`**; all four
   were fixed by `205d77a`. Its §1 answer table still says *"In the line-items
   table, no: a null amount is invisible"* and *"Not on login (21px controls)"* —
   both now false. **Add an inline dated note** (specs take inline notes; ADRs
   take a trailing `## Correction` — that is the house convention).
2. **I-3 — a false comment justifies a shipped design choice.**
   `frontend/src/admin/TaskTable.tsx`'s comment says a test constrains naming the
   holder visibly. **Measured: it does not.** The assertion is `within(table)`,
   not the confirm row, and moving it before the click leaves 35/35 green.
   Either scope the assertion and name the holder visibly, or say plainly that
   nothing constrains the choice. **The "mutually exclusive" framing is
   overstated** — a scoped query or `getAllByText(...).length === 2` satisfies
   both.
3. **I-4 + D-1 + D-8 — de-number every stale citation. 15+ tree-wide.** Five sit
   **inside ADR-0027's own `## Correction`**, four lines above the sentence
   boasting it deliberately carries none: `ReceiptForm.tsx:95/113/227/240/248`
   are all wrong. Four more were **created by this branch** (`5d91fb8`,
   `bbb5366`, `bdbfd03`). Known-stale also: `session.ts:21` → the pathname read
   moved to `:23`, **and that sentence is false a second way** — *"the only
   pathname read in the app"* is untrue since `route.ts` reads it too and says so
   itself; `api.py:856` → `_SpaFiles` moved to `:876`. **Do not repoint. Quote
   the text or name the symbol.**
4. **The four wrong counts.**
   - **`5.45:1` is wrong; it is `5.43:1`.** The handoff pair was corrected when
     this was written; **three remain — `tokens.css` twice (source, not docs)
     and ADR-0027 once.** Re-grep rather than trusting that count (standard 21).
   - ADR-0027 *"35 custom properties"* — measured **54 declarations / 24 unique
     names**. **35 is the `@font-face` count**, cited twelve lines below.
   - ADR-0027 *"runtime dependencies are exactly `react` and `react-dom`… the
     app's third"* — there are **four**, and ADR-0027 §3 forty lines earlier says
     so.
   - ADR-0028 *"nine months"* — `130b202` is 2026-07-29 and the fix is
     2026-08-06: **eight days**.
   - **The plan's defect count says fourteen; the real number is twenty-five.**
5. **I-5 — ADR-0028 §4's "two methods agreed" does not reproduce.** The static
   half yields **6 and 10, not 5 and 9**, because **`require_upload` is a third
   guard name** that neither ADR-0028 §3 nor `api.py`'s docstring records. The
   empirical half reproduces exactly and §4's own tiebreak says empirical wins,
   so **no security conclusion changes** — only the corroboration fails. Record
   `require_upload` beside §3's qualname instruction.
6. **D-2 — ADR-0028's motivating story is falsified by ADR-0028's own §3.** It
   says the old `vite.config.ts` list *"listed exactly 13, and 13 is exactly what
   a flat walk returns."* **The old list contains `/auth/login` and
   `/auth/logout`; a flat walk yields ZERO `/auth/*` paths.** Both are 13; they
   are **different 13s**. A flat walk cannot have produced that list. **Correct
   or withdraw the causal claim** — it is the branch's headline documentation
   deliverable and its narrative is self-refuting. Restated in `MEMORY.md` and
   the plan, so fix all three.

**Also fold in, both already ruled:**
- **Re-triage browser-pass finding I5 to Critical**, recorded **not fixed**. At a
  real window height the terminal states, the summary alert and Approve are below
  the fold, so **a 403 or 404 — where the write LANDED and the task is GONE —
  produces no visible change**. Fixing it means reopening ADR-0024's contract, so
  it is not a drive-by.
- **A latent contrast defect wave A found that the browser pass missed**, because
  no capture puts it on screen: `SignOutControl.module.css`'s `.error` renders
  inside `.confirm`, which paints `--color-surface-raised` — in dark that is
  **4.39:1**, below AA. **Fixing it is a source change**, so it is a finding, not
  part of the sweep.

### 1.3 Then one scoped re-review

Scoped to wave B's diff plus wave A's `8ede47e`. **`8ede47e` has not been
reviewed by anyone but its author and the controller.**

### 1.4 Then the merge

ff-merge → refresh this pair in the same session → **ask before pushing `main`**.
**`src/` changed on this branch** (`bbb5366`), so the **outside-repo import check
applies at the merge** — run entry points from outside the repository.

### 1.5 Residuals that ship with the merge — reported, not fixed

1. **§5.3's confidence band hardcodes `0.85` / `0.60`** while `/metrics` ships
   the authoritative values. **The wire names are
   `thresholds.auto_approve` / `thresholds.review`** — *not* the `Settings`
   attribute names an earlier draft of this file gave, which would read
   `undefined`.
2. **`.screen > div`** is positional. The browser pass confirmed the shell lands
   correctly, so this is a maintainability hazard, not a live defect.
3. **The layout half is still ungated.** Wave A's census pins keywords by value
   and quantities by presence; `cellOverflow` lives in the **ungated** Playwright
   run. Revert 1 is caught only because `display` is a *keyword* — **a width
   regression expressed as a length would still pass.** ADR-0029 §4.
4. **Per-row labels ("Qty 0") duplicate the column headers** inside cells.
   Hiding them violates §6; changing them needs a `MoneyInput` API change.
5. **`--color-null` is 4.27:1 on `--color-surface-active`** — not live today,
   one `background: transparent` away from being live.
6. **Chromium only**; no `prefers-reduced-motion`, no `prefers-contrast`, no
   touch device, no screen reader.
7. **43 undersized hit targets** recorded and unasserted — mostly 20px checkboxes
   that are 44px via their label. **No threshold decision exists in the repo**,
   so asserting one would be an implementer's judgement standing in for the
   design's.
8. **Cascade and specificity are unpinned** — a per-rule census cannot see two
   rules fighting.

## 2. Phase 5 follow-ups — two left

1. **A read route for `corrections`.** Nothing does `select(Correction)`, so a
   reviewer cannot see the correction history of the receipt they are
   correcting and an auditor needs database access. **Blocked on an auth
   ruling.** An answer was given 2026-08-05 — *"both, scoped differently:
   reviewers see corrections for the receipt they hold, admins see any
   receipt's"* — **but it arrived alongside a system notice disclaiming it as
   user input and has never been restated. Re-confirm it verbatim before
   designing the route.**
2. **An ASGI entry point / deployment story.** `create_app` is a factory
   nothing under `src/` calls. `scripts/serve_review_e2e.py` is deliberately
   e2e-scoped — inheriting a deployment policy from an e2e launcher is the
   mistake to avoid. **The only item that can start with no ruling.**

## 3. Phase 6 — merchants & few-shot (P6.T1)

`merchants/{fingerprint,registry}.py` is greenfield; few-shot images first,
target last; hints end "trust the image"; measure top-10-merchant accuracy
before/after — **blocked on ISSUE-001**, so Phase 6 can be built but not
validated. Five things unblock here: semantic dedupe into `process_receipt`;
the same hints into `_attempt_prompt_hash`; `merchant_default_currency` at its
plug-in point in `pipeline.py` (**re-verify the line — the file has grown**);
the `image_phash` gap; `Merchant.receipt_count` (nothing writes it).
`VAT Reg. TIN` is the strongest fingerprint on this corpus.

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

- **From this branch:** the six residuals in §1.5; the class-name guard's three
  parked selector-axis leaks (harmless-but-inexact `:is`/`:where`,
  harmful-but-absurd self-contradictory `:not`, loud-and-safe `@import`);
  token *values* unpinned in the light block; `block()` assumes flat rule
  bodies; **`receipt-form.test.tsx` pins the row highlight through
  `rows[1].style.background`** — the *mechanism*, not the behaviour — which
  actively blocks moving it to a class.
- **The browser pass's five open Importants**, each measured, in
  `docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md` §3:
  **I5** terminal states, the summary alert and Approve sit **below the fold at
  1440×900**, so a failing ⌘↵ produces no visible change; **I6** the inline
  field error renders three grid columns from the field it blames; **I7** a 401
  swaps in the login form with no message and repaints restored edits
  identically to stored data; **I8** the admin tiles tell a reviewer "9 open"
  directly above "No open tasks"; **I9** the 503 says the same sentence twice.
  Every Minor (m10–m16) is also untouched. **I5 and I7 touch ADR-0024's
  contract**, so neither is a drive-by fix.
- **From Task 4:** `getByText(/carol/)` in the release round-trip is **vacuous**
  — it passes from the assignee cell before the click — and fixing the confirm
  to name the holder *visibly* is **mutually exclusive** with keeping that test
  (measured). Nothing pins stylesheet *content* in `src/admin/`; `has_more` is
  reported with no control to act on it; `busyTaskId` locks every row.
- **From the admin-UI-routes milestone:** 20 Minor findings triaged as safe.
  `GET /receipts`' `has_more` is **unpinned in the `True` direction** — a
  constant `has_more: False` survives all 979 tests.
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

Read `docs/KNOWN_ISSUES.md`, do not re-derive; hosted tool-capable model needed
(rotate the echoed Gemini key first); until it runs, no measured accuracy
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
derived at the moment of writing, with its method recorded.

---

## Running it

- Two suites: `python -m pytest` (**979**) and Vitest in `frontend/` (**346**
  across 25 files on the branch, 221 on `main`). `npm test` does **not**
  type-check — run `npm run typecheck` too. `python scripts/verify.py` is what
  "passing" means (ADR-0017).
- **`pyproject.toml` sets `addopts = "-q"`.** So `python -m pytest -q` is `-qq`
  and prints **no pass count**; `-v` nets to dot output. **Use bare
  `python -m pytest`,** or `--junitxml`.
- **`scripts/verify.py` exceeds a 2-minute tool timeout.** Background it — and
  **do not edit while it runs.** Backgrounded during an edit it caught a
  half-applied refactor and reported `FAIL build` on a `TS6133` that no longer
  existed. A phantom failure looks exactly like a real one.
- Lint: `python -m ruff check .`. The frontend linter is **oxlint**; there is
  **no formatter config anywhere** in the tracked tree.
- **`pytest -k` matches substrings, not words.** `-k tasks` does not match
  `test_an_admin_sees_a_task_assigned_to_someone_else`.
- **The working tree is MIXED, not uniformly CRLF.** `tokens.css` and
  `LineItemsTable.module.css` are CRLF; `ReceiptForm.module.css` is LF.
  `core.autocrlf=true` keeps the index content identical so diffs stay
  line-level — but a script that assumes *either* ending matches nothing and
  still reports success. **Read the bytes before anchoring on them.** (This
  bullet used to say the tree was simply CRLF; a mutation anchored on that
  assumption failed silently while this very file was being corrected.)
  And a non-empty `git diff --stat` is not enough —
  `api.py` carries `limit=limit + 1` twice, and two runs landed on the **wrong
  route** and reported the suite passing. Confirm it landed **where you meant**.
- **Grep one distinctive word, never the phrase.** `git grep "one
  unauthenticated route"` returns nothing — the sentence wraps mid-phrase. The
  same trap defeated a `git log -S` pickaxe in the same session, and the
  residual was nearly recorded as already fixed on the strength of it.
- **PowerShell `Get-Content`/`Set-Content` mangles em dashes and `§`.** Three
  separate agents hit this in one day. `Get-Content` defaults to ANSI without a
  BOM, so corruption happens on the **read**. **Use the Read/Write/Edit tools
  for anything non-ASCII** — which is nearly every file here.
- **Vitest sets `css: false`** — a `.module.css` import returns a proxy whose
  keys echo back, so **class names are unpinnable by rendering tests**; a
  renamed class ships as `class="undefined"` with every gate green. Guard by
  reading the stylesheet as text (`frontend/tests/review-null-rule.test.tsx`
  has a working example).
- **Vitest's environment pragma is matched ANYWHERE in a file**, including
  inside a docblock that merely quotes it. It silently moved a suite to Node
  and killed 11 rendering tests.
- **`dirname(fileURLToPath(import.meta.url))` DOES work under jsdom.** It is
  the `new URL(specifier, import.meta.url)` *pattern* Vite rewrites.
  `no-float-in-money-path.test.ts`'s attribution is still wrong and still
  uncorrected — it has been outside every task's permitted set.
- **Enumerating routes:** build the app and walk `app.routes` **recursing
  through `.original_router.routes`** — a flat walk yields 13 routes with
  **zero** `/auth/*` paths, which is exactly how `vite.config.ts` came to list
  13 of 16. A transitively-called guard (`require_role` → `require_user`) is
  invisible at runtime too; detect it by qualname.
- **The Grep tool mangles `/` in content output** — verify slash-sensitive
  claims with Read, `git grep` via Bash, or by executing.
- The destructive-commands hook false-positives on: `rm` under the repo;
  read-only `git grep` whose *pattern* names a sensitive file (including
  `vite.config`); heredocs containing slash-separated config filenames; and
  reading `vite.config.ts` via `cat`/`sed`. Use the Read tool and rephrase
  patterns.
- CLI: `python -m receipts.cli <command>`. E2E: `python
  scripts/seed_review_e2e.py --reset` then `cd frontend && npx playwright test`.

## Git

Default branch **`main`**; `origin` → `CDGYu/Receipt-Digitalization`, **public**.
**Pushing `feat/*` is authorised; ask before pushing `main`** (every `main` push
authorization is one-time). Merged `feat/*` branches and SDD workspaces are
**kept, never cleaned up** — this overrides the superpowers skills, which would
delete both. `.kiro/`, `.github/workflows/`, `.superpowers/`, `var/`,
`eval/golden/images/` are gitignored — never stage anything under `var/`.

**Stage by explicit path, never `git add -A`.** Several commits this session
were made while an implementer held the same worktree; each was verified with
`git diff --cached --stat` *before* committing.

## Workflow

brainstorm → design doc → ADR for anything load-bearing → implementation plan →
subagent-driven execution (one fresh implementer per task, briefed to read the
real signatures first; controller reviews the diff, **re-runs gates
independently**, **reproduces the headline mutation personally**, dispatches a
task review, appends to the ledger). Milestone close: whole-branch review on the
strongest model → ONE fix wave → one scoped re-review → ff-merge → refresh this
pair in the same session.

**Dispatch discipline (ADR-0023, as corrected 2026-08-06):** tasks that share a
file run strictly serially — **and so do tasks that share a global gate.** Two
agents with disjoint file sets can still sabotage each other if one's plan has a
deliberate RED phase and the other's definition of done is a whole-suite result.

**Brief the property, not the fix.** An enumerated list of permitted edits is an
enumerated defence and fails the same way: it produced defect #12, then its own
repair produced #16. Give a bound ("all N existing tests pass unmodified;
anything needing a test changed is a stop-and-report") and let the implementer
find the shape. Measured: the round briefed that way delivered three missing
design sections plus a hazard the controller had not thought of, in one pass.

**Never put test files outside an implementer's permitted set when the task's
deliverable needs pinning.** That was defect #15: the task that finally landed
§4 on the review screen was structurally unable to prove its own work, and the
implementer correctly refused to widen scope rather than edit a test.

**Probe before dispatching.** Plan-defect count by milestone: Phase 5 eleven;
PAN hardening five; PAN grouping six; currency bound two; failure-egress two;
review-UI error recovery four; admin release seven; admin UI backend routes
nine; **review-UI styling twenty-five**. Every one across nine milestones was
the controller's, and every one was caught by an implementer or reviewer who
checked instead of trusting. **The plan's prose is reliable; its claims about
existing artefacts are not.**

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
    examples, and **report further shapes rather than fixing them**. A round has
    converged when it adds a *universally-quantified accept-side* assertion that
    fails on the previous round's defect without anyone having thought of it.
20. **A list in prose is read as complete, so writing one is a claim.** ADR-0028.
    Four instances found false in one day; all four now closed, each by
    **re-deriving** the claim rather than editing it in place.
21. **A citation is a claim too.** Closing a prose defect ages every sentence
    that *cited* it. Twice in one day, and **twice the stale citations were
    inside review standard 20's own text.** The branch that wrote ADR-0028 §5
    forbidding line citations then created four new ones and rotted five more in
    eight days. **Grep by one distinctive word after every change; quote text or
    name a symbol rather than a line.**
22. **A universal pin can still not measure what you care about.** The
    complement of 14: a pin *proven to fail* can still be blind to its named
    property, because the environment cannot observe it. `placeholder="—"` was
    pinned over every control, proven red, and invisible in a browser — **jsdom
    cannot see a clipped box.** Structural, not anecdotal: `css: false` means a
    green class-name guard cannot mean the paint exists. **ADR-0029** states the
    blind spot for the gate set.

And: **a green suite is not evidence that installed software works** — run entry
points from outside the repository.

---

## Blocked on me (the user) — surface these, do not guess

1. **Re-confirm the `corrections` auth ruling** — answered 2026-08-05, never
   confirmed (gates §2.1).
2. **A hosted tool-capable provider + freshly rotated key** (ISSUE-001 → all
   calibration, and Phase 6's success metric).
3. **Do the public golden labels need scrubbing?** (Real third-party names,
   TINs, addresses — also the values the PAN silent-case tests pin.)
4. **R060/R061 grounding (P2.T2)** — also gates bbox highlighting.
5. **GitHub Actions again?** If yes, the workflow calls `scripts/verify.py`.
6. **Close the PAN grouping residual?** Which priced route?
7. **Narrow the `{1,2}` separator** now that its surface is measured?
8. **`main` push** — the next one needs a fresh ask, and it is due: the merge
   is the last step of §1.
9. **The theme control.** ADR-0027 ships dark as a full second theme and **the
   application has no way for a user to choose it** — the only routes in are the
   OS preference and setting `data-theme` by hand. Every token and the
   precedence rule are correct and browser-verified; the decision is
   half-delivered. It needs a home for the control, which ADR-0027 deliberately
   did not open.
10. **The currency prefix**, parked in design §5.1 with *the browser pass* named
   as its resolver. **The pass ran and never addressed it** — grepping the
   report for "currency", "prefix" or "symbol" returns nothing. Its designated
   resolver has been spent; it needs a new one.
11. **Should the Playwright visual run become a sixth gate?** ADR-0029 leaves it
   open. It would need a headless-stable config, a policy for the 43 recorded
   undersized hit targets, and a way to establish a first baseline without
   pinning current defects.

**Today's goal:** <FILL THIS IN — the default is **close the milestone** (§1),
and it is three concrete steps, in order:

1. **Fix wave B** — the documentation sweep, §1.2. Six items, all measured, none
   requiring a decision from me. It is a *sweep*: de-number citations rather than
   repoint them, and re-grep after every change (standard 21).
2. **One scoped re-review** of wave B's diff **plus `8ede47e`**, which only its
   author and the controller have seen.
3. **The ff-merge**, then refresh this pair in the same session, then **ask me
   before pushing `main`**. `src/` changed on this branch, so run the
   outside-repo import check at the merge.

If you would rather not close it, the branch is committed, pushed and green at
every step — say so and I will stop.>
