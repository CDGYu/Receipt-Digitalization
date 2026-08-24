"""The floor pin: what an extraction containing NOTHING scores.

Deliberately reads the **real** golden labels, unlike ``test_eval_metrics.py``
which is synthetic-only by its own docstring. The whole question here is what
the metric does on this corpus, so a synthetic fixture cannot answer it. Labels
only — tracked JSON, no images (gitignored), no network.

Measured 2026-08-12, before the fix and against the labels as they then stood,
with the old every-path denominator: r001 42.50%, r002 37.50%, r003 36.59%. A
model that read nothing scored above 40%; the one real local run on file beat
that floor by a single path. Those three are a dated record and are NOT what
the old definition gives today -- the labels have since grown, and re-running
ADR-0040's probe at HEAD gives 19.35% / 23.81% / 36.36%. The live figures for
the shipped definition are the ones beside ``MAX_FLOOR`` below.

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

from eval.golden_set import DEFAULT_MANIFEST_PATH, TEMPLATE_PATH, _is_private_label
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
# The SIX pins below exist because the label CONTENT was reachable by nothing:
# blanking every buyer block and deleting every flagged row left the whole suite
# green. They are deliberately properties rather than transcriptions of the
# labels -- a test that restated r001's rows would fire on a legitimate re-read
# of the image and become an obstacle to truth instead of a guard on it.
#
# Said "three" until 2026-08-19: this comment arrived with the first three in
# ca44f81 and 6169893 added the array-order pin below it without touching it.
# Said "four" until 2026-08-25, when ISSUE-019 added the withheld-declaration
# pin and the unknown-path pin together.
# The count is here because it is the thing a reader checks the section against;
# if you add a seventh, this line is part of the change.
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


def _manifest() -> dict:
    """The manifest, read strictly -- deliberately NOT through ``load_manifest``.

    ``eval.golden_set.load_manifest`` collapses a missing, unreadable, malformed
    or non-object manifest to ``{}`` so ``composition_stats`` never raises. That
    is correct for a report and wrong for a guard: every one of those collapses
    would leave the pin below iterating an empty mapping and passing on nothing.
    """
    assert DEFAULT_MANIFEST_PATH.exists(), (
        f"no manifest at {DEFAULT_MANIFEST_PATH} -- the withheld declaration has "
        "nowhere to live, so the pin below would pass without checking anything"
    )
    data = json.loads(DEFAULT_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and data, (
        f"{DEFAULT_MANIFEST_PATH} is empty or is not a JSON object"
    )
    return data


@pytest.mark.parametrize("label_path", _labels(), ids=lambda p: p.stem)
def test_a_tracked_label_declares_that_it_withholds_nothing(label_path: Path):
    """ADR-0050 decision 1's "committed whole or not at all", given a gate (ISSUE-019).

    The rule was stated in the ADR and in ``eval/golden/README.md`` and checked
    by nothing: a tracked ``r*`` label with ``merchant.name``, ``merchant.address``,
    ``merchant.tax_id`` and ``buyer.name`` set to ``null`` passed every gate. The
    nearest guard compares the paths the JSON declares against the paths the model
    carries, and a key present with value ``null`` is in *both* sets, so redaction
    by nulling is invisible to it.

    **Why a declaration and not a detection.** A redacted field and an absent one
    are indistinguishable in the label itself -- the README tells a labeller to
    write ``null`` for anything the receipt does not show, so ``merchant.tax_id:
    null`` is correct for a receipt with no printed tax ID and wrong for one where
    the labeller removed it. Asserting "the PII paths are filled" would redden on
    a legitimate receipt. The manifest is the only place that can hold the
    difference, so the property is moved there.

    **The boundary is reused, not reinvented.** ``_is_private_label`` reads the
    same ``p`` prefix as ``.gitignore``'s ``eval/golden/labels/p*.json``, so
    "may withhold" and "is not committed" stay one rule. A second notion of
    private is exactly the drift this would otherwise introduce.

    **What this does NOT close, stated rather than implied:** a labeller who nulls
    a field and does not declare it still passes. Nothing in a static file can
    catch that. What this buys is that withholding from a *tracked* label is no
    longer expressible without saying so -- an honest redaction now fails loudly,
    and a dishonest one is a written falsehood rather than an invisible default.
    """
    entry = _manifest().get(label_path.stem)
    assert isinstance(entry, dict), (
        f"{label_path.stem} has no manifest entry, so its withheld declaration "
        "cannot be checked and this pin would skip it silently"
    )
    assert "withheld" in entry, (
        f"{label_path.stem}'s manifest entry declares no `withheld` list. Absent "
        "is not the same as empty: a missing key is what this pin exists to "
        "refuse, because it reads as 'nothing withheld' while asserting nothing."
    )
    withheld = entry["withheld"]
    assert isinstance(withheld, list), (
        f"{label_path.stem}'s `withheld` is {type(withheld).__name__}, not a list"
    )
    if _is_private_label(label_path):
        return
    assert withheld == [], (
        f"{label_path.stem} is a tracked label and declares {sorted(withheld)} "
        "withheld. ADR-0050 decision 1: a label is committed whole or not at "
        "all. A receipt with something to withhold is a `p*` label, which "
        "`.gitignore` keeps out of the repository."
    )


@pytest.mark.parametrize(
    "json_path",
    [*_labels(), TEMPLATE_PATH],
    ids=lambda p: p.stem,
)
def test_a_label_declares_no_path_the_schema_does_not(json_path: Path):
    """The other direction of the completeness pin above, and a different defect.

    That pin computes ``complete - declared`` and catches a key the label omits.
    This computes ``declared - complete`` and catches a key the label *invents* --
    which is what a misspelled one is. ``ReceiptExtraction`` is ``extra='ignore'``
    and every field is optional, so a typo'd key is dropped in silence and its
    intended path reads as ``null``.

    **That makes a typo indistinguishable from a withholding**, which is why it
    belongs beside the pin above rather than somewhere else: without this, the
    declaration that pin asks for could be satisfied by a label whose fields are
    null for a reason nobody chose. Measured on this schema: a label whose every
    key is misspelled, and ``{}``, both load as a fully-null extraction and
    ``validate_labels`` returns no error for either.

    ``TEMPLATE.json`` is checked for the same reason it is checked above -- the
    README tells a labeller to copy it, so a typo there is a typo in every label
    made afterwards.
    """
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    declared = set(flatten(raw))
    complete = set(flatten(ReceiptExtraction.model_validate(raw).model_dump()))

    unknown = declared - complete
    assert not unknown, (
        f"{json_path.stem} declares {sorted(unknown)}, which the schema does not "
        f"carry -- `extra='ignore'` drops these in silence and the paths they "
        f"were meant to fill read as null"
    )

