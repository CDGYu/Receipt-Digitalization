"""Golden-set evaluation harness (spec §16).

Runs on every prompt, model, or rule change — non-negotiable. It walks the
labelled golden set, scores each receipt against its truth with the pure metrics
in :mod:`eval.metrics`, aggregates the six headline numbers, and writes a
timestamped, prompt-versioned JSON so regressions show up in the diff.

Deliberately offline: the pipeline is injected as ``pipeline_fn`` so this runs
without images or network. Real cost/latency come from the live pipeline and are
left unset here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from receipts.extract.schema import ReceiptExtraction

from .metrics import (
    AUTO_APPROVE_THRESHOLD,
    EvalReport,
    EvalResult,
    FieldBreakdown,
    calibration_curve,
    critical_field_accuracy,
    field_accuracy,
    field_breakdown,
    line_item_f1,
)

#: A pipeline maps a label path to (predicted extraction, confidence).
PipelineFn = Callable[[Path], "tuple[ReceiptExtraction, Decimal]"]

#: Default location for committed eval results (``eval/results/``).
DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _prompt_version() -> str:
    """Current prompt version, or ``"dev"`` if the prompts module is absent."""
    try:
        from receipts.extract.prompts import PROMPT_VERSION

        return PROMPT_VERSION
    except Exception:
        return "dev"


@dataclass
class _Accumulator:
    """Running totals folded over the golden set as it is scored."""

    n_receipts: int = 0
    n_critical_correct: int = 0
    breakdown: FieldBreakdown = FieldBreakdown()
    li_precision: float = 0.0
    li_recall: float = 0.0
    li_f1: float = 0.0
    failures: list[tuple[str, str]] = dc_field(default_factory=list)

    def add(
        self,
        crit: bool,
        bd: FieldBreakdown,
        prf: tuple[float, float, float],
    ) -> None:
        self.n_receipts += 1
        self.n_critical_correct += int(crit)
        self.breakdown = self.breakdown + bd
        p, r, f = prf
        self.li_precision += p
        self.li_recall += r
        self.li_f1 += f

    def add_failure(self, receipt_id: str, detail: str) -> None:
        """Fold in a receipt the pipeline could not process.

        Counted as processed but not correct: it lands in ``n_receipts`` so the
        batch size stays honest, contributes nothing to ``n_critical_correct``,
        and scores zero on line items.
        """
        self.failures.append((receipt_id, detail))
        # The zero breakdown is on purpose: a receipt that produced nothing must
        # not inflate *or* deflate any denominator, only the metrics it
        # genuinely bears on.
        self.add(False, FieldBreakdown(), (0.0, 0.0, 0.0))


def _coerce_confidence(value: Any) -> Decimal:
    """Accept the declared ``Decimal`` but tolerate a stray float/int/str."""
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _build_report(results: list[EvalResult], acc: _Accumulator) -> EvalReport:
    n = acc.n_receipts
    approved = [r for r in results if r.confidence >= AUTO_APPROVE_THRESHOLD]
    n_approved = len(approved)
    n_approved_correct = sum(1 for r in approved if r.critical_correct)

    return EvalReport(
        n_receipts=n,
        n_auto_approved=n_approved,
        n_critical_correct=acc.n_critical_correct,
        auto_approve_threshold=AUTO_APPROVE_THRESHOLD,
        # ``None`` when nothing was approved: undefined, not perfect. The two
        # zero-receipt guards (``calibrate``'s reader-side refusal and
        # ``eval``'s producer-side one) both stand down when receipts *were*
        # read and simply all failed, which is the case this covers.
        auto_approval_precision=(
            (n_approved_correct / n_approved) if n_approved else None
        ),
        auto_approval_rate=(n_approved / n) if n else 0.0,
        critical_field_accuracy=(acc.n_critical_correct / n) if n else 0.0,
        breakdown=acc.breakdown,
        line_item_precision=(acc.li_precision / n) if n else 0.0,
        line_item_recall=(acc.li_recall / n) if n else 0.0,
        line_item_f1=(acc.li_f1 / n) if n else 0.0,
        n_failed=len(acc.failures),
        failures=list(acc.failures),
        calibration=calibration_curve(results),
        results=results,
    )


def _report_to_dict(report: EvalReport) -> dict[str, Any]:
    """Diff-friendly JSON view. Per-receipt class counts plus the full per-path
    map, sorted: §16 commits results so regressions show in a diff, and only the
    map can show *which* field moved.
    """
    return {
        "prompt_version": _prompt_version(),
        "auto_approve_threshold": str(report.auto_approve_threshold),
        "counts": {
            "receipts": report.n_receipts,
            "auto_approved": report.n_auto_approved,
            "critical_correct": report.n_critical_correct,
            "failed": report.n_failed,
        },
        "metrics": {
            "auto_approval_precision": report.auto_approval_precision,
            "auto_approval_rate": report.auto_approval_rate,
            "critical_field_accuracy": report.critical_field_accuracy,
            "transcription_accuracy": report.transcription_accuracy,
            "transcription_accuracy_core": report.transcription_accuracy_core,
            "transcription_accuracy_line_items": (
                report.transcription_accuracy_line_items
            ),
            "self_report_agreement": report.self_report_agreement,
            "hallucinated_fields": report.hallucinated_fields,
            "correctly_empty_fields": report.correctly_empty_fields,
            "structural_mismatch_fields": report.structural_mismatch_fields,
            "line_item_precision": report.line_item_precision,
            "line_item_recall": report.line_item_recall,
            "line_item_f1": report.line_item_f1,
            "cost_per_receipt": (
                str(report.cost_per_receipt)
                if report.cost_per_receipt is not None
                else None
            ),
            "p50_latency_s": report.p50_latency_s,
            "p95_latency_s": report.p95_latency_s,
        },
        # Which rung produced the kept extraction, and why the others lost.
        #
        # **These were deliberately absent until 2026-08-25 (ISSUE-012), and the
        # reason is worth keeping**: ``run_baseline`` folded them in *after*
        # ``run_eval`` returned, and this file is written before it returns, so
        # the keys would have been ``null`` in every file this function ever
        # produced whatever the run measured -- probed 2026-08-21, a run whose
        # report carried ``{'cloud': 1}`` wrote ``null``. A permanently-null key
        # is not a record of provenance.
        #
        # What changed is the ordering, not the key: ``run_eval`` now takes a
        # ``finalize`` hook and calls it *before* writing, so a caller holding
        # provenance this module cannot see folds it in while the report is
        # still unwritten. Spec section 16 commits this file so regressions show
        # in a diff, and ISSUE-001's stated fear is a good accuracy number
        # hiding the fact that everything escalated -- which is precisely what
        # an artefact missing these two keys cannot rule out.
        "extract_rung_counts": report.extract_rung_counts,
        "extract_discard_counts": report.extract_discard_counts,
        # Verbatim error text, not just a count: a run that silently reports
        # "2 failed" is not debuggable four minutes per receipt later.
        "failures": [[receipt_id, detail] for receipt_id, detail in report.failures],
        "calibration": [
            [str(threshold), rate, precision]
            for threshold, rate, precision in report.calibration
        ],
        "results": [
            {
                "receipt_id": r.receipt_id,
                "confidence": str(r.confidence),
                "critical_correct": r.critical_correct,
                "transcription_correct": r.breakdown.transcription_correct,
                "transcription_total": r.breakdown.transcription_total,
                "self_report_correct": r.breakdown.self_report_correct,
                "self_report_total": r.breakdown.self_report_total,
                "hallucinated": r.breakdown.hallucinated,
                "correctly_empty": r.breakdown.correctly_empty,
                "structural_mismatch": r.breakdown.structural_mismatch,
                # The per-path map, sorted. §16 wants results committed so
                # regressions show in a diff; two integers cannot show which
                # field moved, and unsorted keys would make every diff noise.
                "field_results": dict(sorted(r.field_acc.items())),
            }
            for r in report.results
        ],
    }


def _write_report(report: EvalReport, results_dir: Path) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    out_path = results_dir / f"{date.today().isoformat()}-{_prompt_version()}.json"
    out_path.write_text(
        json.dumps(_report_to_dict(report), indent=2), encoding="utf-8"
    )
    return out_path


def run_eval(
    golden_dir: Path,
    pipeline_fn: PipelineFn,
    *,
    results_dir: Path | None = None,
    finalize: Callable[[EvalReport], None] | None = None,
) -> EvalReport:
    """Score every label under ``golden_dir/labels`` and write a results file.

    For each ``*.json`` label: load the truth extraction, run ``pipeline_fn`` on
    the label path to get ``(predicted, confidence)``, compute field accuracy,
    the critical-field gate, and line-item F1, and fold them into an
    :class:`~eval.metrics.EvalReport`. The report is persisted to
    ``results_dir`` (default ``eval/results/``) as
    ``{date}-{prompt_version}.json`` and returned.

    ``pipeline_fn`` is injected, so no images or network are required.

    One receipt never takes the batch down with it. Any exception raised while
    loading a label, running the pipeline, or scoring the result is caught,
    recorded in ``failures``, and the run moves on — a real call can cost
    minutes, so aborting would discard every receipt already paid for and leave
    no results file at all. The failed receipt is still counted in
    ``n_receipts`` with ``critical_correct=False`` and confidence ``0``: it
    reaches a terminal state and can never be scored as auto-approved.
    """
    golden_dir = Path(golden_dir)
    labels_dir = golden_dir / "labels"

    results: list[EvalResult] = []
    acc = _Accumulator()

    for label_path in sorted(labels_dir.glob("*.json")):
        try:
            truth = ReceiptExtraction.model_validate_json(
                label_path.read_text(encoding="utf-8")
            )
            predicted, confidence = pipeline_fn(label_path)

            facc = field_accuracy(predicted, truth)
            bd = field_breakdown(predicted, truth)
            crit = critical_field_accuracy(predicted, truth)
            prf = line_item_f1(predicted.line_items, truth.line_items)
            conf = _coerce_confidence(confidence)
        except Exception as exc:  # noqa: BLE001 - one bad receipt must not abort the run
            acc.add_failure(label_path.stem, f"{type(exc).__name__}: {exc}")
            results.append(
                EvalResult(
                    receipt_id=label_path.stem,
                    # Decimal, not float, and below every threshold: a receipt
                    # the system could not read is not a success.
                    confidence=Decimal("0"),
                    critical_correct=False,
                    # Empty on purpose, and read: this is what reaches the
                    # artifact as ``"field_results": {}`` -- a receipt that
                    # produced nothing scores no path either way.
                    field_acc={},
                )
            )
            continue

        acc.add(crit, bd, prf)
        results.append(
            EvalResult(
                receipt_id=label_path.stem,
                confidence=conf,
                critical_correct=crit,
                field_acc=facc,
                breakdown=bd,
            )
        )

    report = _build_report(results, acc)
    # **Before the write, not after it** -- that ordering is the whole of
    # ISSUE-012. A caller that knows something this module cannot (which rung
    # produced the extraction; only the caller built the ladder) folds it in
    # here, while the report is still unwritten. Folding after `run_eval`
    # returns is what put those counts in the printed report and never in the
    # committed artefact.
    if finalize is not None:
        finalize(report)
    _write_report(report, results_dir if results_dir is not None else DEFAULT_RESULTS_DIR)
    return report
