"""The extraction orchestrator: triage -> extract -> validate -> repair.

This is the only module that sequences model calls. It owns no prompt text
(prompts.py) and no rules (validate/), which keeps each of the three testable
in isolation.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from typing import Callable

from ..progress import ProgressEvent
from ..validate.context import ValidationContext
from ..validate.report import ValidationReport
from ..validate.rules import within_tolerance
from ..validate.validator import validate
from . import prompts as P
from .clients.base import ImagePart, ResponseCache, VLMClient, VLMResponse
from .lineitem_align import align_line_items
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


def _report(progress, attempts: list[Attempt]) -> None:
    """Describe the attempt that just finished.

    Counted from `attempts` rather than from a counter variable, so the number
    cannot disagree with the list it describes. A sink that raises is swallowed:
    narration is never load-bearing.
    """
    if progress is None:
        return
    last = attempts[-1]
    errors = last.report.error_count
    detail = (
        f"attempt {len(attempts)} ({last.pass_name}): "
        f"{errors} error{'' if errors == 1 else 's'}"
    )
    event = ProgressEvent(stage="extract", detail=detail)
    try:
        progress(event)
    except Exception:
        log.warning("progress sink raised during extract; continuing", exc_info=True)


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
    progress: "Callable[[ProgressEvent], None] | None" = None,
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
    _report(progress, attempts)

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
        _report(progress, attempts)
        log.info(
            "Repair round %d: %s -> %s",
            round_index + 1, current.report.summary(), attempts[-1].report.summary(),
        )

    best = min(attempts, key=lambda a: a.rank())
    if progress is not None:
        kept = attempts.index(best) + 1
        event = ProgressEvent(
            stage="extract", detail=f"kept attempt {kept} of {len(attempts)}"
        )
        try:
            progress(event)
        except Exception:
            log.warning(
                "progress sink raised choosing best attempt; continuing", exc_info=True
            )
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
    # A per-attempt copy, so `parse_error` describes THIS response and is not
    # written into a context shared across a thread pool. It must be a COPY, not
    # a field-by-field rebuild: an enumeration carries over only the fields that
    # existed when it was written, so every field added to ValidationContext
    # afterwards is silently dropped on the one path the pipeline actually runs.
    # That is not hypothetical -- it is how `expected_buyer_name` arrived, and
    # R014/R015 were inert on every real run until this became `replace`.
    local_ctx = replace(ctx, parse_error=response.parse_error)
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
    critical_runs: int = 0,
    critical_fields: Sequence[str] = (),
) -> tuple[ConsistencyResult, list[VLMResponse]]:
    """Extract n times independently and diff the results field by field.

    Disagreement across runs is an honest uncertainty estimate. A model's
    self-reported confidence is not — asked directly, it will tell you it is
    confident about a handwritten 1 that is actually a 7.

    Never cache these calls: a cache hit would return the same answer n times
    and manufacture perfect agreement.

    ``critical_fields`` buys a *second, larger* n for the paths that matter
    (P7.T1). No field can be sampled on its own — every path comes out of the
    same whole-receipt call — so the extra evidence is whole extra passes, and
    the only real question is when to pay for it. It is spent on demand: run
    ``n``, and go to ``critical_runs`` only when one of those paths came back
    with no majority. A receipt whose total, date and merchant all agree still
    costs ``n``, which matters on a box where ADR-0039 measures one extract in
    minutes.

    **This is not ``consistency_runs`` with a different name.** Raising that
    takes every path to the larger n on every handwritten receipt, buying the
    same expensive evidence for ``line_items[7].qty`` as for the total. Both
    default to off here, so a caller that passes neither gets exactly the
    behaviour this function has always had.
    """
    runs: list[ReceiptExtraction] = []
    responses: list[VLMResponse] = []

    def sample(times: int) -> None:
        for _ in range(times):
            response = extract(
                image, client, triage_result=triage_result, hints=hints,
                temperature=temperature, cache=None,
            )
            responses.append(response)
            if response.ok:
                runs.append(response.parsed)  # type: ignore[arg-type]

    sample(n)
    attempted = n

    # The escalation reads the *first* vote and then adds to the sample it
    # already has, rather than re-extracting: those runs are evidence, and
    # paying for them twice would make the critical path cost `n + critical_runs`
    # instead of `critical_runs`. `_vote` is pure and works off values already
    # in memory, so calling it twice costs nothing a model can measure.
    #
    # **The trigger is "failed to resolve", NOT `disputed`.** `disputed` in this
    # module means *not unanimous* (see the `ratio < 1.0` branch in `_vote`), so
    # a 3-2 or 2-1 majority is listed there alongside a genuine three-way split.
    # Triggering on it would escalate on almost every handwritten receipt --
    # these calls run at temperature 0.3 precisely so the runs differ -- and
    # that is the always-pay-five behaviour this argument exists to avoid. A
    # path is unresolved when the vote found no strict majority and nulled it:
    # in `disputed` *and* null in the consensus. Unanimous null is neither.
    if critical_runs > n and len(runs) > 1:
        consensus, _, disputed, _ = _vote(runs)
        flat = flatten(consensus)
        if any(p in disputed and flat.get(p) is None for p in critical_fields):
            sample(critical_runs - n)
            attempted = critical_runs

    if not runs:
        return ConsistencyResult(runs=attempted), responses
    if len(runs) == 1:
        return ConsistencyResult(runs=attempted, consensus=runs[0], agreement={}), responses

    consensus, agreement, disputed, values = _vote(runs)
    return (
        ConsistencyResult(
            runs=len(runs), consensus=consensus, agreement=agreement,
            disputed=disputed, values_by_path=values,
        ),
        responses,
    )


#: A flattened line-item path, split into its row index and its field.
_LINE_ITEM_PATH = re.compile(r"^line_items\[(\d+)\]\.(.+)$")


def _as_number(value: object) -> Decimal | None:
    """``value`` as a :class:`Decimal`, or ``None`` when it is not a number.

    **Money reaches this module as a string**, measured rather than assumed:
    :func:`~receipts.extract.paths.flatten` runs ``model_dump(mode="json")``, so
    ``totals.total`` arrives as ``'112.00'``. Tolerance therefore has to parse
    before it can compare.

    Anything that does not parse -- a merchant name, a date like ``2026-07-20``
    -- comes back ``None`` and is compared exactly, which is the right answer for
    a reading that is not a quantity. Deciding by *what the value is* rather than
    by a list of money paths is deliberate: a path list would silently stop
    covering a field the day the schema grows one.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, str):
        try:
            return Decimal(value)
        except InvalidOperation:
            return None
    return None


def _cluster(observed: list) -> tuple[list[list[int]], list]:
    """Group observations into agreement clusters, with one exemplar each.

    Two numbers agree when :func:`~receipts.validate.rules.within_tolerance`
    says so, which is what stops ``949.20`` and ``949.21`` -- cent-level rounding
    between two runs of the same model -- from reading as uncertainty
    (ISSUE-023). Everything else agrees on exact serialisation, as before.

    First-fit and order-dependent, so it is deterministic for a given run order.
    Tolerance is not transitive, and no clustering over a tolerance can be; this
    picks the reading a majority sits closest to rather than pretending
    otherwise.
    """
    clusters: list[list[int]] = []
    exemplars: list = []
    for index, value in enumerate(observed):
        number = _as_number(value)
        for slot, exemplar in enumerate(exemplars):
            other = _as_number(exemplar)
            if number is not None and other is not None:
                same = within_tolerance(number, other)
            else:
                same = _key(value) == _key(exemplar)
            if same:
                clusters[slot].append(index)
                break
        else:
            clusters.append([index])
            exemplars.append(value)
    return clusters, exemplars


def _key(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _reference_run(runs: list[ReceiptExtraction]) -> int:
    """The run whose rows every other run's rows are aligned against.

    The longest, ties to the earliest. Anchoring on run 0 would silently drop
    every row run 0 happened to miss, and the rows a run misses are exactly what
    a consistency check exists to surface.
    """
    return max(range(len(runs)), key=lambda i: (len(runs[i].line_items), -i))


def _aligned_flat(runs: list[ReceiptExtraction]) -> tuple[list[dict], bool]:
    """Flatten every run with its line items re-keyed to the reference's rows.

    **This is the half that ends the "differing count -> all disputed" cascade.**
    Flattened paths are positional -- ``line_items[0].qty``,
    ``line_items[1].qty`` -- so one inserted or dropped row shifted every later
    index and every later row disagreed. Rows are matched by description through
    :func:`~receipts.extract.lineitem_align.align_line_items` instead, which is
    the consumer P0.T3's acceptance named and never got.

    ``position`` is taken from the reference slot rather than voted on: after
    alignment a row's position IS its slot, so voting on it would manufacture a
    disagreement out of the realignment itself.

    Returns the flattened runs and whether any run held a row that matched no
    reference row -- a reading with nowhere to be voted on, which the caller
    reports rather than discards in silence.
    """
    reference = _reference_run(runs)
    reference_rows = runs[reference].line_items
    flattened: list[dict] = []
    unmatched = False

    for index, run in enumerate(runs):
        flat = flatten(run)
        if index == reference:
            mapping = {row: row for row in range(len(reference_rows))}
        else:
            mapping = {}
            for i, j in align_line_items(reference_rows, run.line_items):
                if i is not None and j is not None:
                    mapping[j] = i
                elif j is not None:
                    unmatched = True

        rekeyed: dict = {}
        for path, value in flat.items():
            match = _LINE_ITEM_PATH.match(path)
            if match is None:
                rekeyed[path] = value
                continue
            row, field_name = int(match.group(1)), match.group(2)
            if row not in mapping:
                continue
            slot = mapping[row]
            rekeyed[f"line_items[{slot}].{field_name}"] = (
                slot if field_name == "position" else value
            )
        flattened.append(rekeyed)

    return flattened, unmatched


def _vote(runs: list[ReceiptExtraction]):
    """Per-path majority vote. No strict majority means the field is nulled and
    marked disputed — silence is the correct output when the readings conflict.

    Two things it does NOT do by serialised string equality, both ISSUE-023:
    money agrees within :func:`within_tolerance`, and line items are matched by
    description rather than by position.
    """
    flattened, unmatched_rows = _aligned_flat(runs)
    all_paths = sorted({p for f in flattened for p in f})

    merged: dict[str, object] = {}
    agreement: dict[str, float] = {}
    disputed: list[str] = []
    values_by_path: dict[str, list] = {}

    for path in all_paths:
        observed = [f.get(path) for f in flattened]
        clusters, exemplars = _cluster(observed)
        best = max(clusters, key=len)
        top_count = len(best)

        ratio = top_count / len(flattened)
        agreement[path] = ratio

        if top_count * 2 > len(flattened):  # strict majority
            merged[path] = observed[best[0]]
        else:
            merged[path] = None
            disputed.append(path)

        if ratio < 1.0:
            # The exemplars, not every raw observation: two readings that agree
            # within tolerance are one reading, and listing both would tell a
            # reviewer the model disagreed with itself when it did not.
            values_by_path[path] = list(exemplars)
            if path not in disputed:
                disputed.append(path)

    if unmatched_rows and "line_items" not in disputed:
        # A row some run read and the reference never saw. It has no slot to be
        # voted in, so it is reported here rather than dropped quietly.
        disputed.append("line_items")

    consensus = ReceiptExtraction.model_validate(unflatten(merged))
    return consensus, agreement, disputed, values_by_path
