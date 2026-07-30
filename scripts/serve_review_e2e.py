"""Serve the review API on loopback for the Playwright acceptance run (P5.T5).

    python scripts/serve_review_e2e.py --db sqlite:///var/e2e/review-e2e.db

**This is not a production entry point and must not become one.** This
repository has no supported way to serve `receipts.review.api:create_app` --
there is no `app = create_app(...)` anywhere under `src/`, no `asgi` module, and
the only console script is the CLI -- and that gap is a deployment decision
about settings, session factory, storage backend and host policy that deserves
to be made deliberately, not inherited from whatever an end-to-end test needed.
So this launcher is deliberately narrow, and every choice below is a choice a
real deployment would have to revisit:

  * **loopback only.** The host is the literal `127.0.0.1`, not a flag: nothing
    here should be reachable off the machine.
  * **a published session secret.** `--session-secret` defaults to a fixed
    string that lives in this file, in git, for anyone to read. It exists so the
    acceptance run is reproducible; it is worthless as a secret.
  * **`SESSION_COOKIE_SECURE=false`**, because the run is plain HTTP on
    loopback. `create_app` logs a warning for exactly this, and the warning is
    correct.
  * **no `.env`.** `Settings(_env_file=None)` -- a developer's local
    environment must not steer an acceptance run, the same reason
    `tests/test_api_read.py`'s settings fixture is hermetic.
  * **uploads refuse rather than queue.** `submit` raises instead of reaching
    Redis/RQ, so `POST /upload` answers 503 "could not be queued". The
    acceptance run never uploads; a launcher that silently needed a broker
    would be worse.

It also **fails loudly when the frontend is not built.** `create_app` skips its
SPA mount silently when `FRONTEND_DIST` holds no `index.html` -- correct for a
base install, useless here, where the symptom would be `/app/login` 404ing with
nothing to say why.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

# See scripts/seed_review_e2e.py for why this bootstrap is here.
for _root in (str(REPO_ROOT), str(REPO_ROOT / "src")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

DEFAULT_DB_URL = "sqlite:///var/e2e/review-e2e.db"
DEFAULT_STORAGE_ROOT = "var/e2e/blobs"
DEFAULT_FRONTEND_DIST = "frontend/dist"
DEFAULT_PORT = 8100

#: Not a secret. See the module docstring.
E2E_SESSION_SECRET = "playwright-acceptance-run-not-a-secret"

#: Loopback, and not configurable. See the module docstring.
HOST = "127.0.0.1"


def _refuse_to_queue(job: Any) -> Any:
    """The `submit` this app is built with: no broker, and no pretending."""
    raise RuntimeError(
        f"receipt {getattr(job, 'id', job)} cannot be queued: "
        "scripts/serve_review_e2e.py is an end-to-end launcher with no worker queue"
    )


def build_app(db_url: str, storage_root: Path, frontend_dist: Path, secret: str) -> Any:
    from config.settings import Settings
    from receipts.ingest.storage import LocalStorage
    from receipts.persist.session import make_engine, make_session_factory
    from receipts.review.api import create_app

    if not (frontend_dist / "index.html").is_file():
        raise SystemExit(
            f"{frontend_dist / 'index.html'} is missing, so /app would not be served at all "
            "(create_app skips the SPA mount silently when the dist is absent). "
            "Run `npm --prefix frontend run build` first."
        )

    settings = Settings(
        _env_file=None,
        session_secret=secret,
        session_cookie_secure=False,
        frontend_dist=str(frontend_dist),
    )
    return create_app(
        session_factory=make_session_factory(make_engine(db_url)),
        storage=LocalStorage(storage_root),
        submit=_refuse_to_queue,
        settings=settings,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=DEFAULT_DB_URL, help=f"default: {DEFAULT_DB_URL}")
    parser.add_argument(
        "--storage-root", default=DEFAULT_STORAGE_ROOT, help=f"default: {DEFAULT_STORAGE_ROOT}"
    )
    parser.add_argument(
        "--frontend-dist", default=DEFAULT_FRONTEND_DIST, help=f"default: {DEFAULT_FRONTEND_DIST}"
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"default: {DEFAULT_PORT}")
    parser.add_argument("--session-secret", default=E2E_SESSION_SECRET, help="not a secret")
    args = parser.parse_args(argv)

    import uvicorn

    app = build_app(
        args.db,
        Path(args.storage_root),
        Path(args.frontend_dist),
        args.session_secret,
    )
    print(f"serving the review API for the acceptance run on http://{HOST}:{args.port}")
    uvicorn.run(app, host=HOST, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
