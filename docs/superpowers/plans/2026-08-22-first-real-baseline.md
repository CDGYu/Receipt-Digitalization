# The first real baseline — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce the first measured accuracy number in this project's history —
with a spread — plus the first evidence that the ADR-0047 escalation fires
against a real model, and commit both as durable artifacts carrying provenance.

**Architecture:** One new module, `eval/run_repeats.py`, sitting *above*
`eval.run_baseline`. It owns a repeat loop, hands each repeat its own
`results_dir`, and writes one aggregate artifact carrying config identity,
per-repeat metrics, per-repeat rung counts, and a spread. **Nothing under
`src/` changes**, and `run_eval`'s contract is untouched.

**Tech Stack:** Python 3.13 (3.11 also gated in CI), stdlib only for the new
module (`json`, `pathlib`, `statistics`, `argparse`, `dataclasses`), pytest.

**Spec:** `docs/superpowers/specs/2026-08-22-first-real-baseline-design.md` —
read it before Task 1. This plan argues from it and does not restate it.

**Branch:** `feat/first-real-baseline`, cut from `main` at `3939147`. The spec
is already committed on it.

---

## Global Constraints

Every task's requirements implicitly include this section.

- **Nothing under `src/` may change.** Not one line. This is what makes the
  milestone Approach A rather than Approach B; a task that believes it needs a
  `src/` edit is a **stop-and-report**, not a judgement call.
- **`read_nothing` and `is_filled` are not to be touched.** ISSUE-016 is
  report-don't-fix (review standard 19, and ADR-0047's own ruling). `is_filled`
  is shared with `field_accuracy` by design; narrowing it moves a published
  metric. Further never-fires shapes are **reported, not fixed**.
- **Every existing test passes unmodified.** This is the bound, deliberately
  stated instead of a list of files you may edit — an enumerated permit list is
  an enumerated defence and this repository has the defect numbers to prove it.
  Anything that appears to need an existing test changed is a
  **stop-and-report** with the measurement attached.
- **No network, no provider, no image in any test.** The offline seam is
  `run_baseline`'s injectable `client` / monkeypatched `make_pass_clients`.
  Tasks 1–5 add no test that touches a model.
- **Run the suite as bare `python -m pytest`.** `pyproject.toml` sets
  `addopts = "-q"`, so `-q` nets to `-qq` and prints no pass count.
- **Stage by explicit path. Never `git add -A`.** Verify with
  `git diff --cached --stat` before every commit. `var/` is never staged.
- **Do not write a backticked seven-character hex token unless it resolves to a
  reachable commit** (ADR-0042). `tests/test_sha_citations.py` enforces it over
  every tracked file, including this plan and anything you add.
- **A RED step's stated reason is a prediction, not a fact.** Read the actual
  failure. If a test fails for a different reason than the step predicts, that
  is a finding — record it and stop. Plan RED predictions in this repository
  have been wrong for 3 of 4 and 1 of 6 in past milestones.
- **`python -m pytest -k` matches substrings, not words.** Any `-k` filter below
  is a claim about the names in this plan; verify the selection count before
  believing a green.

---

## The three questions the spec left open, now decided

The spec's §10 asked three. This plan answers all three; each answer has a task
that enforces it.

**Q1 — one schema for a one-rung and a two-rung run.** `config.extract_rungs` is
a **list** of `{model_id, use_tools}` objects: length 1 for the cloud-only run,
length 2 for the ladder. A one-rung run therefore has a one-element list and
**no null-shaped hole** that could read as "not measured". The two artifacts diff
against each other directly. Task 2 enforces it.

**Q2 — the run-id, without reintroducing §3.1's collision one level up.**
Two mechanisms with two different jobs, because a single default is what created
the collision this milestone exists to remove:

- `--run-id` is **required and has no default**, so nothing implicit can
  collide;
- the run directory is created with `exist_ok=False`, so an operator who
  *explicitly* reuses a name is refused rather than silently overwriting.

No auto-suffixing. An auto-suffixed second directory is a second artifact nobody
can tell apart from the first, which is the failure wearing a fix's clothes.
Task 1 enforces both.

**Q3 — per-repeat files, or only the aggregate.** **Both are committed.** §16
wants results committed so regressions show in a diff, and the per-receipt
`field_results` block is where a regression is actually legible. The aggregate
deliberately *points at* the per-repeat files rather than duplicating them, so
committing only the aggregate would commit a document whose relative paths
dangle. Task 6 commits them together.

---

## The aggregate artifact, defined once

Every task below refers to this shape. Values are illustrative; nothing pins
them.

```json
{
  "run_id": "2026-08-22-cloud-only",
  "n_repeats": 5,
  "config": {
    "prompt_version": "1.1.0",
    "prompt_bundle_hash": "<hex>",
    "default_currency": "PHP",
    "vlm_timeout_s": 600,
    "triage": {"model_id": "gemma4:cloud", "use_tools": true},
    "extract_rungs": [{"model_id": "gemma4:cloud", "use_tools": true}]
  },
  "repeats": [
    {
      "index": 1,
      "results_file": "repeat-01/2026-08-22-1.1.0.json",
      "counts": {"receipts": 3, "auto_approved": 0, "critical_correct": 2, "failed": 0},
      "metrics": {"transcription_accuracy": 0.61, "...": null},
      "extract_rung_counts": {"gemma4:cloud": 3},
      "failures": []
    }
  ],
  "spread": {
    "transcription_accuracy": {
      "min": 0.5556, "max": 0.6111, "median": 0.58,
      "n": 5, "n_null": 0,
      "values": [0.5556, 0.6111, 0.58, 0.58, 0.60]
    }
  }
}
```

`results_file` is **relative to the run directory**, so the artifact survives the
repository being cloned anywhere.

---

## File structure

| file | responsibility |
|---|---|
| `eval/run_repeats.py` (**create**) | the whole milestone's code: run directory, config identity, spread, loop, aggregate write, CLI |
| `tests/test_run_repeats.py` (**create**) | every pin for the above |
| `docs/adr/0049-*.md` (**create**, Task 7) | the decisions a later reader would tidy away |
| `docs/KNOWN_ISSUES.md` (**modify**, Task 7) | ISSUE-001 step 6 closed; ISSUE-012 and ISSUE-016 annotated |
| `eval/results/<run-id>/**` (**create**, Task 6) | the measurements themselves |

One module rather than four, because every piece is small, they change together,
and this repository's `eval/` package is four flat modules — splitting a
200-line runner into a package would not match anything here.

---

## Task 1: The run directory, and its refusal

**Files:**
- Create: `eval/run_repeats.py`
- Test: `tests/test_run_repeats.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `prepare_run_dir(results_root: Path, run_id: str) -> Path` — creates and
    returns `results_root/run_id`; raises `FileExistsError` if it already
    exists.
  - `repeat_dir(run_dir: Path, index: int) -> Path` — returns
    `run_dir / f"repeat-{index:02d}"`. Does not create it; `_write_report`
    already does `mkdir(parents=True, exist_ok=True)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_run_repeats.py`:

```python
"""The repeat runner: N runs, N directories, one aggregate.

Offline like the rest of the suite. Nothing here touches a provider, a network
or an image; the seam is ``run_baseline``'s injectable client and the
monkeypatchable ``make_pass_clients``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eval.run_repeats import prepare_run_dir, repeat_dir


def test_prepare_run_dir_creates_the_directory(tmp_path):
    run_dir = prepare_run_dir(tmp_path, "2026-08-22-cloud-only")
    assert run_dir == tmp_path / "2026-08-22-cloud-only"
    assert run_dir.is_dir()


def test_prepare_run_dir_creates_missing_parents(tmp_path):
    """The results root may not exist yet: eval/results/ is empty in a clone."""
    root = tmp_path / "not" / "there" / "yet"
    run_dir = prepare_run_dir(root, "r1")
    assert run_dir.is_dir()


def test_prepare_run_dir_refuses_an_existing_run_id(tmp_path):
    """An explicit reuse is refused, never silently overwritten.

    This is the run-id half of the collision the milestone exists to remove:
    ``_write_report`` names its file ``{date}-{prompt_version}.json``, so a
    second run into one directory destroys the first. Auto-suffixing would
    produce a second artifact nobody can tell from the first, so the answer is
    a refusal.
    """
    prepare_run_dir(tmp_path, "same")
    with pytest.raises(FileExistsError):
        prepare_run_dir(tmp_path, "same")


def test_repeat_dir_zero_pads_so_ten_repeats_sort(tmp_path):
    """Zero-padded, so repeat-02 sorts before repeat-10 in any listing."""
    run_dir = tmp_path / "run"
    assert repeat_dir(run_dir, 1).name == "repeat-01"
    assert repeat_dir(run_dir, 10).name == "repeat-10"
    names = sorted(repeat_dir(run_dir, i).name for i in (1, 2, 10))
    assert names == ["repeat-01", "repeat-02", "repeat-10"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_run_repeats.py`

Expected: collection error — `ModuleNotFoundError: No module named 'eval.run_repeats'`.

**Read the actual failure.** If it fails any other way — for instance an
`ImportError` naming a different module — that is a finding about the import
graph, not this step working. Record it and stop.

- [ ] **Step 3: Write the minimal implementation**

Create `eval/run_repeats.py`:

```python
"""Repeat a baseline run N times and write one aggregate artifact.

``eval.run_baseline`` runs the golden set **once** and writes
``{date}-{prompt_version}.json``. Both components are constant within a day, so
two runs on one day overwrite each other -- measured, with a control. ISSUE-001
step 6 requires repeats, because cloud inference is not deterministic at
``temperature=0``.

This module sits *above* ``run_baseline`` and changes nothing below it. Each
repeat gets its own ``results_dir``, which removes the collision by construction
rather than by renaming anything, and the aggregate this module writes is the
only place a *spread* and the per-rung provenance appear together.

    python -m eval.run_repeats --run-id 2026-08-22-cloud-only --repeats 5
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "prepare_run_dir",
    "repeat_dir",
]


def prepare_run_dir(results_root: Path, run_id: str) -> Path:
    """Create ``results_root/run_id``, refusing to reuse an existing one.

    ``exist_ok=False`` is the point, not an oversight. A second run into a
    directory that already holds one destroys its results file, which is the
    exact defect this module exists to remove -- reintroducing it one level up
    would be worse than leaving it where it was, because the run *looks* like it
    produced a fresh artifact.

    Auto-suffixing was considered and rejected: it produces a second artifact
    indistinguishable from the first, and "nothing silently dropped" is a
    project non-negotiable.
    """
    run_dir = Path(results_root) / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def repeat_dir(run_dir: Path, index: int) -> Path:
    """``run_dir/repeat-NN``. Not created here.

    Zero-padded so a listing sorts correctly past nine repeats. Creation is left
    to ``_write_report``, which already does ``mkdir(parents=True,
    exist_ok=True)`` -- creating it here as well would be a second statement of
    the same thing that can drift.
    """
    return Path(run_dir) / f"repeat-{index:02d}"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_run_repeats.py`
Expected: 4 passed.

- [ ] **Step 5: Prove the refusal is load-bearing**

Change `exist_ok=False` to `exist_ok=True` and re-run.
Expected: `test_prepare_run_dir_refuses_an_existing_run_id` fails on
`DID NOT RAISE`. **Revert the change.**

A pin never proven red is not a pin (review standard 14), and this one is the
whole answer to the spec's §10 Q2.

- [ ] **Step 6: Commit**

```bash
git add eval/run_repeats.py tests/test_run_repeats.py
git diff --cached --stat
git commit -m "feat(eval): a run directory that refuses to be reused"
```

---

## Task 2: The configuration identity block

**Files:**
- Modify: `eval/run_repeats.py`
- Test: `tests/test_run_repeats.py`

**Interfaces:**
- Consumes: Task 1's module.
- Produces:
  - `rung_identity(client: Any) -> dict[str, Any]` — `{"model_id": str|None,
    "use_tools": bool|None}`.
  - `config_identity(tiers: Any, settings: Any) -> dict[str, Any]` —
    the `config` block defined above. *(This line said `tiers: PassClients`
    while the task's own code block said `Any`; corrected to match what
    shipped. See defect 6.)*

**The trap this task exists to avoid, measured before the plan was written:**
`use_tools` is an attribute of `OpenAICompatClient` and **is not present on
`FakeVLMClient`**. Every offline test builds fakes. Reading `client.use_tools`
directly makes every test in this milestone die on `AttributeError`, and reading
it from `Settings` instead would record the *global* flag rather than the
**resolved per-rung** value — which is precisely the distinction ADR-0047
decision 2 exists to make. So it is read from the client, defensively, and
records `null` when unobservable — the same idiom `extract_rung_counts` already
uses for the same reason.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_run_repeats.py`:

```python
from eval.run_repeats import config_identity, rung_identity
from receipts.extract.clients.factory import PassClients
from receipts.extract.clients.fake import FakeVLMClient


class _Settings:
    """The four settings the config block reads, and nothing else."""

    default_currency = "PHP"
    vlm_timeout_s = 600


class _Realish(FakeVLMClient):
    """A fake that carries ``use_tools``, as the real client does."""

    def __init__(self, model_id: str, use_tools: bool) -> None:
        super().__init__([], model_id=model_id)
        self.use_tools = use_tools


def test_rung_identity_records_a_tier_not_a_model():
    """ADR-0047 decision 2: a tier is a (model, use_tools) pair."""
    assert rung_identity(_Realish("m", True)) == {
        "model_id": "m",
        "use_tools": True,
    }


def test_rung_identity_records_null_when_use_tools_is_unobservable():
    """FakeVLMClient carries no ``use_tools``; every offline test uses one.

    Measured before this plan was written: ``use_tools`` is set in
    ``OpenAICompatClient.__init__`` and is absent from ``FakeVLMClient``.
    Reading the attribute directly would make every test below die on
    AttributeError, and null is honest -- it says "not observable here", which
    is what ``extract_rung_counts`` already says with the same value.
    """
    assert rung_identity(FakeVLMClient([], model_id="fake")) == {
        "model_id": "fake",
        "use_tools": None,
    }


def test_config_identity_gives_a_one_rung_run_a_one_element_list():
    """The spec's SS10 Q1: no null-shaped hole for a run with one rung.

    A one-rung and a two-rung run must diff against each other directly, so the
    difference between them is a list length and never a null that reads as
    "not measured".
    """
    only = _Realish("gemma4:cloud", True)
    tiers = PassClients(triage=only, extract_rungs=(only,))

    config = config_identity(tiers, _Settings())

    assert config["extract_rungs"] == [
        {"model_id": "gemma4:cloud", "use_tools": True}
    ]
    assert config["triage"] == {"model_id": "gemma4:cloud", "use_tools": True}
    assert config["default_currency"] == "PHP"
    assert config["vlm_timeout_s"] == 600


def test_config_identity_gives_a_two_rung_run_the_same_shape():
    """The ladder differs from the cloud-only run by list length, nothing else."""
    local = _Realish("granite3.2-vision:2b", True)
    cloud = _Realish("gemma4:cloud", True)
    tiers = PassClients(triage=local, extract_rungs=(local, cloud))

    config = config_identity(tiers, _Settings())

    assert config["extract_rungs"] == [
        {"model_id": "granite3.2-vision:2b", "use_tools": True},
        {"model_id": "gemma4:cloud", "use_tools": True},
    ]
    # Same keys as the one-rung run: the two artifacts are directly diffable.
    one = config_identity(
        PassClients(triage=cloud, extract_rungs=(cloud,)), _Settings()
    )
    assert set(config) == set(one)


def test_config_identity_records_the_prompt_identity_it_did_not_invent():
    """Read from the module that owns them, never restated here.

    A copy of PROMPT_VERSION in this module is a second statement that can
    drift, which is the failure the whole repository legislates against.
    """
    from receipts.extract.prompts import PROMPT_VERSION, prompt_bundle_hash

    only = _Realish("m", True)
    config = config_identity(
        PassClients(triage=only, extract_rungs=(only,)), _Settings()
    )

    assert config["prompt_version"] == PROMPT_VERSION
    assert config["prompt_bundle_hash"] == prompt_bundle_hash()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_run_repeats.py`
Expected: `ImportError: cannot import name 'config_identity'`.

Read the actual failure before continuing.

- [ ] **Step 3: Write the implementation**

Add to `eval/run_repeats.py` (extend `__all__` with both names):

```python
from typing import Any


def rung_identity(client: Any) -> dict[str, Any]:
    """One rung, as the ``(model, use_tools)`` pair ADR-0047 decision 2 defines.

    ``use_tools`` is read from the client rather than from ``Settings`` because
    the *resolved* per-rung value is the thing that differs between rungs --
    ``VLM_USE_TOOLS`` is process-wide and cannot express a ladder whose rungs
    disagree, which is the constraint that ADR made a decision about.

    Read defensively, because it is genuinely optional: ``OpenAICompatClient``
    sets it, ``FakeVLMClient`` does not, and every offline test uses a fake.
    ``None`` means "not observable here", which is the same thing
    ``extract_rung_counts`` says with the same value.
    """
    return {
        "model_id": getattr(client, "model_id", None),
        "use_tools": getattr(client, "use_tools", None),
    }


def config_identity(tiers: Any, settings: Any) -> dict[str, Any]:
    """What ran, in enough detail to tell two runs apart.

    ``extract_rungs`` is a list so a one-rung run and a two-rung run share one
    schema and differ only in length -- never a null that a reader could take
    for "not measured".

    Prompt identity is imported, never restated: a second copy of
    ``PROMPT_VERSION`` here is a copy that can drift.
    """
    from receipts.extract.prompts import PROMPT_VERSION, prompt_bundle_hash

    return {
        "prompt_version": PROMPT_VERSION,
        "prompt_bundle_hash": prompt_bundle_hash(),
        "default_currency": settings.default_currency,
        "vlm_timeout_s": settings.vlm_timeout_s,
        "triage": rung_identity(tiers.triage),
        "extract_rungs": [rung_identity(c) for c in tiers.extract_rungs],
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_run_repeats.py`
Expected: 9 passed.

- [ ] **Step 5: Prove the defensive read is load-bearing**

Replace `getattr(client, "use_tools", None)` with `client.use_tools` and re-run.
Expected: `test_rung_identity_records_null_when_use_tools_is_unobservable` fails
with `AttributeError`. **Revert.**

- [ ] **Step 6: Verify the settings attribute names against the real class**

Run:

```bash
python -c "import sys; from pathlib import Path; sys.path.insert(0, str(Path.cwd()/'src')); sys.path.insert(0, str(Path.cwd())); from config.settings import Settings; s=Settings(); print(s.default_currency, s.vlm_timeout_s)"
```

Expected: two values print without `AttributeError`. **This step exists because
`_Settings` in the test is a stub, and a stub that reflects what the writer
believed rather than what the class declares is a test that passes while the
production path raises.** If either name is wrong, that is the finding — fix the
implementation, not the stub.

- [ ] **Step 7: Commit**

```bash
git add eval/run_repeats.py tests/test_run_repeats.py
git diff --cached --stat
git commit -m "feat(eval): a tier is recorded as a pair, and null when unobservable"
```

---

## Task 3: The spread

**Files:**
- Modify: `eval/run_repeats.py`
- Test: `tests/test_run_repeats.py`

**Interfaces:**
- Consumes: Task 2's module.
- Produces:
  - `spread_over(metric_dicts: list[dict[str, Any]]) -> dict[str, dict]` — for
    every key appearing in any input dict whose values are numeric, an entry
    `{"min", "max", "median", "n", "n_null", "values"}`.

**Two properties this must have**, both from spec §4.1 and §4.2:

- **Every figure in the output is a value that was actually observed.** Median
  uses `statistics.median_low`, not `statistics.median`: for an even count the
  latter averages the two middle values, which synthesises a number nobody
  measured. No mean, and no standard deviation — a stdev over five samples reads
  as a statistic and is not one.
- **The key set is derived, not enumerated.** Metrics are read from the report
  dictionaries themselves, so a metric added to `_report_to_dict` later appears
  without anybody deciding. A list of metric names written here would be a claim
  that ages (review standard 20).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_run_repeats.py`:

```python
from eval.run_repeats import spread_over


def test_spread_reports_only_values_that_were_observed():
    """min, max and median are all real observations; no mean, no stdev.

    ``statistics.median`` averages the two middle values on an even count,
    which invents a figure nobody measured. ``median_low`` cannot.
    """
    out = spread_over([{"acc": 0.10}, {"acc": 0.20}, {"acc": 0.40}, {"acc": 0.80}])

    assert out["acc"]["min"] == 0.10
    assert out["acc"]["max"] == 0.80
    assert out["acc"]["median"] in (0.20, 0.40)
    assert out["acc"]["median"] in out["acc"]["values"]
    assert "mean" not in out["acc"]
    assert "stdev" not in out["acc"]


def test_spread_keeps_the_raw_values_in_repeat_order():
    """The file carries the observations, so any other summary is derivable."""
    out = spread_over([{"acc": 0.3}, {"acc": 0.1}, {"acc": 0.2}])
    assert out["acc"]["values"] == [0.3, 0.1, 0.2]
    assert out["acc"]["n"] == 3
    assert out["acc"]["n_null"] == 0


def test_spread_counts_nulls_separately_rather_than_averaging_over_them():
    """``auto_approval_precision`` is null when nothing was auto-approved.

    A ratio over no paths is undefined, not zero -- the rule ``format_report``
    already follows. Folding a null in as 0 would report a precision collapse
    that did not happen.
    """
    out = spread_over([{"p": 0.9}, {"p": None}, {"p": 0.7}])

    assert out["p"]["n"] == 2
    assert out["p"]["n_null"] == 1
    assert out["p"]["min"] == 0.7
    assert out["p"]["max"] == 0.9
    assert out["p"]["values"] == [0.9, None, 0.7]


def test_spread_of_an_all_null_metric_is_null_not_zero():
    out = spread_over([{"p": None}, {"p": None}])
    assert out["p"]["min"] is None
    assert out["p"]["max"] is None
    assert out["p"]["median"] is None
    assert out["p"]["n"] == 0
    assert out["p"]["n_null"] == 2


def test_spread_derives_its_keys_and_does_not_enumerate_them():
    """A metric added to the report later appears without anybody deciding."""
    out = spread_over([
        {"known": 1, "added_next_year": 5},
        {"known": 2, "added_next_year": 7},
    ])
    assert set(out) == {"known", "added_next_year"}


def test_spread_skips_non_numeric_entries():
    """Counts and metrics are numeric; a stray string is not a distribution."""
    out = spread_over([{"label": "cloud", "n": 1}, {"label": "cloud", "n": 3}])
    assert set(out) == {"n"}


def test_spread_of_one_repeat_has_equal_min_and_max():
    """n=1 is the ladder run. It is a valid spread of one, not an error."""
    out = spread_over([{"acc": 0.5}])
    assert out["acc"]["min"] == out["acc"]["max"] == 0.5
    assert out["acc"]["n"] == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_run_repeats.py`
Expected: `ImportError: cannot import name 'spread_over'`.

- [ ] **Step 3: Write the implementation**

Add to `eval/run_repeats.py` (extend `__all__`):

```python
import statistics


def _numeric(value: Any) -> bool:
    """True for a real number. ``bool`` is excluded: it is not a distribution."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def spread_over(metric_dicts: list[dict[str, Any]]) -> dict[str, dict]:
    """Per metric, the shape of what N repeats actually produced.

    **Every figure here was observed.** ``median_low`` rather than ``median``,
    because ``median`` averages the two middle values on an even count and so
    reports a number no repeat produced. No mean and no standard deviation: a
    stdev over five samples reads as a statistic without being one, and the
    whole reason step 6 demands repeats is that a single figure was going to be
    read as more than it was. The raw values are in the file, so anyone who
    wants another summary can compute it and say so.

    **Keys are derived from the inputs**, so a metric added to
    ``_report_to_dict`` later is included without anybody deciding -- the same
    schema-derived shape ``group_of`` uses, for the same reason.

    Nulls are counted, never folded in as zero. ``auto_approval_precision`` is
    ``None`` when nothing was auto-approved, and a ratio over no paths is
    undefined rather than bad.
    """
    keys: list[str] = []
    for d in metric_dicts:
        for k in d:
            if k not in keys:
                keys.append(k)

    out: dict[str, dict] = {}
    for key in keys:
        raw = [d.get(key) for d in metric_dicts]
        if not any(_numeric(v) for v in raw):
            # Every value is null -> report it as unmeasured, not as zero.
            # Every value non-numeric -> not a distribution; skip the key.
            if not all(v is None for v in raw):
                continue
        observed = [v for v in raw if _numeric(v)]
        out[key] = {
            "min": min(observed) if observed else None,
            "max": max(observed) if observed else None,
            "median": statistics.median_low(observed) if observed else None,
            "n": len(observed),
            "n_null": sum(1 for v in raw if v is None),
            "values": raw,
        }
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_run_repeats.py`
Expected: 16 passed.

- [ ] **Step 5: Prove the median choice is load-bearing**

Change `statistics.median_low` to `statistics.median` and re-run.
Expected: `test_spread_reports_only_values_that_were_observed` fails — with four
values the median becomes `0.30`, which is not in `values`. **Revert.**

This is the pin for spec §4.1's "every figure was observed". Without the red it
is a preference, not a guarantee.

- [ ] **Step 6: Commit**

```bash
git add eval/run_repeats.py tests/test_run_repeats.py
git diff --cached --stat
git commit -m "feat(eval): a spread whose every figure was actually observed"
```

---

## Task 4: The runner and the aggregate

**Files:**
- Modify: `eval/run_repeats.py`
- Test: `tests/test_run_repeats.py`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces:
  - `run_repeats(run_id, repeats, *, golden_dir=None, results_root=None, run_baseline_fn=None, make_tiers_fn=None) -> dict` — runs the loop, writes
    `<run_dir>/aggregate.json`, returns the aggregate dict.

**The trap this task exists to avoid, measured before the plan was written:**
`FakeVLMClient` is **stateful** — it replays a fixed response list in order and
appends to `.calls`. A monkeypatched `make_pass_clients` that closes over one set
of fakes returns *the same exhausted objects* on repeat 2. Every test below must
mint **fresh** fakes per call. A test that does not will fail with
"FakeVLMClient exhausted", which is a test-authoring failure wearing a pin's
clothes.

**`from pathlib import Path` is added by this task, not Task 1.** Task 1's test
block declared it and never used it, which is an `F401` — and
`python -m ruff check .` is one of the five blocking gates. Task 1's implementer
removed the dead import rather than transcribing it, and was right to. This task
is the first that actually calls `Path(...)` in the test module, so the import
appears here. If you find it already present, leave it; if `Path` is
undefined, this note is why.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_run_repeats.py`:

```python
import json
from pathlib import Path

from eval.run_baseline import latest_results_file
from eval.run_repeats import run_repeats


def _fresh_tiers_factory(n_rungs=1):
    """A builder that mints FRESH fakes on every call.

    ``FakeVLMClient`` replays a fixed list and records calls, so returning one
    set of clients from a closure hands repeat 2 an exhausted object. Measured
    before this plan was written; a builder that reuses them fails with
    "FakeVLMClient exhausted", which looks like a product bug and is not one.
    """
    def build(settings=None):
        triage = FakeVLMClient([_triage()], model_id="triage-model")
        if n_rungs == 1:
            only = FakeVLMClient([_good()], model_id="cloud")
            return PassClients(triage=triage, extract_rungs=(only,))
        local = FakeVLMClient([_unparseable()], model_id="local")
        cloud = FakeVLMClient([_good()], model_id="cloud")
        return PassClients(triage=triage, extract_rungs=(local, cloud))

    return build
```

> **Note for the implementer:** `_triage`, `_good`, `_unparseable` and
> `_write_golden` already exist in `tests/test_run_baseline.py`. Import them or
> copy them — **do not modify `tests/test_run_baseline.py`**, which is covered by
> the "every existing test passes unmodified" bound. Copying four small fixture
> helpers into this module is the expected resolution; if you import them
> instead, verify the import does not drag `pytest.importorskip` behaviour
> across modules.

```python
def test_n_repeats_produce_n_directories_and_one_aggregate(tmp_path, monkeypatch):
    """The collision, closed by construction.

    ``_write_report`` names its file ``{date}-{prompt_version}.json``, both
    constant within a day. Measured: two writes into one directory leave one
    file and the second wins. Giving each repeat its own directory is what
    removes that -- and this test is the pin, so Step 5 proves it red.
    """
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients", _fresh_tiers_factory(1)
    )

    aggregate = run_repeats(
        "run-a", 3, golden_dir=golden, results_root=tmp_path / "results"
    )

    run_dir = tmp_path / "results" / "run-a"
    dirs = sorted(p.name for p in run_dir.iterdir() if p.is_dir())
    assert dirs == ["repeat-01", "repeat-02", "repeat-03"]

    # One results file per repeat, all three surviving.
    files = sorted(run_dir.rglob("repeat-*/*.json"))
    assert len(files) == 3

    assert (run_dir / "aggregate.json").is_file()
    assert aggregate["n_repeats"] == 3
    assert len(aggregate["repeats"]) == 3


def test_the_aggregate_points_at_each_repeats_own_results_file(tmp_path, monkeypatch):
    """Relative paths, so the artifact survives being cloned anywhere."""
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients", _fresh_tiers_factory(1)
    )

    run_repeats("run-b", 2, golden_dir=golden, results_root=tmp_path / "results")

    run_dir = tmp_path / "results" / "run-b"
    aggregate = json.loads((run_dir / "aggregate.json").read_text(encoding="utf-8"))
    for entry in aggregate["repeats"]:
        rel = entry["results_file"]
        assert not Path(rel).is_absolute()
        assert (run_dir / rel).is_file()


def test_the_aggregate_carries_the_rung_counts_the_results_file_does_not(
    tmp_path, monkeypatch
):
    """ISSUE-012, discharged for this artifact.

    The ladder escalates: rung 0 returns an unparseable body, so it reads
    nothing and is discarded, and ``cloud`` produces the kept extraction. The
    count must therefore be ``{"cloud": 1}`` and not ``{"local": 1}`` -- an
    assertion that a single key exists would pass either way.
    """
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients", _fresh_tiers_factory(2)
    )

    aggregate = run_repeats(
        "run-c", 2, golden_dir=golden, results_root=tmp_path / "results"
    )

    for entry in aggregate["repeats"]:
        assert entry["extract_rung_counts"] == {"cloud": 1}
        assert entry["failures"] == []

    # And the per-run results file still does not carry them: this milestone
    # took no position on who owns that write.
    run_dir = tmp_path / "results" / "run-c"
    one = json.loads(
        (run_dir / aggregate["repeats"][0]["results_file"]).read_text(encoding="utf-8")
    )
    assert "extract_rung_counts" not in one


def test_the_aggregate_records_a_two_rung_ladder_as_two_tiers(tmp_path, monkeypatch):
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients", _fresh_tiers_factory(2)
    )

    aggregate = run_repeats(
        "run-d", 1, golden_dir=golden, results_root=tmp_path / "results"
    )

    rungs = aggregate["config"]["extract_rungs"]
    assert [r["model_id"] for r in rungs] == ["local", "cloud"]


def test_the_runner_writes_nothing_latest_results_file_can_see(tmp_path, monkeypatch):
    """The guarantee spec SS3.2 rests on, stated over the real function.

    ``receipts calibrate`` with no ``--results`` resolves its input through
    ``latest_results_file``, which globs ``*.json`` non-recursively. An
    aggregate at the top of ``eval/results/`` would become the newest file and
    be handed to a command that cannot read it.
    """
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients", _fresh_tiers_factory(1)
    )
    results_root = tmp_path / "results"

    run_repeats("run-e", 2, golden_dir=golden, results_root=results_root)

    assert latest_results_file(results_root) is None


def test_a_repeat_that_fails_is_recorded_rather_than_averaged_away(
    tmp_path, monkeypatch
):
    """A partially failed repeat must be visible, not folded into the spread.

    ``run_eval`` catches per receipt so one bad receipt never takes the batch
    down. The aggregate therefore carries failures per repeat: a repeat that
    scored some receipts and failed others is not a whole observation.
    """
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)

    def _explodes(settings=None):
        triage = FakeVLMClient([_triage()], model_id="triage-model")
        # No scripted extract response: the extract call raises "exhausted",
        # which run_eval records as a failure for that receipt.
        return PassClients(
            triage=triage, extract_rungs=(FakeVLMClient([], model_id="empty"),)
        )

    monkeypatch.setattr("eval.run_baseline.make_pass_clients", _explodes)

    aggregate = run_repeats(
        "run-f", 1, golden_dir=golden, results_root=tmp_path / "results"
    )

    entry = aggregate["repeats"][0]
    assert entry["counts"]["failed"] >= 1
    assert entry["failures"], "a failed receipt must reach the aggregate"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_run_repeats.py`
Expected: `ImportError: cannot import name 'run_repeats'`.

**Two predictions in this step, and the first one was wrong in an earlier draft
of this very plan.** That draft patched `eval.run_repeats.make_pass_clients`;
`run_baseline` imports the name into its *own* module and calls it there
(`eval/run_baseline.py`, in `run_baseline`'s `client is None` branch), so the
patch would not have reached the clients any repeat actually ran — every test
here would have built real ones. The target is
`eval.run_baseline.make_pass_clients`, which is what the existing ladder test in
`tests/test_run_baseline.py` already patches. If `monkeypatch.setattr` fails at
*setup*, the module no longer exports that name and that is the finding.

Second, `test_a_repeat_that_fails...` predicts an "exhausted" error reaches
`failures`; if it surfaces out of `run_repeats` instead, that is a finding about
`run_eval`'s catch, not about this test. Read both failures.

- [ ] **Step 3: Write the implementation**

Add to `eval/run_repeats.py` (extend `__all__`):

```python
import json

import eval.run_baseline as _baseline
from config.settings import get_settings
from eval.harness import DEFAULT_RESULTS_DIR


def _report_metrics(report: Any) -> dict[str, Any]:
    """The numeric surface of one report, derived from the report itself.

    Reads the same dictionary the results file is built from, so a metric added
    to ``_report_to_dict`` later reaches the spread without anybody deciding.
    """
    from eval.harness import _report_to_dict

    return dict(_report_to_dict(report).get("metrics", {}))


def run_repeats(
    run_id: str,
    repeats: int,
    *,
    golden_dir: Path | None = None,
    results_root: Path | None = None,
) -> dict[str, Any]:
    """Run the baseline ``repeats`` times and write one aggregate artifact.

    Each repeat gets its own ``results_dir`` under ``<run_dir>/repeat-NN``,
    which is what stops ``{date}-{prompt_version}.json`` from colliding. The
    aggregate is written last and is rebuildable from the per-repeat files, so
    an interrupted sequence still leaves every completed repeat on disk.

    Both ``make_pass_clients`` and ``run_baseline`` are reached **through the
    ``eval.run_baseline`` module** rather than imported by name here, so a
    single ``monkeypatch`` of ``eval.run_baseline.make_pass_clients`` governs
    both the clients this function describes and the clients each repeat
    actually runs.

    Importing either name into this module would give it a second binding, and
    a test patching one would leave the other building real clients -- two
    mechanisms that must agree, which is review standard 19. That is not
    hypothetical: ``run_baseline`` calls ``make_pass_clients`` from its own
    namespace, so patching a binding here would not reach it at all.
    """
    if repeats < 1:
        raise ValueError(f"repeats must be at least 1, got {repeats}")

    root = Path(results_root) if results_root is not None else DEFAULT_RESULTS_DIR
    run_dir = prepare_run_dir(root, run_id)
    settings = get_settings()
    tiers = _baseline.make_pass_clients(settings)

    entries: list[dict[str, Any]] = []
    for index in range(1, repeats + 1):
        target = repeat_dir(run_dir, index)
        report = _baseline.run_baseline(golden_dir=golden_dir, results_dir=target)
        written = sorted(target.glob("*.json"))
        entries.append({
            "index": index,
            "results_file": (
                written[0].relative_to(run_dir).as_posix() if written else None
            ),
            "counts": {
                "receipts": report.n_receipts,
                "auto_approved": report.n_auto_approved,
                "critical_correct": report.n_critical_correct,
                "failed": report.n_failed,
            },
            "metrics": _report_metrics(report),
            "extract_rung_counts": report.extract_rung_counts,
            "failures": [list(f) for f in report.failures],
        })

    aggregate = {
        "run_id": run_id,
        "n_repeats": repeats,
        "config": config_identity(tiers, settings),
        "repeats": entries,
        "spread": spread_over([e["metrics"] for e in entries]),
    }
    (run_dir / "aggregate.json").write_text(
        json.dumps(aggregate, indent=2, default=str), encoding="utf-8"
    )
    return aggregate
```

> **Implementer note on `tiers`:** the clients built here are for the **config
> block only**; `run_baseline` builds its own on every call, which is what keeps
> each repeat's fakes fresh. **Do not pass `tiers` into `run_baseline`** — that
> takes its injected-client branch, which is deliberately one rung for every
> pass, and would silently disable the ladder while every test still passed.
> `tests/test_run_baseline.py::test_an_injected_client_gets_no_ladder` is named
> for exactly that behaviour; read it before changing this.
>
> Building the tiers a second time here is safe because `make_pass_clients` is a
> pure function of `settings` — the block therefore describes the same ladder the
> repeats ran. If that ever stops being true, this description stops being
> accurate, and that is the thing to check rather than this sentence.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_run_repeats.py`
Expected: 22 passed.

- [ ] **Step 5: Prove the collision pin is red-capable**

Temporarily change `repeat_dir` to `return Path(run_dir)` — every repeat writing
into the run directory itself. Re-run.

Expected: `test_n_repeats_produce_n_directories_and_one_aggregate` fails, because
one results file survives where three are asserted. **Revert.**

This is the pin for the milestone's central measurement. Without this red it is
an assertion that was never tested against the failure it describes.

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest`
Expected: every test passes, and **no existing test is modified**. Confirm with
`git status --short` that only the two files this milestone owns are dirty.

- [ ] **Step 7: Commit**

```bash
git add eval/run_repeats.py tests/test_run_repeats.py
git diff --cached --stat
git commit -m "feat(eval): N repeats, N directories, one aggregate with provenance"
```

---

## Task 5: The command-line entry point

**Files:**
- Modify: `eval/run_repeats.py`
- Test: `tests/test_run_repeats.py`

**Interfaces:**
- Consumes: Task 4.
- Produces: `main(argv: list[str] | None = None) -> int`, and
  `python -m eval.run_repeats --run-id ID --repeats N`.

**Both arguments are required and neither has a default.** `--run-id` has no
default because an implicit default is what created the collision this milestone
removes. `--repeats` has no default because a default of 1 would let someone run
the tool and read a single run as a baseline, which is the exact thing spec §1
says a baseline is not.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_run_repeats.py`:

```python
from eval.run_repeats import main


def test_both_arguments_are_required(capsys):
    """No default can silently collide, and no default can produce a
    single-run artifact that reads as a baseline."""
    with pytest.raises(SystemExit):
        main(["--repeats", "3"])
    with pytest.raises(SystemExit):
        main(["--run-id", "x"])


def test_main_refuses_a_reused_run_id_with_a_message_not_a_traceback(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients", _fresh_tiers_factory(1)
    )
    (tmp_path / "results" / "taken").mkdir(parents=True)

    code = main([
        "--run-id", "taken",
        "--repeats", "1",
        "--golden-dir", str(golden),
        "--results-root", str(tmp_path / "results"),
    ])

    assert code != 0
    assert "taken" in capsys.readouterr().err


def test_main_writes_the_aggregate_and_reports_where(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VLM_PROVIDER", "ollama")
    golden = tmp_path / "golden"
    _write_golden(golden)
    monkeypatch.setattr(
        "eval.run_baseline.make_pass_clients", _fresh_tiers_factory(1)
    )

    code = main([
        "--run-id", "run-g",
        "--repeats", "2",
        "--golden-dir", str(golden),
        "--results-root", str(tmp_path / "results"),
    ])

    assert code == 0
    out = capsys.readouterr().out
    assert "aggregate.json" in out
    assert (tmp_path / "results" / "run-g" / "aggregate.json").is_file()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_run_repeats.py`
Expected: `ImportError: cannot import name 'main'`.

- [ ] **Step 3: Write the implementation**

Add to `eval/run_repeats.py`:

```python
import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Both identifying arguments are required.

    A reused ``--run-id`` is a clean message and a non-zero exit, not a
    ``FileExistsError`` traceback -- the same shape every other refusal in this
    repository takes.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True,
                        help="names this run's directory; must not already exist")
    parser.add_argument("--repeats", type=int, required=True,
                        help="how many times to run the golden set")
    parser.add_argument("--golden-dir", type=Path, default=None)
    parser.add_argument("--results-root", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        aggregate = run_repeats(
            args.run_id,
            args.repeats,
            golden_dir=args.golden_dir,
            results_root=args.results_root,
        )
    except FileExistsError:
        print(
            f"Run id {args.run_id!r} already has a directory. Runs are never "
            f"overwritten -- choose another --run-id.",
            file=sys.stderr,
        )
        return 1
    except (RuntimeError, ValueError) as exc:
        print(f"Cannot run repeats: {exc}", file=sys.stderr)
        return 1

    root = args.results_root if args.results_root is not None else DEFAULT_RESULTS_DIR
    print(f"Wrote {Path(root) / args.run_id / 'aggregate.json'}")
    print(f"Repeats: {aggregate['n_repeats']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_run_repeats.py`
Expected: 25 passed.

- [ ] **Step 5: Run it from outside the repository**

A green suite is not evidence that an entry point runs. From a directory that is
**not** the repository root:

```bash
python -m eval.run_repeats --help
```

Expected: the help text, exit 0. If it fails on imports, that is the finding —
`eval` is not an installed package, so record how it must be invoked rather than
changing `src/`.

- [ ] **Step 6: Make the module docstring's claims true, and prove it**

`eval/run_repeats.py`'s module docstring has advertised this command and "the
aggregate this module writes" since Task 1, when neither existed. Measured at
that commit: `python -m eval.run_repeats --run-id probe --repeats 5` **exited 0,
printed nothing and wrote nothing** — a documented command reporting success
while producing no artifact, which is the failure shape this module exists to
remove. It was allowed to stand only because this step retires it.

Run the command the docstring actually advertises, against a scratch results
root so nothing lands in `eval/results/`:

```bash
python -m eval.run_repeats --run-id docstring-check --repeats 1 \
  --results-root "$(mktemp -d)"
```

Then read the module docstring line by line and confirm every claim in it is now
true of the module. **Any claim that is still not true gets deleted, not
reworded** — that is this repository's standing rule for prose that over-reaches
(ADR-0032, and five milestones of it being closed by deletion).

Report what the command did, and which docstring claims you checked.

- [ ] **Step 7: Full suite, lint, then commit**

```bash
python -m pytest
python -m ruff check .
git add eval/run_repeats.py tests/test_run_repeats.py
git diff --cached --stat
git commit -m "feat(eval): a runner whose run id cannot silently collide"
```

---

## Task 6 — CONTROLLER ONLY: the real runs

**Do not dispatch this to a subagent.** It needs the operator's machine, a live
Ollama Cloud sign-in, and roughly two hours of wall clock. It produces the
measurement this whole milestone exists for.

**Files:**
- Create: `eval/results/<run-id>/**` (data)

- [ ] **Step 1: Confirm the runtime before spending two hours on it**

```bash
docker ps --format "{{.Names}} {{.Ports}}"
curl -s --max-time 20 http://localhost:11435/api/tags
```

Expected: the `ollama` container up with `11435->11434`, and `gemma4:cloud` and
`granite3.2-vision:2b` both listed. **There are two Ollama daemons on this
machine**; the project reads the Docker one on `:11435`.

- [ ] **Step 2: Time one granite call — ISSUE-001 step 6 item 4**

```bash
VLM_MODEL_EXTRACT="granite3.2-vision:2b" VLM_MODEL_TRIAGE="granite3.2-vision:2b" \
  python scripts/try_one_receipt.py r002
```

Record the wall clock. **This replaces a figure carried from ISSUE-001 (30–39
minutes) that nobody has re-measured on this box.** It writes no files.

**Report the result as wall clock for the receipt, never as a per-call time** —
`VLM_TIMEOUT_S` bounds one HTTP attempt and the SDK retries (ADR-0047 decision
8), so the elapsed figure covers an unknown number of attempts. There is no
per-call measurement in this repository and this step does not create one.

- [ ] **Step 3: Run the ladder once**

```bash
VLM_MODEL_EXTRACT="granite3.2-vision:2b" \
VLM_MODEL_EXTRACT_FALLBACK="gemma4:cloud" \
VLM_MODEL_TRIAGE="granite3.2-vision:2b" \
VLM_USE_TOOLS=true VLM_USE_TOOLS_TRIAGE=false \
  python -m eval.run_repeats --run-id "$(date +%F)-ladder" --repeats 1
```

`VLM_USE_TOOLS_TRIAGE=false` is not optional: tools on costs granite the
`merchant_name_guess` that ADR-0043 decision 1's hint path keys off.

- [ ] **Step 4: Read the ladder's rung counts before going further**

Open `aggregate.json` and read `repeats[0].extract_rung_counts`.

- **`{"gemma4:cloud": 3}`** — every receipt escalated. Record **which clause of
  ADR-0047 decision 3 fired**: a raise (granite timed out or errored) or
  read-nothing. They are different findings and "the escalation works" does not
  distinguish them.
- **Any count for `granite3.2-vision:2b`** — **stop and inspect that receipt's
  kept extraction.** This is spec §6: ISSUE-016's vacuous values defeat
  `read_nothing`, so granite's extraction can be kept and drag the score down.
  Record what field kept it. **Do not fix `read_nothing`** — report-don't-fix.

- [ ] **Step 5: Run the cloud-only baseline five times**

Today's `.env` unchanged — both passes on `gemma4:cloud`, no fallback:

```bash
python -m eval.run_repeats --run-id "$(date +%F)-cloud-only" --repeats 5
```

- [ ] **Step 6: Read the spread before writing any number down**

From the cloud-only `aggregate.json`, read
`spread.transcription_accuracy`. **Report min, max, median and n — never a
single figure.** Two identical runs on r002 have already scored 55.56% and
61.11%; a lone number is a sample wearing a number's clothes.

Check `n_null` on every metric: a metric that was undefined in some repeats has
a spread over fewer observations than the run had repeats.

- [ ] **Step 7: Commit the artifacts**

```bash
git add eval/results/
git diff --cached --stat
git commit -m "eval: the first measured baseline, with its spread and its provenance"
```

Both the per-repeat files and the aggregates are committed — §16 wants results
committed so regressions show in a diff, and the aggregate's `results_file`
paths dangle if the files it points at are not there.

---

## Task 7 — CONTROLLER ONLY: the record

**Files:**
- Create: `docs/adr/0049-<slug>.md`
- Modify: `docs/adr/README.md`, `docs/KNOWN_ISSUES.md`

- [ ] **Step 1: Write ADR-0049**

The decisions a later reader would otherwise tidy away, each with what would
fail if it were reversed (ADR-0048 decision 2):

1. The baseline is the **cloud-only** run; the ladder run is a proof of
   mechanism. The escalation design §7 says a cloud-only run is what step 6
   needs on this hardware.
2. A run directory is **never reused** — required `--run-id`, `exist_ok=False`,
   no auto-suffix.
3. The spread reports **only observed values** — `median_low`, no mean, no
   stdev.
4. `use_tools` is read from the **client**, defensively, and `null` means
   unobservable.
5. This milestone took **no position** on who owns `run_eval`'s write
   (ISSUE-012), and **did not touch** `read_nothing` (ISSUE-016).

Add its row to `docs/adr/README.md`. Verify the two counts agree afterwards:

```bash
ls docs/adr/*.md | grep -v README | wc -l
grep -cE "^\| *\[?0[0-9]{3}" docs/adr/README.md
```

- [ ] **Step 2: Update `docs/KNOWN_ISSUES.md`**

- **ISSUE-001** — step 6 done. Record the spread, both run-ids, and the ladder's
  rung counts. **Do not write a single accuracy figure anywhere.**
- **ISSUE-012** — still open; annotate that it no longer gates step 6, and why.
- **ISSUE-016** — annotate that it **gates a ladder configuration**, which its
  current text does not say, with the measurement from spec §6.

Verify the register stays self-consistent:

```bash
grep -c "^## ISSUE-" docs/KNOWN_ISSUES.md
grep -c "^\*\*Status:\*\*" docs/KNOWN_ISSUES.md
```

Both numbers must agree.

- [ ] **Step 3: Commit, in a commit touching neither handoff file**

```bash
git add docs/adr/ docs/KNOWN_ISSUES.md
git diff --cached --stat
git commit -m "docs(adr): ADR-0049, the baseline is the cloud-only run"
```

**ADR-0033 §1:** `docs/MEMORY.md` and `docs/NEXT_SESSION_PROMPT.md` are refreshed
**last and alone**, in a commit touching nothing else, after the merge. Bundling
them here makes the pair's own freshness check report itself stale.

---

## Self-review of this plan

**Spec coverage.** §1 → Tasks 6.3/6.5. §2 → verified before the plan was
written. §3 architecture → Task 4; §3.1 collision → Tasks 1 and 4; §3.2
subdirectory → Task 4's `latest_results_file` pin. §4 artifact → Tasks 2–4;
§4.1 omissions → Task 3; §4.2 derived keys → Task 3. §5 the two runs → Task 6;
§5.1 which run is the baseline → ADR-0049 decision 1. §6 ISSUE-016 → Task 6
Step 4. §7 failure modes → Task 4's failures test and Task 6 Step 4. §8 testing
→ the RED step in every task. §9/§10 → the decisions section above.

**No spec section is without a task.**

**Type consistency.** `prepare_run_dir` / `repeat_dir` / `rung_identity` /
`config_identity` / `spread_over` / `run_repeats` / `main` are spelled
identically in every task that references them. `PassClients` carries exactly
`triage` and `extract_rungs` — verified against the dataclass, not recalled.
`FieldBreakdown` is never constructed positionally in this plan; all eleven of
its fields default to `0`.

**Known soft spots, stated rather than hidden.**

1. Task 4 Step 4 predicts "22 passed" and Task 5 predicts "25 passed". Those are
   arithmetic over tests this plan wrote and **have not been executed**. Treat a
   different count as a prompt to check *which* test is missing, not as a
   failure.
2. Task 4's fixture note says to copy `_triage` / `_good` / `_unparseable` /
   `_write_golden` rather than import them. `_write_golden` carries a
   `pytest.importorskip` discussion in its docstring about Pillow; the
   implementer must read that docstring before copying, because the guard's
   placement is load-bearing and copying it wrongly makes the whole new module
   skip silently.
3. `_report_to_dict` is a private name. Task 4 imports it. If a reviewer objects,
   the alternative is to rebuild the metrics dict here — which is a second
   statement of the report's shape that can drift, and worse. Recorded as a
   deliberate choice, not an oversight.

---

## Dated defect log

**This plan does not self-amend.** Everything above is the text as corrected;
this log is what was wrong with it and when, so a reader can calibrate how much
of the rest to re-derive rather than trust.

### 2026-08-22 — caught before dispatch, by the plan author

**Defect 1 — the monkeypatch target was wrong, and every test in Tasks 4 and 5
would have built real clients.** The first draft patched
`eval.run_repeats.make_pass_clients`. But `run_baseline` imports
`make_pass_clients` into its **own** module namespace and calls it there, so
that patch reaches the config block in `run_repeats` and **nothing that any
repeat actually runs**. Nine occurrences. Every affected test would have either
hit a live provider or died on the response-less-`fake` refusal — and the
failure would have looked like a product bug rather than a plan bug.

Fixed by routing both calls through the `eval.run_baseline` module
(`import eval.run_baseline as _baseline`) so **one** seam governs both, and by
moving the tests onto `eval.run_baseline.make_pass_clients`, which is the target
`tests/test_run_baseline.py` already uses and has proven.

Found by checking the plan's symbols against the tree instead of against the
draft — the pre-flight ADR-0045 decision 1 makes mandatory. It is also review
standard 19 in miniature: two bindings that must agree.

### 2026-08-22 — caught during Task 1, by its implementer

**Defect 2 — Task 1's test block imported `pathlib.Path` and never used it.**
An `F401`, and `python -m ruff check .` is one of the five blocking gates and is
green on `main` — so transcribing the block verbatim would have put the
repository's only lint error in this milestone's first commit. The implementer
removed the import instead of transcribing it and said so, which is the
behaviour this workflow exists to produce.

**Defect 3 — and the same slip left `Path` undefined in Task 4.** Task 4's tests
call `Path(rel).is_absolute()` but its import block never declared `Path`; with
Task 1's dead import correctly removed, Task 4 would have failed on `NameError`.
Predicted by Task 1's implementer from its own finding, then confirmed against
the brief. **Fixed above:** `from pathlib import Path` now appears in Task 4's
import block, where it is first used, with a note saying why.

Both are the same root cause — an import written where it looked tidy rather
than where it is used — and neither would have been caught by reading the plan,
only by running it.

**Finding 1 (not a defect, but recorded with its ruling) — the module docstring
advertises a command that exits 0 doing nothing.** Task 1's reviewer found, and
the controller independently confirmed, that at commit `bd593c0`
`python -m eval.run_repeats --run-id probe --repeats 5` **exits 0, prints
nothing and writes nothing**: `eval/__init__.py` makes the module runnable, its
body is two `def`s, and argparse never runs, so unrecognised arguments are
ignored. The docstring also claims "the aggregate this module writes", which
Task 4 lands.

**Ruling: it stands until Task 5, and Task 5's Step 6 retires it.** Deleting the
two lines now and re-adding them four tasks later costs a fix round and produces
a diff that adds and removes the same text; and reaching the failure requires
checking out a mid-branch commit of an unmerged branch and running a module that
does not exist on `main`. The obligation is made checkable rather than promised:
Task 5 Step 6 runs the advertised command and reads the docstring claim by
claim, deleting anything still untrue. **If Task 5 does not land, these lines
are deleted before the branch merges** — that is the condition, not a
preference. **Cost if wrong:** a merged branch whose module docstring advertises
a command that does not work, guarded by Task 5's step and by the final
whole-branch review.

### 2026-08-22 — caught during Task 2, by its implementer

**Defect 4 — Task 2's `config_identity` tests could not tell the triage tier
from rung 0, and the assertion could not fail.** Both of the brief's
`config_identity` tests passed the *same* client object as `triage` and as
`extract_rungs[0]`, so `config["triage"]` was asserted against a value
indistinguishable from rung one's. **Reproduced by the controller on the
committed tree:** replacing `rung_identity(tiers.triage)` with
`rung_identity(tiers.extract_rungs[0])` still parses, and **nine of the ten
tests stay green** — only the test the implementer added catches it. Recording
rung one as the triage tier would have shipped with every gate green. This is
the "test that cannot fail" class this repository has shipped three of before.
Closed by the implementer with one test using distinct triage and rung clients,
proven red under exactly that mutation. No production change was needed.

**Defect 5 — the brief's `_Settings` docstring said "The four settings the
config block reads"; it reads two.** A count in prose that quantifies over the
thing beside it, wrong at the moment of writing. Corrected by the implementer to
"two".

**Defect 6 — Task 2's Interfaces block and its code block disagreed about an
annotation.** The Interfaces line declared `config_identity(tiers: PassClients,
…)` while the code block shipped `tiers: Any`. The plan's own self-review checked
symbol *names* for consistency and never checked *annotations*.
**Ruling: the plan was corrected to match the shipped code, not the reverse.**
`config_identity` needs only `.triage` and `.extract_rungs`, so `Any` is
uninformative rather than wrong; and tightening it would buy nothing today
because **mypy is a declared dependency and configured in `[tool.mypy]` but is
invoked by no gate** — verified, and both `scripts/verify.py` and
`.github/workflows/ci.yml` carry notes that an earlier version listed it and no
longer does. Tightening to `PassClients` is recorded as a deferred minor for the
final review. **Cost if wrong:** an annotation no checker reads is less
informative than it could be.

**Non-defects, verified rather than assumed while writing:** `PassClients` has
exactly `triage` and `extract_rungs`; all eleven `FieldBreakdown` fields default
to `0`; `Settings.default_currency` and `Settings.vlm_timeout_s` both resolve;
`_report_to_dict` is importable from `eval.harness` and returns a `metrics` key;
`EvalReport.failures` is `list[tuple[str, str]]`; `FakeVLMClient` carries
`model_id` and **not** `use_tools`, which is why Task 2 exists in the shape it
does.
