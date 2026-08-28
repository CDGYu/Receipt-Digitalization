"""The repairs-off versus repairs-on golden-set comparison."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.run_repair_comparison import compare_aggregates, main, run_repair_comparison


def _aggregate(
    values: list[float | int | None | str],
    *,
    max_attempts: int,
    receipts: list[str],
    complete: bool = True,
    config: dict | None = None,
    distribution: dict | None = None,
) -> dict:
    """A minimal aggregate with one fully specified accuracy distribution."""
    n_repeats = len(values)
    return {
        "run_id": "synthetic",
        "n_repeats": n_repeats if complete else max(0, n_repeats - 1),
        "n_repeats_requested": n_repeats,
        "config": {
            "prompt_version": "test-v1",
            "default_currency": "XTS",
            "max_attempts": max_attempts,
            **(config or {}),
        },
        "spread": {
            "transcription_accuracy": distribution
            if distribution is not None
            else {"values": values, "n": len(values), "n_null": 0},
        },
        "scored_receipts": receipts,
    }


def test_comparison_reports_improvement_only_when_distributions_do_not_overlap():
    baseline = _aggregate([0.40, 0.45], max_attempts=1, receipts=["r1", "r2"])
    repair = _aggregate([0.60, 0.65], max_attempts=2, receipts=["r1", "r2"])

    comparison = compare_aggregates(baseline, repair)

    assert comparison["comparable"] is True
    assert comparison["improved"] is True
    assert comparison["criterion"] == "min(repair) > max(baseline)"


def test_comparison_records_a_successful_non_improvement_for_overlapping_distributions():
    baseline = _aggregate([0.40, 0.65], max_attempts=1, receipts=["r1", "r2"])
    repair = _aggregate([0.60, 0.70], max_attempts=2, receipts=["r1", "r2"])

    assert compare_aggregates(baseline, repair)["improved"] is False


def test_comparison_refuses_different_receipt_sets():
    baseline = _aggregate([0.40], max_attempts=1, receipts=["r1"])
    repair = _aggregate([0.60], max_attempts=2, receipts=["r2"])

    with pytest.raises(ValueError, match="scored_receipts"):
        compare_aggregates(baseline, repair)


@pytest.mark.parametrize("which", ["baseline", "repair"])
def test_comparison_refuses_incomplete_groups(which):
    baseline = _aggregate([0.40], max_attempts=1, receipts=["r1"])
    repair = _aggregate([0.60], max_attempts=2, receipts=["r1"])
    (baseline if which == "baseline" else repair)["n_repeats"] = 0

    with pytest.raises(ValueError, match=f"{which} run is incomplete"):
        compare_aggregates(baseline, repair)


@pytest.mark.parametrize(
    ("baseline_attempts", "repair_attempts"),
    [(2, 2), (1, 1)],
)
def test_comparison_refuses_wrong_attempt_budgets(baseline_attempts, repair_attempts):
    baseline = _aggregate(
        [0.40], max_attempts=baseline_attempts, receipts=["r1"]
    )
    repair = _aggregate([0.60], max_attempts=repair_attempts, receipts=["r1"])

    with pytest.raises(ValueError, match="baseline=1 and repair>=2"):
        compare_aggregates(baseline, repair)


def test_comparison_refuses_configuration_changes_other_than_attempt_budget():
    baseline = _aggregate([0.40], max_attempts=1, receipts=["r1"])
    repair = _aggregate(
        [0.60],
        max_attempts=2,
        receipts=["r1"],
        config={"prompt_version": "test-v2"},
    )

    with pytest.raises(ValueError, match="configuration differ"):
        compare_aggregates(baseline, repair)


@pytest.mark.parametrize(
    "distribution",
    [
        {"values": [0.60, None], "n": 1, "n_null": 1},
        {"values": [0.60, "unknown"], "n": 1, "n_null": 0},
        {"values": [0.60], "n": 0, "n_null": 0},
        {"values": [True], "n": 1, "n_null": 0},
        {"values": [float("nan")], "n": 1, "n_null": 0},
    ],
)
@pytest.mark.parametrize("condition", ["baseline", "repair"])
def test_comparison_refuses_an_incomplete_or_non_numeric_accuracy_distribution(
    distribution, condition
):
    baseline = _aggregate([0.40], max_attempts=1, receipts=["r1"])
    repair = _aggregate([0.60], max_attempts=2, receipts=["r1"])
    (baseline if condition == "baseline" else repair)["spread"][
        "transcription_accuracy"
    ] = distribution

    with pytest.raises(ValueError, match="transcription_accuracy is not fully observed"):
        compare_aggregates(baseline, repair)


def test_run_repair_comparison_runs_both_budgets_and_writes_its_artifact(
    tmp_path, monkeypatch
):
    calls = []
    baseline = _aggregate([0.40, 0.45], max_attempts=1, receipts=["r1", "r2"])
    repair = _aggregate([0.60, 0.65], max_attempts=3, receipts=["r1", "r2"])

    def fake_run_repeats(run_id, repeats, **kwargs):
        calls.append((run_id, repeats, kwargs))
        return baseline if run_id.endswith("-baseline") else repair

    monkeypatch.setattr("eval.run_repair_comparison.run_repeats", fake_run_repeats)

    comparison = run_repair_comparison(
        "impact", 2, repair_attempts=3, results_root=tmp_path / "results"
    )

    assert [call[:2] for call in calls] == [
        ("impact-baseline", 2),
        ("impact-repair", 2),
    ]
    assert [call[2]["max_attempts"] for call in calls] == [1, 3]
    assert comparison["improved"] is True
    artifact = tmp_path / "results" / "impact-comparison.json"
    assert json.loads(artifact.read_text(encoding="utf-8")) == comparison
    assert comparison["baseline_run_id"] == "impact-baseline"
    assert comparison["repair_run_id"] == "impact-repair"


def test_run_repair_comparison_writes_a_non_improvement_artifact(tmp_path, monkeypatch):
    baseline = _aggregate([0.40, 0.65], max_attempts=1, receipts=["r1", "r2"])
    repair = _aggregate([0.60, 0.70], max_attempts=2, receipts=["r1", "r2"])

    monkeypatch.setattr(
        "eval.run_repair_comparison.run_repeats",
        lambda run_id, repeats, **kwargs: (
            baseline if run_id.endswith("-baseline") else repair
        ),
    )

    comparison = run_repair_comparison(
        "overlap", 2, results_root=tmp_path / "results"
    )

    assert comparison["improved"] is False
    assert json.loads(
        (tmp_path / "results" / "overlap-comparison.json").read_text(
            encoding="utf-8"
        )
    )["improved"] is False


def test_run_repair_comparison_refuses_an_invalid_budget_before_starting_a_run(
    tmp_path, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        "eval.run_repair_comparison.run_repeats",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with pytest.raises(ValueError, match="repair_attempts must be at least 2"):
        run_repair_comparison(
            "invalid", 1, repair_attempts=1, results_root=tmp_path / "results"
        )

    assert calls == []
    assert not (tmp_path / "results").exists()


def test_main_forwards_the_cli_options_and_reports_a_written_artifact(
    monkeypatch, capsys
):
    calls = []

    def fake_run_repair_comparison(run_id, repeats, **kwargs):
        calls.append((run_id, repeats, kwargs))
        return {"improved": True}

    monkeypatch.setattr(
        "eval.run_repair_comparison.run_repair_comparison",
        fake_run_repair_comparison,
    )

    code = main([
        "--run-id", "impact",
        "--repeats", "3",
        "--repair-attempts", "4",
        "--golden-dir", "golden-fixture",
        "--results-root", "results-fixture",
    ])

    assert code == 0
    assert calls == [
        (
            "impact",
            3,
            {
                "repair_attempts": 4,
                "golden_dir": Path("golden-fixture"),
                "results_root": Path("results-fixture"),
            },
        )
    ]
    assert capsys.readouterr().out == (
        "Wrote results-fixture\\impact-comparison.json\nImproved: True\n"
    )


def test_main_reports_a_comparison_failure_without_a_traceback(monkeypatch, capsys):
    def fake_run_repair_comparison(*args, **kwargs):
        raise ValueError("baseline and repair scored_receipts differ")

    monkeypatch.setattr(
        "eval.run_repair_comparison.run_repair_comparison",
        fake_run_repair_comparison,
    )

    code = main(["--run-id", "impact", "--repeats", "1"])

    assert code == 1
    captured = capsys.readouterr()
    assert "Cannot run repair comparison" in captured.err
    assert "scored_receipts differ" in captured.err
    assert "Traceback" not in captured.err
