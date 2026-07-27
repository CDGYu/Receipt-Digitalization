"""Extractor tests. No network — FakeVLMClient replays scripted responses."""

from __future__ import annotations

import copy
from datetime import date
from decimal import Decimal as D

import pytest

from receipts.extract.clients.base import ResponseCache, RetryPolicy, VLMTransientError, with_retry
from receipts.extract.clients.fake import FakeVLMClient
from receipts.extract.extractor import (
    PreparedImage,
    extract_with_repair,
    run_consistency,
    triage,
)
from receipts.extract.json_io import (
    JsonParseError,
    build_tool_schema,
    extract_json_blob,
    parse_model_json,
)
from receipts.extract.schema import (
    DocumentType,
    LineItem,
    Merchant,
    ReceiptExtraction,
    ReceiptMeta,
    Totals,
    TriageResult,
)
from receipts.validate.context import ValidationContext

IMG = PreparedImage(b64="ZmFrZQ==", image_hash="abc123")
CTX = ValidationContext(today=date(2026, 7, 26))


def good() -> ReceiptExtraction:
    return ReceiptExtraction(
        merchant=Merchant(name="SUPERMART INC."),
        receipt=ReceiptMeta(date="2026-07-20", currency="PHP"),
        line_items=[
            LineItem(position=0, description_raw="RICE 5KG", qty=D("1"),
                     unit_price=D("100.00"), line_total=D("100.00")),
            LineItem(position=1, description_raw="OIL 1L", qty=D("2"),
                     unit_price=D("50.00"), line_total=D("100.00")),
        ],
        totals=Totals(subtotal=D("200.00"), tax=D("24.00"), discount=D("0.00"),
                      total=D("224.00")),
    )


def broken() -> ReceiptExtraction:
    r = good()
    r.totals.total = D("200.00")  # forgot the tax -> R022
    return r


# --------------------------------------------------------------------------- #
# Tool schema
# --------------------------------------------------------------------------- #


def test_tool_schema_has_no_refs():
    dumped = repr(build_tool_schema(ReceiptExtraction))
    assert "$ref" not in dumped and "$defs" not in dumped


def test_tool_schema_decimals_are_numbers_not_strings():
    schema = build_tool_schema(ReceiptExtraction)
    total = schema["properties"]["totals"]["properties"]["total"]
    types = {b["type"] for b in total["anyOf"]}
    assert types == {"number", "null"}, types


def test_tool_schema_keeps_nested_structure():
    schema = build_tool_schema(ReceiptExtraction)
    item = schema["properties"]["line_items"]["items"]
    assert "description_raw" in item["properties"]
    assert "modifiers" in item["properties"]


def test_tool_schema_preserves_field_descriptions():
    schema = build_tool_schema(ReceiptExtraction)
    assert "ISO 8601" in schema["properties"]["receipt"]["properties"]["date"]["description"]


# --------------------------------------------------------------------------- #
# Response parsing
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw",
    [
        '{"totals": {"total": 1.0}}',
        '```json\n{"totals": {"total": 1.0}}\n```',
        'Here is the data:\n{"totals": {"total": 1.0}}\nHope that helps!',
        '{"totals": {"total": 1.0},}',                       # trailing comma
        '{"merchant": {"name": "A}{B"}, "totals": {"total": 1.0}}',  # braces in string
    ],
)
def test_parser_survives_common_model_misbehaviour(raw):
    parsed = parse_model_json(raw, ReceiptExtraction)
    assert parsed.totals.total == D("1.0")


def test_parser_reports_truncation_clearly():
    with pytest.raises(JsonParseError, match="Unterminated"):
        extract_json_blob('{"totals": {"total": 1.0')


def test_parser_error_names_the_offending_field():
    with pytest.raises(JsonParseError, match="line_items"):
        parse_model_json('{"line_items": "not-a-list"}', ReceiptExtraction)


# --------------------------------------------------------------------------- #
# Triage
# --------------------------------------------------------------------------- #


def test_triage_returns_result():
    client = FakeVLMClient([TriageResult(document_type=DocumentType.HANDWRITTEN_RECEIPT,
                                         estimated_line_item_count=4)])
    result, _ = triage(IMG, client)
    assert result.is_handwritten and result.estimated_line_item_count == 4


def test_triage_failure_does_not_stop_the_pipeline():
    client = FakeVLMClient(["model returned garbage"])
    result, response = triage(IMG, client)
    assert not response.ok
    assert isinstance(result, TriageResult)  # safe defaults, pipeline continues


# --------------------------------------------------------------------------- #
# The repair loop
# --------------------------------------------------------------------------- #


def test_clean_extraction_skips_the_repair_call():
    client = FakeVLMClient([good()])
    outcome = extract_with_repair(IMG, client, ctx=CTX)
    assert len(client.calls) == 1
    assert not outcome.report.has_errors


def test_repair_fires_on_error_and_fixes_it():
    client = FakeVLMClient([broken(), good()])
    outcome = extract_with_repair(IMG, client, ctx=CTX)
    assert len(client.calls) == 2
    assert not outcome.report.has_errors
    assert outcome.extraction.totals.total == D("224.00")


def test_repair_prompt_contains_the_specific_numbers():
    client = FakeVLMClient([broken(), good()])
    extract_with_repair(IMG, client, ctx=CTX)
    repair_prompt = client.calls[1]["user"]
    assert "[R022]" in repair_prompt
    assert "224" in repair_prompt and "200" in repair_prompt


def test_best_attempt_wins_even_when_repair_makes_it_worse():
    """THE regression this design exists to prevent. The repair pass returns
    something with more errors; the original must survive."""
    worse = good()
    worse.totals.total = D("999.00")
    worse.line_items[0].qty = D("7")
    client = FakeVLMClient([broken(), worse])

    outcome = extract_with_repair(IMG, client, ctx=CTX)
    assert outcome.extraction.totals.total == D("200.00")   # the original
    assert outcome.report.error_count < outcome.attempts[1].report.error_count


def test_warnings_alone_do_not_trigger_a_repair_call():
    """Repair costs a full API call. Only ERRORs are worth paying for —
    a missing merchant name is not something a second pass reliably fixes."""
    sparse = good()
    sparse.merchant.name = None          # R012, WARN only
    client = FakeVLMClient([sparse])
    outcome = extract_with_repair(IMG, client, ctx=CTX)
    assert len(client.calls) == 1
    assert outcome.report.warn_count > 0 and not outcome.report.has_errors


def test_null_count_breaks_ties_toward_the_fuller_read():
    """Ranking is (errors, warnings, nulls). With errors and warnings equal,
    prefer the attempt that read more of the receipt."""
    from receipts.extract.extractor import Attempt, _evaluate

    full, sparse = good(), good()
    full.receipt.time = "14:32"          # sparse leaves these null
    full.receipt.number = "OR-0099123"
    full.payment.method = "CASH"

    client = FakeVLMClient([full, sparse])
    a = _evaluate(client.complete_json(system="", user="", images=[],
                                       schema=ReceiptExtraction), CTX, None, "extract")
    b = _evaluate(client.complete_json(system="", user="", images=[],
                                       schema=ReceiptExtraction), CTX, None, "repair")

    assert a.rank()[:2] == b.rank()[:2]      # same errors, same warnings
    assert a.rank() < b.rank()               # fuller read wins
    assert min([b, a], key=lambda x: x.rank()) is a


def test_unparseable_first_attempt_triggers_re_extract_not_repair():
    client = FakeVLMClient(["Invalid JSON: unexpected token", good()])
    outcome = extract_with_repair(IMG, client, ctx=CTX)
    # A repair prompt would embed the previous JSON; a re-extract does not.
    assert "You previously extracted" not in client.calls[1]["user"]
    assert not outcome.report.has_errors


def test_max_repairs_zero_disables_the_loop():
    client = FakeVLMClient([broken()])
    outcome = extract_with_repair(IMG, client, ctx=CTX, max_repairs=0)
    assert len(client.calls) == 1
    assert outcome.report.has_errors


def test_outcome_accumulates_cost_and_latency():
    client = FakeVLMClient([broken(), good()])
    outcome = extract_with_repair(IMG, client, ctx=CTX)
    assert outcome.total_cost == D("0.02")
    assert len(outcome.responses) == 2


def test_resolved_findings_are_marked_for_audit():
    client = FakeVLMClient([broken(), good()])
    outcome = extract_with_repair(IMG, client, ctx=CTX)
    first = outcome.attempts[0].report
    assert any(f.resolved_by_repair for f in first.findings)


# --------------------------------------------------------------------------- #
# Few-shot ordering
# --------------------------------------------------------------------------- #


def test_target_image_is_last_when_few_shots_present():
    from receipts.extract.prompts import FewShot

    client = FakeVLMClient([good()])
    shots = [FewShot(image_b64="c2hvdA==", extraction=good())]
    extract_with_repair(IMG, client, ctx=CTX, few_shots=shots)
    assert client.calls[0]["images"] == 2  # example first, target last


# --------------------------------------------------------------------------- #
# Self-consistency
# --------------------------------------------------------------------------- #


def test_consistency_agrees_when_runs_agree():
    client = FakeVLMClient([good(), good(), good()])
    result, _ = run_consistency(IMG, client, n=3)
    assert result.disputed == []
    assert result.consensus.totals.total == D("224.00")


def test_consistency_flags_a_disagreeing_field():
    a, b, c = good(), good(), good()
    b.totals.total = D("274.00")
    client = FakeVLMClient([a, b, c])

    result, _ = run_consistency(IMG, client, n=3)
    assert "totals.total" in result.disputed
    assert result.agreement["totals.total"] == pytest.approx(2 / 3)
    assert result.consensus.totals.total == D("224.00")  # majority still wins


def test_consistency_nulls_a_field_with_no_majority():
    a, b, c = good(), good(), good()
    a.totals.total, b.totals.total, c.totals.total = D("1"), D("2"), D("3")
    client = FakeVLMClient([a, b, c])

    result, _ = run_consistency(IMG, client, n=3)
    assert result.consensus.totals.total is None  # silence beats a coin flip
    assert "totals.total" in result.disputed


def test_consistency_survives_a_failed_run():
    client = FakeVLMClient([good(), "parse failure", good()])
    result, responses = run_consistency(IMG, client, n=3)
    assert result.runs == 2
    assert sum(1 for r in responses if not r.ok) == 1


# --------------------------------------------------------------------------- #
# Client plumbing
# --------------------------------------------------------------------------- #


def test_retry_backs_off_then_succeeds():
    calls = {"n": 0}
    slept: list[float] = []

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise VLMTransientError("429")
        return FakeVLMClient([good()]).complete_json(
            system="", user="", images=[], schema=ReceiptExtraction
        )

    response = with_retry(flaky, RetryPolicy(max_attempts=4, base_delay_s=0.01,
                                             jitter=False), sleep=slept.append)
    assert response.ok and calls["n"] == 3
    assert slept == [0.01, 0.02]  # exponential


def test_cache_only_stores_deterministic_calls():
    cache = ResponseCache()
    response = FakeVLMClient([good()]).complete_json(
        system="", user="", images=[], schema=ReceiptExtraction
    )
    cache.put("k1", response, temperature=0.0)
    cache.put("k2", response, temperature=0.3)
    assert cache.get("k1") is not None
    assert cache.get("k2") is None  # would manufacture false agreement


def test_cache_prevents_a_second_call():
    cache = ResponseCache()
    client = FakeVLMClient([good()])
    extract_with_repair(IMG, client, ctx=CTX, cache=cache)
    extract_with_repair(IMG, client, ctx=CTX, cache=cache)
    assert len(client.calls) == 1  # second run served from cache
