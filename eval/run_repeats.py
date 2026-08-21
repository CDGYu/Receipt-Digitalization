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
