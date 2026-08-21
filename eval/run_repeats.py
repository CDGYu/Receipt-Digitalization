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

import statistics
from pathlib import Path
from typing import Any

__all__ = [
    "config_identity",
    "prepare_run_dir",
    "repeat_dir",
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

    **Keys are derived from the inputs**, so a metric added to
    ``_report_to_dict`` later is included without anybody deciding. The key set
    is the union over every input dict -- the shape ``field_accuracy`` already
    takes with ``pred.keys() | tru.keys()``, and for the same reason: a key
    only one side reported must not vanish.

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
