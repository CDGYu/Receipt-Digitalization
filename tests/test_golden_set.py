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


#: A label body that will not parse at all. Kept beside the fixture that uses it
#: so the two cannot drift.
_BROKEN_LABEL = '{1: "not a string key"}'


def test_a_label_that_will_not_load_names_itself(tmp_path):
    """The strict loader must say WHICH file it choked on.

    It did not. ``path`` is a loop local and the parse error carries only the
    file's *content*, so a reader got the echoed bytes and the loader's line
    number and nothing else. Measured 2026-08-22 over a real run: the offending
    filename appeared **zero** times in the whole pytest output (ISSUE-022).

    That became expensive when ISSUE-021's fix turned a silent skip into an
    abort: one unreadable label now stops the entire session, and the message
    did not say which label to fix. ``eval/golden/README.md`` targets 50-100.

    **The healthy labels bracket the broken one, and their absence is asserted.**
    A first version wrote only ``r001`` and a broken ``r002``, so the broken file
    sorted last and "names the file that failed" was indistinguishable from
    "names every file" or "names the last file" -- measured, both of those wrong
    implementations passed it, and naming every file is precisely the failure
    this issue exists to prevent at 50-100 labels.

    Asserted on the **rendered traceback** rather than on the mechanism, so the
    pin survives any way of carrying the name -- a note, a wrapped exception, a
    dedicated type. What a reader sees is the property; how it gets there is not.
    """
    (tmp_path / "r001.json").write_text(_VALID_LABEL, encoding="utf-8")
    (tmp_path / "r002.json").write_text(_BROKEN_LABEL, encoding="utf-8")
    (tmp_path / "r003.json").write_text(_VALID_LABEL, encoding="utf-8")

    with pytest.raises(Exception) as excinfo:
        load_labels(tmp_path)

    rendered = "".join(traceback.format_exception(excinfo.value))
    assert "r002.json" in rendered, rendered
    assert "r001.json" not in rendered, "named a label that loaded fine: " + rendered
    assert "r003.json" not in rendered, "named a label that loaded fine: " + rendered


def test_naming_the_label_does_not_change_what_escapes(tmp_path):
    """The reason the loader uses a note instead of a wrapped exception.

    ``load_labels`` catches to annotate and re-raises unchanged, so every caller
    sees the exception it saw before. That is stated in the loader's docstring,
    in the comment at the site, and in ISSUE-022's resolution -- and until this
    test, in nothing that could fail.

    The reference type is derived here rather than named, so the assertion does
    not hard-code pydantic and cannot rot when the schema library changes: it is
    whatever ``model_validate_json`` raises on the same bytes.

    Goes red if the handler ever wraps -- ``raise RuntimeError(...) from exc``
    leaves the traceback naming the file and every other test green.
    """
    (tmp_path / "r001.json").write_text(_BROKEN_LABEL, encoding="utf-8")

    with pytest.raises(Exception) as direct:
        ReceiptExtraction.model_validate_json(_BROKEN_LABEL)
    with pytest.raises(Exception) as through_loader:
        load_labels(tmp_path)

    assert type(through_loader.value) is type(direct.value)
    assert through_loader.value.__cause__ is None, "re-raised, never wrapped"


# --------------------------------------------------------------------------- #
# Private-label redaction (ADR-0050)
# --------------------------------------------------------------------------- #

#: A private label whose **failing field is itself the PII**. That is the only
#: shape that leaks: pydantic echoes the offending value as ``input_value=`` and
#: says nothing about the fields that parsed. ``merchant.tax_id`` is declared a
#: string, so an id typed without quotes -- an ordinary slip next to the
#: README's money-as-string rule -- puts a real tax id in the message.
_PRIVATE_TAX_ID = "7888999000"
_PRIVATE_LABEL_BAD_TAX_ID = json.dumps({"merchant": {"tax_id": int(_PRIVATE_TAX_ID)}})


def test_validate_labels_does_not_echo_a_private_labels_value(tmp_path):
    """The surface a labeller runs by hand, every batch.

    ``eval/golden/README.md`` and the growing-the-golden-set plan (Task 3,
    steps 1 and 3) both tell the labeller to run ``validate_labels`` and read
    its output in the terminal. Measured 2026-08-25 before this pin: the entry
    for a ``p*`` label read ``... input_value=7888999000, input_type=int ...``,
    so following the documented procedure printed a real third party's tax id
    to the screen, where it is one paste away from a commit or an issue.

    ADR-0050 makes ``p*`` the privacy boundary and ``.gitignore`` already
    carries ``eval/golden/labels/p*.json``; this reuses that same prefix so the
    redaction boundary and the commit boundary stay one rule rather than two.

    **What survives is what the labeller needs to fix it**: which field, and
    why. Only the value goes.
    """
    (tmp_path / "p042.json").write_text(_PRIVATE_LABEL_BAD_TAX_ID, encoding="utf-8")

    reported = validate_labels(tmp_path)

    assert len(reported) == 1, reported
    entry = reported[0]
    assert _PRIVATE_TAX_ID not in entry, "leaked a private label's value: " + entry
    assert "p042.json" in entry, entry
    assert "merchant.tax_id" in entry, "must still say which field: " + entry


def test_load_labels_does_not_echo_a_private_labels_value(tmp_path):
    """The pytest-traceback surface, and the one the handoff named.

    A ``p*`` label that will not parse aborts collection, and the traceback is
    written to the terminal and to any CI log. The filename must still appear
    (ISSUE-022) -- redacting the value must not cost the labeller the ability
    to tell WHICH label to fix.
    """
    (tmp_path / "p042.json").write_text(_PRIVATE_LABEL_BAD_TAX_ID, encoding="utf-8")

    with pytest.raises(Exception) as excinfo:
        load_labels(tmp_path)

    rendered = "".join(traceback.format_exception(excinfo.value))
    assert _PRIVATE_TAX_ID not in rendered, "leaked into the traceback: " + rendered
    assert "p042.json" in rendered, rendered
    assert "merchant.tax_id" in rendered, "must still say which field: " + rendered


def test_a_private_label_that_is_not_json_does_not_echo_its_bytes(tmp_path):
    """A syntax error takes a different pydantic path from a type error.

    ``json_invalid`` echoes a truncated window of the **raw file** rather than
    one field's value, so it leaks whatever happens to sit near the mistake.
    Measured 2026-08-25: a trailing comma after a merchant name rendered as
    ``input_value='{"merchant": {"name": "A...HARMACY CORPORATION",}}'`` -- the
    name is split by the ellipsis, which is exactly why an exact-string search
    for it reports "not present" while a reader sees it plainly.

    Asserted on a distinctive fragment rather than the whole name for that
    reason: the truncation point moves with the file's length, so a test that
    looked only for the intact string would pass while the data was on screen.
    """
    body = '{"merchant": {"name": "ACME PHARMACY CORPORATION",}}'
    (tmp_path / "p042.json").write_text(body, encoding="utf-8")

    with pytest.raises(Exception) as excinfo:
        load_labels(tmp_path)

    rendered = "".join(traceback.format_exception(excinfo.value))
    for fragment in ("ACME", "PHARMACY", "CORPORATION"):
        assert fragment not in rendered, (
            f"leaked the fragment {fragment!r} from a private label: " + rendered
        )
    assert "p042.json" in rendered, rendered


def test_a_public_label_keeps_the_detail_redaction_removes(tmp_path):
    """The scope pin: this fix must not become a blanket.

    ``r*`` labels are public by ADR-0050 -- they carry no third party's data,
    they are committed, and their values are already in git. Redacting them
    would buy nothing and cost the labeller the echoed value that makes a type
    error obvious. It would also contradict
    ``test_naming_the_label_does_not_change_what_escapes``, which requires the
    original exception to escape unwrapped for a public label.

    The expected text is **derived** from a direct parse rather than named, so
    this cannot rot when pydantic changes how it renders a value.
    """
    (tmp_path / "r042.json").write_text(_PRIVATE_LABEL_BAD_TAX_ID, encoding="utf-8")

    with pytest.raises(Exception) as direct:
        ReceiptExtraction.model_validate_json(_PRIVATE_LABEL_BAD_TAX_ID)
    assert _PRIVATE_TAX_ID in str(direct.value), "fixture no longer echoes a value"

    reported = validate_labels(tmp_path)
    assert len(reported) == 1, reported
    assert _PRIVATE_TAX_ID in reported[0], (
        "a public label lost detail it is meant to keep: " + reported[0]
    )


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
