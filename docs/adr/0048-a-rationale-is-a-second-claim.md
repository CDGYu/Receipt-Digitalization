# ADR 0048 — A rationale is a second claim, and it is the one nobody checks

**Status:** Accepted (2026-08-21)
**Builds on:** ADR-0045 (a brief is a claim about the tree, and relaying one
makes it yours — this is the same discipline on a different axis: not what the
tree contains, but *why* a thing is the way it is), ADR-0030 (a finding is a
claim, and a fix wave verifies before it fixes), ADR-0032 (a document cannot
certify itself, and a derived claim can rot inside its own commit)
**Relates to:** ADR-0028 (a sentence quantifying over the codebase is derived at
the moment of writing), ADR-0042 (a citation is a claim too)

Derived 2026-08-21 across the whole of `feat/local-to-cloud-escalation`.
**Re-derive rather than quote** — every count here is a property of a moment.

---

## Context

That milestone's plan carried a large number of defects — every one the plan
author's, every one caught by an implementer or reviewer who ran the code
instead of trusting the prose. Sorting them by *what kind of thing was wrong*
produces a sharp asymmetry.

**Wrong facts were cheap.** A line number that had moved, a file that already
had an import block, a predicted failure naming the wrong symbol, a count of
six where the answer was eight: every one of these announced itself the moment
someone opened the file. The implementer noticed, reported, and continued. None
came close to shipping.

**Wrong reasons were expensive**, and they were expensive in a specific way:
they did not stop anyone. They *licensed* the wrong action.

### The four instances, in the order they happened

1. **A load-bearing import justified by docstrings.** The plan said an aliased
   import mattered because two `:data:` docstring references named it. A
   docstring reference binds nothing at runtime. The real reader was a test.
   Following the stated reason, an implementer would have deleted the import as
   cosmetic and broken that test.
2. **An import cycle that does not exist.** A function-level import carried the
   comment "local: avoids an import cycle". The module in question imports only
   stdlib and pydantic, and the package `__init__` is empty. **This was written
   into the task immediately after instance 1 was recorded** — by the same
   author, within the hour.
3. **A boundary justified by a false universal.** A module docstring said the
   egress boundary holds "because nothing else builds one". The builder is under
   `src/`. The conclusion was true; the reason was invented; and the true reason
   — a transitive closure two tests pin — was written nowhere.
4. **A real defect cited as evidence for a different shape.** A fix wave
   supported a claim that "one model at two tool settings is a real ladder" by
   citing the tools-granularity defect. That defect is *two models sharing one
   provider id*. The citation was to a real thing that does not say what it was
   quoted for.

**None of these is a lie, and that is the point.** Each was written by someone
who had read the code and formed an explanation. The explanation is the part
that was not checked — by its author, and then by everyone downstream, because
a reason reads as evidence that the author understood the thing.

---

## Decision 1 — A rationale is a claim, and gets a fact's treatment

Where a document, comment, docstring or commit message says a thing is so
**because** of something, the because is a second assertion. It is derived at
the moment of writing (ADR-0028), it can rot inside its own commit (ADR-0032),
and relaying it makes it yours (ADR-0045).

Reviewers and implementers **check the why, not only the what**. In this
milestone that discipline was applied deliberately from Task 3 onward and
**held far more often than it failed** — across Tasks 3 to 7, rationales checked
and confirmed true outnumbered rationales found false by a wide margin. The
instruction is to check, not to distrust.

## Decision 2 — Where a reason is load-bearing, name what would fail if it were false

"This import is needed because X" is unverifiable prose. "This import is needed;
deleting it reddens `tests/…::test_…`" is a claim with an executable
consequence, and the next reader can settle it in one command.

Prefer the second form wherever the reason is doing work. Where no such
consequence exists, that is itself the finding: the thing is unpinned.

## Decision 3 — Prefer stating what is true to stating why

A sentence that says only what is the case cannot have a false reason. Much of
the prose in this repository explains itself at length, and that is usually
right — it is what stops the next reader re-deriving a decision. But **an
explanation is not free**, and where the *what* stands alone, the *why* is
optional weight that can rot independently.

## Decision 4 — A false reason is deleted, not reworded

ADR-0032's rule applies unchanged. Every one of the four instances above was
closed by deleting the reason, and in three of the four the surrounding sentence
was already correct without it. Rewriting an invented reason produces a second
invented reason at a rate this repository has measured before: on one branch,
five of nine false claims were written *by* the rounds fixing the other four.

## Decision 5 — This is review standard 28

`docs/MEMORY.md` § "Review standards" carries it in the form a reviewer needs.
This ADR is the derivation.

---

## What this ADR does not claim

- **Not that rationales are usually wrong.** They are usually right. Four were
  false in a milestone that checked dozens.
- **Not that comments should be shorter.** This repository's dense commentary is
  load-bearing and has repeatedly stopped a decision being re-litigated. The
  claim is narrower: the *causal* half is a claim, and gets checked.
- **Not a process gate.** Nothing here is enforceable by a test, and inventing
  one would be the enumerated defence review standard 19 names. It is a habit,
  held by whoever reads.

---

## Consequences

**The staged close is the mechanism that catches this**, and the escalation
milestone is the evidence. Each stage found real defects in the stage before it:

- seven task reviews found defects in the plan;
- the whole-branch review found **three stated guarantees deletable with every
  gate green**, which seven task reviews had not;
- the fix wave closing those wrote **four false claims of its own**, one into a
  test file;
- the scoped re-review of that wave caught all four;
- and the controller, checking the re-review, found a false claim **of its own**
  — a service identified from its port listener when `docker ps` was one command
  away, contradicting a standing record in `docs/MEMORY.md` that had been right
  all along.

**No stage was redundant, and the last one is the uncomfortable one.** The
controller's error was made while *correcting other people's errors*, and it was
reported to the user as a correction of their environment. Authority over a
review does not confer accuracy.

**What it costs.** This is a large amount of machinery for one milestone, and it
is only worth it where a wrong answer is expensive and quiet. The escalation
qualifies on both counts: its fallback trigger was wrong twice in the
never-fires direction, and both times every gate stayed green.
