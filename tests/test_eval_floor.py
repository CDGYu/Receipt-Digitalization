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
