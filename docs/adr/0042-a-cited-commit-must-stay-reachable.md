# ADR 0042 — A cited commit must stay reachable, and a rewrite carries its citations

**Status:** Accepted (2026-08-13)
**Builds on:** ADR-0028 (claims about the tree are re-derived, not restated —
§5, citations carry no line numbers, and §7, a citation is a claim too),
ADR-0032 (anchors are where rot lives), whose decision 3 this milestone
**corrects** rather than extends — see its `## Correction (2026-08-13)`
**Relates to:** ADR-0017 (what "passing" means, and the gate list this guard
rides without amending), ADR-0033 (a correction goes to every copy), ADR-0037
(CI runs the gate runner, and it fires on every push), review standards 19, 23
and 25

Derived 2026-08-13 on `feat/dangling-citations`. **Re-derive rather than quote**
(ADR-0028 rule 1) — several counts below are *supposed* to move, and one of them
moving is the point of the milestone.

**Anchor for the citation counts: `e698aca`**, `main`'s tip when this branch
opened. Where a count has a different anchor it names it. The scope is the
tracked non-binary files at that commit — `git ls-tree -r --name-only e698aca`,
minus the binary and generated suffixes `tests/test_sha_citations.py` lists in
`_SKIP_SUFFIXES`. Every token is resolved with `git cat-file --batch-check` and
tested for membership in `git rev-list --all`. The unit of every token count is
the **distinct token**, not the citation site; where a site count is meant it
says so.

That module's docstring states the same measurements from the enforcement end.
Where it and this file disagree, re-run both rather than believing either.

## Context

On 2026-08-12 the review-outcome-focus branch was **replayed onto `main` rather
than merged**. Every commit on it took a new oid, and every sentence that had
already cited an old one kept naming the old one.

Query — every backticked seven-character hex token over the scope above:

| result | count |
|---|---|
| distinct backticked seven-hex tokens | **112** |
| resolve to a commit object | **112** |
| reachable from `main` | **110** |
| reachable only from a branch, not from `main` | **0** |
| **reachable from no ref at all** | **2** |

Those two account for **nine citation sites in three tracked files**: five of
one token (`docs/adr/0041-the-review-outcome-takes-focus.md` ×1,
`docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md` ×4) and four of
the other (`docs/superpowers/plans/2026-08-12-review-outcome-focus.md` ×4).

**The two dead tokens are 5a7fc58 and d2fffc0, and they are written bare
throughout this file.** That is decision 5 below rather than a typographical
accident. Regenerate the site list with `git grep -n "5a7fc58"` and
`git grep -n "d2fffc0"` — the counts above are anchored and this branch changes
them; the commands answer for whatever tree the reader has.

**The claims those nine sentences make stayed true. Their retrievability did
not.** *"At <token> the ADR count was 40 and 40"* is a true statement about that
tree forever. A reader cannot check it, and once `git gc` prunes the object the
token names nothing at all. That gap — between **true** and **checkable** — is
the one ADR-0032 decision 3 does not draw, and it is drawn in that ADR's
`## Correction (2026-08-13)`.

**The warning existed and did not help.** `docs/NEXT_SESSION_PROMPT.md` recorded
the replay at the time, in the section describing it: *"No pre-merge SHA is
quoted anywhere in this section, because the replay gave every one of them a new
value."* It was applied to that section's own prose and to nothing else. The
documents the milestone had already written were not swept, and nothing went
red. A warning addressed to a future reader is not a check — which is the whole
argument for a property over a resolution to be more careful.

Each orphan has a patch-identical replacement already on `main`. Verified by
comparing patches, not subjects:

```
diff <(git show 5a7fc58 --format=) <(git show 99f0207 --format=)   # empty
diff <(git show d2fffc0 --format=) <(git show e0481f4 --format=)   # empty
git merge-base --is-ancestor 99f0207 main                          # true
git merge-base --is-ancestor e0481f4 main                          # true
```

## Decision

### 1. Every backticked seven-character hex token in a tracked file resolves to a commit reachable from some ref

One bounded property, enforced by `tests/test_sha_citations.py`, which rides the
existing pytest gate and needs no amendment to ADR-0017's gate list.
`tests/test_import_isolation.py` and `tests/test_no_float_in_money_path.py` are
the precedent for a tree-wide guard living there.

It is a property and not a list of citations somebody has to remember to update,
which is review standard 19's requirement. Three guarantees, each revertible on
its own (review standard 3):

1. **A dangling citation fails**, naming the token and every `path:line` citing
   it.
2. **A shallow repository fails**, naming `fetch-depth`. It never skips.
3. **`git rev-parse --short HEAD` is still seven characters**, so decision 4's
   rule cannot narrow silently.

Guarantee 2 is enforcement, not decoration: `actions/checkout@v4` defaults to
`fetch-depth: 1`, under which every citation resolves as missing. Both checkout
steps in `.github/workflows/ci.yml` now set `fetch-depth: 0`. Making the shallow
case a **failure** rather than a skip is deliberate — a skip reads as coverage,
which is the shape ADR-0037 exists because of.

### 2. Reachability, not existence

`git cat-file -e` succeeds on both orphans **today**. They are unreferenced, not
yet pruned:

```
git cat-file -e 5a7fc58^{commit}    # exit 0
git cat-file -e d2fffc0^{commit}    # exit 0
```

An existence check would therefore have been **green through this entire
defect**, and would first go red on whatever day somebody ran `git gc` — long
after the branch, the session and the context that could explain it are gone. A
check whose first failure is scheduled for an arbitrary future date is worse
than the defect it is supposed to catch, because by then nobody can tell what
the token was meant to name.

Reachability is the property a reader actually depends on: a commit no ref can
reach is a commit a reader cannot look up, whether or not the object is still
sitting in the store.

### 3. Any ref, not `main`

An ADR records the tree it was derived from and is committed **before** its
merge, so it legitimately cites a commit that is on the branch and not yet on
`main`. **This ADR is an instance of exactly that**: it cites `42e8483`, which is
on this branch and not on `main` — `git merge-base --is-ancestor 42e8483 main`
exits non-zero — and ADR-0041's own derivation line records the branch commit it
was probed at. CI fires on every push (ADR-0037), so a `main`-anchored rule would
fail every branch that documents its own work, starting with this one.

The weaker bound costs nothing measurable today. At `e698aca`, tokens resolving
to a commit **reachable only from a branch and not from `main`: 0.** And it
still catches this defect, because a replay orphans its commits from **every**
ref, not merely from `main`.

**The limit is `git rev-list --all`, which answers over the refs the running
clone has.** A citation to a commit that exists only on an unpushed local branch
passes locally and fails in CI, where the clone has only what was pushed. That
is arguably the correct outcome — a citation nobody else can resolve is a bad
citation — but it is recorded here so it is read rather than discovered, because
the failure appears on a machine other than the author's.

### 4. Exactly seven characters, and the width is pinned

Two measurements over the same scope, each stated with the query that produced
it (review standard 23), because a count without its anchor would mean very
little here.

**Nothing this pattern matches is a false positive** — the direction the rule
rests on. Query: `_SHA_PATTERN` itself, a backticked `[0-9a-f]{7}`.

|  | 7 chars | 8 | 10 | 12 | 20 |
|---|---|---|---|---|---|
| distinct backticked hex tokens that **are** commits | **112** | 0 | 0 | 0 | 0 |
| distinct backticked hex tokens that are **not** | **0** | 1 | 3 | 1 | 1 |

The rule catches 112 of 112 and admits none of the six, **with no exclusion
list**. That is what makes it a property rather than an enumerated defence
(review standard 19): there is nothing to keep up to date, and no file is
exempt — including this one.

**Nothing genuine is written at another length** — a separate and weaker claim,
true of this tree on that day rather than by construction. Backticked
`[0-9a-f]{4,6}`: 18 distinct tokens, none a commit. Backticked
`[0-9a-f]{8,40}`: 6 distinct tokens, none a commit. Widen the query to
backticked hex of *any* length and 49 of 161 distinct tokens are not commits, 43
of those 49 being one to five characters — ADR numbers, HTTP status codes, round
figures.

**The one silent-drift path is closed in the same module.** `core.abbrev` is
unset, so git chooses the abbreviation width from the object count and widens it
as the repository grows (`git config --get core.abbrev` returns nothing). On the
day it reaches eight, newly written citations stop matching the pattern and the
guard silently checks less. `test_git_still_abbreviates_to_seven_characters`
makes that day loud instead.

A seven-character token that is *not* a commit would collide — a PAN-shaped
digit-string, say. None exists today; the table above is the measurement. If one
is ever written the check fails and names it, which is the right outcome: the
fix is to stop writing a bare digit-string in backticks, not to exempt the file.

### 5. A document about a dead commit names it bare, or at full oid length

**The backticked seven-character form *is* the citation.** It is a promise that
the reader can look the commit up. A dead commit cannot be looked up — that is
the entire defect — so writing one in that form makes the claim the document is
denying.

Measured against `_SHA_PATTERN`, which of the available forms are citations:

| form | a citation? |
|---|---|
| the short token in single backticks | **yes** |
| the same token bare | no |
| its full 40-character oid, in backticks | no |
| the token inside double quotes in a command | no |

So a document about an unreachable commit writes it **bare** or at full oid
length, and a command that greps for it quotes it. That is why this file's
Context names both orphans bare, why the repaired design document does, and why
the 2026-08-12 plan's defect-log entry does.

**One constraint falls out and cannot be designed away: a sentence cannot show
an example of the citation form without instantiating it.** There is no way to
write "a citation looks like this" that the guard does not read as a citation.
**The only safe illustration is a commit that really resolves** — `e698aca`
above is one, deliberately. Every backticked seven-hex token in this file is a
live commit for that reason.

### 6. A rewrite carries its citations — into a historical plan's body if that is where they are

Four of the nine sites are in the body of
`docs/superpowers/plans/2026-08-12-review-outcome-focus.md`, a dated historical
record that does not self-amend. The property admits no exception for it, so the
body was edited and **the edit is recorded in that plan's own dated defect
log**.

The narrow ground: **a citation is a pointer, not a claim about the work
performed.** Repointing it at a patch-identical commit changes no claim the plan
makes — verified patch-identical rather than assumed, by the `diff` above. That
plan's ADR-table counts, which were correct at the commit they were anchored to
and read higher today, are deliberately left alone; they are the check working,
not rot.

This is licence to repair a pointer and nothing else. It is not licence to
rewrite a historical document's substance.

### 7. The nine were remapped, not deleted

Every one of the nine sentences is a derivation record — *"I probed the tree at
X; re-derive rather than trust me."* The anchor is the point of the sentence,
which is the one case ADR-0032 decision 3 grants that a number earns its
maintenance cost. Deleting the anchor would leave the next reader unable to tell
a stale probe from a wrong one.

## Consequences

- **What a green pytest run now certifies**: that every token this repository
  writes in the citation form names a commit some ref can reach. **It certifies
  nothing about whether the sentence around the token is true.** The check reads
  resolvability, never accuracy, and no gate reads prose (ADR-0028's own *does
  not decide*, unchanged).
- **The guard's scan set is `git ls-files`, so a new file is invisible until it
  is tracked or staged.** A brand-new document carrying a dead citation passes
  locally while it is untracked, and fails the moment it is added. Stage before
  you believe the run. This ADR was staged before its own verification for
  exactly that reason.
- **The suite now shells out to `git`, which it never did before.** Four test
  modules already use `subprocess` and none of them invoked `git` —
  `git grep -n "\"git\"" e698aca -- tests/ scripts/` returns nothing, and the
  anchor is load-bearing because the same query answers differently today.
  `git` on `PATH` is a new assumption of the suite. It holds locally
  and in CI, where `actions/checkout` needs it anyway, and the container does
  not run tests. It is offline and Node-free either way, so the non-negotiable
  holds — but the assumption is new and is stated rather than absorbed.
- **A git failure is reported as a git failure, not as a citation defect.** A
  non-zero exit from `ls-files`, `rev-list` or `cat-file` raises with git's own
  stderr attached. Left to return empty output, a failing `ls-files` would report
  *"no citations found at all"* and blame the pattern, and a failing `rev-list`
  would report every citation in the tree as unreachable — the wrong-reason
  failure the guard exists to avoid. "Detected dubious ownership" (exit 128,
  empty stdout) is a routine way to reach both.
- **Writing about a dead commit is now slightly awkward, permanently.** Decision
  5's form is not optional and there is no exemption mechanism, so anyone
  documenting an orphan pays the cost of the bare token and of remembering why.
  This ADR is the record of why.
- **The three ten-character tokens are Fira Code tabular-figure width samples,
  and calling them anything else is a known trap.** ADR-0027 and the browser-pass
  spec record that `0000000000`, `1111111111` and `9999999999` each measure
  exactly 96px at 16px, which is what makes a transposed digit break the column.
  This milestone's own documents called them PAN digit-strings instead, in more
  than one place; the design's §2.1 and the implementation plan's defect log both
  carry the correction — read those rather than a count from here. The rule does
  not match them at any width, so nothing needed doing about them either way.
- **What it cost, and where it was found.** The guard was prototyped against the
  real tree before the plan was written, and **the design document that specifies
  the rule failed it on the first run, at five citation sites** — the two orphans
  it is about, written in the form it was about to forbid. Measured at `06382ae`,
  the design's own commit, before `42e8483` repaired it:

  ```
  git show 06382ae:docs/superpowers/specs/2026-08-13-dangling-citations-design.md \
    | grep -coE '`(5a7fc58|d2fffc0)`'
  ```

  Two of one token and three of the other. The resolution was decision 5 — a
  property — rather than an exemption for the specifying document, which is the
  same choice review standard 19 forces everywhere else.

## What this ADR does not decide

**The `path:NNN` citations.** Out of scope, and deliberately: existence is
mechanical, accuracy is not, and resolving each against the line it points at is
a human-judgment job that deserves its own milestone. The population is
anchor-dependent and any figure must be stated with its regex, which is why none
is quoted here — see `docs/NEXT_SESSION_PROMPT.md` residual **A6**, where the
anchors and their numbers live.

**Whether the citation *sweep* becomes a repo script.** That question stands at
**no** and nothing here reopens it. This guard is a different thing: it asks
whether a token **resolves**, never whether a sentence is **right**, and it needs
no human to interpret its output. A sweep does.

**The six non-commit hex tokens** in ADR-0018, ADR-0027 and the browser-pass
spec. Decision 4's rule does not match them, so there is nothing to fix and they
stay exactly as they are. Narrowing the rule is what made them a non-question;
listing them as exceptions would have been the enumerated defence.

**Whether any of this can be extended to prose.** It cannot, by ADR-0028's and
ADR-0032's shared argument: no test can read a sentence for truth. This guard
closes the one sub-part that is mechanical — *can the reader look it up* — and
leaves the rest with the reader, which is where it can actually be discharged.

**What to do about a citation to a commit on an unpushed local branch.** Today
it passes locally and fails in CI (decision 3). Nobody has decided whether that
should be made loud locally too, and the guard as written cannot tell that case
apart from any other unreachable token.

## References

`tests/test_sha_citations.py` — the guard, its three guarantees, and the same
measurements stated from the enforcement end;
`docs/superpowers/specs/2026-08-13-dangling-citations-design.md` — the design,
its §2 measurements, and the document that failed its own rule;
`docs/adr/0032-a-document-cannot-certify-itself.md` decision 3 and its
`## Correction (2026-08-13)`; `docs/adr/0028-claims-about-the-tree-are-re-derived.md`
§5 and §7; `docs/adr/0037-ci-runs-the-gate-runner.md` (why CI fires on every
branch, and the false green that motivated it);
`docs/adr/0017-two-suites-and-the-gate-runner.md` (the gate this rides);
`.github/workflows/ci.yml` (`fetch-depth: 0`, on both checkouts);
`docs/superpowers/plans/2026-08-12-review-outcome-focus.md` — its 2026-08-13
defect-log entry, which is decision 6 applied;
`docs/MEMORY.md` § "Review standards" (19, 23, 25).
