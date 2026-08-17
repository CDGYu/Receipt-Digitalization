# ADR 0043 — Merchant identity is two-phase: a guess retrieves, a TIN commits

**Status:** Accepted (2026-08-15)
**Builds on:** ADR-0002 (provider abstraction — the tier split in decision 6 rests
on it), ADR-0007 (money integrity — the dedupe key compares `Decimal`),
ADR-0011 (deduplication, whose "semantic dedupe is deliberately not wired in"
bullet this **corrects** — see its `## Correction (2026-08-14)`)
**Relates to:** ADR-0017 (what "passing" means), ADR-0029 (what the gates cannot
see — decision 5 is a new instance), ADR-0030 (a finding is a claim), ADR-0039
(the local path is a liveness check, which is why nothing here is validated yet)

Derived 2026-08-14/15 on `feat/merchant-fingerprinting`. **Re-derive rather than
quote** — every count in this document is a property of the tree at a moment.

---

## Context

Phase 6 needed the pipeline to recognise a receipt's merchant so that merchant's
extraction hints could be fed to the model. The obstacle looks circular: hints
must be chosen **before** extraction, but merchant identity comes **from**
extraction.

It is not circular, because two different identifiers exist at two different
times. `TriageResult.merchant_name_guess` is produced by triage, before
extraction. `Merchant.tax_id` — the VAT Reg. TIN, the strongest identifier on
this corpus — exists only after it.

The guess is produced by `granite3.2-vision:2b`, a model measured as reading
nothing (ADR-0039). **Everything below follows from not trusting it.**

## Decision

### 1. A guess may RETRIEVE a merchant. Only a TIN may CREATE or RENAME one.

`lookup(session, name_guess)` reads. `register(session, extraction)` returns
`None` unless the extraction carries **both** a name and a `tax_id`.
`confirm(session, merchant, tax_id, observed_name)` widens `name_variants` only
when the supplied `tax_id` equals the merchant's own.

A garbage guess can therefore retrieve nothing that exists, and can create and
rename nothing at all.

### 2. Matching is exact over normalized names and known variants. No fuzzy matching.

`normalize_merchant_name` (which already existed, and whose docstring says it is
"for FINGERPRINTING") casefolds and strips legal suffixes, punctuation and branch
codes, so `METRO OIL SUBIC INC.` and `Metro Oil Subic Inc` are one merchant. A
miss yields no hints and today's exact behaviour.

**No edit distance, no prefix match, no substring match.** A wrong match injects
*another merchant's hints* into the prompt, which is worse than injecting none.

### 3. Resolution is TIN-FIRST. Name lookup is the fallback.

`register` runs first; `lookup` by name only when it returns `None`.

**The reverse order — the one this milestone's plan originally specified — makes
`confirm` permanently dead code.** `lookup` matches on
`normalize_merchant_name(name)`, and `confirm` recomputes that same key from that
same string, so `key in _keys(merchant)` always holds and `confirm`'s own guard
discards every call. Under name-first, `confirm` can never widen anything, for
anybody. It also attributes a second business sharing a normalized name to the
incumbent forever.

Both were proven by driving the real registry, not by argument.

### 4. `lookup` returns `None` when a normalized key is ambiguous.

Two merchants with different TINs may legitimately have names that normalize to
one key. `register` **accepts** that row — a distinct TIN is a distinct business,
and letting a name veto a TIN-authorised write would leave a real business
permanently unregisterable. `lookup` then resolves that key to **nothing**.

Ordering the scan would only make a wrong answer stable and silent. No hints
beats another merchant's hints.

`confirm` refuses a spelling whose key **any other merchant already answers to** —
otherwise a merchant's own legitimate TIN could silently de-register a different
merchant.

### 5. A populated `merchant_id` means "resolved to a known merchant". It does NOT mean the TIN was read.

The `lookup` fallback populates `merchant_id` for a TIN-less extraction whose
name matches a registered merchant. This is deliberate — `lookup` refuses
ambiguous keys, so a name match is a real match — but **anything keying off
`merchant_id` must not assume a TIN was involved.** Semantic dedupe keys off it.

### 6. Conditioning is tier-dependent: text hints everywhere, few-shot images on the Cloud tier only.

A few hundred tokens of hint text is free. A few-shot image multiplies inference
cost by `(1 + N)`, and the local primary already costs ~31 minutes per receipt
(ADR-0039). So the Cloud pass is a **richer prompt**, not merely a better model —
the escalation work must account for that.

`few_shots_for` is built and tested and **deliberately never called**, because no
Cloud tier exists yet. It knows nothing about tiers; the pipeline decides.

### 7. A few-shot example comes from `extraction_runs.raw_response`, never from the receipt row.

`review/serializers.py`'s `_export_extraction` is lossy: its own docstring says
`merchant.address`, `tax_id`, `phone`, `branch` and several `meta` fields "are
not columns on `receipts` … left at their schema defaults, never invented." An
example built from it would teach the model **that `merchant.tax_id` is always
null** — the one field decision 1 calls strongest.

Three trust conditions, each independently pinned: `status='reviewed'`; **zero**
`corrections` rows; **exactly one** `extraction_runs` row with
`pass_name='extract'`, because `extract_with_repair` returns the *best* attempt
and nothing records which one won.

### 8. Whatever conditions the prompt must also condition the recorded hash.

`_attempt_prompt_hash` reconstructs each attempt's prompt to recover its
`extraction_runs.prompt_hash`. Hints threaded into the extraction call but not
into that reconstruction produce a hash for a prompt **that was never sent**.

**Measured: with that coupling deliberately broken, `1139 passed, 1 deselected`.**
One test in the entire suite can see it.

### 9. A semantically-duplicated receipt keeps its extraction.

Image dedupe writes an empty `ReceiptExtraction()` because no model was called.
Semantic dedupe runs **post-extraction** — `merchant_id`, `txn_date` and `total`
do not exist before it — so the extraction is already paid for. It is persisted
`rejected` with `duplicate_of` set, carrying the real extraction.

That is what makes a false merge **diagnosable** rather than merely reversible,
and it was the condition on which merging was accepted at all.

**Semantic dedupe never saves a model call.** ADR-0011's §18 cost-control
reasoning applies to the image path only. Citing it here is citing the wrong path.

### 10. The pipeline is stricter than the repository about NULL merchants.

`find_duplicate_by_content` deliberately permits a NULL `merchant_id`, matching
other unresolved-merchant receipts. Correct for its own contract; wrong here,
because under exact-match-only resolution many early receipts have no merchant
and two different shops sharing a date and total would merge. **The pipeline
requires a non-NULL `merchant_id` on both sides.** The repository's contract is
unchanged.

## Consequences

**Accepted, and named so nobody rediscovers them as bugs:**

- Same-merchant, same-date, same-total **repeat purchases will merge.** Inherent
  to the key, equally true for TIN matches. Survivable only because of decision 9.
- `merchants.receipt_count` **can read high**: it counts a rejected duplicate, and
  a reprocess resolving to a different merchant credits the new merchant without
  debiting the old. `receipts merchants list` discloses this in its own
  description.
- A misread TIN under a known name creates a **duplicate merchant row**. Strictly
  better than name-first's failure, which attributes a real business's receipts to
  someone else permanently.
- `lookup` scans every merchant, because the normalizer is Python and cannot run
  in SQL. Fine at one business's supplier count; store a normalized key column if
  it ever isn't.

## What this ADR does not decide

- **Whether any of it improves accuracy.** Nothing here can be measured until
  ISSUE-001's baseline runs. "Hints improve extraction" is a hypothesis.
- **The local-to-Cloud escalation mechanism.** Decision 6 constrains it; it does
  not build it.
- `image_phash`-based merchant matching, and Phase 7 self-consistency.

## Note (2026-08-15) — the milestone was not yet merged

*(Closed by the correction below. Kept as written.)*

`feat/merchant-fingerprinting` is **in flight**, not merged. Tasks 1–6 each had a
task review and a scoped re-review; **Task 7 has neither** — its implementer was
cut off by a connection drop. No whole-branch review has run. Read
`docs/NEXT_SESSION_PROMPT.md` for what remains before this is merge-eligible.

## Correction (2026-08-18) — the close ran, and it changed a repository contract

The note above is closed: Task 7 was reviewed, a whole-branch review ran, and one
fix wave and one scoped re-review followed it.

**Decision 10's closing sentence — "The repository's contract is unchanged" — is
scoped to the NULL-merchant rule, and that rule still holds.**
`find_duplicate_by_content` still permits a NULL `merchant_id` to match other
unresolved rows, and the pipeline is still the stricter side.

**But this branch did change that function's `exclude_id` contract**, in
`31a1491`. `exclude_id` now drops the receipt itself *and every candidate that
resolves back to it*, transitively, through a `resolves_back_to` predicate lifted
out of `_reject_cycle`. Without it, reprocessing an original that had a semantic
duplicate was offered its own copy; `mark_duplicate` refused the cycle by
raising; and the `ValueError` took the run down at the `persist` stage, losing
the extraction that run had just paid for. No command could recover it — only
deleting the copy's row.

One predicate now decides both ends: the finder refuses to offer what the writer
would refuse to link. That is what makes `mark_duplicate`'s raise an invariant
rather than an ordinary outcome of a reprocess.

**The two finders now refuse different sets.** `find_duplicate_by_phash` filters
direct back-links in SQL and does not walk the chain; `find_duplicate_by_content`
walks it. Whether the phash side should be widened to match is **not decided
here**.
