# Growing the golden set — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the golden set grow with real receipts **without publishing any
more real businesses' names, addresses or tax IDs** — and record, in the
artifact, which receipts a number actually covers.

**Architecture:** A label is fully public or fully private, never partially
redacted (spec §3 measures why). Private labels take a reserved filename prefix
and are gitignored; **no module changes** to reach them, because every reader
already globs the one directory. The aggregate gains the list of receipt ids it
scored, derived by union rather than by restating the naming rule.

**Tech Stack:** Python 3.13 (3.11 also gated in CI), stdlib only, pytest.

**Spec:** `docs/superpowers/specs/2026-08-22-growing-the-golden-set-design.md` —
**read §3 and §7a before Task 1.** §3 is the measurement that rules out the
obvious design; §7a is the correction recording that most of step 7 already
exists.

---

## Global Constraints

- **Do not touch `eval/metrics.py`'s `field_breakdown`, `field_accuracy` or
  `is_filled`.** They are ADR-0040's published metric surface; narrowing one
  moves a published metric. Spec §3 is the measurement that makes avoiding them
  the whole point of this design.
- **Do not modify the existing labels `r001`–`r003`, `eval/golden/TEMPLATE.json`,
  or `eval/golden/manifest.json`'s existing entries.** Their values are fixtures
  in up to 16 other tracked files (spec §2).
- **Do not change any `glob` over the labels directory.** Four readers exist —
  `eval/golden_set.py`, `eval/harness.py`, `src/receipts/cli.py`,
  `tests/test_eval_floor.py` — and the design's load-bearing property is that
  none of them needs changing.
- **Every existing test passes unmodified.** Anything that appears to need one
  changed is a **stop-and-report** with the measurement attached.
- **No network, no provider, no real receipt image in any test.**
- **Run the suite as bare `python -m pytest`** — `pyproject.toml` sets
  `addopts = "-q"`, so passing `-q` yourself nets to `-qq`.
- **`python -m ruff check .` is one of five blocking gates and is green.** `E`,
  `F`, `I`, `B`, `UP`; line limit 100.
- **Stage by explicit path. Never `git add -A`.** Verify with
  `git diff --cached --stat` before committing.
- **Never commit a file matching the private label pattern.** That is the point
  of the milestone; a violation is a stop-and-report, not a judgement call.
- **A RED step's stated reason is a prediction, not a fact.** Read the actual
  failure; a mismatch is a finding.

---

## The spec's §9 questions, resolved

**Q1 — the private prefix is `p`.** Checked against the tree rather than chosen:
`_is_label_file('p001.json')` returns `True` (`eval/golden_set.py:66-73` excludes
only `TEMPLATE.json` and `manifest*`), so every reader accepts it. Nothing
hardcodes a label stem except `scripts/try_one_receipt.py`'s `r002` default and
test fixtures naming `r001`/`r002`, none of which a `p` file collides with.

**Q2 — the aggregate records the scored receipt ids, not a split count.** A count
would be a second statement of the naming rule, and this milestone has already
shipped one derived count that drifted. A **sorted union of the ids actually
scored** restates nothing, is derived the way `spread_omitted` is, and answers
the reader's real question — *which receipts is this number over?* — rather than
just how many were hidden.

**Q3 — answered by the repo, and should never have been asked.**
`eval/golden/README.md` documents the four-step labelling procedure against
`TEMPLATE.json`, the `images/{id}.<ext>` ↔ `labels/{id}.json` stem pairing, the
money-as-string rule, `null` over a guess, and spec §15's composition targets.
`validate_labels` and `composition_stats` exist and work (`validate_labels`
returns `[]` today). **Task 1 extends that README; it does not write a new one.**

**A consequence worth knowing, not a change to make.**
`tests/test_eval_floor.py` parametrises over `GOLDEN_LABELS.glob("*.json")` and
asserts, per label, that an empty extraction scores below `MAX_FLOOR = 0.10` and
hallucinates nothing. **A private label is therefore validated by the suite the
moment it lands** — for free, with no new machinery. It also means the local
suite runs more parametrised cases than CI. Both are correct; neither needs
code.

---

## File structure

| file | responsibility |
|---|---|
| `.gitignore` (**modify**) | exclude the private label pattern |
| `eval/golden/README.md` (**modify**) | document the public/private choice at the point a labeller decides it |
| `eval/run_repeats.py` (**modify**) | add `scored_receipts` to the aggregate |
| `tests/test_golden_privacy.py` (**create**) | pin the ignore rule and that every reader accepts a `p` label |
| `tests/test_run_repeats.py` (**modify**) | pin `scored_receipts` |

---

## Task 1: The private label convention

**Files:**
- Modify: `.gitignore`
- Modify: `eval/golden/README.md`
- Test: `tests/test_golden_privacy.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: the convention `eval/golden/labels/p*.json` is gitignored and
  accepted by every label reader. Task 2 relies on nothing from this task.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_golden_privacy.py`:

```python
"""A golden label is fully public or fully private, never partly redacted.

Spec section 3 measures why field-level redaction is out: nulling a PII field in
the truth moves its path into the *absent* classes, so a model that reads the
real value off the image is scored as having hallucinated it. The unit of
redaction is therefore the whole receipt, and privacy is carried by the
filename.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from eval.golden_set import _is_label_file

REPO = Path(__file__).resolve().parents[1]
LABELS = REPO / "eval" / "golden" / "labels"


def _check_ignore(relative: str) -> bool:
    """True when git would ignore ``relative``. Asks git, never the file text."""
    return subprocess.run(
        ["git", "check-ignore", "-q", relative],
        cwd=REPO, capture_output=True,
    ).returncode == 0


def test_a_private_label_is_ignored_by_git():
    assert _check_ignore("eval/golden/labels/p001.json"), (
        "a p-prefixed label must be gitignored: it carries a real merchant's "
        "name, address and tax id"
    )


def test_a_public_label_is_not_ignored():
    """The complement, so the rule is a rule and not a blanket."""
    assert not _check_ignore("eval/golden/labels/r001.json")


def test_the_existing_labels_are_still_tracked():
    """Guards the blanket-ignore mistake: a pattern that swallowed the whole
    directory would satisfy the first test and destroy the public set."""
    out = subprocess.run(
        ["git", "ls-files", "eval/golden/labels"],
        cwd=REPO, capture_output=True, text=True,
    ).stdout.split()
    for stem in ("r001", "r002", "r003"):
        assert f"eval/golden/labels/{stem}.json" in out


def test_every_label_reader_accepts_a_private_name():
    """`_is_label_file` is the only filter any reader applies; the other three
    readers glob unfiltered, so accepting here means accepting everywhere."""
    assert _is_label_file(Path("p001.json"))
    assert _is_label_file(Path("r001.json"))
    assert not _is_label_file(Path("TEMPLATE.json"))
    assert not _is_label_file(Path("manifest.json"))


def test_no_private_label_is_committed():
    """The milestone's whole point, asserted over the tracked tree."""
    out = subprocess.run(
        ["git", "ls-files", "eval/golden/labels"],
        cwd=REPO, capture_output=True, text=True,
    ).stdout.split()
    leaked = [f for f in out if Path(f).name.startswith("p")]
    assert not leaked, f"private labels committed: {leaked}"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_golden_privacy.py`

Expected: `test_a_private_label_is_ignored_by_git` FAILS (nothing ignores `p*`
yet). The other four should PASS already — they assert today's state.

**Read the actual failures.** If more than one fails, say which and why before
changing anything: the other four are describing the tree as it is, and a
failure there is a finding about the tree, not about this task.

- [ ] **Step 3: Add the ignore rule**

In `.gitignore`, beside the existing `eval/golden/images/` entry:

```gitignore
# A golden label is fully public or fully private, never partly redacted:
# nulling a PII field in the truth makes a correct read score as a
# hallucination (see the 2026-08-22 growing-the-golden-set design, section 3).
# `p`-prefixed labels carry a real merchant's name, address and tax id and are
# never committed. Their images are already excluded by the line above.
eval/golden/labels/p*.json
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_golden_privacy.py`
Expected: 5 passed.

- [ ] **Step 5: Prove the ignore rule is load-bearing, and that it is not a blanket**

Two mutations, each reverted before the next:

1. Delete the `eval/golden/labels/p*.json` line. Expected:
   `test_a_private_label_is_ignored_by_git` fails. Revert.
2. Replace it with `eval/golden/labels/*.json`. Expected:
   `test_a_public_label_is_not_ignored` fails — **and this is the mutation that
   matters**, because a blanket ignore satisfies the first test while destroying
   the public set. Revert.

Record both outputs.

- [ ] **Step 6: Document it where a labeller decides it**

In `eval/golden/README.md`, add this after the "How to label a receipt"
numbered list, before "Composition targets":

```markdown
## Public or private?

**Decide this before you write the label, not after.** A label is committed in
full or not at all — there is no partly-redacted label, because nulling a PII
field in the truth makes a model that reads the real value score as having
*hallucinated* it (measured; see the 2026-08-22 growing-the-golden-set design,
section 3).

| the receipt is… | name it | what happens |
|---|---|---|
| a real third party's, with their name, address or tax id on it | `p{id}.json` | gitignored — scored here, absent from the repo |
| yours, synthetic, or the owner has consented to publication | `r{id}.json` | committed, as the existing three are |

**When in doubt, use `p`.** A label committed by mistake is in git history
permanently; a private label can always be published later.

Record the receipt in `manifest.json` either way — an id, a category and a
holdout flag carry no personal data, and keeping every receipt there is what
lets `composition_stats` report the real mix. A clone that lacks the label
simply does not count it.
```

- [ ] **Step 7: Full suite, lint, then commit**

```bash
python -m pytest
python -m ruff check .
git add .gitignore eval/golden/README.md tests/test_golden_privacy.py
git diff --cached --stat
git commit -m "feat(golden): a label is fully public or fully private"
```

---

## Task 2: The aggregate says which receipts it scored

**Files:**
- Modify: `eval/run_repeats.py`
- Test: `tests/test_run_repeats.py`

**Interfaces:**
- Consumes: Task 1's convention (only conceptually — no code dependency).
- Produces: `aggregate.json` gains a top-level `scored_receipts`, a sorted list
  of the distinct `receipt_id` values across every repeat.

**Why a list and not a count** (spec §9 Q2): a count of "how many were private"
restates the naming rule, and a second copy of a rule is one that can drift —
this milestone already shipped one derived count that did. A list of ids
restates nothing, and answers the question a reader actually has.

**Where the ids come from.** `EvalResult` carries `receipt_id` — verified, its
fields are `receipt_id, confidence, critical_correct, field_acc, breakdown`.
Read it off the in-memory `report`, never by re-reading the file the loop just
wrote: an artifact derived from its own output cannot disagree with it, so the
check would be vacuous.

**The loop does not keep its reports** — verified: `report` is rebound each
iteration and only derived dicts reach `entries`. So accumulate the ids as you
go rather than retaining whole `EvalReport`s; a set of strings is all that is
needed and holding 100×5 reports for it would be wasteful.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_run_repeats.py`:

```python
def test_the_aggregate_names_the_receipts_it_scored(tmp_path, monkeypatch):
    """A number is only comparable to another number over the same receipts.

    The golden set can hold gitignored labels, so a clone scores fewer receipts
    than this machine does. The aggregate says which, rather than leaving a
    reader to infer coverage from a total.
    """
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients", _fresh_tiers_factory(1)
    )

    aggregate = run_repeats(
        "run-ids", 2, golden_dir=golden, results_root=tmp_path / "results"
    )

    scored = aggregate["scored_receipts"]
    assert scored == sorted(set(scored)), "sorted and deduplicated"
    assert scored, "a scored run names at least one receipt"

    # It is the union over repeats, not one repeat's view.
    from_repeats = {
        r["receipt_id"]
        for entry in aggregate["repeats"]
        for r in json.loads(
            (tmp_path / "results" / "run-ids" / entry["results_file"])
            .read_text(encoding="utf-8")
        )["results"]
    }
    assert set(scored) == from_repeats
```

> **Note for the implementer:** `_write_golden` writes **one** receipt, so this
> test's `scored` has a single element. That is enough to catch a hardcoded
> `[]` or a wrong key, but **not** enough to catch "returns only repeat 1's
> ids". Step 5 tells you what to do about that.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_run_repeats.py::test_the_aggregate_names_the_receipts_it_scored`
Expected: `KeyError: 'scored_receipts'`.

- [ ] **Step 3: Write the implementation**

In `eval/run_repeats.py`, initialise an accumulator beside `entries`:

```python
    scored: set[str] = set()
```

then, inside the loop, immediately after `report = _baseline.run_baseline(...)`
and before `entries.append(...)`:

```python
        # Which receipts this number is over. A clone can hold fewer labels than
        # the machine that ran it -- `eval/golden/labels/p*.json` is gitignored --
        # so a total alone does not say what was covered. Accumulated across
        # repeats, not read from one: a repeat that failed to load a label
        # contributes nothing and must not silently narrow the list.
        scored.update(r.receipt_id for r in report.results)
```

and add the key to the `aggregate` dict beside `spread_omitted`:

```python
            "scored_receipts": sorted(scored),
```

**Mind the indentation:** `aggregate` is built *inside* the loop (the artifact
is rewritten after every repeat), so its keys sit at three levels, not two.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_run_repeats.py`
Expected: every test in the module passes, including the new one.

- [ ] **Step 5: Prove the pin discriminates, and strengthen it if it does not**

Run this mutation: guard the accumulator so only the first repeat contributes —

```python
        if index == 1:
            scored.update(r.receipt_id for r in report.results)
```

**Predicted:** the test still PASSES, because `_write_golden` gives every repeat
the same single receipt, so repeat 1's ids and the union are identical. **If it
passes, that is the finding**, and the test cannot see the defect it is named
for.

Fix it by making the repeats differ: a golden dir with two labels plus a
`make_pass_clients` double whose second repeat fails one of them, so the two
repeats score different id sets. Then re-run the mutation and show it red.
Revert the mutation afterwards.

**Do not skip this because the first test passed.** Eight assertions that could
not fail shipped on the previous milestone, and the two most recent were written
by rounds that were closing earlier ones.

- [ ] **Step 6: Full suite, lint, then commit**

```bash
python -m pytest
python -m ruff check .
git add eval/run_repeats.py tests/test_run_repeats.py
git diff --cached --stat
git commit -m "feat(eval): the aggregate names the receipts it scored"
```

---

## Task 3 — CONTROLLER ONLY: collect and label

**Do not dispatch this to a subagent.** It needs the owner's receipts, a camera,
and human reading. It is the actual bottleneck of step 7 and no code removes it.

- [ ] **Step 1: Confirm the mechanism before collecting anything**

```bash
python -c "from pathlib import Path; from eval.golden_set import validate_labels, composition_stats; print(validate_labels(Path('eval/golden/labels'))); print(composition_stats(Path('eval/golden/labels'), Path('eval/golden/manifest.json')))"
```

Expected today: `[]` and `total: 3`, `by_category: {'handwritten': 3}`.

- [ ] **Step 2: Collect toward the documented mix, not toward a number**

`eval/golden/README.md` carries the targets: `printed_clean` 60%,
`printed_degraded` 15%, `handwritten` 20%, `adversarial` 5%, holding out 20–30%.

**The set is currently 100% handwritten against a 20% target** — five times its
intended weight, in the hardest category. Spec §7a is why that matters: ADR-0049's
60.00–61.43% is an average over three receipts all drawn from the hardest fifth
of the intended mix. **Collecting toward the targets should move the measured
figure with no model change at all**, so do not read a change in the number after
this step as a change in the system.

Follow the README's four steps per receipt. Name each `p{id}` unless the receipt
is yours, synthetic, or consented — Task 1's README section is the rule.

- [ ] **Step 3: Validate after every batch, not at the end**

Re-run Step 1's command. `validate_labels` must stay `[]`. Then
`python -m pytest tests/test_eval_floor.py` — it parametrises over every label
present and will reject a new one whose empty-extraction floor reaches 10% or
which makes an empty extraction hallucinate. **That is free validation of your
labelling**, and a failure there means the label is wrong, not the test.

- [ ] **Step 4: Re-baseline, and report a spread over the new set**

```bash
python -m eval.run_repeats --run-id "$(date +%F)-cloud-only" --repeats 5
```

Read `scored_receipts`, `n_failed` and `spread_omitted` before quoting any
figure, and report min/max/median/n — never a single number. **Compare only to a
run over the same `scored_receipts`**; a figure over a different set is a
different measurement, not a better one.

- [ ] **Step 5: Commit the artifacts, checking for a stranded temp file first**

```bash
find eval/results -name "*.tmp"
git status --short
git add eval/results/ eval/golden/manifest.json
git diff --cached --stat
```

**Read that stat before committing.** No `p*.json` may appear in it. If one
does, stop: the ignore rule failed and Task 1's pin should have caught it.

---

## Dated defect log

**This plan does not self-amend.** Everything above is the text as written; this
log is what was wrong with it and when.

### 2026-08-22 — caught after the merge, closing ISSUE-020

**Defect 7 — Task 3 Step 3 tells the labeller the wrong thing to conclude, and
names the wrong test.** Its sentence "a failure there means the label is wrong,
not the test" is a blanket, and it was **false on the first receipt anyone would
have collected**: `tests/test_rules.py` scored every golden label against a
frozen `today` of 2026-07-28, so a correctly-made label for a receipt
photographed in August failed `R031` as a future date. The label was right and
the test was stale — the exact reverse of what Step 3 says to conclude. That is
review standard 28: a correct instruction (do run the tests) carrying a false
reason (the test is always right), and the reason is what a reader generalises.

**The date is fixed** (ISSUE-020, closed on `feat/corpus-date-not-frozen`), so
that particular counter-example is gone. **The blanket is what licensed it**, and
it is still a blanket.

Two corrections to Step 3, for whoever runs Task 3:

- **Run the whole suite, not `tests/test_eval_floor.py` alone.** Step 3 names
  only that module. With ISSUE-020 closed, `tests/test_rules.py`'s real-corpus
  check is the one that validates a new label against the *validator*, and it is
  not in the module Step 3 names.
- **A green corpus check is not proof it ran.** `tests/test_rules.py` builds its
  corpus inside a bare `except Exception`, so one label that will not parse
  takes the whole corpus to `{}` and every case **skips** while the suite stays
  green — **ISSUE-021**. If you add a label and the corpus case count does not
  go up, that is the bug, not luck.

### 2026-08-22 — caught during Task 2, by its implementer

**Defect 4 — the plan's own remedy for a weak test was itself a test that could
not fail.** Task 2 Step 5 correctly predicted its test would not discriminate,
and prescribed the fix: "a golden dir with two labels plus a `make_pass_clients`
double whose second repeat fails one of them, so the two repeats score different
id sets." **They do not differ.** `run_eval`'s except branch still appends an
`EvalResult(receipt_id=label_path.stem)` for a receipt that failed, so both
repeats yield the same ids — measured `per_repeat=[['r1','r2'],['r1','r2']]`.
Following the plan would have produced a **second** assertion that could not
fail, in the step written to close the first.

Closed by the implementer differently, and it took two rounds. The first grew
the golden set **between** repeats, mirroring the module's existing
`_empties_the_golden_set_after_the_first_repeat`, so repeat 1 saw `{r1}` and
repeat 2 saw `{r1, r2}`, with an explicit precondition assertion so the fixture
could not silently flatten again. **Controller verified the `if index == 1`
mutation is red.**

**Defect 6 — that closure was itself non-discriminating, in the opposite
direction.** Found by review round 1, measured at `3ca4ec4`: because the fixture
only *grew*, repeat 2's id set **was** the union, so an implementation keeping
only the last repeat's ids satisfied every assertion. Rebinding
`scored = {r.receipt_id for r in report.results}` in place of `scored.update(...)`
— a one-token slip, and the likelier one at that line — left all 49 tests in
the module green. Closed by making the repeats **disjoint** rather than nested:
`_swaps_the_label_after_the_first_repeat` adds `r2` *and unlinks `r1`*, so
repeat 1 covers `{r1}`, repeat 2 covers `{r2}`, and neither set equals the
union. **Controller confirmed both directions red**, and the scoped re-review
confirmed them independently in a byte-faithful replica — additionally showing,
by neutralising the exact-value assertion, that the union assertion itself is
what discriminates rather than a neighbour doing its work.

**Defect 5 — the implementation comment the plan prescribed states something
false.** It read "a repeat that failed to load a label contributes nothing".
**Measured against `run_eval` with a malformed label: `ids in results: ['bad']`,
`n_failed: 1`.** A failed receipt *is* in `scored_receipts`, for the same reason
it is in `n_receipts`. The implementer refused to write the sentence and gave
the true reason instead — that `run_eval` globs the labels directory afresh per
repeat.

**The shape recurred at every depth this plan reached.** A mutation that could
not be caught; tests that could not fail; a prescribed *remedy* for a weak test
that was itself a weak test; and then a closure for that which was weak in the
opposite direction. **No count is written here.** Every earlier version of this
sentence carried one, and each was falsified by the round that followed — which
is the same shape, one level up (review standard 20: write a sentence that does
not quantify, or enumerate from the tree at the moment you write it). Every
instance was caught by someone running the mutation instead of trusting the
prose, and **none by a gate.**

### 2026-08-22 — caught during Task 1, by its implementer

**Defect 1 — the plan's central mutation could not be caught, and it was the
mutation the task exists to prove.** Task 1 Step 5 named a blanket
`eval/golden/labels/*.json` as "the mutation that matters, because a blanket
ignore satisfies the first test while destroying the public set", and predicted
`test_a_public_label_is_not_ignored` would redden. **It does not.**
`git check-ignore` consults the **index** first and will not call a *tracked*
path ignored, so under the blanket the brief's five tests run verbatim were
**5 passed** — entirely green against the one wrong rule that destroys the
public set.

**Reproduced by the controller** in a throwaway repository: with a blanket
`labels/*.json`, a tracked `r001.json` returns `rc=1` ("not ignored") while an
untracked `p001.json` returns `rc=0`; the same `r001.json` with `--no-index`
returns `rc=0`, proving the rule does match and only the index was hiding it.

Closed **two independent ways**, either sufficient alone: `--no-index`, which
asks the rules about a *name* rather than the index about a *file*; and an
assertion on `r004.json`, the next public label, which no index entry can mask.
Verified after the fix: the blanket now reddens `test_a_public_label_is_not_ignored`
and an exact-filename rule reddens `test_a_private_label_is_ignored_by_git`.

**Defect 2 — a third wrong rule the brief also could not catch.** An exact
filename rule, `eval/golden/labels/p001.json`, passed every test the brief
wrote. Found and closed by the implementer with an assertion on `p042.json`,
since the rule must cover every private label not yet written.

**Defect 3 — a docstring claiming a guard it cannot provide.** The brief's
`test_the_existing_labels_are_still_tracked` docstring said it "guards the
blanket-ignore mistake". It cannot: `git ls-files` reports the index, and an
ignore rule never untracks anything, so it stays green under the blanket
(measured). Corrected to state what it does guard.

**Also closed by the implementer, unprompted:** two wrong-reason passes, where a
failed `git` (`rc 128`, or an empty `ls-files`) would have read as the *passing*
direction; and two `eval/golden/README.md` lines stating flatly that "Labels are
committed", which the section this task adds contradicts two paragraphs later.

**The shape to carry forward:** every one of these is a test that could not
fail, in a task whose entire subject is a rule that must catch wrong
implementations. The previous milestone shipped eight of that class; this plan
added further instances in its first task alone, and the brief's own Step 5 —
written to prove the rule was a rule and not a blanket — was one of them.

---

## Self-review of this plan

**Spec coverage.** §1 → Task 3. §2 (the fixture constraint) → Global
Constraints. §3 (why per-receipt) → Task 1's docstring and README section. §4
(the convention, no module change) → Task 1; §4's coverage-recording half →
Task 2. §5 (not seeded from model output) → **gap, now closed**: it is not a
code change, so it lives in Task 3 Step 2's instruction to follow the README's
four steps, and the README's own step 3 says "replace every value with exactly
what the image shows". §6 (costs) → Task 3 Step 4's comparison rule. §7a → the
§9 resolutions and Task 3 Step 2. §8 → nothing to implement.

**Placeholder scan:** none. Every step names a command, a file, or shows the
code.

**Type consistency:** `scored_receipts` is spelled identically in Task 2's test,
implementation and commit. `_write_golden`, `_fresh_tiers_factory` and
`run_repeats` match `tests/test_run_repeats.py` as it stands.

**Known soft spots, stated rather than hidden.**

1. **Task 2 Step 5 predicts its own test will pass under the mutation.** That
   prediction is the point of the step, but it is still a prediction: if the
   mutation reddens something, read which test and why before assuming the pin
   is adequate.
2. **Task 1's tests shell out to `git`.** `tests/test_freshness_check.py` and
   `tests/test_sha_citations.py` already do, so the pattern is established, but
   they will behave differently in a shallow or non-git checkout. Neither is a
   configuration CI uses (`fetch-depth: 0` is set on both checkout steps), and
   the plan does not add a skip — a silent skip is how a guard becomes vacuous.
3. **An earlier draft of Task 2 told the implementer to read ids from a
   `reports` list "the loop already keeps", with a conditional fallback if it
   did not.** It does not — `report` is rebound each iteration and only derived
   dicts reach `entries`. Verified and corrected to a definite instruction:
   accumulate ids into a `set` as the loop runs. The conditional form was the
   defect, not just the wrong variable — a step that says "do X, or Y if X is
   not true" has not been checked against the tree.
