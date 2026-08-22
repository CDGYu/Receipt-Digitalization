# ADR 0049 — A baseline is a spread over receipts, and the escalation does not say why it fired

**Status:** Accepted
**Date:** 2026-08-22
**Closes:** `docs/KNOWN_ISSUES.md` ISSUE-001 step 6 — the first measured accuracy
number in this project's history.
**Rests on:** ADR-0047 (the local→Cloud escalation), ADR-0040 (what
`field_accuracy` counts), ADR-0039 (a local run is a liveness check).

---

## Context

Since 2026-07-28 no number in this project was measured. Phase 6's merchant
matching, the buyer capture and every precision claim were built and
unvalidated. ADR-0047 landed the mechanism that could put a receipt-reading
model in front of the golden set; its own closing section states that **the
escalation had never run against a real model.**

This milestone built `eval/run_repeats.py` — a caller above `eval.run_baseline`
that runs the golden set N times, gives each repeat its own results directory,
and writes one aggregate carrying config identity, per-repeat metrics, per-repeat
rung provenance and a spread. It then ran it. Merged by true fast-forward
`3939147` → `aca2521`, 22 commits, single parent each, zero merge commits.

---

## Decision 1 — The baseline is the cloud-only run; the ladder run is a proof of mechanism

`docs/superpowers/specs/2026-08-20-local-to-cloud-escalation-design.md` §7 says
a cloud-only run "is what step 6 needs on this hardware, and what keeps a
baseline from paying granite before every call". This ADR does not overrule that
sentence. **The published figures come from the cloud-only run.** The ladder run
exists to close ADR-0047's stated gap, not to produce a number.

**What would fail if this were false:** a reader would take the ladder's
one-receipt 95.83% for a baseline. It is one receipt, and §Decision 5 is why
that matters more than it sounds.

---

## Decision 2 — No single figure is the baseline, and this run proves it rather than arguing it

Cloud-only, one rung, `gemma4:cloud` for triage and extract, `use_tools=true`,
no fallback. Five repeats, 15 receipts scored, `n_failed` 0, `spread_omitted`
empty, 5 of 5 complete. `PROMPT_VERSION` 1.1.0, prompt bundle
`528cd19c6e5b0f2d`. Committed at `62eefa3`.

| metric | min | max | median | n |
|---|---|---|---|---|
| `transcription_accuracy` | 60.00% | 61.43% | 60.00% | 5 |
| `transcription_accuracy_core` | 52.50% | 55.00% | 52.50% | 5 |
| `transcription_accuracy_line_items` | 70.00% | 70.00% | 70.00% | 5 |
| `line_item_f1` | 55.56% | 55.56% | 55.56% | 5 |
| `self_report_agreement` | 57.69% | 57.69% | 57.69% | 5 |
| `critical_field_accuracy` | 0.00% | 33.33% | 33.33% | 5 |

**`critical_field_accuracy` came back 33.33, 0.00, 33.33, 33.33, 33.33.** One
repeat in five scored **zero** on the metric that gates auto-approval, from
identical inputs at `temperature=0`. A single run landing on repeat 2 would have
recorded 0.00% and been wrong about the system rather than about that run.

**`auto_approval_precision` is `n=4` with `n_null=1`, and the null is correct** —
repeat 2 auto-approved nothing, so its precision is undefined rather than zero.
That is P8.T3's distinction, observed in the wild on the first real run.

---

## Decision 3 — The variance that matters is across receipts, not across repeats

**This is the finding this milestone did not expect, and it is the one to carry
forward.** Per receipt, over the same five repeats:

| receipt | min | max | median |
|---|---|---|---|
| r001 | 60.71% | 64.29% | 64.29% |
| r002 | 91.67% | 95.83% | 95.83% |
| **r003** | **11.11%** | **11.11%** | **11.11%** |

The headline 60.00–61.43% is an **average over receipts spanning 11% to 96%**.
It describes no receipt. The spread across repeats is ±1.4 points; the spread
across receipts is **85 points**.

**ISSUE-001 step 6's standing warning was aimed at the wrong axis.** It said: do
not report a single run, because runs vary. Runs barely vary. **Receipts vary
enormously**, and averaging three of them into one figure hides that one of the
three is a near-total failure.

**r003 scored exactly 11.11% on all five repeats** — a perfectly stable failure,
which is not the signature of a model that read the page and got it wrong.

**What would fail if this were false:** nothing in the artifact. The aggregate
reports only run-level metrics; the per-receipt figures above were derived from
the committed per-repeat files' `results[].transcription_correct` and
`transcription_total`. A reader of the aggregate alone cannot see Decision 3 at
all. That is a gap, recorded in "What this ADR does not decide".

---

## Decision 4 — The escalation fires against a real model, and the artifact does not record why

The ladder — `granite3.2-vision:2b` → `gemma4:cloud`, triage on granite with
`VLM_USE_TOOLS_TRIAGE=false` — was run over **one receipt** (r002), 41m39s wall
clock, committed under `eval/results/ladder-probe/`.

```
triage       : granite3.2-vision:2b   use_tools=False
extract rung 0: granite3.2-vision:2b   use_tools=True
extract rung 1: gemma4:cloud           use_tools=True
extract_rung_counts: {"gemma4:cloud": 1}
```

**Granite ran, was discarded, and the cloud rung produced the kept extraction.**
ADR-0047's closing gap — "the escalation has never run against a real model" —
is closed.

**But which clause of ADR-0047 decision 3 fired is not recorded and cannot be
recovered.** That decision has two: the rung **raised**, or the rung **read
nothing**. They are different facts about the local model — a timeout says the
box is too slow, a read-nothing says the model cannot read the page — and the
artifact conflates them. Verified rather than assumed: `PassAttempt` carries
exactly `pass_name`, `model_id`, `rung`, `kept`; no field records a discard
reason, and `.rung` is read nowhere in `src/` or `eval/` (which is ISSUE-015).

**Do not infer the clause from the elapsed time.** `VLM_TIMEOUT_S` bounds one
HTTP attempt and the SDK retries (ADR-0047 decision 8), so 41m39s covers an
unknown number of attempts across two granite calls.

---

## Decision 5 — The mechanism's own rules, as built

- **A run directory is never reused.** `--run-id` is required with no default,
  and the directory is created with `exist_ok=False`. No auto-suffixing: a
  suffixed second directory is a second artifact nobody can tell from the first.
- **The run directory must be a direct child of the results root.** Enforced in
  `prepare_run_dir` rather than in `argparse`, so a direct caller is closed too.
  An empty `--run-id` otherwise resolves to the root itself and puts
  `aggregate.json` where `latest_results_file` would hand it to
  `receipts calibrate`.
- **Every figure in the spread was observed.** `statistics.median_low`, never
  `median`, which averages the two middle values on an even count. No mean and
  no standard deviation.
- **The spread's key set is the union over repeats**, derived from the reports
  rather than enumerated, so a metric added later appears without anybody
  deciding. A key is reported when some repeat gave it a number **or** every
  repeat gave it `None`, and only then.
- **A tier is recorded as `(model_id, use_tools)`**, read from the client and
  `null` when unobservable. Only `OpenAICompatClient` sets `use_tools`.
- **The aggregate carries `n_failed` and `spread_omitted` at top level.** The
  first exists because an all-failed run reports `0.0` as an *observation* and
  exits 0. The second names any metric the repeats carried that the spread has
  no entry for, **derived by subtracting one key set from the other** rather
  than by restating the inclusion rule — a second copy of that rule is one that
  can drift.
- **`n_repeats` is the number of repeats present; `n_repeats_requested` is the
  target.** They disagree exactly when a run was interrupted.
- **Atomicity is the bonus and must never be the cost.** The aggregate is
  rewritten after every repeat via a staging file and `Path.replace`; a refused
  rename retries briefly and then degrades to an in-place write. Measured: on
  Windows, `replace` onto a destination another process merely holds open for
  reading raises `PermissionError`, while `write_text` onto that same
  destination under the same handle succeeds.

---

## What this ADR does not decide

- **Whether receipt images may leave this machine in production.** Cloud egress
  remains authorised for the **golden set only**. Both runs here read only the
  three golden receipts.
- **Any accuracy target.** Three receipts cannot validate a precision claim, and
  `README.md` and `RECEIPT_SYSTEM_SPEC.md` §15's "roughly 70–85%" expectation
  predates this measurement and stays by ruling until the golden set grows
  (ISSUE-001 step 7).
- **Why r003 fails identically on every repeat.** 11.11% five times is a fact,
  not a diagnosis. Nothing here establishes whether it is the image, the label,
  the prompt or the model.
- **Who owns `run_eval`'s write** (ISSUE-012). Unchanged. What changed is that it
  no longer gates step 6: the aggregate carries the provenance the results file
  omits.
- **`read_nothing`'s vacuous-value shapes** (ISSUE-016). Untouched, report-don't-fix.
- **Whether the aggregate should carry per-receipt figures.** Decision 3 is
  invisible in the aggregate and had to be derived from the per-repeat files.
- **Whether the discard reason should be recorded.** Decision 4 is the argument
  that it should; this ADR does not build it.

---

## Consequences

**What is now possible that was not.** The project has a measured number, and
the mechanism to re-measure it in 2m20s. A regression will show up in a diff of
`eval/results/`.

**What this cost, and it is the argument for the workflow.** Twenty-one plan
defects were found during execution, every one the plan author's, and **eight
assertions that could not fail** — one per task, two of them created by the very
fix rounds that closed earlier ones. The worst would have let a runner recording
**zero measured numbers** pass its brief; the last sat on `extract_rung_counts`,
the field that discharges ISSUE-012. Every one was caught by an implementer or
reviewer who ran a mutation instead of reading the code. **No gate caught any of
them**, and all five were green throughout.

**The most-repeated defect was prose, not code.** Seven times a rationale cited a
precedent that did not support it or promised behaviour the code lacked — once
inside a sentence written to fix that very class. ADR-0048 exists because of this
shape and this milestone paid for it again.

**What no gate here can see.** That r003 fails, that the failure is stable, and
that averaging it into a headline hides it. The suite is green on all of it.
