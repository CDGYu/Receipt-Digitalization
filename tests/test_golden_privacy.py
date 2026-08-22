"""A golden label is fully public or fully private, never partly redacted.

The 2026-08-22 growing-the-golden-set design, section 3, measures why
field-level redaction is out: nulling a PII field in the truth moves its path
into the *absent* classes, so a model that reads the real value off the image is
scored as having hallucinated it. The unit of redaction is therefore the whole
receipt, and privacy is carried by the filename.

That measurement was re-derived 2026-08-22 before this module was written, with
``eval/golden/labels/r001.json`` as the truth and a prediction identical to it:
intact, ``transcription 28/28 hallucinated=0``; with ``merchant.name`` nulled in
the truth alone, ``27/27 hallucinated=1``. Nothing here re-runs it -- it is the
reason the convention has this shape, not a property these tests pin.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from eval.golden_set import _is_label_file

REPO = Path(__file__).resolve().parents[1]


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )


def _check_ignore(relative: str) -> bool:
    """True when the ignore rules cover ``relative``. Asks git, never the file text.

    ``--no-index`` is load-bearing. Without it ``git check-ignore`` consults the
    index first and will not call a *tracked* path ignored, so the blanket
    mistake this module exists to catch -- ``eval/golden/labels/*.json``, which
    silently swallows every public label added from now on -- leaves every
    assertion below green. Measured 2026-08-22 under that blanket pattern: the
    tracked ``r001.json`` reported not-ignored, the untracked ``p001.json``
    reported ignored. The question the convention asks is what the rules say
    about a *name*, and that is the question ``--no-index`` answers.

    Exit 0 means ignored and 1 means not ignored; anything else is git failing
    (128: no repository, a bad ``safe.directory``, no git at all) and is raised
    rather than read as "not ignored", which is the *passing* direction for
    :func:`test_a_public_label_is_not_ignored`.
    """
    result = _git("check-ignore", "--no-index", "-q", relative)
    if result.returncode not in (0, 1):
        raise RuntimeError(
            f"git check-ignore failed ({result.returncode}) on {relative}: "
            f"{result.stderr.strip()}"
        )
    return result.returncode == 0


def _tracked_labels() -> list[str]:
    """Every path git has in the index under the labels directory.

    Raises on a failed git instead of returning nothing: an empty list is what a
    broken environment produces, and it is also what makes
    :func:`test_no_private_label_is_committed` pass. A tripwire that goes green
    when its instrument is broken is not a tripwire.
    """
    result = _git("ls-files", "eval/golden/labels")
    if result.returncode != 0:
        raise RuntimeError(
            f"git ls-files failed ({result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout.split()


def test_a_private_label_is_ignored_by_git():
    assert _check_ignore("eval/golden/labels/p001.json"), (
        "a p-prefixed label must be gitignored: it carries a real merchant's "
        "name, address and tax id"
    )
    assert _check_ignore("eval/golden/labels/p042.json"), (
        "the rule covers the p prefix, not one filename -- every private label "
        "yet to be written is the point"
    )


def test_a_public_label_is_not_ignored():
    """The complement, so the rule is a rule and not a blanket.

    ``r004.json`` is the next public label anyone adds, and naming one that does
    not exist yet keeps the assertion about the *rule*: a blanket ignore does
    its damage to the labels still to come, not to the three already committed.
    """
    assert not _check_ignore("eval/golden/labels/r001.json")
    assert not _check_ignore("eval/golden/labels/r004.json"), (
        "the next public label must land in git; an ignore rule wide enough to "
        "cover it destroys the public set one receipt at a time"
    )


def test_the_existing_labels_are_still_tracked():
    """The three public labels are in the index, and must stay there.

    This does *not* guard the blanket-ignore mistake, though its shape invites
    the reading: ``git ls-files`` reports the index, and an ignore rule never
    untracks anything, so under ``eval/golden/labels/*.json`` this test stays
    green (measured 2026-08-22). ``test_a_public_label_is_not_ignored`` is what
    catches that. What this catches is the other repair -- making a leak "go
    away" with ``git rm --cached`` and taking the public set with it.
    """
    tracked = _tracked_labels()
    for stem in ("r001", "r002", "r003"):
        assert f"eval/golden/labels/{stem}.json" in tracked


def test_every_label_reader_accepts_a_private_name():
    """`_is_label_file` is the only filter any reader applies; the other three
    readers glob unfiltered, so accepting here means accepting everywhere."""
    assert _is_label_file(Path("p001.json"))
    assert _is_label_file(Path("r001.json"))
    assert not _is_label_file(Path("TEMPLATE.json"))
    assert not _is_label_file(Path("manifest.json"))


def test_no_private_label_is_committed():
    """The milestone's whole point, asserted over the tracked tree."""
    leaked = [f for f in _tracked_labels() if Path(f).name.startswith("p")]
    assert not leaked, f"private labels committed: {leaked}"
