"""Global-constraint guard: the handoff pair's freshness check still detects staleness.

``docs/MEMORY.md``'s stamp hands the next session a command instead of a claim, and
``docs/NEXT_SESSION_PROMPT.md`` carries the same command as a template. It is the
only thing that tells a reader the pair has fallen behind the tree. Nothing ran it,
so nothing noticed when it stopped working -- and it had:

* until ADR-0021's 2026-08-02 correction it filtered to ``src tests frontend`` and
  was blind to docs-only commits;
* until that ADR's 2026-08-13 correction it filtered to ``src tests frontend docs``
  and was blind to ``scripts/``-only commits. Measured on ``b4a9c23``, which changed
  ``scripts/verify.py`` and nothing else: the command came back empty, so a stamp
  written on top of it would have tested clean.

Both were found by reading the command, years of sessions apart in intent and two
weeks apart in fact. This module runs it instead.

What is gated, and what is not
------------------------------
**Gated: the command still has both of its properties.** It must list a commit that
is not the pair, and must not list a commit that is only the pair. A check that lost
the first property reports "clean" for a tree that moved; one that lost the second
false-alarms on the very commit that refreshes the pair, which is ADR-0033's finding.

**Not gated: whether the pair is fresh right now.** That is state, not mechanism. The
stamp legitimately trails the tree for the whole of a working session -- and
``scripts/verify.py`` runs mid-session, and CI runs it on every push (ADR-0037) -- so
asserting freshness here would be red through ordinary work and learned as noise. The
pair being stale stays a thing a human reads; the command still working is a gate.

Why the pathspec is extracted rather than written here
------------------------------------------------------
A copy of the command in this file would be a second definition, green while the
document it certifies rots -- the failure ADR-0037 names for gate lists and ADR-0032
§2 for claims. So the tests parse the live command out of the tracked pair and
exercise *that*. Edit the stamp into a form that does not work and these go red.

Why a synthetic repository and not this one's history
-----------------------------------------------------
The two properties need a commit of each shape to judge. Naming real ones would pin
the tests to SHAs that ``git gc``, a replay or a rebase can sever -- ADR-0042, whose
guard is the neighbouring module -- and the controls would rot as history grows. Each
run builds a throwaway repository containing one commit of each shape instead, so the
evidence is constructed rather than remembered.

Why every case runs from a subdirectory too
-------------------------------------------
``:(top,`` is load-bearing and easy to drop when retyping. Measured 2026-08-13, the
two shorter spellings are each silently wrong from a subdirectory, in opposite
directions: ``-- . ":(exclude)…"`` stops listing a non-pair commit, and
``-- ":(exclude)…"`` starts listing a pair-only one, because a relative exclude
resolves against the working directory. A stale-check that answers "clean" from the
wrong directory is the same false signal in a new place, so both properties are
asserted from the root and from a subdirectory that does not contain the change.

Scope: the two files of the pair. ADR-0021 quotes both superseded spellings on
purpose, as the record of what was fixed; those are history and are not scanned.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The handoff pair, by ADR-0019. Not a list that can fall behind the repository:
#: these are the two paths the check itself names, and the check is what is scanned.
PAIR = ("docs/MEMORY.md", "docs/NEXT_SESSION_PROMPT.md")

#: The form ADR-0021's 2026-08-13 correction settled on: no inclusion paths at all,
#: and the pair excluded top-anchored so the command means the same from anywhere.
EXPECTED_PATHSPEC = tuple(f":(top,exclude){path}" for path in PAIR)

#: A subdirectory of the synthetic repository that contains none of the changes, so
#: running there is a real test of anchoring rather than a coincidence.
ELSEWHERE = "frontend"


def _git_failed(command: str, result: subprocess.CompletedProcess[str]) -> str:
    """Message for a git call that did not exit zero."""
    stderr = result.stderr.strip() or "(git wrote nothing to stderr)"
    return (
        f"{command} exited {result.returncode}, so this module checked nothing. That "
        "is an environment failure, not a freshness-check defect: a missing git, a bad "
        "working directory, or an unconfigured safe.directory all land here. git said:\n"
        f"{stderr}"
    )


def _git(*args: str, cwd: Path) -> str:
    """Run git in ``cwd`` and return stdout, raising on a non-zero exit.

    Silence is the answer this module reads as "nothing listed", and a failed git
    produces silence. Left unraised it would arrive at the assertions wearing the
    costume of a passing exclusion check -- the wrong-reason pass that
    ``test_sha_citations`` documents the same guard against.
    """
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(_git_failed("git " + " ".join(args), result))
    return result.stdout


def _live_command_lines() -> list[tuple[str, int, str]]:
    """Every runnable copy of the freshness command in the pair.

    A copy is a line that *starts* a ``git log`` invocation and names both pair
    paths. Prose mentioning the files does not start with ``git log``, and the
    neighbouring commands in the same block (``refs/remotes/origin/main..main`` and
    friends) do not name them.
    """
    found: list[tuple[str, int, str]] = []
    for rel in PAIR:
        body = (REPO_ROOT / rel).read_text(encoding="utf-8")
        for lineno, line in enumerate(body.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("git log") and all(path in stripped for path in PAIR):
                found.append((rel, lineno, stripped))
    return found


def _pathspec(command: str) -> list[str]:
    """The pathspec arguments of a ``git log`` command: everything after ``--``."""
    words = shlex.split(command)
    if "--" not in words:
        return []
    return words[words.index("--") + 1 :]


def _live_pathspecs() -> list[tuple[str, list[str]]]:
    """``(where, pathspec)`` for each live copy, failing rather than returning empty.

    An empty list here would make every loop below a no-op and the module a green
    certificate for a document it never read.
    """
    lines = _live_command_lines()
    if not lines:
        pytest.fail(
            "no freshness command found in "
            + " or ".join(PAIR)
            + ". Either the stamp lost its command -- the pair is then handing the "
            "next session a claim instead of a test, which ADR-0021 decision 2 "
            "forbids -- or the command was reformatted so this module stopped "
            "finding it. Both are defects; neither is a pass."
        )
    return [(f"{rel}:{lineno}", _pathspec(command)) for rel, lineno, command in lines]


@pytest.fixture(scope="module")
def synthetic() -> dict[str, object]:
    """A throwaway repository holding one commit of each shape the check must judge.

    Built per run rather than named by SHA so the controls cannot be severed by a
    replay or rot as history grows -- see the module docstring.
    """
    import tempfile

    with tempfile.TemporaryDirectory(prefix="freshness-gate-") as raw:
        root = Path(raw).resolve()
        _git("init", "-b", "main", cwd=root)
        _git("config", "user.email", "gate@example.invalid", cwd=root)
        _git("config", "user.name", "freshness gate", cwd=root)
        _git("config", "commit.gpgsign", "false", cwd=root)

        for rel in (*PAIR, "scripts/verify.py", f"{ELSEWHERE}/app.ts"):
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("base\n", encoding="utf-8")
        _git("add", "-A", cwd=root)
        _git("commit", "-m", "base", cwd=root)
        base = _git("rev-parse", "HEAD", cwd=root).strip()

        # A commit touching a path the old enumerating pathspec did not watch. This
        # is the shape that was invisible until ADR-0021's 2026-08-13 correction.
        (root / "scripts" / "verify.py").write_text("changed\n", encoding="utf-8")
        _git("add", "-A", cwd=root)
        _git("commit", "-m", "touch scripts only", cwd=root)
        not_the_pair = _git("rev-parse", "HEAD", cwd=root).strip()

        # A commit touching only the pair: the refresh commit, which must stay
        # invisible or it false-alarms on itself (ADR-0033 section 1).
        for rel in PAIR:
            (root / rel).write_text("refreshed\n", encoding="utf-8")
        _git("add", "-A", cwd=root)
        _git("commit", "-m", "refresh the pair", cwd=root)
        pair_only = _git("rev-parse", "HEAD", cwd=root).strip()

        yield {
            "root": root,
            "detects": f"{base}..{not_the_pair}",
            "ignores": f"{not_the_pair}..{pair_only}",
        }


def _run_check(synthetic: dict[str, object], pathspec: list[str], *, span: str,
               run_from: str) -> str:
    """Run the extracted pathspec over ``span`` of the synthetic repository."""
    root = synthetic["root"]
    assert isinstance(root, Path)
    where = root if run_from == "." else root / run_from
    return _git("log", "--oneline", str(synthetic[span]), "--", *pathspec, cwd=where).strip()


@pytest.mark.parametrize("run_from", [".", ELSEWHERE])
def test_the_check_lists_a_commit_that_is_not_the_pair(synthetic, run_from) -> None:
    """The detection half: a tree that moved must not read as clean.

    Losing this is the defect the check has now had twice -- a pathspec that names
    what it watches goes blind to whatever is not on the list.
    """
    for where, pathspec in _live_pathspecs():
        listed = _run_check(synthetic, pathspec, span="detects", run_from=run_from)
        assert listed, (
            f"the freshness command at {where}, run from {run_from!r}, did not list a "
            "commit that changed scripts/verify.py and nothing else. It reports a moved "
            "tree as current, which is the whole failure it exists to prevent. Its "
            f"pathspec is {pathspec}; ADR-0021's 2026-08-13 correction requires "
            f"{list(EXPECTED_PATHSPEC)}."
        )


@pytest.mark.parametrize("run_from", [".", ELSEWHERE])
def test_the_check_ignores_a_commit_that_is_only_the_pair(synthetic, run_from) -> None:
    """The exclusion half: the refresh commit must not trip its own check.

    A stamp cannot name the commit that writes it (ADR-0021 decision 2), so a
    pair-only commit listing here means every refresh reports itself stale --
    ADR-0033's finding, which cost three repair commits in one session.
    """
    for where, pathspec in _live_pathspecs():
        listed = _run_check(synthetic, pathspec, span="ignores", run_from=run_from)
        assert not listed, (
            f"the freshness command at {where}, run from {run_from!r}, listed a commit "
            f"that touched only {' and '.join(PAIR)}:\n{listed}\nThe refresh commit "
            "would report the pair it just wrote as stale. Its pathspec is "
            f"{pathspec}; a relative ``:(exclude)`` resolves against the working "
            "directory, which is why ADR-0021 requires the ``:(top,`` prefix."
        )


def test_every_live_copy_of_the_check_is_the_top_anchored_form() -> None:
    """The form, checked directly, so a wrong one is named rather than merely observed.

    The behavioural tests above would catch most breakages, but this says which
    document is wrong and what it should read -- and it catches a copy that drifts
    from its sibling while both still happen to work.
    """
    wrong = [
        f"  {where}\n      has:  {pathspec}\n      want: {list(EXPECTED_PATHSPEC)}"
        for where, pathspec in _live_pathspecs()
        if tuple(pathspec) != EXPECTED_PATHSPEC
    ]
    assert not wrong, (
        "the freshness command is not the form ADR-0021's 2026-08-13 correction "
        "settled on:\n" + "\n".join(wrong) + "\nNo inclusion paths -- every tracked "
        "path is watched because none is listed -- and the pair excluded "
        "top-anchored so the command means the same from any directory."
    )
