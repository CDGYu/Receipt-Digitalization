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


def test_the_repair_loop_reports_every_attempt():
    """The keystone the sweep threshold and the job ceiling both rest on.

    Extract dominates a receipt, so if it narrated only on stage entry the
    heartbeat would go cold during entirely normal work and the sweep would
    presume a live run dead. Three reports: the first attempt, the repair, and
    the best-attempt choice.
    """
    seen: list[str | None] = []
    client = FakeVLMClient([broken(), good()])
    extract_with_repair(IMG, client, ctx=CTX, progress=lambda e: seen.append(e.detail))
    assert len(seen) == 3
    assert "attempt 1" in seen[0]
    assert "attempt 2" in seen[1]
    assert "kept attempt" in seen[2]


def test_a_raising_sink_does_not_escape_the_per_attempt_report():
    """`_report`'s own guard, driven directly.

    `pipeline.py` hands `extract_with_repair` a `fan_out` product, which
    swallows per delivery, so a raising sink sent through the pipeline never
    reaches this guard -- removing it left the whole suite green. Calling
    `_report` with a raw sink is what actually pins it.

    `seen` is asserted too: a guard that stopped calling the sink would
    otherwise satisfy "nothing escaped" while guarding nothing.
    """
    from receipts.extract.extractor import _evaluate, _report

    client = FakeVLMClient([good()])
    attempt = _evaluate(
        client.complete_json(system="", user="", images=[], schema=ReceiptExtraction),
        CTX, None, "extract",
    )
    seen: list[str | None] = []

    def boom(event):
        seen.append(event.detail)
        raise RuntimeError("sink")

    _report(boom, [attempt])

    assert seen and seen[0].startswith("attempt 1")


def test_a_raising_sink_does_not_escape_the_best_attempt_choice():
    """The third guard, isolated from the second.

    The sink raises **only** on the kept-attempt event, so `_report`'s guard
    is not involved and this test reddens for the best-attempt block alone.
    Asserting the outcome as well proves the extraction survived rather than
    merely that no exception surfaced.
    """
    seen: list[str] = []

    def boom(event):
        if event.detail and event.detail.startswith("kept attempt"):
            seen.append(event.detail)
            raise RuntimeError("sink")

    client = FakeVLMClient([good()])
    outcome = extract_with_repair(IMG, client, ctx=CTX, progress=boom)

    assert seen and seen[0].startswith("kept attempt")
    assert outcome.extraction.totals.total == D("224.00")


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


def test_evaluate_carries_every_context_field_through_to_the_rules(monkeypatch):
    """PROPERTY: `_evaluate` hands the rules every ValidationContext field it was
    given, except `parse_error`, which it must overwrite with this response's.

    `_evaluate` builds a fresh context per attempt so `parse_error` describes
    THIS response rather than being written into a context shared across a
    thread pool. It used to do that by ENUMERATING the fields to carry over, and
    an enumeration carries only the fields that existed when it was written: it
    dropped `expected_buyer_name` and `expected_buyer_tax_id`, so R014/R015 were
    inert on every real pipeline run while every rule unit test stayed green.

    This iterates `dataclasses.fields()` instead of naming fields, so it needs no
    edit when field ten arrives — and the first loop is what makes that true. A
    new field left at its default in the probe would make "carried" and "dropped
    and re-defaulted" indistinguishable, so the probe is required to differ from
    the default on every field, and says so by name when it does not.
    """
    import dataclasses

    from receipts.extract.clients.base import VLMResponse
    from receipts.extract.extractor import _evaluate
    from receipts.extract.schema import ConsistencyResult, Legibility
    from receipts.validate import validator as validator_module
    from receipts.validate.context import RuleConfig
    from receipts.validate.report import Severity
    from receipts.validate.rules import Rule

    probe_ctx = ValidationContext(
        triage=TriageResult(
            document_type=DocumentType.HANDWRITTEN_RECEIPT,
            legibility=Legibility.POOR,
            estimated_line_item_count=7,
        ),
        ocr_text="probe ocr text",
        merchant="probe merchant",
        consistency=ConsistencyResult(runs=3, disputed=["totals.total"]),
        parse_error="the caller's parse error",
        expected_buyer_name="IDEAL SOURCE",
        expected_buyer_tax_id="222-222-222-000",
        config=RuleConfig(max_qty=D("7")),
        today=date(2026, 1, 2),
    )

    for f in dataclasses.fields(ValidationContext):
        default = (
            f.default if f.default is not dataclasses.MISSING else f.default_factory()
        )
        assert getattr(probe_ctx, f.name) != default, (
            f"probe_ctx.{f.name} is still its default; give this field a "
            "distinctive value, or the test cannot tell carried from dropped"
        )

    seen: list[ValidationContext] = []

    class _CtxProbe(Rule):
        id = "R999"
        severity = Severity.INFO

        def check(self, r, ctx):
            seen.append(ctx)
            return []

    monkeypatch.setattr(validator_module, "RULES", [_CtxProbe()])

    response = VLMResponse(parsed=None, raw=None, model_id="probe",
                           parse_error="this response did not parse")
    _evaluate(response, probe_ctx)

    assert len(seen) == 1
    carried = seen[0]
    for f in dataclasses.fields(ValidationContext):
        if f.name == "parse_error":
            continue
        assert getattr(carried, f.name) == getattr(probe_ctx, f.name), \
            f"_evaluate dropped ValidationContext.{f.name}"

    # The one field that must NOT be carried: it describes this response...
    assert carried.parse_error == "this response did not parse"
    # ...and the caller's context is not written through in the process.
    assert probe_ctx.parse_error == "the caller's parse error"
