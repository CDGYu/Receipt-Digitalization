"""The extraction orchestrator: triage -> extract -> validate -> repair.

This is the only module that sequences model calls. It owns no prompt text
(prompts.py) and no rules (validate/), which keeps each of the three testable
in isolation.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal

from ..validate.context import ValidationContext
from ..validate.report import ValidationReport
from ..validate.validator import validate
from . import prompts as P
from .clients.base import ImagePart, ResponseCache, VLMClient, VLMResponse
from .paths import count_nulls, flatten, unflatten
from .schema import ConsistencyResult, ReceiptExtraction, TriageResult

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Carriers
# --------------------------------------------------------------------------- #


@dataclass
class PreparedImage:
    """Output of the preprocess stage, ready for a model call."""

    b64: str
    media_type: str = "image/jpeg"
    image_hash: str = ""
    strips: list["PreparedImage"] = field(default_factory=list)

    def as_part(self, label: str | None = None) -> ImagePart:
        return ImagePart(b64=self.b64, media_type=self.media_type, label=label)


@dataclass
class Attempt:
    extraction: ReceiptExtraction
    report: ValidationReport
    response: VLMResponse
    pass_name: str

    def rank(self) -> tuple[int, int, int]:
        """Sort key — lower is better. Errors dominate, then warnings, then
        how much of the receipt was left unread."""
        return (
            self.report.error_count,
            self.report.warn_count,
            count_nulls(self.extraction),
        )


@dataclass
class ExtractionOutcome:
    extraction: ReceiptExtraction
    report: ValidationReport
    attempts: list[Attempt]
    responses: list[VLMResponse]
    triage: TriageResult | None = None
    consistency: ConsistencyResult | None = None

    @property
    def total_cost(self) -> Decimal:
        return sum((r.cost_usd for r in self.responses), Decimal(0))

    @property
    def total_latency_ms(self) -> int:
        return sum(r.latency_ms for r in self.responses)


# --------------------------------------------------------------------------- #
# Pass 1
# --------------------------------------------------------------------------- #


def triage(image: PreparedImage, client: VLMClient,
           cache: ResponseCache | None = None) -> tuple[TriageResult, VLMResponse]:
    """Cheap classification. Run this on the smallest model that works."""
    prompt = P.build_triage_prompt()
    key = ResponseCache.key(image.image_hash, P.prompt_hash(prompt), client.model_id, 0.0)

    if cache and (hit := cache.get(key)):
        return hit.parsed, hit  # type: ignore[return-value]

    response = client.complete_json(
        system="You classify document images. You never extract amounts.",
        user=prompt,
        images=[image.as_part()],
        schema=TriageResult,
        temperature=0.0,
        max_tokens=512,
        tool_name="classify_document",
    )
    if cache:
        cache.put(key, response, 0.0)

    # A triage failure must not stop the pipeline — fall back to safe defaults
    # and let extraction proceed. Losing the routing hint is much cheaper than
    # losing the receipt.
    result = response.parsed or TriageResult()
    if not response.ok:
        log.warning("Triage failed (%s); falling back to defaults", response.parse_error)
    return result, response  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# Pass 2
# --------------------------------------------------------------------------- #


def extract(
    image: PreparedImage,
    client: VLMClient,
    *,
    triage_result: TriageResult | None = None,
    hints: P.MerchantHints | None = None,
    few_shots: list[P.FewShot] | None = None,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    cache: ResponseCache | None = None,
) -> VLMResponse:
    """The main extraction call."""
    few_shots = few_shots or []
    user = P.build_extraction_prompt(triage_result, hints, few_shots)

    # Few-shot images FIRST, target receipt LAST. Whichever image sits closest
    # to the instructions is the one the model treats as the subject.
    parts: list[ImagePart] = [
        ImagePart(b64=shot.image_b64, media_type=shot.media_type,
                  label=f"Example {i} image:")
        for i, shot in enumerate(few_shots, start=1)
    ]
    parts.append(image.as_part("Receipt to extract:" if few_shots else None))

    key = ResponseCache.key(
        image.image_hash, P.prompt_hash(user + P.SYSTEM_EXTRACTION),
        client.model_id, temperature,
    )
    if cache and (hit := cache.get(key)):
        return hit

    response = client.complete_json(
        system=P.SYSTEM_EXTRACTION,
        user=user,
        images=parts,
        schema=ReceiptExtraction,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if cache:
        cache.put(key, response, temperature)
    return response


# --------------------------------------------------------------------------- #
# Pass 3
# --------------------------------------------------------------------------- #


def repair(
    image: PreparedImage,
    previous: ReceiptExtraction,
    report: ValidationReport,
    client: VLMClient,
    *,
    max_tokens: int = 4096,
) -> VLMResponse:
    """Targeted correction using the specific findings. Never cached — the
    prompt embeds the previous attempt, so a cache hit would be meaningless."""
    user = P.build_repair_prompt(previous, report.render_for_repair_prompt())
    return client.complete_json(
        system=P.SYSTEM_EXTRACTION,
        user=user,
        images=[image.as_part()],
        schema=ReceiptExtraction,
        temperature=0.0,
        max_tokens=max_tokens,
    )


# --------------------------------------------------------------------------- #
# The loop
# --------------------------------------------------------------------------- #


def extract_with_repair(
    image: PreparedImage,
    client: VLMClient,
    *,
    triage_result: TriageResult | None = None,
    ctx: ValidationContext | None = None,
    hints: P.MerchantHints | None = None,
    few_shots: list[P.FewShot] | None = None,
    max_repairs: int = 1,
    normalize_fn=None,
    cache: ResponseCache | None = None,
) -> ExtractionOutcome:
    """Extract, validate, and repair. Returns the BEST attempt, not the last.

    Keeping the best rather than the last matters: repair passes sometimes make
    things worse, especially on poor-legibility images where the model starts
    second-guessing readings that were correct.
    """
    ctx = ctx or ValidationContext()
    if triage_result is not None:
        ctx.triage = triage_result
    normalize_fn = normalize_fn or (lambda x: x)

    attempts: list[Attempt] = []
    responses: list[VLMResponse] = []

    response = extract(
        image, client, triage_result=triage_result, hints=hints,
        few_shots=few_shots, cache=cache,
    )
    responses.append(response)
    attempts.append(_evaluate(response, ctx, normalize_fn, "extract"))

    for round_index in range(max_repairs):
        current = attempts[-1]
        if not current.report.has_errors:
            break

        if not current.response.ok:
            # Nothing parsed, so there is nothing to "repair". Re-extract
            # instead — asking a model to correct an object it never produced
            # wastes a call and usually returns the same broken output.
            log.info("Attempt did not parse; re-extracting rather than repairing")
            response = extract(
                image, client, triage_result=triage_result, hints=hints,
                few_shots=few_shots, cache=None,
            )
            pass_name = "re_extract"
        else:
            response = repair(image, current.extraction, current.report, client)
            pass_name = "repair"

        responses.append(response)
        attempts.append(_evaluate(response, ctx, normalize_fn, pass_name))
        log.info(
            "Repair round %d: %s -> %s",
            round_index + 1, current.report.summary(), attempts[-1].report.summary(),
        )

    best = min(attempts, key=lambda a: a.rank())
    _mark_resolved(attempts[0].report, best.report)

    return ExtractionOutcome(
        extraction=best.extraction,
        report=best.report,
        attempts=attempts,
        responses=responses,
        triage=triage_result,
    )


def _evaluate(response: VLMResponse, ctx: ValidationContext,
              normalize_fn=None, pass_name: str = "extract") -> Attempt:
    """Validate one model response, handling the no-parse case."""
    normalize_fn = normalize_fn or (lambda x: x)
    local_ctx = ValidationContext(
        triage=ctx.triage, ocr_text=ctx.ocr_text, merchant=ctx.merchant,
        consistency=ctx.consistency, parse_error=response.parse_error,
        config=ctx.config, today=ctx.today,
    )
    extraction = response.parsed or ReceiptExtraction()
    if response.ok:
        extraction = normalize_fn(extraction)
    report = validate(extraction, local_ctx)
    return Attempt(extraction=extraction, report=report,
                   response=response, pass_name=pass_name)


def _mark_resolved(first: ValidationReport, best: ValidationReport) -> None:
    """Flag findings that the repair pass fixed, for the audit log."""
    surviving = {f.rule_id for f in best.findings}
    for finding in first.findings:
        finding.resolved_by_repair = finding.rule_id not in surviving


# --------------------------------------------------------------------------- #
# Self-consistency
# --------------------------------------------------------------------------- #


def run_consistency(
    image: PreparedImage,
    client: VLMClient,
    *,
    triage_result: TriageResult | None = None,
    hints: P.MerchantHints | None = None,
    n: int = 3,
    temperature: float = 0.3,
) -> tuple[ConsistencyResult, list[VLMResponse]]:
    """Extract n times independently and diff the results field by field.

    Disagreement across runs is an honest uncertainty estimate. A model's
    self-reported confidence is not — asked directly, it will tell you it is
    confident about a handwritten 1 that is actually a 7.

    Never cache these calls: a cache hit would return the same answer n times
    and manufacture perfect agreement.
    """
    runs: list[ReceiptExtraction] = []
    responses: list[VLMResponse] = []

    for _ in range(n):
        response = extract(
            image, client, triage_result=triage_result, hints=hints,
            temperature=temperature, cache=None,
        )
        responses.append(response)
        if response.ok:
            runs.append(response.parsed)  # type: ignore[arg-type]

    if not runs:
        return ConsistencyResult(runs=n), responses
    if len(runs) == 1:
        return ConsistencyResult(runs=n, consensus=runs[0], agreement={}), responses

    consensus, agreement, disputed, values = _vote(runs)
    return (
        ConsistencyResult(
            runs=len(runs), consensus=consensus, agreement=agreement,
            disputed=disputed, values_by_path=values,
        ),
        responses,
    )


def _vote(runs: list[ReceiptExtraction]):
    """Per-path majority vote. No strict majority means the field is nulled and
    marked disputed — silence is the correct output when the readings conflict.
    """
    flattened = [flatten(r) for r in runs]
    all_paths = sorted({p for f in flattened for p in f})

    merged: dict[str, object] = {}
    agreement: dict[str, float] = {}
    disputed: list[str] = []
    values_by_path: dict[str, list] = {}

    for path in all_paths:
        observed = [f.get(path) for f in flattened]
        tally = Counter(json.dumps(v, sort_keys=True, default=str) for v in observed)
        top_key, top_count = tally.most_common(1)[0]

        ratio = top_count / len(flattened)
        agreement[path] = ratio

        if top_count * 2 > len(flattened):  # strict majority
            merged[path] = next(v for v in observed
                                if json.dumps(v, sort_keys=True, default=str) == top_key)
        else:
            merged[path] = None
            disputed.append(path)

        if ratio < 1.0:
            distinct = []
            for value in observed:
                if value not in distinct:
                    distinct.append(value)
            values_by_path[path] = distinct
            if path not in disputed:
                disputed.append(path)

    consensus = ReceiptExtraction.model_validate(unflatten(merged))
    return consensus, agreement, disputed, values_by_path
