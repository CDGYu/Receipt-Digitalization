# VLM Implementation and Data Sourcing

Companion to `RECEIPT_SYSTEM_SPEC.md`. Covers three things: how the model layer
is built, where training and evaluation data comes from, and how the pieces
connect at runtime.

---

## Contents

| § | Section |
|---|---|
| 1 | The model layer, file by file |
| 2 | Why tool-use instead of "reply in JSON" |
| 3 | Choosing a provider |
| 4 | The call sequence at runtime |
| 5 | Cost and latency budget |
| 6 | Where to get datasets |
| 7 | The handwriting problem |
| 8 | Synthetic data |
| 9 | Your real dataset: the corrections table |
| 10 | Bootstrapping plan |

---

## 1. The model layer, file by file

```
extract/
├── schema.py              Pydantic contract. Depends on nothing.
├── prompts.py             All prompt text. Depends on schema.
├── json_io.py             Tool-schema prep + tolerant response parsing.
├── paths.py               Dotted-path flatten/unflatten.
├── extractor.py           Sequences the three passes. The orchestrator.
└── clients/
    ├── base.py            VLMClient ABC, retry, cost, response cache.
    ├── anthropic_client.py    Hosted.
    ├── openai_compat.py       vLLM / Ollama / any OpenAI-format endpoint.
    └── fake.py                Scripted responses for tests.
```

**The rule that keeps this maintainable:** nothing outside `clients/` imports a
vendor SDK. The pipeline talks to the `VLMClient` interface only. Swapping a
hosted model for a self-hosted Qwen is a config change, not a rewrite — and
more importantly, it means you can A/B two providers against the same golden
set without touching pipeline code.

`extractor.py` owns no prompt text and no validation rules. That separation is
what lets you test prompt changes, rule changes, and orchestration changes
independently instead of guessing which one moved your accuracy.

---

## 2. Why tool-use instead of "reply in JSON"

The extraction call defines a **tool** whose `input_schema` is the JSON Schema
of `ReceiptExtraction`, then forces the model to call it:

```python
tools=[{"name": "record_extraction", "input_schema": build_tool_schema(ReceiptExtraction)}]
tool_choice={"type": "tool", "name": "record_extraction"}
```

The provider constrains generation to the schema, so malformed output becomes
rare rather than a routine failure you retry around. Asking for JSON in prose
and parsing it works, but you will spend real engineering time on markdown
fences, trailing prose, and truncation.

`json_io.py` exists because Pydantic's generated schema is not directly usable
as a tool schema. Two problems, both of which cost real debugging time if you
hit them cold:

**`$ref` / `$defs`.** Pydantic emits nested models as references. Several
providers do not resolve them inside a tool schema and either error or silently
ignore the nested structure — you get back a receipt with no line items and no
explanation. `dereference()` inlines everything.

**`Decimal`.** Pydantic renders a Decimal field as:

```json
{"anyOf": [{"type": "number"},
           {"type": "string", "pattern": "^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$"},
           {"type": "null"}]}
```

That string branch actively invites the model to emit `"949.20"` as a string,
and some providers reject the regex outright. `_collapse_decimal_unions()`
strips it down to `number | null`. There is a test pinning this
(`test_tool_schema_decimals_are_numbers_not_strings`) because it is the kind of
thing that silently reappears on a Pydantic upgrade.

The tolerant parser in `json_io.py` is still there as a fallback path, since
self-hosted servers honour schemas less reliably. It handles fenced blocks,
prose before and after the object, trailing commas, and braces inside strings,
and reports truncation as truncation rather than as a schema violation.

---

## 3. Choosing a provider

Both paths implement the same interface, so this is reversible. Start hosted.

| | Hosted frontier model | Self-hosted open model |
|---|---|---|
| Accuracy on messy receipts | Currently the best available | Close, and closing |
| Handwriting | Usable | Weaker, more variance |
| Cost at low volume | Cheap | Terrible (idle GPU) |
| Cost at high volume | Linear, adds up | Effectively fixed |
| Schema adherence | Strong (tool-use) | Patchier `anyOf` / nullable support |
| Data residency | Leaves your infrastructure | Stays put |
| Setup time | Minutes | Days |

**Rough switching point:** self-hosting starts to make sense somewhere in the
low tens of thousands of receipts per month, and only after accuracy is already
acceptable. Optimising cost before accuracy is the classic way to end up with a
cheap system nobody trusts.

Candidates worth benchmarking on the self-hosted side: the Qwen3-VL family
(strong document understanding, supports grounding/bounding boxes) and dots.ocr
(small, multilingual, purpose-built for document layout). Serve either behind
vLLM and point `OpenAICompatClient` at it:

```bash
vllm serve Qwen/Qwen3-VL-8B-Instruct --limit-mm-per-prompt image=4 --max-model-len 32768
```

The model landscape moves fast. Whatever is best today likely will not be in
six months — which is exactly why the abstraction is worth the hour it takes.

---

## 4. The call sequence at runtime

```
process_receipt(job)
│
├─ preprocess ────────────────────► PreparedImage (b64, image_hash, strips)
│
├─ triage(image, cheap_client) ───► TriageResult
│     │
│     ├─ is_receipt == False ─────► reject, done
│     ├─ legibility unreadable ───► review queue, done
│     └─ otherwise, continue
│
├─ merchants.match_merchant() ────► MerchantHints + up to 2 FewShots
│
├─ extract_with_repair(...)
│     ├─ extract()      ──► normalize() ──► validate()
│     ├─ if has_errors:  repair()  ──► normalize() ──► validate()
│     └─ return min(attempts, key=rank)          # BEST, not last
│
├─ if handwritten or poor legibility:
│     run_consistency(n=3, temp=0.3) ──► disputed field paths
│
├─ score_confidence(extraction, report, triage, consistency)
├─ route(confidence) ─────────────► auto_approved | needs_review
└─ persist + log every VLMResponse to extraction_runs
```

Four design decisions in there are worth understanding before you change them:

**Triage runs on a cheaper model.** It returns no amounts, so it does not need
the strong model. It rejects non-receipts before you pay for extraction and
selects the handwriting prompt variant.

**Few-shot images go first, target receipt last.** Whichever image sits closest
to the instruction text is the one the model treats as the subject. Get this
backwards and it extracts your example instead of the receipt. Pinned by
`test_target_image_is_last_when_few_shots_present`.

**The loop keeps the best attempt, not the last.** Repair passes sometimes make
things worse — on poor-legibility images the model starts second-guessing
readings that were correct. Ranking is `(errors, warnings, nulls)`, so with
errors and warnings tied, the attempt that read more of the receipt wins.

**An unparseable response triggers a re-extract, not a repair.** Asking a model
to correct an object it never produced wastes a call and usually returns the
same broken output.

**Never cache consistency runs.** A cache hit would return the same answer
three times and manufacture perfect agreement, destroying the exact signal the
mechanism exists to produce. `ResponseCache.put()` refuses anything with
`temperature != 0`.

---

## 5. Cost and latency budget

Per receipt, roughly, at ~1500×2000px:

| Pass | Fires | Input tok | Output tok | Notes |
|---|---|---|---|---|
| Triage | 100% | ~1,600 | ~100 | Cheap model |
| Extract | ~97% | ~1,700 | ~600–1,200 | Strong model |
| Repair | ~20–30% | ~3,500 | ~800 | Embeds previous JSON |
| Consistency | handwritten only | 3 × extract | 3 × extract | The expensive one |

Compute actual cost from `PricePer1M` in config — never hardcode prices, they
move. Levers, in order of impact:

1. **Gate on `assess_quality()` before any model call.** A blurry photo costs
   the same as a good one and returns garbage.
2. **Triage on the cheap model.** Roughly half your calls, at a fraction of the
   price.
3. **Cache on `image_hash`.** Reprocessing during development is then free.
   This is a development optimisation more than a production one, and it is the
   difference between 50 API calls per eval run and zero.
4. **Set `CONSISTENCY_RUNS=1` while iterating**, back to 3 for production.
5. **Batch APIs** where available, for backfills.

Latency: 3–8s typical, 15–25s when repair and consistency both fire. The queue
is async, so this only matters for the review UI's perceived responsiveness.

---

## 6. Where to get datasets

Be clear about what you need data *for*. Three different jobs:

- **Smoke testing** — does the pipeline run end to end? Any receipt images.
- **Benchmarking** — how does model A compare to model B? Public datasets.
- **Calibration** — where do I set the auto-approval threshold? **Your own
  receipts, and nothing else.**

Public datasets cannot do the third job. Your merchant mix, capture conditions,
currency, tax conventions, and language are not in any of them.

### Public receipt datasets

| Dataset | Size | Annotations | Useful for |
|---|---|---|---|
| **CORD** | 1,000 Indonesian receipts (800/100/100) | 30 entity types under 4 categories, box-level text + parsing labels | **The best public fit.** The only well-known one with real line-item structure |
| **SROIE** (ICDAR 2019) | 1,000 receipts (626/347) | 4 fields only: company, address, date, total | Header-field accuracy, text localisation. No line items |
| **MC-OCR** | 2,436 Vietnamese receipts | Quality score + key fields | **Mobile-captured** — the most realistic capture conditions of the set |
| **UIT-MLReceipts** | Vietnamese/multilingual | Key fields | Multilingual robustness |
| **WildReceipt** | 1,740 receipts | 25 key categories | Layout variety |
| **ReceiptSense** | Arabic receipts | Receipt understanding | Non-Latin script |
| **FATURA** | Synthetic invoices | Template-generated, multiple annotation formats | Layout experiments; too clean to be a real proxy |
| **FUNSD** | 199 forms | question/answer/header/other | Form structure, not receipts |
| **DocVQA** | 12k+ pages, 50k questions | Q&A | General document understanding |

**CORD and MC-OCR are the closest analogues** if you are working with Southeast
Asian receipts — similar layout conventions, similar thermal print quality,
similar tax-line structure. Start there.

Most of these are on Hugging Face; CORD is commonly available as
`naver-clova-ix/cord-v2`.

### Three cautions

**Check the licence before you build a product on one.** These range from
permissive Creative Commons through research-only competition terms. Several
were released for academic benchmarks and were never licensed for commercial
use. Read the actual terms on the dataset's own page — do not trust a summary,
including this one.

**Their schemas are not your schema.** CORD's 30 entity types and SROIE's 4
fields both need mapping into `ReceiptExtraction`. Write that adapter once, in
`eval/adapters/`, and keep it out of the pipeline.

**A public benchmark score is not a production accuracy claim.** Scoring well
on CORD tells you the model can read Indonesian restaurant receipts. It tells
you very little about the faded thermal slip from the hardware store down the
road.

---

## 7. The handwriting problem

**There is no public handwritten receipt dataset.** This is the single biggest
gap and it is worth planning around rather than discovering in month three.

The closest available things are all wrong in an important way:

- **IAM Handwriting** — 1,539 pages from 657 writers. English prose on forms.
  Real handwriting, but nothing about it resembles a receipt's structure,
  vocabulary, or numeric density.
- **FUNSD** — noisy scanned forms, some handwritten fill-in. Forms, not
  receipts.
- **CASIA-HWDB, KHATT, XFUND** — script-specific handwriting corpora. Useful
  if your handwriting is in those scripts, not otherwise.

So for handwriting you **must** collect your own, and it should be a
deliberate, front-loaded effort:

1. Collect 100–150 real handwritten receipts covering your actual writers.
   Variation between writers is larger than variation between merchants.
2. Photograph them the way they will really be captured — phone, indoor light,
   held in one hand, slightly angled.
3. Label them by hand into the schema. Budget 3–5 minutes each.
4. Hold out 30% from the very start. Do not look at it until you calibrate.

This is a couple of days of tedious work. It is also the only thing that will
tell you whether handwritten receipts are viable at your accuracy bar, and
finding that out in week one is worth a great deal.

Set expectations accordingly: the spec targets 30% auto-approval on handwritten
versus 70% on printed. Budget for permanent human review on that segment.

---

## 8. Synthetic data

Useful for **augmentation and stress-testing**, not as a substitute for real
receipts. Generated receipts are always cleaner and more regular than the real
thing, and a model tuned on them looks great until it meets a crumpled one.

Two things it genuinely helps with:

**Degradation augmentation.** Take your real golden-set images and generate
variants: gaussian blur, JPEG compression at quality 30, perspective warp,
simulated fold lines, glare gradients, thermal fade (reduce contrast in the
lower half). One real receipt becomes eight, and it directly tests the
robustness path that actually breaks in production.

**Layout generation for schema coverage.** Render synthetic receipts with
unusual structures you have not encountered yet — multi-page, split tender,
mixed tax bands, negative line items, 60+ items. Cheap way to find rules that
crash on shapes you did not anticipate.

Keep synthetic data in `eval/synthetic/` and **never mix it into the golden
set**. Report metrics on the two separately. A synthetic score that drifts away
from your real score is a signal your generator has stopped resembling reality.

---

## 9. Your real dataset: the corrections table

Every human correction in the review queue writes a row:

```sql
corrections(receipt_id, field_path, value_before, value_after, corrected_by, created_at)
```

After a few months this is worth more than every public dataset combined,
because it is precisely your merchants, your capture conditions, your failure
modes. Three uses, in increasing order of payoff:

**Merchant hints (immediate).** Group corrections by merchant. If the same
field is wrong on the same merchant repeatedly, that is a hint:
`"Dates on this merchant's receipts are DD/MM/YYYY and print at the bottom."`
Propose via `suggest_hints()`, but require human approval before it enters a
prompt — an auto-applied bad hint is a systematic error generator.

**Few-shot examples (weeks).** A verified extraction — `status='reviewed'` and
zero correction rows — becomes a `FewShot` for that merchant. This is the
highest-leverage accuracy work available once you have volume, and it needs no
ML at all.

**Fine-tuning (months).** At a few thousand corrected pairs, a LoRA fine-tune
of an open model becomes viable. Only worth it once hosted inference cost is
genuinely a problem — it is a cost optimisation, not an accuracy one.

Use `paths.flatten()` to produce field paths so corrections, consistency
diffing, and eval metrics all agree on what a "field" is.

---

## 10. Bootstrapping plan

**Week 1 — data before code.** Collect and label 50–100 of your own receipts
per the composition target in spec §15/M0. Include the handwritten ones.
Hold out 20–30%. Nothing else this week.

**Week 2 — get a signal.** Wire `AnthropicVLMClient` + `extract_with_repair`,
run against the golden set, record baseline field accuracy. Pull CORD in
parallel as a sanity check that your adapter and metrics work on data you did
not label yourself.

**Week 3 — validation and calibration.** Rules are already written. Tune
tolerances against the golden set, then run the threshold sweep and set
auto-approval to hold ≥99% precision.

**Week 4 — review UI.** Corrections start accumulating. This is when the
dataset that actually matters begins to exist.

**Month 2+** — merchant hints, then few-shot, then re-calibrate. Consider
self-hosting only once accuracy is settled and volume justifies it.

One rule to carry through all of it: **re-run the eval harness on every prompt,
model, or rule change, and commit the results.** Grouping by
`prompt_bundle_hash()` makes regressions visible in a diff instead of appearing
three weeks later as an unexplained drop in auto-approval rate.
