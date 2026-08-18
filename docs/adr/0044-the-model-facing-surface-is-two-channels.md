# ADR 0044 — The model-facing surface is two channels, and a prose guarantee is held lexically

**Status:** Accepted (2026-08-19)
**Builds on:** ADR-0002 (provider abstraction — decision 3's client gate is its
consequence), ADR-0027 (`null` != `0` != empty — decision 5 rests on it),
ADR-0040 (what field accuracy counts, whose decisions 1 and 2 were **corrected
in place** by `0669678` — this ADR records why)
**Relates to:** ADR-0028 (prose claims need re-derivation), ADR-0030 (a finding
is a claim), ADR-0032 (a correction that over-reaches), ADR-0039 (the local path
is a liveness check), ADR-0042 (fix-wave prose is the defect surface)

Derived 2026-08-18/19 on `feat/buyer-and-blank-rows`. **Re-derive rather than
quote** — every count here is a property of the tree at a moment.

---

## Context

The branch added two things: a `buyer` block (the *Sold To* party on a
Philippine BIR invoice, distinct from the merchant who sold), and
`is_template_row`, a flag for a pre-printed product row the form leaves blank.
Both had to reach the model, the database, the validator, the evaluation
harness, the export and the review UI.

Two questions dominated the work, and neither was the feature.

**The first: where does the model learn what it is being asked?** The obvious
answer is `src/receipts/extract/prompts.py`. It is wrong, and being wrong about
it cost three separate rounds on this branch.

**The second: what does it mean to guarantee something written in prose?** The
prompt is a document. Its guarantees are sentences. A test that pins a sentence
can only pin the letters it was told to look for.

---

## Decision

### 1. The model-facing surface is `prompts.py` PLUS every `Field(description=)` in `schema.py`. Any claim about what a model can or cannot know must name both.

`build_tool_schema` calls `model_json_schema()`, so Pydantic `description=` text
and class docstrings ship to the model on every extraction and repair call.
`prompts.py`'s own `_bundle_text()` docstring already said so.

It was established on this branch by measurement in Task 6 round 0 — and the
same error recurred **twice afterwards**, both times by someone who had read
that measurement:

- A test asserting a prompt guarantee scanned only the rendered prompt. Moving
  the destructive instruction into `LineItem.is_template_row`'s `description=`
  left it green. The fix ran the same clause loop over the tool schema.
- An eval fixture built as "a model following the shipped prompt perfectly"
  omitted `totals.prices_include_tax`, because that field appears nowhere in
  `prompts.py`. It appears in the tool schema, with a description ending *"null
  if the receipt does not state which — do not guess."* The fixture was not the
  shipped contract, and a receipt was reported at 23/24 that in fact reaches
  24/24.

The recurrence is the finding. One measurement, correctly recorded, did not stop
two later people reasoning from `prompts.py` alone. **Naming both channels is
therefore a rule, not a reminder.**

### 2. That same sentence is the labelling rule, and the labels follow it.

*"null if the receipt does not state which — do not guess."* r002's form prints
"Total Sales (VAT Inclusive)", so the receipt states it: `true`. r001 prints no
such phrase: `null`. Decisively, **r001 is arithmetically identical to r002** —
line amount equals total amount due, subtotal net of VAT — which is precisely
why arithmetic cannot be the criterion and the printed phrase must be.

A golden label records what the paper says. It is not a prediction of what the
model will produce, and it is never adjusted to make a score reachable.

### 3. "The model receives the tool schema" is true of the tool path and false of Ollama's default.

`AnthropicVLMClient` sends the schema unconditionally. `OpenAICompatClient`
gates it on `use_tools`, and `_TOOLS_OFF_BY_DEFAULT` contains `ollama`, so the
JSON-mode fallback sends `response_format: json_object` and **no schema at
all**. Under the project's Ollama-only ruling, the descriptions reach the model
only with `VLM_USE_TOOLS=true`.

So decision 1's surface is two channels, and one of them is switchable at
runtime. A ceiling observed under JSON mode is a client-configuration artefact,
not a labelling or prompt defect, and must be recorded as such.

### 4. A prose guarantee is held by lexical pins, which is weaker than it reads. Write down what they miss, beside them.

Five fix rounds went into one test asserting that the shipped prompt never
instructs the model to skip an unreadable row. It began as an assertion that
could not fail. It ends catching a plain deletion, a semantic inversion, a decoy
block, a vacuity rewording, three widening shapes, a line-wrapped evasion, and a
relocation into the tool schema — **each proven individually by mutating the
source and watching it fail.**

What it still misses is written beside it: synonyms, paraphrase, polarity.

Two mechanisms are worth keeping because neither is guessable:

- **Line wrapping defeats substring matching.** `prompts.py` hard-wraps at ~85
  columns and most keyed phrases are multi-word, so a phrase split across two
  lines is invisible to a raw substring test. Normalise whitespace before
  matching. This is not a reason to add vocabulary.
- **In the tool-schema channel the over-fire trigger is JSON structure, not
  prose.** The clause splitter barely splits JSON. Re-derived 2026-08-19: the
  extraction tool schema serialises to ~9,100 characters and splits into **14**
  clauses, the largest 3,360; the full bundle splits into **141**, largest
  1,706. A field description saying nothing whatsoever about legibility fails
  anyway, matched against a `legibility` enum value more than 1,500 characters
  away inside the same clause. That token is permanent; no rewording of the
  description removes it.

  Those two clause counts are also a worked example of ADR-0028. A review
  reported 14, the controller relayed 14, the implementer measured 141 and wrote
  down what it measured — and the controller recorded that as a correction. It
  was not. **Both numbers were right about different objects**: 14 clauses for
  the schema blob, 141 for the bundle that contains it. A count is meaningless
  without the thing it counts, and "your number was wrong" is itself a claim
  that needs re-deriving before it is written down.

The structural fix — making the guarantee a property of `schema.py` and the
pipeline rather than of the prompt's wording — is not taken here and is recorded
as open.

### 5. A self-report is grouped by what kind of claim it is, not by where it sits in the tree. This corrects ADR-0040.

ADR-0040 decision 1 said group comes from the path string alone — *"a prefix
test, not a list of field names"*. `is_template_row` is the first leaf that is a
claim about the paper while living under a path prefix that averages, and
`_is_filled` counts `False` as filled. So it landed in the transcription
denominator, **correct for free on every row that is not blank, at one free
point per line item.**

Measured on r001 with a prediction that got the row count right and read
nothing: 2/17 → 3/18. That re-opened the inflation `FieldBreakdown` exists to
prevent, on the one number this project exists to state honestly.

The set of such leaves is now declared in **one** place the grouping reads, with
the admission rule stated beside it and a worked near-miss named. The property
was checked by adding a brand-new field to the schema: the label pins failed on
all four files naming it, with zero edits to the test — the set closes the class
by difference, not by enumeration.

### 6. The pins close wholesale rot and schema drift. They do not establish truth, and per-label content rot stays open by design.

A per-receipt pin on label content is either tautological (`label == label`
scores perfectly under every mutation, confirmed by building it) or a
transcription of the label into a test, which fires when someone legitimately
re-reads the image. Three pins were added that are neither, and each was proven
red by mutation.

They are corpus-level and existential by necessity: "every label records a
buyer" breaks the first time a receipt arrives without a *Sold To* block;
"at least one does" goes red exactly when the buyer truth leaves the corpus.

**Re-reading the image remains the only instrument for per-label content.** The
pins' job is to make wholesale rot and schema drift loud. ISSUE-004 records the
residual rather than hiding it.

---

## Consequences

**The evaluation harness now measures the behaviour the pipeline ships.** All
three golden receipts reach 100% field accuracy with zero hallucinations and
zero structural mismatch, against r001's 12/17 with 20 hallucinations before.
That is not the system improving; it is the ruler being corrected. `MAX_FLOOR`
did not move and every floor gained headroom.

**Two failure modes recurred often enough to name.**

*Reasoning from one channel.* Three times, by three different agents, one of
whom had personally measured the counter-example.

*A confident claim about what a test guarantees, written without running
anything.* Seven prose corrections across five rounds on a single test file.
Every one was a sentence describing a guarantee, and the sentences were wrong
while the code was right. The corrective is uncomfortable and cheap: **before
writing that a test catches something, mutate the source and watch it fail.**

**Two near-misses are worth more than the successes.** An implementer's
mutation failed to reproduce a finding and it nearly wrote that up as a
refutation — then found its own construction was wrong. Another's first
array-order mutation re-assigned the positions afterwards, restoring the
invariant, and the pin correctly stayed green. Both were caught by reading the
result rather than trusting the intent. **A failed reproduction is evidence
about the reproduction first, and about the finding only second.**

**Open, recorded rather than fixed:** ISSUE-003 (a blank row drops the unit the
form prints on it — the contract scopes a template row to its printed name, and
the ruling that keeps `unit: null` is itself unguarded), ISSUE-004 (nothing
checks a label against its photograph), ISSUE-005 (`R051`'s message promises
printed order while its check accepts any permutation). Also open: the prompt
guarantee of decision 4 is still lexical, and `prompt_bundle_hash()` has no
PRODUCTION caller -- only tests call it -- while a shipped prompt rule depends
on it covering the schema text.
