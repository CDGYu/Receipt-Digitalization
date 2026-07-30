"""Run every gate a change to this repository has to pass, and name the one that fails.

    python scripts/verify.py

Five gates, in this order:

    pytest      python -m pytest              the offline Python suite
    ruff        python -m ruff check .        lint, line length 100
    typecheck   npm run typecheck             tsc -b
    vitest      npm test                      the component and unit suites
    build       npm run build                 tsc -b && vite build

**Why a script and not a CI workflow.** `.github/workflows/` is untracked in
this repository and GitHub Actions does not run for it, so a committed workflow
would be a gate that never executes -- a false signal, which is worse than no
signal. This script is tracked, so it is the copy that cannot drift out of the
repository, and it runs wherever the person making the change is.

**Why the Node half is not optional.** `npm test` does not type-check.
Measured on this branch: rewriting `SubmitError`'s fields in the
parameter-property form (illegal under `erasableSyntaxOnly`) leaves
`npx vitest run` green on every file while `npm run typecheck` and
`npm run build` both exit 2 on TS1294. Two defects reached a green Vitest run
that way before the pair were added here, so the runner is not evidence about
that class of defect and this list is what makes the other two routine.

**Nothing is skipped silently.** When `npm` is not on PATH each Node gate
prints a `SKIPPED: npm not found` line naming itself, and the Python gates
still decide the exit status -- a clone with no Node installed gets a truthful
verdict on the half it can run, and is told in as many words which half that
was. A gate that quietly disappears is the failure this shape exists to
prevent.

**Every gate runs even after one fails**, because the useful output is the whole
report rather than the first stumble. The exit status is 1 if any gate failed
and 0 otherwise, and the failing names are printed last where they cannot
scroll away.

**Not a gate:** the Playwright acceptance run (`frontend/e2e`). It needs a
browser binary that is not part of a normal install, so it stays an explicit
step -- see `frontend/playwright.config.ts`. A green run of this script says
nothing about it.
"""

from __future__ import annotations

import dataclasses
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import TextIO

REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND = REPO_ROOT / "frontend"

#: Placeholder for ``argv[0]`` of a Node gate, replaced with the resolved npm
#: executable at run time. On Windows ``npm`` is ``npm.cmd``, and these gates run
#: without a shell, so the bare word would not be found even when npm is
#: installed -- ``shutil.which`` is both the presence check and the path.
NPM = "npm"


@dataclasses.dataclass(frozen=True)
class Gate:
    """One command, and where it runs."""

    name: str
    argv: tuple[str, ...]
    cwd: Path
    needs_npm: bool = False


GATES: tuple[Gate, ...] = (
    Gate("pytest", (sys.executable, "-m", "pytest"), REPO_ROOT),
    Gate("ruff", (sys.executable, "-m", "ruff", "check", "."), REPO_ROOT),
    Gate("typecheck", (NPM, "run", "typecheck"), FRONTEND, needs_npm=True),
    Gate("vitest", (NPM, "test"), FRONTEND, needs_npm=True),
    Gate("build", (NPM, "run", "build"), FRONTEND, needs_npm=True),
)

PASS = "PASS"
FAIL = "FAIL"
SKIPPED = "SKIPPED"


def _subprocess_runner(argv: list[str], cwd: Path) -> int:
    """Run a gate and return its exit status, streaming its output as it goes."""
    return subprocess.call(argv, cwd=cwd)


def _shown(argv: Sequence[str]) -> str:
    """A gate's command as one line a human can copy.

    ``sys.executable`` is an absolute path that says nothing useful in a report,
    so it is shown as ``python``. Nothing here is re-parsed, so this is
    presentation only.
    """
    parts = ["python" if part == sys.executable else part for part in argv]
    return " ".join(parts)


def run_gates(
    gates: Iterable[Gate],
    *,
    npm: str | None,
    runner: Callable[[list[str], Path], int],
    out: TextIO,
) -> int:
    """Run ``gates`` in order and return the exit status the caller should use.

    ``npm`` is the resolved npm executable, or ``None`` when it is not
    installed; ``runner`` is the seam the tests replace.
    """
    results: list[tuple[Gate, str]] = []
    for gate in gates:
        argv = list(gate.argv)
        if gate.needs_npm:
            if npm is None:
                print(
                    f"{SKIPPED}: npm not found on PATH -- {gate.name} "
                    f"({_shown(argv)}) did not run",
                    file=out,
                    flush=True,
                )
                results.append((gate, SKIPPED))
                continue
            argv[0] = npm
        print(f"\n=== {gate.name}: {_shown(argv)}", file=out, flush=True)
        code = runner(argv, gate.cwd)
        results.append((gate, PASS if code == 0 else FAIL))

    print("", file=out)
    for gate, status in results:
        print(f"{status:<7} {gate.name:<10} {_shown(gate.argv)}", file=out)

    # No second, rolled-up "these were skipped" line here: the announcement is
    # one line per skipped gate, printed where the gate would have run, and the
    # report block above repeats each one. A summary line as well would mean a
    # test could see the words `SKIPPED: npm not found` in the output while the
    # per-gate announcement had gone missing.
    failed = [gate.name for gate, status in results if status == FAIL]
    if failed:
        print(f"\nFAILED: {', '.join(failed)}", file=out, flush=True)
        return 1
    print("\nevery gate that ran passed", file=out, flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv:
        raise SystemExit(f"{Path(__file__).name} takes no arguments, got {argv}")
    return run_gates(
        GATES,
        npm=shutil.which(NPM),
        runner=_subprocess_runner,
        out=sys.stdout,
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
