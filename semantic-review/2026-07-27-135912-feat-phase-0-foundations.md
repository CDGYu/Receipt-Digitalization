# Phase 0/1 foundations: normalize, preprocess, ingest, export, and the eval harness

This branch lays the offline groundwork under the extraction/validation core that already exists: a normalization layer (money, dates, text, currency), image preprocessing (orient/resize/split, document deskew, quality gating), an ingest front door (upload validation, perceptual-hash and semantic dedupe, PDF rasterization, blob storage), a minimal XLSX export, a shared greedy line-item aligner, and the golden-set eval harness with its six §16 metrics. The through-line is a strict "reformat, never invent" discipline — every reader refuses (`None` / `(None, True)` / uncropped) rather than guess — which is the right bias for a system whose value is auto-approval precision. All 232 tests pass offline and `ruff check .` is clean; the heavy image/Excel deps are import-guarded so the core still loads without them.

**Watch for:** `parse_date` reaches for `date.today()` on two-digit years, making an otherwise-pure parser wall-clock-dependent and leaving that branch untested (confirmed); `make_image_key` builds keys from `datetime.now()` yet its docstring promises every variant of a receipt lands "under one folder," which a month rollover breaks (confirmed, latent); `composition_stats` can raise `JSONDecodeError` on a malformed manifest despite documenting that it never raises (confirmed). No money/float leak, value invention, input mutation, or cross-module contract mismatch was found.

**Verdict**: APPROVED

## High-level view

The spine of the branch is a refusal discipline that runs the same way in every reader: `parse_money` returns `None` the moment a letter or stray symbol survives stripping, `parse_date` returns `(None, True)` for a genuinely ambiguous DD/MM vs MM/DD, `normalize_currency` refuses a bare `$` rather than defaulting to USD, `auto_crop` hands back the uncropped image when it isn't confident, and `is_processable` only ever rejects. Null in, null out, all the way through. `normalize()` deep-copies its input and never touches the already-`Decimal` money fields.

Determinism is strong except for one spot: `parse_date` hard-codes `date.today()` to expand two-digit years. The result is stable except at the 50-year sliding-window edge, and every date test uses a four-digit year, so the wall-clock branch is both non-pure and uncovered. Threading a reference date fixes both.

Storage keys are time-stamped rather than receipt-stable. `make_image_key` partitions by the current year/month, which is fine for the single ingest-time write that exists today (the key is stored on the job), but the docstring's "every variant under one folder" promise will not survive derived variants minted in a later month.

The eval layer scores money the way the validator does — it flattens the python-mode dump so `Decimal`s stay `Decimal`, and compares through `within_tolerance` rather than `==` — so eval and validation can't disagree about a cent. One asymmetry stands out: the critical-field gate treats a null date as agreement but a null total as disagreement, so a truth receipt with no total can never be scored critical-correct.

Ingest decides file type from magic bytes, not the extension, and gates size (including empty) before anything touches storage. PDF rasterization closes the document but not the per-page render objects. Export keeps `float` strictly at the openpyxl cell boundary, which is the sanctioned display exception, and the money-path float guard test structurally enforces `Decimal` on every schema money field.

<details>
<summary>Issues (6)</summary>

1. **Wall-clock date parsing** — `parse_date` (`normalize/dates.py:51`) expands two-digit years with `date.today()`, so an otherwise-pure parser depends on the run date and the branch is untested. Thread a reference date (capture/ingest date or an injected `today`). Non-blocking.
2. **Time-stamped storage keys** — `make_image_key` (`ingest/storage.py:133`) keys by `datetime.now()` while the docstring promises all variants of a receipt share one folder; a month rollover breaks that once derived variants are minted. Use a receipt-stable prefix or pass the partition date in. Latent.
3. **`composition_stats` can raise** — `load_manifest` (`eval/golden_set.py:132`) calls `json.loads` unguarded, so a malformed `manifest.json` raises out of the one helper documented to never raise. Catch the parse error and treat it as `{}` or a reported problem.
4. **Null-total critical-field asymmetry** — `critical_field_accuracy` (`eval/metrics.py:167`) counts a null date as agreement but a null total as disagreement, so a truth receipt with no total can never score critical-correct. Confirm this is intended or handle both fields the same way.
5. **Unclosed PDF page/bitmap objects** — `expand_pdf` (`ingest/ingest.py:176-180`) closes the document but not each `page`/render bitmap; not a true leak, but it triggers pypdfium2 warnings and holds native buffers. Close them inside the loop.
6. **`export_workbook` short `ids`** — passing an `ids` list shorter than `receipts` (`export/xlsx.py:96`) raises `IndexError` mid-write. Validate lengths up front.

</details>

<details>
<summary>Details</summary>

### "Refuse rather than guess" is the spine of the branch

Every reader on the path treats ambiguity as a reason to stop, not a reason to pick. `parse_money` strips currency symbols, thousands separators, and accounting/trailing signs, then bails to `None` if any letter or stray symbol is left (`_INVALID_NUMERIC_RE`) — turning a handwritten `O` into `0` inside a price is exactly the silent corruption the project exists to prevent, and this refuses it. A stray `float` handed in by a manual caller is routed through `Decimal(str(value))` so binary noise never enters the money path. `parse_date` resolves an order only when exactly one component exceeds 12; when both are `<= 12` it returns `(None, True)` and `normalize()` parks the verbatim string in `date_raw` and leaves the canonical date null. `normalize_currency` resolves an ISO 4217 code by fixed precedence and refuses a bare symbol (`$` is USD/CAD/AUD/…), never inferring currency from language. On the pixel side, `auto_crop` returns `(img, False)` unless a convex quad covering at least 25% of the frame is found, and `is_processable` only ever rejects the obviously unusable. It is the right posture for a >=99% auto-approve-precision target, and it's applied consistently across every reader in the branch.

### The one wall-clock read: `parse_date` and two-digit years

`normalize/dates.py:51` expands a two-digit year with `expand_two_digit_year(int(tail), date.today())`. `expand_two_digit_year` itself is a clean pure function — it takes the reference date as a parameter and is unit-tested at the window edges — but `parse_date` supplies `date.today()` implicitly, so the same input string (`"13/04/26"`) produces a date that depends on the day the code runs. In practice the sliding window only flips at its ~50-year boundary, so re-running the eval next week is stable; the concern is that a layer documented as pure and built for reproducible evaluation has a hidden dependency on the clock, and it is the one branch of `parse_date` with no test — every date test in the suite uses a four-digit year, so `date.today()` is never exercised. Threading a reference date (the capture/ingest date, or an injected `today`) makes the function deterministic and testable at once. Confidence: confirmed. This does not corrupt money and does not block the merge, but it is the highest-value fix in the branch.

### Storage keys are time-stamped, not receipt-stable

`ingest/storage.py:133` builds `receipts/{yyyy}/{mm}/{id}/{variant}.jpg` from `datetime.now(UTC)`, while the docstring promises "the same receipt variant always maps to the same place" and that keying by `receipt_id` keeps "every variant of a receipt (original, deskewed, …) together under one folder." Both claims hold only while every variant of a receipt is keyed within the same calendar month. Today that is true by accident: the only call mints the `original` key once at ingest and stores it on the `ReceiptJob`, so lookups read the stored key and nothing recomputes it. The trap is latent — when a later phase generates a `deskewed` (or any derived) variant at a different time, or any code reconstructs a key rather than reading the stored one, a month rollover scatters a receipt's variants across `{mm}` folders and a reconstructed lookup misses. Either drop the timestamp for a receipt-stable prefix, or accept the partition date as a parameter so the caller controls it. Confidence: confirmed (docstring-vs-behavior), latent impact.

### Eval scores money the way the validator does

The load-bearing subtlety here is handled correctly: `field_accuracy` calls `flatten(predicted.model_dump())` — the python-mode dump — so money stays `Decimal` and `within_tolerance` actually fires. `flatten(model)` would internally `model_dump(mode="json")` and compare `"949.20"` against `"949.21"` as strings, scoring a within-a-cent read as a mismatch; the code and its comment both avoid that. Every money comparison (`_values_equal`, `_money_agree`, `critical_field_accuracy`) routes through the validator's own `within_tolerance` (`rel=0.0002`, `floor=0.02`), so the eval and the validator share one notion of "close enough."

One asymmetry is worth an explicit decision. `critical_field_accuracy` (`eval/metrics.py:166-167`) compares date with `==` (so `None == None` counts as agreement) but total with `within_tolerance`, which returns `False` when either side is `None`. A golden receipt whose truth `total` is null therefore can never be scored critical-correct, whatever the model returns. That is defensible — a receipt with no readable total arguably shouldn't count as correctly read — but the inconsistency with the date field looks incidental rather than intended. Confidence: confirmed, minor.

Line-item scoring aligns rows by normalized-description similarity through `align_line_items` (threshold 0.6, mirroring R061) so a single inserted or dropped row doesn't cascade into every later row being marked wrong; a matched pair whose numbers disagree is counted as both a false positive and a false negative, which correctly punishes a wrong number twice.

### Ingest front door: sniffing, gating, and PDF handles

`validate_upload` / `ingest_bytes` gate cheapest-first — extension, then size (with an explicit empty-file case), then a magic-byte sniff (`_sniff_content_type`) — so a renamed `.txt` or a truncated download is refused before it consumes a blob or a model call, and the type is decided by the bytes rather than the filename. Rejected uploads raise `ValueError` from the `ingest_*` entry points, so a caller can't accidentally proceed on a bad file.

`expand_pdf` (`ingest/ingest.py:174-186`) closes the `PdfDocument` in a `finally`, but the per-page objects and the render bitmaps produced by `page.render(scale=scale).to_pil()` (line 178) are never explicitly closed. Closing the document frees its children, so this is not a true leak, but pypdfium2 commonly emits "was not closed" warnings and holds native buffers longer than needed; closing each page/bitmap inside the loop is the tidy form. Confidence: possible, minor.

### Golden-set on-ramp robustness

The module docstring promises that `validate_labels` and `composition_stats` "never raise on a malformed file: the whole point is to report problems, not blow up on them." `validate_labels` honors that with a broad `except` that turns any failure into a reported string. `composition_stats` does not: it calls `load_manifest`, which at `eval/golden_set.py:132` runs `json.loads(...)` on the manifest with no guard, so a malformed `manifest.json` raises `JSONDecodeError` straight out of `composition_stats` — the one function documented to stay exception-free. Wrapping the parse (treat an unparseable manifest as `{}`, or fold it into a reported problem) restores the stated contract. Confidence: confirmed, minor.

### Export at the display boundary, and the float guard

The `float(value)` in `_num_cell` is confined to the openpyxl cell (numeric `number_format`, `None` → empty cell, never the string `"None"`) and nothing downstream reads the sheet back, so it is the sanctioned display boundary rather than a money-path leak. The rough edge is `export_workbook` (`export/xlsx.py:96`): when `ids` is provided it indexes `ids[i]`, so an `ids` list shorter than `receipts` raises `IndexError` partway through building the workbook. A length check (or a guarded `zip`) up front would fail cleanly instead of mid-write. Confidence: possible, minor.

Underneath all of this, `test_no_float_in_money_path` walks the schema's nested models, resolves each annotation through `Optional`/`Union`/`list` to its leaf types, and asserts none is `float` except the allowlisted `LineItem.bbox` — and it first asserts the walk actually reached `Totals.total`, `LineItem.line_total`, and `Modifier.amount`, so it can't pass vacuously. That is the prime directive enforced structurally rather than by convention, and it's well built.

### Test coverage

Covered: the normalize refusal paths (ambiguous date/money/currency, no OCR digit-fixing), decimal-convention detection, perceptual hashing and both dedupe modes, upload sniffing and every rejection reason, the image geometry ops, the OpenCV bounds/quality paths (importorskip-guarded), the XLSX round-trip, the eval metrics and calibration curve, and golden-set validation. 232 pass offline via the fake client; `ruff` is clean; mypy is informational in CI.

Not tested: `parse_date`'s two-digit-year branch — every date test uses a four-digit year, so the `date.today()` path (and the determinism concern above) is never exercised; `make_image_key` behavior across a month boundary; `composition_stats` against a malformed manifest; `export_workbook` with a short `ids` list; and `S3Storage`'s happy path, which needs live credentials and is legitimately out of scope (only its missing-dependency path is asserted).

</details>

<details>
<summary>File map</summary>

- `eval/metrics.py` — six §16 metrics; money compared via `within_tolerance`, `Decimal` preserved through python-mode dump.
- `eval/harness.py` — walks the golden set, aggregates, writes a dated `{date}-{prompt_version}.json`.
- `eval/golden_set.py` — golden-set on-ramp: label validation and composition stats (manifest parse unguarded).
- `eval/__init__.py`, `eval/golden/*` — package doc, template, manifest example, labeling guide.
- `src/receipts/normalize/numbers.py` — `parse_money` / `detect_decimal_convention` / `quantize_money`; refuses on any non-numeric residue.
- `src/receipts/normalize/dates.py` — `parse_date` (two-digit years via `date.today()`), `parse_time`, `expand_two_digit_year`.
- `src/receipts/normalize/text.py` — `clean_text`, merchant fingerprinting, ISO-4217 currency resolution.
- `src/receipts/normalize/__init__.py` — `normalize()`: deep-copy, safe canonicalization, never touches money.
- `src/receipts/preprocess/image_ops.py` — load/orient/rgb/resize/split/base64; returns new images.
- `src/receipts/preprocess/bounds.py` — document quad detection, perspective deskew, skew estimate.
- `src/receipts/preprocess/quality.py` — cheap quality metrics and the reject-only gate.
- `src/receipts/ingest/ingest.py` — upload validation, PDF expansion, in-memory `ReceiptJob`.
- `src/receipts/ingest/storage.py` — `StorageBackend` protocol, local + S3 backends, `make_image_key` (time-stamped).
- `src/receipts/ingest/dedupe.py` — dHash, Hamming distance, image + semantic duplicate lookup over injected candidates.
- `src/receipts/export/xlsx.py` — two-sheet workbook; `float` confined to the cell boundary.
- `src/receipts/extract/lineitem_align.py` — shared greedy similarity-based row alignment.
- `tests/*` — 232 tests across the above; `test_no_float_in_money_path.py` is the schema-level money guard.
- Config/CI: `pyproject.toml` (ruff/mypy/deps + `pipeline` extra), `.github/workflows/ci.yml` (tests + ruff blocking, mypy informational), `.gitignore`.

Full diff: `git diff master...HEAD`.

</details>
