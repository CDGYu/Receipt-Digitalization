"""Golden-set on-ramp tests. Pure and offline — synthetic fixtures under
``tmp_path`` plus the committed ``TEMPLATE.json``. No golden data, no network."""

from __future__ import annotations

import json
import traceback

import pytest

from eval.golden_set import (
    TEMPLATE_PATH,
    composition_stats,
    load_labels,
    load_manifest,
    validate_labels,
)
from receipts.extract.schema import ReceiptExtraction

# A minimal but schema-valid label body. Money is JSON strings so the Decimal
# scale survives the round-trip ("45.00" -> Decimal('45.00'), not '45').
_VALID_LABEL = json.dumps(
    {
        "merchant": {"name": "CORNER STORE"},
        "receipt": {"date": "2026-03-04", "currency": "PHP"},
        "line_items": [
            {
                "position": 0,
                "description_raw": "BREAD",
                "qty": "1",
                "unit_price": "45.00",
                "line_total": "45.00",
            }
        ],
        "totals": {"subtotal": "45.00", "tax": "0.00", "total": "45.00"},
    }
)


# --------------------------------------------------------------------------- #
# TEMPLATE.json
# --------------------------------------------------------------------------- #


def test_template_json_is_schema_valid():
    model = ReceiptExtraction.model_validate_json(
        TEMPLATE_PATH.read_text(encoding="utf-8")
    )
    # A realistic printed receipt: merchant, date, >=2 items, a reconciling total.
    assert model.merchant.name
    assert model.receipt.date
    assert model.receipt.currency
    assert len(model.line_items) >= 2
    assert model.totals.total is not None


# --------------------------------------------------------------------------- #
# validate_labels
# --------------------------------------------------------------------------- #


def test_validate_labels_flags_only_the_bad_file(tmp_path):
    (tmp_path / "good.json").write_text(_VALID_LABEL, encoding="utf-8")
    (tmp_path / "bad.json").write_text("{ not valid json", encoding="utf-8")

    errors = validate_labels(tmp_path)
    assert len(errors) == 1
    assert "bad.json" in errors[0]
    assert "good.json" not in errors[0]


def test_validate_labels_clean_dir_returns_empty(tmp_path):
    (tmp_path / "a.json").write_text(_VALID_LABEL, encoding="utf-8")
    (tmp_path / "b.json").write_text(_VALID_LABEL, encoding="utf-8")
    assert validate_labels(tmp_path) == []


def test_validate_labels_missing_dir_does_not_raise(tmp_path):
    assert validate_labels(tmp_path / "does_not_exist") == []


# --------------------------------------------------------------------------- #
# load_labels
# --------------------------------------------------------------------------- #


def test_load_labels_returns_ids_and_skips_template_and_manifest(tmp_path):
    (tmp_path / "r001.json").write_text(_VALID_LABEL, encoding="utf-8")
    (tmp_path / "r002.json").write_text(_VALID_LABEL, encoding="utf-8")
    (tmp_path / "TEMPLATE.json").write_text(_VALID_LABEL, encoding="utf-8")
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    (tmp_path / "manifest.example.json").write_text("{}", encoding="utf-8")

    labels = load_labels(tmp_path)
    assert set(labels) == {"r001", "r002"}
    assert all(isinstance(v, ReceiptExtraction) for v in labels.values())


def test_a_label_that_will_not_load_names_itself(tmp_path):
    """The strict loader must say WHICH file it choked on.

    It did not. ``path`` is a loop local and the parse error carries only the
    file's *content*, so a reader got the echoed bytes and the loader's line
    number and nothing else. Measured 2026-08-22 over a real run: the offending
    filename appeared **zero** times in the whole pytest output (ISSUE-022).

    That became expensive when ISSUE-021's fix turned a silent skip into an
    abort: one unreadable label now stops the entire session, and the message
    did not say which label to fix. ``eval/golden/README.md`` targets 50-100.

    Asserted on the **rendered traceback** rather than on the mechanism, so the
    pin survives any way of carrying the name -- a note, a wrapped exception, a
    dedicated type. What a reader sees is the property; how it gets there is
    not.
    """
    (tmp_path / "r001.json").write_text(_VALID_LABEL, encoding="utf-8")
    (tmp_path / "r002.json").write_text('{1: "not a string key"}', encoding="utf-8")

    with pytest.raises(Exception) as excinfo:
        load_labels(tmp_path)

    rendered = "".join(traceback.format_exception(excinfo.value))
    assert "r002.json" in rendered, rendered


# --------------------------------------------------------------------------- #
# load_manifest
# --------------------------------------------------------------------------- #


def test_load_manifest_missing_returns_empty(tmp_path):
    assert load_manifest(tmp_path / "nope.json") == {}


def test_load_manifest_reads_sidecar(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"r1": {"category": "handwritten"}}), encoding="utf-8")
    assert load_manifest(path) == {"r1": {"category": "handwritten"}}


def test_load_manifest_malformed_returns_empty(tmp_path):
    # A malformed manifest is a report-time problem, not a crash: return {}.
    path = tmp_path / "manifest.json"
    path.write_text("{ not valid json", encoding="utf-8")
    assert load_manifest(path) == {}


# --------------------------------------------------------------------------- #
# composition_stats
# --------------------------------------------------------------------------- #


def test_composition_stats_counts_from_manifest(tmp_path):
    labels_dir = tmp_path / "labels"
    labels_dir.mkdir()
    for rid in ("r1", "r2", "r3"):
        (labels_dir / f"{rid}.json").write_text(_VALID_LABEL, encoding="utf-8")

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "r1": {"category": "printed_clean", "holdout": False},
                "r2": {"category": "printed_clean", "holdout": True},
                "r3": {"category": "handwritten", "holdout": True},
            }
        ),
        encoding="utf-8",
    )

    stats = composition_stats(labels_dir, manifest_path)
    assert stats["total"] == 3
    assert stats["meets_minimum"] is False  # 3 < 50
    assert stats["by_category"] == {"printed_clean": 2, "handwritten": 1}
    assert stats["holdout_count"] == 2
    assert stats["targets"]["printed_clean"] == 0.60
    assert stats["targets"]["holdout"] == "0.20-0.30"


def test_composition_stats_malformed_manifest_is_safe(tmp_path):
    # A malformed manifest must not blow up the report helper: size counts still
    # work and the manifest-derived breakdown collapses to empty.
    labels_dir = tmp_path / "labels"
    labels_dir.mkdir()
    (labels_dir / "r1.json").write_text(_VALID_LABEL, encoding="utf-8")

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{ not valid json", encoding="utf-8")

    stats = composition_stats(labels_dir, manifest_path)
    assert stats["total"] == 1
    assert stats["by_category"] == {}
    assert stats["holdout_count"] == 0


def test_composition_stats_without_manifest_has_empty_breakdown(tmp_path):
    labels_dir = tmp_path / "labels"
    labels_dir.mkdir()
    (labels_dir / "r1.json").write_text(_VALID_LABEL, encoding="utf-8")

    stats = composition_stats(labels_dir)
    assert stats["total"] == 1
    assert stats["by_category"] == {}
    assert stats["holdout_count"] == 0
    assert stats["meets_minimum"] is False
