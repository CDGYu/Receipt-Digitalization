"""The floor pin: what an extraction containing NOTHING scores.

Deliberately reads the **real** golden labels, unlike ``test_eval_metrics.py``
which is synthetic-only by its own docstring. The whole question here is what
the metric does on this corpus, so a synthetic fixture cannot answer it. Labels
only — tracked JSON, no images (gitignored), no network.

Measured before the fix, with the old every-path denominator:
r001 42.50%, r002 37.50%, r003 36.59%. A model that read nothing scored above
40%; the one real local run on file beat that floor by a single path.

That run is not guesswork and is not read from ``eval/results/``. It is recorded
in ``docs/KNOWN_ISSUES.md`` under ISSUE-001 ("The local path, re-measured
2026-08-11") and again in
``docs/adr/0039-the-local-path-is-a-liveness-check.md``. ``eval/results/`` is
empty by that ADR's decision 2, which keeps liveness artefacts out of it, so its
absence here is the ruling being followed rather than evidence missing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.golden_set import TEMPLATE_PATH
from eval.metrics import field_breakdown, ratio
from receipts.extract.paths import flatten
from receipts.extract.schema import ReceiptExtraction

GOLDEN_LABELS = Path(__file__).resolve().parents[1] / "eval" / "golden" / "labels"

#: An empty extraction must score below this. Stated as a literal, never
#: derived from the code under test: a bound computed by the thing it checks
#: moves with the defect. Measured 2026-08-18: r001 3.6%, r002 4.2%, r003 5.6%.
MAX_FLOOR = 0.10


def _labels() -> list[Path]:
    return sorted(GOLDEN_LABELS.glob("*.json"))


def _truth(label_path: Path) -> ReceiptExtraction:
    return ReceiptExtraction.model_validate(
        json.loads(label_path.read_text(encoding="utf-8"))
    )


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


# --------------------------------------------------------------------------- #
# What the labels themselves must say
#
# The three pins below exist because the label CONTENT was reachable by nothing:
# blanking every buyer block and deleting every flagged row left the whole suite
# green. They are deliberately properties rather than transcriptions of the
# labels -- a test that restated r001's rows would fire on a legitimate re-read
# of the image and become an obstacle to truth instead of a guard on it.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "json_path",
    [*_labels(), TEMPLATE_PATH],
    ids=lambda p: p.stem,
)
def test_a_label_declares_every_field_the_schema_declares(json_path: Path):
    """A key the JSON omits is filled by a schema default and reads as truth.

    This is the only one of the three that closes a *class*: it catches any
    field the schema gains that the labels are never updated to carry, which is
    the same rot ``TEMPLATE.json`` industrialises -- the README tells a labeller
    to copy that file, so a field missing there is missing from every label made
    afterwards. ``TEMPLATE.json`` is checked here for exactly that reason.

    Derived by difference rather than by a list of field names: the parsed model
    knows every path the schema declares, the raw JSON knows every path the
    labeller wrote, and the gap between them is the answer. A named list would
    need editing on every schema change, which is the failure it is meant to
    catch.
    """
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    declared = set(flatten(raw))
    complete = set(flatten(ReceiptExtraction.model_validate(raw).model_dump()))

    missing = complete - declared
    assert not missing, (
        f"{json_path.stem} omits {sorted(missing)} -- the schema declares "
        f"these and the file does not, so a default is standing in for truth"
    )


@pytest.mark.parametrize(
    "json_path",
    [*_labels(), TEMPLATE_PATH],
    ids=lambda p: p.stem,
)
def test_array_order_agrees_with_the_position_values(json_path: Path):
    """Two orderings, and only one of them is what the eval actually reads.

    ``field_accuracy`` joins ``line_items[i]`` by ARRAY INDEX; ``position`` is
    what every human reader trusts. When they disagree, every field of both
    rows is scored against the wrong row and nothing anywhere says so.

    **This would not have caught the printed-order defect fixed in 417c206.**
    There ``position`` equalled its index and both were wrong together, against
    the paper. This catches the other half: a row moved in the array while its
    ``position`` value stays put, or the reverse.

    R051 cannot see it either. Its message promises "0-based, contiguous, and
    in printed order", but its check is ``sorted(positions) == list(range(n))``
    -- every permutation satisfies that, so a shuffled label validates with no
    findings at any severity. See ISSUE-005.
    """
    truth = _truth(json_path)
    positions = [item.position for item in truth.line_items]
    assert positions == list(range(len(positions))), (
        f"{json_path.stem}: array order and position values disagree -- "
        f"positions are {positions} at indices {list(range(len(positions)))}"
    )


def test_every_flagged_row_carries_a_printed_name_and_no_amounts():
    """A blank pre-printed row: a name read off the paper, and nothing else.

    Corpus-wide rather than per-label, because r003's form prints no product
    rows at all -- a parametrised version would pass vacuously on it, and the
    non-vacuity guard would have nothing to stand on.

    This is the pin that also covers a flagged row *gaining* an amount, which
    neither of the other two can see: `_purchased` excludes flagged rows from
    every total and every arithmetic check, so an amount parked on one is money
    that silently leaves the books.
    """
    flagged = [
        (path.stem, item)
        for path in _labels()
        for item in _truth(path).line_items
        if item.is_template_row
    ]
    # Without this the loop below passes vacuously the moment the flagged rows
    # are deleted, which is exactly the rot this pin is here to catch.
    assert flagged, "no golden label records a blank pre-printed row"

    for stem, item in flagged:
        assert item.description_raw.strip(), (
            f"{stem}: a flagged row with no printed name is not a transcription "
            f"of anything"
        )
        assert item.qty is None, f"{stem}/{item.description_raw}: qty"
        assert item.unit_price is None, f"{stem}/{item.description_raw}: unit_price"
        assert item.line_total is None, f"{stem}/{item.description_raw}: line_total"


def test_at_least_one_label_records_a_buyer_name():
    """Existential on purpose, and that is the whole of its strength.

    The universal form -- every label records a buyer -- is wrong the first time
    a receipt arrives without a Sold To block, and a pin that has to be loosened
    is a pin nobody trusts. This one goes red exactly when buyer truth leaves
    the corpus, and survives a receipt that genuinely has none.
    """
    named = [path.stem for path in _labels() if _truth(path).buyer.name]
    assert named, "no golden label records a buyer.name"

