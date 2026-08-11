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

# NO BRANCH IN FLIGHT. `main` is MERGED, and AHEAD of `origin/main`.

**This header said "NO BRANCH IN FLIGHT" for three days while a branch existed**
— true when written, rotted the moment the branch was cut. It has also carried
the wrong push state twice, in both directions. Run the commands rather than the
sentence (ADR-0028 §1):

```
git status --short                                # must be empty
git log --oneline -6
git branch --no-merged main                       # must name NOTHING
git rev-parse main                                # merged tip
git ls-remote --heads origin main                 # authoritative on what is pushed
git log --oneline refs/remotes/origin/main..main  # what the pending push would send
```

## `main` is merged, and has UNPUSHED work on top.

The corrections read route **merged by true fast-forward on 2026-08-10** —
single parent, zero merge commits, `git branch --no-merged main` names nothing.
It went in only after its whole-branch review, three fix rounds and a final
scoped re-review returning **MERGE** and *"no sixteenth false claim"*.

**Eight pushes happened, each on a one-time authorization that the push
consumed** — the corrections read route (2026-08-10), then a docs fix wave, the
shared page bound, the ASGI entry point, the containerisation, CI plus the
P8.T3 eval fix, the ISSUE-001 readiness record plus the backlog
recommendations, and the CLI `--limit` bound (all 2026-08-11). **The theme
control merged after all eight and is NOT pushed. The next `main` push needs
its own fresh ask.**
**Every merged `feat/*` branch is kept at its merge point and pushed.** No
count and no list: the list rotted twice on 2026-08-11, and the commit that
replaced it with "no count is written down" wrote **"all seven"** in the same
sentence — the real figure is **21**. `git branch -r --merged main` is the
answer, and it cannot go stale. Run
`git log --oneline refs/remotes/origin/main..main` rather than believing this
sentence — empty means nothing is waiting to go, and the pair commit that
writes this necessarily lands after any push it could record.

**Freshness check.** `docs/MEMORY.md`'s stamp names **one** position again now
that nothing is in flight:

```
git log --oneline <STAMP>..main -- src tests frontend docs ":(exclude)docs/MEMORY.md" ":(exclude)docs/NEXT_SESSION_PROMPT.md"
```

**Empty means this pair is current.** Anything listed means the tree moved after
it was written.

**Gates on `main` after the merge, controller-run: `python scripts/verify.py` —
all five PASS.** pytest **1004** (was 979 before this milestone); Vitest **346
across 25 files, unmoved**, because no frontend file was in any task's file set.

**And the pre-merge check re-derived each task's deliverable from the built app
rather than from the ledger:** `list_corrections` exported with the right
signature, the three envelopes all on `_PageResponse`, the new route present in
a **recursed 17-route walk** (a flat walk still yields no `/auth/*` — review
standard 17), both ADRs and their index rows in place, and the outside-repo
import check green from `C:\Users`.

**All four tasks are complete**, each with a task review and a scoped
re-review. The close then ran in full, and §0c is its record.

---

## Reading order

1. **`docs/MEMORY.md`** — state, decisions already made, environment, blockers,
   deferred items, and **review standards 1–25**.
2. **The ledgers** — `.superpowers/sdd/*/progress.md`, one per milestone.
   **`.superpowers/sdd/2026-08-10-corrections-read-route/progress.md` is the one
   that matters now**: it holds the nine fix rounds, the nine controller
   defects, every ruling, **the deferred minor findings and the whole-branch
   review's triage of them** (every one: ships). The review-UI
   styling one records twenty-five plan defects and "THE CLOSE".
   **`.superpowers/` is gitignored — open ledgers by path; nothing in them is
   findable by searching the tracked tree.**
3. **`docs/adr/README.md`, then the ADRs (0001–0038** — count the files rather
   than trusting that range**).** *This* file's range has tracked each ADR as it
   landed; it was **`docs/MEMORY.md`'s** copy that sat at `0001–0026` while four
   more ADRs shipped, and it was corrected on 2026-08-10. Derived per-commit
   with `git show <sha>:docs/NEXT_SESSION_PROMPT.md | grep -oE "0001.00[23][0-9]"`.
   Mandatory before touching the matching area:
   - **0038** — the theme control. **Read before touching the theme, the
     header, or anything that wants browser storage.** Three states (`system`
     removes the attribute, so ADR-0027's precedence rule stays reachable both
     ways); a pre-paint script in `index.html` whose duplicated storage key is
     pinned by a text-reading test; and the **narrowing of ADR-0024** that
     permits exactly one key, which nothing else inherits.
   - **0037** — CI runs the gate runner. **Read before touching CI or adding a
     test that needs an optional package.** The workflow runs
     `scripts/verify.py` rather than re-listing gates; it fires on every branch
     because merges here are local fast-forwards; and it guards the suite's
     dependency assumptions in **both** directions — `openai` present,
     `anthropic` absent. Its first run found that the suite passes locally only
     because `openai` happens to be installed here.
   - **0036** — one image, two commands. **Read before changing how the service
     is packaged or run.** The image builds the review UI itself so a stale
     `dist` cannot ship; migrations are a documented operator step, not an
     entrypoint; `/app` holds only what the runtime reads, because a leftover
     `config/` there shadows the installed package. `docs/DEPLOYMENT.md` is the
     guide.
   - **0035** — the ASGI entry point. **Read before deploying the service or
     changing how it boots.** `uvicorn receipts.asgi:app`; importing the module
     builds nothing (a PEP-562 `__getattr__` resolves `app`); it refuses to
     start on four silent misconfigurations, chief among them an unset
     `DATABASE_URL`, which would otherwise serve production off
     `sqlite:///receipts.db`. Also records the two typed escape hatches and why
     `make_storage` moved out of `cli.py`.
   - **0034** — the shared page bound. **Read before adding a paginated route
     or changing a page window.** All three declare `limit`/`offset` through
     one `PageLimit`/`PageOffset`; an out-of-range offset is a 422 from
     request validation, not the `OverflowError` 500 ADR-0031 reported. It also
     records the contract that narrowed, and that validation now runs *ahead*
     of ADR-0031's existence-then-scope ordering.
   - **0033** — *the handoff pair goes last and alone, and a correction goes to
     every copy.* **Read before refreshing this pair, or fixing any sentence
     that appears more than once.** Bundling the pair with any other `docs/`
     change false-alarms its own freshness check (three repair commits in one
     session); `docs/MEMORY.md` states the current milestone **twice** by
     design, so search for the *claim*, not the phrasing.
   - **0032** — *a document cannot certify itself, and a derived claim can rot
     inside its own commit.* **Read before writing a fix wave's prose, or any
     sentence about how well something was checked.** Five of nine false-claim
     defects on the last branch were introduced *by fix rounds*. Gives the bound
     that closed it, and why an anchor is where the next rot lives.
   - **0031** — the corrections read route. **Read before changing who can see
     correction attribution, and before scoping `GET /receipts/{receipt_id}`:
     that route being *unscoped* is the premise its 403-not-404 rests on.** It
     also carries the schema-forced limit (a released or reopened task takes a
     reviewer's own history away) and the `offset` 500 measured on three routes
     — **that 500 is closed; see ADR-0034.**
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

## 0a. The deployment story is DONE and MERGED — entry point AND container.

*(Two milestones, ADR-0035 and ADR-0036, landed the same day and kept in one
section deliberately: splitting them would renumber §0b and §0c and age every
citation of them, which has already happened twice today.)*

    uvicorn receipts.asgi:app        # or: docker run ... receipts

Brainstormed, designed, built and closed 2026-08-11 in one session, by one
worker, with no subagents and **no plan document** — the repo's plans exist to
brief fresh implementers, and there were none. True fast-forward
`d5bf4c3` → `b2ba652`, single parent, three branch commits. Five gates PASS on
`main`, controller-run. pytest **1025 → 1040**. Design:
`docs/superpowers/specs/2026-08-11-asgi-entry-point-design.md`. Decision:
**ADR-0035**.

**Why it refuses rather than constructs.** `make_engine` resolves
`url or Settings().database_url or DEFAULT_URL`, and `DEFAULT_URL` is
`sqlite:///receipts.db` — so the obvious entry point serves production off a
local file when `DATABASE_URL` is unset, silently. Four refusals, collected and
raised once: `DATABASE_URL` unset, `SESSION_COOKIE_SECURE=false`, `REDIS_URL`
unset, and `SERVE_SPA=true` with no `index.html`.

**Two traps worth knowing before you touch it.** Importing the module builds
nothing — `app` comes from a PEP-562 `__getattr__` — and `app` is deliberately
**absent from `__all__`**, because listing it would make a star-import build the
application. An eager module-level `app` was measured: it fails the whole test
file at collection.

**The review found that `make_storage` had never been tested** under either
name, before or after being moved out of `cli.py`. Moving untested code proves
nothing; it is pinned now.

### The container — ADR-0036, merged the same day

**One image, two commands.** `.[api,worker,postgres,pipeline]`; the API takes
the default `CMD`, the worker overrides it with `python -m receipts.worker`.
683 MB, Python 3.13.15. **`docs/DEPLOYMENT.md` is the guide.**

**Two extras were measured, not guessed.** `worker` is *not* the worker's alone
— the API reaches RQ to enqueue and ADR-0035 made `REDIS_URL` a boot
requirement, so an API image without it starts cleanly and fails on every
upload. `pipeline` genuinely is the worker's: the API path calls `ingest_bytes`,
which imports only stdlib and `.storage`.

**A Node stage builds the UI** and `.dockerignore` excludes `frontend/dist`, so
a developer's stale build cannot ship — which `SERVE_SPA` could not have caught,
because a stale `index.html` is still an `index.html`.

**Migrations are an operator step**, not an entrypoint: an entrypoint would have
replicas race and turn a bad migration into a crashloop.

**`python -m receipts.worker` did not exist** until this milestone. `run_worker`
was defined and nothing invoked it — the same gap the API had before ADR-0035,
found by writing a compose `command:` that had to name something real.

**What the review found, and it was mine:** the first image left `src/` and
`config/` in `/app`, and because `config` is a top-level package and the
container runs from `/app`, `import config` resolved to **`/app/config`, not
site-packages**. The container was running a shadowed copy. `pip` now installs
from `/build`, deleted in the same layer.

**Everything above was verified by building and running the image**, not by
reading it — including `alembic upgrade head`, re-tested after the restructure.

### CI — ADR-0037, merged the same day

**`.github/workflows/ci.yml` is tracked again**, reversing the 2026-07-29
untracking. The workflow **runs `scripts/verify.py`** rather than re-listing
gates; `on: [push]`, every branch, no `pull_request:`; Python **3.11 and 3.13**;
a second job builds the image and asserts it **boots**.

**Its first run went red and was worth more than the workflow.** 7 failures in
`tests/test_client_factory.py` — those tests build a real `OpenAICompatClient`
and need the `openai` SDK **without `importorskip`**, so they fail rather than
skip. **The suite passes locally only because `openai` is installed on this
machine.** The coupling runs both ways: that module's docstring requires
`anthropic` **absent**, so CI installs `openai`, does not install `anthropic`,
and asserts both. Green on `3ad51c6`.

`scripts/serve_review_e2e.py` remains untouched by all three milestones.

## 0b. The shared page bound is DONE, MERGED and PUSHED.

Built and closed 2026-08-11 from your ruling — *"fix the offset 500 with a
shared page bound"* — with no design doc, no plan and no ledger: one defect,
two commits, true fast-forward `0851c55` → `744b533`, single parent. Five gates
PASS on `main`, controller-run. pytest **1004 → 1025**; Vitest unmoved, no
frontend file was touched. **ADR-0034** is the decision.

All three paginated routes now share `PageLimit`/`PageOffset`. An out-of-range
offset is a **422 from request validation**, exactly as `offset=-1` already
was. **The contract narrowed:** an offset between 1,000,001 and `2**63-1` used
to answer 200 and now answers 422.

**Read ADR-0034 before adding a paginated route.** Two things in it are easy to
trip over: the pin is stated over the **built app**, so re-declaring `offset` by
hand fails; and validation now runs **ahead** of ADR-0031's existence-then-scope
ordering, so a reviewer holding nothing gets 422 rather than 403 at a bad offset.

**The review found two false claims in the fix wave's own prose** and both are
fixed (ADR-0032 §6 again). **One thing was reported and not fixed:** the CLI's
`--limit` has the same unbounded shape — see "Blocked on me".

## 0c. The corrections read route is DONE, MERGED and PUSHED. Nothing carries over.

**There is no outstanding action from the last milestone.** It was merged and
`main` pushed on 2026-08-10, on an authorization **that push consumed** — the
next `main` push needs its own fresh ask. Start at §2 or answer the questions
under "Blocked on me"; this section is history, kept because it is what a reader
needs to not re-do the close.

The close ran in full: whole-branch review on the strongest model → **MERGE
AFTER FIXES**, no Critical, every finding prose → three fix rounds, each
scope-re-reviewed → a final re-review returning **MERGE** and *"no sixteenth
false claim"* → a pre-merge re-derivation of every task's deliverable from the
built app → true fast-forward, single parent.

**What the review established, so nobody re-does it:** 17 mutations run, 15
killed for the right reason; the two survivors were one equivalent mutant
(dropping `.limit(1)` from a subquery on a UNIQUE column) and the known
`GET /receipts` `has_more` gap on a *different* route. **The PAN pin holds
end-to-end** — three card shapes round-tripped through `PATCH` and came back
masked in `value_before`, `value_after` and the receipt body. **The scope fails
closed**: a role that is neither `reviewer` nor `admin` gets 403.

### 0.1 The deferred minors — ALL TRIAGED AS *SHIPS*

Recorded under review standard 19's report-don't-fix, with rulings, in
`.superpowers/sdd/2026-08-10-corrections-read-route/progress.md`. **The
whole-branch review triaged every one as *ships*; none blocked the merge.**
**No count is given here** — two anchors were tried and both were wrong, the
second because the ledger's record of that very finding quotes the phrase it
searched for (ADR-0033 §3). Read the ledger's list.

The ones still open and worth knowing:

- ~~**The `offset` 500**~~ — **CLOSED 2026-08-11 by the shared page bound,
  ADR-0034.** It was the only one of these that was a live defect.
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
  `assigned_to`, so the access **survives completion** — it ends only if one of
  decision 3's two clearing paths runs, and neither is reachable by the
  reviewer (`release_task` is admin-only). Measured: a reviewer
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

**WITHDRAWN 2026-08-11 — there is no packaging gap.** This read: *"no generated
wrapper exists in `C:\Python314\Scripts`, so `receipts --help` does not run as a
command"*, and dismissed earlier records that said otherwise. Measured:

| directory | has `receipts.exe` | on `PATH` |
|---|---|---|
| `…\AppData\Roaming\Python\Python314\Scripts` | **yes** | **no** |
| `C:\Python314\Scripts` | no | yes |

The install is `--user` and editable, so pip put the wrapper in the user scripts
directory, which is exactly right and is not on `PATH`. By full path it exits 0.
**ADR-0014's consequences already said this**, and ADR-0036's image proves the
packaging: installed system-wide, `receipts` is `/usr/local/bin/receipts`.
`python -m receipts.cli` is still the invocation that always works. Not a
regression from any
branch.

## 2. Phase 5 follow-ups — one DONE, one untouched

1. ~~**A read route for `corrections`**~~ — **DONE, merged and pushed
   2026-08-10.** ~~Nothing does `select(Correction)`~~ — false on `main` now:
   `git grep -nE 'select\(\s*Correction' -- src` returns exactly one hit,
   `review/queue.py`'s `list_corrections`. It was **zero** at `e2ec316`.

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
   envelopes. Four tasks, all complete and reviewed; the close ran in full and
   §0c is its record. Read
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
   together whenever that line is next edited. **The offset defect it also
   deferred is closed — ADR-0034.**

2. ~~**An ASGI entry point / deployment story.**~~ **DONE, merged 2026-08-11 —
   ADR-0035.** `uvicorn receipts.asgi:app`. ~~`create_app` is a factory nothing
   under `src/` calls~~ — false on `main` now: `receipts/asgi.py` calls it.
   `scripts/serve_review_e2e.py` is **unchanged** and stays e2e-scoped; its
   docstring listed the choices a deployment must revisit, and ADR-0035 is
   where they were made.

   **Scoped deliberately narrow.** The Dockerfile, compose services and
   run-book it left out landed the same day as **ADR-0036** (§0a); host, port
   and worker count stay out of the app object by design — they belong to the
   `uvicorn` invocation, and the image's `CMD` is one. **CI landed too**
   (ADR-0037), so the deployment story is complete.

   ~~**§1.6 is still open beside it**~~ — **§1.6 is CLOSED (2026-08-11): the
   wrapper exists, in the user scripts directory, which is not on `PATH`. Never
   a packaging defect.** See §1.6 itself and ADR-0035's closing note.

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
ISSUE-001**); P8.T2 grow the held-out set. ~~P8.T3~~ **DONE 2026-08-11:** an
all-failed run persisted `"auto_approval_precision": 1.0` and now persists
`null`. Two guards existed and neither covered it — `calibrate` refuses a
zero-receipt *result set* and `eval` a zero-receipt *run*, and both stand down
when receipts were read and all failed. The console already printed `n/a`;
only the number that gets written down and kept was wrong.

## 6. Still open from earlier phases

R060/R061 grounding decision (also gates bbox); score `is_handwritten` from
triage too; `is_receipt` has no consumer (never hard-reject on it); blank
pre-printed template rows (sibling of R052).

## 7. Deferred, with rulings

- **From the admin-UI-routes milestone:** 20 Minor findings triaged as safe.
  `GET /receipts`' `has_more` is **unpinned in the `True` direction** — a
  constant `has_more: False` survived the whole suite when it was measured at
  that milestone's close. **The suite has grown twice since, so re-measure
  rather than comparing to any total written down here** (ADR-0032 §3).
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

- Two suites: `python -m pytest` and Vitest in `frontend/`. **No count is
  written here** — a suite count anchored to `main` moves with every milestone,
  and this line's did. Run them (ADR-0032 §3).
  `npm test` does **not** type-check — run
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
  through `.original_router.routes`** — a flat walk yields **zero** `/auth/*`
  paths. Detect a transitively-called guard by qualname, and
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
`.superpowers/`, `var/`, `eval/golden/images/` are
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
25. **The handoff pair goes last and alone, and a correction goes to every
    copy.** ADR-0033. Commit `docs/MEMORY.md` and `docs/NEXT_SESSION_PROMPT.md`
    **in a commit touching nothing else** — the freshness check excludes exactly
    those two paths and watches `docs` otherwise, so bundling them with an ADR
    or an index row makes the pair list itself as stale (**three repair commits
    in one session**). And **find every copy before fixing one**:
    `docs/MEMORY.md` states the current milestone **twice** by design, ~700
    lines apart, so **search for the claim, not the phrasing** — the copy that
    survives is the one worded differently. The **review standards list is the
    highest-risk copy**, because the reading order sends every session here.

And: **a green suite is not evidence that installed software works** — run entry
points from outside the repository. §1.6 is the current example.

---

## Blocked on me (the user) — surface these, do not guess

**Renumbered twice on 2026-08-11.** Two items closed the same day: the `offset`
500 (was item 1 — you chose the shared page bound, ADR-0034) and GitHub Actions
(was item 9 — you said yes, ADR-0037). Everything below each moved up, and one
new item joined the end, so **a reference to "item #N" written before
2026-08-11 points at a different item.** No count is given: the list is right
here (ADR-0032 §3).

**A recommendation is attached to each item, offered 2026-08-11 and NOT a
ruling.** They are one session's reasoning, recorded so the next one does not
re-derive it from scratch — and they are exactly the kind of prose ADR-0030
says to check before acting on. **Where a recommendation and the item's own
measured text disagree, the measurement wins.**

1. **A hosted tool-capable provider + freshly rotated key** (ISSUE-001 → all
   calibration, and Phase 6's success metric).
   > **Recommended: do this first, and it is not close.** Ten of the other
   > items are cosmetic or bounded; this one is why the project cannot state a
   > real accuracy number. **Everything but the key is verified** — see
   > ISSUE-001's "Readiness check, 2026-08-11": the hosted wiring builds, the
   > timeout reaches the client, tool-use is on, and the golden labels still
   > validate zero-findings. **Only a human can do the remaining step**, and
   > the old Gemini key must be rotated regardless — it was echoed to a
   > terminal, and the repo is public.
2. ~~**The theme control.**~~ **DONE, merged 2026-08-11 — ADR-0038.** Three
   states (`system` removes the attribute, so ADR-0027's precedence rule stays
   reachable both ways), a `<select>` in the header beside sign-out, one
   `localStorage` key, and the theme applied before first paint.
   **It required narrowing ADR-0024's "nothing enters browser storage"** — that
   ruling's reason is *"no receipt-adjacent text"*, and a theme preference is
   not that. Exactly one key is permitted; nothing else inherits it.
   **Nobody has seen it in a browser** — jsdom renders no colour, so how it
   reads against the header in either theme is asserted by nothing (ADR-0038's
   own "what the gates still cannot see").
3. **The currency prefix**, parked in design §5.1 with *the browser pass* named
   as its resolver. **The pass ran and never addressed it** — grepping the
   report for "currency", "prefix" or "symbol" returns nothing. **Its designated
   resolver has been spent; it needs a new one.**
   > **Recommendation CORRECTED 2026-08-11.** It said "decide it inline with
   > item 2" — item 2 is now done and this was *not* decided with it, because
   > the two are unrelated. Re-reading §5.1's dated note: the prefix carries
   > **two** independent objections, and the second does not need a browser at
   > all. **`receipt.currency` is itself a correctable text field** edited live
   > on that same screen, so a hardcoded symbol mislabels every money field on a
   > receipt whose currency is being corrected — Task 2's implementer refused on
   > exactly that ground and was upheld. The first objection (a prefix span
   > joins the accessible name, turning `Total` into `Total ₱`) is **derived,
   > not measured**, and §5.1 says checking that derivation is a reviewer's
   > first job.
   >
   > So the real question is not *where* the prefix goes. It is whether a
   > **static** prefix can be right on a screen where currency is user-editable
   > — and the answer looks like no. The live options are: **drop it**, make it
   > **dynamic** from the current field value (which still meets objection one),
   > or show the currency **once per receipt** rather than per field. That is a
   > design call, not a placement call, and it is yours.
4. **Should the Playwright visual run become a sixth gate?** ADR-0029 leaves it
   open. It would need a headless-stable config, a policy for the 43 recorded
   undersized hit targets, and a way to establish a first baseline without
   pinning current defects.
   > **Recommended: no, not yet.** A visual gate established now would pin the
   > 43 recorded undersized hit targets and today's rendering as the baseline
   > before anyone has decided whether they are defects. Revisit after items 2
   > and 3, when the UI has stopped moving.
5. **Does the census parser get replaced?** §1.1 item 1: a `;` or `{}` inside a
   value is silently mis-parsed and ships. Replacing it is real work; adding a
   bullet to ADR-0029 §4 is honest but leaves the hole.
   > **Recommended: add the ADR-0029 §4 bullet; do not rewrite the parser.**
   > The hole needs someone to write pathological CSS to reach. Documenting the
   > blind spot is cheap and true; a replacement parser is a new thing that can
   > be wrong in new ways.
6. **Should the citation sweep become a repo script?** §1.2. ADR-0028
   deliberately declined to propose a CI check for prose, and that stands until
   you say otherwise.
   > **Recommended: no.** Every prose defect found on 2026-08-11 — a false
   > filter list, two wrong counts, aged citations, a claim that CI needed no
   > ruling — needed a human to notice the *claim* was wrong, not that a number
   > had drifted. A script would have caught none of them and would read as
   > coverage.
7. **Do the public golden labels need scrubbing?** (Real third-party names,
   TINs, addresses — also the values the PAN silent-case tests pin.)
   > **Recommendation CORRECTED 2026-08-11 — the first one was wrong.** It said
   > "yes, and sooner is cheaper", which assumed a bounded scrub. Measured
   > since:
   >
   > * **The images are gitignored.** Only the *labels* are public — three
   >   files, each with `merchant.name`, `merchant.address`, `merchant.tax_id`
   >   and `receipt.number` populated. `card_last4` is **null** in all three,
   >   so no card data is exposed.
   > * **The values spread far past the labels.** The TIN appears in **8**
   >   tracked files and the merchant name in **6** — including
   >   `docs/adr/0018-pan-masking-policy.md`, three PAN plans/specs, and two
   >   test modules. The TIN is *load-bearing*: a TIN's digit groups are
   >   PAN-shaped, which is exactly why it became the silent-case fixture.
   > * **And the decisive one: scrubbing the working tree removes nothing.**
   >   `git log -G <tin> --all` finds the value in **11 commits** of a repo
   >   that is public. Every one survives a scrub.
   >
   > So this is not a cheap tidy-up. The real options are **rewrite history**
   > (force-push; breaks every clone, and this repo's standing rule is that
   > merged `feat/*` branches are kept), **make the repo private** (removes the
   > exposure at a stroke, keeps history), or **accept it and stop adding
   > copies**. That is a judgement about a real business's tax ID on a receipt
   > someone was handed, and it is **yours** — I withdraw the "sooner is
   > cheaper" framing, because the history exposure is already at its maximum
   > and does not grow.
8. **R060/R061 grounding (P2.T2)** — also gates bbox highlighting.
   > **Recommended: defer behind item 1.** It is a three-way choice (model
   > returns the text it read / a cheap OCR pass / drop the rules) and none of
   > the three can be evaluated without a working provider. Deciding it now is
   > guessing.
9. **Close the PAN grouping residual?** Which priced route?
   > **Recommended: defer, and answer it together with item 10.** Both surfaces
   > are measured and pinned, so nothing is leaking while they wait.
10. **Narrow the `{1,2}` separator** now that its surface is measured?
    > **Recommended: defer, with item 9 — they are one decision.** How much PAN
    > shape to close by construction versus by enumeration is a single
    > question, and review standard 19 says answer it as one bounded property
    > rather than two narrowings.
**If you want the short version:** unblock **1**, spend an hour on **2**
(taking **3** with it), say no to **4**, **5** and **6**, and leave **8**,
**9** and **10** until item 1 lands. **7 is not a tidy-up** — its values are in
11 commits of a public repo's history, so it is a rewrite-history / go-private /
accept-it decision, and it is yours.

*(The CLI `--limit` bound was item 11 and is **DONE, 2026-08-11** — the last
instance of the class ADR-0034 closed. `_positive_int` bounds above at
`2**63 - 1`, a representability ceiling rather than a policy one, because
`--limit 5000000` is a legitimate batch size. `--workers` shares the validator
and was measured not to need it.)*

## Today's goal

**Nothing is in flight, nothing is half-done, and nothing carries over.** The
containerisation merged and was pushed on 2026-08-11, and §1.6 is closed.
`git branch --no-merged main` should name nothing, and
`git log --oneline refs/remotes/origin/main..main` should come out empty.

**Run the freshness command in `docs/MEMORY.md`'s stamp before trusting any of
this.** If it lists anything, the tree moved after this was written — re-run
`python scripts/verify.py` and re-read §0a, §0b and §0c before acting.

**Then** pick from §2.2 onward, or answer the questions above and let that pick
for you.

**§2.2, the ASGI entry point, is DONE** (ADR-0035), and so is the
containerisation ADR-0035 left out (**ADR-0036**: Dockerfile, compose services,
`docs/DEPLOYMENT.md`). **§1.6 is closed too** — the console script was never
broken; its wrapper sits in the user scripts directory, which is not on `PATH`.
**CI is done as well** (ADR-0037), so nothing in the deployment story is
outstanding.

**If you would rather clear the decision backlog first**, items 3–7 above are all
consequences of the last milestone and all of them are one answer each: the theme
control, the currency prefix, Playwright as a sixth gate, the census parser, and
the citation sweep.

**If anything in this document disagrees with the repo, the repo wins.** This
file has been wrong at the start of several sessions, including one where the
correct version was in git and the stale one was in the working tree. Verify
before trusting, and say what you found — **and per ADR-0030, that applies to
the findings in §1 as much as to the state in the header.**
