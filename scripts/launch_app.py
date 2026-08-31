"""One-click launcher for the Receipt Review system (non-programmer entry point).

    Start.bat            # double-click this; it calls this script

**This is a supervisor, not a new entry point into the application.** It starts
three processes that already exist and are already the supported way to run the
system, waits until they are healthy, opens the browser at the review UI, and
shuts every one of them down cleanly when the window is closed. It adds no
behaviour to the app itself:

  * **Redis** -- the queue broker `receipts.asgi` refuses to boot without and
    the worker drains. Started from the bundled `vendor/redis/redis-server.exe`
    only if nothing is already answering on the configured host/port, so a user
    who installed Memurai or a real Redis keeps theirs.
  * **the worker** -- `python -m receipts.worker`, which runs the pipeline for
    each uploaded receipt (RQ `SimpleWorker` on Windows, handled inside
    `run_worker`).
  * **the review API** -- `uvicorn receipts.asgi:app`, which serves both the
    JSON API and, with `SERVE_SPA=true`, the built UI under `/app`.

Everything each process needs it reads from `.env` through `config.settings`,
exactly as it does when started by hand. This script sets no configuration and
holds no secret; it reads `.env` only to learn *where* things are (the Redis
host/port to probe, the model names to check, the port to open a browser at).

**Ordering is load-bearing.** Redis must answer before the API is asked to
boot, because the API's boot check fails on an unreachable `REDIS_URL`; and the
API must answer `GET /health` before the browser is opened, or the user lands
on a connection error and concludes the app is broken. Each wait has a bounded
timeout and, on expiry, prints what did not come up and why rather than hanging.

**Model checks are warnings, never blockers.** The configured VLM is a
deployment choice (`.env`): local Ollama, a cloud endpoint, or the `fake`
client for a dry run. This script warns when Ollama is the provider and the
daemon is down or a configured model is not pulled -- because that is the most
common "I uploaded a receipt and nothing happened" cause -- but it never
refuses to start the app over it. A cloud provider, or an operator who knows
the model is coming, is not second-guessed.
"""

from __future__ import annotations

import atexit
import getpass
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

# Running a script puts *its own* directory on sys.path, not the repo root, so
# `config` and `receipts` import from the editable checkout. Same bootstrap as
# scripts/serve_review_e2e.py and scripts/seed_review_e2e.py.
for _root in (str(REPO_ROOT), str(REPO_ROOT / "src")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

VENDORED_REDIS = REPO_ROOT / "vendor" / "redis" / "redis-server.exe"
VENDORED_REDIS_CONF = REPO_ROOT / "vendor" / "redis" / "launcher.conf"
REDIS_DATA_DIR = REPO_ROOT / "var" / "redis"

#: How long to wait for each service to come up before giving up and reporting.
REDIS_BOOT_TIMEOUT_S = 20
API_BOOT_TIMEOUT_S = 60

#: The port the API serves on. Not read from .env because the port is a uvicorn
#: argument, not a Settings field (see receipts.asgi's docstring: host/port
#: belong to the invocation). This launcher owns it, and passes it to uvicorn.
API_HOST = "127.0.0.1"
API_PORT = 8000


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def _say(msg: str) -> None:
    """A launcher line, prefixed so it is distinguishable from a child's logs."""
    print(f"[launcher] {msg}", flush=True)


def _parse_redis_host_port(redis_url: str | None) -> tuple[str, int]:
    """Pull host and port out of a REDIS_URL, defaulting to loopback:6379.

    Deliberately tolerant: this is only used to *probe* whether something is
    already listening and to point the bundled server at the same place. The
    real client parsing is redis-py's job, in the worker and the API.
    """
    if not redis_url:
        return ("127.0.0.1", 6379)
    match = re.search(r"redis://(?:[^@/]*@)?([^:/?]+)(?::(\d+))?", redis_url)
    if not match:
        return ("127.0.0.1", 6379)
    host = match.group(1) or "127.0.0.1"
    port = int(match.group(2)) if match.group(2) else 6379
    return (host, port)


def _is_listening(host: str, port: int, timeout: float = 0.5) -> bool:
    """Whether a TCP connect to host:port succeeds right now."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http_ok(url: str, timeout: float = 2.0) -> bool:
    """Whether an HTTP GET returns 2xx. Any error (refused, 5xx) is False."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (loopback)
            return 200 <= resp.status < 300
    except (urllib.error.URLError, OSError):
        return False


# --------------------------------------------------------------------------- #
# Redis
# --------------------------------------------------------------------------- #


def ensure_redis(host: str, port: int, procs: list[subprocess.Popen]) -> bool:
    """Guarantee something is answering Redis at host:port. Returns True on ready.

    If a Redis is already listening -- the user installed Memurai, or left one
    running -- it is used as-is and nothing is started. Otherwise the bundled
    server is launched against the same host/port and we wait for it to answer.
    """
    if _is_listening(host, port):
        _say(f"Redis already running on {host}:{port} -- using it.")
        return True

    if not VENDORED_REDIS.is_file():
        _say(
            f"No Redis is running on {host}:{port} and the bundled server is "
            f"missing at {VENDORED_REDIS}. Install Memurai or Redis, or restore "
            "the bundled copy under vendor/redis/."
        )
        return False

    REDIS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    _say(f"Starting bundled Redis on {host}:{port} ...")
    # --port and --dir on the command line override the conf file, so the same
    # bundled binary follows whatever REDIS_URL says without editing the conf.
    proc = subprocess.Popen(
        [
            str(VENDORED_REDIS),
            str(VENDORED_REDIS_CONF),
            "--port",
            str(port),
            "--dir",
            str(REDIS_DATA_DIR),
        ],
        cwd=str(REPO_ROOT),
    )
    procs.append(proc)

    deadline = time.monotonic() + REDIS_BOOT_TIMEOUT_S
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            _say(f"Redis exited immediately (code {proc.returncode}). See its output above.")
            return False
        if _is_listening(host, port):
            _say("Redis is up.")
            return True
        time.sleep(0.3)

    _say(f"Redis did not start listening within {REDIS_BOOT_TIMEOUT_S}s.")
    return False


# --------------------------------------------------------------------------- #
# Model (Ollama) pre-flight -- warnings only
# --------------------------------------------------------------------------- #


def check_models(settings: Any) -> None:
    """Warn (never block) when the configured Ollama models are not ready.

    Only runs its checks for the Ollama provider. A cloud provider or the fake
    client is a deliberate choice this launcher does not interrogate.
    """
    provider = (settings.vlm_provider or "").strip().lower()
    if provider not in {"ollama", "ollama_compat"}:
        _say(f"VLM provider is {settings.vlm_provider!r}; skipping local model checks.")
        return

    base_url = (settings.vlm_base_url or "http://localhost:11434/v1").rstrip("/")
    # The OpenAI-compatible base ends in /v1; Ollama's native tags endpoint does
    # not. Strip a trailing /v1 to reach /api/tags.
    root = base_url[: -len("/v1")] if base_url.endswith("/v1") else base_url
    tags_url = f"{root}/api/tags"

    try:
        with urllib.request.urlopen(tags_url, timeout=3.0) as resp:  # noqa: S310 (loopback)
            import json

            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        _say(
            "WARNING: Ollama does not appear to be running at "
            f"{root}. Start it (the Ollama app, or `ollama serve`) or uploads "
            "will sit waiting until the cloud fallback (if configured) answers."
        )
        return

    pulled = {m.get("name", "") for m in payload.get("models", [])}
    # Ollama reports names with an implicit :latest; compare on the bare name too.
    pulled_bare = {n.split(":")[0] for n in pulled}

    wanted = {
        "VLM_MODEL_TRIAGE": settings.vlm_model_triage,
        "VLM_MODEL_EXTRACT": settings.vlm_model_extract,
    }
    for key, name in wanted.items():
        if not name:
            continue
        # A ":cloud" model is served by Ollama's cloud proxy, not pulled locally.
        if name.endswith(":cloud"):
            continue
        if name in pulled or name.split(":")[0] in pulled_bare:
            _say(f"Model for {key} ({name}) is pulled.")
        else:
            _say(
                f"WARNING: {key} is {name!r}, which is not pulled. Run "
                f"`ollama pull {name}` or the first receipt will wait for it "
                "(or escalate to the cloud fallback, if one is configured)."
            )


# --------------------------------------------------------------------------- #
# First-run account setup
# --------------------------------------------------------------------------- #


def ensure_account(settings: Any) -> bool:
    """Guarantee the review database can be signed into. Returns True on ready.

    The review UI has no open state -- every screen is behind a login -- so a
    freshly-handed-over copy with no account is a dead end: the app comes up,
    shows a sign-in form, and there is nothing to sign in with. This closes that
    gap, and only that gap.

    Three cases, in order:

      * **schema missing** (a brand-new database file): create every table with
        ``Base.metadata.create_all`` -- the same call ``scripts/seed_review_e2e``
        uses -- then fall through to account creation. This is not a substitute
        for ``alembic upgrade head`` on a real deployment; it is the minimum that
        makes a local SQLite file usable, and it is a no-op on a database that
        already has the tables.
      * **schema present, at least one active account exists**: nothing to do.
      * **schema present, no active account**: prompt in this console (never a
        flag -- a password on a command line lands in shell history) and create
        one admin account, then continue.

    Any failure here is reported and returns False rather than raising, because a
    half-set-up database is something the user must see, not a traceback.
    """
    try:
        from sqlalchemy.exc import OperationalError

        from receipts.persist.models import Base
        from receipts.persist.session import make_engine, make_session_factory
        from receipts.persist.users import ROLE_ADMIN, create_user, list_users
    except Exception as exc:  # pragma: no cover - environment problem
        _say(f"Could not load the account tools ({exc}).")
        return False

    engine = make_engine(settings.database_url)

    # Does the users table exist yet? A fresh SQLite file has no schema.
    try:
        with make_session_factory(engine)() as session:
            accounts = [u for u in list_users(session) if u.is_active]
    except OperationalError:
        _say("First run: setting up a new database ...")
        Base.metadata.create_all(engine)
        accounts = []
    except Exception as exc:
        _say(f"Could not read the accounts table ({exc}).")
        return False

    if accounts:
        return True

    # No account to sign in with. Create one, interactively, right here.
    _say("")
    _say("No sign-in account exists yet. Let's create one now (one time only).")
    try:
        username = input("[launcher]   Choose a username: ").strip()
        while not username:
            username = input("[launcher]   Username cannot be blank. Try again: ").strip()
        password = getpass.getpass("[launcher]   Choose a password (typing is hidden): ")
        while not password:
            password = getpass.getpass("[launcher]   Password cannot be blank. Try again: ")
        confirm = getpass.getpass("[launcher]   Type the password again to confirm: ")
        if password != confirm:
            _say("The two passwords did not match. Start the app again to retry.")
            return False
    except (EOFError, KeyboardInterrupt):
        _say("Account setup cancelled. Nothing was created.")
        return False

    try:
        with make_session_factory(engine)() as session:
            create_user(session, username, password, ROLE_ADMIN)
            session.commit()
    except Exception as exc:
        _say(f"Could not create the account ({exc}).")
        return False

    _say(f"Created admin account {username!r}. Use it to sign in.")
    _say("")
    return True


# --------------------------------------------------------------------------- #
# Worker and API
# --------------------------------------------------------------------------- #


def start_worker(procs: list[subprocess.Popen]) -> subprocess.Popen:
    """Start the RQ worker: `python -m receipts.worker`."""
    _say("Starting the receipt worker ...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "receipts.worker"],
        cwd=str(REPO_ROOT),
        env=_child_env(),
    )
    procs.append(proc)
    return proc


def start_api(procs: list[subprocess.Popen]) -> subprocess.Popen:
    """Start the review API: `uvicorn receipts.asgi:app` on API_HOST:API_PORT."""
    _say(f"Starting the review API on http://{API_HOST}:{API_PORT} ...")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "receipts.asgi:app",
            "--host",
            API_HOST,
            "--port",
            str(API_PORT),
            "--log-level",
            "warning",
        ],
        cwd=str(REPO_ROOT),
        env=_child_env(),
    )
    procs.append(proc)
    return proc


def _child_env() -> dict[str, str]:
    """The environment children inherit, with src/ on PYTHONPATH.

    The package is installed editable here, but making PYTHONPATH explicit means
    the launcher still works from a plain checkout that was never `pip install`ed,
    which is exactly the situation a non-programmer is most likely to be in.
    """
    env = dict(os.environ)
    src = str(REPO_ROOT / "src")
    root = str(REPO_ROOT)
    existing = env.get("PYTHONPATH", "")
    parts = [p for p in (src, root, existing) if p]
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def wait_for_api(proc: subprocess.Popen) -> bool:
    """Wait until GET /health answers, the API process dies, or we time out."""
    health = f"http://{API_HOST}:{API_PORT}/health"
    deadline = time.monotonic() + API_BOOT_TIMEOUT_S
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            _say(
                f"The API exited before becoming ready (code {proc.returncode}). "
                "Its output above says why -- most often a missing setting in .env."
            )
            return False
        if _http_ok(health):
            _say("The review API is ready.")
            return True
        time.sleep(0.4)
    _say(f"The API did not answer {health} within {API_BOOT_TIMEOUT_S}s.")
    return False


# --------------------------------------------------------------------------- #
# Shutdown
# --------------------------------------------------------------------------- #


def shutdown(procs: list[subprocess.Popen]) -> None:
    """Terminate every child we started, most-recently-started first.

    Reverse order so the API and worker stop before the Redis they depend on.
    Terminate first (graceful), then kill anything that has not exited.
    """
    for proc in reversed(procs):
        if proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
    deadline = time.monotonic() + 8
    for proc in reversed(procs):
        remaining = max(0.0, deadline - time.monotonic())
        try:
            proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except OSError:
                pass


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def _check_dependencies() -> bool:
    """Whether the runtime packages the app needs are importable here.

    The `.bat` runs this script with the provisioned ``.venv`` Python, where
    these are installed. If someone instead runs it with a bare system Python
    that was never set up, the failure would otherwise be an ImportError several
    frames deep inside a child process, with no hint that the fix is to use the
    launcher. Checking a few representative imports up front turns that into one
    plain sentence pointing at the right entry point.

    Representative, not exhaustive: one package from each extra the app needs
    (api -> fastapi/uvicorn, worker -> redis/rq, pipeline -> PIL/cv2) plus the
    app itself. If these import, provisioning succeeded.
    """
    probes = {
        "the app": "receipts",
        "the web server": "uvicorn",
        "the web framework": "fastapi",
        "the queue client": "redis",
        "the queue worker": "rq",
        "image handling": "PIL",
        "image processing": "cv2",
    }
    missing = []
    for label, module in probes.items():
        try:
            __import__(module)
        except Exception:
            missing.append(f"{label} ({module})")
    if missing:
        _say("This app's components are not installed in the Python being used.")
        _say("Missing: " + ", ".join(missing))
        _say("")
        _say("Start the app by double-clicking 'Start Receipt Review.bat', which")
        _say("sets up an isolated environment and installs everything for you.")
        _say("Do not run this script with a bare 'python' directly.")
        return False
    return True


def main() -> int:
    _say("Receipt Review -- starting up. Close this window to stop everything.")

    # Fail fast and legibly if we are running in an un-provisioned interpreter,
    # rather than crashing deep inside a child process later.
    if not _check_dependencies():
        return 1

    try:
        from config.settings import get_settings
    except Exception as exc:  # pragma: no cover - environment problem
        _say(f"Could not import the app ({exc}). Start it with 'Start Receipt Review.bat'.")
        return 1

    settings = get_settings()
    redis_host, redis_port = _parse_redis_host_port(settings.redis_url)

    procs: list[subprocess.Popen] = []
    # Register shutdown for every exit path: normal return, exception, and the
    # Ctrl-C / console-close signals the .bat wrapper cannot catch for us.
    atexit.register(shutdown, procs)

    def _handle_signal(signum, _frame):  # type: ignore[no-untyped-def]
        _say("Shutting down ...")
        shutdown(procs)
        sys.exit(0)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handle_signal)
        except (ValueError, OSError):
            pass

    # 1. Redis first -- the API refuses to boot without it.
    if not ensure_redis(redis_host, redis_port, procs):
        _say("Cannot continue without Redis. Nothing was left running.")
        return 1

    # 2. Model pre-flight -- warnings only, never a blocker.
    check_models(settings)

    # 3. First-run account setup -- the UI is login-only, so a copy with no
    #    account cannot be used. Blocks (it is the one thing the user must have),
    #    but only ever prompts on a database that has no active account.
    if not ensure_account(settings):
        _say("Cannot continue without a sign-in account. Nothing was left running.")
        shutdown(procs)
        return 1

    # 4. Worker, then API.
    start_worker(procs)
    api = start_api(procs)

    # 5. Wait for health, then open the browser at the UI.
    if not wait_for_api(api):
        _say("The app did not come up. Stopping everything.")
        return 1

    url = f"http://{API_HOST}:{API_PORT}/app/"
    _say(f"Opening {url}")
    try:
        webbrowser.open(url)
    except Exception:  # pragma: no cover - a headless box has no browser
        _say(f"Could not open a browser automatically. Go to {url} yourself.")

    _say("Everything is running. Leave this window open while you work.")
    _say("Close it (or press Ctrl-C) to stop the app.")

    # 6. Supervise: stay alive until a child dies or the user stops us.
    try:
        while True:
            for proc in list(procs):
                if proc.poll() is not None:
                    _say(
                        "A component stopped unexpectedly. Shutting the rest down "
                        "so nothing is left half-running."
                    )
                    return 1
            time.sleep(1.0)
    except KeyboardInterrupt:
        _say("Shutting down ...")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
