# ADR 0039 — The local path is a liveness check, not a measurement

**Status:** Accepted (2026-08-11)
**Relates to:** ISSUE-001 (`docs/KNOWN_ISSUES.md`), ADR-0002 (provider
abstraction), ADR-0003 (confidence), ADR-0017 (what "passing" means)

Derived 2026-08-11 by running it. **Re-derive rather than quote** (ADR-0028
rule 1) — but see decision 3 before spending half an hour doing so.

## Context

ISSUE-001 has blocked the first real accuracy numbers since 2026-07-28. Its
diagnosis was that `granite3.2-vision:2b` on CPU is both too slow to iterate
against and too weak to read the corpus.

The user chose to stay on Ollama rather than move to a hosted provider, so that
diagnosis was **re-run rather than argued with**: one receipt, 768px, detached,
`VLM_TIMEOUT_S=1800`.

| | July 2026 | **2026-08-11** |
|---|---|---|
| one receipt at 768px | ~1371 s (~23 min) | **1896 s (31.6 min)** |

Same model, same image, **~38% slower**. Ollama moved to 0.32.4; nothing else
about the machine is known to have changed, and no explanation is offered here.

The run itself:

```
Receipts: 1   Auto-approved: 0   Critical-correct: 0   Failed: 0
Auto-approval precision:  n/a      Critical-field accuracy: 0.00%
Field accuracy:        45.00%      Line-item F1:            0.00%
confidence 0.000 · fields_correct 18 / 40
```

**`Failed: 0` is the entire good news.** The pipeline completes end to end
against a real provider. Confidence `0.000`, no critical field correct, no line
item found: the model cannot read the receipt.

CPU-only is measured *today*, not inherited: discovery reported `library=cpu …
total "7.6 GiB"` with no device, and `/api/ps` showed `size_vram=0` with the
model loaded.

## Decision

### 1. A local run is a liveness check. It is not evidence about accuracy

A green local run licenses exactly one sentence: **the pipeline completes end to
end against a real provider.** It licenses nothing about extraction quality,
threshold placement, or the ≥99% auto-approval precision target.

This matters because the run *looks* like a measurement — it prints the six §16
metrics in the same table a real baseline would. `Field accuracy: 45.00%` is the
trap: it is 18 of 40, and ISSUE-001's side-findings record that the denominator
includes `meta.*` and that a field null in both label and extraction scores as
correct. It is dominated by agreeing about nothing.

### 2. Liveness artefacts do not enter `eval/results/`

That directory is for runs that can be compared with each other — §16 wants
results committed so a regression shows up in a diff, grouped by
`prompt_bundle_hash()`.

A one-receipt run at a non-default resolution from a model that read nothing is
not comparable with anything. Committing it would make it the **first** file
there, sitting beside future real baselines as though it belonged. Liveness runs
go to `var/`, which is gitignored.

**`eval/results/` is still empty, and that is correct.** The project has never
had a real baseline.

### 3. Do not re-derive the local timing

It has been measured twice, seven weeks apart, and got worse. A third run costs
half an hour and tells you what this ADR already says.

This is a deliberate exception to ADR-0028 rule 1. That rule exists because
claims about the tree rot silently; **this claim has been re-measured, the newer
number is here, and the direction of travel is recorded.** If the hardware
changes, the run is worth repeating — and then the thing to update is this
table, not a fresh argument.

### 4. Calibration moves with the hardware, not with the code

P3.T6 / P8.T1 (the threshold sweep and confidence weights) and Phase 6's
top-10-merchant accuracy metric stay blocked. **No code change is pending**:
ADR-0002's provider abstraction means the move is environment variables, and
`docs/KNOWN_ISSUES.md`'s readiness check has already verified the hosted wiring
builds, the timeout reaches the client and tool-use is on.

The user's stated plan is a machine with better specifications. Two other routes
remain open and need no code either — **Ollama Cloud** (`ollama signin` exists
in the installed 0.32.4 build; needs `VLM_USE_TOOLS=true` because this provider
is in `_TOOLS_OFF_BY_DEFAULT`) and any hosted OpenAI-compatible or Anthropic
endpoint.

### 5. The configuration stays local

`.env` is left pointing at Ollama. That is the user's choice and costs nothing
to reverse — ADR-0002 exists so switching is environment, not code.

## Consequences

- **The next session does not need to run this.** That is the point.
- **A green `verify.py` still says nothing about extraction quality**, and never
  did (ADR-0017, ADR-0029). This ADR adds the matching sentence for the eval
  harness: a completed baseline is not a validated one.
- **`eval/results/` stays empty until a real baseline exists**, so its first
  file will mean something.
- **The P8.T3 fix was validated in the wild by this run.** Nothing was
  auto-approved — the exact shape that used to persist
  `"auto_approval_precision": 1.0` — and the artefact says `null`.

## What this ADR does not decide

Which capable environment is used, or when. Nor whether the golden set should
grow (P8.T2) — three receipts cannot validate a 99% precision target however
fast they run, and that limit is about the corpus, not the hardware.

Nor why the run got slower. Two numbers and a direction are recorded; the cause
is not investigated.

## References

`docs/KNOWN_ISSUES.md` — ISSUE-001, its readiness check and its re-measurement,
which is the entry to read first and **not** to re-derive;
`docs/adr/0002-provider-abstraction-and-runtime-config.md`;
`docs/adr/0017-two-suites-and-the-gate-runner.md`;
`RECEIPT_SYSTEM_SPEC.md` §16 (the metric set and the commit-the-results rule).
