# Currency Bound + Fixture Race Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the machine-path `currency` write the same column bound the
human path already has, and make the CLI test module's fixture images
structurally distinct so its diagnosed dedupe race cannot fire.

**Architecture:** Task 1 reuses `_bounded_optional_text("currency")` — built
once, shared by both paths — at `save_extraction`'s fields dict, so an
over-long machine value raises `ValueError` at the repository boundary
(ADR-0006) instead of corrupting SQLite silently / killing the receipt with a
Postgres `DataError`. Task 2 replaces the flat fixture PNG in
`tests/test_cli_pipeline.py` with a per-call structurally varied image
(mirroring the sibling module's existing pattern) and pins pairwise
distinctness beyond the real dedupe threshold.

**Tech Stack:** Python 3.14, SQLAlchemy 2.x, pytest, Pillow.

**Design doc:** `docs/superpowers/specs/2026-08-02-currency-bound-and-fixture-race-design.md`

## Global Constraints

- **A full PAN is never persisted**; nothing here may touch `_PAN_RE`,
  `_mask_pan`, `redact_pan`, or the §18 blanket redaction pass.
- **`Decimal` on the money path, never `float`** (ADR-0001). Nothing here
  touches money.
- **ADR-0006:** repository functions raise `ValueError` on bad input; the
  caller commits.
- **No new ADR** — Task 1 implements ADR-0007's existing "bounded text is
  validated against the model column" decision on the machine path.
- **Two test suites**; `python -m pytest` stays offline and Node-free. No
  frontend file moves, so Vitest must stay untouched at its current count.
- **Piped pytest output can lose its final summary line** — use
  `--junitxml` and read counts from the XML.
- Lint is `python -m ruff check .` — bare `ruff` is not on PATH.
- **Every new failing-capable test is proven to fail** with its fix reverted;
  absence-of-breakage assertions get their guarantee reverted separately
  (review standards 2–4).
- **Stage only the files your task names.** Never stage anything under
  `var/`. Do not push.
- **Volatile numbers (test counts, SHAs, line numbers) never go in code
  comments** (ADR-0019). Reading a limit or threshold off the real artifact
  is the pattern, restating it is the anti-pattern.
- The Grep tool mangles `/` in content output in this environment — verify
  slash-sensitive claims with Read, `git grep` via Bash, or by executing.

## File Structure

| File | Responsibility in this change |
|---|---|
| `src/receipts/persist/repository.py` | Task 1: `_CURRENCY_BOUND` constant; the `currency=` line in `save_extraction`'s fields dict; `_RECEIPT_FIELDS`' currency entry reuses the shared constant. |
| `tests/test_repository.py` | Task 1: the RED bound test and the null pass-through test, appended to the `save_extraction` block. |
| `tests/test_process_receipt.py` | Task 1: the pipeline-level pin that the bound is unreachable from `process_receipt`. |
| `tests/test_cli_pipeline.py` | Task 2: the new `_png_bytes`, the distinctness pin, and the imports they need. Nothing else in the module changes. |

No new files. No new dependencies.

---

### Task 1: The machine-path currency bound

**Files:**
- Modify: `src/receipts/persist/repository.py` — the `currency=` line in
  `save_extraction`'s fields dict (near line 547), a new module constant
  directly after `_bounded_optional_text` (whose body ends near line 1072),
  and `_RECEIPT_FIELDS`' `"receipt.currency"` entry (near line 1174)
- Test: `tests/test_repository.py` (append inside the `save_extraction`
  section, after `test_save_extraction_redacts_a_pan_inside_a_line_item_modifier`),
  `tests/test_process_receipt.py` (append after
  `test_clean_receipt_is_persisted_and_auto_approved`)

**Interfaces:**
- Consumes: `_bounded_optional_text(column_name: str) -> Callable[[Any], str | None]`
  (already defined; raises `ValueError` naming the column when the coerced
  text exceeds the column's `length`; otherwise returns
  `None if value is None else str(value)` — it does NOT strip or map `""` to
  `None`).
- Produces: module-level `_CURRENCY_BOUND: Callable[[Any], str | None]` in
  `receipts.persist.repository`, shared by `save_extraction` and
  `_RECEIPT_FIELDS`. No signature changes anywhere.

- [ ] **Step 1: Read the real code before changing it**

Read `src/receipts/persist/repository.py` lines 480–570 (the whole
`save_extraction` head, its fields dict, and the §18 blanket pass comment
below it), lines 1049–1075 (`_coerce_optional_text` and
`_bounded_optional_text`), and the `_RECEIPT_FIELDS` region around line 1174.
Read `tests/test_repository.py` lines 97–215 (the `_job`/`_extraction`/`_save`
builders and the `engine` fixture) and the `ValueError` precedent at
`test_save_extraction_refuses_to_overwrite_a_reviewed_row` (near line 442).
Read the design doc §1 in full.

- [ ] **Step 2: Write the two repository tests**

Append to the `save_extraction` section of `tests/test_repository.py`:

```python
def test_save_extraction_bounds_the_machine_path_currency(engine: sa.Engine) -> None:
    """The machine path holds the same bound the human path has, for the same column.

    ``Receipt.currency`` is length-bounded and the human path already coerces
    through ``_bounded_optional_text("currency")``; the machine path used to
    write the model's text verbatim. The backends disagree about overlong
    text -- Postgres raises ``DataError`` mid-transaction, SQLite stores it
    silently -- so the unbounded write was a receipt-killing exception that
    development could not see. Letters on purpose: an all-digit over-long
    value would be PAN-shaped and masked by the redaction pass, which is a
    different guarantee than the bound pinned here.
    """
    extraction = _extraction()
    extraction.receipt.currency = "PESO PHILIPPINES"

    with Session(engine) as session:
        with pytest.raises(ValueError, match="currency"):
            _save(session, extraction=extraction)


def test_save_extraction_still_stores_a_null_currency(engine: sa.Engine) -> None:
    """The bound rejects only overlong text: a null passes through untouched.

    (The 3-character green path is already pinned by
    ``test_save_extraction_persists_receipt_and_line_items``, which stores
    ``"USD"``.)
    """
    job = _job()
    nulled = _extraction()
    nulled.receipt.currency = None

    with Session(engine) as session:
        _save(session, job=job, extraction=nulled)
        session.commit()

    with Session(engine) as session:
        got = get_receipt(session, job.id)
        assert got is not None
        assert got.currency is None
```

- [ ] **Step 3: Run them and confirm the RED is the right RED**

```
python -m pytest tests/test_repository.py -k "machine_path_currency or still_stores_a_null_currency" -q
```

Expected: `test_save_extraction_bounds_the_machine_path_currency` **FAILS**
because no `ValueError` is raised (the over-long value is stored — that is
the defect); `test_save_extraction_still_stores_a_null_currency` **PASSES**
(nothing blocks `None` today — it is regression protection, and its proof is
the revert in Step 7, not a RED run). If the bound test fails with any other
error, stop and report.

- [ ] **Step 4: Implement — three edits in `repository.py`**

Directly after `_bounded_optional_text`'s body (after the `return coerce`
near line 1072), add:

```python
#: The machine path's bound for the one length-limited column model text
#: reaches. Built once and shared with ``_RECEIPT_FIELDS`` below, so the
#: human and machine paths cannot drift for the same column.
_CURRENCY_BOUND = _bounded_optional_text("currency")
```

In `save_extraction`'s fields dict (near line 547), change:

```python
        currency=receipt_meta.currency,
```

to:

```python
        currency=_CURRENCY_BOUND(receipt_meta.currency),
```

In `_RECEIPT_FIELDS` (near line 1174), change:

```python
    "receipt.currency": ("currency", _bounded_optional_text("currency")),
```

to:

```python
    "receipt.currency": ("currency", _CURRENCY_BOUND),
```

(The dict literal is evaluated at module load, after the constant's
assignment above it, and `save_extraction`'s body resolves the name at call
time — no ordering hazard in either direction.)

- [ ] **Step 5: Run the new tests plus the neighbourhood**

```
python -m pytest tests/test_repository.py -k "save_extraction or corrections or currency" -q
```

Expected: all green — the two new tests pass and nothing pre-existing moves
(the human path's behaviour is byte-identical: the same coercer instance,
same closure logic).

- [ ] **Step 6: Write and run the pipeline-level pin**

Append to `tests/test_process_receipt.py` after
`test_clean_receipt_is_persisted_and_auto_approved`:

```python
def test_a_garbage_currency_never_reaches_the_bounded_column(
    session_factory, storage, settings
):
    """The machine-path bound is unreachable from the pipeline, by construction.

    ``normalize`` replaces ``receipt.currency`` with a whitelisted ISO code or
    ``None`` before anything is saved, so a model emitting free text there
    ends as a persisted receipt with a null currency (these hermetic settings
    carry no ``default_currency``, so nothing is resolved in its place) --
    never as a ``ValueError`` from ``save_extraction``'s bound.
    """
    bad = _good()
    bad.receipt.currency = "PESO PHILIPPINES"
    job = _job(storage)

    result = _run(job, _Client([_triage(), bad]), session_factory, storage, settings)

    assert result.failed_stage is None
    with session_factory() as session:
        receipt = session.get(Receipt, job.id)
        assert receipt is not None
        assert receipt.currency is None
```

```
python -m pytest tests/test_process_receipt.py -k "garbage_currency" -q
```

Expected: PASS. This is an absence-of-breakage pin; its revert-proof is
Step 7's second half.

- [ ] **Step 7: Prove the tests discriminate — two separate reverts**

(a) Revert only the `currency=` line in `save_extraction` (put back
`currency=receipt_meta.currency,`; keep the constant and the tests). Run the
Step 3 selection: the bound test must **FAIL** (value stored, no raise); the
null test must still pass. Restore the fix.

(b) With the fix restored, demonstrate what actually protects the pipeline:
temporarily change the pin's final assertion to
`assert receipt.currency == "PESO PHILIPPINES"` and confirm it **FAILS**
with the stored value being `None` — the measured proof that normalization
(not luck, and not the new bound) is what keeps the bound unreachable from
`process_receipt`. Restore the committed assertion. Record (a) and (b) with
their outputs in your report.

- [ ] **Step 8: Gates**

```
python -m pytest --junitxml=var/junit_task1.xml -q
python -m ruff check .
```

Expected: `failures="0" errors="0"` in the XML (read the counts from the XML,
not stdout; report the exact total), ruff clean. Delete the junit file after
reading it (PowerShell `Remove-Item var/junit_task1.xml` if `rm` is blocked
by the hook).

- [ ] **Step 9: Commit**

```bash
git add src/receipts/persist/repository.py tests/test_repository.py tests/test_process_receipt.py
git commit -m "fix(persist): bound the machine-path currency write to its column

save_extraction wrote the model's currency text verbatim into a
length-bounded column the human path already guards: Postgres raises
DataError mid-transaction on overlong text while SQLite stores it silently,
so the machine path carried a receipt-killing exception development could
not see. The live pipeline never delivers one -- normalize whitelists to
ISO-or-None and the failure and duplicate paths save empty extractions --
so the bound is contract enforcement at the repository boundary (ADR-0006,
implementing ADR-0007's bounded-text decision on the machine path), shared
with _RECEIPT_FIELDS so the two paths cannot drift for the same column."
```

---

### Task 2: Structurally distinct fixture images in the CLI test module

**Files:**
- Modify: `tests/test_cli_pipeline.py` — `_png_bytes` (near lines 124–127),
  the module's import block, and one new test. `_job` and every existing test
  stay untouched.

**Interfaces:**
- Consumes: `compute_phash(img: Image.Image) -> str` and
  `phash_distance(a: str, b: str) -> int` from `receipts.ingest.dedupe`;
  `find_duplicate_by_phash`'s `threshold` keyword default (read via
  `inspect.signature`, never restated).
- Produces: `_png_bytes(seed: int | None = None) -> bytes` — per-call
  distinct by default (module counter), reproducible when `seed` is passed.
  No caller signature changes.

- [ ] **Step 1: Read the real code before changing it**

Read `tests/test_cli_pipeline.py` lines 1–60 (the import block), 120–145
(`_png_bytes` and `_job`), and every `_job` caller — as of this plan they are
`_pending_receipt` (line 280), `_reviewed_receipt` (289),
`_auto_approved_receipt` (300) and the reprocess twin test (847). **Confirm
for yourself that no caller depends on two jobs sharing image bytes**: the
twin test manufactures its hash collision by passing `image_phash=phash`
into `save_extraction` explicitly and never hashes the twin's actual blob,
and the two helper fixtures likewise pass literal `image_phash` values. If
you find a caller that does depend on shared bytes, stop and report — the
premise of this task would be wrong for it.

Then read `tests/test_process_receipt.py` lines 107–126: the sibling module
already learned this lesson ("every uniform bitmap hashes to the same 64
zero bits") and draws seeded random rectangles. This task deliberately
mirrors that pattern, adding only the per-call default.

- [ ] **Step 2: Measure the premise before touching it**

```
python -c "import io, sys, hashlib; sys.path.insert(0, 'src'); sys.path.insert(0, '.'); from PIL import Image; from tests.test_cli_pipeline import _png_bytes; from receipts.ingest.dedupe import compute_phash, phash_distance; a, b = _png_bytes(), _png_bytes(); ha, hb = compute_phash(Image.open(io.BytesIO(a))), compute_phash(Image.open(io.BytesIO(b))); print('sha_equal', hashlib.sha256(a).digest() == hashlib.sha256(b).digest(), 'phash', ha, hb, 'distance', phash_distance(ha, hb))"
```

Expected today: `sha_equal True ... distance 0`. That is the measured race
premise. If it does not reproduce, stop and report. (If importing
`tests.test_cli_pipeline` fails for path reasons, put the same probe in a
throwaway `var/` script that imports the module by file path; delete it
after.)

- [ ] **Step 3: Write the failing distinctness pin**

Append to `tests/test_cli_pipeline.py`:

```python
def test_fixture_images_are_distinct_beyond_the_dedupe_threshold() -> None:
    """The premise of every multi-receipt test in this module, pinned.

    Byte-identical fixture blobs share a sha256 AND a dHash -- a uniform
    bitmap hashes to the same 64 zero bits at any shade -- so receipts
    processed concurrently race into ``find_duplicate_by_phash``'s
    near-duplicate window, and whichever commits first makes the others
    ``REJECTED`` duplicates. That race is this module's diagnosed
    intermittent failure, and distinct bytes alone are not enough: dedupe is
    perceptual, so the images must sit pairwise beyond the threshold, which
    is read off the real function rather than restated here.
    """
    threshold = inspect.signature(find_duplicate_by_phash).parameters["threshold"].default
    blobs = [_png_bytes(seed=seed) for seed in range(12)]

    assert len({hashlib.sha256(blob).digest() for blob in blobs}) == len(blobs)

    hashes = [compute_phash(Image.open(io.BytesIO(blob))) for blob in blobs]
    for i, first in enumerate(hashes):
        for j, second in enumerate(hashes[i + 1 :], start=i + 1):
            assert phash_distance(first, second) > threshold, (i, j, first, second)
```

Add to the module's import block only what is missing (check first): stdlib
`hashlib`, `inspect`, `itertools`, `random`; `from PIL import ImageDraw`
(`Image` and `io` are already imported for the current fixture); and
`compute_phash`, `phash_distance` from `receipts.ingest.dedupe` plus
`find_duplicate_by_phash` from wherever the module already imports repository
names (`from receipts.persist.repository import find_duplicate_by_phash` if
it imports none).

- [ ] **Step 4: Run it and confirm it fails for the stated reason**

```
python -m pytest tests/test_cli_pipeline.py -k "distinct_beyond_the_dedupe" -q
```

Expected: **FAILS with `TypeError`** — today's `_png_bytes()` takes no
`seed` parameter. (The premise behind the test — identical hashes — is the
Step 2 measurement; this run pins that the fixture does not even have the
interface yet.)

- [ ] **Step 5: Replace `_png_bytes`**

Replace lines 124–127 of `tests/test_cli_pipeline.py` with:

```python
#: Seeds for the default-distinct fixture images, one per call.
_PNG_SEEDS = itertools.count()


def _png_bytes(seed: int | None = None) -> bytes:
    """A deterministic PNG with enough structure to carry a distinctive dHash.

    A flat image is useless here: every uniform bitmap hashes to the same 64
    zero bits (dHash keys on gradient direction, not shade), so byte-identical
    fixture blobs made concurrent receipts race into dedupe's near-duplicate
    window -- this module's diagnosed intermittent failure. Mirrors the
    seeded-rectangles fixture in ``tests/test_process_receipt.py``, adding a
    per-call default so every job gets a distinct image unless a test passes
    ``seed`` for reproducible bytes.
    """
    rng = random.Random(next(_PNG_SEEDS) if seed is None else seed)
    image = Image.new("RGB", (900, 1400), (240, 240, 240))
    draw = ImageDraw.Draw(image)
    for _ in range(24):
        left = rng.randrange(0, 780)
        top = rng.randrange(0, 1280)
        shade = rng.randrange(0, 200)
        draw.rectangle(
            [left, top, left + rng.randrange(20, 120), top + rng.randrange(20, 120)],
            fill=(shade, shade, shade),
        )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
```

- [ ] **Step 6: Run the pin and confirm it passes**

```
python -m pytest tests/test_cli_pipeline.py -k "distinct_beyond_the_dedupe" -q
```

Expected: PASS — twelve seeded images, pairwise sha-distinct and pairwise
beyond the threshold. If any pair lands at or under the threshold, the
rectangle geometry is not varied enough — report the failing pair and its
distance rather than loosening the assertion.

- [ ] **Step 7: Prove the pin discriminates — one variable**

Temporarily revert only the *structure*: keep the new signature but replace
the function body's drawing loop with the old flat image (delete the
`ImageDraw` loop so every seed produces the same uniform bitmap). Run the
Step 6 selection: the pin must **FAIL** — the sha-distinctness assertion
fails first (identical bytes), and if you comment that line out for the
check, the distance assertion fails at `0`. Restore the committed body and
confirm the pin passes again. Record both outputs.

- [ ] **Step 8: Run the previously-intermittent test and the whole module**

```
python -m pytest tests/test_cli_pipeline.py -k "inline_one_failing" -q
python -m pytest tests/test_cli_pipeline.py -q
```

Run the first selection five times (a shell loop is fine). Expected: green
every time — though note the race was load-sensitive, so green runs are
consistency evidence, not the proof; the deterministic pin is the proof.
Then the whole module: green, no other test disturbed (the twin test's
injected `image_phash` values are untouched by construction).

- [ ] **Step 9: Gates**

```
python -m pytest --junitxml=var/junit_task2.xml -q
python -m ruff check .
```

Expected: 0 failures / 0 errors in the XML (report the exact total), ruff
clean. Delete the junit file after reading it.

- [ ] **Step 10: Commit**

```bash
git add tests/test_cli_pipeline.py
git commit -m "test(cli): give every fixture receipt a structurally distinct image

The module's fixture returned a byte-identical uniform PNG on every call,
and every uniform bitmap hashes to the same 64 zero dHash bits at any
shade -- so three receipts processed inline shared a sha256 and a phash,
raced into dedupe's near-duplicate window under load, and whichever
committed first made the others REJECTED duplicates where the test
expected AUTO_APPROVED. Seeded random rectangles per call (mirroring
tests/test_process_receipt.py's fixture, plus a per-call default), pinned
by a deterministic pairwise-distance test that reads the threshold off
find_duplicate_by_phash rather than restating it. No caller relied on
shared bytes: the reprocess twin test injects image_phash explicitly."
```

---

## Verification, after both tasks

- [ ] `python scripts/verify.py` — all five gates PASS (pytest, ruff,
      typecheck, vitest, build). Vitest count unchanged — no frontend file
      moved.
- [ ] `python -m pytest --junitxml=var/junit_final.xml -q` and read the
      counts from the XML; delete the file after.
- [ ] `git status` clean; nothing under `var/` ever staged.
- [ ] The bound from outside the repository (the environment lesson):
      `python -c "from receipts.persist.repository import save_extraction"`
      run from a directory outside the repo imports cleanly, and the
      repository-level bound test result is what certifies behaviour.

## Self-review notes

Spec coverage: design §1.1/§1.2 → Task 1 Steps 1 and 3's expected RED;
§1.3 (the ruling, the shared coercer) → Step 4; §1.4 (blanket pass untouched,
`_bounded_optional_text` untouched, live path unchanged) → Steps 4–6;
§1.5 tests 1–3 → Steps 2, 3, 6, 7. Design §2.1 (the diagnosis) → Task 2
Steps 1–2; §2.2 (structural variation, counter default, callers checked,
sibling precedent, explicit-identical escape hatch — resolved: no caller
needs it, so none is added) → Steps 1 and 5; §2.3 tests → Steps 3–8.
Design §3 → the verification block. Design §4 (no ADR) → none written.
