from receipts.extract.paths import SELF_REPORT_LEAVES, group_of, is_filled


def test_group_of_reads_the_path_string_only() -> None:
    assert group_of("meta.notes") == "self_report"
    assert group_of("line_items") == "line_items"
    assert group_of("line_items[0].qty") == "line_items"
    assert group_of("totals.total") == "core"
    assert group_of("receipt.decimal_convention") == "core"


def test_self_report_leaves_are_checked_before_their_prefix() -> None:
    # `is_template_row` lives under `line_items[i].`, which would otherwise
    # claim it. The set is consulted first, and that ordering is the guarantee.
    assert "is_template_row" in SELF_REPORT_LEAVES
    assert group_of("line_items[0].is_template_row") == "self_report"


def test_is_filled_rejects_none_and_empty_containers_only() -> None:
    assert is_filled("SUPERMART") is True
    assert is_filled(0) is True          # a read zero is content
    assert is_filled(False) is True      # so is a read false
    assert is_filled(None) is False
    assert is_filled([]) is False
    assert is_filled({}) is False
