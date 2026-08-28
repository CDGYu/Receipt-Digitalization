# Repair-Loop Impact Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Measure golden-set transcription accuracy with repairs disabled and enabled, then report a strict observed improvement only when the repaired condition exceeds the baseline over the identical receipt IDs.

**Architecture:** Keep the current one-extraction eval as the default, but make its attempt budget explicit from the eval adapter through the baseline and repeated-run runners. A new comparison runner runs both conditions, rejects incomparable artifacts, and persists the distributions plus an unambiguous verdict.

**Tech Stack:** Python 3.11, pytest, existing eval harness, FakeVLMClient for offline tests, Ollama for the final golden-image run.

---

## File structure

- Modify: src/receipts/pipeline.py:434-493 — add and forward max_attempts in build_eval_pipeline.
- Modify: eval/run_baseline.py:61-193 — expose the same argument.
- Modify: eval/run_repeats.py:117-434 — pass it through and include it in aggregate config.
- Create: eval/run_repair_comparison.py — execute both groups, validate comparability, and write a comparison artifact.
- Test: tests/test_pipeline.py, tests/test_run_baseline.py, tests/test_run_repeats.py, tests/test_run_repair_comparison.py.
- Modify: eval/golden/RUN_SHEET.md — publish the exact measurement command.
- Modify: IMPLEMENTATION_PLAN.md:768-770 only after a real artifact meets the criterion.

### Task 1: Thread the existing repair budget through eval

**Files:**

- Modify: src/receipts/pipeline.py:434-493
- Modify: eval/run_baseline.py:61-193
- Test: tests/test_pipeline.py
- Test: tests/test_run_baseline.py

- [ ] **Step 1: Write the failing adapter test**

Add this beside the existing build_eval_pipeline tests. The first extraction has R022's mismatched total; the repair matches the golden label.

~~~python
def test_build_eval_pipeline_spends_the_requested_repair_attempt(tmp_path):
    golden = tmp_path / "golden"
    labels, images = golden / "labels", golden / "images"
    labels.mkdir(parents=True)
    images.mkdir(parents=True)
    (labels / "r1.json").write_text(_good().model_dump_json(), encoding="utf-8")
    _write_png(images / "r1.png")

    broken = _good()
    broken.totals.total = D("200.00")
    client = FakeVLMClient([_triage(), broken, _good()])
    pipeline_fn = build_eval_pipeline(client, CTX, images, max_attempts=2)

    report = run_eval(golden, pipeline_fn, results_dir=tmp_path / "results")

    assert len(client.calls) == 3
    assert report.critical_field_accuracy == 1.0
~~~

- [ ] **Step 2: Verify it fails**

Run: python -m pytest tests/test_pipeline.py::test_build_eval_pipeline_spends_the_requested_repair_attempt -q

Expected: FAIL because build_eval_pipeline has no max_attempts argument.

- [ ] **Step 3: Implement the adapter forwarding**

Add the defaulted argument to the adapter's keyword-only parameters, then forward it to the existing run_receipt parameter. A default of 1 deliberately preserves historic eval behavior.

~~~python
def build_eval_pipeline(
    client: VLMClient,
    ctx: ValidationContext,
    images_dir: Path,
    *,
    image_suffixes: tuple[str, ...] = DEFAULT_IMAGE_SUFFIXES,
    default_currency: str | None = None,
    triage_client: VLMClient | None = None,
    extract_fallback_client: VLMClient | None = None,
    attribution_sink: list[PassAttempt] | None = None,
    max_attempts: int = 1,
) -> Callable[[Path], tuple[ReceiptExtraction, Decimal]]:
~~~

~~~python
        run = run_receipt(
            image_path,
            client,
            ctx,
            max_attempts=max_attempts,
            default_currency=default_currency,
            triage_client=triage_client,
            extract_fallback_client=extract_fallback_client,
        )
~~~

- [ ] **Step 4: Write the failing baseline-runner test**

In tests/test_run_baseline.py, add _broken() by copying _good() and setting totals.total = D("200.00"), then add:

~~~python
def test_run_baseline_forwards_an_explicit_repair_budget(tmp_path):
    golden = tmp_path / "golden"
    _write_golden(golden)
    client = FakeVLMClient([_triage(), _broken(), _good()])

    report = run_baseline(
        golden_dir=golden, client=client, ctx=CTX,
        results_dir=tmp_path / "results", max_attempts=2,
    )

    assert len(client.calls) == 3
    assert report.critical_field_accuracy == 1.0
~~~

- [ ] **Step 5: Implement and validate the baseline parameter**

Add max_attempts: int = 1 to run_baseline, reject values below one before any client is created, and pass it to build_eval_pipeline.

~~~python
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be at least 1, got {max_attempts}")
~~~

~~~python
        attribution_sink=attribution,
        max_attempts=max_attempts,
~~~

Run: python -m pytest tests/test_pipeline.py tests/test_run_baseline.py -q

Expected: PASS.

- [ ] **Step 6: Commit**

~~~bash
git add src/receipts/pipeline.py eval/run_baseline.py tests/test_pipeline.py tests/test_run_baseline.py
git commit -m "feat(eval): expose repair attempts to baseline runs"
~~~

### Task 2: Include the experimental condition in repeated runs

**Files:**

- Modify: eval/run_repeats.py:117-434
- Test: tests/test_run_repeats.py

- [ ] **Step 1: Write the failing artifact test**

Use the module's existing _write_golden and _fresh_tiers_factory helpers.

~~~python
def test_run_repeats_records_the_requested_extraction_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients", _fresh_tiers_factory(1)
    )

    aggregate = run_repeats(
        "repair-budget", 1, golden_dir=golden,
        results_root=tmp_path / "results", max_attempts=2,
    )

    assert aggregate["config"]["max_attempts"] == 2
~~~

- [ ] **Step 2: Verify it fails**

Run: python -m pytest tests/test_run_repeats.py::test_run_repeats_records_the_requested_extraction_budget -q

Expected: FAIL because run_repeats has no max_attempts argument.

- [ ] **Step 3: Pass and record the budget**

Give run_repeats the same max_attempts: int = 1 argument, validate it before prepare_run_dir, include it in config, and forward it to run_baseline.

~~~python
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be at least 1, got {max_attempts}")

    config = config_identity(tiers, settings)
    config["max_attempts"] = max_attempts
~~~

~~~python
        report = _baseline.run_baseline(
            golden_dir=golden_dir,
            results_dir=target,
            max_attempts=max_attempts,
        )
~~~

Add and forward the CLI option:

~~~python
    parser.add_argument(
        "--max-attempts", type=int, default=1,
        help="total extraction attempts; 1 disables repair",
    )
~~~

Run: python -m pytest tests/test_run_repeats.py -q

Expected: PASS.

- [ ] **Step 4: Commit**

~~~bash
git add eval/run_repeats.py tests/test_run_repeats.py
git commit -m "feat(eval): record extraction attempts in repeat runs"
~~~

### Task 3: Add an auditable strict comparison

**Files:**

- Create: eval/run_repair_comparison.py
- Create: tests/test_run_repair_comparison.py

- [ ] **Step 1: Write failing comparator tests**

Create positive and negative fake aggregates. A positive is intentionally stringent: every repaired measurement must exceed every baseline measurement. A comparison with different scored_receipts must fail.

~~~python
def test_comparison_reports_improvement_only_when_distributions_do_not_overlap():
    baseline = _aggregate([0.40, 0.45], max_attempts=1, receipts=["r1", "r2"])
    repair = _aggregate([0.60, 0.65], max_attempts=2, receipts=["r1", "r2"])

    comparison = compare_aggregates(baseline, repair)

    assert comparison["comparable"] is True
    assert comparison["improved"] is True
    assert comparison["criterion"] == "min(repair) > max(baseline)"


def test_comparison_refuses_different_receipt_sets():
    baseline = _aggregate([0.40], max_attempts=1, receipts=["r1"])
    repair = _aggregate([0.60], max_attempts=2, receipts=["r2"])

    with pytest.raises(ValueError, match="scored_receipts"):
        compare_aggregates(baseline, repair)
~~~

- [ ] **Step 2: Verify the tests fail**

Run: python -m pytest tests/test_run_repair_comparison.py -q

Expected: FAIL with ModuleNotFoundError: No module named eval.run_repair_comparison.

- [ ] **Step 3: Implement the closed comparison contract**

compare_aggregates must reject any incomplete run, exact mismatch of scored_receipts, a baseline not at one attempt, a repair group below two attempts, or any configuration change other than the attempt budget. It must compare spread.transcription_accuracy.values only when every value is numeric.

~~~python
def _strictly_improves(baseline: list[float], repair: list[float]) -> bool:
    return bool(baseline and repair and min(repair) > max(baseline))


def compare_aggregates(baseline: dict[str, Any], repair: dict[str, Any]) -> dict[str, Any]:
    if baseline["n_repeats"] != baseline["n_repeats_requested"]:
        raise ValueError("baseline run is incomplete")
    if repair["n_repeats"] != repair["n_repeats_requested"]:
        raise ValueError("repair run is incomplete")
    if baseline["scored_receipts"] != repair["scored_receipts"]:
        raise ValueError("baseline and repair scored_receipts differ")

    baseline_config, repair_config = dict(baseline["config"]), dict(repair["config"])
    baseline_attempts = baseline_config.pop("max_attempts")
    repair_attempts = repair_config.pop("max_attempts")
    if baseline_attempts != 1 or repair_attempts < 2:
        raise ValueError("comparison requires baseline=1 and repair>=2 attempts")
    if baseline_config != repair_config:
        raise ValueError("baseline and repair configuration differ")

    baseline_values = baseline["spread"]["transcription_accuracy"]["values"]
    repair_values = repair["spread"]["transcription_accuracy"]["values"]
    if not all(isinstance(v, (int, float)) for v in baseline_values + repair_values):
        raise ValueError("transcription_accuracy is not fully observed")
    return {
        "comparable": True,
        "metric": "transcription_accuracy",
        "criterion": "min(repair) > max(baseline)",
        "baseline_values": baseline_values,
        "repair_values": repair_values,
        "improved": _strictly_improves(baseline_values, repair_values),
        "scored_receipts": baseline["scored_receipts"],
    }
~~~

Implement run_repair_comparison to invoke run_repeats as {run_id}-baseline with one attempt and {run_id}-repair with the user-provided total (at least two), then write the comparator result plus the two run IDs to {results_root}/{run_id}-comparison.json. A non-improvement writes improved: false and exits successfully; it is a measurement, not a runtime failure.

- [ ] **Step 4: Add the end-to-end offline tests**

Monkeypatch run_repeats in the new module to return the two fake aggregates. Assert the requested budgets, written JSON, improved true for disjoint distributions, and improved false for overlapping distributions.

- [ ] **Step 5: Verify and commit**

Run: python -m pytest tests/test_run_repair_comparison.py -q

Expected: PASS.

~~~bash
git add eval/run_repair_comparison.py tests/test_run_repair_comparison.py
git commit -m "feat(eval): compare baseline and repair accuracy"
~~~

### Task 4: Perform and record the real measurement

**Files:**

- Modify: eval/golden/RUN_SHEET.md
- Modify: IMPLEMENTATION_PLAN.md:768-770 only when truthful

- [ ] **Step 1: Document the exact command**

Add this command to the run sheet and state that three all-handwritten receipts make any success an observed result rather than generalizable evidence.

~~~bash
python -m eval.run_repair_comparison --run-id 2026-08-27-repair-impact --repeats 5 --repair-attempts 2
~~~

- [ ] **Step 2: Run gates**

Run: python -m pytest tests/test_pipeline.py tests/test_run_baseline.py tests/test_run_repeats.py tests/test_run_repair_comparison.py -q

Expected: PASS.

Run: python -m ruff check src/receipts/pipeline.py eval/run_baseline.py eval/run_repeats.py eval/run_repair_comparison.py tests/test_pipeline.py tests/test_run_baseline.py tests/test_run_repeats.py tests/test_run_repair_comparison.py

Expected: All checks passed.

- [ ] **Step 3: Execute the real Ollama comparison**

Confirm that eval/golden/images/ and labels/ still carry the same three stems, then run the command from Step 1. Preserve the two aggregate directories and the comparison JSON under eval/results/.

- [ ] **Step 4: Record only the observed truth**

When the JSON has improved true, tick the definition-of-done row and cite the artifact, receipt IDs, repeats, metric, strict criterion, and three-receipt limitation. When it is false, leave the checkbox unticked and add the artifact path and distributions below the current note. Do not change labels, prompt, model, provider settings, or the evaluated receipt set between conditions.

- [ ] **Step 5: Commit the final artifacts separately**

~~~bash
git add eval/golden/RUN_SHEET.md
git add eval/results/2026-08-27-repair-impact-baseline/ eval/results/2026-08-27-repair-impact-repair/ eval/results/2026-08-27-repair-impact-comparison.json
git add IMPLEMENTATION_PLAN.md
git commit -m "docs(eval): record repair-loop golden-set comparison"
~~~

## Self-review

- **Spec coverage:** The plan creates a genuine repairs-off vs repairs-on measurement, repeats both conditions, rejects incomparable results, and leaves the definition-of-done checkbox governed by a real artifact.
- **Placeholder scan:** Every implementation/test step has named files, code, commands, and expected outcomes.
- **Type consistency:** max_attempts retains run_receipt's existing meaning: total extraction attempts; 1 disables repair and 2 permits one repair.

