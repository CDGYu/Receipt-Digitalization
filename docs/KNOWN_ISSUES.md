# Known Issues / Deferred Work

Open problems that are understood but deliberately parked. Each entry records what
happened, what was already fixed, what is still open, and the exact steps to
resume — so picking it up later does not mean re-deriving the diagnosis.

---

## ISSUE-001 — The first real baseline run has never completed

**Status:** OPEN — deferred by the user until the system is built.
**Owner action required:** yes — but **not the provider choice this issue
recommends.** See the ruling immediately below.
**Discovered:** 2026-07-28. **Blocks:** the first real accuracy numbers (spec §16),
threshold calibration (P3.T6 / P8), and any prompt/rule change that should be
re-evaluated.

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

Secondary: Ollama rejects a `tools` payload for models that do not declare the
capability, so the local path runs in JSON mode rather than schema-constrained
tool-use (handled by `VLM_USE_TOOLS` / the provider default in
`factory.py`, but it means the local run is not exercising the intended
structured-output path — see ADR-0002 and the steering rule "structured output via
tool-use, not 'reply in JSON'").

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
   cause of zero accuracy. **Set `VLM_USE_TOOLS=true`** once the chosen model
   declares tool support — `factory.py`'s `_TOOLS_OFF_BY_DEFAULT` contains
   `ollama`, so the local path has never exercised schema-constrained tool-use
   and runs in JSON mode, against ADR-0002 and the steering rule.
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

**Status:** OPEN — the readability half is fixed; surfacing the flag in the
review UI is a design decision, not a bug fix.
**Owner action required:** yes — whether the review screen should show
`is_template_row`, and if so as a read-only marker or as an editable control.
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

**The review UI does not render the flag.** `LineItemsTable` offers six
columns plus a read-only `position`; a flagged row and a purchased row look
identical on screen. So a reviewer approving a receipt cannot see which of its
rows will be absent from the export's review sheet (`_purchases`,
`export/xlsx.py`) and excluded from every arithmetic check (`_purchased`,
`validate/rules.py`).

Making it *readable* was a bug fix, because correctable implies readable.
Making it *editable* is not the same question and is deliberately unanswered:
`position` is the worked precedent — in `_LINE_ITEM_FIELDS`, readable, and
deliberately not offered, with the measurement behind that recorded at
`frontend/src/review/LineItemsTable.tsx`. Being shown a value you cannot edit
is safe; overwriting one you were never shown is not. That asymmetry is why no
allow-list binds the editable set to the correctable one.

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

## ISSUE-010 - The results list has never been opened in a browser

**Opened 2026-08-20**, at the close of the results-list milestone (`b563242` ->
`f0dc7b6`). Not a defect: a stated gap in what this repository can check.

### What is unseen

`/app/receipts` shipped with a new table, a new stylesheet, 21 new census
entries and 22 tests. **No person has looked at it.** Four things follow from
that, in descending order of risk:

1. **The download has never run in a real browser.** `downloadExportWorkbook`
   (`frontend/src/api/receipts.ts`) builds a **detached** anchor, clicks it, and
   revokes the object URL **synchronously** in a `finally`. Both are the
   documented cross-browser failure modes for blob downloads. jsdom stubs
   `click`, so every test here passes either way. This is the milestone's
   headline user-visible effect and it is the least verified thing in it.
2. **Two stacked negative margins** under the heading
   (`frontend/src/receipts/ReceiptsScreen.module.css`). The arithmetic is right
   -- gap `2xl` plus margin `-2xl + xs` leaves `xs` at both joints -- but
   `AdminScreen` does this once and nothing in this repository has done it twice
   in a row.
3. **Whether the not-extracted em dash reads as "missing"** inside a
   right-aligned cell, rather than as a stray hairline.
4. **A `border-radius` on a `border-collapse: collapse` table**, which browsers
   ignore. Pre-existing as a pattern: `admin/TaskTable.module.css` and
   `review/LineItemsTable.module.css` both already do it, so this is a
   repository-wide question rather than this milestone's.

### Why no gate sees any of it

`css: false` in the Vitest config means a `.module.css` import returns a proxy,
so class names are unpinnable by rendering tests; jsdom lays nothing out and
renders no colour; `click` is stubbed; and `e2e/**` is excluded from the Vitest
run, so Playwright is the only instrument that could reach items 1 and 2 and it
is not a gate.

**A claim that this had been checked was written and deleted.**
`frontend/tests/stylesheets.test.ts` carried a sentence saying every census
entry below it was looked at through a browser; the whole-branch review found it
false the moment Task 5 added 21 entries. Deleting it removed the claim, not the
gap. This issue is the gap.

### How to resume

1. `python scripts/seed_review_e2e.py --reset`, then
   `cd frontend && npx playwright test visual` -- the `visual` filter re-seeds,
   and a full run consumes its one queued task by design.
2. Open `/app/receipts` as an admin and as a reviewer, and **click Export**.
   Watch whether the file actually arrives. If it does not, the fix shapes are
   `document.body.appendChild(anchor)` / `anchor.remove()` and revoking on a
   later tick.
3. Look at both themes. **Dark theme at any width remains unseen at every
   surface in this app**, not only here.

### Related

- ADR-0029 - what the gates certify and what they cannot.
- `docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md` - the
  *SUPERSEDED IN PART* block is the record of which surfaces have been seen, at
  which widths, in which theme.

---

## ISSUE-011 - A measured-false spelling survives in four test files

**Opened 2026-08-20.** Pre-existing; recorded now because the results-list
milestone removed one instance and deliberately did not touch the rest.

### What is wrong

Four files state that a mistyped CSS-module key renders `class="undefined"`:
`frontend/tests/admin-screen.test.tsx`,
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

A fix wave editing four files it never otherwise touched is the over-reach
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
