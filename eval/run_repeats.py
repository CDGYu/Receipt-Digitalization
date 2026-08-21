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
from typing import Any

__all__ = [
    "config_identity",
    "prepare_run_dir",
    "repeat_dir",
    "rung_identity",
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
