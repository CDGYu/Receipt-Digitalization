"""First-run provisioning for the one-click launcher.

    python scripts/bootstrap.py        # run by "Start Receipt Review.bat"

**This is what makes "copy the folder to a new PC and double-click" work.** On a
fresh machine the Python packages the app needs (fastapi, uvicorn, rq, redis,
pillow, opencv, ...) are not installed. This script creates a project-local
virtual environment at ``.venv`` and installs the project plus its runtime
extras into it, so the launcher and its child processes all run from one
isolated, complete environment that never collides with other Python projects on
the machine.

It is designed to be run on **every** startup and do nothing on all but the
first: a sentinel file records the fingerprint of what was installed, and when
that fingerprint still matches, this returns immediately. So the cost is paid
once (a slower first launch that needs internet), and every launch after is
instant and offline.

What it deliberately does NOT do:

  * **Install Python.** A program cannot reliably install its own interpreter.
    The ``.bat`` checks for Python and tells the user where to get it; this
    script is only ever reached once a Python exists.
  * **Install Ollama or pull models.** Those are only needed for the *local*
    model path and are a deployment choice. The launcher warns about them at
    run time; provisioning does not force them.

Exit codes: ``0`` the environment is ready (freshly provisioned or already so);
non-zero it could not be made ready, with the reason printed. The ``.bat`` keeps
its window open on a non-zero exit so the user can read it.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VENV_DIR = REPO_ROOT / ".venv"
PYPROJECT = REPO_ROOT / "pyproject.toml"
#: Records the fingerprint of the last successful provision. Lives inside the
#: venv so deleting .venv also resets provisioning -- the two can never disagree.
SENTINEL = VENV_DIR / ".provisioned"

#: The runtime extras the launcher needs. Not ``dev`` (pytest/ruff/mypy are for
#: working on the project, not running it) and not ``ocr``/``postgres`` (opt-in
#: deployment choices, off by default in settings). This is the set that makes
#: the API serve, the worker process receipts, and images decode.
EXTRAS = ["api", "worker", "pipeline"]

#: Bumped by hand when this script's own install *recipe* changes (a new extra,
#: a different pip step) in a way pyproject.toml alone would not capture. Part of
#: the fingerprint, so such a change re-provisions existing machines too.
RECIPE_VERSION = "1"


def _say(msg: str) -> None:
    print(f"[setup] {msg}", flush=True)


def venv_python() -> Path:
    """The python.exe inside the venv (Windows layout)."""
    return VENV_DIR / "Scripts" / "python.exe"


def _fingerprint() -> str:
    """What the current environment *should* contain, as a short hash.

    Combines this machine's Python version, the recipe version, the chosen
    extras, and the contents of ``pyproject.toml`` (which pins the dependency
    set). Any change to those means the recorded install is stale and we
    re-provision; no change means we skip.
    """
    hasher = hashlib.sha256()
    hasher.update(sys.version.encode("utf-8"))
    hasher.update(RECIPE_VERSION.encode("utf-8"))
    hasher.update(",".join(sorted(EXTRAS)).encode("utf-8"))
    try:
        hasher.update(PYPROJECT.read_bytes())
    except OSError:
        # No pyproject is a hard error later; fold its absence into the hash so
        # the state is at least consistent rather than crashing here.
        hasher.update(b"<no-pyproject>")
    return hasher.hexdigest()


def _is_provisioned(expected: str) -> bool:
    """Whether the venv exists, has a python, and matches ``expected``."""
    if not venv_python().is_file():
        return False
    try:
        return SENTINEL.read_text(encoding="utf-8").strip() == expected
    except OSError:
        return False


def _run(cmd: list[str], *, what: str) -> bool:
    """Run a provisioning command, streaming its output. True on success."""
    _say(what)
    result = subprocess.run(cmd, cwd=str(REPO_ROOT))
    if result.returncode != 0:
        _say(f"FAILED: {what} (exit {result.returncode}).")
        return False
    return True


def ensure_environment() -> int:
    """Make ``.venv`` ready to run the app. Returns a process exit code."""
    if not PYPROJECT.is_file():
        _say(
            f"pyproject.toml is missing at {PYPROJECT}. This does not look like "
            "the project folder -- make sure you copied the whole folder."
        )
        return 1

    expected = _fingerprint()
    if _is_provisioned(expected):
        # Nothing to do -- this is the common case on every launch after the first.
        return 0

    # Either no venv, or pyproject/recipe changed since the last install.
    if not venv_python().is_file():
        _say("First-time setup: creating an isolated environment (.venv). This is")
        _say("a one-time step and needs an internet connection. Please wait ...")
        if not _run(
            [sys.executable, "-m", "venv", str(VENV_DIR)],
            what="creating the virtual environment",
        ):
            _say(
                "Could not create the environment. If you are offline, connect to "
                "the internet and try again."
            )
            return 1
    else:
        _say("Dependencies changed since last run; updating the environment ...")

    vpy = str(venv_python())

    # A recent pip/setuptools/wheel avoids a whole class of build failures on the
    # binary wheels this project pulls in (opencv, pillow-heif).
    if not _run(
        [vpy, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"],
        what="updating the installer",
    ):
        return 1

    # Install the project itself plus the runtime extras, editable so it tracks
    # the checkout. `.[api,worker,pipeline]` is the set the launcher needs.
    target = f".[{','.join(EXTRAS)}]"
    if not _run(
        [vpy, "-m", "pip", "install", "-e", target],
        what="installing the app and its components (this is the slow part)",
    ):
        _say(
            "Could not install the components. The most common cause is no "
            "internet connection during first-time setup."
        )
        return 1

    # Record success only after everything above passed, so a half-finished
    # install never reads as done.
    try:
        SENTINEL.write_text(expected, encoding="utf-8")
    except OSError as exc:
        _say(f"Installed successfully but could not write the setup marker ({exc}).")
        # Not fatal: the app will still run; next launch just re-checks.
        return 0

    _say("Setup complete. Future launches will start immediately.")
    return 0


if __name__ == "__main__":
    raise SystemExit(ensure_environment())
