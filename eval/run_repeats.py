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

import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import eval.run_baseline as _baseline
from config.settings import get_settings
from eval.harness import DEFAULT_RESULTS_DIR, _report_to_dict

__all__ = [
    "config_identity",
    "prepare_run_dir",
    "repeat_dir",
    "run_repeats",
    "rung_identity",
    "spread_over",
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

    **Keys are derived from the inputs**, never enumerated here. The key set
    is the union over every input dict -- the shape ``field_accuracy`` already
    takes with ``pred.keys() | tru.keys()``, and for the same reason: a key
    only one side reported must not vanish. A key in that union is reported
    when some repeat gave it a number, or when every repeat gave it ``None``,
    and only then.

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
        observed = [v for v in raw if _numeric(v)]
        if not observed and not all(v is None for v in raw):
            # Nothing numeric, and not every value null: not a distribution at
            # all, so the key is dropped. An all-null metric is the *other*
            # case and is reported -- with null figures, never with zeroes.
            continue
        out[key] = {
            "min": min(observed) if observed else None,
            "max": max(observed) if observed else None,
            "median": statistics.median_low(observed) if observed else None,
            "n": len(observed),
            "n_null": sum(1 for v in raw if v is None),
            "values": raw,
        }
    return out


def _report_metrics(report: Any) -> dict[str, Any]:
    """The numeric surface of one report, derived from the report itself.

    Reads the same dictionary the results file is built from, so no list of
    metric names lives here. What reaches the spread is ``spread_over``'s rule,
    not this function's.
    """
    return dict(_report_to_dict(report).get("metrics", {}))


def _report_counts(report: Any) -> dict[str, Any]:
    """The count block of one report, on ``_report_metrics``'s rule.

    The keys are ``_report_to_dict``'s, read from it rather than re-listed
    here, so this block and the file each repeat writes cannot fall out of step,
    and no list of key names -- and no count of them -- lives here to age.
    """
    return dict(_report_to_dict(report).get("counts", {}))


#: How many times the rewrite tries the atomic route before giving up on it.
#: The holders that refuse a rename on Windows -- a scanner reading the file
#: just written, an indexer, an editor -- let go in milliseconds, so a couple of
#: retries converts most of them into a normal atomic write; a run that waits
#: longer than that is paying for durability with time it does not have.
_RENAME_ATTEMPTS = 3

#: Seconds before the second attempt; the third waits twice this.
_RENAME_BACKOFF_S = 0.05


def _rewrite_aggregate(run_dir: Path, payload: str) -> None:
    """Put ``payload`` in ``<run_dir>/aggregate.json``, atomically where it can.

    The file is written beside its destination and renamed over it, so a reader
    sees the previous aggregate or the new one and never a half-written file --
    ``write_text`` truncates before it writes, and this rewrite happens once per
    repeat rather than once per run.

    **The atomicity is the bonus and must never be the cost.** ``Path.replace``
    onto a destination another handle holds open raises ``PermissionError`` on
    Windows -- measured on this machine, from nothing more than a reader with
    the file open -- while ``write_text`` onto that same destination, under that
    same handle, succeeds. Raised out of the loop that failure would abort the
    run *and* burn the run id, which :func:`prepare_run_dir` refuses to reuse,
    for the sake of a window a kill has to land inside. So a rename that will
    not go through degrades to writing in place, and **no path here raises**.

    The staging file does not survive either path. A process killed between the
    staging write and the rename can leave one, and a killed process cleans
    nothing up in any design; what it does leave behind is a destination that
    still parses.
    """
    target = run_dir / "aggregate.json"
    pending = run_dir / "aggregate.json.tmp"
    try:
        pending.write_text(payload, encoding="utf-8")
        for attempt in range(1, _RENAME_ATTEMPTS + 1):
            try:
                pending.replace(target)
                return
            except OSError as exc:
                if attempt == _RENAME_ATTEMPTS:
                    print(
                        f"Could not rename {pending.name} over {target.name} "
                        f"({type(exc).__name__}: {exc}). Writing the aggregate "
                        f"in place instead, which is not atomic.",
                        file=sys.stderr,
                    )
                    break
                time.sleep(_RENAME_BACKOFF_S * attempt)
        target.write_text(payload, encoding="utf-8")
    except OSError as exc:
        # Not a raise: every completed repeat's own results file is already on
        # disk and the remaining repeats are still worth running. The aggregate
        # is the thing that degraded, and saying so is what keeps that from
        # being a silent drop.
        print(
            f"Could not write {target} ({type(exc).__name__}: {exc}). This "
            f"run's aggregate is missing or stale; each repeat's own results "
            f"file is unaffected.",
            file=sys.stderr,
        )

    try:
        pending.unlink(missing_ok=True)
    except OSError as exc:
        print(
            f"Could not remove {pending} ({type(exc).__name__}: {exc}).",
            file=sys.stderr,
        )


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
    aggregate is rewritten after **every** repeat, not once at the end: the
    per-rung counts and five of the config block's six keys are in no results
    file, so a sequence killed part way through would otherwise lose exactly
    what this artifact exists to carry.

    ``n_repeats`` is the number of entries the file actually holds, never the
    number asked for, so the artifact cannot claim a repeat it does not carry.
    ``n_repeats_requested`` is the target; the two disagree exactly when a run
    was interrupted, which is how a reader tells one apart from a complete run
    of the smaller size.

    Both ``make_pass_clients`` and ``run_baseline`` are reached **through the
    ``eval.run_baseline`` module** rather than imported by name here. That is
    load-bearing for the first of them: ``run_baseline`` looks
    ``make_pass_clients`` up in its own module globals, so a name imported into
    *this* module would be a second binding that a
    ``monkeypatch.setattr("eval.run_baseline.make_pass_clients", ...)`` never
    reaches -- the config block below would call the real factory and describe a
    ladder no repeat ran. ``run_baseline`` is reached the same way so there is
    one rule here rather than two.
    """
    if repeats < 1:
        # Before the run directory is created: `prepare_run_dir` refuses an id
        # it has already seen, so claiming one for a run of nothing would burn
        # the id the real run wanted.
        raise ValueError(f"repeats must be at least 1, got {repeats}")

    root = Path(results_root) if results_root is not None else DEFAULT_RESULTS_DIR
    run_dir = prepare_run_dir(root, run_id)
    settings = get_settings()
    # For the config block only. `run_baseline` builds its own clients on every
    # call, and must: its one client parameter is `client=`, whose branch is
    # deliberately a single rung serving every pass
    # (tests/test_run_baseline.py::test_an_injected_client_gets_no_ladder), so
    # feeding these forward would disable the ladder silently.
    tiers = _baseline.make_pass_clients(settings)

    config = config_identity(tiers, settings)
    entries: list[dict[str, Any]] = []
    aggregate: dict[str, Any] = {}

    for index in range(1, repeats + 1):
        target = repeat_dir(run_dir, index)
        report = _baseline.run_baseline(golden_dir=golden_dir, results_dir=target)
        written = sorted(target.glob("*.json"))
        entries.append({
            "index": index,
            "results_file": (
                written[0].relative_to(run_dir).as_posix() if written else None
            ),
            "counts": _report_counts(report),
            "metrics": _report_metrics(report),
            "extract_rung_counts": report.extract_rung_counts,
            "failures": [list(f) for f in report.failures],
        })

        aggregate = {
            "run_id": run_id,
            "n_repeats": len(entries),
            "n_repeats_requested": repeats,
            "config": config,
            "repeats": entries,
            "spread": spread_over([e["metrics"] for e in entries]),
        }
        # Serialized here and persisted there: a value this module cannot
        # encode is a defect in this module and must raise, while a file system
        # that will not take the write is a condition of the machine the run is
        # on and must not cost the run.
        _rewrite_aggregate(run_dir, json.dumps(aggregate, indent=2, default=str))

    return aggregate
