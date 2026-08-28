"""Compare repairs-off and repairs-on golden-set accuracy distributions.

Run the same golden set repeatedly with repair disabled and enabled, then make
one deliberately strict claim: the repair condition improved only when its
lowest transcription accuracy is above the baseline condition's highest.

    python -m eval.run_repair_comparison --run-id repair-impact --repeats 5 \
        --repair-attempts 2
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from eval.harness import DEFAULT_RESULTS_DIR
from eval.run_repeats import run_repeats

__all__ = ["compare_aggregates", "main", "run_repair_comparison"]


def _is_numeric(value: Any) -> bool:
    """Return whether ``value`` is a finite numeric measurement, not a flag."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _is_integer(value: Any) -> bool:
    """Return whether ``value`` is an integer count, not a Boolean flag."""
    return isinstance(value, int) and not isinstance(value, bool)


def _require_complete(aggregate: dict[str, Any], condition: str) -> int:
    """Return the completed repeat count or reject an incomplete aggregate."""
    try:
        completed = aggregate["n_repeats"]
        requested = aggregate["n_repeats_requested"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"{condition} run is incomplete") from exc

    if (
        not _is_integer(completed)
        or not _is_integer(requested)
        or completed < 0
        or requested < 0
        or completed != requested
    ):
        raise ValueError(f"{condition} run is incomplete")
    return completed


def _config_without_attempt_budget(
    aggregate: dict[str, Any], condition: str
) -> tuple[dict[str, Any], int]:
    """Separate and validate the sole configuration difference we permit."""
    try:
        config = dict(aggregate["config"])
        max_attempts = config.pop("max_attempts")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "comparison requires baseline=1 and repair>=2 attempts"
        ) from exc

    if not _is_integer(max_attempts):
        raise ValueError("comparison requires baseline=1 and repair>=2 attempts")
    return config, max_attempts


def _fully_observed_transcription_values(
    aggregate: dict[str, Any], n_repeats: int
) -> list[float | int]:
    """Read a distribution only when it contains one numeric value per repeat."""
    try:
        distribution = aggregate["spread"]["transcription_accuracy"]
        values = distribution["values"]
        observed = distribution["n"]
        nulls = distribution["n_null"]
    except (KeyError, TypeError) as exc:
        raise ValueError("transcription_accuracy is not fully observed") from exc

    if (
        not isinstance(values, list)
        or not _is_integer(observed)
        or not _is_integer(nulls)
        or observed != len(values)
        or observed != n_repeats
        or nulls != 0
        or not all(_is_numeric(value) for value in values)
    ):
        raise ValueError("transcription_accuracy is not fully observed")
    return values


def _strictly_improves(
    baseline: list[float | int], repair: list[float | int]
) -> bool:
    """Whether every repair observation exceeds every baseline observation."""
    return bool(baseline and repair and min(repair) > max(baseline))


def compare_aggregates(
    baseline: dict[str, Any], repair: dict[str, Any]
) -> dict[str, Any]:
    """Compare two repeat aggregates under an auditable closed contract.

    A comparison is valid only for completed runs over the exact same receipts,
    with the same configuration except that the baseline used one extraction
    attempt and the repair condition used at least two. The full distributions
    are retained so a false verdict remains a useful measurement artifact.
    """
    baseline_repeats = _require_complete(baseline, "baseline")
    repair_repeats = _require_complete(repair, "repair")

    try:
        baseline_receipts = baseline["scored_receipts"]
        repair_receipts = repair["scored_receipts"]
    except (KeyError, TypeError) as exc:
        raise ValueError("baseline and repair scored_receipts differ") from exc
    if baseline_receipts != repair_receipts:
        raise ValueError("baseline and repair scored_receipts differ")

    baseline_config, baseline_attempts = _config_without_attempt_budget(
        baseline, "baseline"
    )
    repair_config, repair_attempts = _config_without_attempt_budget(repair, "repair")
    if baseline_attempts != 1 or repair_attempts < 2:
        raise ValueError("comparison requires baseline=1 and repair>=2 attempts")
    if baseline_config != repair_config:
        raise ValueError("baseline and repair configuration differ")

    baseline_values = _fully_observed_transcription_values(baseline, baseline_repeats)
    repair_values = _fully_observed_transcription_values(repair, repair_repeats)
    return {
        "comparable": True,
        "metric": "transcription_accuracy",
        "criterion": "min(repair) > max(baseline)",
        "baseline_values": baseline_values,
        "repair_values": repair_values,
        "improved": _strictly_improves(baseline_values, repair_values),
        "scored_receipts": baseline_receipts,
    }


def run_repair_comparison(
    run_id: str,
    repeats: int,
    *,
    repair_attempts: int = 2,
    golden_dir: Path | None = None,
    results_root: Path | None = None,
) -> dict[str, Any]:
    """Run the baseline and repair conditions, then persist their comparison.

    ``repair_attempts`` is checked before either repeated run starts. That
    means a bad budget cannot claim a baseline run ID or create any directory.
    A non-improvement is intentionally not an error: it is the result this
    measurement exists to distinguish from an observed improvement.
    """
    if not _is_integer(repair_attempts) or repair_attempts < 2:
        raise ValueError(
            f"repair_attempts must be at least 2, got {repair_attempts}"
        )

    baseline_run_id = f"{run_id}-baseline"
    repair_run_id = f"{run_id}-repair"
    baseline = run_repeats(
        baseline_run_id,
        repeats,
        golden_dir=golden_dir,
        results_root=results_root,
        max_attempts=1,
    )
    repair = run_repeats(
        repair_run_id,
        repeats,
        golden_dir=golden_dir,
        results_root=results_root,
        max_attempts=repair_attempts,
    )
    comparison = {
        "run_id": run_id,
        "baseline_run_id": baseline_run_id,
        "repair_run_id": repair_run_id,
        **compare_aggregates(baseline, repair),
    }

    root = Path(results_root) if results_root is not None else DEFAULT_RESULTS_DIR
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{run_id}-comparison.json"
    target.write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    return comparison


def main(argv: list[str] | None = None) -> int:
    """Run the comparison CLI and report ordinary failures without a traceback."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--repeats", type=int, required=True)
    parser.add_argument(
        "--repair-attempts",
        type=int,
        default=2,
        help="total extraction attempts for the repair condition; minimum 2",
    )
    parser.add_argument("--golden-dir", type=Path, default=None)
    parser.add_argument("--results-root", type=Path, default=None)
    args = parser.parse_args(argv)

    root = args.results_root if args.results_root is not None else DEFAULT_RESULTS_DIR
    target = Path(root) / f"{args.run_id}-comparison.json"
    try:
        comparison = run_repair_comparison(
            args.run_id,
            args.repeats,
            repair_attempts=args.repair_attempts,
            golden_dir=args.golden_dir,
            results_root=args.results_root,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Cannot run repair comparison: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {target}")
    print(f"Improved: {comparison['improved']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
