# ADR 0051 — A guard must not share its derivation with its subject

**Status:** Accepted
**Date:** 2026-08-23
**Closes:** nothing. It records why three fixes in one day each shipped a guard
that was proven red and still guarded nothing.
**Rests on:** ADR-0030 (a finding is a claim), ADR-0032 (a document cannot
certify itself), ADR-0045 (a brief is a claim about the tree),
ADR-0048 (a rationale is a second claim).
**Extends:** review standards 14 and 15, which this does not replace.

---

## Context

On 2026-08-22/23 three defects were fixed in sequence, each surfaced by fixing
the one before it: ISSUE-020 (the golden corpus validated against a frozen
`today`), ISSUE-021 (one unloadable label silently emptied the whole corpus),
ISSUE-022 (the resulting loud failure named every part of the error except the
file).

Each fix shipped with a new test. **Each of those tests was proven red by a
mutation before it was committed.** All three were then found, by review, to
be incapable of catching the defect they were named for.

That is not review standard 14's failure — these pins *were* proven red. Nor
standard 15's — the reds landed on the right assertions, with the right
messages. Something one level further out was wrong, three times, in three
different shapes, and nothing in the repository named it.

---

## Decision — a guard derives its expectation independently of its subject, or it is decoration

Concretely, before committing a guard, two questions must both be answered:

1. **Where does my expected value come from?** If it comes from the same
   function, fixture, or object the subject uses, a defect in that shared thing
   moves both sides at once and the guard cannot see it.
2. **Is my subject forced through the path I am guarding?** If the subject can
   reach its result another way, the guard is checking a path nobody takes.

**A mutation that proves the guard red must be applied where the *subject*
computes its answer, not where the guard computes its expectation.** That is the
operational form of this decision, and it is what all three failures below would
have caught.

---

## The three shapes, all measured

### 1. Shared helper the subject can bypass (ISSUE-020)

`tests/test_rules.py` got a `_corpus_context()` helper, used by both the corpus
check and a guard test standing beside it. Its docstring said the two "cannot
drift".

Measured: re-freezing the context **at the corpus check's own call site**,
bypassing the helper entirely, reinstated ISSUE-020 verbatim and left the whole
module and the lint gate green. A guard that builds its own context cannot see
the check re-freezing its own.

**Closed by deleting the helper** and moving the guard *inside* the corpus
check's parametrisation, so there is exactly one construction site. The check is
now `test_the_real_corpus_validates_as_production_does`, and it asserts the exact
ERROR rule ids per case, which lets one parametrised test carry both ends of the
bound: a receipt dated today must be clean, one dated past the slack must still
raise `R031`.

### 2. Shared derivation on both sides (ISSUE-021)

`test_every_label_file_on_disk_reached_the_corpus` compared "what is on disk"
against "what got scored" — but took the on-disk side from `_label_files`, the
same function the loader globs with.

Measured: excluding `r003.json` inside `_is_label_file` left a real label on
disk, never scored, with the guard **and the entire suite** green. Both sides had
moved together.

**Closed by reading the directory directly**, case-insensitively. That also
catches a label saved as `.JSON`: scored on a case-insensitive filesystem and
invisible to the loader's glob on CI's Linux — a data-side instance of the same
shape needing no code change at all.

### 3. A fixture in which right and wrong coincide (ISSUE-022)

`test_a_label_that_will_not_load_names_itself` wrote a valid `r001` and a broken
`r002`. The broken label therefore sorted **last**.

Measured: naming **every** label file passed, and so did naming the **last** one.
"Names the file that failed" was indistinguishable from both — and naming every
file is precisely the failure the issue exists to prevent at the 50–100 receipts
`eval/golden/README.md` targets.

**Closed by bracketing** the broken label with healthy ones and asserting their
**absence** from the render, not only the broken one's presence.

---

## What this ADR does not decide

- **Whether every existing guard in the tree is re-audited against it.** That is
  a sweep nobody has scoped, and standard 19 warns that enumerating instances is
  not the same as closing a class.
- **Whether "proven red" should stop being sufficient in a brief.** Review
  standards 14 and 15 stand as written; this adds a question, it does not remove
  theirs.
- **Anything about the golden set itself.** ADR-0050 owns that; this is about
  how its guarantees are checked.

---

## Consequences

- **A brief that asks for a pin should say where the mutation goes.** "Prove it
  red" is satisfiable at the guard's own construction site, which proves the
  guard can fail, not that it can catch anything.
- **Deleting a shared helper can be the fix.** In shape 1 the helper *was* the
  defect: it created a second construction site that looked like a single source
  of truth. One call site beat one helper.
- **Reviews found all three; no gate found any.** Five gates were green on every
  one of them, including a case where a real label sat unscored on disk. This is
  the argument for keeping an independent review stage on even a two-commit
  branch.
- **The reason a design was chosen needs its own pin.** ISSUE-022's "every caller
  sees the same exception type" was stated in a docstring, a code comment and an
  issue, and enforced nowhere — a wrapping `raise ... from exc` left the whole
  suite green. It is now pinned by
  `test_naming_the_label_does_not_change_what_escapes`, which derives its
  reference type from the parser on the same bytes rather than naming pydantic,
  so it cannot rot when the schema library changes. **That derivation is this
  decision applied to itself.**
