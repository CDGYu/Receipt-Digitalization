# Machine-path currency bound + the intermittent test's fixture race

**Date:** 2026-08-02
**Branch:** `feat/currency-bound-and-fixture-race`
**Baseline:** `main @ b81ba34` (last code commit `0d6cea2`)
**Governing ADRs:** 0001 (nothing here touches money arithmetic), 0006 (the
`ValueError` boundary this extends to the machine path), 0007 ("bounded text is
validated against the model column" — the decision this implements on the
machine path), 0011 (the terminal-state contract the failure semantics rely
on), 0017 (what "passing" means), 0018 (the sink redaction that makes the
error message safe).

Two small, unrelated defects, both fully diagnosed in prior sessions and both
re-measured at this baseline. Bundled onto one branch by user ruling
(2026-08-02) so they share one review→merge cycle.

---

## 1. Defect A — the machine-path `currency` write is unbounded

### 1.1 The chain, measured

- `ReceiptMeta.currency` is `str | None` with no constraints
  (`extract/schema.py:105`).
- `Receipt.currency` is `String(3)` (`persist/models.py:154`).
- The human path coerces through `_bounded_optional_text("currency")`
  (`repository.py:1174`), which reads the limit off the column and raises
  `ValueError: currency holds at most 3 characters, got N (...)` — written
  precisely because "Postgres raises a `DataError` and SQLite stores it
  anyway" (`repository.py:1058-1060`).
- The machine path writes `currency=receipt_meta.currency` verbatim
  (`repository.py:547`, inside `save_extraction`'s fields dict). No guard.

### 1.2 Exposure, measured — a latent contract gap, not a live leak

The live pipeline cannot deliver an over-long value to that write today:

- `process_image` normalizes before anything is saved (`pipeline.py:229-231`):
  `normalize()` **replaces** `receipt.currency` with the output of
  `normalize_currency` (`normalize/__init__.py:73`), and `_as_iso_code`
  whitelists against `_ISO_4217` (`normalize/text.py:107-112`) — so the saved
  value is a recognised ISO code or `None`, never arbitrary model text.
- The failure path saves an **empty** `ReceiptExtraction()` when no row exists
  and touches only status/confidence on update (`pipeline.py:771-778`);
  the duplicate path likewise saves an empty extraction (`pipeline.py:601`).

What remains exposed is `save_extraction` as a public §14.8 contract: direct
callers (tests, future code) and any future re-wiring that saves an
un-normalized extraction would silently corrupt on SQLite and kill the
receipt with a `DataError` mid-transaction on Postgres.

**Scope is exactly one column.** A `String(\d+)` scan of `persist/models.py`
finds six bounded columns; of those `save_extraction` writes from model text,
`currency` (`String(3)`) is the only one unguarded — `card_last4`
(`String(4)`) has the stronger `_last4` guarantee, `image_phash`
(`String(16)`) is system-minted and structurally excluded from the redaction
pass, and the remaining model-text columns are unbounded `Text`.

### 1.3 The decision (user ruling, 2026-08-02): raise `ValueError`

`save_extraction` runs the machine value through the **same coercer the human
path already uses** — `_bounded_optional_text("currency")`, built once at
module level and applied in the fields dict. Over-long → `ValueError` naming
the column, ADR-0006's boundary, exactly as this function already behaves for
the reviewed-row refusal (`repository.py:519`).

Why raise rather than coerce to `None`: one column, one bound, one behaviour —
the human and machine paths must not disagree about the same column; and on
the live path the raise is unreachable by construction (§1.2), so it is pure
contract enforcement — a regression that saves un-normalized data fails
loudly at the boundary instead of silently on SQLite / fatally on Postgres.
Coercing to `None` was considered and refused: it hides malformed input and
diverges from `_RECEIPT_FIELDS`' semantics for the identical column.

Consequences, checked against the code:

- If the raise ever fires inside the pipeline, the stage wrapper lands the
  receipt `needs_review` naming the stage (ADR-0011); `_persist_failure`
  itself cannot re-trip the bound because it saves an empty extraction —
  no failure loop, nothing dropped.
- A PAN-shaped currency quoted in the `ValueError` message is already covered:
  `enqueue_review` redacts `reason` at the sink, and ADR-0018 records
  `_bounded_optional_text`'s message as exactly the kind of text that pass
  exists for.
- The coercer changes nothing else: `_coerce_optional_text` is exactly
  `None if value is None else str(value)` (`repository.py:1049-1050`) — no
  stripping, no empty-string mapping — so for a `str | None` input the only
  behavioural addition is the length check. (An earlier draft of this section
  claimed stripping; falsified by reading the function.)

### 1.4 What must not change

- The blanket §18 redaction pass over the fields dict stays exactly as it is;
  the bound applies at field construction, before that pass, and a bounded
  ≤3-char value cannot be lengthened by masking.
- `_bounded_optional_text` itself is untouched — it already does the job.
- No behaviour change on the live pipeline path (§1.2), pinned by test.
- **One thing does change (user ruling, 2026-08-02): the §18 column walk's
  seeding contract for `currency`.** `test_every_text_column_save_extraction_writes_is_redacted`
  seeded a PAN through `receipt.currency`, which the bound now rejects, so
  `currency` becomes that walk's **second** named structural exclusion
  alongside `card_last4` and is seeded with a bounded (≤3-character) code
  instead. The rationale is `card_last4`'s exactly: a value that fits
  `String(3)` cannot contain a 13-digit PAN, so the bound is the stronger
  guarantee. Cost, stated as ADR-0018 states `card_last4`'s: a future second
  column sourced from `receipt.currency` would not be covered by that walk.
  Recorded as a dated correction in ADR-0018.

### 1.5 Tests

1. **RED first:** `save_extraction` with an over-long **letters-only**
   `currency` (e.g. `"PESO PHILIPPINES"` — letters so the §18 redaction pass
   is orthogonal to what this test measures; an all-digit over-long value
   would be PAN-shaped and masked first) currently stores it on SQLite —
   after the fix, `pytest.raises(ValueError)` with the message naming
   `currency`. Proven to fail with the fix reverted.
2. Green path: a 3-character code and `None` still store unchanged.
3. Absence-of-breakage (revert-separately per review standard 3): the
   end-to-end path — a scripted client emitting a garbage over-long currency
   ends with the receipt persisted, `currency` `None` (normalize refused it),
   and a terminal status — proving the bound is unreachable from
   `process_receipt` and the pipeline behaviour did not move.

**Note (2026-08-02, found during implementation).** §1.2 reasoned that what
remains exposed is "direct callers (tests, future code)" saving an
un-normalized extraction. That class had a **live instance already in the
suite**, which this design did not check for:
`test_every_text_column_save_extraction_writes_is_redacted` calls
`save_extraction` directly with an un-normalized extraction and deliberately
seeds a PAN into every `str`-typed field, `receipt.currency` included — so the
bound raised on it and the test went RED, the sole failure in the suite. It was
the correct RED for the wrong test: the bound working exactly as designed, on a
caller the design had reasoned about abstractly without grepping for it. Fixed
per §1.4's ruling bullet (second named exclusion, bounded seed, docstring
rationale rewritten); that test's docstring had itself recorded the unbounded
currency as an out-of-scope gap it "does not depend on", which this change
retires. Lesson for the next design in this repo: when a change tightens a
contract at a public boundary, enumerate the boundary's existing callers in the
test suite, not only in `src/`.

---

## 2. Defect B — the intermittent test's fixture race

### 2.1 The diagnosis (done in prior sessions; premises re-confirmed at this baseline)

`tests/test_cli_pipeline.py::test_inline_one_failing_receipt_does_not_abandon_the_others`
fails intermittently under load with a receipt landing `REJECTED` where it
expects `AUTO_APPROVED`. It is **not** ordering (pytest-randomly is not
installed; pytest11 entry points: `anyio`, `superclaude`). The race:

- `_png_bytes()` (`tests/test_cli_pipeline.py:124-127`) returns a
  **byte-identical** uniform 900×1400 PNG on every call.
- `_job` (`:130-140`) stores one per receipt, so all three receipts in the
  test share a sha256 **and** a dHash — a uniform image of any shade hashes
  to the all-zero dHash, because dHash keys on gradient direction
  (`ingest/dedupe.py:28-34`).
- Dedupe treats hashes within **5 bits** as duplicates
  (`find_duplicate_by_phash`, `repository.py:884`), so whichever receipt
  commits first makes the others duplicates → `REJECTED`.

Reproduced 11/12 under six CPU burners; corroborated twice since by fresh
agents hitting it unprompted on ordinary full runs.

### 2.2 The decision: distinct blobs per receipt, distinct **structurally**

Varying only the fill colour fixes the sha256 but **not** the dHash (uniform
in → all-zero hash out, at any shade). The fixture must vary the image's
*gradient structure* per call — e.g. a dark band whose position derives from a
per-call counter — so the three images differ pairwise by **well more than
the 5-bit threshold**.

Shape of the change (the plan will fix exact code):

- `_png_bytes` varies per call by default via a module-level counter (an
  `itertools.count()` driving the band's position), so every existing caller
  gets distinct blobs without a signature change at the call sites; every
  image remains a receipt-shaped 900×1400 PNG.
- **Callers checked first:** if any test in the module deliberately relies on
  two jobs sharing bytes (a dedupe assertion), the helper gains an explicit
  way to request identical bytes for that caller alone; the default stays
  distinct. If no such caller exists, the counter alone is the change.

**Note (2026-08-02, found during implementation).** The conditional above
fired: the plan had resolved it the other way ("no caller needs it, so none is
added"), and that resolution is what was wrong. Two callers depend on
byte-identical images, both *transitively* through `_pending_receipt` rather
than by calling `_job` directly, which is why a check of `_job`'s direct
callers missed them.
`test_reprocessing_a_duplicate_linked_original_never_empties_it` breaks
outright under distinct images — the copy it builds is meant to *be* a dedupe
duplicate, which is what lets it run with an empty client script, dedupe
having short-circuited extraction before the VLM is called.
`test_a_receipt_whose_run_failed_is_never_matched_as_a_dedupe_original` is
worse: it stays green while going vacuous, since with distinct images the
second receipt would not match even if the failed run *had* stored its hash
— which is the mutation that test exists to catch. (Measured in review: with
that mutation applied, the shared blob is matched, while distinct blobs sit
31 bits apart and go unmatched. Deleting the empty-`image_phash` skip is
*not* the discriminating mutation — `phash_distance` raises on `""`.)

Both now pass one shared blob explicitly through `_job`'s sibling-style
`data=` override (`tests/test_process_receipt.py:155-158`); the per-call
default stays distinct.

### 2.3 Tests

1. **The deterministic pin (RED against the current fixture):** the images the
   fixture hands to N jobs are pairwise distinct in sha256 **and** pairwise
   `phash_distance(compute_phash(...)) > 5` — asserted directly, no load
   generation, no flakiness. Fails today (distance 0), passes after.
2. The intermittent test itself runs green; the fix does not attempt to
   reproduce the probabilistic race in CI — the deterministic pin is the
   guard, the diagnosis is the evidence.

---

## 3. Verification

`python scripts/verify.py` all five gates; pytest counts read from junitxml
(the piped summary line clips in this environment); `python -m ruff check .`.
Both new tests proven to fail with their fix reverted, separately. No frontend
file moves, so the Vitest count must not move either.

## 4. ADRs

No new ADR. Defect A implements ADR-0007's existing bounded-text decision on
the machine path under ADR-0006's error convention; Defect B is test-only.
The design doc is the record; the handoff pair carries the volatile numbers.
