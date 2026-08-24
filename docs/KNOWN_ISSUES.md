# Known Issues / Deferred Work

Open problems that are understood but deliberately parked. Each entry records what
happened, what was already fixed, what is still open, and the exact steps to
resume — so picking it up later does not mean re-deriving the diagnosis.

---

## ISSUE-001 — The first real baseline

*(Heading corrected 2026-08-22. It read "The first real baseline run has never
completed", which stopped being true that day. Citations name the issue number,
not the heading.)*

**Status:** OPEN, NARROWED — **step 6 is DONE, 2026-08-22 (ADR-0049).** Steps 7
(grow the golden set) and 8 (calibrate) remain, and step 7 now gates more than
the model does — see the measurement below.
**Owner action required:** yes — but **not the provider choice this issue
recommends.** See the ruling immediately below.
**Discovered:** 2026-07-28. **Blocks:** the first real accuracy numbers (spec §16),
threshold calibration (P3.T6 / P8), and any prompt/rule change that should be
re-evaluated.

> ## MEASUREMENT, 2026-08-22 — STEP 6 IS DONE, and the number is a spread
>
> **Cloud-only, one rung**, `gemma4:cloud` for triage and extract,
> `use_tools=true`, no fallback. Five repeats, 15 receipts, `n_failed` 0,
> `spread_omitted` empty, 5 of 5 complete, 2m20s wall clock. Committed at
> `62eefa3` under `eval/results/2026-08-22-cloud-only/`.
>
> | metric | min | max | median | n |
> |---|---|---|---|---|
> | `transcription_accuracy` | 60.00% | 61.43% | 60.00% | 5 |
> | `transcription_accuracy_core` | 52.50% | 55.00% | 52.50% | 5 |
> | `critical_field_accuracy` | 0.00% | 33.33% | 33.33% | 5 |
> | `line_item_f1` | 55.56% | 55.56% | 55.56% | 5 |
>
> **DO NOT QUOTE 60% AS THE ACCURACY.** It is an average over three receipts
> that scored **11%, 64% and 96%**. See ISSUE-017 — the variance that matters is
> across receipts, not across repeats, and this issue's own standing warning was
> aimed at the wrong axis.
>
> **The repeats still earned their cost.** `critical_field_accuracy` came back
> 33.33, **0.00**, 33.33, 33.33, 33.33 — one repeat in five scored zero on the
> metric that gates auto-approval, from identical inputs at `temperature=0`.
>
> **`cost_per_receipt` and both latency percentiles are `null` on every
> repeat.** Nothing in `eval/` or `src/` assigns them.
>
> **No per-call timing exists here.** `VLM_TIMEOUT_S` bounds one HTTP attempt
> and the SDK retries (ADR-0047 decision 8).
>
> **Step 2's `VLM_TIMEOUT_S` is 900 → that is stale; it is 600.**

> ## USER RULING, 2026-08-14 — Ollama only, and accuracy is the priority
>
> **This issue's "Recommended fix" is SUPERSEDED and must not be re-proposed.**
> The user has ruled that this system uses **Ollama only — no Gemini, no OpenAI,
> no Anthropic, no other hosted API.** Three sections below still argue for a
> hosted provider and are marked where they stand: *Recommended fix*, *How to
> resume* step 1, and the readiness check's hosted-wiring row. They are kept as
> the record of what was tried, not as instructions.
>
> **Alongside it: high extraction accuracy is the stated goal.** No target number
> is agreed, and none is defensible yet — this issue says so itself, because
> three golden receipts cannot validate any accuracy claim.
>
> **The two rulings collide with measured hardware, and that collision is now the
> open question.** Measured on this box 2026-08-14: **Intel i3-1115G4, 2 cores /
> 4 threads**, 15.7 GB RAM (~7.0 free), **Intel UHD iGPU only** — Ollama reports
> `library=cpu`, `size_vram=0`, and WSL2 cannot pass an Intel iGPU through.
> **One model is pulled: `granite3.2-vision:2b`.**
>
> A 2.5B model already costs 31.6 min per receipt here and reads nothing. High
> accuracy needs a 7B-class document model, which on two CPU cores is roughly 3×
> that. **Ollama-only + this machine + high accuracy is over-constrained.**
>
> ### The resolution, same day: two tiers, both Ollama
>
> **`granite3.2-vision:2b` stays the local primary, and Ollama Cloud becomes a
> confidence-triggered fallback.** The project also moves to a
> better-specified machine. No new provider enters the system, so the ruling
> holds.
>
> **One question was asked and answered, and it is the reason this is not simply
> "buy better hardware":** *does stronger hardware give granite proper accuracy?*
> **No.** Weights decide comprehension; hardware decides speed. A 2.5B model has
> a 2.5B ceiling on any machine.
>
> **But one exception is real and applies here, and it means granite has never
> actually been given a fair test.** The pipeline default is `max_edge=2048`
> (`resize_for_model`, `preprocess/image_ops.py`). At 2048 on this box **triage
> alone took 887 s and extraction hit the 900 s timeout — it never completed.**
> Every completed local run was forced down to `max_edge=768`, where that same
> function logged *"estimated text height 7.7px is below 12px; text may be
> illegible."*
>
> **So the "reads nothing" verdict rests entirely on a run the code itself
> flagged as unreadable.** On adequate hardware granite would finish at 2048 for
> the first time, and that alone could move it off zero — not because the model
> improved, but because it would finally be shown a legible image. Expect
> *something*, not high accuracy: 2.5B is very small for document OCR, and
> granite declares no tool support, so it cannot use the schema-constrained path
> either.
>
> **That test is the empirical decider** for whether granite is a primary or
> merely a cheap first pass that escalates nearly everything. It is cheap, it has
> never been run, and it must run at 2048 on the new machine.
>
> **The escalation itself is a real design change, not a config switch.**
> `make_client` returns exactly one client today; there is no second model, no
> fallback, and no record of which model produced a kept extraction. That last
> one matters most — without it no eval can attribute accuracy to a model, and a
> good-looking number could be hiding the fact that everything escalated. The
> escalation *rate* has to be reported beside the accuracy figure. Likely an ADR:
> it changes what "the provider" means, which **ADR-0002** currently treats as a
> single runtime choice.

### Measurement (2026-08-21) — the empirical decider RAN, and the hypothesis is refuted

**The ruling block above is wrong about what a legible image would do.** It
argues that "granite reads nothing" rests entirely on a run the code flagged as
unreadable, and predicts that at `max_edge=2048` granite "would finish at 2048
for the first time, and that alone could move it off zero — not because the
model improved, but because it would finally be shown a legible image."

It finished at 2048. It did not move off zero.

**Run:** r002, `max_edge=2048`, `VLM_TIMEOUT_S=3600`, `VLM_USE_TOOLS=false`,
`granite3.2-vision:2b` via `scripts/try_one_receipt.py`, against the WSL Ollama
on `:11435` — the endpoint `VLM_BASE_URL` names.

| | 768 (the run this issue calls unreadable) | **2048** |
|---|---|---|
| triage | — | **590 s** |
| extract | 2121 s | **6563 s** |
| merchant / date / total | all null | **all null** |
| line items | 0 | **0** |
| fields transcribed correctly | 2 | **2** |
| confidence | — | **0.000**, `needs_review` |
| critical fields all correct | no | **no** |

The only populated field was `currency: PHP`, and `DEFAULT_CURRENCY` supplied it
— the model read nothing at all. Validation returned `R010` (total is null) as
an error plus three warnings for the missing date, merchant and line items.

**The percentages are not comparable and the numerators are.** This run reports
8.33% (2/24) against the earlier 11.11% (2/18): the denominator grew because
ADR-0044 added `buyer.*` and `is_template_row` to the golden labels, and
`buyer.name` duly appears in the mismatch list. Two fields correct, both times.

**Triage did not improve either**, which the ruling block did not predict: at
2048 `merchant_name_guess` and `est_items` stayed correct, `is_receipt` stayed
wrong, and `legibility` became wrong where 768 had it right.

#### What this settles, and what it does not

- **Settled: granite is not a viable extract rung on this hardware at any
  resolution it can run.** 7153 s per receipt end to end, for nothing read.
  Against roughly 25 s for `gemma4:cloud`.
- **Settled: granite stays useful for triage.** `merchant_name_guess` was
  correct at both resolutions, and ADR-0043 decision 1's hint path keys off it.
- **Not settled: whether a larger local model would.** This is a measurement
  about a 2.5B model on two CPU cores, not about local inference in general.
- **Not settled: anything about `gemma4:cloud`'s accuracy.** That is step 6.

#### A second finding, which is about the harness rather than the model

**`VLM_TIMEOUT_S` bounds one HTTP attempt, not one `complete_json` call.**
`OpenAICompatClient` passes `timeout=timeout_s` to `openai.OpenAI(...)` and never
sets `max_retries`, which that SDK defaults to **2** (verified against the
installed openai 2.48.0). So a single call can take up to **3 × `VLM_TIMEOUT_S`**
before raising, and the retries are silent — nothing in the log distinguishes a
first attempt from a third.

That means **the 6563 s above is elapsed wall clock over an unknown number of
attempts** and cannot be attributed to one inference. It also means this issue's
earlier "extraction hit the 900 s timeout" was up to 2700 s of real time.
Whether to pin `max_retries` is undecided and belongs with the escalation ADR.

### Correction (2026-08-18) — granite DOES declare tool support

**The ruling block above says granite "declares no tool support, so it cannot use
the schema-constrained path either." That is false as measured today.** The same
claim has a second copy in the source: the comment above `_TOOLS_OFF_BY_DEFAULT`
in `src/receipts/extract/clients/factory.py` names `granite3.2-vision` among the
models that do "not declare the capability". **That copy is still there** — this
correction records it rather than reaching into `src/` to change it.

Measured against the running server, which is the anchor for the claim:

    curl -s http://localhost:11435/api/tags
    -> granite3.2-vision:2b   capabilities: ['completion', 'tools', 'vision']
       (2.5B, Q4_K_M, context 16384)

**What this establishes:** the model advertises `tools` in Ollama's own model
metadata, beside `vision` and `completion`.

**What it does NOT establish**, none of which may be assumed downstream:

- **That `/v1/chat/completions` accepts and honours a `tools` payload for this
  model.** The capability list and the OpenAI-compat shim are different surfaces;
  only sending such a request settles it.
- **That tool-use would improve the extraction.** A 2.5B model shown an
  illegible image is not rescued by a schema. Tool-use constrains the *shape* of
  an answer, not whether the model can read.
- **That `_TOOLS_OFF_BY_DEFAULT` should change.** Its *behaviour* is a safe
  default whatever reason is written beside it. The defect established here is
  the stated reason, not necessarily the choice.

**Whether the claim was ever true is not determinable from here**, and it is
deliberately not asserted either way. Ollama reports capabilities per model, and
both the server and the model tag have moved since the sentence was written (the
pulled blob reports `modified_at` 2026-07-28). It may have been accurate then and
rotted, or been wrong from the start. Recorded as **false now, with the command**
— calling a stale claim "never true" is a mistake this project has already made
in the other direction.

**Consequence for step 4 of the ordered plan above** (*"Set `VLM_USE_TOOLS=true`"*):
it is more plausible than the ruling implies, and still untested. The experiment
that settles it is one triage call with tools on — the ruling's stated fear is a
hard 400 on exactly that call, so the cheapest test produces the evidence either
way.

### Measurement (2026-08-18) — granite at 2048 vs 768, and what step 2 settles

**Step 2 of the ordered plan above — "give granite one fair test at
`max_edge=2048`" — has now run, with a 768 control. The answer is no: a legible
image does not make this model extract more.**

Method: `scripts/try_one_receipt.py r002 --max-edge {2048,768}`, `VLM_TIMEOUT_S`
5400 for **both**, same commit, same scorer, `granite3.2-vision:2b` (2.5B,
Q4_K_M). The two runs differ in `max_edge` and nothing else — the raised timeout
was applied to both so it could not become a second variable.
`try_one_receipt.py` writes no files, so ADR-0039's rule that liveness artefacts
stay out of `eval/results/` holds by construction.

| | 2048 | 768 (control) |
|---|---|---|
| triage | 553 s | 234 s |
| extract | 1268 s | 2121 s |
| total | 30.4 min | 39.3 min |
| transcription accuracy | 16.67% (3/18) | 11.11% (2/18) |
| **core** | **15.38% (2/13)** | **15.38% (2/13)** |
| line items | 20.00% (1/5) | 0.00% (0/5) |
| line-item F1 | 0.00 | 0.00 |
| hallucinated fields | 2 | 0 |
| triage `merchant_name_guess` | correct | correct |

**The headline number misleads; the core number is the real one.** Core accuracy
is *identical* — nothing about the merchant, tax id, invoice number, date or
totals was read at either resolution. The whole 5.6-point difference sits in the
line-items group, where the 2048 run emitted **two blank line-item rows** and the
768 run emitted **none**. A blank row earns structural credit for existing at a
position the truth also has, while **line-item F1 is 0.00 in both** — no line
item was read either way. The 2048 run was also **worse** where it counts: two
hallucinated fields against zero, including `receipt.date = '03-75-26'` against a
truth of `2026-03-28`. At 768 the model correctly left the date null.

`currency: PHP` in both runs is `DEFAULT_CURRENCY` filling an empty field, not a
value read off the image. Do not count it as a read.

**Verdict: `granite3.2-vision:2b` is not a primary, and 2048 is not worth its
cost.** Weights decide comprehension, so no machine changes this.

#### Two claims above are falsified by this run

**1. "Granite reads nothing" is too strong.** Its *triage* pass returned
`merchant_name_guess='SUMMIT FUEL OPC'` — exactly `merchant.name` in
`eval/golden/labels/r002.json` — **at both resolutions**. The verdict was formed
from the extraction alone; nobody had read the triage guess. **ADR-0043's
founding premise, from which its decision 1 explicitly follows, is narrower than
written**, and that ADR now carries its own dated correction.

**2. The 2026-07-29 timing table below does not reproduce, in either direction.**
Recorded triage @2048 887 s → measured **553 s**. Recorded extract @768 1057 s →
measured **2121 s**. The 768 run came out *slower overall* than the 2048 run,
which nothing here explains. **No timing argument from that table should be
relied on**, including the claim that 2048 cannot complete on this box. What
actually stopped it was `VLM_TIMEOUT_S` at 900 s sitting just under an 887 s
triage — a config value, not a hardware limit.

#### What this does NOT establish

- **Any accuracy claim.** One receipt, one model, one machine, and ADR-0039
  governs: this is a liveness and legibility check. Three golden receipts could
  not carry an accuracy claim even if all three had run.
- **That resolution never matters.** It did not matter *for this model on this
  receipt*. A model that can actually read may behave differently.
- **That the two-tier plan changes.** Ollama Cloud as the tier that does the
  reading is untouched by this, and is better motivated by it rather than worse.

### Measurement (2026-08-18) — step 4 is answered, and the answer is DO NOT enable it

**Step 4 of the ordered plan above — "Set `VLM_USE_TOOLS=true`" — has now run.
The `/v1` shim accepts a `tools` payload, and enabling it is still the wrong
action for the local path.**

Method: `scripts/try_one_receipt.py r002 --max-edge 768`, `VLM_TIMEOUT_S=5400`,
same commit, same scorer. **`VLM_USE_TOOLS` is the only variable** against the
768 control recorded above. Three things were checked before the run so it could
not pass or fail vacuously:

- **The flag reaches the object that builds the request.** `make_client(Settings())`
  under the env var yields `OpenAICompatClient` with `client.use_tools is True`,
  read off the instance rather than inferred from the environment.
- **No response cache is in play.** `scripts/try_one_receipt.py` passes none and
  `triage`'s `cache` parameter defaults to `None`, so every call is a real one. A
  cache hit would have returned the previous run's answer without ever sending a
  `tools` payload.
- **`temperature` is 0.0**, defaulted at `OpenAICompatClient.__init__` and sent
  in the payload, so the differences below are not sampling variation.

**1. No 400.** ISSUE-001's stated fear — a hard 400 on the first (triage) call —
does not reproduce. Ollama's OpenAI-compatible endpoint honoured the payload for
this vision model.

**2. The extraction is IDENTICAL**, not merely equal-scoring: every field null,
zero line items, `currency: PHP` from `DEFAULT_CURRENCY`, and **the same 24
entries in the mismatch list**.

| | tools OFF | tools ON |
|---|---|---|
| transcription accuracy | 11.11% (2/18) | 11.11% (2/18) |
| core | 15.38% (2/13) | 15.38% (2/13) |
| line items | 0.00% (0/5) | 0.00% (0/5) |
| hallucinated / correctly empty / structural | 0 / 12 / 5 | 0 / 12 / 5 |
| line-item F1 | 0.00 | 0.00 |

**3. Triage DEGRADES, and in the field the rest of the system depends on.**

| triage field | tools OFF | tools ON | golden |
|---|---|---|---|
| `is_receipt` | False ✗ | True ✓ | it is a receipt |
| `legibility` | fair ✓ | good ✗ | `fair` |
| `est_items` | 1 ✓ | 0 ✗ | 1 line item |
| `merchant_name_guess` | `SUMMIT FUEL OPC` ✓ | **empty ✗** | `SUMMIT FUEL OPC` |
| `document_type` | handwritten_receipt | pos_receipt | label: "pre-printed form, handwritten values" |

One field improves; three regress. **The decisive one is `merchant_name_guess`**:
`lookup(session, name_guess)` keys off it, so it is the entry point of Phase 6's
whole hint-retrieval path (ADR-0043 decision 1). Enabling tool-use would
silently disable the one thing this model does reliably well.

**Verdict: leave `_TOOLS_OFF_BY_DEFAULT` containing `ollama`.** It is correct for
a reason none of the three previously written beside it: not the capability
claim (false — see the correction above), not the hard 400 (does not reproduce),
but measured output.

**4. It was much faster, and that is reported with its caveat.** Extract 386 s
against 2121 s; whole run 11.0 min against 39.3 min. Constrained generation
emitting fewer tokens is the obvious explanation and **is a hypothesis — token
counts were not measured.** Timings on this box are also not reproducible (see
the previous section), so one run is one run. It is largely moot: a model that
reads nothing faster still reads nothing.

#### A standing decision now conflicts with a measurement

**ADR-0002 and the steering rules make tool-use structured output a
non-negotiable**, and on the only model in play it costs the merchant guess and
buys nothing. That conflict is **recorded, not resolved** — it needs a user
ruling. It is written here so a future session reading the non-negotiable does
not simply flip the flag.

#### What this does NOT establish

- **Anything about a Cloud-tier model.** The shim is the same; the model is not.
  A model that can actually read may well do better with a schema than without,
  which is the usual case and the reason the non-negotiable exists.
- **Any accuracy claim.** One receipt, one model (ADR-0039).
- **That tool-use causes the speedup.** Correlated in one run, mechanism unmeasured.

### Measurement (2026-08-18) — step 3 is answered, and BOTH answers are yes

**Step 3 asked two unverified things about Ollama Cloud: whether a strong enough
vision model is offered, and whether it accepts a `tools` payload. Both are yes,
on the free tier.** This is the first time since 2026-07-28 that a path to a
real accuracy number exists.

Signed in as `charlesyyyu2622`. **The daemon runs in Docker** (container
`ollama`, `ollama/ollama`, host `11435` → container `11434`, named volume at
`/root/.ollama`), so `ollama signin` has to happen **inside the container** —
`docker exec -it ollama ollama signin`. Signing in on the Windows host
authenticates a CLI that serves nothing; the host CLI cannot even see the daemon,
because it defaults to port 11434 where nothing listens.

**A vision-capable cloud model, reachable and free: `gemma4:cloud`.**

| model | vision | pull | inference |
|---|---|---|---|
| `gemma4:cloud` | yes | ok | **works, free tier** |
| `qwen3.5:cloud` (397B) | yes | ok | **402 — "requires a subscription"** |
| `kimi-k2.6:cloud` | yes | ok | **402 — "requires a subscription"** |

**The paywall is per model, not blanket.** A pull succeeds for all three — it
fetches a manifest, not weights — so *pull success is not access*. Only an
inference call distinguishes them, and that is the check to run for any
candidate.

**Tool-use works properly on it**, which is the second question:

    finish_reason : tool_calls
    tool_calls    : [{"function": {"name": "emit_receipt",
                      "arguments": "{\"merchant\":\"ACME\",\"total\":\"12.50\"}"}}]

A real `tool_calls` array with arguments parsed into the requested schema — not
JSON smuggled through `content`. **ADR-0002's tool-use rule is vindicated on a
model that can read**, and its 2026-08-18 correction records the granite
exception as per-model rather than a softening of the rule.

**Nothing was pointed at it.** `.env` still names `granite3.2-vision:2b`;
`VLM_BASE_URL` needs no change, because the local daemon is still the endpoint —
it proxies. Switching is `VLM_MODEL_EXTRACT` / `VLM_MODEL_TRIAGE`, plus
`VLM_USE_TOOLS=true`, and `VLM_TIMEOUT_S` can likely come down a long way.

#### The constraint this uncovered, and it belongs to step 5

**`_TOOLS_OFF_BY_DEFAULT` is keyed on the provider; the exception is per model.**
`granite3.2-vision:2b` and `gemma4:cloud` are both provider `ollama`, so one
`VLM_USE_TOOLS` cannot be off for the local model and on for the cloud one.
Under the two-tier escalation this is a defect in the knob's granularity, not a
preference. Recorded in ADR-0002's correction; **deliberately not fixed**, because
where the decision lives is the escalation ADR's business.

#### What this does NOT establish

- **That `gemma4:cloud` reads receipts well.** It has not seen one. Everything
  above is capability and access, not accuracy.
- **That the free tier is adequate.** Rate limits, quotas and whether a full
  baseline run completes on it are all unmeasured.
- **Anything about cost or data handling.** A cloud tier sends receipt images
  off this machine, which the local-only setup did not. That is a decision, not
  a detail.

### Measurement (2026-08-18) — `gemma4:cloud` READS THE RECEIPT

**User ruling first: receipt images may go to Ollama Cloud for the GOLDEN SET
only, for now.** Production upload routing is a separate decision and has not
been made. The golden labels are already committed to a public repo, so the
incremental exposure is the image rather than new data.

`scripts/try_one_receipt.py r002 --max-edge 2048`, `VLM_MODEL_EXTRACT` and
`VLM_MODEL_TRIAGE` both `gemma4:cloud`, `VLM_USE_TOOLS=true` (ADR-0002's rule,
applied to a model that can read).

```
[triage]  12s   is_receipt=True  type=handwritten_receipt  est_items=3
                merchant_guess='SUMMIT FUEL OPC'
[extract] 13s
  merchant   : SUMMIT FUEL OPC          tax_id : 774-423-646-00011
  invoice no : 18241                    date   : null  raw=03-28-26
  line items : DieselPlus  qty=17.39  price=115.0  total=2000
  totals     : subtotal=1785.71  tax=214.29  total=2000
  payment    : CASH                     handwritten=True
VALIDATION errors=0 warns=0        CONFIDENCE 0.700 -> needs_review
```

**Merchant name, TIN, invoice number, the real line item, both totals and the
payment method are all exactly right.** `1785.71 + 214.29 = 2000.00` — internally
consistent. Against granite on the same receipt: **25 seconds against 30–39
minutes**, transcription **61.11% against 11.11%**, core **76.92% against
15.38%**, validation **0 errors against 2**, confidence **0.700 against 0.000**.

**ADR-0043's TIN-first design is now live rather than hypothetical.** The
strongest fingerprint on this corpus was read exactly, which is the premise
decision 1 was built on and could not previously be exercised.

#### THE FINDING THAT MATTERS MOST: cloud inference is NOT deterministic at temperature 0

The run was executed twice, identically, by accident. **The two disagree:**

| | run 1 | run 2 |
|---|---|---|
| transcription accuracy | 55.56% (10/18) | 61.11% (11/18) |
| core | 69.23% (9/13) | 76.92% (10/13) |
| hallucinated | 10 | 9 |
| structural mismatches | 15 | 12 |
| `totals.subtotal` | *not extracted* | `1785.71` |

Same model, same image, same prompt, `temperature: 0.0` in the payload. The
local path was stable across repeats; this is not. Distributed inference —
batching, routing, mixed hardware — is the obvious explanation and **is not
measured here**. Three consequences, none of them optional:

- **A single-run baseline is not a number, it is a sample.** Any accuracy figure
  from the cloud tier needs repeats and a spread, or it will move on its own and
  be read as a regression. This would have silently corrupted the first real
  baseline (step 6).
- **`ResponseCache` assumes determinism.** Its docstring says "Only cache
  temperature==0 calls", whose justification is that such calls are reproducible.
  That premise does not hold for this tier.
- **Phase 7 self-consistency gets stronger, not weaker.** Sampling the same
  prompt and reconciling is exactly the remedy for this, and it was designed for
  handwriting rather than for provider nondeterminism.

#### Two things that look like defects and are not

- **`date` is null and that is CORRECT.** The printed date is `03-28-26`, which
  is genuinely ambiguous between MM-DD-YY and DD-MM-YY. The system's rule is null
  over confident-wrong; `date_raw` keeps the string and R011 fires as *info*.
  **But "critical fields (merchant+date+total) all correct" counts it as a
  miss**, so the headline gate penalises the pipeline for behaving correctly.
  That is a metric question in the same family as ADR-0040, not a model failure.
- **`MaxiPower` and `MaxiGreen` are the known pre-printed template rows.** The
  golden label's own notes say they "are blank template rows and must NOT be
  emitted as line items". The model emitted them, which is why line-item
  precision is 0.33 while **recall is 1.00** — it found every real item and
  added two phantoms. This is the open item in the prompt's §6 (sibling of
  R052), now **reachable and reproducible** for the first time.

#### What this does NOT establish

- **Accuracy.** One receipt of three, and now demonstrably variable between runs.
- **That the free tier survives a real workload.** Rate limits, quotas and
  concurrency are unmeasured; two calls is not a baseline.
- **That production uploads may use it.** The ruling above is golden-set only.

### Goal

Run `python -m eval.run_baseline` over the three hand-verified golden receipts and
get the six §16 metrics. Everything needed for this is in place: the labels, the
images, the pipeline, the scorer, and the harness. The run itself has not
succeeded.

### What happened

**Attempt 1 — 14:40, died on receipt 1.**
`VLMTransientError: connection: Request timed out.`
The client used the openai SDK's own 180s default while a single triage call takes
~262s. Root cause: `VLM_TIMEOUT_S` was declared in `Settings` but **never passed to
the client constructor** by the factory — the same shape of bug `VLM_BASE_URL`
once had. **FIXED** in `1f9f122`; the configured timeout now reaches the client
(verified: `client._client.timeout == 900.0`).

**Attempt 2 — 15:22, ran ~65 minutes, then vanished.**
Zero bytes of output, no results file written, process gone. This is the signature
of the process being **killed**, not failing: an unhandled exception would have
printed a traceback, and the harness fix in `1f9f122` would have recorded a
per-receipt failure and still written a report. Most likely the background process
was torn down when a long foreground wait was interrupted.

### Measured end-to-end run (2026-07-29, r002 via `scripts/try_one_receipt.py`)

The pipeline **does work end to end** — but the local model cannot read the
receipt. Timings on this hardware (CPU-only):

| image `max_edge` | base64 | triage | extract | total |
|---|---|---|---|---|
| 2048 (default) | 745 KB | **887 s** | timed out at 900 s, then retried | never finished |
| 768 | 129 KB | **314 s** | **1057 s** | ~23 min |

At 2048px, triage alone (887s) sits *just under* the 900s timeout — which is why
the earlier baseline attempts died. At 768px it completes, but
`resize_for_model` correctly warns `estimated text height 7.7px is below 12px`,
and the extraction comes back effectively empty: every field null, two blank line
items.

**The safety machinery behaved exactly as designed on that bad extraction** —
R010 ERROR (total is null) plus R011/R012/R053 warnings, confidence `0.000`,
routed `needs_review` at priority 0 (urgent). It did not auto-approve garbage.
Scored against the golden label: critical fields correct = False, line-item
F1 = 0.00. So the infrastructure is validated; the *model* is the problem.

### Root cause still open

**`granite3.2-vision:2b` on CPU is too slow, and too weak, to iterate against.** A 3-receipt baseline is 6+ calls (triage + extract per
receipt, more if a repair fires), so ~30–60 minutes per run — and the eval harness
is meant to be re-run on *every* prompt, model, or rule change (§16). Two
consequences:

1. Each run is long enough that an interruption kills it before it finishes.
2. Even when it works, the iteration loop is impractical.

Secondary: the local path runs in JSON mode rather than schema-constrained
tool-use (handled by `VLM_USE_TOOLS` / the provider default in
`factory.py`, but it means the local run is not exercising the intended
structured-output path — see ADR-0002 and the steering rule "structured output via
tool-use, not 'reply in JSON'").

*(Corrected 2026-08-21.)* This sentence opened "Ollama rejects a `tools` payload
for models that do not declare the capability". It does not — see
**Measurement (2026-08-18) — step 4 is answered** above, finding 1, and
ADR-0002's 2026-08-18 correction. The clause is deleted rather than reworded;
the reason the provider default stays off is in that measurement's verdict.

### Recommended fix — SUPERSEDED 2026-08-14 by the ruling at the top

*(Kept as the record of what was diagnosed and tried. **Do not act on it**: the
user has ruled Ollama-only. The security note at the end of this section still
stands — that key needs revoking whether or not it is ever used.)*

**Point the baseline at a hosted, tool-capable model.** `.env` already has a
commented-out Gemini block using the OpenAI-compatible endpoint:

```
VLM_PROVIDER=openai
VLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
VLM_API_KEY=<a fresh key>
VLM_MODEL_EXTRACT=gemini-3.5-flash
VLM_MODEL_TRIAGE=gemini-3.1-flash-lite
```

This turns 30+ minutes into well under a minute and exercises real tool-use.
Keep the Ollama config commented alongside it for offline/zero-cost spot checks —
the provider abstraction (ADR-0002) means switching is one env var.

> **SECURITY:** the Gemini key currently sitting commented-out in `.env` was
> echoed in terminal output during this session. **Rotate it before use.** `.env`
> is gitignored, so it was never committed.

**Alternatives if staying local:**
- Run one receipt at a time — `run_baseline(golden_dir=...)` accepts any directory
  with a `labels/` + `images/` pair, so a single-label dir works.
- Let it run uninterrupted and accept 30–60 min. Start it detached, and do not
  block the session on a foreground wait.
- Try a larger/faster local vision model that declares tool-use support
  (Qwen-VL class), or run Ollama with GPU acceleration.

### Readiness check, 2026-08-11 — everything but the key

*(**The hosted-wiring row below is superseded 2026-08-14 — Ollama only.** The
measurement stands: the OpenAI-compatible client does build against a hosted
`base_url`. It is simply no longer a path this project will take. Every other
row still applies, and two of them matter more than ever under the ruling:
`DEFAULT_CURRENCY=PHP` is correct, and the golden set is three labels.)*

Re-run of the resume steps that do not need a provider. **Only step 1 is
outstanding, and only a human can do it.**

| checked | result |
|---|---|
| current config | **still local**: `VLM_PROVIDER=ollama`, `granite3.2-vision:2b`, `VLM_TIMEOUT_S=900`. The hosted block is still commented out. |
| `DEFAULT_CURRENCY` | `PHP` — already correct, per step 1's warning |
| hosted wiring (step 3) | **works.** With the Gemini env block and a dummy key, `make_client` builds an `OpenAICompatClient` at the right `base_url` |
| `VLM_TIMEOUT_S` reaches the client | **yes** — 120.0 s. Attempt 1's root cause is genuinely fixed, not just believed to be |
| `use_tools` on the hosted path | **True** — so the run exercises real tool-use, closing the "Secondary" gap above |
| golden set | 3 labels, 3 images; **all three still validate with zero findings**, so the precondition under "What to expect" still holds |

No network call was made: the `openai` constructor does not touch the network,
so this proves wiring, not reachability. **The key is the only remaining
variable** — a valid key turns this from unverified to running.

**The compromised key was NOT echoed again** during this check. Configuration
presence was reported as a boolean.

### The local path, re-measured 2026-08-11 — it got WORSE

The user chose to stay on Ollama, so the "alternatives if staying local" above
were run rather than argued about. **One receipt (`r001`), 768px, detached,
`VLM_TIMEOUT_S=1800`** so a slow extract could not time out and burn a retry.

| | July (this issue, above) | **2026-08-11** |
|---|---|---|
| one receipt at 768px | ~1371 s (~23 min) | **1896 s (31.6 min)** |

**~38% slower than July, on the same model and the same image.** Not explained
here — Ollama moved to 0.32.4 and nothing else about the box is known to have
changed. Recorded as a measurement, not a diagnosis.

What the run produced:

```
Receipts: 1   Auto-approved: 0   Critical-correct: 0   Failed: 0
Auto-approval precision:  n/a      Critical-field accuracy: 0.00%
Field accuracy:        45.00%      Line-item F1:            0.00%
confidence 0.000, critical_correct false, fields_correct 18 / 40
```

**`Failed: 0` is the good news and the whole of it:** the pipeline completes end
to end against a real provider. Everything else says the model cannot read the
receipt — confidence `0.000`, no critical field right, no line item found.

**Do not read 45% as "nearly half right".** As this issue's own side-findings
note, `field_accuracy` counts `meta.*` — annotator prose and model self-reports
— and a field that is null in both label and extraction scores as correct. The
number is dominated by agreeing-about-nothing.

**The GPU finding is current, not inherited.** Ollama ran discovery on
2026-08-11 and reported `library=cpu … total "7.6 GiB" available "7.2 GiB"` with
no device, and `/api/ps` showed `size_vram=0` while the model was loaded. CPU-only
is measured today, not assumed still true from July.

**Not committed to `eval/results/`.** One receipt, at a non-default resolution,
from a model that read nothing, would be the *first* artefact in that directory
and would sit beside future real baselines as though comparable. It lives in
`var/` (gitignored). §16 wants results committed so regressions show in a diff;
this is not a result, it is a liveness check.

### A third local option this issue did not have: Ollama Cloud

`ollama signin` **exists in the installed build** (0.32.4, verified via
`ollama --help`), and the server already reports `OLLAMA_NO_CLOUD:false` with
`OLLAMA_REMOTES:[ollama.com]`. That makes "stay on Ollama, stop paying the CPU
cost" a real option rather than a hypothetical, and it needs no code change —
`VLM_PROVIDER=ollama` with the same `base_url`, a cloud model tag, and
**`VLM_USE_TOOLS=true`** to override `_TOOLS_OFF_BY_DEFAULT`, which otherwise
silently keeps this provider in JSON mode (the "Secondary" finding above).

Untested here: no account was created, so whether a suitable vision model is
offered and whether it accepts a `tools` payload are both unverified.

### How to resume (exact steps)

1. ~~Rotate the Gemini key; put the hosted config in `.env` (block above).~~
   **SUPERSEDED 2026-08-14 — Ollama only.** Replace this step with: settle the
   runtime question in the ruling at the top, then pull a document-capable
   vision model to replace `granite3.2-vision:2b`, which is the single largest
   cause of zero accuracy. **Never set `VLM_USE_TOOLS=true` on its own** —
   `factory.py`'s `_TOOLS_OFF_BY_DEFAULT` contains `ollama`, so the local path
   runs in JSON mode rather than schema-constrained tool-use, against ADR-0002
   and the steering rule, and this step said exactly "Set `VLM_USE_TOOLS=true`"
   until 2026-08-21. Under the per-pass ladder that advice is **actively harmful
   taken alone**: `VLM_USE_TOOLS` is the whole-process default, so it turns tools
   on for the *triage* rung too, where `granite3.2-vision:2b` is measured above
   to lose `merchant_name_guess` entirely — the field ADR-0043 decision 1's hint
   path keys off. Pair it with the per-rung settings the local→Cloud escalation
   milestone added:
   * `VLM_USE_TOOLS=true` **plus `VLM_USE_TOOLS_TRIAGE=false`** — tools on for
     the extract rungs, held off for triage. There is no separate setting for
     the *first* extract rung, so this pairing is how it is reached;
   * `VLM_USE_TOOLS_FALLBACK=true` alone — tools on for the second extract rung
     only, leaving triage and the first rung at the provider default.
   **Revoke the old Gemini key anyway** — it was echoed to a terminal and this
   repo is public.
   Keep `DEFAULT_CURRENCY="PHP"` — BIR invoices never print a currency, and
   without it currency resolves to null on every receipt.
2. `VLM_TIMEOUT_S` stays high for a local model. It is `900` now; a bigger model
   on two CPU cores may need more, and Attempt 1 of this issue died because a
   timeout was too short rather than too long.
3. Sanity-check the wiring before a full run:
   ```
   python -c "from config.settings import Settings; from receipts.extract.clients.factory import make_client; s=Settings(); c=make_client(s); print(s.vlm_provider, s.vlm_model_extract, float(c._client.timeout))"
   ```
4. Time a single call first, so a slow provider is caught in one call, not six:
   `triage(prepare_image(Path('eval/golden/images/r001.jpg')), client)`
5. Then the full run: `python -m eval.run_baseline`
   (writes `eval/results/{date}-{PROMPT_VERSION}.json` and prints the §16 table).
6. Commit the results file — §16 requires results be committed so regressions show
   up in a diff, grouped by `prompt_bundle_hash()`.

### What to expect, and what would be suspicious

- The three labels currently validate with **zero** findings, so any ERROR in the
  run comes from the *model's* extraction, not from the rules.
- `is_receipt` came back **false** for a valid invoice on the local model. Nothing
  reads that field yet (grep: no consumers in `src/`), so it is harmless today —
  but the §3 "reject garbage before you pay for extraction" gate does not exist,
  and when it is built it must **not** hard-reject on a small model's `is_receipt`.
  Route to review instead; nothing is ever silently dropped.
- Two traps the local model *did* get right, and worth confirming on the hosted
  one: it named the merchant (`METRO OIL SUBIC INC.`) rather than the buyer
  (`Ideal Source`), and it counted **1** line item rather than all six pre-printed
  fuel rows.
- Confidence/auto-approval numbers are meaningful now (real scoring is wired in),
  but the ≥99% precision target **cannot be validated on three receipts** — treat
  the first run as a smoke test plus a directional read, not a calibration.

### Two side-findings from the smoke run

**`is_receipt` came back `false` for a valid invoice on both receipts tried**
(r001 and r002). Nothing reads that field yet — grep finds no consumers in
`src/` — so it is harmless today, but the §3 "reject garbage before you pay for
extraction" gate does not exist. When it is built it must **not** hard-reject on a
small model's `is_receipt`; route to review instead (nothing is ever silently
dropped).

**`field_accuracy` counts fields the model cannot possibly match.** The flattened
comparison includes `meta.*`, so the annotator prose in a golden label's
`meta.notes` is scored against whatever the model wrote, and `meta.legibility` /
`meta.is_handwritten` are model self-reports rather than facts about the receipt.
On the smoke run these were among the 27 mismatches. Consider excluding `meta.*`
(or at least `meta.notes`) from the field-accuracy denominator so the number
reflects transcription, not annotation. Until then, read per-field accuracy as
slightly pessimistic.

> **Correction, 2026-08-12 — the diagnosis stands, the remedy was refuted.**
> Measured before acting on it (ADR-0030). Excluding `meta.*` moves the floor an
> empty extraction reaches from 42.50% to 39.39% on r001, and on r003 from
> 36.59% to 36.36% — **0.22 points**. Excluding only `meta.notes` **raises**
> every floor, because `notes` is a path an empty extraction *fails*, so
> dropping it removes a penalty rather than a gift. The real driver was
> agreement about absence: of r001's 17 free points, 12 were **non-`meta`** paths
> where neither side was filled — fields the receipt does not have. (The
> qualifier matters: without it the count is 14, because two `meta.*` paths are
> `[]` on both sides, and those two are already counted among the `meta.*`
> self-reports resting at their schema defaults.) **ADR-0040** is what shipped
> instead: metric 4 became a set of ratios and counts over one classifier that
> reads *filled* from the truth side only — its decision 2 is where they are
> named. Its probe re-derives every figure in this note.
>
> The last sentence above — "read per-field accuracy as slightly pessimistic" —
> was the reading under the old scalar and is left as the record of what was
> thought. Under `transcription_accuracy` it no longer holds: the floor is
> ~5.9%, not ~40%.

### Related

- `docs/MEMORY.md` — "The real receipt corpus" (why this corpus is unusual) and
  the deferred-task list.
- ADR-0002 (provider abstraction / runtime config), ADR-0003 (confidence).
- `.superpowers/sdd/progress.md` — the full session-by-session trail.

---

## ISSUE-002 — A repair attempt's recorded `prompt_hash` names a prompt that was never sent

**Status:** OPEN — deliberately not fixed. The one-line code change is not the
hard part; see "Why it is not being fixed".
**Owner action required:** yes — the migration decision, not the code.
**Discovered:** 2026-08-15, by the Phase 6 merchant-fingerprinting milestone,
which found it and left it alone. **Pre-existing:** present at `8f0b413`, before
that branch existed. **Blocks:** nothing today, because nothing reads the column
(below). It makes every historical repair row's `prompt_hash` unusable as an
audit key the day something does.

### What is wrong

`receipts.extract.extractor.repair()` sends the repair text as `user` and the
extraction system prompt as `system`:

```python
user = P.build_repair_prompt(previous, report.render_for_repair_prompt())
return client.complete_json(system=P.SYSTEM_EXTRACTION, user=user, ...)
```

`receipts.pipeline._attempt_prompt_hash` rebuilds that prompt to fill
`extraction_runs.prompt_hash`, and its repair branch hashes the `user` half
alone while the extract branch four lines below appends the system half:

```python
if attempt.pass_name == "repair":
    previous = attempts[attempt_number - 2]
    return P.prompt_hash(
        P.build_repair_prompt(
            previous.extraction, previous.report.render_for_repair_prompt()
        )
    )
return P.prompt_hash(
    P.build_extraction_prompt(triage_result, hints, few_shots or [])
    + P.SYSTEM_EXTRACTION
)
```

So for every `pass_name='repair'` row in `extraction_runs`, the stored 16-char
hash is the hash of a string no provider ever received.

**`re_extract` is correct.** The branch tests the literal `"repair"`, and a
re-extract attempt (`extractor.py`'s `pass_name = "re_extract"`) therefore takes
the extract branch, which appends the system prompt.

This is the same class as ADR-0043 decision 8 — *whatever conditions the prompt
must also condition the recorded hash* — in the same function, but it is not that
branch's doing.

Re-derivable:

```
git grep -n "SYSTEM_EXTRACTION" -- src/receipts/extract/extractor.py
    -> 3 hits: the extract cache key (~145), `system=` on the extract call
       (~152), `system=` on the repair call (~181). Both calls send it.
git grep -n "prompt_hash" -- src eval frontend scripts
    -> no hits outside `src/`. Inside it the column is written by
       `repository.save_extraction_run` and read back by nothing:
       `ResponseCache.key` computes its own hash from the prompt in hand, and
       `registry.few_shots_for` — the one place that queries `ExtractionRun` —
       reads `raw_response` off the row and never touches `prompt_hash`.
```

### Why it is not being fixed

Appending `P.SYSTEM_EXTRACTION` to the repair branch is one line. Its consequence
is not: every repair row already written carries the old hash, so the fix splits
the audit trail into two hashes for one prompt with nothing recording which
scheme a given row used. Leave them, backfill them, or version the scheme — that
is a migration-shaped decision about the audit contract, and it belongs to
whoever owns that contract rather than to a fix wave passing through.

### How to resume (exact steps)

1. Settle the question above: what happens to the repair rows already stored.
2. Append `+ P.SYSTEM_EXTRACTION` in the repair branch of
   `pipeline._attempt_prompt_hash`, exactly as the extract branch does.
3. Pin it the way the extract side is already pinned.
   `tests/test_pipeline_merchant_hints.py`'s
   `test_the_recorded_hash_describes_the_prompt_that_was_actually_sent` asserts
   the stored hash equals `P.prompt_hash(user_sent + system_sent)` for the
   `(system, user)` pair a recording client was **actually handed**. A repair-pass
   twin of that test is the proof; a test that rebuilds both sides the same way
   proves nothing.

### The related divergence: eval extracts unhinted

`run_receipt` — the `build_eval_pipeline` path — calls `extract_with_repair`
with no `hints` and no `few_shots`, so **eval measures a different prompt than
production sends.** Nothing is persisted on that path (it takes no session) and
`prompts.prompt_bundle_hash()` hashes only the static templates, so eval
*grouping* is unaffected and no committed baseline is wrong today. It will matter
the moment ISSUE-001's baseline runs: the accuracy figure will describe the
unhinted prompt while `process_receipt` sends the hinted one, and nothing in the
results file says so.

### Related

- ADR-0043 decision 8 (whatever conditions the prompt conditions the hash) and
  decision 6 (tier-dependent conditioning).
- ISSUE-001 — the baseline run that turns the eval divergence above from a note
  into a wrong number.

---

## ISSUE-003 — A blank pre-printed row drops the unit the form prints on it

**Status:** OPEN — deliberately not fixed. The fix is in `schema.py` or
`prompts.py`, both closed when this was found.
**Owner action required:** yes — whether a template row should carry `unit`
at all. Until that is answered the labelling rule below stands.
**Discovered:** 2026-08-18, labelling the golden set for the buyer-and-blank-rows
milestone, by reading `eval/golden/images/r001.jpg`. **Pre-existing:** the
contract gap arrived with `is_template_row` itself. **Blocks:** nothing today.

### The labelling rule, so nobody has to re-derive it

**A row with `is_template_row: true` carries its printed product name and
nothing else. `unit` is `null` on a flagged row even when the form pre-prints
one.**

That is the rule. The rest of this entry is why, and is not needed to follow it.

### What is wrong

`LineItem.is_template_row`'s schema description — which ships to the model —
scopes a blank row to one field: "the row itself is still checked, so
transcribe the printed product name". Prompt rule 9 enumerates the same
shape: printed name in `description_raw`, `is_template_row = true`, and
`qty`, `unit_price` and `line_total` null. Neither mentions `unit`, and
`LineItem.unit` has no `description` at all, so nothing reaches the model
about it in either channel.

The paper says otherwise. `eval/golden/images/r001.jpg` pre-prints `Lt.` in
the Unit column against **all six** product rows, including the five that were
never written in. `eval/golden/labels/r001.json` records that fact in
`meta.notes` and leaves `unit` null on the five flagged rows, while the one
filled row (CLEAN DIESEL) carries `unit: "Lt."`. So identically-printed
content is treated two ways inside one file.

### Why it is not being fixed

Labelling `unit: "Lt."` on the five flagged rows creates **five permanently
unearnable transcription paths**: the shipped contract never asks for the
field on such a row, so a model that does everything it is told still loses
them. That is the same punish-a-correct-model defect the golden labels were
just corrected to remove, rebuilt on a new axis. Between an incomplete label
and a label that penalises correct behaviour, the milestone chose incomplete
and wrote the observation into the notes so the gap is visible.

### It is unguarded, and that is the risk

Nothing fails if somebody "fixes" the inconsistency the wrong way. Setting
`unit: "Lt."` on all five flagged rows leaves the whole suite green. The
argument FOR the edit is in the tracked tree (r001's note about the six
pre-printed `Lt.`s); this entry is the only record of the ruling against it.

### How to resume

1. Decide the contract question: does a blank pre-printed row transcribe every
   pre-printed cell on that row, or only the product name?
2. If every cell: give `LineItem.unit` a `description`, extend prompt rule 9
   to name it, then relabel r001's five flagged rows — in that order, so the
   paths become earnable before they become truth.
3. If only the product name: nothing to do in code. Consider saying so in
   `is_template_row`'s description, so the next labeller does not have to find
   this entry.

### Related

- `eval/golden/labels/r001.json` — `meta.notes` records the six pre-printed
  `Lt.`s; the five flagged rows leave `unit` null.
- ISSUE-004 — why re-reading the image is the only instrument that would have
  found this in the first place.

---

## ISSUE-004 — Nothing checks a label against its photograph, and per-label rot is open by design

**Status:** OPEN — structural, not a defect to fix. Recorded so the pins are
not mistaken for something they are not.
**Owner action required:** no.
**Discovered:** 2026-08-18, when a printed-order defect in `r001.json` and
`r002.json` was caught by a human reading a plan against the images — not by
any test. **Pre-existing:** since the golden set existed. **Blocks:** nothing;
it bounds what green means.

### What is wrong

`eval/golden/images/` is gitignored — receipts carry PII — so the labels are
the only tracked artefact and **no test can compare a label to the paper it
describes.** A transcription that is simply wrong is invisible to CI at any
level of effort.

The pins added in `tests/test_eval_floor.py` do not change this, and are not
meant to. Their job is to make **wholesale rot and schema drift loud**, not to
establish truth:

- `test_a_label_declares_every_field_the_schema_declares` — a schema field the
  labels never picked up. Covers `TEMPLATE.json` too, because the README tells
  labellers to copy it.
- `test_every_flagged_row_carries_a_printed_name_and_no_amounts`
- `test_at_least_one_label_records_a_buyer_name`
- `test_array_order_agrees_with_the_position_values`

### The residual, measured

**A single label's content rotting alone stays green — but the mutation has
to be tidy about it.** Re-measured 2026-08-19, the suite now being 1236 tests:

- Blanking `r001.json`'s buyer block and deleting all five of its flagged rows,
  leaving r002 and r003 untouched, gives **1 failed, 1235 passed**. The failure
  is `test_array_order_agrees_with_the_position_values[r001]`: the deletion
  leaves `CLEAN DIESEL` alone in the array carrying `position: 3`, so positions
  `[3]` no longer match indices `[0]`.
- Renumbering that survivor to `position: 0` — one more edit, and the one a
  careful vandal or a careless script would make — gives **1236 passed**. P1
  still sees every declared field, P2 still finds flagged rows in r002, and P3
  still finds a buyer name in r002 and r003.

So the residual is real and the entry stands; the array-order pin narrows it by
one step rather than closing it.

**This paragraph said "passes the full suite, 1228 tests" until 2026-08-19, and
that was wrong when it was written, not rotted.** The array-order pin landed at
`6169893` five minutes before `b3868e8` wrote this entry, and the entry lists
that pin among the four above — so the mutation was not re-run against the tree
being described, and the count came from an earlier one. It is exactly the
failure ADR-0028 names: a measurement quoted rather than re-derived, inside a
section headed *measured*.

The residual is by design. The alternative is a test that transcribes r001's
rows, which would fire on a legitimate re-read of the image and become an
obstacle to truth rather than a guard on it.

### How to resume

There is no code change that closes this. What would help, in rough order of
cost:

1. Treat any label edit as needing the image re-read, and say which image was
   read in the commit message — the convention this milestone started.
2. Record per-receipt evidence in `meta.notes` when it is a reading of the
   paper (paper order, pre-printed units, printed phrases like
   "Total Sales (VAT Inclusive)"), so a later reviewer can audit without the
   photograph.
3. If the corpus ever reaches its 50–100 target, a second labeller
   independently re-reading a sample is the only real instrument.

### Related

- ISSUE-003 — found only by reading the image; unguarded for the same reason.
- ISSUE-005 — the production-side ordering guard that does not guard.

---

## ISSUE-005 — R051's message promises printed order; its check accepts any permutation

**Status:** OPEN — deliberately not fixed. `src/receipts/validate/rules.py` was
closed when this was found.
**Owner action required:** no — the fix is small and uncontroversial, it simply
had no owner in this milestone.
**Discovered:** 2026-08-18, while pinning the golden labels' array order.
**Pre-existing:** yes, since R051 was written. **Blocks:** nothing today; it
means one operator-facing sentence is not true.

### What is wrong

R051 tells the operator:

```
Line item positions are {positions}, expected {expected}. Positions must be
0-based, contiguous, and in printed order.
```

Its check is:

```python
positions = [i.position for i in r.line_items]
expected = list(range(len(positions)))
if sorted(positions) == expected:
    return []
```

`sorted()` discards order, so **every permutation passes.** Only gaps,
repeats and off-by-one bases are caught. The third clause of the message —
"and in printed order" — is enforced by nothing.

Verified 2026-08-18 on `eval/golden/labels/r001.json` with its array slots 0
and 3 swapped and each row keeping its own `position` value, so the list reads
`[3, 1, 2, 0, 4, 5]`: `validate()` returns **zero findings at any severity**.

This matters because `field_accuracy` joins `line_items[i]` by **array index**
while `position` is what a human reads. When the two disagree, every field of
both rows is scored against the wrong row, silently.

### What is already guarded, and what is not

The golden labels are now covered by
`tests/test_eval_floor.py::test_array_order_agrees_with_the_position_values`,
which fails on exactly the mutation above. **That pin covers the labels and
`TEMPLATE.json` only.** An extraction coming out of the pipeline is checked by
R051 and by nothing else, so the gap is open on the production path.

### How to resume

1. In R051, compare `positions == expected` rather than
   `sorted(positions) == expected`. The message then becomes true as written.
2. Confirm no fixture relies on the looser rule before changing it: a permuted
   extraction that previously validated clean will start producing a finding,
   which is the point, but it is still a behaviour change.
3. Pin it with a permutation, not a gap — a test built from a missing or
   repeated position passes under both implementations and proves nothing.

### Related

- ISSUE-004 — the eval-side half of the same ordering problem.
- ADR-0040 — why `field_accuracy` joins by index.

---

## ISSUE-006 — A reviewer cannot see which rows will vanish from the export

*(Heading kept as written, and it stopped being true on 2026-08-23 — the review
screen now shows the flag and lets a reviewer change it. Citations name the
issue number, not the heading. What survives is the arithmetic residual below,
which the control does not touch.)*

**Status:** OPEN, NARROWED — **the visibility half is CLOSED 2026-08-23** on
`feat/label-provenance-rule`. `LineItemsTable` renders a `Template` column, a
per-row checkbox with the accessible name `Template row {position}`, bound to
`line_items[{position}].is_template_row` and sending the text `_coerce_bool`
reads. **The silent-arithmetic residual below is untouched and is what keeps
this issue open.**
**Owner action required:** no — the ruling was given 2026-08-23: *"I want it to
be editable so if the result is wrong, they can change it."* Read-only was the
alternative and was not chosen.
**Discovered:** 2026-08-19, in the whole-branch review of
`feat/buyer-and-blank-rows`. **Pre-existing:** no — the flag arrived on this
branch. **Blocks:** nothing; it bounds what a reviewer's approval means.

### What was fixed

`is_template_row` is in `_LINE_ITEM_FIELDS`, so a dotted
`PATCH {"line_items[0].is_template_row": true}` returns 200 and flips it —
and `_line_item` (`review/serializers.py`) emitted no key for it, so the value
was correctable and unreadable at once. That is the P5.T3b defect class
(*a reviewer could overwrite what the machine read without ever being shown
it*) one dict over from where it was closed.

`_line_item` now emits the key, and
`test_every_correctable_line_item_column_is_readable_in_the_detail`
(`tests/test_api_read.py`) binds `_LINE_ITEM_FIELDS` to it as a property —
the same binding `test_every_correctable_receipt_column_is_readable_in_the_detail`
already gives `_RECEIPT_FIELDS`. It names the missing column rather than
failing a count, proven by writing it before the key existed.

### What is still open

*(This section read "The review UI does not render the flag" and set out why
making it editable was a separate, unanswered question. **The user answered it
on 2026-08-23: editable.** The original reasoning is deleted rather than kept
with a caveat — ADR-0032's rule for a sentence whose subject is a decision that
has since been taken.)*

**The visibility half is closed.** `LineItemsTable` renders a `Template` column
and a per-row checkbox; a flagged row and a purchased row no longer look
identical, and a reviewer who disagrees with the machine can change it in either
direction. `position` remains the one read-only correctable column, for the
reason recorded in that component: it is the addressing key every other edit
uses.

**Four pins hold it, each proven red by a mutation placed where the component
computes its answer** (ADR-0051): seeding through `String(...)` instead of
`boolText(...)` reddens the null pin with `expected 'null' to be null`; sending
a boolean instead of the text reddens the write-path pin; making the control a
text box reddens both the type assertion *and* the per-row role count; and
dropping the `<th>` reddens the column list. One mutation per run, each
reverted.

**What no pin covers**: nothing joins the editable set to `_LINE_ITEM_FIELDS`,
so this column being offered is a decision recorded in prose, not a property. The
asymmetry is deliberate — `position` is correctable and deliberately not offered
— so an allow-list binding the two sets would be wrong, and the honest statement
is that the UI's choice of columns is unpinned in both directions.

**And a checkbox cannot carry design section 4's null mark**, so an
`is_template_row` of `null` renders identically to `false`: ADR-0027 decision 5's
`null` is not `0` is not empty, defeated by the control type. Found by
`tests/review-null-rule.test.tsx` going red on the new column rather than by
anyone predicting it. **Reported, not fixed** — the shape is pre-existing
(`meta.is_handwritten` and `meta.receipt_is_inconsistent` have had it since the
form was built, and that pin lists them for the same reason), and a tri-state
control is an ADR-0027 decision rather than a repair. The pin now names the two
unmarkable controls explicitly instead of asserting an empty list.

### The residual, measured

**A mis-flagged row is loud only while another purchase survives.** Measured
2026-08-19 with `validate()` over a two-row receipt totalling 1000.00:

| receipt | mis-flag one filled row | finding |
|---|---|---|
| two purchases, subtotal printed | sum short by 400.00 | `R020` **error** |
| two purchases, no subtotal | sum short by 400.00 | `R024` **warn** |
| one purchase, either way | `_purchased` becomes empty | **nothing at all** |

The last row is the one that matters here, and it is the shape the whole
golden corpus has: `sum_line_nets` returns `None` on an empty purchase set, so
`R020.applies` and `R024.applies` are both false and the arithmetic goes
offline rather than firing. Re-measured on the labels themselves — flagging
r001's `CLEAN DIESEL`, r002's `DieselPlus` or r003's `DSL-2` produces **zero
findings at any severity**, because each of the three receipts has exactly one
filled row.

**This is not a pre-existing silence.** At the merge base (`a26d6c1`)
`is_template_row` did not exist, `export/xlsx.py` wrote every line item, and
the labels recorded that blank pre-printed rows "must NOT be emitted as line
items" at all — so no row could vanish, because none was transcribed. The flag
is what makes both the transcription and the vanishing possible, and this
entry is the record that the second half arrived without a way for a reviewer
to see it.

### How to resume

1. Answer the contract question: is the flag *shown* (a marker on the row, so
   an approval means the reviewer accepted the split) or *shown and editable*
   (a reviewer can re-classify a row)?
2. If shown only: render it in `LineItemsTable` as a non-interactive marker.
   No server change — the key is already in the detail response.
3. If editable: it needs a control in `LineItemsTable` and a key in
   `fieldsFromReceipt`, and `test_every_correctable_receipt_path_is_offered_by_the_review_client`
   (`tests/test_repository.py`) — which today binds `_RECEIPT_FIELDS` only and
   says why line items are out of scope — has to grow a line-item half. That
   decision also has to say what happens to `position`, which is correctable
   and deliberately not offered for a different reason.
4. Either way, pin the arithmetic residual above with the **one-purchase**
   shape, not the two-purchase one: a two-row mutation is caught by R020/R024
   already and would prove nothing about the silent case.

### Related

- ISSUE-003 — the other open question about what a flagged row carries.
- ADR-0044 §6 — what the label pins do and do not establish.
- `docs/adr/0016-review-next-resumes-the-callers-task.md` — the P5.T3b defect
  this repeats, and the fix that bound the receipt half.

---

## ISSUE-007 — `PROMPT_VERSION` is unenforced, and no test that fires for the right reason is available

**Status:** OPEN — deliberately not pinned. The reasoning is the point of this
entry; the alternative was a test that reads as a guard and is not one.
**Owner action required:** yes — whether `eval/harness.py` should key results
on `prompt_bundle_hash()` instead of on `PROMPT_VERSION`. That is a change to
the committed-results contract (spec §16), not a bug fix.
**Discovered:** 2026-08-19, in the whole-branch review of
`feat/buyer-and-blank-rows`. **Pre-existing:** yes, since `PROMPT_VERSION`
existed. **Blocks:** nothing today; it means one module rule is honour-system.

### What is wrong

`src/receipts/extract/prompts.py` rule 1 requires `PROMPT_VERSION` to be bumped
on **any** change to the prompt text, and rule 5 extends that to a reworded
schema `description=`, because `eval/harness.py` names its output file from
`PROMPT_VERSION`.

Nothing enforces it. **Measured 2026-08-19: reverting `PROMPT_VERSION` from
`"1.1.0"` to `"1.0.0"` — undoing this branch's own bump, which covers a
reworded `is_template_row` description, a new `Buyer` block and new prompt
rules — passes the full suite, 1236 tests.** The one reference to the constant
outside `prompts.py` is `eval/harness.py:_prompt_version()`.

The consequence is concrete. `_write_report` writes
`eval/results/{date}-{prompt_version}.json` with a plain `write_text`, and the
payload's `prompt_version` key repeats it. An un-bumped prompt change made on
the same day as an earlier run **overwrites that run's artefact**; on a later
day it files under a key that describes the wrong prompt. Either way the eval
grouping key no longer identifies what was measured — the exact defect rule 5
names.

### Why no pin was added

The mechanism that *would* enforce it already exists and already works.
`_bundle_text()` covers every prompt constant **and** the tool-schema JSON, and
`prompt_bundle_hash()` moves when any of them changes — proven by
`test_the_bundle_hash_moves_when_a_description_the_model_sees_changes`
(`tests/test_pipeline_merchant_hints.py`), which rewords the real field and
asserts the hash moves. **`prompt_bundle_hash()` has no production caller.**

The only test shape that closes the gap from the test side is a checked-in
`{PROMPT_VERSION: prompt_bundle_hash()}` table. It was considered and rejected,
for two reasons that are about the shape rather than the effort:

1. **Its red state has two remedies of identical cost, and only one is the
   rule.** Edit the prompt without bumping and the table goes red; the cheapest
   way to green is to paste the new hash under the old version, which *is* the
   defect, and it is exactly as many keystrokes as bumping. A guard whose
   easiest green is the thing it guards against is a reminder, not an
   enforcement — and afterwards it passes while encoding nothing.
2. **It fires on every legitimate bump too, and cannot tell the two apart.**
   Rule 1 already puts one obligation on a prompt edit; the table adds a second
   one, in another file, satisfiable without satisfying the first.

A bare `assert PROMPT_VERSION == "1.1.0"` was not considered further: it goes
red on the next legitimate bump and green again the moment the literal is
updated, having checked nothing about the text at all.

**An honest gap is preferable to a test that passes for the wrong reason.**
This entry is that gap, written down.

### How to resume

1. Decide the contract question: should the eval grouping key be
   `prompt_bundle_hash()` rather than `PROMPT_VERSION`? The hash already covers
   what rule 5 is about and needs no human discipline.
2. If yes, the smallest honest version is **additive**: put the bundle hash in
   `_report_to_dict`'s payload beside `prompt_version`, and in the filename, so
   an un-bumped change can no longer collide with the run before it. That gives
   `prompt_bundle_hash()` its first production caller, which ADR-0044 records as
   open.
3. Note that `eval/results/` is empty by ADR-0039 decision 2, so no committed
   artefact constrains the naming choice yet. That will not stay true.
4. Only after the harness reads the hash is a pin worth writing, and then it
   pins the harness rather than the constant.

### Related

- ADR-0044 — lists `prompt_bundle_hash()`'s missing production caller as open.
- ISSUE-002 — the other place a recorded `prompt_hash` names something that was
  not what was sent.
- `docs/adr/0039-the-local-path-is-a-liveness-check.md` — why `eval/results/` is
  empty.

---

## ISSUE-008 — Two copies of "which rows are purchases", with nothing binding them

**Status:** OPEN — recorded, not fixed. Neither copy is wrong today; the risk is
drift.
**Owner action required:** no.
**Discovered:** 2026-08-19, in the whole-branch review of
`feat/buyer-and-blank-rows`. **Pre-existing:** no — both arrived with
`is_template_row`. **Blocks:** nothing.

### What is wrong

The same predicate is written twice, in `src/receipts/export/xlsx.py` as
`_purchases` and in `src/receipts/validate/rules.py` as `_purchased`. Both
return the line items whose `is_template_row` is false, and the two
comprehensions differ only in variable naming.

`xlsx.py` is deliberately decoupled from the ORM and from `validate`
(ADR-0010), so sharing the helper is not free — that decoupling is why the
second copy exists rather than being an oversight, and `_purchases`' docstring
already points at `_purchased` in prose.

Both are separately pinned:
`tests/test_xlsx.py::test_a_template_row_is_not_exported_as_a_purchase` and
`::test_the_items_count_counts_purchases_not_pre_printed_rows` on one side,
`tests/test_rules.py::test_R020s_finding_counts_only_the_purchases` and
`::test_R024s_finding_counts_only_the_purchases` on the other. So a change to
either copy alone is caught. **Nothing catches a change to the *concept* that
is applied to only one of them** — if "purchase" ever grows a second condition,
one side gets it and the suite stays green.

### How to resume

Do not merge them for tidiness; the module boundary is deliberate. If the
predicate gains a second condition, the cheap binding is a test that asserts the
two functions agree on one constructed receipt covering every case — one test,
in neither module's suite, that fails when the concept splits.

### Related

- ADR-0010 — why `export/xlsx.py` does not import from `persist` or `validate`.
- ISSUE-006 — the reviewer-facing half of the same flag.

---

## ISSUE-009 — `CorrectionPatch` no longer describes the contract it validates

**Status:** OPEN — recorded, not fixed. Harmless today because `extra="allow"`
makes the undeclared paths work anyway.
**Owner action required:** no.
**Discovered:** 2026-08-19, in the whole-branch review of
`feat/buyer-and-blank-rows`. **Pre-existing:** no — both gaps arrived with this
branch's new fields. **Blocks:** nothing; it means the published API schema is
incomplete.

### What is wrong

`src/receipts/review/schemas.py` declares the `PATCH /receipts/{id}` body. Two
of this branch's correctable paths are absent from it:

- `CorrectionPatch` has no `buyer` field, and its docstring enumerates the
  closed set as "`merchant.name`, `receipt.*`, `totals.*`, `payment.*`,
  `meta.*`, and `line_items[i].*`" — `buyer.*` is missing from both.
- `_LineItemPatch` has no `is_template_row`.

Neither breaks anything: `_PATCH_MODEL_CONFIG` is `ConfigDict(extra="allow")` at
every level, and `apply_corrections` is the single place that decides whether a
path is known — which is the deliberate design, so that "unknown field" has one
error currency (400) rather than two.

**What it does break is the published schema.** Measured 2026-08-19:
`CorrectionPatch.model_json_schema()` has top-level properties
`['line_items', 'merchant', 'meta', 'payment', 'receipt', 'totals']`, and
neither the string `buyer` nor `is_template_row` appears anywhere in it —
`$defs._LineItemPatch` lists seven properties and not the flag. FastAPI
publishes that schema as OpenAPI, so a client generated from it cannot send
either field, while the route accepts both.

The docstring is the sharper half: it names the closed set as a fact, and the
set it names is no longer the set `_RECEIPT_FIELDS` holds.

### How to resume

1. Add a `buyer` sub-model and `is_template_row` to `_LineItemPatch`, mirroring
   the existing sub-models. That is the whole change; nothing downstream reads
   these declarations except OpenAPI.
2. Delete the enumeration from `CorrectionPatch`'s docstring rather than
   extending it, or point it at `_RECEIPT_FIELDS`/`_LINE_ITEM_FIELDS` by name. A
   copy of a closed set in prose is a copy that rots — the same reasoning
   `4297547` applied to the design docs.
3. `tests/test_api_write.py` already exercises both paths through the route, so
   the declarations need no new test. What would need one is the property that
   every path in the two maps is declared — and that would be a third copy of
   the binding
   `test_every_correctable_receipt_path_is_offered_by_the_review_client` and
   `test_every_correctable_line_item_column_is_readable_in_the_detail` already
   give, so decide whether a third is wanted before writing it.

### Related

- ISSUE-006 — the readability half, which was a defect rather than a
  documentation gap.
- `docs/adr/0016-review-next-resumes-the-callers-task.md` — the
  two-independent-lists failure this is a benign instance of.

---

## ISSUE-010 - The results list, opened in a browser

**Status:** OPEN, and narrowed to one item nobody has decided. The browser pass
ran on 2026-08-20 across Chromium, Firefox and WebKit. Of the four things this
issue was opened for, one was **refuted**, one was **confirmed correct**, one was
**a real finding and is fixed**, and one is **confirmed and is a repository-wide
question**. What is left is item 4 and the surfaces nobody has still looked at.

**Opened 2026-08-20** at the close of the results-list milestone (`b563242` ->
`f0dc7b6`) as a stated gap in what this repository can check, and answered the
same day against the real API on SQLite.

### 1. The download works. The predicted defect is not there

`downloadExportWorkbook` (`frontend/src/api/receipts.ts`) still builds a
**detached** anchor and still revokes the object URL **synchronously** in a
`finally`. Both remain the documented cross-browser failure modes for blob
downloads. Neither loses the file.

Measured in all three engines: the server answered `200` with
`Content-Disposition: attachment; filename="receipts-export.xlsx"`, the file
reached the filesystem in every engine at roughly 11 KB with `PK` magic, and all
three opened in `openpyxl` with four sheets and the same rows the screen showed,
in the same order. **The two fix shapes this issue used to recommend --
`appendChild`/`remove`, and revoking on a later tick -- are not needed.**

**The green means something, because the instrument was proven red first.**
Replacing `anchor.click()` with a no-op, confirming the mutated tree still
typechecked and built and that the bundle hash changed, then re-running: all
three engines failed, and failed on the discriminating pair rather than on a
timeout of unknown cause -- `200` from the server, no `download` event, nothing
on disk. A probe that cannot see the failure it reports the absence of is worth
nothing, and this one can see it.

**What this does not license:** headless, one operating system, these engine
builds, and no real Save dialog. It is not a claim about every browser forever.

### 2. The two stacked negative margins are correct

`.who` and `.scope` each carry `margin-top: calc(var(--space-2xl) * -1 +
var(--space-xs))`, measured as `-22px`, against the screen's `24px` flex gap:
**2px at both joints**, which is `--space-xs` exactly. Verified at 1440, 1024 and
375, in both themes, in all three engines. No overlap and no margin collapse; the
three lines read as one block. The arithmetic this issue described was right.

### 3. The not-extracted mark in a right-aligned cell -- a real finding, fixed

The question was whether the mark reads as "missing" or as a stray hairline. **In
a left-aligned column it reads as missing; in the right-aligned money column it
read as a stray hairline**, and the mechanism was not the one this issue guessed.

The stroke is deliberate. `Value.module.css` gives `.notExtracted` a
`border-left` plus `padding-left`, and `Value.tsx`'s docstring names it as design
section 4's scannability device. It is a **gutter**: it works because a stack of
left-aligned form fields shares a left edge for the rules to line up on. A
right-aligned cell has no such edge -- the span shrink-wraps and is pushed right,
so the rule lands at a different x in every row. The sharpest instance was a
receipt carrying a currency but no total, where the rule fell between the
currency code and the mark and read as a broken glyph.

**Fixed by mirroring rather than by removing.** `Value` gained an `align` prop
defaulting to `start`, and `.notExtractedEnd` carries the same rule on
`border-right`/`padding-right`. The three right-aligned call sites pass `end`:
the results list's Total and Confidence, and the admin task table's age.

`kind` was rejected as the axis on a measurement: two of the five numeric-kind
call sites are left-aligned (`admin/StatTiles.tsx` and `review/ConfidenceRail.tsx`,
neither stylesheet declaring `text-align` at all), so keying the edge off `kind`
would have moved the rule to the wrong side on two surfaces to fix a third.

Accepted in a browser, not only in a test: after the change the marks in the
Total column share a right edge at the same x, right-aligned marks paint a right
rule and no left one, and the left-aligned Date and Merchant marks are unchanged
-- in all three engines and both themes.

### 4. The `border-radius` on a collapsed table is confirmed ignored -- STILL OPEN

`.table` sets `border-collapse: collapse` and `border-radius: var(--radius-lg)`
on the same rule; the corners render square in all three engines, so the radius
declares an intent the browser discards. **Pre-existing as a pattern:**
`admin/TaskTable.module.css` and `review/LineItemsTable.module.css` both do the
same, so it is a repository-wide question and not this screen's. Nobody has ruled
on it.

### What looking produced that nothing had asked for

- **Money renders at four decimal places** in the list (`USD 1000.0000`).
  Consistent with the app's convention rather than a regression -- `money()`
  returns `str()` off a scale-4 column and the review form's inputs show 4dp too
  -- but a read-only register aimed at accounting is where 2dp and a thousands
  separator would be expected. Undecided.
- **The list is ordered by ingestion, not by transaction date.**
  `query_export_receipts` ends `.order_by(Receipt.created_at, Receipt.id)`,
  deliberately, so the list and the workbook can never disagree about paging
  order -- and the downloaded file's rows came back in exactly the screen's
  order, which is ADR-0046's projection property holding in practice. A reader
  scanning the Date column will still read it as unsorted. **Not a defect**, and
  it was written up as one before the query was read.
- **At 375 the table clips to two columns with no affordance that it scrolls.**
  The page itself correctly never scrolls sideways (asserted:
  `document.documentElement.scrollWidth` equals `clientWidth`), and the scroller
  works, but nothing signals that Total, Status and Confidence exist.
- **The reviewer view is handled well**: rather than the button vanishing
  silently, the screen states that only an admin can download the workbook. A
  reviewer sees every row.
- **`--color-null` does not reach its risky background here.** The table declares
  no zebra striping and no row hover fill, so the mark paints on
  `--color-surface`, never on `--color-surface-active`.

### Why no gate saw any of it, and still cannot

`css: false` in the Vitest config means a `.module.css` import returns a proxy,
so class names are unpinnable by rendering tests; jsdom lays nothing out and
renders no colour; `click` is stubbed; and `e2e/**` is excluded from the Vitest
run, so Playwright is the only instrument that could reach any of this and it is
not a gate. **All five gates were green throughout, including while item 3 was
live.**

**A claim that this had been checked was written and deleted.**
`frontend/tests/stylesheets.test.ts` carried a sentence saying every census
entry below it was looked at through a browser; the whole-branch review found it
false the moment Task 5 added 21 entries. Deleting it removed the claim, not the
gap.

### Two defects in this issue's own resume steps, found by following them

Recorded because they cost the first attempt, and because they are the reason a
brief is a claim about the tree (ADR-0045):

1. **There is no admin to be.** `scripts/seed_review_e2e.py` creates exactly one
   account, a reviewer, while `GET /export/xlsx` is guarded by
   `require_role(ROLE_ADMIN)`. Signing in and clicking Export as the seeded user
   returns 403 and teaches nothing about the anchor. The pass added an admin to
   the database out of band; **seeding one is still not done**, and anyone
   repeating this will need it again.
2. **`npx playwright test visual` never navigates to `/app/receipts`.** Every
   `goto` in `frontend/e2e/visual.spec.ts` targets `/app/login`, `/app/review` or
   `/app/admin`, so that step re-seeds and re-captures the older surfaces only.

### What remains unseen

Item 4's ruling, and 768 at every surface. **Dark theme is no longer unseen
everywhere** -- this screen was looked at in it, at 1440, and renders correctly
-- but no other surface in this app has been.

### Related

- ADR-0029 - what the gates certify and what they cannot.
- ADR-0046 - the list is a projection of the export's query.
- `docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md` - the
  *SUPERSEDED IN PART* block is the record of which surfaces have been seen, at
  which widths, in which theme.

---

## ISSUE-011 - A measured-false spelling survives in three test files

**Status:** OPEN. Pre-existing and cosmetic; the guards it sits beside are all
correct.

**Opened 2026-08-20.** Recorded then because the results-list milestone removed
one instance and deliberately did not touch the rest.

*(Corrected 2026-08-20: this said **four test files** in its heading and again
below, while its own list named three. It is **four sentences across three
files**. The four is not arbitrary -- `grep -l` over `frontend/tests/` does
return four paths -- but the fourth is `value.test.tsx`, which this issue's own
"Why it was not fixed" paragraph already identifies as the record rather than
the error. A file count and a sentence count that happen to coincide are exactly
the shape review standard 23 warns about: state the anchor beside the number.)*

### What is wrong

Four sentences, in three files, state that a mistyped CSS-module key renders
`class="undefined"`: `frontend/tests/admin-screen.test.tsx`,
`frontend/tests/review-null-rule.test.tsx` (twice), and
`frontend/tests/theme-control.test.tsx`.

**It does not.** `frontend/tests/value.test.tsx` records the 2026-08-13
measurement: under this suite the proxy returns a *scoped string*, so a typo
renders a plausible-looking class that no stylesheet declares; in a real build
the key is absent and React omits the attribute entirely. Only
`String(undefined)` produces the literal.

The guards those sentences justify are all correct. Only the stated mechanism is
wrong, and it is wrong in the direction that makes the defect sound louder than
it is -- a reader expecting `class="undefined"` in the DOM will not find it.

### Why it was not fixed with the milestone that found it

A fix wave editing three files it never otherwise touched is the over-reach
ADR-0032 and ADR-0042 both name, and this project has watched consecutive waves
introduce a false claim while closing one. The anchor is
`grep -rn 'class="undefined"' frontend/tests/`, which also returns
`value.test.tsx`'s two corrective mentions -- those are the record, not the
error.

### How to resume

Delete the mechanism half of each sentence and say the class **ships
unpainted**. That is the wording `value.test.tsx` records for the sites already
corrected, and `frontend/tests/receipts-screen.test.tsx` is the worked example.
Do not replace it with a more careful description of the proxy.

---

## ISSUE-012 — The escalation counts never reach the committed results file

**Status:** OPEN — recorded, not fixed. Fixing it moves who owns the write,
which is a decision rather than a patch.
**Owner action required:** no.
**Discovered:** 2026-08-20, during the local→Cloud escalation milestone;
promoted here 2026-08-21 by that branch's whole-branch review.
**Pre-existing:** no — the field arrived with this milestone.
**Blocks:** nothing. *(Updated 2026-08-22: it read "ISSUE-001 step 6,
partially". Step 6 ran without it — the aggregate `eval/run_repeats.py` writes
carries the per-rung provenance the results file omits, so this issue's stated
reason for blocking is discharged. Who owns `run_eval`'s write is still open.)*

### What is wrong

`EvalReport.extract_rung_counts` records how many receipts each extract rung
produced the kept extraction for. It reaches the printed report and
`run_baseline`'s return value. It does **not** reach
`eval/results/{date}-{PROMPT_VERSION}.json`.

The ordering is why: `run_eval`'s last two statements are `_write_report(...)`
then `return report` (checked 2026-08-21), and `run_baseline` folds the counts
in *after* `run_eval` returns. So a key added to `_report_to_dict` would be
`null` in every file that function has ever produced, whatever the run measured.
`eval/harness.py` carries that reason at the site, together with the probe that
established it — a run whose report carried `{'cloud': 1}` wrote `null`.

ISSUE-001 step 6 says to commit the results file so regressions show in a diff.
An artifact that omits which model produced what does not record the thing that
step exists to record — and ISSUE-001's own stated fear is a good accuracy
number hiding the fact that everything escalated.

### How to resume

The fix is not "add the key". It is to decide who writes the results file: move
the write out of `run_eval` to a caller that has the folded report, or give
`run_eval` a way to receive the counts before it writes. Either changes
`run_eval`'s contract, and
`tests/test_cli_reports.py::test_the_producer_writes_the_shape_this_module_hand_writes`
pins the artifact's key sets against a hand-written fixture, so the fixture
moves with it.

### Related

- ISSUE-001 — step 6, and the escalation-rate requirement.
- ISSUE-013 — the other half of the same figure: the key it is counted by.
- `docs/superpowers/specs/2026-08-20-local-to-cloud-escalation-design.md` §6.1 —
  the provenance route, and why it takes `cost_per_receipt`'s path.

---

## ISSUE-013 — `extract_rung_counts` is keyed by `model_id`, and a tier is not a model

**Status:** OPEN — recorded, not fixed. The key is specified in the milestone
plan and in `EvalReport.extract_rung_counts`' own field comment, and it is in
the field's committed type, so changing it is a decision rather than a patch.
(Design §6 does *not* name the key — checked 2026-08-21; it says only that the
report "gains per-rung counts".)
**Owner action required:** no.
**Discovered:** 2026-08-20, during the local→Cloud escalation milestone;
promoted here 2026-08-21 by that branch's whole-branch review.
**Pre-existing:** no. **Blocks:** nothing today; it bounds what the figure can
show.

### What is wrong

Design §2.2 defines a tier as a **`(model, use_tools)` pair**, not a model.
`PassAttempt` records `model_id` and no tools flag, and `run_baseline` counts
`counts[entry.model_id]`.

Nothing forbids `VLM_MODEL_EXTRACT_FALLBACK` naming the same model as
`VLM_MODEL_EXTRACT`. Measured 2026-08-21 with
`vlm_model_extract=vlm_model_extract_fallback='m'`, `VLM_USE_TOOLS=false` and
`VLM_USE_TOOLS_FALLBACK=true`: `make_pass_clients` builds two rungs, `[('m',
False), ('m', True)]`, and one distinct `model_id`. Both rungs would land in one
count and the escalation would be invisible — **in the figure ISSUE-001 asked
for precisely so a good number could not hide one.**

That configuration is **constructible**, which is what the measurement above
shows; nothing here shows anything wants it. The tools-granularity defect
design §7.1 closes is a different shape — *two models* sharing one provider id
(`granite3.2-vision:2b` and `gemma4:cloud`, both `ollama`) — so it is not
evidence for this one.

### How to resume

Key the counts by whatever a tier actually is. `PassAttempt` would carry the
tools flag, `run_baseline`'s fold would key on the pair, and `format_report`'s
one-line-per-model block would have to render it. The type
(`dict[str, int] | None`) is part of the committed contract, and design §2.2 is
the sentence that makes the change necessary rather than optional.

### Related

- ISSUE-012 — the same figure, and where it fails to arrive.
- `docs/superpowers/specs/2026-08-20-local-to-cloud-escalation-design.md` §2.2,
  §6, §7.1.

---

## ISSUE-014 — `frozen=True` is a stated interface property that nothing pins

**Status:** OPEN — recorded, not fixed. Whether to pin it, and where, is a
decision about how much of a dataclass's declaration is worth a test.
**Owner action required:** no.
**Discovered:** 2026-08-20 (Task 4) and again at Task 5, during the local→Cloud
escalation milestone; promoted here 2026-08-21 by that branch's whole-branch
review. **Pre-existing:** the class is; the three newest members are not.
**Blocks:** nothing.

### What is wrong

This milestone declared three frozen dataclasses — `PassAttempt` and
`RunOutcome` in `src/receipts/pipeline.py`, `PassClients` in
`src/receipts/extract/clients/factory.py`. **Measured 2026-08-21, one mutation
at a time, each anchored on its own class name and each with the tree confirmed
importable first: dropping `frozen=True` from any one of the three leaves the
whole suite green — `1291 passed` on all three runs.**

The gap is wider than this milestone. Also measured 2026-08-21:
`git grep -n "dataclass(frozen=True)" -- src eval` returns **10** declarations,
and `git grep -n "FrozenInstanceError" -- tests` returns **0**. No test in this
repository asserts that any dataclass is frozen. Immutability is a promise the
declarations make and nothing checks.

### How to resume

Do not add ten near-identical `pytest.raises(FrozenInstanceError)` tests — that
is the enumerated defence review standard 19 names, and it grows with the tenth
dataclass anyone declares. If it is worth pinning, the shape that converges is
one property over a set: assert that a named set of result types is frozen, and
make the *set* the thing a new type has to be added to. Deciding which types
belong in that set is the decision here.

### Related

- ADR-0046 decision 5 and the `_resolve_merchant` rollback — the same class: a
  stated interface property with no test behind it.
- Review standard 14 — a pin never proven red is not a pin; this is the case
  before there is a pin at all.

---

## ISSUE-015 — `PassAttempt.rung` is written and never read

**Status:** OPEN — recorded, not fixed. Deleting the field or pinning it are
both defensible, and the choice belongs with the ADR.
**Owner action required:** no.
**Discovered:** 2026-08-20 (Task 5), during the local→Cloud escalation
milestone; promoted here 2026-08-21 by that branch's whole-branch review.
**Pre-existing:** no. **Blocks:** nothing.

### What is wrong

`PassAttempt.rung` records which rung of the ladder an attempt was. Measured
2026-08-21: `git grep -n "\.rung\b" -- src eval` returns **nothing** — the field
is read nowhere in production code. `git grep -n "rung=" -- src eval` returns
its four write sites, all in `run_receipt`.

`run_baseline` folds the counts out of `pass_name`, `model_id` and `kept` only,
so **a ladder that recorded `rung=0` for every rung would leave every gate
green.** One test reads it —
`tests/test_pipeline.py::test_triage_runs_on_its_own_client_when_one_is_given`
asserts the triage entry is `rung=0` — which pins the triage pass's value and
nothing about the extract rungs, where the number is the one that carries
information.

### How to resume

Two honest answers, and picking between them is the point:

1. **Pin it.** Extend an existing ladder test to assert the extract entries'
   `rung` values, so a ladder that numbers every rung 0 goes red. Cheap.
2. **Delete it.** A field nothing reads is a field that can be wrong for as long
   as it exists. `attribution` is a tuple in ladder order, so the index is
   recoverable without storing it.

Do not do both, and do not leave it as it is on the grounds that it is
harmless — a write-only field in a provenance record is exactly the shape
ISSUE-001 asked provenance to protect against.

### Related

- ISSUE-013 — the other unpinned property of the same record.
- `docs/superpowers/specs/2026-08-20-local-to-cloud-escalation-design.md` §6.

---

## ISSUE-016 — `read_nothing` counts a vacuous value as something the model read

**Status:** OPEN — recorded, not fixed, and deliberately so: the two obvious
fixes are both worse than the gap.
**Owner action required:** no.
**Discovered:** 2026-08-20 during the local→Cloud escalation milestone (M1 of
its whole-branch review); promoted here 2026-08-21. **Pre-existing:** no.
**Blocks:** nothing measured; it narrows when the fallback fires.
*(Updated 2026-08-22: it **does** gate a ladder configuration. If granite emits
`merchant.name=""`, `totals.total=0` or `prices_include_tax=False`, its
extraction is kept and never escalates. Filed under "does not gate anything",
which is true of a cloud-only run and false of a ladder.)*

### What is wrong

`read_nothing` compares an extraction's filled `core` and `line_items` paths
against a default of the same shape, and `is_filled` accepts `0`, `False` and
`""` as content — by design, because a read zero and a read false are content.
The consequence is that a model answering with an empty-but-present value keeps
its rung.

Measured 2026-08-21, each on an otherwise default `ReceiptExtraction()`:

| set | `read_nothing` |
|---|---|
| `merchant.name = ""` | `False` |
| `totals.total = Decimal("0")` | `False` |
| `totals.prices_include_tax = False` | `False` |

`False` means "it read something", so the local rung is kept and the cloud rung
never runs. This is the **third** time this predicate has been found wrong in
the never-fires direction: design §3's correction records the first, §3.1's the
second (a single blank `LineItem`), and this is the third.

### How to resume

**Do not close it by enumerating fields.** Every previous version of this
predicate was wrong because a field rested at a default `is_filled` accepts, and
the fix each time was to make the *baseline* more like the thing being judged —
not to list fields. A list rots on the next schema change and is review standard
19's enumerated defence.

**Do not change `is_filled`.** It is shared with `field_accuracy` by design
(design §3.3, §4): one definition of "content", not two. A read zero is content
for accuracy scoring, and that is correct there.

What is left is a decision nobody has taken: whether "vacuous" is a third
concept, distinct from both "filled" and "matches the default", and if so what
it is defined against. Note the direction of the cost — a predicate that is too
eager escalates a receipt the local rung actually read, and an extract call on
this hardware is measured in minutes. **No range is written here.** The two
figures this sentence used to quote — 2121 s and 6563 s — are the extract pass
of *two different runs*, at `max_edge` 768 and 2048, and this file says three
lines below that table that the second **cannot be attributed to one
inference**, because `VLM_TIMEOUT_S` bounds one attempt and the SDK retries
twice. There is no per-call measurement in this repository.

### Related

- `docs/superpowers/specs/2026-08-20-local-to-cloud-escalation-design.md` §3,
  §3.1, §3.3, §4 — the predicate, both earlier corrections, and why the grouping
  is shared.
- ISSUE-008 — why a second copy of the predicate is not the answer.

---

## ISSUE-017 — The baseline's variance is across receipts, not across repeats

**Status:** OPEN — a finding, not a bug. It changes how every accuracy figure in
this project must be read.
**Owner action required:** no. **Discovered:** 2026-08-22, ISSUE-001 step 6.
**Pre-existing:** yes, and invisible until a real run existed.
**Blocks:** any single-figure accuracy claim.

### What is wrong

`transcription_accuracy` per receipt, over the same five repeats of the
2026-08-22 cloud-only baseline:

| receipt | min | max | median |
|---|---|---|---|
| r001 | 60.71% | 64.29% | 64.29% |
| r002 | 91.67% | 95.83% | 95.83% |
| **r003** | **11.11%** | **11.11%** | **11.11%** |

The published 60.00–61.43% is an average over receipts spanning **11% to 96%**.
The spread across repeats is ±1.4 points; across receipts it is **85 points**.

**ISSUE-001 step 6's standing warning — "do not report a single run" — was aimed
at the wrong axis.** Runs barely vary. Receipts vary enormously, and averaging
three into one figure hides that one of the three is a near-total failure.

**r003 scored exactly 11.11% on all five repeats.** A perfectly stable failure
is not the signature of a model that read the page and got it wrong.

### Why it is not being fixed

It is not a defect in code. It is a fact about a three-receipt corpus, and the
remedy is ISSUE-001 step 7 — grow the golden set — which this makes more urgent
than the model choice does.

### How to resume

Derive it from the committed per-repeat files:
`results[].transcription_correct / transcription_total`, per `receipt_id`. The
aggregate carries run-level metrics only, so this is invisible in
`aggregate.json` — see ADR-0049's "What this ADR does not decide".

### Related

- ISSUE-001 step 6 (the measurement) and step 7 (the remedy).
- ADR-0049 decision 3.

---

## ISSUE-018 — The escalation records that it escalated, never why

**Status:** OPEN — a gap the first real ladder run exposed.
**Owner action required:** no. **Discovered:** 2026-08-22, ISSUE-001 step 6.
**Pre-existing:** yes — it arrived with ADR-0047 and had no consequence until a
real rung was discarded. **Blocks:** interpreting any ladder run.

### What is wrong

ADR-0047 decision 3 discards a rung on **two** clauses: the call **raised**, or
the extraction **read nothing**. They are different facts about the local model —
a raise says the box is too slow, a read-nothing says the model cannot read the
page — and **nothing records which one fired.**

Measured 2026-08-22: `PassAttempt` carries exactly `pass_name`, `model_id`,
`rung`, `kept`. No field records a discard reason, and `.rung` is read nowhere
in `src/` or `eval/` (ISSUE-015).

The first real ladder run (`eval/results/ladder-probe/`, one receipt, 41m39s)
shows `extract_rung_counts: {"gemma4:cloud": 1}` — granite ran, was discarded,
the cloud rung was kept. **Which clause fired is unrecoverable from the
artifact.**

**Do not infer it from elapsed time.** `VLM_TIMEOUT_S` bounds one HTTP attempt
and the SDK retries (ADR-0047 decision 8), so any elapsed figure covers an
unknown number of attempts.

### How to resume

`PassAttempt` is the natural home, and it is also the natural reader ISSUE-015
asks for: a field recording why a non-kept rung was discarded gives `rung` its
first production consumer and answers this at the same time. Both the plan and
the field's committed type would change, so it is a decision rather than a line.

### Related

- ISSUE-015 — `PassAttempt.rung` is write-only; this is the reader it wants.
- ADR-0047 decision 3, ADR-0049 decision 4.

---

## ISSUE-019 — "Committed whole or not at all" is a rule no gate holds

**Status:** OPEN — found by the whole-branch review of
`feat/golden-set-privacy`, before merge.
**Owner action required:** no, but the remedy is a design decision.
**Discovered:** 2026-08-22, closing ISSUE-001 step 7's machinery.
**Pre-existing:** no — it arrives with ADR-0050, which states the rule.
**Blocks:** nothing today. It is a stated guarantee with nothing behind it,
which is the shape this repository has twice paid for.

### What is wrong

ADR-0050 decision 1 ends "**So a label is committed whole or not at all**", and
`eval/golden/README.md` tells a labeller the same thing. **Nothing checks it.**
A tracked `r*` label with `merchant.name`, `merchant.address`, `merchant.tax_id`
and `buyer.name` set to `null` passes every gate. Measured by the whole-branch
review on a replica of the branch tip, with the label committed and the full
suite green; the classification half is re-derived below and is the controller's
own.

The nearest guard, `test_a_label_declares_every_field_the_schema_declares`,
compares the paths the raw JSON declares against the paths the parsed model
carries. A **deleted** key is caught, because the schema default fills it and
the two sets differ. A key present with value `null` appears in both sets, so
**redaction by nulling is invisible to it.**

There is a second violation shape the design's own measurement does not cover.
A sentinel string corrupts the metric a different way — scoring a correct read
as *wrong* rather than as *invented*, with `hallucinated` unchanged:

```
intact               transcription 28/28   core 12/12   hallucinated=0
merchant.name NULL   transcription 27/27   core 11/11   hallucinated=1
merchant.name "[REDACTED]"
                     transcription 27/28   core 11/12   hallucinated=0
```

### Why it is hard rather than merely undone

**A redacted field and an absent one are indistinguishable in the label.**
`eval/golden/README.md` step 3 tells a labeller to use `null` for anything the
receipt does not show or that cannot be read — so `merchant.tax_id: null` is
correct for a receipt with no printed tax ID, and wrong for one where the
labeller removed it. A pin asserting "the PII paths are filled" would redden on
a legitimate receipt.

Closing this needs a **declared marker** — something in the label or the manifest
that says "this path was withheld" as distinct from "this path was blank" — and
that is a schema decision ADR-0050 deliberately does not take.

### How to resume

State one bounded property and enforce it at both ends, rather than enumerating
redaction shapes (review standard 19 — nulls and sentinels are two shapes of one
class, and a third will exist). The candidate: a label carries an explicit
withheld-paths declaration, empty for every public label, and a test asserts
every tracked label's declaration is empty. That also gives the metric the
`field_breakdown` hook design §3 says field-level redaction would need, without
taking it.

### Related

- ADR-0050 decisions 1 and 2.
- The 2026-08-22 growing-the-golden-set design, §3 and §8's last bullet.

---

## ISSUE-020 — A frozen `GOLDEN_TODAY` reddens the suite for any recent receipt

**Status:** **CLOSED 2026-08-22**, on `feat/corpus-date-not-frozen`. Found by
the whole-branch review of `feat/golden-set-privacy`, before merge; fixed before
any receipt was collected. **The fix was neither of the two options this issue
proposed** — see the resolution below.
**Owner action required:** no.
**Discovered:** 2026-08-22.
**Pre-existing:** yes — the frozen date predates the branch and had no
consequence while the golden set held only receipts from July.
**Blocks:** **ISSUE-001 step 7, on its first receipt.**

### What is wrong

`tests/test_rules.py` loads the real labels directory at import and
`test_real_corpus_labels_produce_no_errors` (renamed
`test_the_real_corpus_validates_as_production_does` by the fix) scores every
label against a frozen
`GOLDEN_TODAY = date(2026, 7, 28)`. Rule `R031` flags a future receipt date, its
severity is `Severity.ERROR`, and `future_date_slack_days` defaults to `1`.

**So a correctly-made label for any receipt dated after 2026-07-29 fails the
suite.** Measured with a label copied from `r001` and dated 2026-08-20:

```
FAILED tests/test_rules.py::test_real_corpus_labels_produce_no_errors[p999]
E  AssertionError: p999: [R031] receipt.date 2026-08-20 is in the future
   (today is 2026-07-28). [...]
```

(The rule's message continues "This usually means day and month were swapped, or
a digit in the year was misread" — advice that is wrong here, which is the
point.)

Every receipt Task 3 collects will be dated after 2026-07-29.

### The trap that comes with it

The plan's Task 3 Step 3 tells the labeller to run **only**
`tests/test_eval_floor.py` and says "a failure there means the label is wrong,
not the test". Applied to this failure the reason is **backwards**: the label is
right and the frozen date is stale. That is review standard 28 — a correct
instruction carrying a false reason is more dangerous than a wrong one, because
the reason is what a reader generalises from.

Note also that `tests/test_rules.py` is a **fifth** reader of the labels
directory, reaching it transitively through `eval/golden_set.py`'s glob rather
than globbing itself. ADR-0050's four-row table enumerates the globs and is
correct as written; the set of things a new label affects is larger than the set
of things that glob.

### How to resume

Two options, and the choice is a design call nobody has made:

1. **Move the frozen date** on each collection round. Cheapest, and it rots
   again by construction.
2. **Score each label against its own receipt date** (or the label's capture
   date from `manifest.json`), so the corpus test asks "was this valid when it
   was issued" rather than "is it valid on one hardcoded day". Removes the class
   rather than the instance, and changes what the test means.

Whichever is chosen, the plan's Step 3 instruction needs the corrected reason.

### Resolution, 2026-08-22 — and neither option above was taken

**Option 2 was wrong twice, and both halves were caught only by checking the
tree.** Scoring a label against its own receipt date makes `R031` **vacuous on
the corpus**: `(date - date).days` is `0`, which is inside the slack for every
label, so a typo'd future date — the exact defect `R031` exists to catch —
becomes invisible in the one place real labels are checked. And **`manifest.json`
carries no capture date** at all: it holds `category` and `holdout` per receipt
and nothing else, so the parenthetical variant did not exist. That sentence was
written from memory rather than from the file.

**What the tree actually said.** The corpus check was the only caller
overriding `today` **that validates the real corpus** — nine test modules
override it for their own fixtures, and an earlier version of this sentence said
"the only caller" flatly, which is false. Every non-test site builds a bare
`ValidationContext()`: `eval/run_baseline.py`, `scripts/try_one_receipt.py`,
`src/receipts/extract/extractor.py`, `src/receipts/pipeline.py`,
`src/receipts/validate/validator.py` — enumerated from the tree at the moment
of writing, because a draft of this list said "all four" and omitted the
`scripts/` one. `ValidationContext.today` already defaults to `date.today` and
`config=RuleConfig()` was the default too, so **the override was the entire difference
between the corpus check and a bare context.**

**One thing that does not follow, stated because the draft asserted it.**
"So the corpus is validated the way a real receipt is" is *not* implied.
Production builds a bare context and then **populates** it — `extractor.py`
sets `ctx.triage`, `pipeline.py` `replace()`s in the expected-buyer fields.
Measured on all three labels: the ERROR findings are identical bare vs triaged,
and the only rules the extra fields add are `R014`/`R015`, both `WARN`, which
this check does not assert on. So the gap is invisible **today**, and becomes
real the day an ERROR-severity rule reads a field production fills.

**Why the remaining time-dependence is safe.** A receipt already in the past
recedes further every day, so a label that passes now passes forever. The only
thing that can redden it is a date genuinely in the future, which is a typo —
precisely what `R031` is for. `R031` itself never depended on this check — it is
pinned by its own unit tests against synthetic receipts, which never touch the
corpus. (No count is given: an earlier draft of this sentence, and the fix's
commit message, both said "three dedicated unit tests"; there are two for
`R031`, and the third the grep showed belongs to `R032`.)

**Pinned by** `tests/test_rules.py::test_the_real_corpus_validates_as_production_does`,
which scores the real labels **and two synthetic calendar cases through one
call**: a receipt dated today, which must be clean, and one dated past the
future-date slack, which must still raise exactly `R031`.

**The first shape of this fix was itself unenforced, and the review found it.**
The guard began as a separate test *beside* the corpus check, and the corpus
check kept building its own context — so re-freezing that call site to
`date(2026, 7, 28)` reinstated ISSUE-020 verbatim while all 118 tests and the
lint gate stayed green. **A guard that builds its own context cannot see the
check re-freezing its own.** That is why both synthetic cases now live *inside*
the parametrised check.

**Why both ends are needed, each measured rather than imagined.** "Today's
receipt passes" alone is satisfied *forever* by a context frozen far in the
**future** (`date(2099, 1, 1)`) or with the slack inflated
(`future_date_slack_days=100000`) — and either makes `R031` vacuous on the whole
corpus, which is the same vacuity Option 2 was rejected for, reached by another
door. An earlier draft of this section called that residual a one-day exposure.
It was unbounded.

All three redden now, one mutation per run, each parsed before it was believed:
the original literal reddens the dated-today case; 2099 and the inflated slack
each redden the past-the-slack case.

*(A draft said the pin was "proven red twice: against the code before the fix,
and against a re-freeze". Those were one mutation described twice — the helper
did not exist before the fix, so both reduce to the same freeze.)*

### Related

- ISSUE-001 step 7; ADR-0050 decision 2.
- `src/receipts/validate/rules.py`'s `R031`;
  `src/receipts/validate/context.py`'s `future_date_slack_days`.

---

## ISSUE-021 — One unloadable label silently disables the whole real-corpus check

**Status:** **CLOSED 2026-08-22**, on `feat/corpus-loads-loudly`. Found while
closing ISSUE-020, in the same block.
**Owner action required:** no.
**Discovered:** 2026-08-22.
**Pre-existing:** yes.
**Blocks:** nothing today, and the exposure grows with every label collected.

### What is wrong

`tests/test_rules.py` builds its corpus at import:

```python
try:
    GOLDEN_LABELS = load_labels(DEFAULT_LABELS_DIR)
except Exception:  # labels are PII and may be absent -- skip, never error
    GOLDEN_LABELS = {}
```

`load_labels` is **the strict loader** — its own docstring says a malformed
file raises on purpose. So **any** label that will not parse takes the whole
corpus to `{}`, the parametrisation collapses to `[None]`, and every
real-corpus case **skips**. The suite stays green with its only real-data
regression check switched off.

Measured, on a throwaway directory rather than the tracked one:

```
valid only     : ['r001']
with malformed : RAISES ValidationError
  -> caught, GOLDEN_LABELS = {} -> parametrize [None] -> every corpus case SKIPS
```

**The comment is the tell.** "labels are PII and may be absent" describes the
*intended* skip — a clone with no labels — and the handler cannot tell that
from a label that is present and broken. Those need opposite answers: absent is
a legitimate skip, broken is a failure.

### Why it matters more from here on

Step 7 exists to add labels, by hand, from photographs. Hand-written JSON is
exactly where a parse or schema error comes from, and the moment one lands the
corpus check goes quiet rather than loud. `tests/test_eval_floor.py` would
redden on most such files, so a labeller is unlikely to miss the mistake
entirely — but they would fix it believing the corpus check had been running,
and any malformation that `load_labels` rejects while `test_eval_floor`'s own
parse tolerates leaves no red at all.

### Correction, 2026-08-22 — the handler is dead, not merely broad

**A draft of this issue said "Absent is `FileNotFoundError`". That is false, and
it makes the remedy wrong.** Absence never raises: `_label_files` uses
`labels_dir.glob("*.json")`, and a glob over a directory that does not exist
yields nothing rather than throwing. Measured:

```
absent directory     -> RETURNED {}  (no exception)
empty directory      -> RETURNED {}  (no exception)
```

So the `except Exception` **cannot ever fire for the case its own comment
names.** The PII-absent skip is delivered entirely by the empty glob. The
handler fires only for the broken case — the one case it must not swallow. It is
not over-broad; it is **100% mis-targeted**.

### A worked instance where nothing goes red at all

The hedge below says `tests/test_eval_floor.py` "would redden on most such
files". Here is one where it does not, found by the review. `load_labels` parses
with `model_validate_json` (pydantic-core's parser); `test_eval_floor` uses
`json.loads` then `model_validate`. A lone surrogate escape diverges: the first
rejects it, the second accepts. With a fourth label carrying
`"description_raw": "DSL\ud800-2"`:

```
tests/test_rules.py     : 115 passed, 1 skipped   (corpus 3 cases -> 1 skip)
tests/test_eval_floor.py: 21 passed               (was 17 -- it GREW by 4, green)
full suite              : 1348 passed, 1 skipped, exit 0
```

**No red anywhere**, and `test_eval_floor`'s case count going *up* is not
evidence the label is good.

### How to resume

**Delete the try/except.** Narrowing it is the wrong fix, because there is no
condition to narrow it to: absence already returns `{}` without raising. A bare
`GOLDEN_LABELS = load_labels(DEFAULT_LABELS_DIR)` was measured with every label
moved out of the tree — `115 passed, 1 skipped`, no import error — so the
clone-with-no-labels case survives deletion untouched.

**A silent skip is how a guard becomes vacuous** — the same reasoning
`docs/superpowers/plans/2026-08-22-growing-the-golden-set.md` gives for not
adding a skip to the privacy tests.

**One thing ISSUE-020's fix changed here.** The corpus check is now parametrised
over the labels *plus two synthetic calendar cases*, so an unloadable label no
longer shows as `1 skipped`; it shows as the two synthetic cases passing. The
count of real-label cases going **down** is still the signal, and it is now the
only one — which makes this issue more worth closing, not less.

### Resolution, 2026-08-22 — deleted, not narrowed

**The handler is gone.** There was nothing to narrow it to: `_label_files`
globs, and **its own docstring already said so** — *"a missing directory yields
an empty list — `Path.glob` does not raise on a non-existent directory, so
callers stay exception-free."* The handler was written against a hazard the code
it calls documents as impossible. Re-derived rather than taken from that
docstring: an absent directory and an empty one both return `{}` with no
exception.

**Measured end to end, in the runtime rather than by reasoning about it.** With
a malformed label present, collection now stops:

```
E   pydantic_core._pydantic_core.ValidationError: 1 validation error for ReceiptExtraction
E     Invalid JSON: key must be a string at line 1 column 3 ...
ERROR tests/test_rules.py
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
```

**It does not name the offending file, and a draft of this section said it
did.** Measured: `grep -c p999` over the whole pytest output returns **0**. The
error echoes the file's *content* and the loader's line; `path` is a loop local
and pytest does not print locals without `--showlocals`. At three labels the
culprit is guessable; at the 50-100 the README targets it is not, and
`validate_labels` beside it already renders `"{filename}: {reason}"`. **That gap
is ISSUE-022.**

The probe was named `p999.json` on purpose — that pattern is gitignored, so a
probe stranded by an interrupted session could never reach the index. It was
removed and the labels directory verified back to its three real files. **Twice
the removal had to be done in Python**, because the destructive-commands hook
refuses `rm` on an in-tree path; the second time it blocked a *compound* command
and the deletion silently did not run, leaving the probe in place until the next
check caught it.

**The standing guard** is
`tests/test_rules.py::test_every_label_file_on_disk_reached_the_corpus`: what is
on disk is what got scored. Proven red by making the handler fire exactly as a
broken label would, which left the corpus `{}` while three labels sat beside it.

**Its first version did not discriminate, and the review caught that.** It took
`on_disk` from `_label_files` — the very function the loader globs with — so
anything that function dropped left both sides at once. Measured: excluding
`r003.json` inside `_is_label_file` left a real label on disk and unscored with
the guard and the entire suite green. It now reads the directory itself,
case-insensitively, which also covers a label saved as `.JSON`: scored on this
box's filesystem and invisible to the loader's glob on CI's Linux.

**The red also showed the defect's signature directly:** collection went from
**120 cases to 117** — the three real-label cases vanished from the
parametrisation and *nothing but this guard noticed*, which is precisely why
plan Defect 7 tells a labeller to count the real-label cases rather than the
total. *(A draft said "120 cases to 116". 116 was the **passed** count with the
guard failing beside it; no state ever collected 116. The delta that matters is
3, which is the number of labels.)*

**What this does not change.** The divergence between `model_validate_json` and
`json.loads` + `model_validate` is still real — a lone surrogate escape is
accepted by one and rejected by the other. It is no longer *silent*, because
the strict loader now fails the run instead of emptying the corpus, but the two
parsers still disagree about what a valid label is. Nobody has decided whether
they should.

### Related

- ISSUE-020 — the same block, found while closing it.
- ADR-0050 decision 2, on what a new label is and is not validated by.

---

## ISSUE-022 — A label that will not load fails loudly without saying which one

**Status:** **CLOSED 2026-08-23**, on `feat/label-errors-name-the-file`. Found by
the review of the ISSUE-021 fix, in the claim that fix made about itself.
**Owner action required:** no.
**Discovered:** 2026-08-22.
**Pre-existing:** the behaviour is; the *exposure* arrives with ISSUE-021's fix,
which turned a silent skip into a loud abort.
**Blocks:** nothing. It costs a labeller time, and the cost grows with the
corpus.

### What is wrong

`load_labels` parses each file with
`ReceiptExtraction.model_validate_json(path.read_text(...))` and lets the error
out unwrapped. `path` is a loop local, and pytest does not print locals without
`--showlocals`, so the failure names the **test module** and the **loader line**
and echoes the file's *content* — never its path. Measured over the whole pytest
output with a malformed `p999.json` present:

```
$ python -m pytest tests/test_rules.py 2>&1 | grep -c "p999"
0
```

```
tests\test_rules.py:627: in <module>
    GOLDEN_LABELS = load_labels(DEFAULT_LABELS_DIR)
eval\golden_set.py:100: in load_labels
    labels[path.stem] = ReceiptExtraction.model_validate_json(
E   pydantic_core._pydantic_core.ValidationError: 1 validation error for ReceiptExtraction
E     Invalid JSON: key must be a string at line 1 column 2 ...
```

At three labels the culprit is guessable. `eval/golden/README.md` targets 50-100.

### Why it matters more from here on

ISSUE-021's fix made this failure **abort the whole pytest session** rather than
quietly empty the corpus. That is the right trade — but it means one unreadable
private label blocks every test in the repository, and the message does not say
which file to fix.

### How to resume

`validate_labels`, in the same module, already renders `"{filename}: {reason}"`.
The narrow change is to wrap the parse in `load_labels` and re-raise carrying
`path.name`.

**Note what that is not.** Re-raising with context is the opposite of the
handler ISSUE-021 deleted: that one *swallowed* and returned `{}`; this one
would raise, louder and better addressed. The distinction is worth stating in
the commit, because the diff will look like an `except` returning to the file it
was just removed from.

Check `load_labels`'s callers before changing the exception type —
`tests/test_rules.py`, `eval/harness.py`'s neighbours and `validate_labels`
itself are the places to look.

### Resolution, 2026-08-23 — a note, not a new exception type

`load_labels` now wraps the parse and calls
`exc.add_note(f"while loading golden label {path.name}")` before re-raising.

**A note rather than a wrapped exception, deliberately.** Every caller sees the
same exception type it saw before, so nothing can break on the change — and
the enumeration behind that is small: `load_labels` is called from two files,
`tests/test_golden_set.py` and `tests/test_rules.py`. *(A draft added "neither
of which catches anything". That was false the moment it was written: this
branch's own pin wraps the call in `pytest.raises(Exception)`, one commit
earlier. The conclusion survives — a bare `Exception` catch is type-agnostic —
but the claim did not.)* The note is carried in `__notes__` and rendered by both
`traceback.format_exception` and pytest since Python 3.11; this project gates
3.11 and 3.13.

**Measured end to end in the collection path**, which is the case that matters,
with a malformed label present:

```
E     Invalid JSON: key must be a string at line 1 column 2 ...
E   while loading golden label p999.json
ERROR tests/test_rules.py
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
```

`grep -c "p999.json"` over the whole pytest output returns **1**. It returned
**0** before.

**This is not the handler ISSUE-021 deleted, and the diff will look like it
is.** That one caught everything and returned `{}`, hiding the failure. This one
catches, adds the one missing fact, and re-raises unchanged. Swallowing versus
annotating is the whole difference, and the code comment says so at the site,
because the next reader will arrive with ISSUE-021 in mind.

**Pinned by** `tests/test_golden_set.py::test_a_label_that_will_not_load_names_itself`,
which asserts on the **rendered traceback** rather than on `__notes__`, so the
pin survives any other way of carrying the name — a wrapped exception, a
dedicated type. What a reader sees is the property; how it gets there is not.

**Its first version could not tell "the file that failed" from "any file".** The
fixture wrote a valid `r001` and a broken `r002`, so the broken label sorted
last, and two wrong implementations passed: naming **every** label file, and
naming the **last** one. Naming every file is precisely the failure this issue
exists to prevent at 50-100 labels. The healthy labels now bracket the broken
one and their **absence** is asserted; all three reds measured, one mutation per
run.

**And the reason the design was chosen is now pinned too**, by
`test_naming_the_label_does_not_change_what_escapes`. "Every caller sees the same
type" was stated in three places and enforced nowhere — a wrapping
`raise RuntimeError(...) from exc` left the whole suite green. It derives the
reference type from `model_validate_json` on the same bytes rather than naming
pydantic, so it cannot rot when the schema library changes.

### Related

- ISSUE-021 — the fix whose own description claimed this already worked.
- The 2026-08-22 growing-the-golden-set plan, Defect 7.

---

## ISSUE-023 — Consistency voting has neither tolerance nor shared alignment

**Status:** OPEN — recorded, not fixed. It is `IMPLEMENTATION_PLAN.md` P2.T1,
which was never built.
**Owner action required:** no. **Discovered:** 2026-08-23, auditing
`IMPLEMENTATION_PLAN.md` against the tree.
**Pre-existing:** yes — `run_consistency` has had this shape since Phase 0.
**Blocks:** nothing today, because `run_consistency` has no caller. **It blocks
P7.T1**: wiring consistency into the pipeline without fixing this puts both
defects on a live path at once.

### What is wrong

`_vote` (`src/receipts/extract/extractor.py`) decides agreement by **exact
string equality**. It flattens each run and tallies
`json.dumps(v, sort_keys=True, default=str)` per path. P2.T1 was written to fix
the two consequences, and both are still live:

- **No money tolerance.** `949.20` and `949.21` serialise to different strings
  and count as disagreement, so cent-level rounding between runs reads as
  uncertainty. `within_tolerance` is defined in `src/receipts/validate/rules.py`
  and appears **nowhere** under `src/receipts/extract/`.
- **Line items are compared positionally.** The flattened paths are
  `line_items[0].qty`, `line_items[1].qty`, … so one inserted or dropped row
  shifts every later index and every later row disagrees — the "differing count
  -> all disputed" cascade `align_line_items` was built to end.

**`align_line_items` shipped and consistency never adopted it.** Tree-wide its
only callers are `eval/metrics.py` and `tests/test_lineitem_align.py`; nothing
under `src/receipts/extract/` references it. **P0.T3's acceptance names two
consumers** — `line_item_f1` and the consistency diff — **and only the first
exists**, so that task is half-met rather than done.

### How to resume

Both halves are one change in `_vote`: compare money paths through
`within_tolerance` instead of by serialisation, and diff `line_items` through
`align_line_items` instead of by flattened index. **Do it before P7.T1**, not
after.

**The import is already there and costs nothing** — `extract/extractor.py`
imports `..validate.{context,report,validator}` and `extract/lineitem_align.py`
already imports `normalize_desc` from `..validate.rules`, the same module
`within_tolerance` lives in. *(An earlier draft of this entry warned that
reaching for `validate/` would be a new dependency edge. It is not, and the
warning was deleted rather than softened — ADR-0048.)*

### Related

- P7.T1 — `run_consistency` is unwired, which is the only reason this is latent.
- `IMPLEMENTATION_PLAN.md` P0.T3 (acceptance half-met) and P2.T1.

---

## ISSUE-024 — Nothing cross-checks the triage line-count against what was extracted

**Status:** OPEN — recorded, not fixed. It is `IMPLEMENTATION_PLAN.md` P2.T3,
which was never built.
**Owner action required:** no. **Discovered:** 2026-08-23, auditing
`IMPLEMENTATION_PLAN.md` against the tree.
**Pre-existing:** yes. **Blocks:** nothing, but it leaves the spec §18
tall-receipt trap open — the failure the rule was specified to catch.

### What is wrong

Spec §18 names a silent failure: a tall receipt is split into strips, some rows
are lost, and **nothing notices** when no subtotal is printed to make the
arithmetic disagree. P2.T3 specifies the guard — triage estimated 12 line items,
6 were extracted, raise a WARN — and it does not exist.

Measured 2026-08-23 over `src/receipts/validate/rules.py`:

- **30 rules are registered** (anchor: lines matching `id = "R[0-9]{3}"`), and
  the highest id is **R070**. P2.T3 asked for the next free id after R070;
  nothing was added.
- **`estimated_line_item_count` appears exactly twice, both inside R013**
  (`LineItemsPresent`): once as a *suppressor* — `if ctx.triage and
  ctx.triage.estimated_line_item_count == 0: return False` — and once to build a
  hint string. R013 fires only when **zero** rows were extracted.
- No rule compares the estimate against `len(r.line_items)` when rows *are*
  present, and no rule in the file mentions truncation.

So the estimate is read, and never used to detect the loss it exists to detect.

### How to resume

A new rule at the next free id after R070, `applies` when
`ctx.triage.estimated_line_item_count` is present and non-zero, `check` raising
WARN on a large mismatch against `len(r.line_items)`. **"Large" is the decision**
— the estimate is a model's guess about a photograph, so a tight threshold will
fire on correct extractions.

**Its RED must be proven the right way** (ADR-0051): put the mutation where the
*rule* computes its answer, not where the test computes its expectation.

### Related

- `IMPLEMENTATION_PLAN.md` P2.T3; `RECEIPT_SYSTEM_SPEC.md` §18.
- ISSUE-005 — the other open rule defect.

---

## ISSUE-025 — Best-attempt selection is proven only in isolation

**Status:** OPEN — recorded, not fixed. It is `IMPLEMENTATION_PLAN.md` P2.T4,
whose acceptance is unmet although the mechanism ships.
**Owner action required:** no. **Discovered:** 2026-08-23, auditing
`IMPLEMENTATION_PLAN.md` against the tree.
**Pre-existing:** yes. **Blocks:** nothing. It is a coverage gap in a guarantee
the pipeline depends on, not a defect in behaviour.

### What is wrong

`extract_with_repair` promises "Returns the BEST attempt, not the last" — so a
repair that makes an extraction *worse* must lose to the original. P2.T4's
acceptance is explicit that this must be **"proven under the pipeline, not just
in isolation."**

Measured 2026-08-23:

- The adversarial direction is pinned **only in isolation**, by
  `test_best_attempt_wins_even_when_repair_makes_it_worse`
  (`tests/test_extractor.py`), which drives `extract_with_repair` directly.
- The pipeline-level repair test,
  `test_repair_resolved_findings_are_kept_as_history`
  (`tests/test_process_receipt.py`), exercises the repair **improving** the
  extraction — broken totals, then good — and asserts findings survive as
  history.
- `git grep -in worse -- tests/test_process_receipt.py` returns **nothing**: no
  pipeline-level test drives a worse repair at all.

So the direction that matters — the pipeline keeping the original when the
repair regresses — is asserted by no test that runs through
`process_receipt`.

*(This entry was nearly filed as DONE off a case-insensitive grep for
"best attempt" that matched two **prose comments** in `pipeline.py` and
`tests/test_process_receipt.py`. Substring evidence answered for a symbol —
review standard 18.)*

### How to resume

One test in `tests/test_process_receipt.py` driving a `_Client` sequence whose
repair pass returns a strictly worse extraction, asserting the persisted receipt
carries the **original** values. Prove it red by making the pipeline keep the
last attempt rather than the best — the mutation belongs where `process_receipt`
selects, not where the test states its expectation (ADR-0051).

### Related

- `IMPLEMENTATION_PLAN.md` P2.T4.
- Review standard 18 — a substring can answer for a declaration.

---

## ISSUE-026 — A receipt cannot enter the system from a browser

**Status:** OPEN — recorded, not fixed. It is the unbuilt half of
`IMPLEMENTATION_PLAN.md` P5.T2.
**Owner action required:** **yes** — whether the upload screen gets built is a
scope decision, not a bug fix.
**Discovered:** 2026-08-23, auditing `IMPLEMENTATION_PLAN.md` against the tree.
**Pre-existing:** yes — no upload UI has ever existed.
**Blocks:** nothing mechanical. It bounds who can use the product: today, only
someone with a shell.

### What is wrong

P5.T2 asks for four things — **upload (drag-drop, progress)**, a receipts list
with filters, a review queue by priority, and an export trigger. Three shipped
(ADR-0046 and the review milestones). **The upload half has no component and
nothing mounts one.**

Measured 2026-08-23:

- `frontend/src/main.tsx` mounts exactly `LoginPage`, `AdminScreen`,
  `ReceiptsScreen` and `ReviewScreen`.
- `find frontend/src -iname "*upload*"` returns **nothing** — there is no
  unmounted component either.
- The only `upload` reference under `frontend/src/api/` is a comment in
  `client.ts` about `POST /upload` being unparseable if a header is set.

**The backend half is complete.** `POST /upload` is registered in
`review/api.py` at `status_code=202`, guarded by `require_upload`, size-bounded
by `settings.max_upload_mb`. It is reachable — by `python -m receipts.cli
ingest`, or by any HTTP client. Just not from the app.

This is one step past **ADR-0046 decision 5** ("a screen nothing mounts is not
delivered"): there is no screen to mount.

### How to resume

It needs a ruling first, because the answer may legitimately be "no". The CLI is
the intended ingestion path for a batch of scanned receipts, and a drag-drop
page is a different product decision from a reviewer's queue. If it is built it
inherits ADR-0027's tokens, ADR-0024's error-recovery contract, and ADR-0046
decision 3 if it paginates anything.

### Related

- ADR-0046 decision 5 — a screen nothing mounts is not delivered.
- `IMPLEMENTATION_PLAN.md` P5.T2.

---

## ISSUE-027 — A PDF is accepted at the door and always fails at `preprocess`

**Status:** OPEN — a live defect, and the only one on this board where an
advertised input type never works.
**Owner action required:** **yes** — wire `expand_pdf`, or stop accepting PDFs.
Both are defensible and §19 advertises PDF support, so it is a decision.
**Discovered:** 2026-08-23, designing the upload screen — a screen has to tell a
user what happens when they drop a PDF, and the answer turned out to be "it is
accepted and then it dies".
**Pre-existing:** yes, on every path. **Blocks:** nothing mechanically; it bounds
what the upload screen may accept.

### What is wrong, measured

`.pdf` is in `_ALLOWED_SUFFIXES`, and `validate_upload` accepts one. Measured
2026-08-23 against a minimal valid one-page PDF:

```
validate_upload -> ACCEPTED | content_type: application/pdf
load_image      -> UnsupportedFormat: Unsupported file extension: '.pdf'
```

So the file is stored, a `pending` row is written, the job is queued, and the run
fails at `preprocess`. Nothing is silently dropped — `failed_stage` is set and the
receipt is visible — so this is loud rather than dangerous. It is still an input
type the product advertises and has never been able to process.

**`expand_pdf` is what should bridge the gap, and it has zero callers.**
`git grep expand_pdf -- src`, re-run 2026-08-24, finds its definition in
`ingest/ingest.py`, its import and its `__all__` entry in `ingest/__init__.py`,
and the `process_receipt` docstring reference quoted below -- **no call among
them**. Neither `ingest_file`, `ingest_bytes`, `cmd_ingest` nor the
`POST /upload` route calls it.

*(This paragraph said "three hits: its own definition, the re-export, and one
comment" until 2026-08-24. There is no comment hit under `src/`, and the hit it
omitted is the docstring the next paragraph quotes and calls false. The
conclusion was right; the evidence for it was never true.)*

**And `process_receipt`'s own docstring states the opposite.** It says *"A PDF
upload is expanded into one image (and one job) per page by ingest -- see
`expand_pdf` -- because one job maps to one receipt id here; a PDF that reached
this function would fail cleanly at `preprocess` rather than silently extracting
only its first page."* The safety net is real and works. The premise is false:
**every** PDF reaches that function, because nothing expands any of them. That is
ADR-0048's shape — a correct sentence about the failure mode, resting on a claim
about the tree that is not true.

### A correction under my own name

`IMPLEMENTATION_PLAN.md`'s definition-of-done row **"`receipts ingest` handles
JPEG, PNG, HEIC, PDF" was ticked on 2026-08-23 during the plan audit, by me, and
it is wrong.** `receipts ingest` *accepts* a PDF — it validates, stores and rows
it — and processing it fails every time. Under any honest reading of a
definition-of-done row that is not "handles". Corrected in the same commit that
files this issue.

### How to resume

Two options, and they are a decision rather than a fix:

- **Wire `expand_pdf` into the ingest path**, one job per page. This is what the
  pipeline docstring already assumes and what §19 advertises. It needs
  `make_image_key` to disambiguate pages, one `ReceiptJob` per page rather than
  per upload, and an answer for what the *upload response* returns when one file
  becomes twelve receipts — today it returns a single `receipt_id`.
- **Drop `.pdf` from `_ALLOWED_SUFFIXES`** and reject it at the door with a
  reason. One line, immediately honest, and it makes the README and §19 wrong
  until they are edited too.

Whichever is chosen, `process_receipt`'s docstring must lose the sentence that
asserts the expansion already happens.

### Related

- `IMPLEMENTATION_PLAN.md` P1.T3 (`ingest/`), and its definition-of-done row.
- ADR-0013 — ingest does not enqueue.
- ADR-0048 — a rationale is a second claim.

---

## ISSUE-028 — The containerised worker can only ever run the `fake` VLM client

**Status:** OPEN. The image fix is one word and is in flight on
`feat/editorial-refresh`; what stays open is the consequence — **every
compose-based run this project has ever done was silently a `fake`-client run**,
whatever `VLM_PROVIDER` it was given.
**Owner action required:** **yes**, but not for the fix — for the re-reading.
Decide which recorded runs, if any, were described as exercising a provider they
could not have reached.
**Discovered:** 2026-08-24, standing the full stack up for the first real
pipeline run. Nothing was looking for it; it surfaced because a run that should
have taken minutes finished instantly.
**Pre-existing:** yes, on every containerised path for as long as the image has
existed. **Blocks:** any claim that a compose run exercised a real model.

### The mechanism, re-derived from the tree rather than relayed

- `pyproject.toml:33` declares `openai = ["openai>=1.50"]` — an **optional
  extra**.
- The committed `Dockerfile:73` runs
  `pip install --no-cache-dir ".[api,worker,postgres,pipeline]"`.
  **`openai` is not among those four.**
- `src/receipts/extract/clients/openai_compat.py:57` imports the SDK **inside
  `OpenAICompatClient.__init__`** (`import openai  # noqa: PLC0415`).

So the import raises `ModuleNotFoundError` at **client construction**, not at
module import. That is why nothing failed at container startup and why the
resulting fall back to `fake` was indistinguishable from a configuration
problem. Confirmed at runtime inside the running worker as well as statically
here.

### One precision, because a wrong reason licenses a wrong fix

This was first reported as "the image has neither `openai` nor `httpx`". Both
are indeed absent, but **only `openai` is load-bearing**: `httpx>=0.27` sits in
the **`dev`** extra (`pyproject.toml:23`), and **nothing under
`src/receipts/` imports it**. Adding `httpx` to the image would fix nothing.
The defect is one missing extra, not two.

### Why no gate saw it, and why that is the familiar shape

The five gates are pytest, ruff, `tsc -b`, vitest and the frontend build
(`scripts/verify.py:88-94`). **Not one of them builds the image or runs a
container.** So this joins the clipped `Theme` control and the progress bar
nobody has watched narrate: a whole capability absent, with everything green.

### Resume

1. The fix is `,openai` in the `Dockerfile` extras list. **Verify it by running
   `import openai` inside the running worker**, not by reading the `Dockerfile`
   — reading the file is what made this invisible for so long.
2. Decide what, if anything, must be re-labelled among recorded compose runs.
3. Consider whether anything should assert that the image can *construct* its
   configured client. Nothing does today, and a check that only reads
   configuration would have passed throughout.

### Related

- ADR-0029 — what the gates certify, and what they do not.
- ADR-0039 — local VLM inference on this box is a liveness check only.
- ADR-0048 — a rationale is a second claim.
- ISSUE-027 — the other live defect where an advertised capability never works.
- ISSUE-029 and ISSUE-030 — both were unreachable until this was fixed.

---

## ISSUE-029 — The job ceiling is shorter than one receipt on this hardware

**Status:** OPEN — live on default configuration.
**Owner action required:** **yes** — it is a decision (raise the ceiling, derive
it from the model's measured cost, or make it explicit per deployment), not a
line to change.
**Discovered:** 2026-08-24, on the first pipeline run that ever reached a real
model. It was unreachable before — see ISSUE-028.
**Pre-existing:** yes. **Blocks:** any containerised run completing on this box.

### Measured, and the comment beside it already described the failure

`src/receipts/worker.py:71` sets `DEFAULT_JOB_TIMEOUT_S = 900`. Its own comment,
lines 67-70, reads: *"a timeout shorter than the work would kill jobs that were
about to succeed and hand them back as failures."* **900 is that value**, now
measured rather than reasoned about.

Observed on receipt `7399df56` under `granite3.2-vision:2b`, from the
container's timestamps: **triage alone took 696s**; `extract` was entered at
696s; the work-horse was killed at **960s wall** — the 900s ceiling plus RQ
monitor slack — **204 seconds into extract**. ADR-0039's standing figure for
this box is ~1896s per receipt.

So with the project's own configured local model on the project's own hardware,
**every receipt is killed mid-extract.**

### Why nothing saw it

Under the fake client a receipt finishes in about 1.9 seconds and cannot
approach a 900s ceiling. ISSUE-028 meant the container could only ever run the
fake client, so this was unreachable until both were true at once.

### Resume

1. Decide the ceiling. A fixed constant that fits one model will not fit
   another; ADR-0039's figure is a floor for this box, not a budget.
2. **Do not treat raising it as closing ISSUE-030.** See there.

---

## ISSUE-030 — A killed work-horse leaves a receipt with no terminal state, ever

**Status:** OPEN. **This one breaks a stated guarantee**, and raising ISSUE-029's
ceiling hides it without closing it.
**Owner action required:** **yes.**
**Discovered:** 2026-08-24, as the consequence of ISSUE-029 firing.
**Pre-existing:** yes, on every path where a job dies without raising.

### The guarantee it breaks

`docs/MEMORY.md:1979-1980`: *"Nothing is silently dropped — every receipt reaches
a terminal state."*

### Why no handler can save it

`process_receipt_job` deliberately has no net around the processing. Its own
docstring says so (`src/receipts/worker.py:246`): *"The one `except` below is
not a second net around the processing"* — that single `except` guards the Redis
progress write. **This is correct design for a throw**: `process_receipt`
re-raises, and RQ records a failed job.

**A SIGKILLed work-horse throws nothing.** No Python exception is raised in that
process at all, so no handler of any kind can run. Verified statically here and
observed in the run.

### What it leaves behind

Minutes after the kill, `GET /receipts/{id}/progress` still returned
`{"status":"pending","stage":"extract"}`. The job sits in `rq:failed:receipts`
and nothing requeues it.

### It also puts a hole in a property that was proved this morning

The processing screen stops on **`status`** and never on `stage` — that is
correct, and it was proved on two independent failure paths. But it assumes
`status` eventually becomes terminal. **Here it never does, so the screen polls
forever.** The defect is not in the screen; the screen is right. The pipeline
has a reachable path to no terminal state at all.

### Resume

1. The **parent** process, not the horse, must mark a receipt whose job died
   without reaching a terminal status. RQ's failed-job registry is where that
   lives.
2. Any kill reaches this, not just a timeout: OOM, a container restart, a
   deploy. That is why it is filed apart from ISSUE-029.
3. Separately, decide whether the screen should say "this receipt has stopped
   making progress" rather than polling indefinitely.

### Related

- ISSUE-029 — the timeout that fires it on default configuration.
- ISSUE-028 — why both were unreachable until 2026-08-24.
- ADR-0022 — failure egress redaction, the other place a failure path is
  contractual.
- ISSUE-031 — found by being forced off the queue path by this one.

---

## ISSUE-031 — Progress narration exists on exactly one of four entry points

**Status:** OPEN — the progress feature is dead by construction on a deployment
the project explicitly supports.
**Owner action required:** **yes** — it is a decision about where the sink
belongs, not a missing argument to add in three places without thinking.
**Discovered:** 2026-08-24, after ISSUE-029 forced the run off the queue path
onto a CLI one. **Pre-existing:** yes, since the progress sink was added.
**Blocks:** any narration on `--inline`, `reprocess` or `process_batch`.

### Re-derived rather than asserted, because "the one X" is the shape this
### project keeps getting wrong

Every `process_receipt(` call site in `src/`:

| site | path | supplies `progress=`? |
|---|---|---|
| `cli.py:874` | `receipts process --inline` | **no** |
| `cli.py:982` | `receipts reprocess` | **no** |
| `pipeline.py:1330` | `process_batch` | **no** |
| `worker.py:272` | the RQ job | **yes**, at `worker.py:279` |

Every `progress=` supplied in `src/`: `pipeline.py:687` (internal, passing it
further down) and `worker.py:279`. (`review/queue.py:599` is `in_progress=`, a
substring false positive — named here so the next person does not re-find it.)

**Four call sites, one narrator.** `stage` is `null` for every receipt processed
off the queue, by construction rather than by accident.

### Why it matters more than "a CLI flag is quiet"

`--inline` is the **documented** path for a single machine or a box with no
Redis — `cli.py:30`, `cli.py:406-407`, and ADR-0013. On such a deployment the
upload screen polls `GET /receipts/{id}/progress`, receives `stage: null` every
time, and the STEPS list stays empty for every receipt forever. **The processing
screen's entire narration feature is dead on a supported deployment**, and no
gate can see it because nothing exercises the screen against an
inline-processed receipt.

### The near-miss that is worth as much as the finding

The run that surfaced this was watching for events between `extract` and
`normalize` — whether the repair loop narrates at all. It was run through
`reprocess`, which is one of the three silent paths. **"The repair loop emits
nothing" would have been true of the observation and false about the cause**,
and it was caught before being reported rather than after. The repair-loop
question therefore **remains open**: it cannot be answered on any path but the
queue.

### Resume

1. Decide where the sink belongs. Threading `progress=` through three more call
   sites is the obvious move and may be the wrong one — a CLI has no Redis to
   write to on the deployment that most needs this.
2. Answering the repair-loop question needs the **queue** path with a raised
   `job_timeout`. `enqueue_receipt` already accepts one as a parameter while
   `_default_submit` uses the constant — see ISSUE-029.
3. Nothing exercises the screen against an inline-processed receipt. Consider
   whether that gap is worth a test before the narration is trusted anywhere.

### Related

- ISSUE-029 — forced the run off the queue path, which is how this was found.
- ADR-0013 — ingest does not enqueue, and `--inline` is the no-Redis path.
- ADR-0048 — a rationale is a second claim; see the near-miss above.
