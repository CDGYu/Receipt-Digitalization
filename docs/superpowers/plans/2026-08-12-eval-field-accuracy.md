# Eval Field Accuracy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the one field-accuracy scalar — which averages transcription, correct-emptiness and model self-report, and so has a ~40% floor reachable by producing nothing — with four numbers that each measure one thing, and keep the per-path map in the committed artefact.

**Architecture:** A pure classifier in `eval/metrics.py` splits each receipt's dotted-path set into three classes using two axes: **group** (read from the path string: `meta` / `line_items` / `core`) and **filled** (read from the *truth* value). `eval/harness.py` accumulates the resulting `FieldBreakdown` instead of two integers and writes the new shape. `eval/run_baseline.py` gains one shared renderer that both the batch table and `scripts/try_one_receipt.py` call, so "what counts as correct" stops having two definitions.

**Tech Stack:** Python 3.11+/3.13, pydantic v2, pytest. No new dependencies.

Design: `docs/superpowers/specs/2026-08-12-eval-field-accuracy-honesty-design.md`. Read it first; every section below cites it rather than restating its reasoning.

## Global Constraints

- **`receipts.extract.paths.flatten` must not be modified.** Its empty-container-as-leaf behaviour is load-bearing for self-consistency diffing and the corrections log. The "an empty container means absent" rule is an eval rule and lives only under `eval/`. (Design §2, "Out, deliberately".)
- **`eval.metrics.field_accuracy` keeps its name, signature and meaning** — `(predicted, truth) -> dict[str, bool]`. Spec §16 declares it. The defect is in aggregation. (Design §2.)
- **Rename, never redefine.** The attribute `EvalReport.field_accuracy` and the JSON key `"field_accuracy"` must not survive carrying new semantics. Grep for both at the end of Task 3 and expect zero hits outside historical records. (Design §3.7.)
- **`python -m pytest` bare.** `pyproject.toml` sets `addopts = "-q"`, so `-q` makes it `-qq` and prints no pass count.
- **`python scripts/verify.py` exceeds a 2-minute tool timeout.** Background it, and do not edit source or tests while it runs — a backgrounded run during an edit once reported a phantom `FAIL build`.
- **`pytest -k` matches substrings, not words.** Every `-k` filter below was checked against the test names this plan itself creates; if you add a test, re-check the filter rather than assuming.
- **Stage by explicit path, never `git add -A`.** Verify with `git diff --cached --stat` before committing.
- **The property, not the enumeration:** all existing tests must pass unmodified except where a task explicitly says otherwise. Anything else needing a test changed is a stop-and-report, not a judgement call.
- **This plan's claims about existing artefacts were probed at `1bddd0d`, not recalled.** They can still be wrong. Read the real file before trusting any line of this plan that describes one, and report the discrepancy rather than working around it.

## File Structure

| file | responsibility | task |
|---|---|---|
| `eval/metrics.py` | pure classification + per-receipt breakdown; the report dataclass | 1, 2 |
| `tests/test_eval_floor.py` | **new.** The floor pin, read against the tracked golden *labels* | 1 |
| `tests/test_eval_metrics.py` | classifier unit tests (synthetic only — see below) and harness tests | 1, 2 |
| `eval/harness.py` | accumulation and the committed JSON shape | 2 |
| `tests/test_cli_reports.py` | synthetic results-file fixtures must match what the producer now writes | 2 |
| `eval/run_baseline.py` | the one renderer both callers use, and the printed table | 3 |
| `scripts/try_one_receipt.py` | calls the shared renderer instead of computing its own scalar | 3 |
| `tests/test_run_baseline.py` | renderer and table tests | 3 |
| `docs/adr/0040-what-field-accuracy-counts.md` | **new.** The decision | 4 |
| `docs/adr/README.md` | index row | 4 |
| `docs/KNOWN_ISSUES.md` | dated correction: ISSUE-001's own remedy was refuted | 4 |

**Why `tests/test_eval_floor.py` is a new file.** `tests/test_eval_metrics.py`'s module docstring reads *"Pure and offline — synthetic fixtures only, no golden data, no network."* The floor pin must score against the **real** golden labels, because the whole point is what the metric does on this corpus. Putting it in that file would silently falsify the file's own stated contract. It reads `eval/golden/labels/*.json` only — tracked JSON, no images (which are gitignored), no network.

---

### Task 1: The classifier and the per-receipt breakdown

Pure additions to `eval/metrics.py`. Nothing consumes them yet, so this task is independently reviewable and cannot break the harness.

**Files:**
- Modify: `eval/metrics.py`
- Test: `tests/test_eval_metrics.py` (classifier section, synthetic)
- Create: `tests/test_eval_floor.py`

**Interfaces:**
- Consumes: `eval.metrics.field_accuracy`, `receipts.extract.paths.flatten`, `receipts.extract.schema.ReceiptExtraction` — all existing, all unchanged.
- Produces, for Tasks 2 and 3:
  - `FieldBreakdown` — frozen dataclass, all ten fields `int`, all defaulting to `0`, supporting `+`.
  - `field_breakdown(predicted: ReceiptExtraction, truth: ReceiptExtraction) -> FieldBreakdown`
  - `ratio(correct: int, total: int) -> float | None`

- [ ] **Step 1: Write the failing classifier tests**

Append to `tests/test_eval_metrics.py`, after the existing `field_accuracy` section:

```python
# --------------------------------------------------------------------------- #
# field_breakdown
# --------------------------------------------------------------------------- #


def test_breakdown_counts_a_filled_truth_path_as_transcription():
    bd = field_breakdown(_extraction(), _extraction())
    # merchant.name, receipt.date, totals.total ... are all filled in truth.
    assert bd.transcription_total > 0
    assert bd.transcription_correct == bd.transcription_total


def test_breakdown_never_counts_an_empty_truth_path_as_transcription():
    # receipt.cashier is None in both fixtures: absent, not transcription.
    bd = field_breakdown(_extraction(), _extraction())
    assert bd.correctly_empty > 0
    assert bd.hallucinated == 0


def test_breakdown_puts_meta_paths_in_self_report_not_transcription():
    bd = field_breakdown(_extraction(), _extraction())
    assert bd.self_report_total > 0
    # No meta path may be inside the transcription denominator.
    assert bd.transcription_total == bd.core_total + bd.line_items_total


def test_breakdown_classifies_by_prefix_not_by_a_list_of_names():
    """A meta path the classifier has never been told about still lands in
    self_report. This is the property review standard 19 asks for: one bounded
    rule, not an enumeration that a new schema field silently escapes."""
    from eval.metrics import _group

    assert _group("meta.some_field_added_next_year") == "meta"
    assert _group("line_items[7].qty") == "line_items"
    assert _group("line_items") == "line_items"
    assert _group("totals.total") == "core"


def test_breakdown_counts_an_invented_value_as_hallucination():
    truth = _extraction()
    predicted = _extraction()
    predicted.receipt.cashier = "MARIA"   # truth leaves this None
    bd = field_breakdown(predicted, truth)
    assert bd.hallucinated == 1


def test_breakdown_treats_an_empty_container_as_absent():
    """flatten emits ``[]`` as a leaf on purpose, so "had none" stays visible.
    But a receipt whose tax_breakdown is empty has no tax breakdown to read, so
    it must not be a point a model can earn.

    Differential, not introspective: it compares two truths differing only in
    that one field. A test that asked the classifier which paths it counted
    would mirror the rule under test and could never fail.

    Measured: core_total is 8 with the empty container and 11 with one band
    (label/base/rate/amount, of which base is None).
    """
    empty_truth = _extraction()
    filled_truth = _extraction()
    filled_truth.totals.tax_breakdown = [
        TaxBand(label="VAT", rate=D("0.12"), amount=D("24.00"))
    ]

    bd_empty = field_breakdown(_extraction(), empty_truth)
    bd_filled = field_breakdown(_extraction(), filled_truth)

    assert bd_empty.core_total < bd_filled.core_total


def test_breakdown_an_extra_predicted_row_is_hallucination_not_a_miss():
    both = _items()
    extra = LineItem(position=3, description_raw="ZZZ NOVELTY WIDGET",
                     qty=D("1"), unit_price=D("5.00"), line_total=D("5.00"))
    bd = field_breakdown(_extraction(items=both + [extra]), _extraction(items=both))
    # The invented row's paths are absent in truth, so they are hallucination.
    assert bd.hallucinated > 0


def test_breakdown_sums_with_plus():
    a = field_breakdown(_extraction(), _extraction())
    b = field_breakdown(_extraction(), _extraction())
    total = a + b
    assert total.transcription_total == a.transcription_total * 2
    assert total.correctly_empty == a.correctly_empty * 2


def test_ratio_is_none_on_an_empty_denominator_never_zero():
    from eval.metrics import ratio

    assert ratio(0, 0) is None
    assert ratio(0, 4) == 0.0
    assert ratio(1, 4) == 0.25
```

Extend that file's schema import to add `TaxBand`:

```python
from receipts.extract.schema import (
    LineItem,
    Merchant,
    ReceiptExtraction,
    ReceiptMeta,
    TaxBand,
    Totals,
)
```

And extend the existing import block at the top of the file:

```python
from eval.metrics import (
    EvalReport,
    EvalResult,
    calibration_curve,
    critical_field_accuracy,
    field_accuracy,
    field_breakdown,
    line_item_f1,
)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_eval_metrics.py -k breakdown`

Expected: **collection error** — `ImportError: cannot import name 'field_breakdown' from 'eval.metrics'`.

That is failure for the *wrong reason*: nothing is being measured yet, only absence. It is fine here — these are unit tests of a new function, and their real proof is that they pass on the implementation and fail on a mutation of it. The floor pin in Step 6 is the one that needs a proper RED, and Step 8 gives it one.

- [ ] **Step 3: Implement the classifier**

Add to `eval/metrics.py`. Put `_group`/`_is_filled`/`ratio` just below `_norm_text`, and `FieldBreakdown`/`field_breakdown` just below `field_accuracy`.

```python
#: Path prefixes that decide a leaf's family. Structural on purpose: a prefix
#: test classifies a schema field added next year without anybody deciding it
#: should be, where a list of field names would silently let it through
#: (review standard 19 — an enumerated defence never converges).
_META_PREFIX = "meta."
_LINE_ITEMS = "line_items"


def _group(path: str) -> str:
    """Which family a dotted path belongs to: ``meta``, ``line_items`` or ``core``.

    Read from the path string alone — never from either side's value.
    """
    if path.startswith(_META_PREFIX):
        return "meta"
    if path == _LINE_ITEMS or path.startswith(f"{_LINE_ITEMS}["):
        return "line_items"
    return "core"


def _is_filled(value: object) -> bool:
    """True when a leaf carries information the model could have read.

    ``None`` is not filled, and neither is an empty container. ``flatten``
    emits ``[]``/``{}`` as leaves deliberately, so that "had none" is visible
    rather than absent — but a receipt whose ``totals.tax_breakdown`` is empty
    has no tax breakdown to transcribe, so it is not a point anyone can earn.

    Written with ``isinstance``/``len`` rather than ``value in (None, [], {})``:
    that form compares with ``==``, and equality against a container is not a
    test this rule should rest on.
    """
    if value is None:
        return False
    return not (isinstance(value, (list, dict)) and len(value) == 0)


def ratio(correct: int, total: int) -> float | None:
    """``correct/total``, or ``None`` when the denominator is zero.

    ``None``, never ``0.0``: a ratio over no decisions is undefined, not bad.
    Same rule as ``auto_approval_precision`` (P8.T3), applied to the new
    metrics before it can bite a second time.
    """
    return (correct / total) if total else None
```

```python
@dataclass(frozen=True)
class FieldBreakdown:
    """One receipt's dotted paths, split into classes that mean different things.

    The old single scalar averaged three unlike quantities — what the model
    read, what it correctly left empty, and what it said about itself — and the
    last two dominate: an extraction containing *nothing* scored 42.50% / 37.50%
    / 36.59% against the three golden labels. See
    ``docs/superpowers/specs/2026-08-12-eval-field-accuracy-honesty-design.md``.

    Two axes decide a path's class. **Group** comes from the path string;
    **filled** is read from the *truth* side only. Reading "filled" from the
    prediction would let a model enlarge its own denominator by inventing
    fields.

      * ``transcription`` — truth filled, group ``core`` or ``line_items``.
        The points a model has to earn by reading.
      * ``self_report`` — truth filled, group ``meta``. Self-description, and
        in ``meta.notes`` human annotator prose. Reported, never averaged in.
      * absent — truth not filled. Split into ``hallucinated`` (the model
        produced a value anyway) and ``correctly_empty``.

    The classes tile the path set: nothing is dropped, it is only stopped from
    inflating a percentage.
    """

    transcription_correct: int = 0
    transcription_total: int = 0
    core_correct: int = 0
    core_total: int = 0
    line_items_correct: int = 0
    line_items_total: int = 0
    self_report_correct: int = 0
    self_report_total: int = 0
    hallucinated: int = 0
    correctly_empty: int = 0

    def __add__(self, other: "FieldBreakdown") -> "FieldBreakdown":
        """Fold two receipts' breakdowns together (micro-averaging)."""
        if not isinstance(other, FieldBreakdown):
            return NotImplemented
        return FieldBreakdown(
            *(
                getattr(self, f.name) + getattr(other, f.name)
                for f in fields(self)
            )
        )


def field_breakdown(
    predicted: ReceiptExtraction, truth: ReceiptExtraction
) -> FieldBreakdown:
    """Split one receipt's path set into the classes of :class:`FieldBreakdown`.

    Derived from the same :func:`field_accuracy` map the harness records, over
    the same ``model_dump()`` (python mode) both sides use, so the counts and
    the per-path map can never disagree.
    """
    pred = flatten(predicted.model_dump())
    tru = flatten(truth.model_dump())

    core_c = core_t = li_c = li_t = sr_c = sr_t = hall = empty = 0
    for path, ok in field_accuracy(predicted, truth).items():
        if not _is_filled(tru.get(path)):
            if _is_filled(pred.get(path)):
                hall += 1
            else:
                empty += 1
            continue
        group = _group(path)
        if group == "meta":
            sr_t += 1
            sr_c += int(ok)
        elif group == "line_items":
            li_t += 1
            li_c += int(ok)
        else:
            core_t += 1
            core_c += int(ok)

    return FieldBreakdown(
        transcription_correct=core_c + li_c,
        transcription_total=core_t + li_t,
        core_correct=core_c,
        core_total=core_t,
        line_items_correct=li_c,
        line_items_total=li_t,
        self_report_correct=sr_c,
        self_report_total=sr_t,
        hallucinated=hall,
        correctly_empty=empty,
    )
```

Extend the existing dataclasses import at the top of `eval/metrics.py`:

```python
from dataclasses import dataclass, field, fields
```

- [ ] **Step 4: Run the classifier tests to verify they pass**

Run: `python -m pytest tests/test_eval_metrics.py -k breakdown`
Expected: PASS. (Verified filter: every test added in Step 1 contains the substring `breakdown` except `test_ratio_is_none_on_an_empty_denominator_never_zero` — run that one with `-k ratio`.)

Run: `python -m pytest tests/test_eval_metrics.py`
Expected: PASS, all of them. No existing test may change.

- [ ] **Step 5: Commit**

```bash
git add eval/metrics.py tests/test_eval_metrics.py
git commit -m "feat: classify eval paths by what they measure, not all alike"
```

- [ ] **Step 6: Write the floor pin**

Create `tests/test_eval_floor.py`:

```python
"""The floor pin: what an extraction containing NOTHING scores.

Deliberately reads the **real** golden labels, unlike ``test_eval_metrics.py``
which is synthetic-only by its own docstring. The whole question here is what
the metric does on this corpus, so a synthetic fixture cannot answer it. Labels
only — tracked JSON, no images (gitignored), no network.

Measured before the fix, with the old every-path denominator:
r001 42.50%, r002 37.50%, r003 36.59%. A model that read nothing scored above
40%; the one real local run on file beat that floor by a single path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.metrics import field_breakdown, ratio
from receipts.extract.schema import ReceiptExtraction

GOLDEN_LABELS = Path(__file__).resolve().parents[1] / "eval" / "golden" / "labels"

#: An empty extraction must score below this. Stated as a literal, never
#: derived from the code under test: a bound computed by the thing it checks
#: moves with the defect. Measured floor under the new definition is ~5.9%.
MAX_FLOOR = 0.10


def _labels() -> list[Path]:
    return sorted(GOLDEN_LABELS.glob("*.json"))


def test_the_golden_label_set_is_not_empty():
    """Without this, the parametrised test below passes vacuously on an empty
    directory — a pin that cannot fail is not a pin (review standard 14)."""
    assert _labels(), f"no golden labels found under {GOLDEN_LABELS}"


@pytest.mark.parametrize("label_path", _labels(), ids=lambda p: p.stem)
def test_an_extraction_that_read_nothing_scores_near_zero(label_path: Path):
    truth = ReceiptExtraction.model_validate(
        json.loads(label_path.read_text(encoding="utf-8"))
    )
    bd = field_breakdown(ReceiptExtraction(), truth)
    floor = ratio(bd.transcription_correct, bd.transcription_total)

    assert floor is not None
    assert floor < MAX_FLOOR, (
        f"{label_path.stem}: an extraction containing nothing scored "
        f"{floor:.2%} — the metric is measuring agreement about absence, "
        f"not reading"
    )


@pytest.mark.parametrize("label_path", _labels(), ids=lambda p: p.stem)
def test_an_extraction_that_read_nothing_hallucinates_nothing(label_path: Path):
    truth = ReceiptExtraction.model_validate(
        json.loads(label_path.read_text(encoding="utf-8"))
    )
    bd = field_breakdown(ReceiptExtraction(), truth)
    assert bd.hallucinated == 0
    assert bd.correctly_empty > 0
```

- [ ] **Step 7: Run the floor pin to verify it passes**

Run: `python -m pytest tests/test_eval_floor.py`
Expected: PASS — 7 tests (1 non-emptiness + 3 labels × 2 parametrised).

If the label count is not 3, the parametrised count differs. That is expected as P8.T2 grows the set; it is not a failure.

- [ ] **Step 8: Prove the pin red BY MUTATION — this step is the point of the task**

The floor test passing is not evidence it would catch anything. It has never failed for the right reason: at Step 6 the function already existed, so it went green immediately.

Make **one** change in `eval/metrics.py` — restore the old "every path counts" denominator inside `field_breakdown`, keeping the new name:

```python
        if not _is_filled(tru.get(path)):
            # MUTATION: count absent paths as transcription, as the old scalar did
            core_t += 1
            core_c += int(ok)
            continue
```

Run: `python -m pytest tests/test_eval_floor.py`

Expected: **FAIL** on every label, with the assertion message quoting a floor around 42%/37%/36% — the numbers in this file's docstring.

Confirm the mutation landed where you meant (review standard 16): the failure message must name the floor, not raise `AttributeError` or `TypeError`. A failure for any other reason means the mutation went somewhere else — revert, re-read, and try again.

Then **revert the mutation** and re-run to confirm green:

```bash
git diff --stat            # must show eval/metrics.py modified
git checkout -- eval/metrics.py
git diff --stat            # must be empty
python -m pytest tests/test_eval_floor.py
```

Record in the ledger: the mutation, the observed floors, and that it was reverted.

- [ ] **Step 9: Commit**

```bash
git add tests/test_eval_floor.py
git commit -m "test: pin the floor an empty extraction can reach"
```

---

### Task 2: Aggregation and the committed artefact

**Files:**
- Modify: `eval/metrics.py` (the `EvalReport`/`EvalResult` dataclasses)
- Modify: `eval/harness.py` (`_Accumulator`, `_build_report`, `_report_to_dict`)
- Test: `tests/test_eval_metrics.py` (harness section)
- Test: `tests/test_cli_reports.py` (fixtures must reflect what the producer writes)

**Interfaces:**
- Consumes from Task 1: `FieldBreakdown`, `field_breakdown`, `ratio`.
- Produces, for Task 3: `EvalReport` with `transcription_accuracy`, `transcription_accuracy_core`, `transcription_accuracy_line_items`, `self_report_agreement` (all `float | None`) and `hallucinated_fields`, `correctly_empty_fields` (both `int`). `EvalResult.breakdown: FieldBreakdown`.

- [ ] **Step 1: Write the failing harness tests**

In `tests/test_eval_metrics.py`, change the one existing assertion in `test_run_eval_survives_a_failing_receipt` — this is the single test modification this plan authorises, and it is a rename, not a weakening:

```python
    # The empty field map keeps the transcription denominator honest: r1 read
    # perfectly, so the aggregate stays 1.0 rather than being halved by a
    # receipt that produced nothing.
    assert report.transcription_accuracy == 1.0
```

Then append to the harness section:

```python
def test_the_report_carries_each_class_separately(tmp_path):
    golden = tmp_path / "golden"
    labels = golden / "labels"
    labels.mkdir(parents=True)
    (labels / "r1.json").write_text(
        _extraction(total="224.00").model_dump_json(), encoding="utf-8"
    )

    def pipeline_fn(path):
        return _extraction(total="224.00"), D("0.95")

    report = run_eval(golden, pipeline_fn, results_dir=tmp_path / "results")

    assert report.transcription_accuracy == 1.0
    assert report.transcription_accuracy_core == 1.0
    assert report.transcription_accuracy_line_items == 1.0
    assert report.self_report_agreement == 1.0
    assert report.hallucinated_fields == 0
    assert report.correctly_empty_fields > 0


def test_a_hallucinated_field_is_counted_and_does_not_touch_transcription(tmp_path):
    golden = tmp_path / "golden"
    labels = golden / "labels"
    labels.mkdir(parents=True)
    truth = _extraction(total="224.00")
    (labels / "r1.json").write_text(truth.model_dump_json(), encoding="utf-8")

    def pipeline_fn(path):
        invented = _extraction(total="224.00")
        invented.receipt.cashier = "MARIA"      # truth leaves this None
        return invented, D("0.95")

    report = run_eval(golden, pipeline_fn, results_dir=tmp_path / "results")

    assert report.hallucinated_fields == 1
    # Inventing a field must not enlarge the denominator the model is scored on.
    assert report.transcription_accuracy == 1.0


def test_the_artifact_keeps_the_per_path_map_sorted(tmp_path):
    """Spec §16 says metric 4 exists to show 'where to focus prompt work'. Two
    integers cannot answer that; the map can. Sorted so a diff is legible."""
    golden = tmp_path / "golden"
    labels = golden / "labels"
    labels.mkdir(parents=True)
    (labels / "r1.json").write_text(
        _extraction(total="224.00").model_dump_json(), encoding="utf-8"
    )

    def pipeline_fn(path):
        return _extraction(total="999.00"), D("0.95")     # wrong total

    results_dir = tmp_path / "results"
    run_eval(golden, pipeline_fn, results_dir=results_dir)
    payload = json.loads(
        next(results_dir.glob("*.json")).read_text(encoding="utf-8")
    )

    row = payload["results"][0]
    assert row["field_results"]["totals.total"] is False
    assert list(row["field_results"]) == sorted(row["field_results"])
    assert row["transcription_correct"] < row["transcription_total"]
    assert payload["metrics"]["transcription_accuracy"] < 1.0
    assert "field_accuracy" not in payload["metrics"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_eval_metrics.py -k "class_separately or hallucinated or per_path_map or survives_a_failing"`
Expected: FAIL — `AttributeError: 'EvalReport' object has no attribute 'transcription_accuracy'`, and `KeyError: 'field_results'`.

- [ ] **Step 3: Change the report dataclasses**

In `eval/metrics.py`, in `EvalReport`, replace the single line `field_accuracy: float        # 4` with the **aggregate breakdown**, and expose the ratios as properties:

```python
    # Metric 4 is not one number, because it was never measuring one thing.
    # The report stores the aggregate counts and derives the ratios, so the
    # printed block and the JSON cannot disagree, and so `format_breakdown`
    # can render a whole run and a single receipt with the same code.
    breakdown: FieldBreakdown           # 4
```

and add, after the dataclass fields:

```python
    @property
    def transcription_accuracy(self) -> float | None:
        """Metric 4: of the fields this receipt *has*, how many were read.

        ``None`` when the denominator is zero, never ``0.0`` — the same rule
        ``auto_approval_precision`` learned in P8.T3, applied before it can
        bite a second time.
        """
        return ratio(
            self.breakdown.transcription_correct, self.breakdown.transcription_total
        )

    @property
    def transcription_accuracy_core(self) -> float | None:
        return ratio(self.breakdown.core_correct, self.breakdown.core_total)

    @property
    def transcription_accuracy_line_items(self) -> float | None:
        return ratio(self.breakdown.line_items_correct, self.breakdown.line_items_total)

    @property
    def self_report_agreement(self) -> float | None:
        """``meta.*`` — model self-description, reported, never averaged in."""
        return ratio(
            self.breakdown.self_report_correct, self.breakdown.self_report_total
        )

    @property
    def hallucinated_fields(self) -> int:
        return self.breakdown.hallucinated

    @property
    def correctly_empty_fields(self) -> int:
        return self.breakdown.correctly_empty
```

**Why properties rather than six more fields.** A caller renders metric 4 from `report.breakdown`, and every ratio is derived from the same counts the JSON reports. Six independently-stored floats could drift from the counts beside them, and `format_report` would have had to re-implement the block that `format_breakdown` already renders — which is the *second definition* this whole milestone exists to remove (design §2.1).

`breakdown` has no default, so it must be declared **before** the defaulted fields (`cost_per_receipt` onwards) — put it exactly where `field_accuracy` was.

In `EvalResult`, add one field (it must have a default — `receipts.cli.cmd_calibrate` rebuilds `EvalResult` without it):

```python
    #: Per-class counts. Defaults to all-zero so ``cmd_calibrate``, which
    #: rebuilds results from JSON for the curve alone, needs no change.
    breakdown: FieldBreakdown = field(default_factory=FieldBreakdown)
```

- [ ] **Step 4: Change the aggregation**

In `eval/harness.py`, in `_Accumulator`, replace `field_correct: int = 0` and `field_total: int = 0` with:

```python
    breakdown: FieldBreakdown = FieldBreakdown()
```

Change `add` to take the breakdown and fold it:

```python
    def add(
        self,
        crit: bool,
        facc: dict[str, bool],
        bd: FieldBreakdown,
        prf: tuple[float, float, float],
    ) -> None:
        self.n_receipts += 1
        self.n_critical_correct += int(crit)
        self.breakdown = self.breakdown + bd
        p, r, f = prf
        self.li_precision += p
        self.li_recall += r
        self.li_f1 += f
```

In `add_failure`, pass an all-zero breakdown and update its docstring's last sentence:

```python
        self.failures.append((receipt_id, detail))
        # The empty map and zero breakdown are on purpose: a receipt that
        # produced nothing must not inflate *or* deflate any denominator, only
        # the metrics it genuinely bears on.
        self.add(False, {}, FieldBreakdown(), (0.0, 0.0, 0.0))
```

In `_build_report`, replace the `field_accuracy=...` line with one line — the ratios are properties now, so nothing else is passed:

```python
        breakdown=acc.breakdown,
```

Extend the import block at the top of `eval/harness.py`:

```python
from .metrics import (
    AUTO_APPROVE_THRESHOLD,
    EvalReport,
    EvalResult,
    FieldBreakdown,
    calibration_curve,
    critical_field_accuracy,
    field_accuracy,
    field_breakdown,
    line_item_f1,
    ratio,
)
```

In `run_eval`, compute the breakdown beside the other metrics and carry it:

```python
            facc = field_accuracy(predicted, truth)
            bd = field_breakdown(predicted, truth)
            crit = critical_field_accuracy(predicted, truth)
            prf = line_item_f1(predicted.line_items, truth.line_items)
            conf = _coerce_confidence(confidence)
```

```python
        acc.add(crit, facc, bd, prf)
        results.append(
            EvalResult(
                receipt_id=label_path.stem,
                confidence=conf,
                critical_correct=crit,
                field_acc=facc,
                breakdown=bd,
            )
        )
```

- [ ] **Step 5: Change the committed JSON shape**

In `_report_to_dict`, replace the `"field_accuracy"` entry in `"metrics"` with the six new keys, and rewrite the `"results"` comprehension:

```python
        "metrics": {
            "auto_approval_precision": report.auto_approval_precision,
            "auto_approval_rate": report.auto_approval_rate,
            "critical_field_accuracy": report.critical_field_accuracy,
            "transcription_accuracy": report.transcription_accuracy,
            "transcription_accuracy_core": report.transcription_accuracy_core,
            "transcription_accuracy_line_items": (
                report.transcription_accuracy_line_items
            ),
            "self_report_agreement": report.self_report_agreement,
            "hallucinated_fields": report.hallucinated_fields,
            "correctly_empty_fields": report.correctly_empty_fields,
            "line_item_precision": report.line_item_precision,
            "line_item_recall": report.line_item_recall,
            "line_item_f1": report.line_item_f1,
            "cost_per_receipt": (
                str(report.cost_per_receipt)
                if report.cost_per_receipt is not None
                else None
            ),
            "p50_latency_s": report.p50_latency_s,
            "p95_latency_s": report.p95_latency_s,
        },
```

```python
        "results": [
            {
                "receipt_id": r.receipt_id,
                "confidence": str(r.confidence),
                "critical_correct": r.critical_correct,
                "transcription_correct": r.breakdown.transcription_correct,
                "transcription_total": r.breakdown.transcription_total,
                "self_report_correct": r.breakdown.self_report_correct,
                "self_report_total": r.breakdown.self_report_total,
                "hallucinated": r.breakdown.hallucinated,
                "correctly_empty": r.breakdown.correctly_empty,
                # The per-path map, sorted. §16 wants results committed so
                # regressions show in a diff; two integers cannot show which
                # field moved, and unsorted keys would make every diff noise.
                "field_results": dict(sorted(r.field_acc.items())),
            }
            for r in report.results
        ],
```

Also update `_report_to_dict`'s docstring — delete the sentence beginning *"Per-receipt field maps collapse to counts"*, which this step falsifies, and replace it with:

```python
    """Diff-friendly JSON view. Per-receipt class counts plus the full per-path
    map, sorted: §16 commits results so regressions show in a diff, and only the
    map can show *which* field moved.
    """
```

- [ ] **Step 6: Run the harness tests to verify they pass**

Run: `python -m pytest tests/test_eval_metrics.py`
Expected: PASS. The only pre-existing test changed is the one rename in Step 1.

- [ ] **Step 7: Update the synthetic results fixtures so the stub reflects the write**

`tests/test_cli_reports.py` builds results files by hand for `calibrate` to read. `calibrate` ignores the metric keys, so these pass either way — which makes them a green test asserting a dead contract (review standard 8: the stub reflects the write).

In `_write_results`, replace the `"metrics"` dict with the new key set (same numbers, new names):

```python
        "metrics": {"auto_approval_precision": 0.0, "auto_approval_rate": 0.0,
                    "critical_field_accuracy": 0.0, "transcription_accuracy": 0.0,
                    "transcription_accuracy_core": 0.0,
                    "transcription_accuracy_line_items": 0.0,
                    "self_report_agreement": 0.0, "hallucinated_fields": 0,
                    "correctly_empty_fields": 0,
                    "line_item_precision": 0.0, "line_item_recall": 0.0,
                    "line_item_f1": 0.0, "cost_per_receipt": None,
                    "p50_latency_s": None, "p95_latency_s": None},
```

In the row builder and the two inline row literals, replace `"fields_correct": ..., "fields_total": 1` with `"transcription_correct": ..., "transcription_total": 1`. Grep to find every one:

```bash
git grep -n "fields_correct\|fields_total" -- tests/test_cli_reports.py
```

Expected after the edit: zero hits in that file.

- [ ] **Step 8: Run the CLI report tests**

Run: `python -m pytest tests/test_cli_reports.py`
Expected: PASS. `cmd_calibrate` reads only `confidence` and `critical_correct`, so nothing here should have needed a behaviour change — if a test fails on the *content* of a metric key, stop and report: it means `calibrate` reads more than this plan says it does.

- [ ] **Step 9: Commit**

```bash
git add eval/metrics.py eval/harness.py tests/test_eval_metrics.py tests/test_cli_reports.py
git commit -m "feat: the report carries each class of field separately"
```

---

### Task 3: One renderer, two callers

**Files:**
- Modify: `eval/run_baseline.py`
- Modify: `scripts/try_one_receipt.py`
- Test: `tests/test_run_baseline.py`

**Interfaces:**
- Consumes from Tasks 1–2: `FieldBreakdown`, `ratio`, the new `EvalReport` fields.
- Produces: `eval.run_baseline.format_breakdown(bd: FieldBreakdown) -> str` — the metric-4 block, used by both the batch table and the single-receipt script.

- [ ] **Step 1: Write the failing renderer tests**

In `tests/test_run_baseline.py`, update both existing `EvalReport(...)` constructions — they pass `field_accuracy=0.95` by keyword, which no longer exists. Replace that one keyword in each with:

```python
        breakdown=FieldBreakdown(
            transcription_correct=19, transcription_total=20,
            core_correct=9, core_total=10,
            line_items_correct=10, line_items_total=10,
            self_report_correct=2, self_report_total=4,
            hallucinated=2, correctly_empty=11,
        ),
```

and extend that file's existing import — it currently reads `from eval.metrics import EvalReport  # noqa: E402`:

```python
from eval.metrics import EvalReport, FieldBreakdown  # noqa: E402
```

**Know before you trust this file's green.** `tests/test_run_baseline.py` opens with `pytest.importorskip("PIL")` and `pytest.importorskip("pillow_heif")`, so the **entire module skips** where those are absent. Measured at `1bddd0d`: both are present on this machine and CI installs `.[dev,pipeline,api,openai]`, so the module does run in both places today — this is a latent trap, not a live one. It is worth one command because a renderer pin that skips is not a pin (review standard 14), and ADR-0037 exists because the suite once passed locally only because a package happened to be installed. Confirm these tests actually *ran*:

```bash
python -m pytest tests/test_run_baseline.py -rs
```

`-rs` prints skip reasons. If the module skipped, say so in the ledger rather than reporting the task green — and note that the two new `format_breakdown` tests need neither Pillow nor an image, so if the skip is real they belong in a module that does not skip.

In `test_format_report_contains_metric_labels`, replace `"Field accuracy"` in the expected-labels list with `"Transcription accuracy"`, and append `"Hallucinated fields"`.

Then add:

```python
def test_format_breakdown_renders_every_class():
    from eval.metrics import FieldBreakdown
    from eval.run_baseline import format_breakdown

    text = format_breakdown(FieldBreakdown(
        transcription_correct=9, transcription_total=10,
        core_correct=5, core_total=5,
        line_items_correct=4, line_items_total=5,
        self_report_correct=1, self_report_total=4,
        hallucinated=2, correctly_empty=11,
    ))

    assert "90.00%" in text          # transcription
    assert "Hallucinated fields" in text
    assert "2" in text
    assert "Correctly empty" in text


def test_format_breakdown_renders_an_empty_denominator_as_na_not_zero():
    """A ratio over no paths is undefined, not 0% — the P8.T3 rule, on screen."""
    from eval.metrics import FieldBreakdown
    from eval.run_baseline import format_breakdown

    text = format_breakdown(FieldBreakdown())
    assert "n/a" in text
    assert "0.00%" not in text
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_run_baseline.py`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'field_accuracy'` before the edit, and `ImportError: cannot import name 'format_breakdown'` after it.

That `TypeError` is the rename's proof: the old name is genuinely gone, not shadowed.

- [ ] **Step 3: Implement the shared renderer**

In `eval/run_baseline.py`, add above `format_report`:

```python
def _pct(value: float | None) -> str:
    """A percentage, or ``n/a`` when the ratio is undefined.

    ``None`` renders as ``n/a``, never ``0.00%``: a ratio over no paths is
    undefined, not bad. Same rule the auto-approval line already follows.
    """
    return f"{value * 100:6.2f}%" if value is not None else f"{'n/a':>7}"


def format_breakdown(bd: FieldBreakdown) -> str:
    """Spec §16 metric 4, as the block it needs to be.

    One renderer, two callers — this module's batch table and
    ``scripts/try_one_receipt.py``. The script used to compute its own
    ``correct/len(acc)`` scalar, which meant "what counts as correct" had two
    definitions in a codebase whose ``cmd_eval`` docstring says it has one.
    """
    return "\n".join([
        f"  Transcription accuracy:   "
        f"{_pct(ratio(bd.transcription_correct, bd.transcription_total))}"
        f"   ({bd.transcription_correct}/{bd.transcription_total})",
        f"    core:                   "
        f"{_pct(ratio(bd.core_correct, bd.core_total))}"
        f"   ({bd.core_correct}/{bd.core_total})",
        f"    line items:             "
        f"{_pct(ratio(bd.line_items_correct, bd.line_items_total))}"
        f"   ({bd.line_items_correct}/{bd.line_items_total})",
        f"  Self-report agreement:    "
        f"{_pct(ratio(bd.self_report_correct, bd.self_report_total))}"
        f"   ({bd.self_report_correct}/{bd.self_report_total})",
        f"  Hallucinated fields:      {bd.hallucinated:>12d}",
        f"  Correctly empty fields:   {bd.correctly_empty:>12d}",
    ])
```

Extend this module's import:

```python
from .metrics import EvalReport, FieldBreakdown, ratio
```

- [ ] **Step 4: Use it in the batch table**

In `format_report`, delete the local `def pct` and use `_pct`. Metric 4's line becomes **one call to the shared renderer** — this is the point of the task, and the reason `EvalReport` stores the aggregate breakdown rather than six loose floats:

```python
    lines = [
        "Baseline eval report (spec §16)",
        "=" * 46,
        f"  Receipts:                 {report.n_receipts:>12d}",
        f"  Auto-approved:            {report.n_auto_approved:>12d}",
        f"  Critical-correct:         {report.n_critical_correct:>12d}",
        f"  Failed:                   {report.n_failed:>12d}",
        f"  Auto-approve threshold:   {str(report.auto_approve_threshold):>12}",
        rule,
        f"  Auto-approval precision:  {precision}",
        f"  Auto-approval rate:       {_pct(report.auto_approval_rate)}",
        f"  Critical-field accuracy:  {_pct(report.critical_field_accuracy)}",
        format_breakdown(report.breakdown),
        f"  Line-item precision:      {_pct(report.line_item_precision)}",
        f"  Line-item recall:         {_pct(report.line_item_recall)}",
        f"  Line-item F1:             {_pct(report.line_item_f1)}",
        rule,
        f"  Cost per receipt:         {cost:>12}",
        f"  p50 latency:              {p50:>12}",
        f"  p95 latency:              {p95:>12}",
    ]
```

`format_breakdown` returns a multi-line string; `"\n".join(lines)` at the end handles that without change.

The `precision` local above it currently calls the deleted `pct`; change it to:

```python
    precision = (
        _pct(report.auto_approval_precision)
        if report.n_auto_approved
        else f"{'n/a':>7}"
    )
```

**Correct the stale docstring while you are in this function.** `format_report`'s docstring says `_build_report` *"defines it as ``1.0``"* when nothing is auto-approved. P8.T3 changed that to `None`; the correction reached `_build_report` and `EvalReport`'s comment and missed this third copy. Replace that paragraph's first two sentences with:

```
    **Auto-approval precision renders as ``n/a`` when nothing was
    auto-approved.** ``_build_report`` resolves it to ``None`` in that case
    (P8.T3), and this is the line an operator reads off the terminal as the
    system's headline metric.
```

- [ ] **Step 5: Give the script the same definition**

In `scripts/try_one_receipt.py`, extend the function-local import:

```python
    from eval.metrics import critical_field_accuracy, field_accuracy, field_breakdown, line_item_f1
    from eval.run_baseline import format_breakdown
```

Replace the scoring block — the lines from `acc = field_accuracy(...)` through the `field accuracy` print — with:

```python
    acc = field_accuracy(extraction, truth)
    bd = field_breakdown(extraction, truth)
    precision, recall, f1 = line_item_f1(extraction.line_items, truth.line_items)
    critical = critical_field_accuracy(extraction, truth)

    print("\n" + "-" * 68)
    print("VS GOLDEN LABEL")
    print("-" * 68)
    print(f"  critical fields (merchant+date+total) all correct: {critical}")
    print(format_breakdown(bd))
    print(f"  line-item F1   : {f1:.2f}  (precision {precision:.2f} recall {recall:.2f})")
```

Leave the `MISMATCHED` listing below it exactly as it is — it is the per-path detail, and it is the useful half.

Update this module's docstring: the sentence ending *"(field accuracy, the critical-field gate, line-item F1)"* becomes *"(the §16 metric-4 block, the critical-field gate, line-item F1)"*.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_run_baseline.py`
Expected: PASS.

- [ ] **Step 7: Confirm the old name is gone**

```bash
git grep -n "\.field_accuracy\b" -- src eval scripts tests
git grep -n "\"field_accuracy\"\|fields_correct\|fields_total" -- src eval scripts tests
```

Expected: **zero hits** from both, other than `critical_field_accuracy` (a different metric, which keeps its name) and the pure function `field_accuracy(` being *called*. If either returns a hit naming the report's scalar, the rename is incomplete — a name that kept its spelling and changed its meaning is what §3.7 of the design forbids.

Historical records under `docs/` are out of scope and must keep their old text — see Task 4.

- [ ] **Step 8: Verify the script actually runs**

`scripts/try_one_receipt.py` has **no test coverage** — probed, not assumed. Its import wiring is therefore unpinned, so check it by executing rather than by reading:

```bash
python scripts/try_one_receipt.py --help
```

Expected: the argparse help, exit 0. This catches an import error in the block edited in Step 5, which no test would.

- [ ] **Step 9: Commit**

```bash
git add eval/run_baseline.py scripts/try_one_receipt.py tests/test_run_baseline.py
git commit -m "feat: one renderer for metric 4, and the script stops keeping its own"
```

---

### Task 4: The decision and the refuted finding

**Files:**
- Create: `docs/adr/0040-what-field-accuracy-counts.md`
- Modify: `docs/adr/README.md`
- Modify: `docs/KNOWN_ISSUES.md`

**Interfaces:** none — documentation only. Depends on Tasks 1–3 being merged so the ADR describes what shipped.

- [ ] **Step 1: Write ADR-0040**

Create `docs/adr/0040-what-field-accuracy-counts.md`. Read ADR-0039 first and follow its shape, which is (verified, not recalled):

```
# ADR 0040 — <title>

**Status:** Accepted (2026-08-12)
**Relates to:** ...

Derived <date> by <how>. **Re-derive rather than quote** (ADR-0028 rule 1).

## Context
## Decision
### 1. ...
### 2. ...
## Consequences
## What this ADR does not decide
## References
```

It must record:

- **Context:** the measured floor — an extraction containing nothing scored 42.50% / 37.50% / 36.59% on r001/r002/r003 under the old definition. The contributors: 11 both-null paths, 4 `meta.*` defaults, 2 schema defaults on r001.
- **Decision 1:** the two axes — group from the path string, filled from the truth side only. Why filled is never read from the prediction: it would let a model enlarge its own denominator.
- **Decision 2:** four numbers, and why 3 and 4 are counts rather than ratios (their denominator is a property of the schema, not of the receipt).
- **Decision 3:** rename, never redefine. `field_accuracy` the *function* keeps its name and meaning; the report's scalar does not survive.
- **Decision 4:** `flatten` is not touched, and why (three consumers, empty-container leaves deliberate).
- **Consequences:** the floor is now ~5.9%, with the single residual path named (`receipt.decimal_convention`). Line items stay in the headline denominator and why. Micro-averaging is unchanged and is a known open question. `eval/results/` was empty when this landed, so no committed artefact was invalidated — this was the last free moment.
- **What this does not fix:** three receipts cannot support a ≥99% precision claim (P8.T2). `meta.notes` will always fail, by design.

- [ ] **Step 2: Add the index row**

In `docs/adr/README.md`, append to the table (matching the existing row format exactly):

```markdown
| [0040](0040-what-field-accuracy-counts.md) | What eval field accuracy counts, and the three things it used to average | Accepted |
```

Then add a paragraph to the prose section below the table, in the style of the `**0039**` paragraph that precedes it.

- [ ] **Step 3: Record the refuted finding in ISSUE-001**

In `docs/KNOWN_ISSUES.md`, under "Two side-findings from the smoke run", append a dated note to the `field_accuracy` side-finding. **Do not delete or rewrite the original text** — the diagnosis was right and the record of what was thought is part of the trail:

```markdown
> **Correction, 2026-08-12 — the diagnosis stands, the remedy was refuted.**
> Measured before acting on it (ADR-0030). Excluding `meta.*` moves the floor
> from 42.50% to 39.39% on r001 and by **0.23 points** on r003; excluding only
> `meta.notes` **raises** every floor, because `notes` is a path an empty
> extraction fails, so dropping it removes a penalty rather than a gift. The
> real driver was both-null agreement on fields the receipt does not have — 11
> of r001's 17 free points. **ADR-0040** is what shipped instead.

```

**Do not touch** the `fields_correct 18 / 40` line in the re-measurement table, or the same string in ADR-0039. Those are accurate records of what a past run printed; rewriting them would falsify history to match the present, and ADR-0039 §3 says that measurement is not to be re-derived.

- [ ] **Step 4: Check every copy of the claim**

ADR-0033 §2: a correction goes to every copy. Search for the *claim*, not the phrasing:

```bash
git grep -n "field accuracy" -- docs
git grep -in "45.00%\|45%" -- docs
```

For each hit, decide: is it a **historical record** (leave it) or a **live claim about how the metric works** (correct it)? Report the list and the decision for each in the ledger rather than silently editing.

- [ ] **Step 5: Commit**

```bash
git add docs/adr/0040-what-field-accuracy-counts.md docs/adr/README.md docs/KNOWN_ISSUES.md
git commit -m "docs: ADR-0040, and ISSUE-001's remedy recorded as refuted"
```

---

## Final gate

- [ ] **Run the full gate runner**

Background it — it exceeds a 2-minute tool timeout — and **make no edits while it runs**:

```bash
python scripts/verify.py
```

Expected: all five PASS (pytest, ruff, typecheck, vitest, build).

pytest count should rise by roughly the number of tests this plan adds. **No count is written here**: the suite moves with every milestone and a number in a plan is a claim about a tree that has since changed. Run it.

Vitest should be **unmoved** — no frontend file is in any task's file set. If it moved, something was edited outside scope; stop and report.

- [ ] **Confirm the design's promises actually hold, from the built artefact**

Not from this plan, and not from the ledger:

```bash
python -c "
import json, pathlib, tempfile
from decimal import Decimal as D
from eval.harness import run_eval
from receipts.extract.schema import ReceiptExtraction
tmp = pathlib.Path(tempfile.mkdtemp())
labels = tmp / 'golden' / 'labels'; labels.mkdir(parents=True)
for p in sorted(pathlib.Path('eval/golden/labels').glob('*.json')):
    (labels / p.name).write_text(p.read_text(encoding='utf-8'), encoding='utf-8')
report = run_eval(tmp / 'golden', lambda _p: (ReceiptExtraction(), D('0')), results_dir=tmp / 'results')
print('transcription_accuracy floor:', report.transcription_accuracy)
print('hallucinated:', report.hallucinated_fields, ' correctly_empty:', report.correctly_empty_fields)
payload = json.loads(next((tmp / 'results').glob('*.json')).read_text(encoding='utf-8'))
print('field_accuracy key gone:', 'field_accuracy' not in payload['metrics'])
print('per-path map present:', 'field_results' in payload['results'][0])
"
```

Expected: the floor below `0.10`, `hallucinated: 0`, the old key gone, the map present.

---

## Notes for the implementer

**The plan's claims about existing artefacts are the part that has historically been wrong** — ten milestones, every plan defect the controller's, every one caught by someone who checked instead of trusting. Read the real file before trusting any line here that describes one. **"This step's premise is false" is a valid, expected outcome**; report it with what you measured rather than working around it.

**Task 1 Step 8 is not optional and not a formality.** A floor test that has only ever been green proves nothing (review standard 14). The mutation is what turns it into a pin, and the failure must name the floor — a failure by `AttributeError` means it landed somewhere else (standard 16).

**Existing tests pass unmodified unless the step you are executing tells you, in that step, to change one.** That is the whole bound — no count is given here, because an earlier draft of this sentence said "two exceptions" while the plan mandates three (Task 2 Steps 1 and 7, Task 3 Step 1), which is the enumerated-defence failure this repo has hit repeatedly (review standard 19).

Every authorised change is a **rename or a shape update to match the producer** — never a weakened assertion. If a step's edit would make a test check *less* than it did, stop and report: that is not what any step here intends. Anything else that seems to need a test changed is also a stop-and-report.
