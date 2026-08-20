# Local-to-Cloud escalation (ISSUE-001 step 5)

**Date:** 2026-08-20
**Status:** Approved, not built
**Issue:** ISSUE-001 step 5 — "build the local→Cloud escalation"
**Decision record:** an ADR is required; see §10.

---

## 1. What this is for

Nothing in this project has a measured accuracy number. The blocker has never
been the harness — it is that no model reachable from this machine could read a
receipt. `gemma4:cloud` can. This milestone builds the mechanism that lets a run
use it, so that step 6 (the first real baseline) becomes possible.

**It does not produce an accuracy number.** That is step 6, and it needs repeats
and a spread rather than a single run — cloud inference is not deterministic at
`temperature=0`, and two identical runs on r002 scored 55.56% and 61.11%.

---

## 2. The shape, and why it is not what ISSUE-001 described

ISSUE-001 describes a **confidence-triggered fallback**: run local, score, and
escalate when the score is low. The measurements it records falsify the premise
that design rests on.

**Granite's extraction is empty and its triage is good.** At `max_edge=768` its
extraction is every field null, zero line items, 11.11% transcription accuracy
(2/18) — *identical* with tool-use on and off. Its triage in the same run read
`merchant_name_guess: SUMMIT FUEL OPC`, `legibility: fair` and `est_items: 1`,
all correct, and that merchant guess is the entry point of ADR-0043 decision 1's
whole hint-retrieval path.

A confidence trigger therefore fires on every receipt, which makes the local pass
a fixed toll rather than a ladder, and makes the "escalation rate" ISSUE-001 asks
to be reported a constant.

**So the ladder is per pass, and only the extract pass has two rungs:**

| pass | rungs | why |
|---|---|---|
| `triage` | local | the pass granite is measurably good at, and the cheapest place to get the merchant guess |
| `extract` | local, then cloud | the user's ruling: run local first, fall back when it does not work. The two rungs are **roles filled by configuration**, not fixed identities — see §7 |
| `repair` | whichever rung produced the kept extraction | repairing a rung that was discarded spends a call re-asking an answer already rejected |
| `consistency` | not wired (P7.T1 is a separate milestone) | |

### 2.1 What a tier is

A tier is a **`(model, use_tools)` pair**, not a provider. On Ollama both rungs
share the endpoint, the key and the timeout: the local daemon proxies `:cloud`
models, so switching rungs is the model string plus the tools flag. ISSUE-001
records this directly — "`VLM_BASE_URL` needs no change, because the local daemon
is still the endpoint — it proxies."

This is why the milestone is small. It is not a multi-provider abstraction.

---

## 3. The fallback trigger

The local rung's result is **discarded** when any of:

1. the call raised (`VLMTransientError` / `VLMPermanentError` out of extract);
2. the response carried a `parse_error`;
3. the extraction **read nothing**.

Clause 3 needs a definition that cannot rot as the schema grows, and this project
already has one.

### 3.1 "Read nothing", defined by reuse and not by a new list

> The extraction read nothing ⟺ no path whose group is `core` or `line_items`
> is filled.

`_group(path)` and `_is_filled(value)` in `eval/metrics.py` are ADR-0040's
machinery. `_group` classifies a dotted path as `self_report`, `line_items` or
`core` **from the path string alone**, and `_is_filled` is already documented as
"True when a leaf carries information the model could have read". A field added
to the schema later is classified by the prefix test without anyone deciding,
which is exactly the property ADR-0040 built them for.

An enumerated list of fields would rot on the next schema change, and a second
copy of the predicate would reproduce ISSUE-008 — two identical predicates with
nothing binding them — which is already open in this repository for that shape.

### 3.2 It runs on the pre-normalization extraction

`normalize` fills `currency` from `DEFAULT_CURRENCY`. Granite's measured output
was "every field null, zero line items, `currency: PHP` from `DEFAULT_CURRENCY`".
Testing after normalization would read that `PHP` as content the model produced,
and the fallback would never fire. The predicate therefore takes
`outcome.extraction`, before `normalize` is applied.

### 3.3 Why the self-report group must be excluded

A strict "every leaf is null" test can never be true: `prices_include_tax`
defaults to `False`, and `meta.*` fields rest at `[]`/`None`/`False`. Those are
the model's claims about the paper, not transcriptions from it — which is the
distinction `_group` exists to draw.

---

## 4. Moving the grouping into `src`

`_group` and `_is_filled` are private to `eval/metrics.py`, and the dependency
runs **eval → src** (`eval/run_baseline.py` imports
`receipts.extract.clients.factory`). The pipeline cannot import them without
inverting that.

**Decision: move both to `src/receipts/extract/paths.py`** — beside `flatten`,
which they already call, and `count_nulls`, whose docstring already says it is
"the final tie-break when picking between extraction attempts". Two rungs are
two attempts; this is the same question. `eval/metrics.py` imports them from
their new home, so there is still exactly one definition.

**The move must be behaviour-preserving**, and is pinned as such: `field_accuracy`
must be unchanged on a fixture across the move. This touches ADR-0040's machinery
and that ADR's classes-tile-the-path-set property must still hold.

---

## 5. The egress boundary

**User ruling (2026-08-20): the escalation is for the eval path only, and a
production upload must not be able to reach the cloud through it.**

This is structural rather than a default, and the enumeration that makes it so:

- every production entry — `worker.py`, and both `cli.py` call sites — calls
  **`process_receipt`**;
- the only non-test caller of **`run_receipt`** is `build_eval_pipeline`.

So the ladder is a parameter on `run_receipt` and **never** on `process_receipt`.
Production has no argument to pass and no code path to reach. `make_client` is
untouched and keeps returning exactly one client; a separate builder constructs
the ladder and only the eval adapter calls it.

### 5.1 The limit of that guarantee, stated

This does **not** prevent someone configuring production's single client to point
at a cloud model. That was possible before this milestone and remains possible
after it. The guarantee is that *this mechanism* is unreachable from the
production path — nothing wider. Claiming more would be a false claim of the
kind ADR-0032 is about.

---

## 6. Provenance

ISSUE-001's requirement: without a record of which model produced a kept
extraction, no eval can attribute accuracy to a model, and a good-looking number
could be hiding the fact that everything escalated.

**What already exists**, and the brief understates it: `extraction_runs.model_id`
is written on every call (`repository.py`, from `response.model_id`,
`nullable=False`). Every model call is already attributed.

**What is actually missing**: nothing links a receipt to the run whose output it
kept — there is no FK from `receipts` to `extraction_runs`. Today that is
inferable because one client serves every pass. A second rung is precisely what
breaks the inference.

**And it is not a database problem here.** The eval path touches no database, so
for this milestone provenance flows out through the return path.

### 6.1 The route, which follows an existing precedent

`EvalReport`'s docstring already says `cost_per_receipt` and the latency
percentiles "are not observable through the injected `pipeline_fn` (which returns
only an extraction and a confidence), so they stay `None` here and are filled in
by callers that measure the real pipeline." Tier attribution is the same kind of
fact and takes the same route, so `run_eval`'s contract does not change.

- `run_receipt` returns a **`RunOutcome`** dataclass — `extraction`, `report`,
  `triage`, `attribution` — replacing today's triple. Four positional elements is
  where a tuple stops being readable, and `ProcessResult`/`BatchResult` are the
  established idiom. Four call sites change: three tests and
  `build_eval_pipeline`.
- `attribution` records **every rung attempted and which one was kept**.
- `build_eval_pipeline` appends each attribution to a caller-owned collector;
  `run_baseline` folds it in after `run_eval`.
- `EvalReport` gains per-rung counts, `None` when unobservable.

### 6.2 The rate is printed beside the accuracy

`format_report` prints the per-rung counts **next to** the accuracy figures. The
placement is the requirement, not a nicety: ISSUE-001's stated fear is a good
number that hides having escalated everything, and a figure on its own page does
not answer it. Counts rather than a derived percentage, so nothing drifts.

---

## 7. Configuration

**Nothing set means today's behaviour, exactly.** That is a hard requirement of
this design, and it is pinned (§9).

| setting | role |
|---|---|
| `VLM_MODEL_TRIAGE` | **existing, and gains its first consumer.** It is declared in `Settings` today with zero references in `src`, `eval`, `scripts` or `tests`. Unset falls back to `VLM_MODEL_EXTRACT`, which is today's behaviour |
| `VLM_MODEL_EXTRACT` | the **first** extract rung — meaning unchanged |
| `VLM_MODEL_EXTRACT_FALLBACK` | the **second** extract rung. **Unset means no fallback**: the ladder has one rung |
| `VLM_USE_TOOLS_TRIAGE` | the triage rung's tool-use flag. See the trap in §7.2 — this is not optional convenience |
| `VLM_USE_TOOLS_FALLBACK` | the second rung's tool-use flag |

**"Local" and "cloud" are roles, not hard-coded identities.** A rung is whatever
its model setting names. So a **cloud-only run** — which is what step 6 needs on
this hardware, and what keeps a baseline from paying granite before every call —
is `VLM_MODEL_EXTRACT=gemma4:cloud` with `VLM_MODEL_EXTRACT_FALLBACK` unset. No
code change and no special mode; the ladder simply has one rung that happens to
be a cloud model.

### 7.2 The trap a reader of ISSUE-001 would otherwise walk into

ISSUE-001 says switching to the cloud tier is "`VLM_MODEL_EXTRACT` /
`VLM_MODEL_TRIAGE`, plus `VLM_USE_TOOLS=true`". Under a per-pass ladder that
advice is now **actively harmful if taken globally**: `VLM_USE_TOOLS` is the
whole-process default, so setting it true turns tool use on for the *triage* rung
too — and granite's triage is measured to degrade with tools on, losing
`merchant_name_guess` entirely, which is the field ADR-0043 decision 1's hint
path keys off.

`VLM_USE_TOOLS_TRIAGE` exists so the triage rung can hold tools off while the
cloud extract rung has them on. It is the per-rung half of the same granularity
defect §7.1 closes, and leaving it out would close the defect for extract while
leaving it open for triage.

### 7.1 The tools granularity defect, closed

`_TOOLS_OFF_BY_DEFAULT` is `frozenset({"ollama"})` — keyed on the **provider**,
while the exception is per **model**. Granite and `gemma4:cloud` are both
provider `ollama`, so one `VLM_USE_TOOLS` cannot be off for one and on for the
other. ADR-0002's 2026-08-18 correction recorded this and deliberately left it
for this milestone.

Under a per-pass ladder the two now appear in the *same* pass, so the defect stops
being theoretical: granite's triage **degrades** with tools on
(`merchant_name_guess` goes empty, measured), and `gemma4:cloud` requires tools on
per ADR-0002.

**Resolution: one function, used at both ends.** Tool use for a rung resolves as
the explicit per-rung value, else the global `VLM_USE_TOOLS`, else the provider
default. That is the precedence chain `make_client` already implements with one
level added, and both `make_client` and the ladder builder call the same
function. Not two mechanisms that must agree — review standard 19.

---

## 8. What this milestone does not do

- **It produces no accuracy number.** That is step 6.
- **It does not route production uploads to the cloud.** §5.
- **It does not wire self-consistency.** P7.T1 is its own milestone, though its
  value rose when cloud nondeterminism was measured.
- **It adds no FK from `receipts` to `extraction_runs`.** The eval path has no
  database; production provenance is a separate decision (§6).
- **It does not call `few_shots_for`.** Few-shot images remain Cloud-tier-only
  and unattached; ADR-0043 recorded that deliberately.

---

## 9. Testing

Each pin is proven red before the fix, and each guarantee is reverted separately.

1. The trigger fires on a raise, on a `parse_error`, and on a read-nothing
   extraction — and **does not** fire on a partial-but-real one.
2. The cloud rung is not called when local returns something usable, and is
   called when it does not.
3. Repair runs on the rung whose extraction was kept.
4. Attribution names the kept rung; the report's counts move when the ladder does.
5. Moving `_group`/`_is_filled` is behaviour-preserving — `field_accuracy`
   unchanged on a fixture.
6. An enumeration over production entry points showing none constructs a ladder
   (a universal claim is answered by an enumeration, not an argument).
7. With no new settings set, the client set is exactly one client.

### 9.1 What no test here can establish

Whether `gemma4:cloud` reads receipts *well*; whether the free tier survives a
full run; and anything about cloud nondeterminism. All three are step 6's, and
the last is why step 6 needs repeats and a spread.

---

## 10. Why this needs an ADR

It changes what "the provider" means. **ADR-0002** treats the provider as a
single runtime choice, and this makes the model-and-tools pair a per-pass,
per-rung property. It also closes the granularity defect ADR-0002's own
correction recorded and left open. The ADR carries: the per-pass ladder, the
trigger predicate, the move of the grouping into `src`, the egress boundary and
its stated limit, and the provenance route.

---

## 11. Environment findings from the day this was designed

Recorded because they are not derivable from the tree and they gate the work.

- **`~/.ollama` had been reset.** The model store was empty (0 files) and the
  `id_ed25519` identity was regenerated when the daemon was next started, so the
  account registration from 2026-08-18 was gone with it.
- **`gemma4:cloud` returned `Unauthorized`** on an inference call while its
  manifest pulled successfully — a direct instance of ISSUE-001's own warning
  that *pull success is not access*. Cleared by the user running `ollama signin`;
  re-probed and confirmed working.
- **Ollama is installed at `%LOCALAPPDATA%\Programs\Ollama\ollama.exe`**, which is
  on PowerShell's `PATH` but not on Git Bash's — the same shape as §1.6's
  `receipts.exe` wrapper.
- **There is no cloud build of granite.** Measured against the registry:
  `granite3.2-vision:2b` resolves, `granite3.2-vision:2b-cloud` and
  `granite3.2-vision:cloud` both 404, with `gemma4:cloud` resolving as the control
  that shows the query can match a cloud model. Running the same weights on cloud
  hardware would not improve comprehension in any case — ISSUE-001 already
  answered that: weights decide comprehension, hardware decides speed.

### 11.1 One experiment is outstanding and should run before the ladder is locked

Granite has **never been given a fair test**. Every completed local run was
forced to `max_edge=768`, where `resize_for_model` itself logged "estimated text
height 7.7px is below 12px; text may be illegible". At the pipeline default of
2048 it has never finished — triage alone took 887 s and extract hit the 900 s
timeout.

So "granite reads nothing" rests entirely on a run the code flagged as
unreadable. ISSUE-001 calls the 2048 run **the empirical decider** for whether
granite is a genuine first rung or a cost paid before every cloud call, and it
needs only a raised `VLM_TIMEOUT_S` and one receipt. Its result does not change
the mechanism this document specifies — the ladder is configurable either way —
but it changes what the default ladder should be.
