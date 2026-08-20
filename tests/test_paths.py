from decimal import Decimal

from receipts.extract.paths import SELF_REPORT_LEAVES, group_of, is_filled, read_nothing
from receipts.extract.schema import ReceiptExtraction


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


def test_a_default_extraction_read_nothing() -> None:
    # This is what `_evaluate` produces when a response does not parse
    # (`response.parsed or ReceiptExtraction()`), so the parse-failure case is
    # covered here rather than as a separate clause.
    assert read_nothing(ReceiptExtraction()) is True


def test_any_transcribed_core_field_means_something_was_read() -> None:
    with_merchant = ReceiptExtraction()
    with_merchant.merchant.name = "SUPERMART INC."
    assert read_nothing(with_merchant) is False

    with_total = ReceiptExtraction()
    with_total.totals.total = Decimal("224.00")
    assert read_nothing(with_total) is False


def test_a_default_valued_field_read_differently_counts() -> None:
    # `decimal_convention` rests at 'point' by default, but it names a
    # convention the document prints. A model that read 'comma' read something.
    read_as_comma = ReceiptExtraction()
    read_as_comma.receipt.decimal_convention = "comma"
    assert read_nothing(read_as_comma) is False


def test_self_report_alone_is_not_content() -> None:
    # The model describing its own reading is not a transcription from the
    # paper, so a difference confined to `meta.` still reads as nothing.
    only_meta = ReceiptExtraction()
    only_meta.meta.is_handwritten = True
    assert read_nothing(only_meta) is True
