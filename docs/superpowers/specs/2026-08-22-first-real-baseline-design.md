# The first real baseline — design

**Date:** 2026-08-22
**Status:** Proposed
**Closes:** `docs/KNOWN_ISSUES.md` ISSUE-001 step 6 — the first accuracy number
this project has ever measured.
**Rests on:** ADR-0047 (the local→Cloud escalation), ADR-0040 (what
`field_accuracy` means), ADR-0039 (a local run is a liveness check).

---

## §0. Where every figure in this document comes from

This section exists because ADR-0045 makes relaying a measurement into a design
an act that takes ownership of it, and this document does both.

**Measured while writing this design, on `main` at `3939147`.** Each is
reproducible from the command or probe named beside it in the section that uses
it:

- the results filename collides across repeats, and the second write wins (§3);
- `latest_results_file` sees a top-level file and not a subdirectory (§3);
- the live environment builds **one** extract rung (§5);
- a granite→gemma4 ladder builds **two** rungs with **two distinct**
  `model_id` values (§5, §9);
- `read_nothing` returns `False` for each of the three ISSUE-016 shapes, and
  `True` for a default extraction (§6);
- the committed artifact's top-level keys carry no rung-counts key (§4);
- `eval/results/` is not gitignored, so §16's "commit the results" is reachable;
- the golden set is three images and three labels on disk; `eval/results/` is
  empty and nothing under it is tracked;
- five gates PASS at `3939147`, controller-run.

**Carried from `docs/KNOWN_ISSUES.md` ISSUE-001 and not re-measured here.**
Every one is a claim about a model's behaviour, which costs a real call to
check, and §5 spends one of those calls deliberately rather than assuming:

- `granite3.2-vision:2b` — 11–16% transcription, null merchant / TIN / invoice /
  total, 30–39 minutes per receipt;
- `gemma4:cloud` — reads r002 correctly, roughly 25 seconds;
- two identical `gemma4:cloud` runs on r002 scored 55.56% and 61.11%.

**A note on every elapsed figure above.** ADR-0047 decision 8: `VLM_TIMEOUT_S`
bounds one HTTP attempt and the SDK retries, so each is wall clock over an
unknown number of attempts. There is no per-call measurement in this
repository and this document does not create one.

---

## §1. What this delivers, and what it does not

**Delivers three things.**

1. **A headline accuracy number with a spread**, from repeated cloud-only runs.
   A single run is not a baseline: the two figures in §0 differ by 5.55 points
   on one receipt at `temperature=0`.
2. **The first evidence that the ADR-0047 escalation fires against a real
   model.** That ADR's closing section states plainly that it never has — every
   behavioural measurement in it comes from a fake client.
3. **A committed durable record of both, carrying provenance** — which rung
   produced the extraction that was kept, for each receipt.

**Does not deliver.** A calibrated threshold (step 8, and three receipts cannot
carry one). A larger golden set (step 7). Any decision about whether production
uploads may reach the cloud — that authorisation remains golden-set-only and
this milestone does not widen it.

---

## §2. The state this rests on

Verified rather than assumed, because this document's own instructions say the
handoff has been wrong at the start of several sessions:

| check | result |
|---|---|
| working tree | clean |
| `git branch --no-merged main` | names nothing |
| `main` vs `git ls-remote --heads origin main` | equal at `3939147` |
| freshness check, anchor `2a2dc1b` | empty |
| ADR files vs ADR index rows | 48 and 48 |
| `^## ISSUE-` headings vs `**Status:**` lines | 16 and 16 |
| `python scripts/verify.py` | all five PASS |

The runtime is the **Docker** Ollama on `:11435`, not the Windows-native daemon
on `:11434`; `granite3.2-vision:2b` and `gemma4:cloud` are both present on it.
Naming the port is not pedantry — there are two daemons on this machine and the
project reads only one of them.

---

## §3. Architecture — one new caller, and nothing else moves

A thin module above `run_baseline`, invoked as `python -m eval.run_repeats` to
match `python -m eval.run_baseline`:

```
for i in 1..n:
    report = run_baseline(results_dir = eval/results/<run-id>/repeat-NN/)
    collect (metrics, extract_rung_counts, failures, that repeat's file path)
write eval/results/<run-id>/aggregate.json
```

**Nothing under `src/` changes.** `run_eval`, `_write_report`,
`_report_to_dict`, and the hand-written fixture in
`tests/test_cli_reports.py::test_the_producer_writes_the_shape_this_module_hand_writes`
are untouched. That is the whole point of this shape: ISSUE-012's own text says
fixing it "moves who owns the write", and a new caller owning a *new* write
takes no position on who should own the old one.

### 3.1 Why each repeat gets its own directory

`_write_report` names the file `{date}-{prompt_version}.json`. Both components
are constant within a day, so repeats collide. Measured — two writes into one
directory, then the same two into separate directories, with distinguishable
reports:

```
one directory   -> 1 file on disk, survivor counts.receipts = 22   (the first is gone)
two directories -> 2 files on disk, survivors 11 and 22            (control)
```

The control arm is the reason the first arm is believable: an instrument that
cannot report the absence of the fault has not reported its presence
(review standard 14, applied to the instrument).

`python -m eval.run_baseline` — the invocation ISSUE-001 step 6 item 5 names —
does not expose `results_dir`, so the documented command cannot produce the
repeats the same step demands. Giving each repeat its own directory removes the
collision **by construction**, with no rename and no change to the naming
contract.

### 3.2 Why the aggregate lives in a subdirectory

`latest_results_file` does a non-recursive `glob("*.json")` and sorts by mtime.
Measured:

```
aggregate at the top of eval/results/  -> latest_results_file returns it
only subdirectories present            -> latest_results_file returns None
```

`receipts calibrate` with no `--results` resolves its input through that
function. An aggregate at the top level would become the newest file and
`calibrate` would be handed a document it does not understand. **The
load-bearing half of this reason is the measurement above, not any claim about
how `calibrate` fails** — whether it refuses cleanly or raises, it stops
producing a threshold either way, so the decision does not rest on which.

Putting both the per-repeat directories and the aggregate below
`eval/results/<run-id>/` leaves `latest_results_file` seeing exactly what it
sees today, which is nothing: `eval/results/` is currently empty and nothing
under it is tracked.

---

## §4. The aggregate artifact

The artifact `run_eval` writes today has top-level keys `prompt_version`,
`auto_approve_threshold`, `counts`, `metrics`, `failures`, `calibration`,
`results` — **no rung-counts key at all**, which is ISSUE-012 read off a written
file rather than off the source. The aggregate carries three things that file
cannot.

**Configuration identity.** The resolved ladder as `(model_id, use_tools)` per
extract rung and for triage; `DEFAULT_CURRENCY`; `VLM_TIMEOUT_S`;
`PROMPT_VERSION`; `prompt_bundle_hash()`. A tier is a `(model, use_tools)` pair
(ADR-0047 decision 2), so recording the model alone would record something that
is not the tier.

**Per repeat.** The §16 metrics, `extract_rung_counts`, `failures`, and the
relative path to that repeat's own results file — so the aggregate points at
the per-receipt detail rather than duplicating it.

**Spread.** Per metric, across repeats: `min`, `max`, `median`, `n`, and the raw
per-repeat values.

### 4.1 Two deliberate omissions

**No mean and no standard deviation.** A standard deviation over five samples is
a figure that reads as a statistic and is not one, and the whole reason step 6
demands repeats is that a single number was going to be read as more than it
was. The raw per-repeat values are in the file; anyone who wants a different
summary can compute it from them and say so.

**No derived escalation rate.** Counts only, carrying forward §6.2 of
`docs/superpowers/specs/2026-08-20-local-to-cloud-escalation-design.md`:
"Counts rather than a derived percentage, so nothing drifts."

*(That reasoning lives in the escalation **design**, not in ADR-0047. An earlier
draft of this section cited "ADR-0047 §6.2", which does not exist: that ADR's
decisions are numbered 1 through 8 with lettered subsections, and none of them is
a 6.2. Caught by the self-review that checked the citation instead of trusting
it; review standard 21.)*

### 4.2 Which metrics get a spread

**Derived from the artifact, not enumerated here.** The aggregate computes a
spread over the per-repeat `metrics` block, read from the report dictionary
itself, and the key set is the **union over every repeat**, so a key only one
repeat reported does not vanish — the shape `field_accuracy` already takes with
`pred.keys() | tru.keys()`, and for the same reason: a list written in prose is
read as complete, so writing one is a claim that ages (review standard 20).

**Derived is not unconditional.** A key in that union gets an entry when some
repeat gave it a number, or when every repeat gave it `None`, and only then.

> **Corrected 2026-08-22, during Task 3.** This paragraph cited `group_of` as
> the precedent. That was false: `group_of`'s **first** check is membership of
> the enumerated `SELF_REPORT_LEAVES`, so it is a prefix test *plus* an
> enumeration and is not an example of "derived, not enumerated" at all. The
> decision is unchanged; only its supporting fact was wrong, which is ADR-0048's
> species exactly — a wrong reason reads as evidence the author understood the
> thing. Found by Task 3's implementer, which refused to write a docstring it
> could not make true. `field_accuracy` was verified before being substituted.

> **Corrected again 2026-08-22, later the same day.** That first correction
> deleted this paragraph's only qualifier — it had read "a spread over **every
> numeric entry** in the per-repeat `metrics` block" — while leaving "included
> without anybody deciding" standing. The result promised inclusion that
> `spread_over` does not give and that its shipped docstring explicitly denies,
> in the one paragraph titled "which metrics get a spread". The condition is now
> stated in full, as a biconditional. The rule is worth reading precisely: a
> non-numeric *value* is not by itself a reason a key is dropped — measured,
> `spread_over([{"x": 1}, {"x": "a"}])` reports `x` with `n: 1` — what drops a
> key is having no number in any repeat while not being null in all of them.

---

## §5. The two runs, and one call before them

**Before either: one timed granite call.** ISSUE-001 step 6 item 4 —
`scripts/try_one_receipt.py`, which was checked to write no files at all, so it
leaves no artefact in `eval/results/` (ADR-0039). Its purpose is to replace the
carried 30–39 minute figure with one measured on this box today, before
committing to a run that pays it three times. A slow provider should be caught
in one call rather than in nine.

**Run 1 — the ladder, n=1.** `VLM_MODEL_EXTRACT=granite3.2-vision:2b`,
`VLM_MODEL_EXTRACT_FALLBACK=gemma4:cloud`, `VLM_USE_TOOLS=true`,
`VLM_USE_TOOLS_TRIAGE=false`. Measured to build:

```
rung 0: granite3.2-vision:2b  use_tools=True
rung 1: gemma4:cloud          use_tools=True
triage: granite3.2-vision:2b  use_tools=False
```

`VLM_USE_TOOLS_TRIAGE=false` is not optional: tools on costs granite the
`merchant_name_guess` that ADR-0043 decision 1's hint path keys off. There is no
per-rung setting for the *first* extract rung, so rung 0 inherits the global
`true`; the carried measurement is that tools leave granite's extraction
identical, so this is accepted rather than worked around.

This run answers one question: **does the escalation fire against a real model,
and on how many receipts.**

**Run 2 — cloud-only, n=5.** Today's `.env` unchanged. Measured to build **one**
extract rung, `gemma4:cloud` with `use_tools=True`, which is a valid one-rung
baseline. This run produces the headline number and its spread.

Both runs read only the three golden receipts, which is the whole of the
2026-08-18 egress authorisation.

### 5.1 Why the headline number comes from the cloud-only run

§7 of the escalation design says a cloud-only run "is what step 6 needs on this
hardware, and what keeps a baseline from paying granite before every call". This
design does not overrule that sentence: **the baseline is the cloud-only run.**
The ladder run is a one-off proof that the mechanism works against a real model —
the thing ADR-0047's closing section says has never been done — and it is not the
source of the published number.

A later reader who sees a ladder run in this milestone should not conclude the
baseline came from one, which is why this is stated here rather than left to be
inferred.

That split is also why the ladder is n=1 while the cloud-only run is n=5: the
nondeterminism the repeats exist to measure is the **cloud's**, so repeating the
ladder would pay granite again for a spread granite does not produce.

---

## §6. ISSUE-016 gates this configuration, and is handled by observation

ISSUE-016 is filed as gating nothing. That is true of a cloud-only run and false
of a ladder. Measured, with a control:

```
default extraction                 -> read_nothing = True    (escalates)
merchant.name = ""                 -> read_nothing = False   (kept)
totals.total = 0                   -> read_nothing = False   (kept)
totals.prices_include_tax = False  -> read_nothing = False   (kept)
```

If granite emits any of those on any receipt, its extraction is **kept**, never
escalates, and carries that receipt's score down to granite's transcription
rate. ADR-0047 §3a said a third instance of this class should be expected. This
is where it bites.

**Report-don't-fix stands** (review standard 19, and ADR-0047's own ruling): no
enumeration of fields, and no change to `is_filled`, which `field_accuracy`
shares by design — narrowing it would move a published metric.

**What this design does instead is make it legible.** The per-rung counts reach
the aggregate, so a kept-granite receipt is visible in the committed record. The
requirement this milestone takes on: **if the counts show granite kept any
receipt, that extraction is inspected and the finding recorded before any number
is published.** A kept-granite receipt is a real observation about the ladder,
not a corruption to be hidden — the defect today is only that it would be
invisible.

Without the aggregate this would be invisible twice over: the counts do not
reach the committed file (ISSUE-012), and a poisoned accuracy figure looks
exactly like a clean one.

---

## §7. Failure modes this design plans for

**granite raises on every attempt.** ADR-0047 decision 3's first clause escalates
on a raise, so the run completes and the counts show granite keeping nothing.
That is a successful run of the mechanism, but it exercises the **raise** clause
and not the **read-nothing** clause, and the record must say which one fired
rather than reporting "the escalation works".

**The cloud tier throttles or fails mid-run.** A raise on the final rung has no
further rung. `run_eval` catches per receipt, records it in `failures`, and
continues — so a partially failed repeat still produces a file. The aggregate
therefore carries **failures per repeat**, not only metrics: a repeat that
scored two receipts and failed one must not average into the spread as though
it were whole.

**A repeat dies between runs.** Each repeat writes its own file before the next
begins, so an interrupted sequence leaves every completed repeat's own results
file on disk. The aggregate is written last.

> **Corrected 2026-08-22, during Task 4.** This paragraph ended "and can be
> rebuilt from the per-repeat files". **That is false, and it is false for the
> one reason that matters most here:** the per-rung counts are in no results
> file at all — that is ISSUE-012, and closing that gap is why this artifact
> exists — and five of `config`'s six keys (`prompt_bundle_hash`,
> `default_currency`, `vlm_timeout_s`, `triage`, `extract_rungs`) appear
> nowhere else either. An interrupted run keeps its scores and **loses its
> provenance**. Task 4's implementer refused to write the claim into the
> shipped docstring and reported it; the controller verified it against the
> artifact's key set before correcting both copies.

**`prompt_bundle_hash()` has no production caller (ISSUE-007).** Reading it into
the aggregate is a read. It does **not** close ISSUE-007 and does not give the
function the production caller that issue asks for.

---

## §8. Testing

Offline, against a scripted `FakeVLMClient` — the seam `run_baseline` already
exposes. No test in this milestone requires a network call: the real runs are
the measurement, not the gate.

Four guarantees, each reverted separately (review standard 3):

1. **N repeats produce N results files in N directories, plus one aggregate.**
   Proven red by pointing two repeats at one directory and showing one file
   survives — the collision measured in §3.1 is what this pin exists to hold
   closed, so a pin that was never red against it is not a pin.
2. **The aggregate's rung counts equal the reports'.** Pinned against a fake
   ladder that actually escalates, so the assertion is not satisfied by a single
   key appearing in both places.
3. **The spread is computed over repeats that deliberately differ**, so
   `min != max`. A spread over identical repeats is an assertion that cannot
   fail, and this repository has shipped three of those.
4. **`latest_results_file(eval/results/)` still returns `None`** after the
   runner has written a full run — the guarantee §3.2 rests on, stated over the
   real function rather than over a description of it.

---

## §9. What this milestone does not decide

- **ISSUE-012's own decision** — who owns the existing write. It stays open. What
  changes is that it no longer gates step 6, because its stated reason for
  blocking ("an artifact that omits which model produced what does not record
  the thing that step exists to record") is discharged by the aggregate.
- **ISSUE-013.** Measured inert under **both** configurations here: the ladder's
  two rungs carry two distinct `model_id` values, so keying the counts by
  `model_id` distinguishes them correctly. Its collapse needs two rungs naming
  one model with opposed tools flags, which on this corpus is only reachable
  with `gemma4:cloud` in both rungs, because granite has no cloud build.
- **ISSUE-016.** Observed, recorded, not fixed.
- **Whether receipt images may leave this machine in production.** Unchanged.
- **Any threshold** (step 8) or **golden-set growth** (step 7). Three receipts is
  33 percentage points per receipt, and no calibration claim survives that.

---

## §10. Open questions for the plan

1. **Does the ladder run's aggregate and the cloud-only run's aggregate share a
   schema?** They should, so the two are diffable, but the ladder has two rungs
   and the cloud-only has one. The schema must express a one-rung run without a
   null-shaped hole that reads as "not measured".
2. **What is the `<run-id>`?** A date plus a configuration label is readable and
   sorts, but two runs of one configuration on one day would collide again — the
   exact defect §3.1 exists to remove. The plan must not reintroduce it one
   level up.
3. **Are the per-repeat files committed, or only the aggregate?** §16 wants
   results committed so regressions show in a diff, and the per-receipt
   `field_results` block is where a regression is actually legible.
