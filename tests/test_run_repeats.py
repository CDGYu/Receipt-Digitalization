"""The repeat runner: N runs, N directories, one aggregate.

Offline like the rest of the suite. Nothing here touches a provider, a network
or an image; the seam is ``run_baseline``'s injectable client and the
monkeypatchable ``make_pass_clients``.
"""

from __future__ import annotations

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
