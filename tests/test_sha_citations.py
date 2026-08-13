"""Global-constraint guard: a commit this repository cites must stay reachable.

Documents here anchor their measurements to a commit -- *"derived at ``e698aca``"*,
*"probed at ``e698aca``, not recalled"*. That example names a real, reachable
commit deliberately: the rule below means a docstring cannot show the citation
form without instantiating it, so the only safe illustration is one that
resolves. ADR-0032 decision 3 called that kind of
anchor "true forever". It is not. On 2026-08-12 a branch was replayed onto
``main`` rather than merged, and nine citations in three tracked files were left
naming commits that no ref can reach. The claims stayed true; they stopped being
checkable, and after ``git gc`` the tokens name nothing at all. ADR-0042 is the
decision this guard enforces.

Why reachability and not existence
----------------------------------
``git cat-file -e`` succeeds on an orphaned commit until it is pruned, so an
existence check would have been green through the entire defect and would first
go red on whatever day somebody ran ``git gc``. The property is reachability.

Why any ref and not ``main``
----------------------------
An ADR records the tree it was derived from and is committed *before* the merge,
so it legitimately cites a commit that is on the branch and not yet on ``main``.
CI fires on every push (ADR-0037), so a ``main``-anchored rule would fail every
branch that documents its own work. Reachable-from-any-ref passes there and
still catches a replay, which orphans commits from *every* ref.

Why exactly seven hex characters
--------------------------------
Two measurements over the tracked non-binary files at ``e698aca``, each stated
with the query that produced it, so a later reader can re-run it instead of
trusting it.

*Nothing this pattern matches is a false positive* -- the direction the rule
actually rests on. Query ``_SHA_PATTERN`` itself, a backticked
``[0-9a-f]{7}``: 112 distinct tokens, and all 112 resolve to a commit object.
None needs excluding, which is what makes this a property rather than an
enumerated defence (review standard 19).

*Nothing genuine is written at another length* -- a separate and weaker claim,
true of this tree on that day rather than by construction. Backticked
``[0-9a-f]{4,6}``: 18 distinct tokens, none a commit. Backticked
``[0-9a-f]{8,40}``: 6 distinct tokens, none a commit -- a date, three
tabular-figure digit samples, a 20-digit PAN-masking example, an Alembic
revision id. Widen the query to backticked hex of *any* length and 49 of 161
distinct tokens are not commits, 43 of those 49 being one to five characters --
ADR numbers, HTTP status codes, round figures. A count quoted here without its
query would therefore mean very little.

The one silent-drift path -- ``core.abbrev`` is auto and git widens it as the
object count grows -- is pinned by
``test_git_still_abbreviates_to_seven_characters``.

A consequence worth knowing before editing any document about a dead commit: the
seven-character backticked form IS the citation, so a document discussing an
unreachable commit must name it bare or at full oid length. A sentence cannot
show an example of the form without instantiating it.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: A citation as this repository writes one: a backticked seven-character hex
#: token. Anchored deliberately at seven -- see the module docstring.
_SHA_PATTERN = re.compile(r"`([0-9a-f]{7})`")

#: Binary and generated files carry hex that is not a citation.
_SKIP_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
    ".pdf", ".woff", ".woff2", ".lock",
)


def _git_failed(command: str, result: subprocess.CompletedProcess[str]) -> str:
    """Message for a git call that did not exit zero."""
    stderr = result.stderr.strip() or "(git wrote nothing to stderr)"
    return (
        f"{command} exited {result.returncode}, so this module checked nothing. "
        "That is an environment failure, not a citation defect: a missing git, a "
        "bad working directory, or an unconfigured safe.directory all land here. "
        f"git said:\n{stderr}"
    )


def _git(*args: str) -> str:
    """Run git at the repository root and return stdout.

    A non-zero exit raises rather than returning empty output. Silence here
    reaches the assertions wearing the costume of a citation defect: if
    ``ls-files`` fails, the vacuity check reports "no citations found at all"
    and blames this module's pattern; if ``rev-list`` fails, every citation in
    the tree reports as unreachable. Both are the wrong-reason failure the
    module exists to avoid, and git's "detected dubious ownership" (exit 128,
    empty stdout) is a common way to reach them.
    """
    result = subprocess.run(
        ["git", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(_git_failed("git " + " ".join(args), result))
    return result.stdout


def _tracked_text_files() -> list[Path]:
    return [
        REPO_ROOT / line
        for line in _git("ls-files").splitlines()
        if line and not line.lower().endswith(_SKIP_SUFFIXES)
    ]


def _citations() -> dict[str, list[str]]:
    """Map each cited seven-hex token to the ``path:line`` places citing it."""
    found: dict[str, list[str]] = {}
    for path in _tracked_text_files():
        try:
            body = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        for lineno, line in enumerate(body.splitlines(), 1):
            for token in _SHA_PATTERN.findall(line):
                found.setdefault(token, []).append(f"{rel}:{lineno}")
    return found


def _resolve(tokens: list[str]) -> dict[str, str]:
    """Resolve abbreviations to full oids in one git call.

    Returns ``{token: oid}`` for tokens that name a commit, and ``{token: ""}``
    for anything git reports as ``missing`` or ``ambiguous``.
    """
    if not tokens:
        return {}
    proc = subprocess.run(
        ["git", "cat-file", "--batch-check=%(objectname) %(objecttype)"],
        cwd=str(REPO_ROOT),
        input="\n".join(tokens) + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(_git_failed("git cat-file --batch-check", proc))
    lines = proc.stdout.splitlines()
    if len(lines) != len(tokens):
        raise AssertionError(
            f"git cat-file answered {len(lines)} line(s) for {len(tokens)} token(s); "
            "the batch-check contract changed and this helper cannot pair them up"
        )
    resolved: dict[str, str] = {}
    for token, line in zip(tokens, lines, strict=True):
        parts = line.split()
        resolved[token] = parts[0] if len(parts) == 2 and parts[1] == "commit" else ""
    return resolved


def test_the_repository_history_is_not_shallow() -> None:
    """A shallow clone cannot answer this file's question, so it must not pass.

    ``actions/checkout`` defaults to ``fetch-depth: 1``. Under that, every cited
    commit resolves as missing and this module would either fail for the wrong
    reason or -- worse -- be made to skip, which reads as coverage it does not
    have. It fails loudly and names the fix instead.
    """
    shallow = _git("rev-parse", "--is-shallow-repository").strip()
    assert shallow == "false", (
        "the repository history is shallow, so cited commits cannot be resolved. "
        "Set `fetch-depth: 0` on the checkout step; see ADR-0042."
    )


def test_git_still_abbreviates_to_seven_characters() -> None:
    """Pin the assumption the citation pattern rests on.

    ``core.abbrev`` is unset, so git chooses a width from the object count and
    widens it as the repository grows. On the day it reaches eight, new
    citations stop matching ``_SHA_PATTERN`` and this guard silently checks
    less. This makes that day loud.
    """
    short = _git("rev-parse", "--short", "HEAD").strip()
    assert len(short) == 7, (
        f"git now abbreviates to {len(short)} characters ({short!r}), so the "
        "seven-character citation pattern no longer matches newly written "
        "citations. Widen the pattern and re-derive the false-positive "
        "measurement in this module's docstring."
    )


def test_every_cited_commit_is_reachable_from_a_ref() -> None:
    """The property: a cited commit is reachable, not merely present.

    An unreachable commit is one ``git gc`` away from naming nothing, and a
    reader cannot check the claim built on it today.
    """
    citations = _citations()
    if not citations:
        pytest.fail(
            "no citations found at all, which means the pattern stopped "
            "matching rather than that the tree is clean"
        )

    reachable = set(_git("rev-list", "--all").split())
    resolved = _resolve(sorted(citations))

    broken: list[str] = []
    for token in sorted(citations):
        oid = resolved[token]
        if not oid:
            reason = "does not name a commit"
        elif oid not in reachable:
            reason = f"names {oid[:12]}, which no ref can reach"
        else:
            continue
        broken.append(
            f"  `{token}` {reason}\n"
            + "".join(f"      {place}\n" for place in citations[token])
        )

    assert not broken, (
        f"{len(broken)} cited commit(s) cannot be reached from any ref:\n"
        + "".join(broken)
        + "\nA replay, rebase, amend or force-push severs a citation without "
        "touching the citing document. Remap each to the live commit (compare "
        "patches, not subjects) or remove the anchor. See ADR-0042."
    )
