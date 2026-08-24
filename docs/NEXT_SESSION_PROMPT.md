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

# THE TASK LIST — what is actually left, in order

**Verify the branch and push state below before acting on any of this.** This
section says what to do; the commands say where the tree is.

## 1. ISSUE-001 step 7, Task 3 — COLLECT AND LABEL REAL RECEIPTS

**This is the only thing standing between the project and a number that
describes an actual receipt, and it needs a person and a camera.** Step 7's
machinery merged 2026-08-22/23; **it grew the golden set by nothing.** The set is
three receipts, all handwritten, against a 20% handwritten target.

**Read before you photograph anything:**

| what | where | why |
|---|---|---|
| the task | `docs/superpowers/plans/2026-08-22-growing-the-golden-set.md`, **Task 3** | the four steps, controller-only |
| **its corrections** | same file, **dated defect log, Defect 7** | Step 3's instruction carries a false reason and names the wrong module |
| the design | `docs/superpowers/specs/2026-08-22-growing-the-golden-set-design.md` §3, §7a, §7b | why redaction is per receipt; what was superseded |
| the procedure | `eval/golden/README.md` | the four labelling steps, `eval/golden/TEMPLATE.json`, the money-as-string rule, `null` over a guess, the composition targets, and the public/private decision |
| the decision | **ADR-0050** | a label is fully public or fully private; `p*` is gitignored |
| what a number means | **ADR-0049**, **ADR-0040** | a baseline is a spread; what `field_accuracy` counts |

**Four things that will bite, each already paid for:**

- **`null` means "the receipt does not show this".** It is also what a redacted
  field looks like, which is why **ISSUE-019** exists: "committed whole or not at
  all" is a rule **no gate holds**, and the obvious pin is not writable.
- **Nothing can check your label against the photograph** — **ISSUE-004**. The
  images are gitignored, so a wrong transcription is invisible to CI at any
  severity. Labelling accuracy is entirely on the reader. A printed-order defect
  in `r001`/`r002` was once caught by a human reading a plan against the images
  and by nothing else.
- **Count real-label cases, not the total.** The corpus check carries two
  synthetic calendar cases that pass whether or not a label loaded.
- **A label that will not parse aborts the whole session and names itself** —
  look for `while loading golden label <name>`. **A `p*` label's value no longer
  reaches the terminal** — ISSUE-033, closed 2026-08-25 on
  `feat/golden-label-privacy`. **Two surfaces leaked, not one**, and the one
  described here was the quieter: `validate_labels` prints to the terminal, and
  steps 1 and 3 below tell you to run it and read it after every batch. Both now
  report the field path and error kind (`merchant.tax_id [string_type]`) and
  never the value. What pydantic echoed was the *failing field's* value, never
  the whole label — a sibling PII field on a record that failed elsewhere never
  appeared.

**Then re-baseline** (Task 3 Step 4) and report min/max/median/n over the new
set, never a single figure. **Compare only to a run over the same
`scored_receipts`.**

**But neither committed baseline HAS a `scored_receipts` field** — measured
2026-08-23. It was added by `3ca4ec4`, inside step 7's machinery, which merged
*after* the baseline landed at `62eefa3`; `eval/results/2026-08-22-cloud-only/`
and `eval/results/ladder-probe/` both predate it. **It has now been derived**
— 2026-08-25, by reading `results[].receipt_id` out of every repeat file in both
run directories — and **the two runs do not score the same set:**

| run | `scored_receipts` | repeats |
|---|---|---|
| `2026-08-22-cloud-only` | `{r001, r002, r003}`, identical on all five | 5, `n_failed: 0`, `spread_omitted: []` |
| `ladder-probe` | **`{r002}` alone** | 1 |

**An earlier version of this paragraph said both give `r001, r002, r003`.** That
is true of the baseline and **false of `ladder-probe`**, which scored one
receipt — as this file's own ISSUE-018 passage already said in the words "ONE
receipt", while this paragraph said otherwise. So the two are not a strong and a
weak comparison of the same thing; they are different measurements, and
comparing them is precisely the error Step 4 warns against. Do not backfill the
committed artifacts.

## 2. EVERY REMAINING TASK — the whole board, grouped by what it costs you

**This is a pointer, not a second source.** `docs/KNOWN_ISSUES.md` is the register
for every `ISSUE-` row and carries each diagnosis and its resume steps;
`IMPLEMENTATION_PLAN.md` is the phase/task reference. **Where a line here and its
source disagree, the source wins** (ADR-0030). **No issue count is written in this
section** — count `^## ISSUE-` headings in the register, and note that its
`**Status:**` lines are one per heading by design, so the two answers must agree.

### 2a. Plan 3 is MERGED. What it left behind is four owner rulings.

**Plan 3, the Editorial visual refresh, merged 2026-08-24** — true fast-forward
`9b15d6a` -> `68217a2`, 32 commits, zero merge commits, all five gates PASS at
the tip. Plan: `docs/superpowers/plans/2026-08-24-editorial-visual-refresh.md`.
Spec: `docs/superpowers/specs/2026-08-23-upload-and-visual-refresh-design.md`
§5–§7. Decision: **ADR-0052**.

**Its decision 14 — the browser pass inside the milestone — is the reason four
of the issues below exist.** It found a regression *the plan itself introduced*
(severity text at **4.39:1** on a raised surface, under the floor, **with all
five gates green**) and a zero-width table column already sitting on `main`.
Both invisible to pytest, ruff, `tsc -b`, vitest and the build. **Do this again
on any visual milestone.** `scripts/verify.py` does not run Playwright.

**The four rulings, each with a measured cause and no chosen fix. Do not guess
one — read the issue, they are not equivalent:**

| ruling | issue | why it needs you |
|---|---|---|
| **The job ceiling** | **ISSUE-029** | `DEFAULT_JOB_TIMEOUT_S = 900` is shorter than one receipt on this box — triage alone measured **696s**. The comment beside it already describes the failure it causes. A fixed constant that fits one model will not fit another. |
| **The stranded-receipt hole** | **ISSUE-030** | An interrupted run leaves a receipt at `pending` **forever**, breaking the stated guarantee that every receipt reaches a terminal state. **Raising ISSUE-029's ceiling hides this without closing it.** Reproduced on two unrelated paths. A reaper needs no migration — `updated_at` does not advance mid-run — but cannot distinguish *slow* from *stranded*, and the signal that would (progress events) is ISSUE-031. |
| **Where the progress sink belongs** | **ISSUE-031** | Narration exists on **exactly one of four** `process_receipt` call sites. `--inline` is the documented no-Redis deployment and narrates nothing, ever. Threading `progress=` through three more sites is the obvious move and may be wrong: a CLI has no Redis to write to on the deployment that most needs this. |
| **The table column fix** | **ISSUE-032** | Cause **measured**: `th` is `box-sizing: content-box` with 8px padding, so seven columns demand more than the table has and the eighth collapses to 0 at every width. Three candidate fixes with different blast radii; **one repaints every table cell in the app.** |

**Two more await you and are older:** **ISSUE-027** (a PDF is accepted at the
door and always dies at `preprocess`), and **ISSUE-006's arithmetic residual**.

**Held, not lost — two things a session deliberately did not commit.**

- **The compose `VLM_*` env.** The image can now reach Ollama (ISSUE-028 fixed
  at `45b5329`), but pointing the dev worker at a real model **while ISSUE-029
  is open** turns every dev upload into a ~15-minute hang that ends by stranding
  the receipt — strictly worse than today's fast, honest `FakeVLMClient
  exhausted`. **It should land after the ceiling, not before.** The change sits
  uncommitted in `docker-compose.yml`.
- **The `docs/` prose sweep.** A sample of six falsifiable claims in the
  high-traffic docs found **two false, both in this handoff pair** — including
  one telling the owner to rule on whether to build a screen that had shipped
  that morning. The register-wide surface (~100 falsifiable claims across
  `MEMORY.md`, this file, and `KNOWN_ISSUES.md`) is **unswept**. Note the true
  bound: **no gate checks whether any doc's prose claims are true; one gate
  (`tests/test_freshness_check.py:84,137-138`) reads this pair and checks the
  *form of one command* in it.**

**What the browser pass still owes.**

It ran and produced findings, but three items deferred from the previous
milestone were not closed by it and remain open: **raw stage identifiers shown
to an audience** (`dedupe`, `persist` are operational vocabulary), **the
production `setInterval` body is unexercised by any test**, and
**`app-admin-route.test.tsx` is misnamed** for what it now covers. Also open:
the three count cards on `/app/` keep their `min-width` at 375 and read as
unfinished — `flex: 1 1 10rem` would fix 375 *and* change the 1440 look
materially, so it is a decision.

### 2b. THE ONE THAT UNBLOCKS EVERYTHING ELSE — ISSUE-001

- **Step 7, Task 3 — collect and label real receipts.** Section 1 above is the
  whole briefing. It needs a person and a camera and no code removes it.
  **ISSUE-017 is why it outranks every model choice**: three receipts spanning
  11% to 96%, so the headline describes none of them.
- **Step 8 — calibrate thresholds** (P3.T6 / P8.T1) on a held-out split. Blocked
  on step 7.

**Five further tasks are blocked on that number and on nothing else**, and the
plan does not say so anywhere: P3.T6's calibration report, P6.T1's "measure
top-10-merchant accuracy before/after few-shot", P8.T1's fitted weights, P8.T2's
statistically valid held-out set, and P9.T1's self-hosted benchmark. **None of
them is startable today.**

### 2c. WHERE THE SYSTEM CAN STILL BE WRONG

- **ISSUE-006** — **the only issue on the board where a user gets a confidently
  wrong answer.** A reviewer who mis-flags the *sole* purchase gets zero findings
  at any severity and the row silently leaves the export; all three golden
  receipts have that shape. **The visibility half is DONE**: you ruled 2026-08-23
  that `is_template_row` is **editable**, and it shipped in plan 2 — a reviewer
  can now see and correct which rows leave the export. **The arithmetic residual
  is still open**: nothing warns when the correction empties the purchase set.
- **ISSUE-024** *(new 2026-08-23)* — nothing cross-checks the triage line-count
  against what was extracted, so spec §18's silent tall-receipt truncation goes
  undetected. `IMPLEMENTATION_PLAN.md` P2.T3, never built.
- **ISSUE-023** *(new 2026-08-23)* — consistency voting compares by exact string
  equality, so `949.20` and `949.21` disagree, and line items are compared
  positionally so one lost row cascades into every later one. P2.T1, never built.
  **Fix it before P7.T1**, not after.
- ~~**ISSUE-005** — `R051`'s message promises printed order; its check accepts
  any permutation.~~ **RESOLVED 2026-08-24** at `5c72af5`, pinned by a
  permutation whose sorted set is still `0..n-1` — a gap or a repeat would have
  passed under the old check and proved nothing.
- **ISSUE-025** *(new 2026-08-23)* — best-attempt selection is proven only in
  isolation; no pipeline-level test drives a repair that makes things worse.
- **ISSUE-002 / ISSUE-003** — recorded, deliberately not fixed. Read the entries
  before reopening either.

### 2d. THE ESCALATION IS UNOBSERVABLE — four issues, one shape

Worth taking as one milestone rather than four line-fixes, because **ISSUE-015's
missing reader is ISSUE-013's natural fix**:

- **ISSUE-012** — the per-rung counts never reach the committed results JSON.
- **ISSUE-013** — they are keyed by `model_id`, but a tier is `(model, use_tools)`.
- **ISSUE-015** — `PassAttempt.rung` is write-only in production.
- **ISSUE-018** — the escalation records *that* it escalated, never *why*.

**Two of these were once called gates on step 6's number; step 6 committed one
without them.** Read them as caveats on that figure rather than as blockers.
**And they will not bite the next baseline either** — today's config is one rung
and granite is too slow on this box for a laddered run, so a re-baseline after
Task 3 will be cloud-only again. *(Do not use "fix these first so the new baseline
records its provenance" as the reason to do them. That reason was checked on
2026-08-23 and it does not hold.)*

- **ISSUE-014 / ISSUE-016** — the other two ADR-0047 residuals. **ISSUE-016 is
  report-don't-fix**: do not enumerate fields, and do not change `is_filled` —
  `field_accuracy` shares it by design.

### 2e. SPECIFIED, NEVER BUILT

- ~~**ISSUE-026** — a receipt cannot enter the system from a browser.~~
  **RESOLVED 2026-08-24.** `/app/upload` was built, mounted and merged, and is
  **pinned as mounted** by mutation. This bullet asked you to rule on building a
  screen that had already shipped, for a day — found by a query, not by anyone
  re-reading it.
- **P5.T1's bounding-box highlighting** — never built, and gated on the R060/R061
  grounding decision, because nothing produces the text layer it would key off.
- **P7.T1 self-consistency** — `run_consistency` lives in `extract/extractor.py`
  with **zero callers**. Gate on `triage.is_handwritten`, **never
  `document_type`**; consistency runs are never cached. **Close ISSUE-023 first**
  or you wire two known defects onto a live path.

### 2f. RECORDED, HARMLESS, CHEAP

**ISSUE-008** (a `LineItem.is_purchase` on the schema is the single source),
**ISSUE-009** (declarations plus a docstring), **ISSUE-011** (four deletions — say
the class *ships unpainted*, do not describe the mechanism), **ISSUE-007** (needs
a contract decision first), **ISSUE-004** and **ISSUE-019** (both structural — a
rule no gate holds, recorded rather than fixable), **ISSUE-010** (all that remains
is the collapsed-table `border-radius`, a repo-wide question nobody has ruled on).

### 2g. WAITING ON YOU, NOT ON ANYONE'S TIME

The full list is under "BLOCKED ON THE USER" below. The ones that block work
rather than merely tidy it: **the four rulings in 2a** (ISSUE-029/030/031/032),
**R060/R061 grounding** (which also gates bbox), and **what happens to
`IMPLEMENTATION_PLAN.md`**. *(ISSUE-006's flag decision and ISSUE-026's upload
ruling were both given on 2026-08-23 and both shipped; this line asked for them
again for a day.)* On the last: its checkboxes are **93 unticked out of
93**, and its "Current state" still lists fourteen things as "Specified but not
built" that all shipped, so it competes with the register instead of
complementing it. **You ruled 2026-08-23 that the boxes stay unticked for now**;
whether the file is corrected or retired is still open.

## 3. How to work here, and why it is not optional

- **Every review this project has run has found something real.** On 2026-08-22/23,
  four branches got four independent reviews and every one found a false claim or
  a guard that did not guard, in work that had already been checked. **Five gates
  were green on all of them.**
- **ADR-0051** is the newest and the one that changes what you do: a guard must
  not share its derivation with its subject. **Put the mutation where the
  SUBJECT computes its answer**, not where the guard computes its expectation.
- **Review standards 1—28** are in `docs/MEMORY.md`. Hold all of them.
- **The handoff pair goes last and alone** (ADR-0033), and **every `main` push
  needs its own fresh ask.**
- **No file here records whether `main` is pushed.** Two sentences claiming it
  rotted, the second on 2026-08-23. `git ls-remote --heads origin main` against
  `git rev-parse main` is the answer; `git log --oneline
  refs/remotes/origin/main..main` says what a push would send.

---

# BRANCH AND PUSH STATE — the commands below are the answer, not this heading.

**Do not expect `git rev-parse main` to equal the stamp's anchor.** It will be
ahead of it by the pair commit, because a stamp cannot name the commit that
writes it. A draft of this header once said "`main` is untouched at `6f29aa5`",
which the pair commit falsified the instant it landed — ADR-0032 §2, in the
sentence claiming the document was current.

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

## What last merged, and how to check what is pushed.

> **This section was stale when you were last handed it, for the third time.**
> The 2026-08-22 refresh left this paragraph naming **step 5** although **step 6
> had already merged** before that refresh was written. The warning two
> paragraphs down said this paragraph had failed to move twice; it then failed a
> third time, in the very refresh that carried the warning. **Read the git
> commands above, not this heading.**

**PLAN 3 — the Editorial visual refresh — merged by true fast-forward on
2026-08-24**: `9b15d6a` -> `68217a2`, **32 commits**, single parent each, **zero
merge commits**. All five gates PASS at the tip, controller-run.
`feat/editorial-refresh` is kept at its merge point. Decisions: **ADR-0052**
(the ramp changed hue, not brightness) and **ADR-0053** (two derivations from
one source are one derivation). **ADR-0023 widened a third time**: creating a
file is a shared-state write.

**A second Claude session shared that branch** and contributed six commits — a
nav bar, the `/app/` home screen, a Docker blob-volume fix, an approve-button
label, and R051's ordering fix. All were reviewed on the same terms as the
plan's own work.

**That gate run is worth one line of its own.** Three earlier full-suite
attempts failed on `Test timed out in 5000ms`, with jsdom environment setup at
**32s against a normal ~1s**, while an unrelated process held **23,590 seconds
of CPU on four cores**. **A timeout is not an assertion failure.** Re-run before
believing one, and do not merge on "probably environmental" — the clean run is
what settled it.

**It grows the golden set by nothing, and that is the whole remaining job.**
Task 3 of `docs/superpowers/plans/2026-08-22-growing-the-golden-set.md` is
controller-only: collect and label real receipts. It needs a person and a
camera.

**What to know BEFORE you photograph anything:**

- **ISSUE-020 is CLOSED** (2026-08-22), and it would have stopped you on the
  first receipt: the real-corpus check scored every label against a frozen
  `today` of 2026-07-28, so anything dated after 2026-07-29 failed `R031`. It
  now builds a bare `ValidationContext()` and carries two synthetic calendar
  cases bounding `today` at both ends. **Do not re-pin it to a literal.**
- **ISSUE-021 is CLOSED** (2026-08-22). The corpus was built inside a bare
  `except Exception` that could only ever fire for a label that would not read
  or parse, and it took the whole corpus to `{}` while the suite stayed green.
  The handler is gone; a bad label now aborts collection.
- **ISSUE-022 is CLOSED** (2026-08-23). That abort used to name nothing — the
  filename appeared zero times in the whole output. It now prints
  `while loading golden label <name>`. A bad label still stops the whole
  session; it just tells you which one.
- **ISSUE-033 is CLOSED** (2026-08-25, on `feat/golden-label-privacy`), and it
  was both narrower and wider than it was recorded as. **Narrower:** pydantic
  echoed the **failing field's** value as `input_value=...`, not the label's
  content — measured at two failure sites, a sibling PII field on a record that
  failed elsewhere never appeared. **Wider:** it leaked on two surfaces, and the
  traceback was the quieter one. `validate_labels` prints to the terminal, and
  `eval/golden/README.md` and Task 3 steps 1 and 3 all tell a labeller to run it
  after every batch. Redaction is scoped to `p*`, reusing `.gitignore`'s own
  prefix; a public label keeps the echoed value, and a pre-existing pin requires
  that.
- **Count real-label cases, not the total.** The corpus check carries two
  synthetic calendar cases that pass whether or not a label loaded, and
  `test_every_label_file_on_disk_reached_the_corpus` is a *regression* guard
  against re-adding a swallow — for a label you just added it is green whether
  it parsed or was filtered out.
- **The plan's Task 3 Step 3 still tells you "a failure there means the label is
  wrong, not the test".** ISSUE-020 was the counter-example; the blanket
  remains. Plan Defect 7 is the record, and it also says to run the whole suite
  rather than the one module Step 3 names.
- **ISSUE-019** — "a label is committed whole or not at all" is a rule **no gate
  holds**, and the obvious pin is not writable, because the README tells you to
  use `null` for what a receipt does not show. Redacted and absent look the
  same.

*(The previous last-merge was **ISSUE-001 step 6, the first measured accuracy
number in this project's history**, 2026-08-22 — `3939147` -> `aca2521`, 22
commits, single parent each, zero merge commits. Decision **ADR-0049**.
**The number is a spread and describes no receipt** — 60.00-61.43% across five
repeats, while per receipt those same runs give 60.71-64.29%, 91.67-95.83% and
**11.11% on every one of the five**. That is ISSUE-017. **Do not quote 60%.**)*

*(The previous last-merge was **ISSUE-001 step 5, the local-to-Cloud
escalation**, 2026-08-21 — `de90c8a` -> `1f245d9`, **30 commits**, single
parent each, zero merge commits. Decision: **ADR-0047**, which **corrects
ADR-0002**. `docs/KNOWN_ISSUES.md` ISSUE-012 through ISSUE-016 are what it
leaves.)*

**The five things to know before touching the escalation** are ADR-0047's
decisions 2, 3, 5, 6 and 8, and every one of them is a trap in a different
direction:

- **a tier is `(model, use_tools)`, not a provider.** Both models here are
  provider `ollama` and want opposite answers about tool use;
- **the trigger runs BEFORE `normalize`.** After it, `DEFAULT_CURRENCY` fills
  `currency` and that reads as content the model produced — the fallback would
  never fire. This predicate has been wrong twice in that direction already;
- **the escalation is eval-only**, and `run_receipt`'s caller set is pinned by
  an **AST enumeration**, not a grep. Adding a caller is a deliberate act;
- **non-final rungs run with `max_repairs=0`**;
- **`VLM_TIMEOUT_S` bounds one HTTP attempt, not one call.** The SDK retries
  twice, so any elapsed timing is wall clock over an unknown number of attempts.
  **There is no per-call measurement in this repository** — do not quote one.

**What the escalation left undone was the accuracy number — and step 6 has
since delivered it** (ADR-0049; read the spread, never a single figure).
Two of ADR-0047's open issues bite there specifically —
ISSUE-012 (the per-rung counts never reach the committed results file) and
ISSUE-013 (they are keyed by `model_id`, so two tiers on one model collapse into
one count).

*(The previous last-merge was the **results list and the admin export button**,
2026-08-20 — `b563242` -> `f0dc7b6`, 23 commits, single parent each, zero merge
commits. Decision **ADR-0046** — the list is a projection of the export's query,
and a screen nothing mounts is not delivered. **Read it before touching
`/app/receipts`, either export route, or any new screen.** It closed with no ADR;
one was written the next day at the user's request, which is why ADR-0046 cites
no branch commits and post-dates the merge.)*

*(The previous last-merge was **Buyer / Sold-To capture and blank-row
transcription**, 2026-08-19 — `a26d6c1` -> `27f765e`, 45 commits, single parent
each, zero merge commits. Decision **ADR-0044**, which **corrects ADR-0040**. It
left **ISSUE-003 through ISSUE-009**; **ISSUE-006 is the one to read first** — a
reviewer who mis-flags the *sole* purchase on a receipt gets zero findings at
any severity and the row silently leaves the export, and all three golden
receipts have exactly that shape.)*

*(The previous last-merge was **Phase 6 merchant fingerprinting**, 2026-08-18
— `8f0b413` → `9a3ffa2`, thirty commits, single parent each, zero merge
commits.
Decision: **ADR-0043**, which **corrects ADR-0011** and carries its own
`## Correction (2026-08-18)`.)* **§0h is the record**, and it is worth reading even
if you are not touching merchants: the close found a behavioural regression that
all five gates were green on.

*(This paragraph has twice failed to move when a branch landed — it named the
2026-08-13 repair until 2026-08-14, and the 2026-08-14 browser pass until this
refresh. Those are §0f and §0g. **The failure mode is a paragraph nobody thinks
to edit because it was true the last time they read it.**)*

**Every push is on a one-time authorization that the push consumes, and the
next `main` push needs its own fresh ask.** **No count and no list of past
pushes is written here** — an earlier version of this paragraph enumerated them,
the list rotted twice on 2026-08-11, and the commit that replaced it with "no
count is written down" wrote a count in the same sentence.
**Every merged `feat/*` branch is kept at its merge point and pushed**;
`git branch -r --merged main` answers **reachability only, which is weaker than
that rule** — it passed throughout the period `feat/eval-field-accuracy`'s remote
ref sat six commits behind its merge point (found and fast-forwarded 2026-08-13).
Being reachable from `main` is not the same as being *at* the merge point, and
comparing each local ref with its `origin/` counterpart is what catches the
difference. The command names no SHA, so nothing in it can be severed, but it
reads a local cache — `git ls-remote` is what is authoritative about the remote.
Run
`git log --oneline refs/remotes/origin/main..main` rather than believing this
sentence — empty means nothing is waiting to go, and the pair commit that
writes this necessarily lands after any push it could record.

**Freshness check.** `docs/MEMORY.md`'s stamp names **one** position again now
that nothing is in flight:

```
git log --oneline <STAMP>..main -- ":(top,exclude)docs/MEMORY.md" ":(top,exclude)docs/NEXT_SESSION_PROMPT.md"
```

**Empty means this pair is current.** Anything listed means the tree moved after
it was written. **Read the stamp for the SHA** — it is not written here, because
a SHA in two places is a SHA that can disagree with itself.

*(The `HEAD`-for-`main` substitution that stood here is **deleted**, not kept
with a caveat — the branch landed, so the stamp's command is right as written.
It comes back the next time a pair is written on an unmerged branch.)*

**Gates on `main` at the merged tip, controller-run: `python scripts/verify.py` —
all five PASS.** **No pytest count and no delta is given** — the number moves
with every milestone and an earlier version of this line's did. Run it.

**CI can be read without credentials.**
`gh` is not logged in on this machine, `GH_TOKEN` is unset, and the GitHub MCP
server has no Actions tool — but the repository is public, so the REST API answers
anonymously:

```
curl -s "https://api.github.com/repos/CDGYu/Receipt-Digitalization/actions/runs?per_page=5"
curl -s "https://api.github.com/repos/CDGYu/Receipt-Digitalization/actions/runs/<id>/jobs"
```

The first gives `head_sha`, `status` and `conclusion` per run; the second locates
which job failed when a run-level `failure` does not say enough. **No verdict or
run count is written here** — both move with the next push, which is the whole
reason the command is given instead.

**What is worth knowing rather than re-deriving: the 2026-08-13 guards hold on
Linux, not only on the Windows machine that wrote them.** `gates (py3.11)` and
`gates (py3.13)` both pass with `tests/test_freshness_check.py` in the suite, and
that module shells out to `git init`, `git show --name-only` and
`merge-base --is-ancestor`, and re-derives its state assertions against the real
commit graph of a fresh `fetch-depth: 0` clone. That is the class of coupling
**ADR-0014** warns about and **ADR-0037**'s first red run actually found — seven
tests that passed locally only because a package happened to be installed.

**Re-running the gates yourself is not ceremony**, and this milestone is the
sharpest evidence yet for the complementary point: **every defect found on the
2026-08-13 branch was found by a person or an agent re-deriving a claim, and
none by a gate.** The five gates stayed green throughout, including while each
defect was live. The gates certify that the code runs; they cannot read a
sentence for truth, which is what **ADR-0029** says and what **ADR-0042** now
says again from the other side.

**And the pre-merge check re-derived each task's deliverable from the built
artefact rather than from the ledger:** the guard driven red three ways (a
citation remapped back to its dead token, a fabricated token naming no commit,
and a real `--depth 1` clone failing on `fetch-depth` rather than skipping), the
fast-forward verified as eighteen single-parent commits with zero merges, and —
the one that mattered — **the two commits this branch cited on its own branch
confirmed reachable from `main` after the merge**, because a replay instead of
a fast-forward would have orphaned them and turned the branch's own guard red
on contact.

**All four tasks are complete**, each with a task review and a scoped
re-review. The close then ran in full, and §0f is its record.

---

## START HERE — every open task, in one place

**This index is a pointer, not a second source.** Each row names where the
detail lives, and where a row and its source disagree, **the source wins**
(ADR-0030: a finding is a claim, and so is a summary of one).

Rewritten 2026-08-20 to carry **every** open issue rather than the current
milestone's. **No count is written here any more.** `docs/KNOWN_ISSUES.md` is
the register; count its `^## ISSUE-` headings, and note that its `**Status:**`
lines are one per heading by design, so the two answers must agree.

*(A count stood here and rotted twice in two days — first "nine are open" when
eleven were, then "eleven issues, all eleven open" when ISSUE-012 through 016
had been added by the escalation milestone's close. A number in a pointer to a
source is a second source, which is what ADR-0030 says a summary is.)*

*(The first of those two rotted counts was an anchor problem: "nine" counted
`**Status:**` lines while two entries opened with `**Opened …**` instead. Every
entry carries the Status line now, so a heading count and a Status count agree —
which is the check to run, not a number to read. Review standard 23.)*

### The tracks

| # | track | state | where the detail is |
|---|---|---|---|
| **T2** | **Make accuracy measurable** | **Steps 5 and 6 are DONE (ADR-0047, ADR-0049).** A number exists and it is a spread. **Step 7 — grow the golden set — is the next thing, and ISSUE-017 is why it now matters more than the model does.** | §1 below, `docs/KNOWN_ISSUES.md` ISSUE-001 |
| ~~T5~~ | ~~Look at `/app/receipts`~~ | **DONE 2026-08-20.** Opened in three engines; the download works, one defect found and fixed. **No ADR.** | `docs/MEMORY.md`, ISSUE-010, §2 |
| T6 | Correctness issues left recorded | **OPEN.** ISSUE-005, 006, 007, 008, 009. | §3 below |
| **T9** | **What the escalation left** | **OPEN.** ISSUE-012 and 013 were called gates on step 6's number; step 6 committed one anyway (ADR-0049) and they stayed open. 014, 015, 016 likewise. | **§6b below**, ADR-0047 |
| T7 | Phases 7 and 8 | Partly blocked on T2. | §4 below |
| T8 | Earlier-phase leftovers | Open, unblocked, low priority. | §5 below |
| ~~T1~~ | ~~Phase 6 merchants~~ | **CLOSED 2026-08-18.** ADR-0043. | `docs/MEMORY.md` |
| ~~T3~~ | ~~Buyer and blank rows~~ | **CLOSED 2026-08-19.** ADR-0044, ADR-0045. | `docs/MEMORY.md` |
| ~~T4~~ | ~~The results list ("A1")~~ | **CLOSED 2026-08-20.** ADR-0046. | `docs/MEMORY.md`, §7 |

**If you want one sentence:** **collect and label real receipts — step 7's
Task 3.** Steps 5 and 6 landed the mechanism and the number; step 7's machinery
landed 2026-08-22 (ADR-0050) and grew the set by nothing. **Read plan Defect 7
first** — ISSUE-020, ISSUE-021 and ISSUE-022, which would each have stopped or
misled you, are all closed.
If you want something smaller, **ISSUE-006** is still the only issue on the board
where a user gets a confidently wrong answer.

---

## THE COMPLETE ISSUE REGISTER

**Every issue, as of 2026-08-25 — with three exceptions.** ISSUE-020, ISSUE-021 and ISSUE-022 are closed and have no row here: the register carries 33 `^## ISSUE-` headings and this table 30, compared 2026-08-25. `docs/KNOWN_ISSUES.md` is the source for
every row and **is not to be re-derived** — each entry there records the
diagnosis, what was already fixed, and the exact steps to resume. **This table
is a pointer; where it and an entry disagree, the entry wins.**

| issue | one line | state |
|---|---|---|
| **ISSUE-001** | **Step 6 is DONE (2026-08-22).** `transcription_accuracy` min 60.00% / max 61.43% / median 60.00% over five repeats — but read ISSUE-017 before quoting it. Steps 7 and 8 remain. | **OPEN, NARROWED** |
| ISSUE-002 | A repair attempt's `extraction_runs.prompt_hash` names a prompt that was never sent. | OPEN, pre-existing, deliberately not fixed |
| ISSUE-003 | A blank pre-printed row drops the unit the form prints on it (`Lt.` on all six r001 rows). | OPEN by design — labelling it creates five unearnable paths |
| ISSUE-004 | Nothing checks a golden label against its photograph; per-label content rot is open. | OPEN **by design** — re-reading the image is the only instrument |
| ISSUE-005 | `R051`'s message promises printed order; its check accepted any permutation. | **RESOLVED 2026-08-24** at `5c72af5` — pinned by a permutation, not a gap |
| **ISSUE-006** | **A reviewer who mis-flags the *sole* purchase gets zero findings at any severity and the row silently leaves the export.** All three golden receipts have that shape. | **OPEN — the only silent-wrong-answer** |
| ISSUE-007 | `PROMPT_VERSION` is unenforced; reverting it passes the whole suite. **Its easiest green is the defect.** | OPEN — needs a contract decision |
| ISSUE-008 | `xlsx._purchases` and `rules._purchased` are identical predicates with nothing binding them. | OPEN — drift risk, not wrong today |
| ISSUE-009 | `CorrectionPatch`'s docstring no longer describes the contract it validates; OpenAPI omits `buyer.*` and `is_template_row`. | OPEN — harmless, misleading |
| ISSUE-010 | `/app/receipts` **has now been opened**, in three engines. The download **works**; the predicted defect was refuted. One real finding (the gutter) is fixed. | **OPEN, narrowed** — only the collapsed-table `border-radius`, a repo-wide question |
| ISSUE-011 | A measured-false `class="undefined"` spelling survives in **three** test files (four sentences). | OPEN — pre-existing, cosmetic |
| **ISSUE-012** | **The per-rung counts never reach the committed results JSON.** They reach the printed report and the return value; `run_eval` writes the file before it returns and `run_baseline` folds them in after. | **OPEN.** This row said "must close before step 6 commits a number"; step 6 committed one on 2026-08-22 without it |
| **ISSUE-013** | **`extract_rung_counts` is keyed by `model_id`, but ADR-0047 defines a tier as `(model, use_tools)`** — so two rungs on one model with opposed tools flags are two tiers and one count, and the escalation goes invisible in the figure that exists to expose it. | **OPEN — a decision ADR-0047 does not take** |
| ISSUE-014 | `frozen=True` on `PassAttempt`, `RunOutcome` and `PassClients` is pinned by nothing; dropping any one leaves the suite green. Tree-wide there are 10 frozen dataclasses and 0 `FrozenInstanceError` assertions. | OPEN — stated interface property, unenforced |
| ISSUE-015 | `PassAttempt.rung` is **write-only in production** — four write sites, no reader in `src/` or `eval/`. | OPEN — either give it a reader (see ISSUE-013) or drop it |
| ISSUE-016 | `read_nothing` still counts vacuous values as content: `merchant.name=""`, `totals.total=0`, `prices_include_tax=False`. The **third** never-fires shape in this predicate's history. **It gates a ladder configuration**, which its own "does not gate anything" filing denies. | OPEN — **report-don't-fix**; do not enumerate fields, do not change `is_filled` |
| **ISSUE-017** | **The baseline's variance is across receipts, not repeats.** r001 60.71-64.29%, r002 91.67-95.83%, **r003 11.11% on all five repeats**. The headline averages receipts spanning 11% to 96% and describes none of them. | **OPEN — read before quoting any figure** |
| **ISSUE-018** | **The escalation records that it escalated, never why.** ADR-0047 decision 3 discards on two clauses — raised, or read nothing — and `PassAttempt` has no field for which. A timeout and an unreadable page are different facts. | **OPEN — a decision, and ISSUE-015's missing reader** |
| ISSUE-019 | "A label is committed whole or not at all" is a rule **no gate holds**, and the obvious pin is not writable — the README tells you to use `null` for what a receipt does not show, so redacted and absent look the same. | OPEN — structural |
| ~~ISSUE-020~~ | A frozen `GOLDEN_TODAY` reddened the suite for any receipt dated after 2026-07-29. | **CLOSED 2026-08-22** |
| ~~ISSUE-021~~ | One unloadable label silently took the whole real-corpus check to `{}` while the suite stayed green. | **CLOSED 2026-08-22** |
| ~~ISSUE-022~~ | That abort named no file; it now prints `while loading golden label <name>`. | **CLOSED 2026-08-23** |
| **ISSUE-023** | **Consistency voting has neither tolerance nor shared alignment.** `_vote` compares by exact string equality over `json.dumps(...)`, so `949.20` and `949.21` disagree and line items are compared positionally. `align_line_items` shipped for this and its only callers are `eval/metrics.py` and its own tests. | **OPEN — `IMPLEMENTATION_PLAN.md` P2.T1, never built. Fix before P7.T1** |
| **ISSUE-024** | **Nothing cross-checks the triage line-count against what was extracted.** 30 rules registered, highest id R070, and both uses of `estimated_line_item_count` sit inside R013, which fires only at zero rows. Spec §18's silent truncation is undetected. | **OPEN — P2.T3, never built** |
| ISSUE-025 | Best-attempt selection is proven only in isolation; no pipeline-level test drives a repair that makes things worse, which is exactly the direction P2.T4's acceptance names. | OPEN — coverage gap, not a behavioural defect |
| ISSUE-026 | A receipt cannot enter the system from a browser. | **RESOLVED 2026-08-24** — `/app/upload` built, mounted, pinned by mutation |
| **ISSUE-027** | **A PDF is accepted at the door and always fails at `preprocess`.** `validate_upload` accepts one, `load_image` raises `UnsupportedFormat`, and `expand_pdf` has zero callers. The upload screen refuses PDFs client-side as an interim. | **OPEN — needs your ruling: wire `expand_pdf`, or stop accepting PDFs?** |
| ISSUE-028 | The containerised worker could only ever run the `fake` VLM client — the image lacked the `openai` extra, so every OpenAI-shaped provider raised at client construction. **Every compose run this project has ever done was silently a fake-client run.** | **RESOLVED 2026-08-24** at `45b5329`; the re-reading of past runs is not |
| **ISSUE-029** | **The job ceiling is shorter than one receipt.** `DEFAULT_JOB_TIMEOUT_S = 900`; triage alone measured **696s** under the project's own local model. Its own comment already describes the failure it causes. | **OPEN — needs your ruling: what ceiling, and derived from what?** |
| **ISSUE-030** | **An interrupted receipt has no terminal state, ever.** Breaks the stated "nothing is silently dropped" guarantee. **Not RQ-specific** — reproduced on a synchronous CLI path. Raising ISSUE-029's ceiling **hides this without closing it**. | **OPEN — needs your ruling: reaper, per-runner hook, or both?** |
| **ISSUE-031** | **Progress narration exists on exactly one of four `process_receipt` call sites.** `--inline` — the documented no-Redis deployment — narrates nothing, ever. | **OPEN — needs your ruling: where does the sink belong?** |
| **ISSUE-032** | **A control paints over the column beside it at every width.** Cause measured: `th` is `box-sizing: content-box` with 8px padding, so seven columns demand more than the table has and the eighth renders at **0**. | **OPEN — needs your ruling: three fixes, one repaints every table cell** |
| ISSUE-033 | A `p*` label's value was printed by `validate_labels` — the command Task 3 tells a labeller to run after every batch — and by the pytest traceback. Per-field, not whole-label. | **CLOSED 2026-08-25** on `feat/golden-label-privacy` |

---

## THE WORK, IN PRIORITY ORDER

### §1. T2 — make accuracy measurable (ISSUE-001). **STEP 6 IS DONE; STEP 7 IS NEXT.**

**Nothing in this project has a measured accuracy number.** Phase 6's merchant
matching and the buyer capture are both **built and unvalidated** because of it.

**What changed on 2026-08-21: the mechanism now exists.** Step 5 is done
(ADR-0047), so for the first time since 2026-07-28 a model that can read a
receipt can be put in front of the golden set. **Step 6 is no longer waiting on
anything.**

Steps 2, 3 and 4 were **answered by running them** on 2026-08-18 — read them in
ISSUE-001 rather than re-running (**ADR-0039**: the local path is a liveness
check only, and its §16 table means nothing about accuracy).

- ~~**Step 5 — build the local→Cloud escalation.**~~ **DONE 2026-08-21,
  ADR-0047.** Merged `de90c8a` -> `1f245d9`, 30 commits. The ladder is **per
  pass**, not confidence-triggered, because ISSUE-001's own measurements falsify
  the premise a confidence trigger rests on. Read **ADR-0047 before touching the
  client factory, `run_receipt`, or the eval harness**; its decisions 2, 3, 5, 6
  and 8 are five traps in five different directions.
  *(Its docstring-level claim that "nothing records which model produced a kept
  extraction" was **overstated**: `extraction_runs.model_id` records every call.
  What was missing was the link from a receipt to the run it kept — and on the
  eval path that is not a database problem at all.)*

- **Step 6 — run the first real baseline. THIS IS NOW THE NEXT REAL WORK, AND
  NOTHING BLOCKS IT.** Detached, and commit the results file.
  **`gemma4:cloud` DOES read the receipt** (2026-08-18, r002: merchant, TIN,
  invoice, line item, both totals and payment all exact, 0 validation errors, in
  25 seconds). **User ruling: golden set only.**

  **Read ISSUE-012 and ISSUE-013 before you start**, because both decide what
  the committed number is worth: the per-rung counts **do not reach the results
  JSON**, and they are **keyed by `model_id`** when a tier is
  `(model, use_tools)`, so two tiers on one model collapse into one count.

  **Configuration.** Today's `.env` runs both passes on `gemma4:cloud` with no
  fallback, which is one rung — a valid cloud-only baseline. If you point triage
  at granite, **set `VLM_USE_TOOLS_TRIAGE=false`**: `VLM_USE_TOOLS` is
  process-wide and tools-on costs granite the `merchant_name_guess` ADR-0043
  decision 1 keys off.

  **⚠ DO NOT REPORT A SINGLE RUN AS THE BASELINE.** Cloud inference is **not
  deterministic at `temperature=0`** — two identical runs scored 55.56% and
  61.11%. Repeats and a spread, or the figure is a sample wearing a number's
  clothes.

  **⚠ AND DO NOT QUOTE A PER-CALL TIMING.** `VLM_TIMEOUT_S` bounds one HTTP
  attempt and the SDK retries twice (ADR-0047 decision 8), so every elapsed
  figure in this repository covers an unknown number of attempts. There is no
  per-call measurement here; one was invented during the last milestone and
  deleted.
- **Step 7 — grow the golden set.** Three receipts cannot validate any accuracy
  claim; one receipt is 33 percentage points. This gates the goal more
  fundamentally than the model does.
- **Step 8 — calibrate thresholds** (P3.T6 / P8.T1) on a held-out split.

**Standing rulings that bound this work:** Ollama only, no hosted APIs
(2026-08-14); high extraction accuracy is the goal, with no target number yet;
cloud egress is authorised for the **golden set only** — routing production
uploads to the cloud is a separate decision and has **not** been made.

### §2. T5 — DONE 2026-08-20. `/app/receipts` has been opened.

**Merged by true fast-forward `19a0911` -> `d692cc3`, 2 commits, no ADR.**
`docs/KNOWN_ISSUES.md`'s ISSUE-010 is the record and carries every measurement;
**do not re-derive it.** In brief, item by item as this section used to list
them:

1. **The download WORKS**, in Chromium, Firefox and WebKit — `200`, a valid
   workbook on disk, four sheets, the same rows the screen showed. The detached
   anchor and the synchronous revoke lose nothing. **The two fix shapes this
   section used to recommend are struck as unnecessary.** The green is worth
   believing because the probe was **proven red first**: with `anchor.click()`
   removed, all three engines returned `200` and produced no download.
2. **The two stacked negative margins are correct** — `-22px` against a `24px`
   gap leaves `--space-xs` at both joints, at three widths in both themes.
3. **This one was real, and it is fixed.** The mark's hairline is a *gutter*, and
   a left-edge gutter in a right-aligned column aligns with nothing; a currency
   with no total put the rule between the code and the mark. `Value` gained
   `align` (default `start`) and `.notExtractedEnd`. **`kind` is not the axis** —
   `StatTiles` and `ConfidenceRail` both render numeric kinds left-aligned.
4. **Confirmed ignored, and STILL OPEN.** The `border-radius` on a
   `border-collapse: collapse` table renders square. Pre-existing as a pattern —
   `TaskTable` and `LineItemsTable` both do it — so it is a repo-wide question
   nobody has ruled on. **This is all that is left of ISSUE-010.**

**Two things this pass found by following this section's own instructions, both
still true and both unfixed:** there is **no admin in the seed**
(`scripts/seed_review_e2e.py` creates one reviewer) while `GET /export/xlsx`
requires admin, so clicking Export as the seeded user 403s; and **`npx playwright
test visual` never navigates to `/app/receipts`** — every `goto` in that spec
targets `/app/login`, `/app/review` or `/app/admin`. Anyone repeating this needs
both.

**Still unseen, repo-wide: 768 at every surface, and dark theme everywhere
except this screen** — which was looked at in dark at 1440 and renders
correctly. The scope of what has ever been looked at is the *SUPERSEDED IN PART*
block of `docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md` — that
block is the source; do not restate it.

### §3. T6 — the recorded correctness issues

**ISSUE-006 first.** It is the only one where a user gets a confidently wrong
answer. The readability half is fixed; **surfacing the flag in the review UI is
a design decision**, and the arithmetic pin needs the one-purchase shape rather
than the two-purchase one. It touches the same screens as the results list, so
read **ADR-0046** before changing either.

Then, in rough order of cheapness: **ISSUE-005** (one line, needs its own RED),
**ISSUE-008** (a `LineItem.is_purchase` on the schema is the single source),
**ISSUE-009** (declarations plus a docstring), **ISSUE-011** (four deletions —
say the class *ships unpainted*, do not describe the mechanism), **ISSUE-007**
(needs a contract decision first: give `prompt_bundle_hash()` a production
caller, which changes spec §16's filename), **ISSUE-002**, **ISSUE-003**,
**ISSUE-004**.

### §4. T7 — Phases 7 and 8

- **P7.T1 self-consistency.** `run_consistency` exists in `extract/extractor.py`
  with **zero references in `pipeline.py`**. Gate on `triage.is_handwritten`,
  **never `document_type`**; consistency runs are never cached. **Its value went
  up for a reason it was not designed for**: cloud inference is nondeterministic
  at `temperature=0`, and self-consistency is exactly that remedy. r002 *is*
  handwritten, so the gate would fire.
- **P3.T6 / P8.T1** threshold sweep + confidence weights into
  `config/rules.yaml` — **blocked on ISSUE-001**.
- **P8.T2** grow the held-out set. Target 50–100 receipts; it is 3.

### §5. T8 — still open from earlier phases

R060/R061 grounding decision (also gates bbox highlighting); score
`is_handwritten` from triage too; `is_receipt` has no consumer (**never
hard-reject on it**). §6 below has the full list, §7 what is deferred with
rulings.

### §6b. T9 — what the escalation left (ISSUE-012 … 016)

All five are recorded in `docs/KNOWN_ISSUES.md` with their measurements, and
**ADR-0047's "What this ADR does not decide"** is why two of them are open
decisions rather than bugs. **Do not re-derive them.**

**These two were called gates on step 6's number. Step 6 committed a number on
2026-08-22 without settling either, so read them as caveats on that figure
rather than as blockers:**

- **ISSUE-012 — the per-rung counts never reach the committed results JSON.**
  They reach the printed report and the return value. `run_eval` writes the file
  before returning; `run_baseline` folds counts in after. ISSUE-001 step 6
  commits that file as the durable record, so a baseline landed today records
  the accuracy but not which model produced it. **Fixing it moves who owns the
  write** — a design change, not a line.
- **ISSUE-013 — the counts are keyed by `model_id`.** ADR-0047 decision 2
  defines a tier as `(model, use_tools)`, so two rungs naming one model with
  opposed tools flags are two tiers and one count key, and the escalation goes
  invisible in the figure built to expose it. Both the plan and the field's own
  comment specify this key, so **changing it is a decision.**

**These three do not gate anything:**

- **ISSUE-014** — `frozen=True` on `PassAttempt`, `RunOutcome` and `PassClients`
  is pinned by nothing; dropping any one leaves the suite green. Tree-wide: 10
  frozen dataclasses, 0 `FrozenInstanceError` assertions.
- **ISSUE-015** — `PassAttempt.rung` is **write-only in production**: four write
  sites, no reader in `src/` or `eval/`. Either give it a reader (it is the
  natural fix for ISSUE-013) or drop it.
- **ISSUE-016** — `read_nothing` still counts vacuous values as content
  (`merchant.name=""`, `totals.total=0`, `prices_include_tax=False`). This is the
  **third** never-fires shape in that predicate's history; ADR-0047 §3a names the
  pattern. **Report-don't-fix** (review standard 19): do not enumerate fields,
  and **do not change `is_filled`** — `field_accuracy` shares it by design, so
  narrowing it moves a published metric.

---

## BLOCKED ON THE USER — surface these, do not guess

1. **Rotate the Gemini API key at Google.** Deleted from `.env` 2026-08-18;
   deleting it there **changes nothing about the exposure**. *(Corrected under
   my own name: it was **never** in this repo's git history — I claimed it was,
   verified four ways, and was wrong. The real exposure is that it was echoed to
   a terminal on 2026-07-28.)*
2. ~~**A browser pass on `/app/receipts`** (ISSUE-010).~~ **DONE 2026-08-20**,
   and it earned its cost twice over: the download **works** in three engines
   (the predicted defect was refuted), and looking found a real defect the issue
   had only guessed at, now fixed. **What it leaves you** is the collapsed-table
   `border-radius` — a repo-wide pattern question — and two gaps in the fixtures
   that are worth a ruling: **the seed creates no admin** while the export route
   is admin-only, and **the `visual` spec never visits the screen**. Neither was
   fixed, because both change tracked files that were outside this work.
3. **Do the public golden labels need scrubbing?** Real third-party names, TINs
   and addresses. **Not a tidy-up:** the TIN is in **11 commits** of a public
   repo, so it is a rewrite-history / go-private / accept-it decision.
4. **`min-height: 60vh`** on the failure notice (item 14) — undecided.
5. **Browser-pass I7** (item 12) — a 401 mid-review swaps in the login form with
   no message. Touches **ADR-0024**'s contract, so it is a contract change, not
   a drive-by fix.
6. **Should the Playwright visual run become a sixth gate?** Recommended **no,
   not yet** — it would pin 43 recorded undersized hit targets as the baseline.
7. **Should the citation sweep become a repo script?** Recommended **no** —
   every prose defect found needed a human to notice the *claim* was wrong.
8. **R060/R061 grounding**, and the **two queued PAN scoped decisions** (the
   grouping residual and the `{1,2}` separator) — all recommended **defer**.

---

## WHAT IS NOT OPEN — do not re-do these

The deployment story is complete: entry point (**ADR-0035**), container
(**ADR-0036**), CI (**ADR-0037**), guide (`docs/DEPLOYMENT.md`). Eval field
accuracy is redefined (**ADR-0040**, corrected by **ADR-0044**). Also shipped:
the theme control (**ADR-0038**), the shared page bound (**ADR-0034**), the
corrections read route (**ADR-0031**), the CLI `--limit` bound, merchant
fingerprinting (**ADR-0043**), buyer/blank-row capture (**ADR-0044**), and the
results list (**ADR-0046**). §1.6's "packaging gap" was **withdrawn** — it was
never one.

---

## Reading order

1. **`docs/MEMORY.md`** — state, decisions already made, environment, blockers,
   deferred items, and **review standards 1–28**.
2. **The ledgers** — `.superpowers/sdd/*/progress.md`, one per milestone.
   **`.superpowers/sdd/2026-08-10-corrections-read-route/progress.md` is the one
   that matters now**: it holds the nine fix rounds, the nine controller
   defects, every ruling, **the deferred minor findings and the whole-branch
   review's triage of them** (every one: ships). The review-UI
   styling one records twenty-five plan defects and "THE CLOSE".
   **`.superpowers/` is gitignored — open ledgers by path; nothing in them is
   findable by searching the tracked tree.**
3. **`docs/adr/README.md`, then the ADRs** — **no range is written here; count
   them.** Compare the two answers **to each other** rather than to any number
   in this file: `ls docs/adr/*.md | grep -v README | wc -l` (how many ADRs) and
   `grep -cE "^\| *\[?0[0-9]{3}" docs/adr/README.md` (how many index rows).
   Mandatory before touching the matching area:
   - **0048** — *a rationale is a second claim, and it is the one nobody
     checks.* **Read before writing a plan, a brief, a docstring or a fix wave's
     prose.** Wrong facts announce themselves; wrong *reasons* license the wrong
     action, because a reason reads as evidence the author understood the thing.
     Four instances in one milestone, none of them a lie — including a "local
     import avoids a cycle" comment for a cycle that does not exist, **written
     one task after the identical species was recorded**. Its decision 2 is the
     usable one: where a reason is load-bearing, **name the thing that would fail
     if it were false**; if nothing would, the thing is unpinned and that is the
     finding. It is review standard 28.
   - **0047** — *a tier is a model and its tools flag, and the escalation is
     eval-only.* **Read before touching the client factory, `run_receipt`, the
     eval harness, or anything that decides which model runs.** It **corrects
     ADR-0002**. Decision 2 is why tool use is resolved by one function and not
     two; decision 3 is the fallback trigger, whose definition was **wrong twice
     in the never-fires direction** — and 3a names the pattern, because a third
     is expected and ISSUE-016 is it; decision 5 is the user's eval-only ruling,
     pinned by an **AST enumeration** rather than a grep, with §5a stating what
     the guarantee does *not* cover; decision 6 is why a discarded rung gets no
     repair budget; and decision 8 is that **`VLM_TIMEOUT_S` bounds one HTTP
     attempt, not one call** — so no elapsed timing here is a per-call figure.
     Its closing section says what no gate can see: **the escalation has never
     run against a real model.**
   - **0046** — *the list is a projection of the export's query, and a screen
     nothing mounts is not delivered.* **Read before touching `/app/receipts`,
     either export route, or any new screen or entry point.** Decision 1 is why
     the list is not built on `GET /receipts`; decision 2 is the guard asymmetry
     a later reader will want to "tidy" away; decision 3 is why a new paginated
     route must join `PAGINATED_PATHS`; decision 5 is that **a screen nothing
     mounts is deletable with every gate green**, which happened here in the
     very next screen after a test was built to close it for `/app/admin`; and
     decision 6 is that **a mutation which does not compile proves nothing**.
   - **0045** — *a brief is a claim about the tree, and relaying one makes it
     yours.* **Read before writing a plan, before dispatching any task, and
     before ordering work on a finding somebody else measured.** Decision 1
     makes pre-flighting a brief against the tree mandatory; decision 3 says a
     claim you pass between agents becomes yours to re-derive; decision 4 says
     "your number was wrong" is itself a claim. **It was written on 2026-08-19
     and was cited nowhere in this file until 2026-08-20** — the session that
     followed it produced nine plan defects, three of them assertions that could
     not fail, and every one was caught by an implementer or reviewer who ran
     the mutation instead of reasoning about it. It is the highest-yield ADR in
     this repository for anyone running the subagent workflow.
   - **0044** — the model-facing surface is two channels. **Read before touching
     `prompts.py`, `schema.py`, or anything a model is shown.** It **corrects
     ADR-0040**.
   - **0043** — merchant identity is two-phase. **Read before touching
     merchants, dedupe, or the prompt hash.** It **corrects ADR-0011**.
   - **0042** — a cited commit must stay reachable, and a rewrite carries its
     citations. **Read before citing a commit, before rewriting history other
     documents cite, and before writing about a commit no ref can reach.**
     `tests/test_sha_citations.py` enforces it: reachability not existence
     (`git cat-file -e` succeeds on an orphan until `gc`), any ref not `main`
     (an ADR cites its own branch before the merge), a shallow clone **fails**
     rather than skips. **It corrects ADR-0032 decision 3** — a closed anchor's
     claim is permanent, its retrievability is not. Its decision 5 is the one
     that bites while you write: the backticked short form *is* the citation,
     so a dead commit is named bare or at full oid, and no sentence can show an
     example of the form without instantiating it. **Its coverage boundary is
     stated in the ADR and is narrower than the one-line version** — a token
     inside a larger backticked span is invisible.
   - **0039** — the local path is a liveness check. **Read before running the
     eval harness or believing its output.** A local run prints the six §16
     metrics and licenses only "the pipeline completes"; liveness artefacts stay
     out of `eval/results/`; and the local timing is **not** to be re-derived.
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

> **This section is the archive, not the task list.** Every entry below is a
> milestone that has already merged; it exists for the reading order each one
> leaves behind. **What is actually left is "THE TASK LIST" at the top of this
> file.**

*(§0e and §0d are newest and sit first deliberately. They are lettered rather
than renumbered to the front because renumbering ages every citation of §0a–§0c,
and that has already happened twice in this file's history.)*

## 0h. Phase 6 merchant fingerprinting — DONE, MERGED and PUSHED (2026-08-18).

**Nothing carries over.** True fast-forward `8f0b413` → `9a3ffa2`, **thirty
commits, single parent each, zero merge commits**. `feat/merchant-fingerprinting`
is kept at its merge point and pushed. Decision: **ADR-0043**, which **corrects
ADR-0011** and now carries its own `## Correction (2026-08-18)`.

**No `main` push state is recorded here** — see "Today's goal" for why the claim
was removed rather than updated. `git log --oneline refs/remotes/origin/main..main`
is the answer.

**Read in this order:**

1. **ADR-0043** — `docs/adr/0043-merchant-identity-is-two-phase.md`. Ten
   decisions. Read it before touching merchants, dedupe, or the prompt hash.
   It **corrects ADR-0011**, whose "semantic dedupe is deliberately not wired"
   bullet is now false and carries its own dated correction.
2. **The design** — `docs/superpowers/specs/2026-08-14-merchant-fingerprinting-design.md`.
   **Read its dated notes**; one rules out the obvious few-shot source, another
   scopes its own opening table as a pre-milestone snapshot that is no longer
   current.
3. **The plan** — `docs/superpowers/plans/2026-08-14-merchant-fingerprinting.md`.
   **Read its dated CORRECTED blocks first. Two of its own code listings were
   wrong** and would have shipped green.
4. **The ledger** — `.superpowers/sdd/2026-08-14-merchant-fingerprinting/progress.md`.
   **Gitignored — open it by path.** Every ruling, every deferred minor, and what
   each costs if wrong. Nothing in it is findable by searching the tracked tree.

### The behavioural defect, and it beat every gate

**Reprocessing an original that had a semantic duplicate failed EVERY time**, and
threw away the extraction the run had just paid for. Measured:
`status=needs_review`, `failed_stage='persist'`, `extraction_runs` did not grow,
repeatable, recoverable only by deleting the copy's row — for which there is no
command. Reachable with **no `--force`**: `cmd_reprocess` always permits
`pending`, `needs_review` and `rejected`.

The mechanism is the part worth carrying. `_find_duplicate_image` has **two**
defences against exactly this — a reprocess skip on `_ALREADY_EXTRACTED`, and a
back-link filter in `find_duplicate_by_phash` — **and its own docstring names the
failure and says "neither defence is load-bearing alone."** The content path
shipped with **neither**. The design and the plan both cited `mark_duplicate`'s
`ValueError` as a *safety property*; it is one, and it takes the persist stage
down instead of corrupting the chain. Neither document treated the raise as a
control-flow path.

**Closed by one predicate at both ends**, not two rules that must agree:
`resolves_back_to` is the chain walk lifted out of `_reject_cycle`;
`find_duplicate_by_content` refuses to *offer* what `mark_duplicate` would refuse
to *link*. The walk is transitive on purpose — a one-hop filter matching the
phash twin **fails the chain test**, which is pinned. **`find_duplicate_by_content`'s
`exclude_id` contract changed** and ADR-0043's correction is where that is
recorded; whether the phash side should be widened to match is **not decided**.

### What the close cost, and it is the argument for running it

**No gate saw any of it.** All five were green throughout, including while the
regression was live.

**The fix wave wrote three new false claims while closing old ones.** One
restated a clause it had been **explicitly forbidden** to write, with the number
filed off: told not to write about re-photographs or Hamming distance, it
produced *"a second photograph of a purchase already stored is credited"* — true
only if that photograph lands more than five bits away on the perceptual hash.
The wave's self-audit caught two of its own; the scoped re-review caught three
more. **Every one was closed by deletion**, which is now five milestones running.

**Two of the six new tests are sole witnesses** across the whole suite — the
dedupe fall-through and the `_resolve_merchant` rollback. Before this milestone
that rollback was load-bearing and pinned by **nothing**: deleting it left 1157
green while producing the row of nulls its docstring promises cannot happen, and
the test whose *name* claimed the guarantee patched `register` to raise **before
any database work**, so it never reached the handler.

### What this milestone does NOT do, so nobody looks for it

- **No accuracy is validated.** Nothing here is measurable until ISSUE-001 runs.
  "Hints improve extraction" is a hypothesis, and ADR-0043 says so.
- **`few_shots_for` is built, tested, and deliberately never called** — few-shot
  images are Cloud-tier-only and no Cloud tier exists. Not dead code; a recorded
  decision. Do not "fix" it.
- **No `fingerprint.py`.** `normalize_merchant_name` already existed.
- **`image_phash`-based merchant matching** is explicitly out of scope.

### Five things that will bite you

- **A populated `merchant_id` does NOT mean the TIN was read.** The name-lookup
  fallback populates it too. Semantic dedupe keys off that column.
- **Semantic dedupe never saves a model call.** It runs post-extraction, so the
  extraction is already paid for. ADR-0011's §18 cost-control reasoning is about
  the *image* path; citing it here cites the wrong path.
- **Same-merchant, same-date, same-total repeat purchases WILL merge.** Inherent
  to the key. Survivable only because the duplicate keeps its extraction.
- **`merchants.receipt_count` is credited for a duplicate caught AFTER
  extraction, and never for a re-uploaded image** — the image path returns before
  any merchant is resolved. Three documents claimed otherwise in three different
  wordings. **Derive this from `registry.increment`'s one call site**, not from
  prose, including this bullet.
- **The two duplicate finders now refuse different sets.**
  `find_duplicate_by_phash` filters direct back-links in SQL;
  `find_duplicate_by_content` walks the chain transitively. That asymmetry is
  deliberate and recorded, not an oversight to tidy.

## 0g. Browser-pass I6, I8 and I9 are CLOSED — DONE, MERGED and PUSHED (2026-08-14).

**Nothing carries over.** True fast-forward `d5be9da` → `f92b497`, thirty-three
commits, single parent each, zero merge commits. **No ADR was written and nothing
under the top-level `src/` changed.** Both halves are narrower than they read, so
they are spelled out here: **three existing ADRs gained dated corrections** —
**0024** (decision 4's rationale quoted copy the app no longer renders), **0027**
(its "Still open" list named four findings that were closed) and **0038** — and
**six files under `frontend/src/` changed.** ADR-0024 is the one **I7** waits on,
so whoever takes I7 needs its correction, not just the decision. Design:
`docs/superpowers/specs/2026-08-13-browser-pass-i6-i8-i9-design.md` — **read its
two dated notes; they correct its own body.** Plan:
`docs/superpowers/plans/2026-08-13-browser-pass-i6-i8-i9.md` — **read its dated
defect log FIRST; fifteen controller defects, written as found.** Ledger:
`.superpowers/sdd/2026-08-13-browser-pass-i6-i8-i9/` — **gitignored, open by
path**; twenty-five rulings, each with what it costs if wrong.

**I7 is the one that stays OPEN**, by design: it touches ADR-0024's contract and
needs a ruling from you. It is item 12 in "Blocked on me".

### What shipped

**I6** — every text and money field is wrapped in a `.fieldCell` at the call site
in `ReceiptForm`, so the error sits under the field that sent it at every column
count. The wrapper is at the call site and **not inside `MoneyInput`**, because
`LineItemsTable` uses that component three times per row inside table cells.
**I8** — the tiles region opens with a caption naming the figures' scope.
**I9** — the duplicated 503 sentence became two site-appropriate ones, and the
failure notice gained a card applied only on the failure render.

### The one behavioural defect, and it beat every gate

`.caption` shipped with `grid-column: 1 / -1`. **A grid item spanning a track
makes that track non-empty**, so `auto-fit` stopped collapsing and behaved as
`auto-fill`. Measured in Chromium: at 1440 the tiles went **336px → 219px with
469px of the row blank**. At 1024 there is no difference — and 1024 is the width
of the finding's own evidence capture, which is why it survived.

**It passed all five gates, five task reviews and five scoped re-reviews.** The
whole-branch review found it by measuring a browser. If you take one thing from
this milestone, take that: **jsdom lays nothing out, so no gate here can see a
layout regression at all.**

### Then a person looked, on 2026-08-14 — and it was worth it

**`cd42e4f`**, committed hours after this merge. The acceptance run —
`npx playwright test visual`, 15/15 — was executed against the merged tree and
**its captures were read.** I6 and I8 are correct by eye, and the `auto-fit`
repair holds in a real browser rather than in a computed track list.

**Looking produced something measuring had not: a question.** I9's frame is
right and its finding closed, but the card is **mostly empty** — a
`min-height: 60vh` box around three small elements. Whether that is the right
box for a block that small is a judgement no measurement makes, so it went to
you as **item 14** rather than being fixed. The pass also confirmed the parked
finding that `.alert` and `.action` paint the card's own fill.

**The source for what was seen, at which widths and in which theme, is the
*SUPERSEDED IN PART* block of
`docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md`** — this section
and the rows in that report point at it rather than restating it, and ADR-0027's
correction deliberately carries none of it. **Dark theme at any width and 768
remain unseen.** That session then ended without refreshing this pair, which is
how the "not pushed" sentence under "Today's goal" survived into the next one.

### Four things to know before touching this area

- **`grid-column: 1 / -1` on a grid item defeats `auto-fit` collapsing.** If you
  need a full-width child inside an `auto-fit` grid, put the grid on an inner
  element instead — which is what `.tiles` now does.
- **Neither class guard joins a class to the DOM.** Both compare `styles.X`
  references in the TSX against declarations in the CSS. A wrapper that loses its
  `className` entirely is invisible unless the guard runs in **both** directions;
  the admin guard gained its reverse direction on 2026-08-14 for that reason.
- **CSS *values* are pinned by presence, not by value**, wherever the value is a
  quantity — a stated bound of the census. `min-width: 0`, `min-height: 60vh`,
  `border`, `background` are all swappable with the census byte-identical.
- **A quotation is a copy that ages.** Two docblocks on this branch quoted UI copy
  and went stale the moment it was reworded; both now describe by role instead.

### The lesson this milestone paid for

**Seven fix rounds across five tasks produced exactly one behavioural defect.**
Everything else was a sentence. **Four corrections over-reached while closing a
real defect, and all four were fixed by deletion** rather than a better rewrite.
**Six verifications passed vacuously** — including two controller greps scoped to
the wrong directory and a reviewer's own mutation batch defeated by CRLF. And
**briefing a fix as a bounded property instead of a list closed six claims where
the list named two**, after both enumerations had come back incomplete.

All fifteen plan and brief defects were the controller's; implementers and
reviewers found every one, including two corrections to the controller's own
corrections.

## 0f. A cited commit must stay reachable — DONE, MERGED and PUSHED (2026-08-13).

**Nothing carries over.** True fast-forward `e698aca` → `29a5a88`, eighteen
commits, single parent each, zero merge commits. Decision: **ADR-0042**, which
**corrects ADR-0032 decision 3**. Design:
`docs/superpowers/specs/2026-08-13-dangling-citations-design.md`. Plan:
`docs/superpowers/plans/2026-08-13-dangling-citations.md` — **read its dated
defect log first; it records seven plan defects and the divergence between its
own code block and what shipped.** Ledger:
`.superpowers/sdd/2026-08-13-dangling-citations/` — **gitignored, open by
path.**

**The defect.** Nine citations in three tracked files named commits no ref could
reach, orphaned by §0e's replay. Every claim built on them stayed true; none
stayed checkable. §0e recorded that the replay renumbered everything — and
applied that warning to §0e's own prose and to nothing else.

**What shipped.** `tests/test_sha_citations.py`, three guarantees: every
backticked seven-character hex token **in a tracked file** resolves to a commit
**reachable from some ref**; a shallow repository **fails** rather than skips
(so `fetch-depth: 1` cannot make it vacuous on GitHub); and `git rev-parse
--short HEAD` is still seven characters, so the pattern cannot silently narrow
as git widens `core.abbrev`. Plus `fetch-depth: 0` on both `actions/checkout`
steps.

### Four things to know before touching it

- **Reachability, not existence.** `git cat-file -e` succeeds on an orphan until
  `git gc` prunes it, so an existence check would have been green throughout.
- **Any ref, not `main`.** An ADR is committed before its merge and cites its own
  branch; CI fires on every push. This branch was itself an instance until the
  fast-forward landed.
- **The guard's boundary is narrower than a one-line summary of it.** A token
  inside a *larger* backticked span — `main @ <sha>`, `<sha>..<sha>` — is
  invisible, and live anchors of that shape exist. ADR-0042 names the boundary
  with its query. Widening the regex is a new decision, deliberately not taken.
- **Write a dead commit bare or at full oid**, never in single backticks — the
  short backticked form *is* the citation. A sentence cannot show an example of
  the form without instantiating it, so the only safe illustration is a commit
  that resolves.

### The lesson this milestone paid for

**Every defect on this branch was found by re-derivation; none by a gate**, and
the five stayed green throughout. **No count is written down** — findings,
rounds and instances give three different answers, which is ADR-0032 §5's trap
and this branch tripped it twice. Three were the controller's own
reasoning, corrected by subagents. **Five consecutive rounds shipped a new false
claim while closing an old one** — the last being the fix wave correcting a
*stale* claim by calling it *never true*, which a 2026-08-02 ancestor of `main`
falsifies. Two rulings came out of it and are now in `docs/MEMORY.md`'s review
standards: **an empty grep is not evidence until you have shown the grep can
match what you are looking for**, and **a permanence claim about a command is a
copy of ADR-0042's correction when the command's anchor is closed**.

**Reported here, then fixed on 2026-08-13 in the session after this one:**
`scripts/verify.py`'s docstring said `.github/workflows/` is untracked and
Actions does not run — false since ADR-0037. Re-deriving the rest of the
docstring found a second false claim that nobody had reported, and both were
deleted rather than rewritten.

## 0e. Review outcome focus is DONE, MERGED and PUSHED (2026-08-12).

**Nothing carries over.** True fast-forward `7c8dcc5` → `cd308bf`, single
parent, zero merge commits. Closes browser-pass finding **I5**. Decision:
**ADR-0041**. Plan:
`docs/superpowers/plans/2026-08-12-review-outcome-focus.md` — **read its dated
defect log first.** Ledger:
`.superpowers/sdd/2026-08-12-review-outcome-focus/` — **gitignored, open it by
path**; nothing in it is findable by searching the tracked tree.

**The merge needed a replay, and it was the controller's fault.** The handoff
pair was committed to `main` mid-session while the branch sat on the older tip,
so the two diverged and a fast-forward stopped being possible. Resolved by
replaying the branch's twelve commits onto `main`, verified faithful — the
replayed tip differed from the old tip by exactly the two pair files — rather
than by accepting a merge commit. **No pre-merge SHA is quoted anywhere in this
section, because the replay gave every one of them a new value.**
`git log --oneline 7c8dcc5..cd308bf` is the list. **If you refresh this pair
mid-milestone, either rebase before merging or keep the pair off `main` until
the branch lands.**

### What was verified, and how

- **Five gates PASS at the merged tip**, controller-run. pytest **1081** unmoved
  (no Python touched); Vitest **27 files / 372 tests**.
- **Task 1** — the outcome region and its focus effect. Review **Approved**, no
  Critical or Important. **Controller reproduced both mutations personally**:
  removing the focus call fails **three** tests on an `activeElement` assertion,
  not a null-region error; moving the alert outside the region fails on
  `region.contains(alert)`.
- **Task 2** — ADR-0041 and I5's dated verdict. One fix round, review clean.
- **Whole-branch review** (opus): **no behavioural defect**, one Critical and
  four Important, **every one about a claim that was not true**. One fix wave,
  one scoped re-review, then one targeted fix for a defect the re-review found
  **in the wave's own replacement for the Critical**.

### The defect, and the fix, in one paragraph each

**The defect.** The outcome — the backend-down explanation, the summary alert,
the terminal or held card — rendered at the end of a long document, and the
⌘↵ chord is a **`window`** listener, so it fires while the reviewer types at the
top of the form. Measured: Approve at **y=1195**, below the fold at 1440×900,
×800 **and ×1080**, with a two-line-item receipt and a **73px** row pitch. A 403
or 404 — where *the write landed and the task is gone* — produced **no visible
change at all**.

**The fix.** One `<section tabIndex={-1}>` with **no role** gathers the outcome
and takes focus when it appears; the browser scrolls a focused element into view
by itself. Measured after: `regionTop=768, scrollY=460, inView=true`, and
`document.activeElement` **is** the region.

### Three things to know before touching it

- **The region must stay a `<section>`.** `.screen > div` is the image pane's
  positional sticky selector, and that stylesheet's own comment calls it "the
  ONLY direct `<div>` child".
- **The region carries no role, and that is a user ruling** (ADR-0024 decision 4:
  a second alert makes `findByRole('alert')` match two elements and throw). For
  a `<section>`, "no role" and "no accessible name" are the same decision.
- **Nothing paints on the focused region** — `outline-style: none`,
  `box-shadow: none`, `:focus-visible` **false**, both themes. Measured, recorded
  in ADR-0041, deliberately not fixed: adding an indicator is an ADR-0027 token
  decision. The census entry for `.outcome` is a gate that would fail if one were
  added.

### I5 is FIXED and MEASURED, not SEEN

A Playwright `inView=true` is a machine measuring geometry. **What nobody has
watched is I5's own behaviour** — the outcome appearing, taking focus, and being
scrolled to. *(Narrowed 2026-08-14: this said nobody had looked at the screen
since the styling milestone's browser pass. The 2026-08-14 pass did capture the
review screen and a person read those captures — that is how I6 was confirmed —
but a still capture cannot show a scroll, and that note makes no claim about I5.)*

### The lesson this milestone paid for

One false claim — *"a future outcome rendered as a sibling is a test failure"* —
reached **four** documents: the design, ADR-0041, the ADR index, and a test's own
**name**. It was falsified by measurement (a role-less sibling leaves the suite
at 372/372) only at the whole-branch review. **Review standard 25 gained a bullet:
a test's name is a copy, and greps for the sentence never reach it.**

## 0d. Eval field accuracy is REDEFINED, DONE, MERGED and PUSHED (2026-08-12).

**Nothing carries over.** True fast-forward `871f1aa` → `01d6a5a`, single
parent, zero merge commits. Decision: **ADR-0040**. Design:
`docs/superpowers/specs/2026-08-12-eval-field-accuracy-honesty-design.md`.
Plan: `docs/superpowers/plans/2026-08-12-eval-field-accuracy.md` — **read its
"Dated defect log" at the bottom FIRST; the task text above it does not
self-amend and nine of its steps were wrong.**

**The defect.** `field_accuracy` averaged what the model **read**, what it
**correctly left empty**, and what it **said about itself**. The last two
dominate, so an extraction containing **nothing at all** scored
**42.50% / 37.50% / 36.59%**. The one real local run on file scored 45.00% —
**one path above silence.**

**What shipped.** Two axes: **group** from the path string (a prefix test, so a
schema field added later is classified without anybody deciding), and **filled**
read from the **truth side only** — reading it from the prediction would let a
model enlarge its own denominator by inventing fields. The classes tile the path
set. Floor is now ~5.9%. `field_accuracy` the function keeps its name, signature
and meaning; **`flatten` was not touched** — it has callers outside `eval/`.

**Three things to know before you touch it:**

- **`correctly_empty` still rises when a model hallucinates.** Documented, not
  hidden. The bound is narrow: every path it counts is one `field_accuracy`
  scores as agreement. Strengthening it means changing `field_accuracy`.
- **`structural_mismatch` is the residue class** — the two sides disagree about
  whether a path exists, *or* about null versus empty on one they share.
- **ISSUE-001's own proposed remedy was REFUTED, not applied.** Excluding
  `meta.*` moves r003's floor by 0.22 points; excluding only `meta.notes`
  **raises** every floor. Recorded with its measurement (ADR-0030).

**`README.md` and `RECEIPT_SYSTEM_SPEC.md` §15's "roughly 70–85%" expectation
predates this redefinition and STAYS, by ruling, until a real baseline exists.**
ADR-0040's "What this ADR does not decide" is where that is recorded.

**What this milestone cost, and it is the reason to read the defect log:** nine
plan defects, every one the controller's, every one found by an implementer or
reviewer who executed instead of trusting. **Three tests that could not fail
shipped and were caught by review, not by any gate** — an identity over its own
constructor, a substring satisfied by an unrelated percentage, and `0 == 0`.
And one enumeration went **three → five → six**; **review standard 26** is what
came out of it.

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

Line-number citations remain in live files (`frontend/src`, `frontend/tests`,
`docs/adr`, `docs/MEMORY.md`). **No count is written here, because the count is
a property of the anchor and not of the tree.** Measured 2026-08-12 over those
four paths: an anchor requiring a directory separator gives **44**; one that
does not gives **72**. This section asserted **71** from 2026-08-11 until then,
alongside a 32/39 split derived from it. **Derive it with the anchor you intend,
and state the anchor beside the number** (review standard 23).

*This paragraph is itself a worked example of standard 25.* On 2026-08-12 the
A6 index row was corrected and this section — which the START HERE index itself
declares authoritative over the row — was not, in the same commit that added
standard 26 about corrections failing to reach every copy.

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
measured. **That report's status note carries a dated verdict per finding and is
the source — this list is a copy, so where they disagree, believe the report.**
Closed there: C1, C2, C3, I4, and I5, I6, I8, I9. **I7 and the Minors m10–m16 are
what remain open.**

- **I5 — FIXED AND MERGED 2026-08-12 (ADR-0041, §0e).** Closed as *fixed and
  measured*, **not as seen**: a Playwright `inView=true` is a machine measuring
  geometry, and what nobody has watched is the outcome appearing, taking focus
  and being scrolled to — which a still capture cannot show, so the 2026-08-14
  pass leaves it exactly where it was and claims nothing about it.
  Original finding, kept because the elements still render last and the fix is
  that the reviewer is taken to them: at 1440×900 the terminal states, the
  summary alert and Approve are below the fold, so **a 403 or a 404 — where the
  write LANDED and the task is GONE — produces no visible change at all.**
  Re-measured
  2026-08-12: below the fold at **900, 800 and 1080**, and it degrades 73px per
  line item. See **§0e** and ADR-0041 (on the branch).
- **I6, I8 and I9 — FIXED AND MERGED 2026-08-14 (§0g), and SEEN 2026-08-14**
  at 1440 and 375 in light. Their original text: I6, the inline field error
  renders three grid columns from the field it blames; I8, the admin tiles tell a
  reviewer "9 open" directly above "No open tasks"; I9, the 503 says the same
  sentence twice. **I9's closure opened a new question** about the failure card's
  `min-height: 60vh` — item 14 in "Blocked on me". Scope of what was seen is in
  the report's *SUPERSEDED IN PART* block and is not repeated here.
- **I7 — the only Important finding still OPEN.** A 401 swaps in the login form
  with no message and repaints restored edits identically to stored data. Every
  Minor (m10–m16) untouched.

  *(This bullet listed I6, I7, I8 and I9 together as open until 2026-08-14. It was
  written before the §0g merge and did not move with it — the same shape as the
  status note that "advertised four fixed defects as open" for a day, in the very
  report this section points at.)*
- **I7 touches ADR-0024's contract**, so it is not a drive-by fix. (This line
  named I5 too until 2026-08-12; I5 was taken as its own milestone, which is
  §0e, and it extended ADR-0024 rather than reopening it.)

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

## 3. Phase 6 — merchants & few-shot (P6.T1) — **BUILT AND MERGED 2026-08-18**

**This section described work to do, then work on a branch. It is now shipped.**
See **§0h**, which is the record; **ADR-0043** is the decision; the design is
`docs/superpowers/specs/2026-08-14-merchant-fingerprinting-design.md` and the plan
is `docs/superpowers/plans/2026-08-14-merchant-fingerprinting.md` — **read the
plan's dated correction blocks, because two of its own code listings were wrong.**

Of the five things this section said would unblock: **semantic dedupe, the hints
into `_attempt_prompt_hash`, `merchant_default_currency`, and
`Merchant.receipt_count` are all done.** The `image_phash` gap is **not** — no
merchant matching keys off it, and ADR-0043 puts it explicitly out of scope.

`merchants/registry.py` is the only new module; there is **no `fingerprint.py`**,
because `normalize_merchant_name` already existed and its own docstring says it is
"for FINGERPRINTING". `VAT Reg. TIN` remains the strongest fingerprint on this
corpus, and ADR-0043 decision 1 is built on exactly that.

**Still true and still blocking:** top-10-merchant accuracy cannot be measured
until ISSUE-001 runs. Phase 6 was built and cannot be validated.

## 4. Phase 7 — self-consistency (P7.T1)

Wire `run_consistency` (`extract/extractor.py`, zero references in
`pipeline.py`) for handwritten/low-legibility; **gate on
`triage.is_handwritten`, never `document_type`**; consistency runs never cached.

**Its value went up on 2026-08-18 for a reason it was not designed for.** Cloud
inference is **not deterministic at `temperature=0`** — two identical
`gemma4:cloud` runs on r002 disagreed, one reading `totals.subtotal` and the
other not. Self-consistency is exactly the remedy for that, and it was scoped to
handwriting. Worth re-reading the phase with provider variance in mind before
building it, and note that r002 *is* handwritten, so the gate would fire here.

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
~~blank pre-printed template rows (sibling of R052)~~ **DONE 2026-08-19** — `is_template_row`, ADR-0044.

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

Read `docs/KNOWN_ISSUES.md`, do not re-derive. **A model that can read a receipt
is needed, and under the 2026-08-14 Ollama-only ruling that means Ollama Cloud**
— this line said "a hosted tool-capable model" until 2026-08-18, which the
ruling forbids. Rotate the echoed Gemini key regardless: that is security, and
revoking is not reissuing. Until such a runtime exists, no measured accuracy
numbers and no real precision claim.

---

## Non-negotiables

`Decimal` money path; pure validation; stable rule IDs; null over
confident-wrong; **a full PAN never persisted**; nothing silently dropped; a
machine run never overwrites a `reviewed` row; optional-import discipline;
tool-use structured output; few-shot images first; consistency never cached;
`python -m pytest` offline and Node-free.

**One of those carries a measured per-model exception, and the rule was NOT
softened.** *Tool-use structured output* stands (ADR-0002), and step 3 measured
it working properly on `gemma4:cloud` — a real `tool_calls` array with arguments
parsed into the requested schema. **`granite3.2-vision:2b` is the exception**:
tools on leaves the extraction identical and costs triage the merchant guess
Phase 6's `lookup` keys off, so `_TOOLS_OFF_BY_DEFAULT` is right for that model.
**So `VLM_USE_TOOLS=true` is correct for the Cloud tier and wrong for the local
one — and the flag is keyed on the provider, which cannot express that.** Both
are provider `ollama`. ADR-0002's 2026-08-18 correction records the exception and
the constraint; ISSUE-001 has the tables.

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
- **Vitest sets `css: false`** — a `.module.css` import returns a proxy that
  answers for **any** key, so **class names are unpinnable by rendering tests**;
  a renamed class ships **unpainted** with every gate green. Measured 2026-08-14
  in both environments: under this suite the proxy returns a *scoped* string, so
  a typo renders a plausible-looking name no stylesheet declares; in a real build
  the key is absent and React omits the attribute rather than stringifying it.
  **It does not render `class="undefined"`** — this bullet said so until
  2026-08-14, and so did six places in `value.test.tsx`. Guard by reading the
  stylesheet as text (`frontend/tests/stylesheets.test.ts` is the census) **and**
  by a reference-to-declaration guard (`value.test.tsx`'s `COMPONENTS`, or
  `admin-screen.test.tsx`'s copy for the admin surface). **Neither joins a class
  to the DOM** — both compare references in the TSX against declarations in the
  CSS, so a wrapper that loses its `className` entirely is invisible to both
  unless the guard runs in *both* directions.
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
  `cd frontend && npx playwright test`. **For the visual spec, run
  `npx playwright test visual` instead** — the whole suite consumes its one
  queued task in `review.spec.ts` by design, so a full run leaves
  `visual.spec.ts` with an empty queue and a self-diagnosing failure. The
  `visual` filter re-seeds. Measured 2026-08-14, at the cost of a run;
  `frontend/e2e/visual.spec.ts` says so in its own docblock.

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

**Numbers are stable from 2026-08-11 onward. Resolved items stay in place,
struck through, and keep their number.** This list was renumbered three times in
one day — the `offset` 500, GitHub Actions, and the CLI `--limit` bound all
closed and everything below each shifted up — and each shift aged every
reference to "item #N" written before it. Two of those references were mine and
had to be chased. Leaving a dead entry in place costs a line; moving a live one
costs a correction, so the trade is settled the other way now.

**A reference to "item #N" written before 2026-08-11 still points at a
different item**, because of those three shifts. No count is given: the list is
right here (ADR-0032 §3).

**A recommendation is attached to each item, offered 2026-08-11 and NOT a
ruling.** They are one session's reasoning, recorded so the next one does not
re-derive it from scratch — and they are exactly the kind of prose ADR-0030
says to check before acting on. **Where a recommendation and the item's own
measured text disagree, the measurement wins.**

1. **An Ollama runtime that can actually read a receipt, + a freshly rotated
   key** (ISSUE-001 → all calibration, and Phase 6's success metric).
   **[Retitled 2026-08-18.** This item said *"a hosted tool-capable provider"*
   from 2026-08-11 until then, and **your own 2026-08-14 ruling forbids that**.
   The item never stopped being the blocking one; it was pointing at a provider
   class you had ruled out, in four places in this file and two in
   `docs/MEMORY.md`.**]**
   > **LARGELY CLOSED 2026-08-18 — the runtime half is solved.** You signed in,
   > and `gemma4:cloud` is vision-capable, free-tier, and honours a `tools`
   > payload. Both of the things this item called unverified are now measured;
   > ISSUE-001 step 3 has them. **What is left of this item is not a blocker but
   > a decision**: whether `gemma4:cloud` actually reads receipts well enough
   > (it has not seen one), whether the free tier's limits survive a full run,
   > and **whether receipt images may leave this machine at all** — the
   > local-only setup never sent them anywhere, and that is a judgement about
   > third-party businesses' tax IDs, not a configuration detail.
   > **The Gemini key half is DONE and I was wrong about it.** The commented
   > block is deleted from `.env` (2026-08-18). I described it repeatedly as
   > sitting in a public repo's history; **it never was.** Verified four ways —
   > `git log -S` and `-G` both return zero commits, a broader pattern returns
   > zero, `.env` appears in no commit, and it is gitignored. I had conflated it
   > with item 7's golden-label TIN, which genuinely is in 11 commits. The real
   > exposure is the recorded one: it was **echoed to a terminal** on
   > 2026-07-28. Revoking at Google is still worth doing and now costs nothing,
   > since Gemini is out of scope — but it is not the emergency I called it.
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
3. ~~**The currency prefix.**~~ **RESOLVED 2026-08-11: dropped.** Its
   designated resolver (the browser pass) was spent, and one fact settles it
   that neither parked objection used — **`receipt.currency` is already a
   labelled, editable field on that same screen**, so the currency is shown
   once per receipt already, in the field that owns it. A prefix would repeat
   an editable value on every money field. Full reasoning in design §5.1's
   dated resolution note.
4. **Should the Playwright visual run become a sixth gate?** ADR-0029 leaves it
   open. It would need a headless-stable config, a policy for the 43 recorded
   undersized hit targets, and a way to establish a first baseline without
   pinning current defects.
   > **Recommended: no, not yet.** A visual gate established now would pin the
   > 43 recorded undersized hit targets and today's rendering as the baseline
   > before anyone has decided whether they are defects. Revisit after items 2
   > and 3, when the UI has stopped moving.
5. ~~**Does the census parser get replaced?**~~ **RESOLVED 2026-08-11: no —
   documented instead.** Reproduced first: `content: '+'` → `content: '+;XX'`
   leaves the census green, 0 failures, while the glyph differs and ships.
   **ADR-0029 §4 now carries the bullet it was missing** — the blind spot was
   neither layout, nor cascade, nor a narrower surface, so nothing named it.
   Reaching it takes deliberately pathological CSS; a quote-aware parser is a
   new component that can be wrong in new ways.
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
12. **Browser-pass finding I7** — a 401 mid-review swaps the whole screen for the
    login form with no message, and repaints restored edits identically to stored
    data. **Deliberately left OPEN by the 2026-08-14 milestone (§0g)** which
    closed I6, I8 and I9 beside it, because it touches **ADR-0024's contract**:
    the error-recovery rules about what renders, what announces, and what the
    stash may hold. Closing it is a contract change, not a fix.
    > **Recommended: rule on it before anyone builds it.** The three findings
    > merged beside it needed no ruling and cost seven fix rounds; this one needs
    > a decision about ADR-0024 first, and the milestone that closed its
    > neighbours is the cheapest moment to make it, while the surface is fresh.
13. ~~**A browser pass on the three screens §0g changed.**~~ **DONE 2026-08-14
    (`cd42e4f`), and it earned its cost.** The run was `npx playwright test
    visual`, 15/15, and a person read the captures at 1440 and 375 in light. I6
    and I8 are correct by eye and the `auto-fit` repair holds in a real browser.
    **It also produced item 14, which is a live ruling and was not one before.**
    **Not closed by it:** dark theme at any width, 768, and every untouched
    surface. Whether *that* pass happens is still a call, and the argument for it
    is unchanged — the milestone shipped a layout regression past all five gates
    and ten reviews, tiles 35% narrower with a third of the row blank at 1440,
    found only because the final reviewer measured a browser. **jsdom lays
    nothing out.**
14. **Is `min-height: 60vh` right for the failure notice?** New on 2026-08-14,
    from looking rather than measuring. `.noticeFailed`
    (`frontend/src/review/ReviewScreen.module.css`) pairs `min-height: 60vh` with
    `justify-content: center`, so the card renders correctly and **mostly empty**:
    three small elements with roughly 350px of blank above and 370px below at
    1440, and the same proportions at 375. I9's finding is closed either way —
    the frame is there, and this is not a regression.
    > **Recommended: rule on it, and expect the answer to be a token decision
    > rather than a number.** Whether a block that small should hold a 60vh box
    > is a judgement no measurement makes, which is why it reached this list
    > instead of being fixed. Worth pairing with the parked finding the same pass
    > confirmed: `.alert` and `.action` paint the card's own fill, so the alert is
    > distinguished only by its left border and `Try again` reads as a thin
    > outline on white. Both are ADR-0027 token questions and they are cheapest
    > answered together.
**If you want the short version:** **1 is largely closed as of 2026-08-18** —
`gemma4:cloud` works, the Gemini block is deleted, and what remains of it is a
judgement about sending receipt images off this machine. *(This line has twice
named the wrong thing: a hosted provider until 2026-08-18, then two Cloud
questions that are now measured.)* **The next thing to build is T2 step 5.**
Say no to **4** and **6**. Leave **8**, **9** and **10** until 1 lands. **7 is
not a tidy-up** — its values are in 11 commits of a public repo's history, so it
is a rewrite-history / go-private / accept-it decision, and it is yours.
**12** and **14** are both cheap and both about a surface that is fresh right
now: 14 is a token judgement someone has already looked at, and 12 has been
**OPEN and unchanged since the 2026-08-06 browser pass**, waiting on a ruling
rather than on anyone's time — the report's status row says exactly that.

*(**2**, **3** and **5** closed on 2026-08-11, as did the CLI `--limit` bound
that was item 11. **13** closed on 2026-08-14 and produced **14**. Their entries
are struck through above rather than removed.)*

*(The CLI `--limit` bound was item 11 and is **DONE, 2026-08-11** — the last
instance of the class ADR-0034 closed. `_positive_int` bounds above at
`2**63 - 1`, a representability ceiling rather than a policy one, because
`--limit 5000000` is a legitimate batch size. `--workers` shares the validator
and was measured not to need it.)*

## Today's goal

# NOTHING IS IN FLIGHT. TWO PLANS MERGED — AND THE GOLDEN SET IS STILL THREE RECEIPTS.

**`git branch --no-merged main` must name NOTHING.** Run it rather than believing
this sentence — it has been wrong in **both** directions, announcing no branch
while one existed for three days, and announcing one after it landed.

**What merged, 2026-08-24.** True fast-forward `791c356` -> `9170151`, **38
commits, single parent each, zero merge commits**. `feat/label-provenance-rule`
is kept at its merge point. Five gates PASS at the merged tip, controller-run.

- **Pipeline progress, end to end.** A pure `receipts.progress` vocabulary; an
  **optional, default-`None`** sink through `extract_with_repair` and
  `process_receipt`, so every existing caller is unaffected by construction; a
  Redis writer in the worker; and `GET /receipts/{id}/progress`.
- **`/app/upload`** — a receipt can now enter the system from a browser, which
  ISSUE-026 recorded it could not. The screen becomes a live processing view
  **in place**, narrating stages and stopping on **`status`, never on `stage`**.
- **ISSUE-006's visibility half** — `is_template_row` is editable in the review
  UI, so a reviewer can see and correct which rows leave the export.
- **`IMPLEMENTATION_PLAN.md` corrected against the tree**, and **ISSUE-023
  through ISSUE-027** filed.

**What did NOT merge: plan 3, the Editorial visual refresh** — and with it the
browser pass, which is the only thing that can see any of the above.

**AND THE THING THAT MATTERS MOST DID NOT MOVE.** All of that is machinery.
**The golden set is three receipts, exactly as it was**, and **ISSUE-001 step 7
Task 3 — collect and label real receipts — is still the top of the board.** It
needs a person and a camera, no code removes it, and it still gates every
accuracy claim in this project. Section 1 above is the whole briefing.

**Three things are owed before anyone demos this.**

1. **Nothing has ever run the join.** `worker -> Redis -> route -> screen` is
   pinned in halves and exercised end to end by **nothing** — `redis` is not
   installed on this machine, so no gate and no reviewer crossed that boundary.
   The design's §9 asks for a dry run of the full stack. Do it before demo day.
2. **Nobody has looked at the new screen.** jsdom lays nothing out and Vitest
   sets `css: false`, so the two-pane layout, the 1023px collapse and the stage
   list's weight are invisible to every gate. Three findings are deferred to that
   pass: raw stage identifiers shown to an audience (`dedupe`, `persist` are
   operational vocabulary), the production `setInterval` body being unexercised,
   and `app-admin-route.test.tsx` being misnamed for what it now covers.
3. **The design carries two dated corrections and plan 3 inherits the document.**
   §4's hero sequence named `validate`, `findings` and `repair` as narrated
   steps — there are exactly **three** `ProgressEvent` constructions in the tree
   and **only `stage="extract"` ever carries a detail**, so those three emit
   nothing. §3's decisions 5 and 9 describe a drop zone, a file list, `multiple`
   and a HEIC chip, **none of which was built**, deliberately. **Read both
   corrections before building from either section.**

**No push state is written here** — run the command below, and **every `main`
push needs its own fresh ask.**

**THE NUMBER, AND IT IS A SPREAD.** Cloud-only, one rung, `gemma4:cloud` both
passes, five repeats, 15 receipts, `n_failed` 0, committed at `62eefa3`:
`transcription_accuracy` **min 60.00%, max 61.43%, median 60.00%, n=5**.

**DO NOT QUOTE 60% AS THE ACCURACY.** Per receipt it is **r001 60.71-64.29%,
r002 91.67-95.83%, r003 11.11% on every one of the five repeats.** The headline
is an average over receipts spanning 11% to 96%; it describes no receipt. That
is **ISSUE-017**, and it is the finding this milestone did not expect: **the
standing warning above was aimed at the wrong axis.** Runs barely vary — ±1.4
points. Receipts vary by **85 points**.

**The escalation fired against a real model for the first time**
(`eval/results/ladder-probe/`, ONE receipt, 41m39s, not a baseline): granite ran,
was discarded, `gemma4:cloud` produced the kept extraction. ADR-0047's closing
gap is closed. **But which of its decision 3 clauses fired — raised, or read
nothing — is not recorded and cannot be recovered.** That is **ISSUE-018**, and
it is also the production reader **ISSUE-015** has been asking for.

**What to do next, shortest honest answer: ISSUE-001 step 7's Task 3 — collect
and label real receipts.** The machinery to do it safely is merged; the set is
still three. ISSUE-017 is why it outranks any model choice: on three receipts,
one is a near-total failure and the average hides it. **ISSUE-020 is closed;
read plan Defect 7 before you photograph anything.** **ISSUE-006** is
still the only issue where a user gets a confidently wrong answer.

**Two things measured this session that will bite you.**
`python -m eval.run_repeats` **does not run from outside the repository** —
`pyproject.toml` excludes `eval/` from the installed package, so invoke it from
the repo root. And **granite is far slower than ISSUE-001's carried figure
suggests**: a standalone triage call alone exceeded 10 minutes and was killed at
10m28s, and one receipt through the full ladder took 41m39s. `VLM_TIMEOUT_S` is
**600**, not the `900` ISSUE-001 step 2 still claims.

**Run these first, and believe them over this document:**

```
git branch --show-current                         # expect main
git status --short                                # must be empty
git branch --no-merged main                       # must name NOTHING
git log --oneline refs/remotes/origin/main..main  # what a push would send
python scripts/verify.py                          # background it; exceeds a 2-min timeout
```

**No push state is written here, and that is deliberate.** The command above is
the answer. **Every `main` push is a one-time authorization the push consumes**,
so the next one needs its own fresh ask no matter what the command says.

*(An earlier draft of this very refresh said "`main` IS NOT PUSHED", defending
it as the one piece of state worth stating outright. It was true when committed
and **false within the hour**, because the push it was describing then happened.
That is ADR-0032 §2 — a claim can rot inside the commit that carries it — and
this file had already learned to delete push state once before. It got
reintroduced anyway. Read the command.)*

**Last full controller-run of `python scripts/verify.py`: 2026-08-21 at the
merged tip, all five gates PASS.** Committed after it: ADR-0048 and this handoff
pair, both documentation only. Re-run it rather than reasoning from that
sentence.

**What the PREVIOUS milestone proved — review standard 27 — and it still
reads first because it is the shape most likely to bite you.** ISSUE-010 predicted the export download would fail, and reasoned
from the code: a **detached** anchor, and a **synchronous** `revokeObjectURL`.
Both readings were exactly right. Both genuinely are documented cross-browser
failure modes. **The conclusion was still wrong** — the file arrives in
Chromium, Firefox and WebKit, and the two fixes the issue recommended would have
changed working code to settle a question nobody had asked a browser.
**A defect derived from reading has the shape of a measurement and none of the
standing.**

**The second thing it proves is about instruments.** A probe's green is worth
nothing until the probe has been proven red — standard 14, applied to what you
are measuring *with* rather than to the pin. Removing `anchor.click()` sent all
three engines red on the discriminating pair (server `200`, no download), and
that is the only reason the green was written down. **A probe that cannot see
the failure whose absence it reports has reported nothing.**

**And the reproduction steps are a claim about the tree too** (ADR-0045).
ISSUE-010's own two resume steps were both wrong — no admin exists in the seed
while the export route is admin-only, and the `visual` filter never navigates to
the screen. Following them is how that was found, at the cost of one run.

**What looking produced that reading had not:** a real defect, in the item the
issue ranked third of four. The hairline is a **gutter**, and a left-edge gutter
in a right-aligned column aligns with nothing.

**And what the LATEST milestone proved is review standard 28**, which it earned
four times over: **a correct instruction carrying a false reason is more
dangerous than a missing one.** A wrong line number announces itself; an
invented *rationale* reads as understanding and licenses an implementer to
simplify something load-bearing. Every near-miss in that milestone was one.

**Then** pick from the START HERE index, which carries every open issue — or
answer the questions under "Blocked on the user" and let that pick for you.

**If you want the shortest honest answer to "what next":** **ISSUE-001 step 7's
Task 3** — collect and label real receipts. Step 5 built the mechanism, step 6
measured the number, and step 7 built the machinery that lets the set grow
without publishing real businesses' details. **What none of them did is add a
receipt**, and the number will keep describing no receipt until one does. **Read ISSUE-012 and
ISSUE-013 before starting it**, because both decide what the committed number is
worth. If you want something smaller first, **ISSUE-006** is the only issue on
the board where a user gets a confidently wrong answer.

**Read these before you touch anything**, in this order: `docs/MEMORY.md` (state
plus **review standards 1–28**) → `docs/adr/README.md` → the ADRs its rows send
you to, of which **ADR-0047 is the newest and the one that changes what you do**
if you touch extraction at all — and **ADR-0045** remains the highest-yield one
for anybody running the subagent workflow. `docs/KNOWN_ISSUES.md` is the
source for every issue and **is not to be re-derived**.

**Your own memory index carries what this repository does not.** The entries
that matter most before you start:

- `escalation-merged-and-step-6-is-next` — the five ADR-0047 traps in short
  form, and which two issues decide what a baseline number is worth;
- `a-rationale-is-a-second-claim` — ADR-0048 as a habit rather than a record;
- `ollama-hardware-ceiling-on-this-box` — **there are two Ollamas here**, and
  the project reads the Docker one on `:11435`. Name the port, and run
  `docker ps` before naming a runtime;
- `a-defect-derived-from-reading-is-a-hypothesis` — prove a probe red before
  believing its green;
- `parallel-agents-share-one-worktree` and `sdd-dispatch-lane-discipline` —
  before dispatching anything in parallel.

**If anything in this document disagrees with the repo, the repo wins.** This
file has been wrong at the start of several sessions, including one where the
correct version was in git and the stale one was in the working tree, and one
where it carried eighteen lines of leaked string concatenation into the section
a reader is told to read first. Verify before trusting, and say what you found.