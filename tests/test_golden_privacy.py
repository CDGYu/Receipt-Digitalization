"""A golden label is fully public or fully private, never partly redacted.

The 2026-08-22 growing-the-golden-set design, section 3, measures why
field-level redaction is out: nulling a PII field in the truth moves its path
into the *absent* classes, so a model that reads the real value off the image is
scored as having hallucinated it. The unit of redaction is therefore the whole
receipt, and privacy is carried by the filename.

That measurement was re-derived 2026-08-22 before this module was written, with
``eval/golden/labels/r001.json`` as the truth and a prediction identical to it:
intact, ``transcription 28/28 hallucinated=0``; with ``merchant.name`` nulled in
the truth alone, ``27/27 hallucinated=1``. It is pinned below, because the
design's section 7.4 asks for it and because it is the *reason* the convention
has this shape: a change that quietly reversed it would leave everything else in
this module guarding a rule nobody needed any more.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from eval.golden_set import _is_label_file
from eval.metrics import field_breakdown
from receipts.extract.schema import ReceiptExtraction

REPO = Path(__file__).resolve().parents[1]

#: The one directory this convention governs, named once so a test cannot drift
#: from the path it claims to be checking.
LABELS_DIR = "eval/golden/labels"

#: Private ids the rule has to cover. They differ in the digit immediately after
#: the ``p``, so no rule of the form ``p<literal>*`` can satisfy all three: it
#: fixes that digit and misses two of them. Measured 2026-08-22,
#: ``eval/golden/labels/p0*.json`` ignores ``p001`` and the ``p042`` this tuple
#: replaced, while leaving every id from ``p100`` up committable -- and the
#: README targets 50-100 receipts, so ``p100`` is an id someone reaches rather
#: than a hypothetical. (A character class such as ``p[0-9]*`` does satisfy all
#: three; for numeric ids that is the same rule, and the narrowing that actually
#: gets written is a literal prefix.)
PRIVATE_SAMPLES = ("p001.json", "p100.json", "p900.json")


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


def _ignore_source(relative: str) -> str | None:
    """The ignore *file* whose rule covers ``relative``, or ``None`` if none does.

    Asks git, never the file text.

    ``--no-index`` is load-bearing. Without it ``git check-ignore`` consults the
    index first and will not call a *tracked* path ignored, so the blanket
    mistake this module exists to catch -- ``eval/golden/labels/*.json``, which
    silently swallows every public label added from now on -- leaves every
    assertion below green. Measured 2026-08-22 under that blanket pattern: the
    tracked ``r001.json`` reported not-ignored, the untracked ``p001.json``
    reported ignored. The question the convention asks is what the rules say
    about a *name*, and that is the question ``--no-index`` answers.

    The *source* is returned rather than a bool because an exit code cannot tell
    a shared convention from a local one. Measured 2026-08-22 with the rule in
    ``.git/info/exclude`` and nothing in ``.gitignore``: all five tests green,
    on a convention that reaches no clone and no reviewer.

    Exit 0 means ignored and 1 means not ignored; anything else is git failing
    (128: no repository, a bad ``safe.directory``, no git at all) and is raised
    rather than read as "not ignored", which is the *passing* direction for
    :func:`test_a_public_label_is_not_ignored`.
    """
    result = _git("check-ignore", "--no-index", "-v", relative)
    if result.returncode not in (0, 1):
        raise RuntimeError(
            f"git check-ignore failed ({result.returncode}) on {relative}: "
            f"{result.stderr.strip()}"
        )
    if result.returncode == 1:
        return None
    # -v prints "<source>:<line>:<pattern>\t<pathname>". Splitting the tab off
    # first and then from the right keeps a Windows drive letter in <source>.
    described = result.stdout.strip().split("\t", 1)[0]
    fields = described.rsplit(":", 2)
    return fields[0] if len(fields) == 3 else described


def _tracked_labels() -> list[str]:
    """Every path git has in the index under the labels directory.

    Raises on a failed git *and* on a successful-but-empty answer. Both are the
    shape a broken instrument produces, and both are also what makes
    :func:`test_no_private_label_is_committed` pass: ``git ls-files`` exits 0
    with no output when its path is missing or renamed. A tripwire that goes
    green when its instrument is broken is not a tripwire.
    """
    result = _git("ls-files", LABELS_DIR)
    if result.returncode != 0:
        raise RuntimeError(
            f"git ls-files failed ({result.returncode}): {result.stderr.strip()}"
        )
    paths = result.stdout.split()
    if not paths:
        raise RuntimeError(
            f"git ls-files listed nothing under {LABELS_DIR}: the directory is "
            "missing, renamed or untracked. 'Nothing there' is also what a "
            "clean leak check looks like, so it is raised rather than passed."
        )
    return paths


def test_a_private_label_is_ignored_by_git():
    for name in PRIVATE_SAMPLES:
        assert _ignore_source(f"{LABELS_DIR}/{name}") == ".gitignore", (
            f"{name} must be ignored by a rule in the tracked .gitignore -- it "
            "carries a real merchant's name, address and tax id, and a rule "
            "kept anywhere else protects this clone only"
        )


def test_a_public_label_is_not_ignored():
    """The complement, so the rule is a rule and not a blanket.

    ``r004.json`` is the next public label anyone adds, and naming one that does
    not exist yet keeps the assertion about the *rule*: a blanket ignore does
    its damage to the labels still to come, not to the three already committed.

    ``frontend/package.json`` is the other axis a too-wide rule opens. A bare
    ``p*.json``, written without the directory in front of it, matches at every
    level of the tree -- measured 2026-08-22, it covers both tracked frontend
    manifests while leaving all five of these tests green.
    """
    assert _ignore_source(f"{LABELS_DIR}/r001.json") is None
    assert _ignore_source(f"{LABELS_DIR}/r004.json") is None, (
        "the next public label must land in git; an ignore rule wide enough to "
        "cover it destroys the public set one receipt at a time"
    )
    assert _ignore_source("frontend/package.json") is None, (
        "the rule must be anchored to the labels directory; an unanchored "
        "pattern matches at every level and reaches files it never named"
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
        assert f"{LABELS_DIR}/{stem}.json" in tracked


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


def test_nulling_a_pii_field_in_the_truth_scores_a_correct_read_as_invented():
    """The measurement that rules out field-level redaction, pinned.

    ADR-0040 reads *filled* from the truth side only, so nulling a PII field
    there does not merely drop it from the denominator -- it moves the path into
    the absent classes, where a prediction that fills it is **hallucinated**. A
    model that read the real merchant name off the image would be scored as
    inventing it, and a public CI run would report hallucinations that never
    happened. That is why a label is committed whole or not at all.

    Asserted as three deltas rather than as absolute counts, so re-labelling
    ``r001`` cannot rot it (review standard 5): one path leaves
    ``transcription_total``, one leaves ``core_total``, and exactly one arrives
    in ``hallucinated``. The prediction is byte-identical to the intact truth in
    both halves, so the only thing that differs between them is the truth.

    Goes red if ``eval/metrics.py``'s ``_is_filled`` learns to treat a ``None``
    truth path as absent-by-declaration rather than as empty, or if
    ``field_breakdown`` stops counting a filled prediction over an empty truth
    as ``hallucinated`` -- which is the change someone makes while reintroducing
    field-level redaction believing it only shrinks a denominator.
    """
    raw = (REPO / LABELS_DIR / "r001.json").read_text(encoding="utf-8")
    predicted = ReceiptExtraction.model_validate_json(raw)
    intact = field_breakdown(predicted, ReceiptExtraction.model_validate_json(raw))

    # The precondition. Without it every delta below is satisfied by a truth
    # that was already scoring hallucinations, and the test pins nothing.
    assert intact.hallucinated == 0, (
        f"a prediction identical to the truth must invent nothing, got {intact.hallucinated}"
    )

    nulled = json.loads(raw)
    assert nulled["merchant"]["name"] is not None, "fixture: the name must start filled"
    nulled["merchant"]["name"] = None
    redacted = field_breakdown(predicted, ReceiptExtraction.model_validate(nulled))

    assert redacted.hallucinated == intact.hallucinated + 1, (
        "nulling one PII field in the truth alone must make a correct read of it "
        "score as invented -- this is why redaction is per receipt, not per field"
    )
    assert redacted.transcription_total == intact.transcription_total - 1
    assert redacted.core_total == intact.core_total - 1
