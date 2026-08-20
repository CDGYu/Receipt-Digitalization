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

**The `/app/receipts` browser pass and the gutter fix merged by true
fast-forward on 2026-08-20** — `19a0911` -> `d692cc3`, **2 commits**, single
parent each, zero merge commits. **No ADR**: the change decides nothing new, and
§4's gutter keeps the meaning it had. `docs/KNOWN_ISSUES.md`'s **ISSUE-010** is
the record and is not to be re-derived; `docs/MEMORY.md`'s Snapshot bullet is the
summary.

**The thing to know before touching it:** the not-extracted mark's hairline is a
**gutter**, not decoration — it works because a column of values shares an edge.
`Value` takes `align` (default `start`), and the three right-aligned call sites
pass `end`. **Do not re-key that off `kind`**: two of the five numeric-kind call
sites are left-aligned, so `kind` would move the rule to the wrong edge on
`StatTiles` and `ConfidenceRail`.

**And the thing it leaves undone:** the `border-radius` on a
`border-collapse: collapse` table, which is a repo-wide pattern question; and two
fixture gaps that make ISSUE-010 expensive to repeat — **no admin in the seed**
while the export route is admin-only, and a `visual` spec that **never visits the
screen**.

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

*(The `HEAD`-for-`main` substitution that stood here while a branch was in flight
is **deleted**, not kept with a caveat. Nothing is unmerged; the stamp's command
is right as written.)*

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
milestone's. The register below is complete as of that date: **eleven issues,
all eleven open.**

*(It said "nine are open" for half a day. Nine was the count of `**Status:**`
lines in `docs/KNOWN_ISSUES.md`, and ISSUE-010 and ISSUE-011 opened with
`**Opened …**` instead, so a status-anchored grep dropped the two newest entries
— while the table three rows below marked both OPEN. Both entries now carry the
Status line every other one has, so the anchor and the answer finally agree.
Review standard 23: state the anchor beside the number.)*

### The tracks

| # | track | state | where the detail is |
|---|---|---|---|
| **T2** | **Make accuracy measurable** | **BLOCKED, and it is the thing gating the project.** Untouched by the last three milestones. | §1 below, `docs/KNOWN_ISSUES.md` ISSUE-001 |
| ~~T5~~ | ~~Look at `/app/receipts`~~ | **DONE 2026-08-20.** Opened in three engines; the download works, one defect found and fixed. **No ADR.** | `docs/MEMORY.md`, ISSUE-010, §2 |
| T6 | Correctness issues left recorded | **OPEN.** ISSUE-005, 006, 007, 008, 009. | §3 below |
| T7 | Phases 7 and 8 | Partly blocked on T2. | §4 below |
| T8 | Earlier-phase leftovers | Open, unblocked, low priority. | §5 below |
| ~~T1~~ | ~~Phase 6 merchants~~ | **CLOSED 2026-08-18.** ADR-0043. | `docs/MEMORY.md` |
| ~~T3~~ | ~~Buyer and blank rows~~ | **CLOSED 2026-08-19.** ADR-0044, ADR-0045. | `docs/MEMORY.md` |
| ~~T4~~ | ~~The results list ("A1")~~ | **CLOSED 2026-08-20.** ADR-0046. | `docs/MEMORY.md`, §7 |

**If you want one sentence:** **T5 is done**, so the most important thing and
the next real build are now the same thing — **T2**, a model that can read a
receipt, blocked since 2026-07-28. The cheapest remaining valuable thing is
**ISSUE-006**, the only issue where a user gets a confidently wrong answer.

---

## THE COMPLETE ISSUE REGISTER

**All eleven, as of 2026-08-20.** `docs/KNOWN_ISSUES.md` is the source for every
row and **is not to be re-derived** — each entry there records the diagnosis,
what was already fixed, and the exact steps to resume.

| issue | one line | state |
|---|---|---|
| **ISSUE-001** | **The first real baseline run has never completed.** No accuracy number in this project is measured. Gates T2, Phase 6's success metric, P3.T6/P8.T1, and any precision claim. | **OPEN — the blocker** |
| ISSUE-002 | A repair attempt's `extraction_runs.prompt_hash` names a prompt that was never sent. | OPEN, pre-existing, deliberately not fixed |
| ISSUE-003 | A blank pre-printed row drops the unit the form prints on it (`Lt.` on all six r001 rows). | OPEN by design — labelling it creates five unearnable paths |
| ISSUE-004 | Nothing checks a golden label against its photograph; per-label content rot is open. | OPEN **by design** — re-reading the image is the only instrument |
| ISSUE-005 | `R051`'s message promises printed order; its check accepts any permutation. | OPEN — one-line fix, needs its own RED |
| **ISSUE-006** | **A reviewer who mis-flags the *sole* purchase gets zero findings at any severity and the row silently leaves the export.** All three golden receipts have that shape. | **OPEN — the only silent-wrong-answer** |
| ISSUE-007 | `PROMPT_VERSION` is unenforced; reverting it passes the whole suite. **Its easiest green is the defect.** | OPEN — needs a contract decision |
| ISSUE-008 | `xlsx._purchases` and `rules._purchased` are identical predicates with nothing binding them. | OPEN — drift risk, not wrong today |
| ISSUE-009 | `CorrectionPatch`'s docstring no longer describes the contract it validates; OpenAPI omits `buyer.*` and `is_template_row`. | OPEN — harmless, misleading |
| ISSUE-010 | `/app/receipts` **has now been opened**, in three engines. The download **works**; the predicted defect was refuted. One real finding (the gutter) is fixed. | **OPEN, narrowed** — only the collapsed-table `border-radius`, a repo-wide question |
| ISSUE-011 | A measured-false `class="undefined"` spelling survives in **three** test files (four sentences). | OPEN — pre-existing, cosmetic |

---

## THE WORK, IN PRIORITY ORDER

### §1. T2 — make accuracy measurable (ISSUE-001). THE BLOCKER.

**Nothing in this project has a measured accuracy number.** Phase 6's merchant
matching and the buyer capture are both **built and unvalidated** because of it.
Three milestones have shipped around this without touching it.

Steps 2, 3 and 4 were **answered by running them** on 2026-08-18 — read them in
ISSUE-001 rather than re-running (**ADR-0039**: the local path is a liveness
check only, and its §16 table means nothing about accuracy).

- **Step 5 — build the local→Cloud escalation. THIS IS THE NEXT REAL BUILD.**
  `make_client` returns one client, and **nothing records which model produced a
  kept extraction** — without that no eval can attribute accuracy to a model,
  and a good number could be hiding the fact that everything escalated. Report
  the escalation **rate** beside the accuracy figure. Probably an ADR.
  **Start from the measured constraint:** `_TOOLS_OFF_BY_DEFAULT` is keyed on
  the **provider**, and the exception is per **model** — `granite3.2-vision:2b`
  and `gemma4:cloud` are both provider `ollama`, so one `VLM_USE_TOOLS` cannot
  be off for the local model and on for the cloud one. Widening the key to
  `(provider, model)`, or moving the choice into whatever selects the tier, is
  this milestone's decision. **ADR-0002**'s 2026-08-18 correction records the
  constraint and deliberately does not fix it.
- **Step 6 — run the first real baseline**, detached, and commit the results
  file. **`gemma4:cloud` DOES read the receipt** (2026-08-18, r002: merchant,
  TIN, invoice, line item, both totals and payment all exact, 0 validation
  errors, in 25 seconds). **User ruling: golden set only.**
  **⚠ DO NOT REPORT A SINGLE RUN AS THE BASELINE.** Cloud inference is **not
  deterministic at `temperature=0`** — two identical runs scored 55.56% and
  61.11%. Repeats and a spread, or the figure is a sample wearing a number's
  clothes.
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
   deferred items, and **review standards 1–27**.
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

# NOTHING IS IN FLIGHT. The `/app/receipts` browser pass merged on 2026-08-20.

**`git branch --no-merged main` must name nothing.** Run it rather than
believing this sentence — it has been wrong in **both** directions, announcing
no branch while one existed for three days, and announcing one after it landed.

**You are starting, not finishing.** The work was small and the close was
proportionate: two commits, no ADR, no plan and no ledger — one browser pass and
the one defect it found. Gates re-run at the merged tip.

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

**Last full controller-run of `python scripts/verify.py`: 2026-08-20 at the
merged tip, all five gates PASS.** Everything committed after it is this handoff
pair. Re-run it rather than reasoning from that sentence.

**What this milestone proves, and it is new — review standard 27 is what came
out of it.** ISSUE-010 predicted the export download would fail, and reasoned
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

**Then** pick from the START HERE index — which as of 2026-08-20 carries **every
open issue**, not just the current milestone's — or answer the questions under
"Blocked on the user" and let that pick for you.

**If you want the shortest honest answer to "what next":** **ISSUE-001 step 5**,
the local-to-Cloud escalation. It has gated this project since 2026-07-28, it is
the next real build, and T5 — which was the cheap alternative — is now done. If
you want something smaller first, **ISSUE-006** is the only issue on the board
where a user gets a confidently wrong answer.

**Read these before you touch anything**, in this order: `docs/MEMORY.md` (state
plus **review standards 1–27**) → `docs/adr/README.md` → the ADRs its rows send
you to, of which **ADR-0046 and ADR-0045 are the two written most recently and
the two most likely to change what you do**. `docs/KNOWN_ISSUES.md` is the
source for all eleven issues and **is not to be re-derived**. Your own memory
index carries the cross-session lessons that are not in this repo at all.

**If anything in this document disagrees with the repo, the repo wins.** This
file has been wrong at the start of several sessions, including one where the
correct version was in git and the stale one was in the working tree, and one
where it carried eighteen lines of leaked string concatenation into the section
a reader is told to read first. Verify before trusting, and say what you found.