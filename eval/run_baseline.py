"""One-command baseline runner (spec §15 M1 -> §16).

Composes the pieces that already exist -- environment :class:`Settings`, the VLM
client :func:`make_pass_clients` factory, the M1 :mod:`receipts.pipeline`, and
the eval :mod:`eval.harness` -- into the single call a user makes to get real
baseline metrics over the golden set::

    env Settings -> make_pass_clients -> build_eval_pipeline -> run_eval

**This is the only place the extract ladder is constructed**, which is what
keeps the escalation on the eval path (design §5). Nothing under ``src/``
outside :func:`~receipts.pipeline.run_receipt` can be handed a second rung --
held by ``tests/test_pipeline.py``'s
``test_process_receipt_has_no_ladder_parameter`` and
``test_run_receipt_is_called_only_by_build_eval_pipeline``, one for each of
design §5's two claims.

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
from receipts.extract.clients.factory import PassClients, make_pass_clients
from receipts.pipeline import PassAttempt, build_eval_pipeline
from receipts.validate.context import ValidationContext

from .golden_set import GOLDEN_DIR
from .harness import DEFAULT_RESULTS_DIR, run_eval
from .metrics import EvalReport, FieldBreakdown, ratio, tier_key

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
    default_currency: str | None = None,
    max_attempts: int = 1,
) -> EvalReport:
    """Run the M1 pipeline over the golden set and return the eval report.

    ``golden_dir`` defaults to :data:`eval.golden_set.GOLDEN_DIR`. When
    ``client`` is ``None`` the per-pass clients are built from the environment
    (:func:`~config.settings.get_settings` +
    :func:`~receipts.extract.clients.factory.make_pass_clients`); a ``fake``
    provider is refused with a clear :class:`RuntimeError` because it carries no
    scripted responses. ``ctx`` defaults to a stock :class:`ValidationContext`.

    **An injected ``client`` is one rung and gets no ladder.** That seam is what
    the offline tests and ``scripts`` use, and passing a client is not opting
    into an escalation, so it is wrapped as a single-rung
    :class:`~receipts.extract.clients.factory.PassClients` serving every pass --
    exactly what this function did before the ladder existed. Building the
    ladder on both branches would silently override the caller's client.

    The returned report carries ``extract_rung_counts``: how many receipts each
    extract rung produced the *kept* extraction for. It is folded out of the
    per-run attribution after ``run_eval`` returns, which is the same route
    ``cost_per_receipt`` takes and means it reaches the printed report and the
    return value but not this run's own results JSON (design §6.1).

    ``default_currency`` overrides the configured ``DEFAULT_CURRENCY``; left
    ``None`` it is read from :class:`~config.settings.Settings`. Settings are
    read on both paths, including when a ``client`` is injected -- they carry
    defaults for every field, so this needs no provider and the offline path
    stays offline. Passing the configured default through is what stops a corpus
    that never prints an ISO code (PH BIR invoices) from scoring a currency miss
    on every receipt.

    The report is written under ``results_dir`` (the harness default
    ``eval/results/`` when ``None``) and returned.
    """
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be at least 1, got {max_attempts}")

    golden_dir = Path(golden_dir) if golden_dir is not None else GOLDEN_DIR
    settings = get_settings()

    if client is None:
        if settings.vlm_provider.strip().lower() == "fake":
            raise RuntimeError(_FAKE_PROVIDER_HINT)
        tiers = make_pass_clients(settings)
    else:
        # An injected client is one rung, used for every pass -- exactly what
        # this function did before the ladder existed. Passing a client is not
        # opting into an escalation, and building the ladder here regardless
        # would override the client the caller handed in.
        tiers = PassClients(triage=client, extract_rungs=(client,))

    if ctx is None:
        ctx = ValidationContext()

    if default_currency is None:
        default_currency = settings.default_currency

    attribution: list[PassAttempt] = []
    pipeline_fn = build_eval_pipeline(
        tiers.extract_rungs[0],
        ctx,
        golden_dir / "images",
        default_currency=default_currency,
        triage_client=tiers.triage,
        extract_fallback_client=(
            tiers.extract_rungs[1] if len(tiers.extract_rungs) > 1 else None
        ),
        attribution_sink=attribution,
        max_attempts=max_attempts,
    )
    def _fold_rung_provenance(report: EvalReport) -> None:
        """Attach which rung produced what, **before the report is written**.

        Passed to `run_eval` as `finalize` rather than applied to its return
        value, and that is the whole of ISSUE-012: `run_eval` writes the
        committed results file and then returns, so anything folded in
        afterwards reached the printed report and the caller's copy and never
        the artefact. Probed 2026-08-21 -- a run whose report carried
        `{'cloud': 1}` wrote `null`.

        Closes over `attribution`, which `build_eval_pipeline` fills *during*
        `run_eval`; by the time this runs it holds the whole run.
        """
        # Only the extract rung whose extraction was *kept* is counted. The
        # triage pass is a different question, and a rung that ran and was
        # discarded did not produce the extraction this report scored --
        # counting either would turn the answer to "did everything escalate?"
        # into a call tally.
        counts: dict[str, int] = {}
        # ...and the discarded ones, by the clause that discarded them. Without
        # this the ladder's own record answers "which rung won" and not "why
        # the others lost", which is the question a ladder run is asked
        # (ISSUE-018).
        discards: dict[str, dict[str, int]] = {}
        rungs = tiers.extract_rungs
        for entry in attribution:
            if entry.pass_name != "extract":
                continue
            # **`entry.rung` is the reader ISSUE-015 asked for, and it is load
            # bearing rather than decorative.** `entry.model_id` cannot
            # identify the tier when two rungs share a model and differ only in
            # their tools answer -- the ladder ISSUE-013 measured. `rung` is
            # the index into `extract_rungs`, so it is the only thing that
            # resolves which of them ran. Guarded because an out-of-range index
            # would key every count to one rung silently, which is the failure
            # this replaces.
            if not 0 <= entry.rung < len(rungs):
                raise RuntimeError(
                    f"attribution names extract rung {entry.rung}, and this run "
                    f"built {len(rungs)}. The ladder and its record disagree, "
                    f"so no count keyed from it would mean anything."
                )
            key = tier_key(rungs[entry.rung])
            if entry.kept:
                counts[key] = counts.get(key, 0) + 1
            else:
                by_reason = discards.setdefault(key, {})
                reason = entry.discarded.value
                by_reason[reason] = by_reason.get(reason, 0) + 1
        # ``None``, not ``{}``: an empty dict would read as "measured, and no
        # rung ran". Only a run that scored no receipt at all leaves this empty.
        report.extract_rung_counts = counts or None
        report.extract_discard_counts = discards or None

    return run_eval(
        golden_dir,
        pipeline_fn,
        results_dir=results_dir,
        finalize=_fold_rung_provenance,
    )


def _pct(value: float | None) -> str:
    """A percentage, or ``n/a`` when the ratio is undefined.

    ``None`` renders as ``n/a``, never ``0.00%``: a ratio over no paths is
    undefined, not bad. Same rule the auto-approval line already follows.
    """
    return f"{value * 100:6.2f}%" if value is not None else f"{'n/a':>7}"


def format_breakdown(bd: FieldBreakdown) -> str:
    """Spec §16 metric 4, as the block it needs to be.

    One renderer, two callers — this module's batch table and
    ``scripts/try_one_receipt.py``. The script used to compute its own
    ``correct/len(acc)`` scalar, which meant "what counts as correct" had two
    definitions in a codebase whose ``cmd_eval`` docstring says it has one.
    """
    return "\n".join([
        f"  Transcription accuracy:   "
        f"{_pct(ratio(bd.transcription_correct, bd.transcription_total))}"
        f"   ({bd.transcription_correct}/{bd.transcription_total})",
        f"    core:                   "
        f"{_pct(ratio(bd.core_correct, bd.core_total))}"
        f"   ({bd.core_correct}/{bd.core_total})",
        f"    line items:             "
        f"{_pct(ratio(bd.line_items_correct, bd.line_items_total))}"
        f"   ({bd.line_items_correct}/{bd.line_items_total})",
        f"  Self-report agreement:    "
        f"{_pct(ratio(bd.self_report_correct, bd.self_report_total))}"
        f"   ({bd.self_report_correct}/{bd.self_report_total})",
        f"  Hallucinated fields:      {bd.hallucinated:>12d}",
        f"  Correctly empty fields:   {bd.correctly_empty:>12d}",
        f"  Structural mismatches:    {bd.structural_mismatch:>12d}",
    ])


def format_report(report: EvalReport) -> str:
    """Render the six §16 metrics as a compact, printable text table.

    Counts up top, then the rate/accuracy metrics as percentages, then the
    cost/latency line. Cost and latency are not observable through the injected
    ``pipeline_fn`` (the offline harness leaves them ``None``), so they render
    as ``n/a`` rather than a misleading zero.

    **Auto-approval precision renders as ``n/a`` when nothing was
    auto-approved.** ``_build_report`` resolves it to ``None`` in that case
    (P8.T3), and this is the line an operator reads off the terminal as the
    system's headline metric. A run that approved nothing (including a run
    that scored no receipts at all) printed ``Auto-approval precision:
    100.00%``, which is the exact artifact this project has committed once and
    banned; no caller of this function can print it now.

    The failed count always shows, and each failure is listed with its error
    text when there is one — a partially failed run must be obvious on screen,
    not something you find later by reading the JSON.

    **The per-rung counts print inside the accuracy block, not under it.** That
    placement is the requirement rather than a nicety (design §6.2): ISSUE-001's
    stated fear is a good accuracy figure hiding the fact that every receipt
    escalated, and a number in a trailing section does not answer it. Counts,
    not a derived escalation rate — a percentage needs a denominator that can go
    stale while the counts cannot. Nothing prints when they are ``None``, which
    is every offline run: an injected ``pipeline_fn`` cannot see a rung.
    """

    precision = (
        _pct(report.auto_approval_precision)
        if report.n_auto_approved
        else f"{'n/a':>7}"
    )
    cost = (
        f"${report.cost_per_receipt}"
        if report.cost_per_receipt is not None
        else "n/a"
    )
    def _interval(bounds: tuple[float, float] | None) -> str:
        """The 95% interval beside a rate, or nothing when it is undefined.

        **A rate without a sample size cannot support the spec's criterion.**
        Section 70 asks for >= 99% precision on auto-approved receipts; that is
        a claim about evidence, and "100.00%" over three receipts and over three
        hundred render identically without this. Measured at perfect precision:
        3-of-3 is roughly [44%, 100%], and the lower bound does not clear 99%
        until about a thousand.

        Empty string rather than `n/a` when undefined: the rate beside it
        already renders `n/a`, and a second one would say the same thing twice.
        """
        if bounds is None:
            return ""
        low, high = bounds
        return f"   95% CI [{low * 100:.1f}%, {high * 100:.1f}%]"

    p50 = f"{report.p50_latency_s:.2f}s" if report.p50_latency_s is not None else "n/a"
    p95 = f"{report.p95_latency_s:.2f}s" if report.p95_latency_s is not None else "n/a"

    # Spliced into the accuracy block below rather than appended after it: the
    # placement is the requirement (design §6.2). Nothing at all when the counts
    # are `None` -- a bare heading with no rows under it would read as a
    # measurement that came back empty, which is the opposite of "not measured".
    rung_lines: list[str] = []
    if report.extract_rung_counts:
        rung_lines.append("  Extraction by rung:")
        rung_lines.extend(
            # Keyed by tier, not by model: the ` +tools`/` -tools` suffix is
            # what tells two rungs of one model apart (ISSUE-013). Widened
            # from 32 to fit it without pushing the count out of column.
            f"    {tier:40s} {count}"
            for tier, count in sorted(report.extract_rung_counts.items())
        )

    rule = "-" * 46
    lines = [
        "Baseline eval report (spec §16)",
        "=" * 46,
        f"  Receipts:                 {report.n_receipts:>12d}",
        f"  Auto-approved:            {report.n_auto_approved:>12d}",
        f"  Critical-correct:         {report.n_critical_correct:>12d}",
        f"  Failed:                   {report.n_failed:>12d}",
        f"  Auto-approve threshold:   {str(report.auto_approve_threshold):>12}",
        rule,
        f"  Auto-approval precision:  {precision}"
        f"{_interval(report.auto_approval_precision_interval)}",
        f"  Auto-approval rate:       {_pct(report.auto_approval_rate)}",
        f"  Critical-field accuracy:  {_pct(report.critical_field_accuracy)}"
        f"{_interval(report.critical_field_accuracy_interval)}",
        format_breakdown(report.breakdown),
        f"  Line-item precision:      {_pct(report.line_item_precision)}",
        f"  Line-item recall:         {_pct(report.line_item_recall)}",
        f"  Line-item F1:             {_pct(report.line_item_f1)}",
        *rung_lines,
        rule,
        f"  Cost per receipt:         {cost:>12}",
        f"  p50 latency:              {p50:>12}",
        f"  p95 latency:              {p95:>12}",
    ]

    # Name the receipts that failed and why. The count alone is not actionable
    # when a single call costs minutes; the error text is what tells you whether
    # to raise VLM_TIMEOUT_S or fix a label.
    if report.failures:
        lines.append(rule)
        lines.append("  Failures:")
        lines.extend(
            f"    {receipt_id}: {detail}" for receipt_id, detail in report.failures
        )

    return "\n".join(lines)


def latest_results_file(results_dir: Path) -> Path | None:
    """Most recently written results JSON in ``results_dir`` (or ``None``).

    The harness names the file
    ``{date}-{prompt_version}-{prompt_bundle_hash}.json`` and does not return
    its path; picking the newest file back out avoids duplicating (and drifting
    from) that private naming logic -- which is why the third component could be
    added for ISSUE-007 without touching this function at all.

    Not private: this module's own ``main`` uses it to report where a run's
    results landed, and ``receipts calibrate`` (``receipts.cli.cmd_calibrate``)
    uses it to find the newest file when the operator does not name one
    explicitly with ``--results``.
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

    written = latest_results_file(DEFAULT_RESULTS_DIR)
    print(f"\nResults written to: {written if written is not None else DEFAULT_RESULTS_DIR}")


if __name__ == "__main__":
    main()
