# PAN hardening — closing two leaks, one asymmetry, and three false sentences

**Date:** 2026-07-31 · **Base:** `main @ 446df20` · **Status:** approved, not yet implemented
**Implements:** SPEC §18 (PAN handling), ADR-0007. Follows the Phase 5 ledger's
"NEXT TASK, ALREADY SCOPED: PAN HARDENING"
(`.superpowers/sdd/2026-07-29-review-ui/progress.md:1784-1808`).

---

## 1. Context

`redact_pan` is the guard behind the project's hardest invariant — **a full PAN
is never persisted**. It has been widened twice, and **both widenings produced a
surprise that was only found by executing the code.** This task exists because
the Phase 5 whole-branch review found two residual leaks and the user's ruling
was that the regex deserves its own task with a measured battery rather than a
patch appended to a merge.

Everything below was reproduced against `main @ 446df20` before it was written.
No claim here is recalled.

### 1.1 The four defects

| # | Defect | Severity | Documented anywhere? |
|---|---|---|---|
| **a** | A four-group PAN with a 5+ digit tail is stored **whole** | 17–19 digits in the clear | **No** |
| **b** | A separated run of more than four groups leaves seven digits clear | 7 digits | `repository.py:124-130` |
| **d** | `save_extraction` copies `receipt_number`, `date_raw`, `currency` and every line-item text field **verbatim** | **Whole PAN, plainest spelling** | No |
| **c** | Three prose claims that the measurements falsify | — | they *are* the documentation |

**(a), reproduced:**

```
'4111 1111 1111 11111'   (17 digits) -> unchanged
'4111 1111 1111 111111'  (18 digits) -> unchanged
'4111 1111 1111 1111111' (19 digits) -> unchanged
```

The trailing group is `\d{1,4}` (`repository.py:135`), so the match simply fails
to cover the run and nothing fires. Byte-identical under the pre-Phase-5
pattern — pre-existing, not introduced.

**(b), reproduced:**

```
'4111 1111 1111 1111 111' -> '************1111 111'      7 digits clear
```

The obvious fix — a fifth alternative for longer runs — **is measured worse**:
it lets `'4111 1111 1111 1111 9999 9999'` and `'4111.1111.1111.1111.1111'`
through *whole*, because the long run is consumed and `_mask_pan` then rejects
it for length and returns it untouched. Both failures share one root cause:
**`_mask_pan` fails open.**

**(d), reproduced** through the real `save_extraction`:

```python
ReceiptMeta(number="4111111111111111", date_raw="CARD 4111-1111-1111-1111")
  -> receipts.receipt_number = '4111111111111111'
  -> receipts.date_raw       = 'CARD 4111-1111-1111-1111'
```

`save_extraction` redacts exactly two of its text columns —
`merchant_name_raw` and `payment_method` (`repository.py:373,385`) — and copies
the rest verbatim. A **reviewer** typing that same string gets it masked, because
`_plan_change` runs `redact_pan` over every coerced text value
(`repository.py:1020`). The machine does not. This needs no regex edge case: it
is the plainest PAN spelling there is, in two columns the review UI now displays
and lets a human edit. It was carried into this task from the parked
"`apply_corrections` / `save_extraction` should agree" item, and measurement
promoted it from an inconsistency to the most severe defect on the list.

**(c), the three false sentences:**

- `frontend/src/review/ReceiptForm.tsx:35-37` — "a 13-19 digit card number …
  in the four-group or Amex grouping with any mix of space, dot, hyphen,
  underscore, slash or comma between the groups -- is masked before it reaches
  the column". Falsified by (a). Written *fresh* in the commit whose purpose was
  removing false sentences.
- `docs/adr/0007:27-28` — "separators being any mix of spaces and hyphens".
  True before the Phase 5 widening to `[ .\-_/,]`, false now, and it is the
  governing document.
- `repository.py:124-130` records (b) but not (a) — accurate as far as it goes,
  incomplete about the worse of the two.

### 1.2 The constraint that decides the design

**Real merchant TINs in this corpus are 12–14 digits printed `3-3-3-N`:**

```
'221 193 789 09013'   14 digits   (eval/golden/labels, r001)
'774-423-646-00011'   14 digits   (r002)
'205-741-640-162'     12 digits   (r003)
'103-969-951-00000'   14 digits   (the printer TIN in r001's notes)
```

Fourteen digits sits squarely inside the 13–19 PAN range. These are silent today
**only** because `_PAN_RE` demands `4-4-4-N` or `4-6-5`. So the natural
fail-closed design — *any run of 13+ digits gets masked* — would mask every
merchant TIN in the corpus, and `save_extraction_run` passes the **entire**
extraction payload through `redact_pan` into `extraction_runs.raw_response`, so
`merchant.tax_id` goes through it even though it is not a correctable path.
MEMORY.md records the `VAT Reg. TIN` as the strongest merchant fingerprint
available for Phase 6.

> **The group-shape requirement is load-bearing, not incidental. It is the only
> thing standing between this redaction rule and the corpus's merchant
> fingerprints.** Any future widening that relaxes it must measure the four
> spellings above first.

---

## 2. Decisions

| # | Decision | Rationale |
|---|---|---|
| **C1** | **`_mask_pan` stops failing open.** 13–19 digits → mask; **>19 digits → mask the longest valid PAN-shaped prefix and leave the remainder** | Fail-open is the single root cause of both (a) and (b). Masking the prefix preserves today's behaviour on over-long runs instead of changing two things at once. |
| **C2** | **The `4-4-4-N` alternative becomes a greedy run**, guarded by `(?!\.\d{1,2}(?!\d))` before each separator | Greedy alone closes (a) and (b) but **eats the amount** in `'4111 1111 1111 1111.99'`. The guard refuses a group reached via `.` with 1–2 digits — a decimal fraction, not a PAN group. |
| **C3** | **The group-shape requirement is kept and documented as load-bearing** | §1.2. It protects the corpus TINs. |
| **C4** | **`save_extraction` redacts by default**, over every `str` in its `fields` dict, rather than by an enumerated column list | The list has now been found short twice. Default-on makes a *new* column safe without anyone remembering. |
| **C5** | **A test enumerates the text columns from `__table__.c`** and asserts each is redacted | Makes C4 enforceable: a new column fails RED rather than leaking silently. This is the guarantee, not the code. |
| **C6** | **The `>19`-digit residual is kept and documented, not fixed** | `'4111 1111 1111 1111 9999 9999'` leaves 12 clear. A 24-digit run is not a PAN. Widening a third time to chase it is exactly the move that has surprised twice. |
| **C7** | **ADR-0018 records the measured policy**; ADR-0007 gets a dated correction | The policy is now four interacting rules with non-obvious reasons. It has to be readable by whoever widens this next, in the tracked tree. |

---

## 3. Architecture

### 3.1 The detector

```
SEP  = [ .\-_/,]
FRAC = (?!\.\d{1,2}(?!\d))          # a '.'-reached group of 1-2 digits is a fraction

(?<!\d)(?<!\d\.)
(?:
    \d{4}(?: FRAC SEP \d{4} )+ (?: FRAC SEP \d{1,7} )?   # greedy 4-4-4-... run
  | \d{4} SEP \d{6} SEP \d{5}                            # Amex 4-6-5, unchanged
  | \d{13,19}(?!\.\d)                                    # unseparated, unchanged
)
(?!\d)
```

Only the first alternative changes. The lookbehinds, the Amex and unseparated
alternatives, and the trailing `(?!\d)` are untouched — including the
`(?!\.\d)` that ADR-0007 and the Phase 5 fix wave scoped onto the unseparated
alternative *alone*, which must not be relocated again.

### 3.2 The decision function

`_mask_pan` becomes total over its input rather than returning the match
unchanged when the length check fails:

- `< 13` digits → return the text unchanged (not a PAN).
- `13–19` digits → mask all but the last four.
- `> 19` digits → find the longest `13 ≤ n ≤ 19` prefix that ends on a
  group boundary (the next character is not a digit); mask that prefix, leave
  the remainder. If no such prefix exists, return unchanged.

The prefix search is a bounded loop over at most seven candidate lengths. It is
pure, and its inputs are a string — it stays as testable as the current function.

### 3.3 The redaction boundary

`save_extraction` builds its `fields` dict as it does today, then:

```python
fields = {k: redact_pan(v) if isinstance(v, str) else v for k, v in fields.items()}
fields["card_last4"] = _last4(extraction.payment.card_last4)
```

Money is `Decimal` and dates are `date`/`time` objects, so they are structurally
out of reach — the `isinstance(v, str)` gate is the same one `_plan_change`
already uses at `repository.py:1020`, which is what makes the two sides agree.
`card_last4` keeps its narrower `_last4`, applied after, because `_last4` is a
stronger guarantee than redaction, not a weaker one. `_build_line_items` gets
the same treatment for its text columns.

**This changes what is stored.** `receipt_number`, `date_raw`, `currency` and
the line-item text fields will now be masked when they carry a PAN. That is the
point, but it is a behaviour change and not merely a new guard: fixtures that
happen to contain long digit runs may move.

### 3.4 What does not change

`redact_pan`'s recursion (dict keys and values, list/tuple/set/frozenset,
numeric scalars), `_last4`, `_coerce_money`'s finiteness gate, the
`_bounded_optional_text` boundary, `_plan_change`, and every route. No API path
moves and no schema changes.

---

## 4. Measurements

Run against `main @ 446df20` before any change. `CURRENT` is the shipped
pattern; `PROPOSED` is the §3 design.

### 4.1 Must mask

| value | CURRENT | PROPOSED |
|---|---|---|
| `4111 1111 1111 1111` | `************1111` | `************1111` |
| `4111 1111 1111 11111` | **whole** | `*************1111` |
| `4111 1111 1111 111111` | **whole** | `**************1111` |
| `4111 1111 1111 1111111` | **whole** | `***************1111` |
| `4111 1111 1111 1111 111` | `************1111 111` | `***************1111` |
| `4111 1111 1111 1111.99` | `************1111.99` | `************1111.99` |
| `4111.1111.1111.1111.99` | `************1111.99` | `************1111.99` |
| `CARD 3782 822463 10005 OK` | `CARD ***********0005 OK` | unchanged |
| `CARD NO.4111111111111111` | `CARD NO.************1111` | unchanged |
| `4111 1111-1111 1111` | `************1111` | unchanged |
| `4111_1111_1111_1111` / `/` / `,` | masked | unchanged |
| `4111 1111 1111 1111 9999 9999` | `************1111 9999 9999` | unchanged (C6) |
| `4111.1111.1111.1111.1111` | `************1111.1111` | unchanged (C6) |

### 4.2 Must stay silent

`221 193 789 09013` · `774-423-646-00011` · `205-741-640-162` ·
`103-969-951-00000` · `SUBTOTAL 1234567890123.45` · `2026-07-31` · `555-1234` ·
`1111` · `0.4111111111111111` · `18.0` · `1234.56` · `1234 5678` ·
`TOTAL 2000.00` · `QTY 1234 5678 9012` — all unchanged under both patterns.

### 4.3 The two-direction result

- **Regressions (masked by CURRENT, not by PROPOSED): none.**
- **New false fires (silent under CURRENT, firing under PROPOSED): none.**
- **Amounts destroyed: none.**

### 4.4 A measurement that lied, recorded deliberately

The first prototype used "digits left in the clear" as its score. It ranked
`'4111 1111 1111 1111.99' -> '**************1199'` as an **improvement** — 4
clear digits instead of 6 — while that output has silently eaten the `.99`
amount into the mask. The metric could not see money destruction because it was
never asked about money. `FRAC` (C2) exists because of that failure, and the
lesson generalises: **a masking change must be scored on what it destroys as
well as on what it leaks.** Both columns are in §4.1 for that reason.

---

## 5. Deliverables

| # | Deliverable | Files |
|---|---|---|
| **D1** | The detector fix — C1, C2, C3 | `src/receipts/persist/repository.py` |
| **D2** | Redact-by-default at the writer — C4, C5 | `src/receipts/persist/repository.py`, `tests/test_repository.py` |
| **D3** | The three false sentences + ADR-0018 | `frontend/src/review/ReceiptForm.tsx`, `docs/adr/0007-pan-redaction-and-money-integrity.md`, `docs/adr/0018-pan-masking-policy.md`, `docs/adr/README.md`, `repository.py` docstring |
| **D4** | The corpus-TIN silence battery | `tests/test_repository.py` |
| **D5** | The skip-recoverability regression test | `tests/test_api_write.py` |

**D5 is independent of D1–D4** and should land first, as its own commit. It
binds three properties that are true today and that nothing would catch losing:
a receipt skipped through the review UI is (i) still listed by
`GET /receipts?status=needs_review`, (ii) still `PATCH`-able to `reviewed`, and
(iii) still re-openable by `enqueue_review`. It lives in `tests/test_api_write.py`
because two of the three are HTTP-level; `enqueue_review` is called directly for
(iii) rather than through `receipts reprocess`, so the test does not depend on
the CLI. Landing it before the redaction work keeps the queue's behaviour pinned
while the writer changes underneath it.

---

## 6. Testing

### 6.1 Shape

The PAN battery becomes two explicit tables — `MUST_MASK` (value, expected) and
`MUST_STAY_SILENT` (value) — parametrised, replacing the ad-hoc assertions that
have accumulated across three widenings. §4.1 and §4.2 are the initial contents;
the four corpus TINs (D4) join `MUST_STAY_SILENT` with a comment naming the
label file each came from.

### 6.2 Proving the tests

- **Every masking case is proven RED** with the fix reverted. §4.1's "CURRENT"
  column is the expected RED output, so the revert's result is predicted in
  advance rather than accepted after the fact.
- **The silent cases assert the absence of breakage**, which a RED run cannot
  prove. Each guarantee is therefore reverted **separately**: the `FRAC` guard
  alone, the group-shape requirement alone, and the 13–19 length window alone.
  One variable per mutation, or the result names the wrong cause.
- **D5's three properties are likewise reverted one at a time** — the test must
  go red for the right reason three times, not once.
- **D2's column-enumeration test (C5)** is proven by adding a throwaway
  unredacted text column locally and confirming it fails, then removing it.

### 6.3 Gates

`python scripts/verify.py` (ADR-0017) — pytest, ruff, typecheck, vitest, build.
`python -m pytest` must stay offline and Node-free. The controller re-runs the
gates independently of the implementer's claim, and runs the CLI from outside
the repository, per the environment lesson.

---

## 7. Risks

| Risk | Mitigation |
|---|---|
| **A third widening surprise** | §4 is the battery, in both directions, and it ships as the test. C6 refuses to widen further for the over-long residual. |
| **Masking a merchant TIN** | §1.2's four spellings are committed silent cases (D4). C3 documents *why* the group-shape requirement cannot be relaxed casually. |
| **D2 changes stored values** | Expected and intended, but it is a behaviour change: existing fixtures carrying long digit runs may move, and that is a test-fixture update, not a defect to suppress. |
| **`_mask_pan`'s prefix search is new logic on the hardest invariant** | It is pure, bounded to seven iterations, and every branch is covered by §4.1's over-long rows. |
| **Prose drifting again** | Per the project's rule, no number goes in a comment if it can change without its sentence changing. The `ReceiptForm.tsx` claim is bound by the table it introduces rather than generalised from it. |

---

## 8. Out of scope

- The `>19`-digit residual (C6) — documented, not fixed.
- Login rate limiting, the `corrections` read route, the ASGI entry point, the
  admin release for a claimed task, and the five design §5 error-recovery rows.
  Each is its own named piece of work in the Phase 5 ledger.
- Anything requiring a real provider — ISSUE-001 remains deferred.

---

## 9. References

SPEC §18 · ADR-0001 · ADR-0006 · **ADR-0007** · ADR-0012 · ADR-0015 · ADR-0017 ·
`.superpowers/sdd/2026-07-29-review-ui/progress.md:1715-1808` (the fix wave, the
adjudicated residuals, and the scoped next task) · `docs/MEMORY.md`.
