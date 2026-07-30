"""``scripts/verify.py`` -- the gate runner's two load-bearing promises.

The script itself shells out to pytest, ruff and npm, so the thing under test
here is deliberately not ``main()``: :func:`run_gates` takes the runner and the
resolved ``npm`` path as arguments, and these tests pass a fake runner that
records what it was asked to do and returns a canned status. Running the real
gates from inside the suite would run the suite from inside the suite.

The two promises:

  * **a missing npm skips the Node gates out loud and does not fail the run.**
    A clone with no Node installed must still get a truthful verdict on the
    Python half -- and must be told, per gate, that the other half did not run.
    Silence there is the failure mode ADR-0014 is about.
  * **a failing gate fails the run and names itself.** Every gate still runs
    (the point is a report, not a fail-fast chain), and the exit status is
    non-zero with the failing gate's name in the output.

The fake runner is keyed on a gate's **exact** command line rather than on a
fragment of it or on its name. A fragment matched more than one gate the first
time this was written -- ``ruff``'s last argument is ``.``, which appears in
``sys.executable``, and ``vitest``'s is ``test``, which appears in ``pytest`` --
so two of these tests passed while failing a gate they had not chosen. The name
would work, but it is the string the assertions look for, and a fake steered by
that cannot show the name reaching the output on its own.

``scripts`` is not a package, so the module is loaded from its path.
"""

from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

import pytest

_VERIFY_PATH = Path(__file__).resolve().parents[1] / "scripts" / "verify.py"


def _load_verify():
    name = "verify_script_under_test"
    spec = importlib.util.spec_from_file_location(name, _VERIFY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered *before* it is executed: `@dataclasses.dataclass` resolves the
    # decorated class's `__module__` through `sys.modules`, so a module that is
    # not there yet fails with `AttributeError: 'NoneType' object has no
    # attribute '__dict__'` (measured, on 3.14) rather than anything that names
    # the real cause.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


verify = _load_verify()


class _Runner:
    """A fake gate runner: records every invocation, answers from ``codes``.

    ``codes`` maps an exact command line (``" ".join(argv)``) to the status to
    return for it. Anything not named returns 0.
    """

    def __init__(self, codes: dict[str, int] | None = None) -> None:
        self.calls: list[tuple[list[str], Path]] = []
        self.codes = codes or {}

    def __call__(self, argv: list[str], cwd: Path) -> int:
        self.calls.append((list(argv), cwd))
        return self.codes.get(" ".join(argv), 0)


def _command(gate, npm: str | None) -> str:
    """The command line ``run_gates`` will build for ``gate``."""
    argv = list(gate.argv)
    if gate.needs_npm:
        assert npm is not None, "a Node gate has no command line when npm is absent"
        argv[0] = npm
    return " ".join(argv)


def _gate(name: str):
    return next(gate for gate in verify.GATES if gate.name == name)


def _run(*, npm: str | None, codes: dict[str, int] | None = None):
    runner = _Runner(codes)
    out = io.StringIO()
    status = verify.run_gates(verify.GATES, npm=npm, runner=runner, out=out)
    return status, runner, out.getvalue()


def _commands_run(runner: _Runner) -> list[str]:
    return [" ".join(argv) for argv, _ in runner.calls]


def _summary(printed: str) -> dict[str, str]:
    """The report's per-gate verdicts, as ``{gate name: status}``.

    Parsed rather than pattern-matched so the assertions do not depend on the
    column widths.
    """
    verdicts = {}
    for line in printed.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] in {verify.PASS, verify.FAIL, verify.SKIPPED}:
            verdicts[fields[1]] = fields[0]
    return verdicts


def test_the_five_gates_are_the_ones_this_project_runs():
    assert [gate.name for gate in verify.GATES] == [
        "pytest",
        "ruff",
        "typecheck",
        "vitest",
        "build",
    ]
    assert [gate.name for gate in verify.GATES if gate.needs_npm] == [
        "typecheck",
        "vitest",
        "build",
    ]


def test_a_missing_npm_skips_the_node_gates_out_loud():
    status, runner, printed = _run(npm=None)
    node_gates = [gate.name for gate in verify.GATES if gate.needs_npm]
    announced = [
        line for line in printed.splitlines() if line.startswith("SKIPPED: npm not found")
    ]

    assert status == 0, "the Python half passed; a missing npm must not fail the run"
    # One announcement per skipped gate, each naming its own gate: a single
    # rolled-up line would let two of the three disappear unnoticed.
    assert len(announced) == len(node_gates)
    for name in node_gates:
        assert sum(name in line for line in announced) == 1, f"{name} was skipped in silence"
    assert not any("npm" in command for command in _commands_run(runner)), (
        "a skipped gate must not be executed"
    )
    assert _summary(printed) == {
        gate.name: verify.SKIPPED if gate.needs_npm else verify.PASS for gate in verify.GATES
    }


def test_a_missing_npm_still_runs_the_python_gates():
    _, runner, _ = _run(npm=None)
    assert _commands_run(runner) == [
        _command(_gate("pytest"), None),
        _command(_gate("ruff"), None),
    ]


def test_a_missing_npm_does_not_hide_a_python_failure():
    status, _, printed = _run(npm=None, codes={_command(_gate("ruff"), None): 1})
    assert status == 1
    assert "FAILED: ruff" in printed


@pytest.mark.parametrize("failing", ["pytest", "ruff", "typecheck", "vitest", "build"])
def test_a_failing_gate_fails_the_run_and_names_itself(failing):
    status, _, printed = _run(npm="npm", codes={_command(_gate(failing), "npm"): 2})

    assert status == 1, f"a failing {failing} gate must fail the run"
    assert f"FAILED: {failing}" in printed
    assert _summary(printed)[failing] == verify.FAIL


def test_every_gate_runs_even_after_one_fails():
    _, runner, _ = _run(npm="npm", codes={_command(_gate("pytest"), "npm"): 1})
    assert len(runner.calls) == len(verify.GATES)


def test_the_node_gates_run_through_the_resolved_npm_path():
    """Not the bare word ``npm``.

    On Windows ``npm`` is ``npm.cmd`` and there is no shell here, so
    ``subprocess`` cannot find it by name -- ``shutil.which`` is both the
    presence check and the path.
    """
    resolved = "C:/Program Files/nodejs/npm.cmd"
    _, runner, _ = _run(npm=resolved)
    node_calls = [argv for argv, _ in runner.calls if argv[0] == resolved]
    assert len(node_calls) == sum(1 for gate in verify.GATES if gate.needs_npm)


def test_the_node_gates_run_in_the_frontend_directory():
    _, runner, _ = _run(npm="npm")
    for gate, (_, cwd) in zip(verify.GATES, runner.calls, strict=True):
        expected = verify.FRONTEND if gate.needs_npm else verify.REPO_ROOT
        assert cwd == expected, gate.name


def test_a_clean_run_reports_every_gate_as_passed():
    status, _, printed = _run(npm="npm")
    assert status == 0
    assert _summary(printed) == {gate.name: verify.PASS for gate in verify.GATES}
    assert "FAILED" not in printed
