"""One-command baseline runner (spec §15 M1 -> §16).

Composes the pieces that already exist -- environment :class:`Settings`, the VLM
client :func:`make_client` factory, the M1 :mod:`receipts.pipeline`, and the
eval :mod:`eval.harness` -- into the single call a user makes to get real
baseline metrics over the golden set::

    env Settings -> make_client -> build_eval_pipeline -> run_eval

This module owns no prompt text, no rules, and no provider details; it only
*wires*. ``client`` and ``ctx`` are injectable, which is the same seam the
pipeline and harness already use to stay offline-testable with a scripted
``FakeVLMClient``.

One guard rail is worth stating out loud: the *default* ``fake`` provider is
built with no scripted responses (``make_client`` returns ``FakeVLMClient([])``)
and so cannot drive a real extraction. Rather than let that fail deep inside the
pipeline with an opaque "exhausted" error, :func:`run_baseline` refuses early
with a message naming the environment variables to set.

Run it once a provider is configured and the golden set is labelled::

    python -m eval.run_baseline
"""

from __future__ import annotations

import sys
from pathlib import Path

from config.settings import get_settings
from receipts.extract.clients.base import VLMClient
from receipts.extract.clients.factory import make_client
from receipts.pipeline import build_eval_pipeline
from receipts.validate.context import ValidationContext

from .golden_set import GOLDEN_DIR
from .harness import DEFAULT_RESULTS_DIR, run_eval
from .metrics import EvalReport

#: Shown when the resolved provider is ``fake`` on the ``client=None`` path.
_FAKE_PROVIDER_HINT = (
    "VLM_PROVIDER is 'fake' (the default), which is built with no scripted "
    "responses and cannot run a real extraction. Configure a real provider "
    "before running the baseline:\n"
    "  VLM_PROVIDER=anthropic   (or openai, vllm, ollama, ...)\n"
    "  VLM_API_KEY=<your key>\n"
    "  VLM_MODEL_EXTRACT=<model id>\n"
    "Or pass an explicit client (e.g. a scripted FakeVLMClient) to run offline."
)


def run_baseline(
    golden_dir: Path | None = None,
    *,
    client: VLMClient | None = None,
    ctx: ValidationContext | None = None,
    results_dir: Path | None = None,
) -> EvalReport:
    """Run the M1 pipeline over the golden set and return the eval report.

    ``golden_dir`` defaults to :data:`eval.golden_set.GOLDEN_DIR`. When
    ``client`` is ``None`` the client is built from the environment
    (:func:`~config.settings.get_settings` +
    :func:`~receipts.extract.clients.factory.make_client`); a ``fake`` provider
    is refused with a clear :class:`RuntimeError` because it carries no scripted
    responses. ``ctx`` defaults to a stock :class:`ValidationContext`.

    The report is written under ``results_dir`` (the harness default
    ``eval/results/`` when ``None``) and returned.
    """
    golden_dir = Path(golden_dir) if golden_dir is not None else GOLDEN_DIR

    if client is None:
        settings = get_settings()
        if settings.vlm_provider.strip().lower() == "fake":
            raise RuntimeError(_FAKE_PROVIDER_HINT)
        client = make_client(settings)

    if ctx is None:
        ctx = ValidationContext()

    pipeline_fn = build_eval_pipeline(client, ctx, golden_dir / "images")
    return run_eval(golden_dir, pipeline_fn, results_dir=results_dir)


def format_report(report: EvalReport) -> str:
    """Render the six §16 metrics as a compact, printable text table.

    Counts up top, then the rate/accuracy metrics as percentages, then the
    cost/latency line. Cost and latency are not observable through the injected
    ``pipeline_fn`` (the offline harness leaves them ``None``), so they render
    as ``n/a`` rather than a misleading zero.
    """

    def pct(value: float) -> str:
        return f"{value * 100:6.2f}%"

    cost = (
        f"${report.cost_per_receipt}"
        if report.cost_per_receipt is not None
        else "n/a"
    )
    p50 = f"{report.p50_latency_s:.2f}s" if report.p50_latency_s is not None else "n/a"
    p95 = f"{report.p95_latency_s:.2f}s" if report.p95_latency_s is not None else "n/a"

    rule = "-" * 46
    lines = [
        "Baseline eval report (spec §16)",
        "=" * 46,
        f"  Receipts:                 {report.n_receipts:>12d}",
        f"  Auto-approved:            {report.n_auto_approved:>12d}",
        f"  Critical-correct:         {report.n_critical_correct:>12d}",
        f"  Auto-approve threshold:   {str(report.auto_approve_threshold):>12}",
        rule,
        f"  Auto-approval precision:  {pct(report.auto_approval_precision)}",
        f"  Auto-approval rate:       {pct(report.auto_approval_rate)}",
        f"  Critical-field accuracy:  {pct(report.critical_field_accuracy)}",
        f"  Field accuracy:           {pct(report.field_accuracy)}",
        f"  Line-item precision:      {pct(report.line_item_precision)}",
        f"  Line-item recall:         {pct(report.line_item_recall)}",
        f"  Line-item F1:             {pct(report.line_item_f1)}",
        rule,
        f"  Cost per receipt:         {cost:>12}",
        f"  p50 latency:              {p50:>12}",
        f"  p95 latency:              {p95:>12}",
    ]
    return "\n".join(lines)


def _latest_results_file(results_dir: Path) -> Path | None:
    """Most recently written results JSON in ``results_dir`` (or ``None``).

    The harness names the file ``{date}-{prompt_version}.json`` and does not
    return its path; picking the newest file back out avoids duplicating (and
    drifting from) that private naming logic.
    """
    files = sorted(
        results_dir.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return files[0] if files else None


def main() -> None:
    """CLI entry point: run the baseline, print the report and results path.

    A ``fake`` provider raises before any work happens; that becomes a friendly
    setup hint on stderr and a non-zero exit rather than a traceback.
    """
    try:
        report = run_baseline()
    except RuntimeError as exc:
        print(f"Cannot run baseline: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(format_report(report))

    written = _latest_results_file(DEFAULT_RESULTS_DIR)
    print(f"\nResults written to: {written if written is not None else DEFAULT_RESULTS_DIR}")


if __name__ == "__main__":
    main()
