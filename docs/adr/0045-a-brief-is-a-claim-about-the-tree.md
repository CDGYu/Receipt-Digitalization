# ADR 0045 — A brief is a claim about the tree, and relaying one makes it yours

**Status:** Accepted (2026-08-19)
**Builds on:** ADR-0023 (parallel agents share one worktree — the dispatch
discipline here is its sibling), ADR-0030 (a finding is a claim — this extends
it from findings to *briefs* and to *relayed* findings), ADR-0044 (the
model-facing surface, written the same day and itself carrying two of the
defects this ADR describes)
**Relates to:** ADR-0028 (prose claims need re-derivation), ADR-0032 (a
correction that over-reaches), ADR-0033 (the handoff pair goes last and alone),
ADR-0042 (fix-wave prose is the defect surface)

Derived 2026-08-18/19 on `feat/buyer-and-blank-rows`. **Re-derive rather than
quote** — every count here is a property of the tree at a moment.

---

## Context

The milestone ran nine tasks through subagent-driven development: a fresh
implementer per task, a task review, fix rounds, a scoped re-review, then a
whole-branch review. It worked — no Critical finding at any stage, and 9 of 9
deletion probes on the headline deliverables were caught.

The defects were somewhere else. **Six were in the plan**, written before any
implementer saw it. **Six more were in claims the controller relayed** between
agents without re-deriving them. Not one was in the shipped code at the point it
was found.

ADR-0030 established that a *finding* is a claim requiring verification. This
extends that in the two directions the milestone actually bled from.

---

## Decision

### 1. Pre-flight every task brief against the tree before dispatching it.

Read the brief, then check each artefact it names — files, symbols, signatures,
test paths, component props — actually exists at the stated shape. Correct what
does not, **at source in the plan**, then re-extract the brief.

Five defects were caught this way before any implementer saw them:

- a test snippet calling `field_accuracy(truth, pred)` and reading
  `breakdown.transcription.total`, wrong four ways at once — wrong function,
  wrong argument order, wrong input type, and a nested attribute that does not
  exist;
- steps naming `tests/test_export_xlsx.py` three times when the file is
  `tests/test_xlsx.py`, which the same task's Files block had right;
- a Files block naming one frontend file where three are load-bearing — the
  task's own test asserted a patch body that could not be produced under it;
- a test rendering a component with props it does not take, clicking a button it
  does not have, and reading a patch body it never builds;
- an "all eight `TEXT_FIELDS`" cardinal in a file the task was about to make
  nine-and-ten.

**Every one would have run green or wasted a round.** A brief that names a
nonexistent file fails loudly; a brief that names the wrong *shape* is the
expensive kind, because an implementer will make the code match it.

### 2. A plan defect is corrected at source, and the wrong instruction is not quoted in the correction.

Fixing it only in the dispatch leaves the defect for the next reader. Fixing it
in the plan *and quoting what it used to say* is worse than either: a plan is
skimmed, and a restated bad instruction is one somebody will follow. Say what is
true; put the history in the commit message.

The sixth plan defect is the one that proves the rule. Task 7 step 2 said to give
blank pre-printed rows a `position` "continuing the existing sequence", while
`prompts.py` rule 5 and `RECEIPT_SYSTEM_SPEC.md` both require **printed order**
and `field_accuracy` joins `line_items[i]` by **array index**. Measured against a
model following the shipped prompt perfectly: append order scores **20/28 with 4
phantom hallucinations**, paper order **28/28 with 0**. The label contradicted
its own notes inside one file.

That one shipped green through an implementer and a task review, and was caught
only because the implementer flagged an instruction it could not reconcile with
the code rather than transcribing it. **The instruction to refuse-and-flag rather
than transcribe is therefore load-bearing, not politeness.**

### 3. Relaying a finding makes it yours. Re-derive before ordering work on it.

A controller sits between reviewers and implementers, and a claim that passes
through gains authority it did not earn. Six relayed claims were false this
milestone:

- **"nineteen snake_case headers"** — a number matching no set in the file. The
  implementer searched and found none yields 19: it was invented, not
  mis-anchored. It reached a tracked commit message, which stays wrong.
- **"the maps paid for themselves on the rename"** — inverted. The rename cost 6
  name-carrying lines; under the previous literal design it would have cost 3.
  The refactor's real justification is *insertion* safety, which is separately
  proven.
- **"a mis-flagged filled row trips `[warn] R024`"** — true only while another
  purchase survives. When the mis-flagged row is the receipt's **only** purchase
  — the shape all three golden receipts have — `_purchased` empties,
  `sum_line_nets` returns `None`, and both rules skip: **zero findings at any
  severity.** This was the mitigation used to keep a finding out of Critical.
- **"equally silent at the merge base, so not a regression"** — false. At the
  merge base the flag does not exist and the exporter writes every row, so no row
  *could* vanish. The class is branch-introduced.
- **"the fix would make the two shape checks redundant"** — false. A *missing*
  key throws and is caught; a key at the *wrong type* throws nothing and is
  silently compared.
- **a clause count relayed as a correction** — see decision 4.

The corrective is not more caution in the reviewer. It is that **the controller
re-derives any claim it is about to make an implementer act on**, and that
implementers are told plainly to measure rather than transcribe. Every one of the
six above was caught by an implementer doing exactly that.

### 4. A count is meaningless without the thing it counts, and "your number was wrong" is itself a claim.

A review reported the tool schema splits into **14** clauses. The controller
relayed 14. The implementer measured **141**, wrote down what it measured, and
the controller recorded that as a correction and praised the discipline.

Re-derived: the tool schema splits into 14 clauses; the full bundle containing it
splits into 141. **Both were right about different objects.** There was no error
to correct, and the subagent credited with correcting one had done nothing wrong.

State the set with the number. And before writing that someone's figure was
wrong, re-derive it — a false correction costs the same as a false claim and is
harder to notice, because it arrives wearing the clothes of diligence.

### 5. Ask for a bounded property; never an enumerated list of permitted edits.

Held throughout, and it paid twice:

- The label pins close **wholesale** rot and schema drift by set difference, not
  by naming fields. Verified by adding a brand-new field to the schema: the pins
  failed on all four label files naming it, with **zero edits to the test**.
- *Correctable implies readable* — every key in a correction map must appear in
  the serializer's output — replaced a per-field allow-list, and fails on the
  next unpaired addition rather than on the next reviewer to notice.

Where no honest property exists, **record the gap instead of shipping a test that
passes for the wrong reason.** `PROMPT_VERSION` is the worked example: the only
available shape is a checked-in `{version: hash}` table whose red state has two
remedies of identical cost — bump the version, or paste the new hash under the
old one — so **its easiest green is the defect.** ISSUE-007 records that, with the
real fix.

---

## Consequences

**The instruments are cheaper than the process they protect.** A brief pre-flight
is minutes and caught five defects. A controller-run mutation is one command and
settled three disputes a review round would have cost hours. Twice, a
deletion-only fix round was verified by comparing ASTs with docstrings stripped —
identical, 75328 characters each side — which is stronger evidence than a fresh
reviewer would have produced and cost one command.

**Refusal to transcribe is the highest-yield behaviour observed.** Every defect in
decisions 2 and 3 was caught by an implementer declining to write down something
it could not reconcile, and none by a gate. It follows that a dispatch should
instruct measurement over transcription explicitly, and that a report saying "this
did not reproduce as stated" is a success, not a delay.

**A failed reproduction is evidence about the reproduction first.** One
implementer's mutation failed to reproduce a finding and it nearly wrote that up
as a refutation before discovering its own construction was wrong — it had kept
the keyword on the true side, satisfying the check it meant to break. Another's
first array-order mutation re-assigned the positions afterwards, restoring the
invariant it meant to violate, and the pin correctly stayed green. Both were
caught by reading the result rather than trusting the intent.

**What this does not fix.** The controller is still the single point through which
every claim passes, and re-deriving everything is not affordable. The rule is
therefore scoped: re-derive what you are about to make someone act on. Claims
that only inform a summary can be relayed with attribution — and should be
attributed, so the next reader knows whose measurement it was.
