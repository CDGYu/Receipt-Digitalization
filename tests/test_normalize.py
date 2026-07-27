"""Tests for the normalization layer.

Normalization SAFELY canonicalizes an extraction: it may reformat a value but
must never invent one, never touch money ``Decimal`` values, never fix an
ambiguous date by guessing, and never mutate its input. Null in -> null out.
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal

from receipts.extract.schema import (
    LineItem,
    Merchant,
    ReceiptExtraction,
    ReceiptMeta,
    Totals,
)
from receipts.normalize import (
    clean_text,
    detect_decimal_convention,
    expand_two_digit_year,
    normalize,
    normalize_currency,
    normalize_merchant_name,
    parse_date,
    parse_money,
    parse_time,
    quantize_money,
)

# --------------------------------------------------------------------------- #
# numbers.parse_money
# --------------------------------------------------------------------------- #


def test_parse_money_refuses_letters_never_guesses():
    # A handwritten "O" is not a zero. Turning "O.50" into 0.50 is the exact
    # silent corruption this system exists to prevent.
    assert parse_money("O.50") is None


def test_parse_money_comma_convention():
    assert parse_money("1.234,56", convention="comma") == Decimal("1234.56")


def test_parse_money_point_convention_strips_thousands():
    assert parse_money("1,234.56") == Decimal("1234.56")


def test_parse_money_strips_currency_symbol():
    assert parse_money("$1,234.56") == Decimal("1234.56")


def test_parse_money_space_thousands_with_comma_decimal():
    assert parse_money("1 234,56", convention="comma") == Decimal("1234.56")


def test_parse_money_eu_cents():
    assert parse_money("9,99", convention="comma") == Decimal("9.99")


def test_parse_money_accounting_parentheses_are_negative():
    assert parse_money("(5.00)") == Decimal("-5.00")


def test_parse_money_leading_minus_is_negative():
    assert parse_money("-5.00") == Decimal("-5.00")


def test_parse_money_blank_and_none_are_none():
    assert parse_money("   ") is None
    assert parse_money(None) is None


def test_parse_money_passes_decimal_through_unchanged():
    assert parse_money(Decimal("3.50")) == Decimal("3.50")


def test_parse_money_rejects_garbage_after_normalization():
    assert parse_money("1.2.3") is None


# --------------------------------------------------------------------------- #
# numbers.detect_decimal_convention
# --------------------------------------------------------------------------- #


def test_detect_convention_picks_comma_for_eu_samples():
    assert detect_decimal_convention(["1.234,56", "9,99", "1.000,00"]) == "comma"


def test_detect_convention_picks_point_for_us_samples():
    assert detect_decimal_convention(["1,234.56", "9.99"]) == "point"


def test_detect_convention_uses_locale_prior_when_ambiguous():
    # "1.234" alone is ambiguous (1234 or 1.234); the merchant locale decides.
    assert detect_decimal_convention(["1.234"], merchant_default_locale="de-DE") == "comma"
    assert detect_decimal_convention(["1.234"], merchant_default_locale="en-US") == "point"


def test_detect_convention_defaults_to_point_with_no_signal():
    assert detect_decimal_convention([]) == "point"


# --------------------------------------------------------------------------- #
# numbers.quantize_money
# --------------------------------------------------------------------------- #


def test_quantize_money_rounds_half_up():
    assert quantize_money(Decimal("1.005")) == Decimal("1.01")
    assert quantize_money(Decimal("1.004")) == Decimal("1.00")


def test_quantize_money_respects_places():
    assert quantize_money(Decimal("2.5"), places=0) == Decimal("3")


# --------------------------------------------------------------------------- #
# dates.parse_date / parse_time / expand_two_digit_year
# --------------------------------------------------------------------------- #


def test_parse_date_iso_is_unambiguous():
    assert parse_date("2026-03-14") == (date(2026, 3, 14), False)


def test_parse_date_iso_with_slashes():
    assert parse_date("2026/03/14") == (date(2026, 3, 14), False)


def test_parse_date_day_over_twelve_is_unambiguous():
    assert parse_date("13/04/2026") == (date(2026, 4, 13), False)


def test_parse_date_both_le_twelve_is_ambiguous():
    assert parse_date("03/04/2026") == (None, True)


def test_parse_date_hint_resolves_ambiguity():
    assert parse_date("07/04/2026", hint_format="%d/%m/%Y") == (date(2026, 4, 7), False)


def test_parse_date_invalid_calendar_date_is_not_ambiguous():
    assert parse_date("2026-13-01") == (None, False)


def test_parse_date_empty_and_garbage():
    assert parse_date("") == (None, False)
    assert parse_date("not a date") == (None, False)


def test_parse_time_24h_and_12h():
    assert parse_time("14:32") == time(14, 32)
    assert parse_time("2:32 PM") == time(14, 32)


def test_parse_time_rejects_garbage():
    assert parse_time("nope") is None


def test_expand_two_digit_year_sliding_window():
    assert expand_two_digit_year(23, date(2025, 6, 1)) == 2023
    assert expand_two_digit_year(85, date(2025, 6, 1)) == 1985
    assert expand_two_digit_year(26, date(2026, 1, 1)) == 2026


def test_parse_date_two_digit_year_uses_injected_today():
    # 2-digit-year DMY (day > 12 so the order is unambiguous). Injecting `today`
    # makes the sliding-window expansion deterministic and testable without
    # depending on the wall clock.
    assert parse_date("13/04/26", today=date(2026, 1, 1)) == (date(2026, 4, 13), False)
    # Sliding-window branch: '85' is >50 years ahead of 2026, so it slides back
    # a century to 1985 rather than forward to 2085.
    assert parse_date("13/04/85", today=date(2026, 1, 1)) == (date(1985, 4, 13), False)


# --------------------------------------------------------------------------- #
# text.clean_text / normalize_merchant_name / normalize_currency
# --------------------------------------------------------------------------- #


def test_clean_text_strips_controls_and_collapses_whitespace():
    assert clean_text("  hello\x00\t world \n") == "hello world"


def test_clean_text_nfkc_normalizes_compatibility_chars():
    assert clean_text("\uff21\uff22\uff23") == "ABC"


def test_normalize_merchant_name_strips_legal_suffix_for_fingerprint():
    assert normalize_merchant_name("SuperMart, Inc.") == "supermart"
    assert normalize_merchant_name("Joe's Coffee CO") == "joe s coffee"


def test_normalize_currency_prefers_explicit_iso_code():
    assert normalize_currency("PHP", "USD") == "PHP"


def test_normalize_currency_ignores_ambiguous_symbol_falls_back():
    # A bare "$" is ambiguous (USD/CAD/AUD/...). Do not guess from it; the
    # merchant default resolves instead.
    assert normalize_currency("$", "USD") == "USD"


def test_normalize_currency_returns_none_rather_than_guessing():
    assert normalize_currency("$", None, None) is None
    assert normalize_currency("XYZ", "ABC", "DEF") is None


def test_normalize_currency_uses_system_default_last():
    assert normalize_currency(None, None, "USD") == "USD"
    assert normalize_currency(None, None, None) is None


def test_normalize_currency_canonicalizes_case():
    assert normalize_currency("usd", None) == "USD"


# --------------------------------------------------------------------------- #
# top-level normalize
# --------------------------------------------------------------------------- #


def test_normalize_does_not_mutate_input_and_null_stays_null():
    raw = ReceiptExtraction(
        merchant=Merchant(name=None, address=None),
        receipt=ReceiptMeta(date=None, currency="PHP"),
        line_items=[
            LineItem(position=0, description_raw="RICE", line_total=Decimal("100.00")),
        ],
    )
    before = raw.model_dump()
    result = normalize(raw)
    after = raw.model_dump()

    assert before == after  # raw untouched (deep copy)
    assert result is not raw
    assert result.merchant.name is None  # null in -> null out
    assert result.receipt.date is None


def test_normalize_fills_missing_positions_by_order():
    raw = ReceiptExtraction(
        line_items=[
            LineItem(description_raw="first"),
            LineItem(description_raw="second"),
            LineItem(description_raw="third"),
        ]
    )
    result = normalize(raw)
    assert [it.position for it in result.line_items] == [0, 1, 2]
    assert [it.description_raw for it in result.line_items] == ["first", "second", "third"]


def test_normalize_sorts_line_items_by_position():
    raw = ReceiptExtraction(
        line_items=[
            LineItem(position=2, description_raw="C"),
            LineItem(position=0, description_raw="A"),
            LineItem(position=1, description_raw="B"),
        ]
    )
    result = normalize(raw)
    assert [it.position for it in result.line_items] == [0, 1, 2]
    assert [it.description_raw for it in result.line_items] == ["A", "B", "C"]


def test_normalize_canonicalizes_unambiguous_date():
    raw = ReceiptExtraction(receipt=ReceiptMeta(date="13/04/2026"))
    assert normalize(raw).receipt.date == "2026-04-13"


def test_normalize_nulls_ambiguous_date_and_keeps_raw():
    raw = ReceiptExtraction(receipt=ReceiptMeta(date="03/04/2026"))
    result = normalize(raw)
    assert result.receipt.date is None
    assert result.receipt.date_raw == "03/04/2026"


def test_normalize_leaves_money_decimals_untouched():
    # normalize must NOT re-quantize or round money; quantize_money is display
    # only and must never run before validation.
    raw = ReceiptExtraction(
        line_items=[LineItem(position=0, description_raw="X", line_total=Decimal("100.005"))],
        totals=Totals(total=Decimal("100.005")),
    )
    result = normalize(raw)
    assert result.totals.total == Decimal("100.005")
    assert result.line_items[0].line_total == Decimal("100.005")


def test_normalize_cleans_text_fields():
    raw = ReceiptExtraction(
        merchant=Merchant(name="  ACME\x00  STORE  "),
        line_items=[LineItem(position=0, description_raw="RICE\t\t5KG")],
    )
    result = normalize(raw)
    assert result.merchant.name == "ACME STORE"
    assert result.line_items[0].description_raw == "RICE 5KG"


def test_normalize_resolves_currency_and_drops_ambiguous_symbol():
    with_code = normalize(ReceiptExtraction(receipt=ReceiptMeta(currency="usd")))
    assert with_code.receipt.currency == "USD"

    with_symbol = normalize(ReceiptExtraction(receipt=ReceiptMeta(currency="$")))
    assert with_symbol.receipt.currency is None
