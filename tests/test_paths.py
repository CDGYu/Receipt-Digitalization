from decimal import Decimal

from receipts.extract.paths import (
    SELF_REPORT_LEAVES,
    _content_paths,
    group_of,
    is_filled,
    read_nothing,
)
from receipts.extract.schema import LineItem, ReceiptExtraction


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


def test_a_blank_line_item_is_not_content() -> None:
    """A row the model emitted but read nothing into is still nothing read.

    `LineItem()` rests at `position=0` and `description_raw=""`, and `is_filled`
    accepts both -- `0` is content, and `""` is a `str` rather than an empty
    *container*. So a model answering R013's "Triage estimated roughly 1 line
    items" with a single empty row used to read as having read something, and
    the fallback would not have fired. Measured, not imagined: triage returned
    `est_items=1` on r002, which is the prompt that invites exactly this.
    """
    one_blank = ReceiptExtraction(line_items=[LineItem()])
    assert read_nothing(one_blank) is True


def test_blank_rows_are_not_content_however_many_or_however_numbered() -> None:
    """Two blank rows, and the same two after `normalize` renumbers them.

    `normalize` fills missing positions by order and sorts
    (`normalize/__init__.py`), so a pair of blank rows can arrive numbered 0,1
    rather than 0,0. Position is structural -- assigned by order, not read off
    the paper -- so neither spelling may count as content.
    """
    assert read_nothing(ReceiptExtraction(line_items=[LineItem(), LineItem()])) is True
    renumbered = ReceiptExtraction(
        line_items=[LineItem(position=0), LineItem(position=1)]
    )
    assert read_nothing(renumbered) is True


def test_a_row_carrying_one_real_value_is_content() -> None:
    """The other direction, reverted separately: the row baseline must not
    swallow a row the model actually read something into."""
    assert read_nothing(ReceiptExtraction(line_items=[LineItem(description_raw="COKE")])) is False
    assert read_nothing(ReceiptExtraction(line_items=[LineItem(qty=Decimal("2"))])) is False


def test_the_baseline_is_not_empty_so_the_compare_cannot_collapse() -> None:
    """The quiet failure mode this predicate has, pinned.

    `read_nothing` is a comparison against the default's filled paths. If the
    schema ever left `core` with no filled defaults at all, that comparison
    would silently become the emptiness test the design explicitly rejects --
    and every test above would still pass. This is the only assertion that
    notices.
    """
    assert _content_paths(ReceiptExtraction()), (
        "the default extraction has no filled core paths, so read_nothing has "
        "collapsed into the emptiness form spec 3.1 rejects"
    )


def test_self_report_alone_is_not_content() -> None:
    # The model describing its own reading is not a transcription from the
    # paper, so a difference confined to `meta.` still reads as nothing.
    only_meta = ReceiptExtraction()
    only_meta.meta.is_handwritten = True
    assert read_nothing(only_meta) is True
