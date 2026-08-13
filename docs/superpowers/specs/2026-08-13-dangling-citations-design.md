# Design — a cited SHA must resolve, and a rewrite carries its citations

**Date:** 2026-08-13
**Status:** proposed
**Anchor for every measurement below:** `main` at `e698aca`, working tree clean.
Each number states the query that produced it. Re-derive rather than quote
(ADR-0028 rule 1); several numbers here are *supposed* to change the moment the
repair lands, and one of them is the point of the milestone.

---

## 1. What this closes

Nine citations in three tracked files name commits that no ref can reach. They
were orphaned on 2026-08-12 when the review-outcome-focus branch was replayed
onto `main` rather than merged — a controller error recorded in
`docs/NEXT_SESSION_PROMPT.md` §0e, which says plainly that *"the replay gave
every one of them a new value"*. That warning was applied to §0e's own prose and
to nothing else. The documents the milestone itself wrote were not swept.

Two of them survive only as unreferenced objects. `git gc` prunes them, and on
that day nine tracked sentences point at nothing at all.

---

## 2. The defect, measured

### 2.1 The dangling citations

Query: every backticked hex token of 7–40 characters, over every tracked
non-binary file (`git ls-files`, minus image/font/lock/svg suffixes); each token
resolved with `git cat-file -e <tok>^{commit}` and then tested for reachability
with `git branch -a --contains`.

| result | count |
|---|---|
| distinct backticked hex tokens, 7–40 chars | 118 |
| resolve to a commit reachable from `main` | 110 |
| resolve to a commit reachable only from a branch | 0 |
| **resolve to a commit reachable from NO ref** | **2** |
| do not resolve to a commit at all | 6 |

**The two unreachable commits account for nine citations:**

| token | citations | files |
|---|---|---|
| 5a7fc58 | 5 | `docs/adr/0041-the-review-outcome-takes-focus.md` (×1); `docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md` (×4) |
| d2fffc0 | 4 | `docs/superpowers/plans/2026-08-12-review-outcome-focus.md` (×4) |

**Neither token is written in backticks anywhere in this document, and that is
the property working rather than a typographical accident.** §4's rule treats a
seven-character hex token wrapped in single backticks as a citation — a promise
that the reader can look it up. `e698aca` above is one, and resolves. These two
do not, and that is the whole defect, so a document *about* a dead commit names
it bare or at full 40-character length instead. Measured: the wrapped form
matches; the same token bare, its full oid wrapped, and the token inside double
quotes in a command all do not.

**This document failed its own guard on the first run**, at five such citations,
which is how the rule was found. Note the constraint that follows and is not
avoidable: **a sentence cannot show an example of the form without instantiating
it**, so the only safe example is a commit that really does resolve. ADR-0042
carries both.

**No line numbers, per ADR-0028 §5** — they would be right when written and
wrong the moment the first repair lands, which is *this* milestone. The list is
regenerated instead by `git grep -n "5a7fc58"` and `git grep -n "d2fffc0"`.
The counts above are anchored at `e698aca`; the commands answer for whatever
tree the reader has.

**The six that do not resolve are false positives of that anchor, not defects.**
Three are Fira Code tabular-figure width samples (`0000000000`, `1111111111`,
`9999999999`, in ADR-0027 and the browser-pass spec, which record that each
"measure[s] exactly 96px at 16px" — **not** PAN digit-strings, as an earlier
draft of this sentence called them), one is a PAN masking example
(`41111111111111111111`, ADR-0018), one is a date (`20260727`), and one is an
Alembic revision id (`b9342906a5a6`). The anchor is mine and it over-matches;
§4.1 is where that is dealt with, and it is dealt with by narrowing the rule
rather than by listing the exceptions (review standard 19).

### 2.2 The two replay pairs

Each orphan has a replayed equivalent already on `main`. Verified by comparing
the patches, not by comparing the subjects:

```
diff <(git show 5a7fc58 --format=) <(git show 99f0207 --format=)   # empty
diff <(git show d2fffc0 --format=) <(git show e0481f4 --format=)   # empty
git merge-base --is-ancestor 99f0207 main                          # true
git merge-base --is-ancestor e0481f4 main                          # true
```

| dead | live | subject |
|---|---|---|
| 5a7fc58 | `99f0207` | `fix: the review outcome takes focus, so a 403 is not invisible` |
| d2fffc0 | `e0481f4` | `docs: design for the review outcome taking focus (I5)` |

The dead column is bare and the live column is backticked, deliberately — see
§2.1. The replacement is checkable and so it is written as a citation; the thing
it replaces is not.

### 2.3 The ADR range, stale by one in three sentences

| query | answer |
|---|---|
| `ls docs/adr/*.md \| wc -l` minus `README.md` | **41** |
| `grep -cE "^\| *\[?0[0-9]{3}" docs/adr/README.md` | **41** |
| four-digit prefixes | contiguous, 0001–0041 |

Against that, three sentences say otherwise. Quoted rather than cited by line
(ADR-0028 §5), and all three are found by:

```
git grep -n -E "0001[^0-9]*0040|40 rows" -- docs
```

**The character class is not decoration.** The range is written with an **en
dash** (U+2013, bytes `e2 80 93`), and `git grep`'s `.` matches one *byte*, so
`0001.0040` returns **zero hits** — measured, after this spec's first draft
handed over exactly that pattern. `[^0-9]*` spans the three bytes. And the range
pattern alone finds only **two** of the three: the row count is its own sentence
and needs its own term.

* `docs/MEMORY.md` — *"**`docs/adr/` — 0001–0040** (re-derived at the 2026-08-12
  merge: `ls docs/adr/*.md` minus `README.md` counts **40** …"*
* the same file, in the same parenthesis — *"the index table carries **40
  rows**"*
* `docs/NEXT_SESSION_PROMPT.md` — *"then the ADRs (**0001–0040** — count the
  files rather than trusting that range)"*

ADR-0041 landed after the re-derivation those sentences record, and the pair
commit that followed did not touch them.

`docs/NEXT_SESSION_PROMPT.md` additionally claims *"**This** file's range has
tracked each ADR as it landed"* — a sentence its own range falsifies.

**And `docs/MEMORY.md` predicted exactly this**, two sentences below the stale
number: *"do not trust this sentence either the next time an ADR is added."* It
was right, and being right changed nothing, because a warning addressed to a
future reader is not a check. That is the argument for §4 over a resolution to
be more careful.

---

## 3. What this makes explicit: a closed anchor is not permanent

`docs/adr/0032-a-document-cannot-certify-itself.md` §3 is **Accepted** and says:

> * **Closed** — evaluated at a fixed commit (`at e2ec316, zero hits`). True
>   forever. Safe.

Nine citations falsify it. A closed anchor is durable only while the commit it
names stays reachable, and a replay, rebase, amend or force-push severs that
**without touching the citing document and without anything going red**.

The distinction that matters, and that ADR-0032 §3 does not draw:

* The **claim** stays true. "At d2fffc0 the ADR count was 40 and 40" is a true
  statement about that tree, forever.
* The **retrievability** does not. A reader cannot check it, and after `git gc`
  the token names nothing.

So §3's ordering — *no number > a number closed to a SHA > a number anchored to
a moving ref* — **survives, qualified.** A closed SHA is still better than a
moving ref. It is not permanent, and the gap between "true" and "checkable" is
where these nine citations live.

**Every copy of the claim**, found by grepping for the claim rather than the
phrasing (review standard 25):

| file | search for | disposition |
|---|---|---|
| `docs/adr/0032-a-document-cannot-certify-itself.md`, decision 3 | `True forever` | corrected |
| `docs/MEMORY.md`, review standard 24 | `Closed anchors` | corrected |
| `docs/adr/0032-…`, decision 3's closing sentence | `no number >` | qualified, not deleted |

**Do not grep for the phrase to find these — measured, and it fails.** The
ADR's copy wraps mid-phrase: `True` ends one line and `forever. Safe.` begins the
next.

| query (at `e698aca`, scoped to `docs`) | hits |
|---|---|
| `git grep "true forever"` | 1 — the `MEMORY.md` copy only |
| `git grep -i "true forever"` | **1 — case-insensitivity does not help** |
| `git grep "forever"` | 8, including both copies |

So a fix wave that greps the phrase corrects `MEMORY.md`, misses the Accepted
ADR, and ships a review-standard-25 failure **inside the correction to review
standard 24**. Grep one distinctive word — `forever`, or `Closed` — and read the
hits. This is the trap ADR-0028 §5 and the handoff's "grep one distinctive word,
never the phrase" both describe, live in the sentence being repaired.

`docs/NEXT_SESSION_PROMPT.md`'s standard-24 summary does **not** carry the
claim — checked with `git grep`, not assumed.

---

## 4. The property

> **Every 7-character hex token a tracked file writes in backticks resolves to a
> commit reachable from some ref.**

One bounded, checkable property rather than a list of citations to remember to
update (review standard 19). Enforced at both ends: a test at the reading end,
and ADR-0042 at the writing end saying a history rewrite carries its citations
with it.

### 4.1 Why "exactly 7", and what that rule is worth

Measured over the same tracked-file set:

| | 7 chars | 8 | 10 | 12 | 20 |
|---|---|---|---|---|---|
| tokens that ARE commits | **112** | 0 | 0 | 0 | 0 |
| tokens that are NOT commits | **0** | 1 | 3 | 1 | 1 |

Every genuine citation in this repository is seven characters; every false
positive is not. The rule catches 112 of 112 and admits none of the six, with no
exclusion list — which is what makes it a property rather than an enumerated
defence.

**Its one silent-drift path is closed in the same test.** `core.abbrev` is unset
(auto), and git widens the default abbreviation as the object count grows. On
the day it reaches 8, new citations stop matching and the rule narrows with
nothing going red. Guarantee 3 in §5 asserts `git rev-parse --short HEAD` is
still seven characters, so that day is loud.

A seven-character PAN-shaped token would still collide. No such token exists
today (the table above is the measurement); if one is ever written, the check
fails and names it, which is the correct outcome — the fix is to stop writing a
bare digit-string in backticks.

### 4.2 Why reachability, and not existence

`git cat-file -e 5a7fc58^{commit}` **succeeds today.** Both orphans are still in
the object store, merely unreferenced. A check built on existence would have been
green through this entire defect and would first go red on whatever day someone
runs `git gc` — long after the branch, the session and the context are gone.

```
5a7fc58: cat-file -e -> True;  reachable from a ref -> False
d2fffc0: cat-file -e -> True;  reachable from a ref -> False
99f0207: cat-file -e -> True;  reachable from a ref -> True
```

### 4.3 Why "any ref", and not "reachable from `main`"

`docs/adr/0041-…:12` was written **on the branch**, citing a commit that was on
the branch and not yet on `main`. That is the normal case: an ADR records the
tree it was derived from, and it is committed before the merge. CI fires
`on: [push]` for every branch (ADR-0037), so a `main`-anchored rule would fail
every branch that documents its own work.

"Reachable from any ref" passes there and still catches this defect, because the
replay orphaned these commits from **every** ref. The measurement that shows the
weaker bound loses nothing today: *reachable only from a branch, not from `main`
— **0**.*

---

## 5. The check, and its three guarantees

### 5.1 Mechanics

Two subprocesses, both timed at `e698aca`:

| step | command | measured |
|---|---|---|
| build the reachable set | `git rev-list --all` | **398** commits, **0.030s** |
| resolve every abbreviation | `git cat-file --batch-check`, all tokens on stdin | one call; prints `missing` for a non-object |

Membership is then a set lookup, so the cost does not scale with the number of
citations. `git rev-parse` resolves an unreachable object fine, so the failure
message can name the orphan by its full oid rather than only by the token.

It lives in `tests/test_sha_citations.py`, so it rides the existing pytest gate
and needs no amendment to ADR-0017's gate list. `tests/test_import_isolation.py`
and `tests/test_no_float_in_money_path.py` are the precedent for a tree-wide
guard living there.

**It would be the first test in the suite to invoke `git`.** Four test modules
already use `subprocess` (`test_cli_reports`, `test_import_isolation`,
`test_migrations`, `test_verify_script`) and **none of them shells out to
`git`** — measured with `git grep -n "\"git\"" -- tests/ scripts/`, which returns
nothing. `git` on `PATH` therefore becomes a new assumption of the suite. It
holds locally, in CI (`actions/checkout` needs it) and nowhere else that matters,
because the container does not run tests. It is offline and Node-free either way,
so the non-negotiable holds — but the assumption is new and is stated rather than
absorbed.

### 5.2 The guarantees, each revertible on its own (review standard 3)

1. **A dangling citation fails**, naming `file:line` and the token.
2. **A shallow repository fails**, naming `fetch-depth`. It never skips.
3. **`git rev-parse --short HEAD` is still 7 characters**, so §4.1's rule cannot
   narrow silently.

Each is proven red separately, and none of the three proofs is synthetic:

| guarantee | RED proof |
|---|---|
| 1 | **The tree holds nine real dangling citations right now.** The test is written first and must fail naming exactly those nine. It goes green when §6 lands — not when a mutation is reverted. |
| 2 | Clone this repository shallow into a temp directory and run the test there; it must fail naming `fetch-depth`, not error and not skip. **The clone URL must be `file://…`** — `git clone --depth 1 <plain path>` silently ignores `--depth` and hardlinks a full history, so a plain-path attempt produces a non-shallow clone and proves nothing. Verified 2026-08-13: `git clone --depth 1 file:///C:/Users/user/Downloads/Project` gives `is-shallow-repository → true`, one commit, and `git cat-file -e 99f0207^{commit}` fails. |
| 3 | Run the test with `-c core.abbrev=8`; the assertion must fire. |

**Guarantee 2 is the one that would otherwise rot.** `actions/checkout@v4`
defaults to `fetch-depth: 1`, so without §6.3 the check would resolve nothing in
CI. Making that a *failure* rather than a skip is deliberate: `ci.yml`'s own
header argues that a workflow which cannot execute "is worse than none, because
it reads as coverage", and ADR-0037 exists because the suite passed locally only
by accident of an installed package. A skip here would reproduce that shape
exactly.

---

## 6. What gets repaired

### 6.1 The nine citations — remapped, not deleted

Every one of the nine sentences is a derivation record: *"I probed the tree at
X, re-derive rather than trust me."* The anchor is the point of the sentence,
which is the one case ADR-0032 §3 grants that a number earns its maintenance
cost. Deleting it would leave a reader unable to tell a stale probe from a wrong
one. Both replacements are verified patch-identical (§2.2), so each sentence
stays exactly as true as it was.

### 6.2 The plan's body is edited, and the edit is logged

`docs/superpowers/plans/2026-08-12-review-outcome-focus.md` is a dated
historical record that "does not self-amend". Four of the nine citations are in
its body, and the property in §4 does not admit an exception for them.

The resolution: **the body is edited, and the remap is recorded in that plan's
own dated defect log.** A citation is a pointer, not a claim about the work
performed; remapping it to a patch-identical commit changes no claim the plan
makes. ADR-0042 records this as the narrow exception it is, so the next reader
does not take it as licence to rewrite a plan's substance.

The plan's ADR-table step is worth reading after the remap, because it becomes a
worked example of the check working: *"They were 40 and 40 at `e0481f4`"* is true
of that commit, and the two commands beside it answer higher today. **No current
number is written here**, because this milestone's own Task 3 adds an ADR and an
index row, so any figure would rot before the branch merged — which is ADR-0032
decision 3, and it caught this document twice.

### 6.3 CI

`fetch-depth: 0` on **both** checkouts in `.github/workflows/ci.yml` — the
`gates` job needs it for the test; the `image` job is included so the two do not
drift into meaning different things.

### 6.4 The ADR range

The three sentences are the ones quoted in §2.3, found with the grep given
there — **including its character class**, for the reason §2.3 measures. Per
ADR-0032 §3 the range is a number whose
anchor costs more than it is worth, and the *"do not trust this sentence either"*
warning sitting two lines below it in `docs/MEMORY.md` has already demonstrated
that in this exact spot. **The range and the row count are replaced by the two
commands that derive them:**

```
ls docs/adr/*.md | grep -v README | wc -l          # how many ADRs
grep -cE "^\| *\[?0[0-9]{3}" docs/adr/README.md    # how many index rows
```

They are compared **to each other**, not to a number written down, so there is
nothing left to age — which is ADR-0032 §4's "hand over the command, not the
answer" applied to the one sentence that most recently proved it needed it. The
NEXT_SESSION_PROMPT sentence claiming the file "has tracked each ADR as it
landed" is deleted rather than corrected — its subject is the document's own
trustworthiness (ADR-0032 §1).

---

## 7. What this does not decide

* **A6 — the 44 `path:NNN` citations.** Out of scope. Existence is mechanical;
  accuracy is not, and resolving each against the line it points at is a
  human-judgment job that deserves its own milestone. The count is anchored:
  **44** over `frontend/src`, `frontend/tests`, `docs/adr`, `docs/MEMORY.md`
  with an anchor requiring a directory separator, at `e698aca` — which
  reproduces §1.2's 2026-08-12 figure exactly.
* **§1.2's loose-anchor figure does not reproduce.** It records **72** for an
  anchor not requiring a separator; the same scope at `e698aca` with the regex
  `\b[\w.\-]+\.\w+:\d+\b` gives **100**. Two regexes, one tree, two answers.
  This is not resolved here, and it is evidence for §1.2's own thesis rather
  than against it: the loose number is a property of the regex, so it should be
  stated with the regex or not at all.
* **Whether the citation *sweep* becomes a repo script.** "Blocked on me" item 6
  stands at *no*, and nothing here reopens it. The property in §4 is a different
  thing: it checks whether a token **resolves**, never whether a sentence is
  **right**, and it needs no human to interpret its output.
* **The 6 non-commit hex tokens** in ADR-0018, ADR-0027 and the browser-pass
  spec stay as they are. §4.1's rule does not match them, so there is nothing to
  fix.
* **The tree-wide `path:NNN` population.** Measured at **139 across 37 files**
  (separator anchor, whole tracked tree) so the number is not re-derived later
  under the impression it is small. Not acted on.

---

## 8. Scope of the change

| file | change |
|---|---|
| `tests/test_sha_citations.py` | new — the property and its three guarantees |
| `docs/adr/0041-the-review-outcome-takes-focus.md` | 1 citation remapped |
| `docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md` | 4 citations remapped |
| `docs/superpowers/plans/2026-08-12-review-outcome-focus.md` | 4 citations remapped + defect-log entry |
| `.github/workflows/ci.yml` | `fetch-depth: 0` on both checkouts |
| `docs/adr/0042-a-cited-commit-must-stay-reachable.md` | new — the decision |
| `docs/adr/0032-a-document-cannot-certify-itself.md` | dated correction to §3 |
| `docs/adr/README.md` | one row for 0042 |
| `docs/MEMORY.md` | standard 24's copy; the ADR range |
| `docs/NEXT_SESSION_PROMPT.md` | the ADR range; the self-certifying sentence |

The last two are the handoff pair and go **last, in a commit touching nothing
else** (ADR-0033, review standard 25).

No behaviour changes. No `src/` file is touched, so pytest's count moves only by
the new test's cases and Vitest does not move at all.
