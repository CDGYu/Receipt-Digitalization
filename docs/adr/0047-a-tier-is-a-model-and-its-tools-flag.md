# ADR 0047 — A tier is a model and its tools flag, and the escalation is eval-only

**Status:** Accepted (2026-08-21)
**Corrects:** ADR-0002 (VLM provider abstraction + env-based runtime config) —
its 2026-08-18 correction recorded that `_TOOLS_OFF_BY_DEFAULT` is keyed on the
provider while the exception is per model, and deliberately left the fix "for
the escalation ADR". This is that ADR.
**Builds on:** ADR-0040 (what field accuracy counts — its `group_of`/`is_filled`
grouping is what the fallback trigger is defined in terms of), ADR-0039 (the
local path is a liveness check), ADR-0043 (merchant identity is two-phase —
decision 1's hint path keys off `merchant_name_guess`, which is why triage stays
local-capable), ADR-0045 (a brief is a claim about the tree)
**Relates to:** ADR-0029 (what the gates certify and what they cannot),
ADR-0030 (a finding is a claim), ADR-0032 (a document cannot certify itself)

Derived 2026-08-20/21 on `feat/local-to-cloud-escalation`. **Re-derive rather
than quote** — every count here is a property of the tree at a moment.

---

## Context

ISSUE-001 has blocked this project since 2026-07-28: no model reachable from
this machine could read a receipt, so no accuracy number exists. Its step 5 asks
for a "local→Cloud escalation" and describes a **confidence-triggered fallback**
— run the local model, score the result, escalate when the score is low.

The measurements ISSUE-001 itself records falsify the premise that design rests
on, and one more measurement taken during this milestone finished the job.

---

## Decision 1 — The ladder is **per pass**, not confidence-triggered

**Granite's extraction is empty and its triage is good.** At `max_edge=768` its
extraction is every field null, zero line items, two fields transcribed
correctly — *identical* with tool-use on and off. Its triage in the same run
read `merchant_name_guess`, `legibility` and `est_items` correctly.

A confidence trigger therefore fires on **every** receipt, which makes the local
pass a fixed toll rather than a ladder and makes the escalation rate ISSUE-001
asks to be reported a constant.

So triage gets one rung and extract gets two. The rungs are **roles filled by
configuration**, not fixed identities: a cloud-only run is
`VLM_MODEL_EXTRACT=gemma4:cloud` with no fallback set.

### 1a — The empirical decider ran, and it refuted ISSUE-001's hypothesis

ISSUE-001 argued that "granite reads nothing" rested on an image the code itself
called illegible, and predicted that at the pipeline default of 2048 granite
"could move it off zero — not because the model improved, but because it would
finally be shown a legible image."

Run on r002 at `max_edge=2048` with the timeout raised: **590 s triage, 6563 s
extract, every real field null, zero line items, confidence 0.000.** The same two
fields correct as at 768. Triage did not improve either — it kept the two answers
that matter and got `legibility` *wrong* where 768 had it right.

**A legible image did not produce a reading; it produced a longer wait.** The
default ladder is therefore a single cloud rung for extract, with granite kept
for triage where it earns its cost. `docs/KNOWN_ISSUES.md`'s
`Measurement (2026-08-21)` is the record.

---

## Decision 2 — A tier is a `(model, use_tools)` pair, not a provider

On Ollama both rungs share the endpoint, the key and the timeout: the local
daemon proxies `:cloud` models, so switching rungs is the model string plus the
tools flag. That is why this milestone is small — it is not a multi-provider
abstraction.

**This closes ADR-0002's granularity defect.** `granite3.2-vision:2b` and
`gemma4:cloud` are both provider `ollama` and want opposite answers about tool
use: granite's triage *degrades* with tools on (it loses `merchant_name_guess`,
ADR-0043 decision 1's entry point), and `gemma4:cloud` requires them. One
provider-keyed flag cannot express that.

Resolution is **one function used at both ends**, not two mechanisms that must
agree: the rung's own explicit value, then the process-wide `VLM_USE_TOOLS`,
then the provider default. `make_client` calls it with `explicit=None`, which is
exactly the two-level chain it applied inline before — verified differentially
across nine provider spellings times three flag values, 27/27 identical.

**A trap this creates, and the setting that exists for it.** `VLM_USE_TOOLS` is
process-wide, so the advice "set `VLM_USE_TOOLS=true` for the cloud tier" now
turns tools on for the **triage** rung too. `VLM_USE_TOOLS_TRIAGE` exists
solely so triage can hold tools off while the cloud extract rung has them on.
There is **no** per-rung setting for the first extract rung; the pairing is how
that rung is reached.

---

## Decision 3 — The trigger has two clauses, and "read nothing" is defined against a default of the same shape

The local rung's result is discarded when the call **raised**, or when the
extraction **read nothing**:

> the extraction read nothing ⟺ its filled `core` and `line_items` paths are
> identical to those of a default extraction carrying the same rows, each row
> mirroring its counterpart's `position`.

**A parse failure is not a third clause.** `_evaluate` resolves it as
`response.parsed or ReceiptExtraction()`, so it produces exactly a default
extraction, which clause 2 already catches. Specifying it separately would have
been a check that can never independently fire.

**It runs before `normalize`.** `normalize` fills `currency` from
`DEFAULT_CURRENCY`, and granite's measured output was every field null with
`currency: PHP` supplied that way — judging afterwards would read that as content
the model produced, and the fallback would never fire.

### 3a — This definition was wrong twice, in the same direction, and the pattern is the point

Both wrong versions were **never-fires**: they would have left the cloud rung
unreachable with every gate green.

1. "No `core` or `line_items` path is filled" — false on a *totally empty*
   extraction, because `ReceiptExtraction()` carries
   `receipt.decimal_convention = 'point'`, which ADR-0040 classifies as `core`
   on purpose (the convention is something the document prints).
2. "Identical to a default-constructed `ReceiptExtraction()`" — false for one
   blank row, because `LineItem()` rests at `position=0` and
   `description_raw=""`, both of which `is_filled` accepts.

**Every wrong version was wrong because a field rests at a default that
`is_filled` accepts, and every fix was to make the baseline more like the thing
being judged rather than to enumerate fields.** Reading found neither; a
measurement found both. A third instance should be expected, and
`docs/KNOWN_ISSUES.md` ISSUE-016 records the class that is still open —
`merchant.name=""`, `totals.total=0` and `prices_include_tax=False` all still
read as content.

**`is_filled` is not the place to fix that.** It is shared with `field_accuracy`
by design (decision 4), and narrowing it would move a published metric.

---

## Decision 4 — One definition of "what the model read", in `src`

`group_of` and `is_filled` moved from `eval/metrics.py` to
`src/receipts/extract/paths.py`, beside `flatten` and `count_nulls`, and
`eval/metrics.py` imports them back under its existing private names so no call
site moved.

A copy would have reproduced ISSUE-008 — two identical predicates with nothing
binding them — which is already open in this repository for exactly that shape.
The move is load-bearing rather than cosmetic: neutering the `SELF_REPORT_LEAVES`
check reddens **pre-existing** `test_eval_metrics.py` tests, so the single
definition is genuinely shared.

---

## Decision 5 — The escalation is eval-path only, and structurally so

**User ruling, 2026-08-20.** A production upload must not be able to reach the
cloud through the escalation.

The ladder is a parameter on `run_receipt` and never on `process_receipt`;
`make_client` still returns exactly one client and is what every production
entry uses; only `build_eval_pipeline` receives rungs. Both halves are pinned:
a signature check (bounded so `**kwargs` cannot satisfy it), and an **AST
enumeration** asserting that `run_receipt`'s non-test call sites are exactly
`{build_eval_pipeline}`.

**The second half was prose until it was tested.** A `worker.py` function
calling `run_receipt(..., extract_fallback_client=...)` passed the entire suite.
Stating a ruling in a spec, a docstring and a plan is not enforcing it.

### 5a — The limit of this guarantee, stated

This does **not** prevent someone configuring production's single client to
point at a cloud model. That was possible before this milestone and remains
possible. The guarantee is that *this mechanism* is unreachable from the
production path — nothing wider.

The AST guard's own bound: static reach ends at a name, so `getattr`,
`globals()` and `importlib` routes pass. A string-literal check was measured to
cost **zero** false positives across all 70 modules and was still declined — it
closes one spelling of a route with unboundedly many, which is review standard
19's enumerated defence.

---

## Decision 6 — Non-final rungs run with `max_repairs=0`

`extract_with_repair` performs the extract *and* its repair rounds in one call,
so a rung cannot be kept first and repaired after — short of re-extracting,
which is the cost the rule exists to avoid. A non-final rung is a probe; repairs
on a rung that may be discarded re-ask a model that already failed, at tens of
minutes per call on this hardware.

Consequence, accepted: a non-final rung that *is* kept receives no repair
rounds. With no fallback configured there is one rung, it is final, and it gets
the configured budget — so **today's behaviour is unchanged**, which is this
milestone's standing requirement.

---

## Decision 7 — Provenance travels through the return value, not the database

`extraction_runs.model_id` already records the model for every call the
*service* path makes. What was missing is the link from a receipt to the run
whose output it kept — and on the eval path that is not a database problem,
because the eval path touches no database.

So `run_receipt` returns a `RunOutcome` carrying an `attribution` tuple,
`build_eval_pipeline` drains it into a caller-owned sink, and `run_baseline`
folds per-rung counts into the report. This follows `EvalReport`'s stated
precedent: facts the injected `pipeline_fn` cannot observe stay `None` and are
filled in by callers that measure the real pipeline.

**The counts print beside the accuracy figures.** That placement is the
requirement, not a nicety: ISSUE-001's stated fear is a good number hiding the
fact that everything escalated, and a figure on its own page does not answer it.

---

## Decision 8 — `VLM_TIMEOUT_S` bounds one attempt, not one call

`OpenAICompatClient` passes `timeout=timeout_s` into `openai.OpenAI(...)` and
never sets `max_retries`, which that SDK defaults to **2**. One `complete_json`
can therefore take up to **3 × `VLM_TIMEOUT_S`**, and the retries are silent.

Two consequences worth carrying: a failing local rung costs three times the
timeout before the fallback runs, not once; and **any timing measured through
this client is wall clock over an unknown number of attempts** — including the
6563 s in decision 1a, and ISSUE-001's earlier "extract hit the 900 s timeout",
which was up to 2700 s of real time.

Whether to pin `max_retries` is **not decided here** — it changes retry
behaviour for every provider.

---

## What this ADR does not decide

- **Whether receipt images may leave this machine in production.** Cloud egress
  is authorised for the **golden set only**; routing production uploads to the
  cloud is a separate decision and has not been made.
- **How the per-rung counts are keyed.** They are keyed by `model_id`, and
  decision 2 defines a tier as `(model, use_tools)` — so two rungs naming the
  same model with opposed tools flags are two tiers and one count key, and the
  escalation becomes invisible in the figure that exists to expose it.
  ISSUE-013.
- **Where the counts are written.** They reach the printed report and the
  returned object but **not** the committed results JSON, because `run_eval`
  writes the file before it returns and `run_baseline` folds the counts in
  after. ISSUE-001 step 6 commits that file as the durable record. ISSUE-012.
- **Whether `read_nothing` should reject vacuous values.** ISSUE-016, and
  report-don't-fix: closing it by enumerating fields is the defence that never
  converges.
- **No accuracy number.** That is step 6, and it needs repeats and a spread —
  cloud inference is not deterministic at `temperature=0`, and two identical
  runs on r002 scored 55.56% and 61.11%.

---

## Consequences

**What is now possible that was not.** An eval run can use a model that reads
receipts. That has been the blocker since 2026-07-28, and step 6 is no longer
waiting on a mechanism.

**What this cost, and it is the argument for the workflow.** Thirty-one plan
defects were found during execution, every one the plan author's. The ones that
would have caused damage were never wrong facts — they were **correct
instructions carrying invented reasons**, which invite an implementer to
simplify something load-bearing. Four assertions that could not fail were caught,
one of them the first in this repository's history to be caught *before* it
landed. Two lines were found deletable with all five gates green, and the
whole-branch review found three more, including the one that makes the final
rung final.

**What no gate here can see.** The escalation has never run against a real
model. Every measurement in this ADR about *behaviour* comes from a fake client;
every measurement about *models* comes from `scripts/try_one_receipt.py`, which
does not use this mechanism. The first real baseline is step 6, and it is the
first time these two things meet.
