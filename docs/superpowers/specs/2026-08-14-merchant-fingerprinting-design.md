# Phase 6 — merchant fingerprinting, hints and few-shot (P6.T1)

**Status:** design approved 2026-08-14. Not yet implemented.
**Milestone:** P6.T1. **Spec:** §8.3 (hints), §6.2 (indexes), §18 (trust the image).
**Blocked for measurement, not for construction:** no accuracy claim in this
document can be validated until ISSUE-001's baseline runs.

---

## 1. Why this is smaller than it looks

The plan describes `merchants/{fingerprint,registry}.py` as greenfield. It is
not. **Eight pieces of this milestone are already written, exported, and called
by nothing** — re-derived from the tree on 2026-08-14 rather than taken from the
plan:

| piece | where | state |
|---|---|---|
| `merchants` table — all seven columns incl. `hints`, `name_variants`, `receipt_count` | `persist/models.py` | exists, nothing writes it |
| `normalize_merchant_name` — casefold, strip legal suffixes, punctuation, branch codes | `normalize/text.py` | **exported, zero callers** |
| `MerchantHints`, `FewShot` | `extract/prompts.py` | exist, never constructed |
| `build_extraction_prompt(triage, hints, few_shots)` | `extract/prompts.py` | accepts both, always passed `None, []` |
| `extract_with_repair(..., few_shots=)` | `extract/extractor.py` | parameter exists, never supplied |
| `save_extraction(..., merchant_id=)` | `persist/repository.py` | keyword exists, never passed |
| `find_duplicate_by_content` / `find_semantic_duplicate` | `persist/repository.py`, `ingest/dedupe.py` | **exported, zero callers** |
| `receipts merchants list \| hints` | `cli.py` | **works today**, incl. the §18 guard |

**The table is the state of the tree *before* this milestone and is not
maintained as the tasks land.** Rows have since been wired —
`find_duplicate_by_content` acquired its first caller in Task 6, and it is not
the only one. Read it as the starting position it was written to establish, and
read the tree for what is true now.

`normalize_merchant_name`'s own docstring says it is "for FINGERPRINTING" and
"NOT the display name". It already turns `METRO OIL SUBIC INC.` into
`metro oil subic`.

**Consequence, and a deviation from the approved design:** there is **no
`fingerprint.py`**. It would have been a wrapper around a purpose-built function
that already exists, which is the kind of module this project's reviews delete.
The only genuinely new file is `merchants/registry.py`.

The CLI already enforces §18: `merchants hints --add` appends `; trust the
image` to any hint that does not already end that way, and says so. Nothing in
this milestone needs to re-implement that.

## 2. The chicken-and-egg problem, and why it is already solved

Hints must be chosen **before** extraction, but the merchant's identity comes
**from** extraction. The schema resolved this before the milestone started:

- **`TriageResult.merchant_name_guess`** exists and is produced by triage, which
  runs first. It is the **lookup** key.
- **`Merchant.tax_id`** — the VAT Reg. TIN, the strongest identifier on this
  corpus — is only available after extraction. It is the **confirmation** key.

So identity is two-phase: guess to *retrieve*, TIN to *commit*.

## 3. Decisions

All four were taken by the user on 2026-08-14 during brainstorming.

**D1 — Conditioning is tier-dependent.** Text hints apply on **both** tiers;
few-shot **images** apply on the **Ollama Cloud tier only**.
*Why:* a few hundred tokens of hint text is free; a few-shot image multiplies
inference cost by `(1 + N)`. The local primary is `granite3.2-vision:2b` at
~31 min/receipt, where that is fatal. This makes the Cloud pass a *richer prompt*
and not merely a better model — which the escalation work must account for.

**D2 — Matching is exact, over normalized names and known variants only.**
No fuzzy matching, no edit distance. A miss means no hints and today's exact
behaviour. `name_variants` grows **only** when an extracted `tax_id` confirms
that a new spelling belongs to a known merchant.
*Why:* `merchant_name_guess` is produced by a model measured as reading nothing.
A wrong match injects **another merchant's hints**, which is worse than none.

**D3 — Semantic dedupe is IN scope.** Recommended against and overruled;
recorded so the reasoning is not relitigated. The recommendation was to ship
fingerprinting alone, because this milestone is otherwise purely additive while
dedupe is not. **The risk is materially lower than the pipeline's comment
implies**, and §7 says why.

**D4 — A semantically-duplicated receipt keeps its extraction.** It is persisted
`rejected` with `duplicate_of` set, carrying the real extraction rather than the
empty one image dedupe writes.
*Why:* the extraction is already paid for, and keeping it is what makes a false
match **diagnosable** rather than merely reversible.

**D5 — A few-shot example must come from a receipt with `status='reviewed'` and
zero rows in `corrections`.** This is `FewShot`'s own docstring rule: "an
unverified example teaches the model your errors."

## 4. What gets built

**`src/receipts/merchants/registry.py`** — the only module that touches the
`merchants` table.

- `lookup(session, name_guess) -> Merchant | None` — normalize via
  `normalize_merchant_name`, match against normalized `canonical_name` or any
  member of `name_variants`. Exact only (D2).
- `confirm(session, merchant, tax_id, observed_name) -> None` — when the
  extracted `tax_id` equals the merchant's, add `observed_name` to
  `name_variants` if new. This is the **only** path that widens matching.
- `register(session, extraction) -> Merchant | None` — create a merchant from a
  **confirmed** extraction (a `tax_id` is required). Returns `None` otherwise, so
  a garbage guess can never create a row.
- `increment(session, merchant) -> None` — bump `receipt_count`.

`few_shots_for(session, storage, merchant, limit)` selects examples under D5. It
lives here because it is a merchant-scoped query. **It knows nothing about
tiers** — the pipeline decides whether to call it at all, which is where D1 is
enforced. A function that returned `[]` "because the tier is local" would be a
second place for that rule to live, and the two would eventually disagree.

> ### Dated note, 2026-08-14 — where a few-shot extraction comes from
>
> **Written while planning, because the obvious source is actively harmful and
> the signature above changed.** `FewShot` needs an `image_b64` *and* a
> `ReceiptExtraction`, so this function needs the storage backend too — hence
> the extra parameter.
>
> **Do not rebuild the extraction with `review/serializers.py`'s
> `_export_extraction`.** It is private and explicitly lossy: its own docstring
> says `merchant.address`, `tax_id`, `phone`, `branch` and several `meta` fields
> "are not columns on `receipts` … left at their schema defaults, never
> invented." A few-shot built from it would teach the model that
> **`merchant.tax_id` is always null** — the one field §2 calls the strongest
> identifier on this corpus. That is worse than no few-shot at all.
>
> **Use `extraction_runs.raw_response` instead**, which is JSONB and holds the
> complete model output. D5 is what makes this sound: `status='reviewed'` with
> **zero** rows in `corrections` means the human changed nothing, so the raw
> response *is* the verified extraction.
>
> **One ambiguity, closed conservatively.** `extract_with_repair` returns the
> **best** attempt, not the last, and `_persist_outcome` writes *every* attempt
> to `extraction_runs` without marking which one was kept. Rather than add a
> column, this milestone only accepts a receipt as a few-shot candidate when it
> has **exactly one** `extraction_runs` row with `pass_name='extract'`. A clean
> single-pass extraction is then unambiguous. This narrows the candidate pool,
> which is acceptable — few-shot needs a handful of examples, not all of them —
> and it needs no migration.

## 5. Flow

```
triage ──> merchant_name_guess
             │
             ├─ registry.lookup ──> Merchant | None
             │                        │
             │                        ├─ hints        (both tiers, D1)
             │                        └─ few_shots    (Cloud tier only, D1+D5)
             ▼
        extract_with_repair(hints, few_shots)
             │
             ├─ tax_id present? ─> registry.confirm / register
             │                     set receipts.merchant_id
             │                     registry.increment
             ▼
        semantic dedupe (§7)
             ▼
        persist
```

## 6. The four wiring points

Each currently carries an `(M5)` comment naming this milestone.

1. **`pipeline.py`, the `extract` stage** — supply `hints` and, on the Cloud
   tier, `few_shots` to `extract_with_repair`.

2. **`_attempt_prompt_hash`** — *the highest-risk line in the milestone.* It
   rebuilds each attempt's prompt to recover its hash, and today hardcodes
   `build_extraction_prompt(triage_result, None, [])`. Its own docstring warns
   that M5 must pass the same values. **If it is missed, every recorded
   `prompt_hash` describes a prompt that was never sent** — silently, with every
   gate green, and the eval harness groups results by `prompt_bundle_hash()`.
   This gets a dedicated test (§9).

3. **Semantic dedupe** — §7.

4. **`merchant_default_currency`** — apply the merchant's `default_currency` at
   its plug-in point. **Locate it by symbol, not by line number**; the file has
   grown. It composes with `_normalizer(settings.default_currency)`, which is the
   global fallback; the merchant value is the more specific one.

## 7. Semantic dedupe

**It cannot run where image dedupe runs.** That stage is pre-extraction;
`merchant_id`, `txn_date` and `total` do not exist until after. So it runs
post-extraction, inside the `persist` stage.

**As built (2026-08-14) it runs after `save_extraction`, not before it.** The
design said "pre-persist"; the implementation reads the dedupe key off the row
`save_extraction` has just written instead of deriving `txn_date` a second time
from the extraction, so the stored value and the key cannot disagree. The
duplicate branch then only ever decorates a stored extraction — which is what
makes "the duplicate keeps what it paid for" structural rather than a
convention. See `pipeline._find_duplicate_content` and ADR-0011's 2026-08-14
correction.

**It therefore never saves a model call.** Image dedupe's "§18 cost control: a
re-upload costs nothing beyond the hash" does **not** carry over — by the time a
semantic duplicate is detectable, it has already been paid for in full. Anyone
citing §18 cost control for this path is citing the wrong path.

**Three safety properties are already implemented** and are why D3's risk is
lower than the pipeline comment suggests:

- `find_duplicate_by_content` **refuses to match without both `txn_date` and
  `total`**. Its docstring: with neither, "every undated or unpriced receipt
  [would be] a duplicate of every other".
- `total` is compared as an exact `Decimal` in Python, not in SQL, so the match
  has one documented semantics on every backend.
- `mark_duplicate` **raises `ValueError` on a dangling FK or a cycle**, walking
  `duplicate_of` to check. It cannot corrupt the chain.

**And a false match is recoverable**: the duplicate keeps a row, `rejected` and
out of exports and the review queue, with `duplicate_of` pointing at the
original. Under D4 it also keeps its extraction, so a wrong merge can be *read*
and not just undone.

**One case needs care.** `find_duplicate_by_content` permits a NULL
`merchant_id`, matching only other unresolved-merchant receipts. That is correct
for re-uploads but means two *different* merchants' receipts can collide if both
fail merchant resolution and share a date and total. Under D2 that will be common
early, because granite resolves few merchants. **This milestone therefore requires
a non-NULL `merchant_id` on both sides before acting on a semantic match.** The
repository function keeps its current, more permissive contract; the *pipeline*
is the stricter caller.

## 8. Safety properties

- A garbage `merchant_name_guess` can **create nothing and rename nothing** —
  every write path requires a confirmed `tax_id` (D2).
- A lookup miss is **behaviourally identical to today**: no hints, no few-shot.
- The `receipts merchants list` `-` placeholder for `receipt_count` becomes a
  real number, and its CLI description — which explains why it prints `-` — must
  be updated in the same change or it becomes a false claim.

## 9. Testing

- **`normalize_merchant_name` is pure** and gets a table of cases, including the
  `METRO OIL SUBIC INC.` / `Metro Oil Subic Inc` collision this corpus needs.
- **Registry writes get a mutation each**, per this project's standard that a pin
  never proven red is not a pin: reverting `confirm`'s variant append, and
  reverting the `tax_id` requirement in `register`, must each fail a test for the
  right reason.
- **The `_attempt_prompt_hash` coupling gets its own test.** A hint that reaches
  the extraction prompt but not the hash reconstruction must fail. This is the
  defect class the test exists for, and it is invisible to every other gate.
- **Semantic dedupe gets both directions**: a true duplicate is caught, and two
  receipts with NULL `merchant_id` sharing a date and total are **not** merged.

## 10. What this design does not decide

- **Any accuracy number.** Nothing here can be measured until ISSUE-001's
  baseline runs. The claim that hints improve extraction is a hypothesis.
- **The escalation mechanism itself** — local-to-Cloud routing is its own work.
  D1 constrains it (the Cloud pass carries a richer prompt) but does not build it.
- **`image_phash`-based merchant matching.** Out of scope; visual similarity as a
  fingerprint is a separate idea.
- **Phase 7 self-consistency**, which plugs into the same extract stage.
- **Whether few-shot helps at all on a 2.5B model.** D1 routes it to Cloud partly
  because that question is unanswerable on the local tier.
