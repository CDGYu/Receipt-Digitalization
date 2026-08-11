# ADR 0035 — The ASGI entry point, and what it refuses to start on

**Status:** Accepted (2026-08-11)
**Builds on:** ADR-0014 (optional dependencies stay out of every import path),
ADR-0012 (auth and roles), ADR-0004 (portable persistence)
**Relates to:** ADR-0006 (the `ValueError` boundary), ADR-0017 (the gate runner),
ADR-0032 §3 (anchors are where rot lives)

Derived 2026-08-11 against `feat/asgi-entry-point`. **Re-derive rather than
quote** (ADR-0028 rule 1).

## Context

`create_app` was a factory **nothing under `src/` called**. There was no `asgi`
module and no `app = create_app(...)` anywhere, so the service had no supported
way to be served. The only thing that served it, `scripts/serve_review_e2e.py`,
says in its own docstring that it must not become the answer and lists why:
loopback hardcoded, a published session secret in git,
`SESSION_COOKIE_SECURE=false`, no `.env`, and uploads that refuse rather than
queue. Each is right for an acceptance run and wrong for a deployment.

### The hazard that set the shape

`make_engine` resolves its URL as `url or Settings().database_url or
DEFAULT_URL`, and `DEFAULT_URL` is `sqlite:///receipts.db`. So the obvious entry
point —

```python
app = create_app(session_factory=make_session_factory(make_engine(settings.database_url)), ...)
```

— **serves production off a local SQLite file when `DATABASE_URL` is unset**,
with nothing logged and nothing failing. The data goes somewhere nobody looks.

That is why this module's job is to **refuse**, not merely to construct. Every
check below earns its place the same way: the misconfiguration is silent, and
the symptom shows up far from the cause.

## Decision

### 1. One module, a factory, and a lazily-resolved `app`

`src/receipts/asgi.py` exposes `create_asgi_app(settings=None)` and resolves
`app` through a PEP-562 module `__getattr__`.

```
uvicorn receipts.asgi:app
```

**Importing the module builds nothing** — no engine, no configuration read, no
filesystem access. ADR-0014 exists because two shipped defects put optional
dependencies on an import path; a module whose *import* requires a configured
database is the same shape. `python -c "import receipts.asgi"` succeeds on a
base install with no configuration at all, verified from `C:\Users`.

`persist/__init__.py` already resolves its public names through a lazy attribute
map, so this is the package's existing idiom.

**Rejected — factory-only** (`uvicorn --factory receipts.asgi:create_asgi_app`):
cleanest semantics, but every command line and document must carry `--factory`,
and omitting it does not error. Uvicorn serves the *function object* and the
failure appears per-request instead of at boot. A footgun bought with purity.

**Rejected — eager `app = create_asgi_app()`**: simplest to read, and makes
importing the package tree require a configured database. Measured: with the
eager form in place, `tests/test_asgi.py` fails at **collection** with the boot
error.

### 2. Four refusals, collected and raised once

`_check_boot_config` gathers **every** failure before raising, so a
misconfigured deployment learns everything wrong from one attempt rather than
one item per restart.

| refuses when | because |
|---|---|
| `DATABASE_URL` unset | the hazard above — a local SQLite file, silently |
| `SESSION_COOKIE_SECURE=false` | session cookies in cleartext; `create_app` only *warns* |
| `REDIS_URL` unset | `POST /upload` cannot queue; the failure would surface at first upload |
| `SERVE_SPA=true` and `FRONTEND_DIST` has no `index.html` | `_install_spa` skips silently and `/app/*` 404s unexplained |

`SESSION_SECRET` is **not** re-checked. `install_session_middleware` already
raises without it a few frames later, and two checks of one condition are two
places to keep in agreement.

### 3. It raises `ValueError`

Matching `install_session_middleware`, which already raises `ValueError` for the
missing-`SESSION_SECRET` case — verified by reading it. One type for every boot
failure means a caller wrapping `create_asgi_app` catches all of them with one
`except`.

That is also the API's 400 currency (ADR-0006), which looks like a hazard and is
not: these raise during app **construction**, before any request exists and
before the error handlers are installed. A bespoke boot exception would split one
failure class across two types to guard a path that cannot be reached.

### 4. Two escape hatches, both typed and both defaulted safe

Neither refusal can be absolute without making a legitimate deployment
impossible. Both live in `Settings` rather than being read ad hoc from the
environment, so they are typed, defaulted, and documented in one place.

* **`allow_insecure_session_cookie: bool = False`.** Without it there is no way
  to run the real entry point over plain HTTP at all. With it, doing so stops
  being a default nobody noticed and becomes a line somebody wrote.
* **`serve_spa: bool = True`.** `frontend/dist` is **gitignored**, so a fresh
  checkout has no `index.html` and any deployment wanting the UI must run
  `npm run build` first. Left true, that step is enforced. Set false, an
  API-only deployment becomes possible.

`serve_spa=False` also stops `_install_spa` mounting when a stale `dist/`
happens to exist — "do not serve the SPA" has to mean it, or the flag lies.
This is the decision's only change to `api.py`.

### 5. What it does not decide

Host, port, workers, proxy headers, TLS, process supervision, and migrations.
Those belong to the `uvicorn` invocation or the platform. The module exposes an
ASGI app and nothing else.

`scripts/serve_review_e2e.py` is **unchanged**. Replacing it was never the
point; its docstring listed the choices a real deployment must revisit, and this
ADR is where they were made.

## `make_storage` got a home

The backend was built by `_make_storage`, private in `cli.py`. The entry point
needed the same four lines, and both importing a private helper across modules
and copying it were wrong. It is now
`receipts.ingest.storage.make_storage(settings)`; `cli.py` keeps `_make_storage`
as a delegation so its call sites and its docstring's promise — that
`receipts users list` works with no blob store configured — are unchanged.

This is the first `config` dependency under `receipts.ingest`, and it is safe in
the way ADR-0014 cares about: `pydantic-settings` is a **base** dependency, the
model has no import-time side effects, and `config.settings` imports only
`receipts.score.thresholds`, which imports nothing but the standard library — so
there is no cycle. `boto3` stays lazy inside `S3Storage`.

## How it is pinned

`create_asgi_app(settings=...)` takes hermetic `Settings`, so every case is a
unit test needing no environment, no `.env`, no Redis, no Postgres and no built
frontend.

`test_the_baseline_settings_boot` is the control: without it, every refusal test
could pass because the baseline was broken rather than because the field under
test was.

### Proven red, six ways

Each mutation applied alone and reverted before the next (review standard 4):

| mutation | killed |
|---|---|
| `if not settings.database_url:` → `if False:` | its own test + the collect-all case |
| the `SESSION_COOKIE_SECURE` condition → `if False:` | its own test + the collect-all case |
| `if not settings.redis_url:` → `if False:` | its own test + the collect-all case |
| `if settings.serve_spa:` → `if False:` | its own test + the collect-all case |
| drop `if not settings.serve_spa: return` from `_install_spa` | the mount test **only** |
| add module-level `app = create_asgi_app()` | the whole file, at collection |

The fifth killing *only* the mount test is the useful detail: the boot check and
the mount flag are separate guarantees, and a mutation to one must not be
covered by a test for the other.

The collect-all case asserts **membership** — that each variable is named in the
message — not a count. A message naming three of four problems satisfies any
assertion about "several" (review standard 23).

### Verified in the runtime environment, not only in the suite

A green suite is not evidence that installed software works; this repository has
a standing rule about it because a green suite twice certified a CLI that was
broken at import. Run from `C:\Users`, outside the repository, through the
installed package:

* `uvicorn receipts.asgi:app` — *Application startup complete*, serving on the
  bound port.
* the same command with `DATABASE_URL` unset — refuses, printing the
  `ValueError` and naming the variable.
* `python -c "import receipts.asgi"` with nothing configured — imports clean.

## Consequences

- **The service can be deployed.** That was the gap.
- **Four new ways to fail at boot**, all of them replacing a way to fail
  silently later. Nothing runs this way today — the module did not exist — so no
  existing deployment breaks.
- **`Settings` grew two fields.** Both default safe, so an existing `.env` is
  unaffected.
- **`_install_spa` has a second reason to skip.** The boot check keeps the two
  distinguishable: unbuilt-but-wanted now refuses, and declared-off is the only
  remaining silent case.
- **The error message interpolates `DEFAULT_URL`** rather than quoting
  `sqlite:///receipts.db`, so the warning cannot drift from the value it warns
  about (ADR-0032 §3).

## What this ADR does not decide

Containerisation, a deployment run-book, or CI. Each was offered and deliberately
left out of scope; none is blocked by anything here.

Nor the `receipts` console-script gap — `pyproject.toml` declares
`[project.scripts] receipts = "receipts.cli:_console_main"` and the distribution
records the entry point, but no wrapper exists in `C:\Python314\Scripts`. Same
smell, different root cause, and it may resolve to "reinstall" rather than to
code. Use `python -m receipts.cli` until it is settled.

## References

`docs/superpowers/specs/2026-08-11-asgi-entry-point-design.md`;
`scripts/serve_review_e2e.py` (the docstring that enumerated these choices);
`docs/adr/0014-optional-dependency-import-discipline.md`;
`docs/adr/0006-repository-conventions.md`; `tests/test_asgi.py`.
