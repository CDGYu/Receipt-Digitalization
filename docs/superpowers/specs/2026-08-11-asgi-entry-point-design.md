# ASGI entry point — design (2026-08-11)

**Status:** approved 2026-08-11. Decision recorded in **ADR-0035**.

Derived against `main` at `d5bf4c3`. **Re-derive rather than quote**
(ADR-0028 rule 1).

## 1. The gap

`create_app` is a factory **nothing under `src/` calls**. There is no `asgi`
module, no `app = create_app(...)` anywhere, and the only console script is the
CLI. The service cannot be served by any supported means.

The one thing that does serve it, `scripts/serve_review_e2e.py`, says in its own
docstring that it must not become the answer, and enumerates why: it hardcodes
loopback, ships a published session secret, forces `SESSION_COOKIE_SECURE=false`,
refuses a `.env`, and makes uploads fail rather than queue. Every one of those is
correct for an acceptance run and wrong for a deployment. **Inheriting a
deployment policy from an e2e launcher is the mistake this design exists to
avoid.**

### 1.1 The hazard that sets the shape

`make_engine` resolves its URL as `url or Settings().database_url or DEFAULT_URL`,
and `DEFAULT_URL` is `sqlite:///receipts.db`. So the *obvious* entry point —

```python
app = create_app(session_factory=make_session_factory(make_engine(settings.database_url)), ...)
```

— **silently serves production off a local SQLite file** when `DATABASE_URL` is
unset. Nothing fails, nothing logs, and the data goes somewhere nobody looks.
That is the failure this design is built around: the entry point's job is to
refuse, not merely to construct.

## 2. Scope

**In:** one module, the settings it needs, one helper promoted out of `cli.py`,
tests, and an ADR.

**Out, deliberately:** no Dockerfile, no compose service, no deployment run-book,
no CI change, and no host/port/worker policy — those belong to the `uvicorn`
invocation, not to the app object. `scripts/serve_review_e2e.py` is **not**
modified; replacing it was never the point.

Also out: the `§1.6` packaging gap (the declared `receipts` console script
installs no wrapper). Same smell — "the installed artefact is unfinished" — but a
different root cause, and it may resolve to "reinstall" rather than to code.

## 3. Architecture

One new module, `src/receipts/asgi.py`:

```
get_settings()
  -> _check_boot_config(settings)          # refuses HERE, before anything is built
  -> make_engine(settings.database_url)
  -> make_session_factory(engine)
  -> make_storage(settings)
  -> create_app(...)                       -> FastAPI
```

### 3.1 A factory plus a lazy attribute

```python
def create_asgi_app(settings: Settings | None = None) -> FastAPI: ...

def __getattr__(name: str):                # PEP 562
    if name == "app":
        return create_asgi_app()
    raise AttributeError(name)
```

`uvicorn receipts.asgi:app` works, because uvicorn resolves the target with
`getattr`. **Importing the module builds nothing** — no engine, no config
validation, no filesystem access.

That property is the reason for the lazy attribute rather than a module-level
`app = create_asgi_app()`. ADR-0014 exists because two shipped defects put
optional dependencies on an import path; a module whose import opens a database
is the same shape. With `__getattr__`, `python -c "import receipts.asgi"`
succeeds on a base install with no configuration at all.

`persist/__init__.py` already resolves its public names through a lazy attribute
map, so this is the package's existing idiom rather than a new one.

**Rejected: factory-only** (`uvicorn --factory receipts.asgi:create_asgi_app`).
It has the cleanest semantics, but every command line and document must carry
`--factory`, and omitting it does not error — uvicorn serves the *function
object*, which fails per-request instead of at boot. A footgun in exchange for
purity.

**Rejected: eager module-level `app`.** Simplest to read; makes importing the
package tree require a configured database.

## 4. The boot contract

`_check_boot_config(settings)` **collects every failure and raises once.** A
misconfigured deployment should learn everything that is wrong in one attempt,
not one item per restart. It raises a single error naming each problem and the
environment variable that fixes it.

**It raises `ValueError`**, matching `install_session_middleware`, which already
raises `ValueError` for the missing-`SESSION_SECRET` case — verified by reading
it, not assumed. One type for every boot failure means a caller wrapping
`create_asgi_app` catches all of them with one `except`.

That type is also the API's 400 currency (ADR-0006), which looks like a hazard
and is not: these raise during app *construction*, before any request exists and
before the handlers are installed. The alternative — a bespoke boot exception —
would split one failure class across two types to guard against a path that
cannot be reached.

| refuses when | because |
|---|---|
| `DATABASE_URL` unset | §1.1 — the service would run on `sqlite:///receipts.db` and nobody would know |
| `SESSION_COOKIE_SECURE=false` | session cookies would travel in cleartext; today `create_app` only logs a warning |
| `REDIS_URL` unset | `POST /upload` cannot queue, and the failure would appear at first upload rather than at boot |
| `SERVE_SPA=true` and `FRONTEND_DIST` holds no `index.html` | `create_app` skips the SPA mount **silently**, so `/app/*` 404s with nothing explaining why |

`SESSION_SECRET` is **not** re-checked here. `install_session_middleware`
already refuses to start without it, and duplicating the check would give two
places to keep in agreement for no gain.

### 4.1 Two escape hatches, both of which must be typed out

Neither refusal above can be absolute without making a legitimate deployment
impossible, so each gets an explicit opt-out **in `Settings`** — typed,
defaulted safe, and documented in one place rather than read ad hoc from the
environment.

* **`allow_insecure_session_cookie: bool = False`.** Without it, no plain-HTTP
  run of the real entry point is possible at all. With it, running insecure
  stays possible but becomes a deliberate act somebody wrote down.
* **`serve_spa: bool = True`.** `frontend/dist` is **gitignored**, so a fresh
  checkout has no `index.html` and every deployment must run `npm run build`
  first. Left true, that build step is enforced. Set false, the SPA mount is
  skipped as a declared choice and an API-only deployment becomes possible.

`serve_spa=False` must also stop `_install_spa` from mounting when a stale
`dist/` happens to exist — "do not serve the SPA" has to mean it, or the flag
lies. This is the design's only change to `api.py`.

## 5. `make_storage` gets a home

The storage backend is built today by `_make_storage`, **private in `cli.py`**.
The entry point needs the same four lines. Importing a private helper across
modules and duplicating it are both wrong.

It moves to `receipts/ingest/storage.py`, which already owns `LocalStorage`,
`S3Storage` and `StorageBackend`, and becomes public `make_storage(settings)`.
`cli.py` keeps `_make_storage` as a thin delegation so its call sites and its
docstring's promise — that `receipts users list` works with no blob store
configured — are unchanged.

This is the design's only change to a module it does not otherwise touch, and it
is included because the alternative is a second copy of a decision.

## 6. What the entry point does not decide

Host, port, workers, proxy headers, TLS, process supervision, and migrations.
All belong to the invocation or the platform. The module exposes an ASGI app and
nothing else, so a deployment can put it behind whatever it already has.

`/health` semantics are unchanged and remain what they were: liveness, not a
dependency check.

## 7. Testing

`create_asgi_app(settings=...)` accepts hermetic `Settings`, so every case below
is a unit test that touches no environment and no `.env`.

* **Each of the four refusals fires**, proven by building a `Settings` that
  satisfies every check except the one under test — **one guarantee reverted at
  a time**, so a test that passes for the wrong reason is visible.
* **Each refusal passes when satisfied**, which is the control that stops the
  suite going green because everything refuses.
* **All failures are collected**: a `Settings` violating several reports all of
  them, and the assertion names each one rather than counting them.
* **Import builds nothing.** `import receipts.asgi` succeeds with no
  configuration; the proof is that it succeeds in an environment where
  `create_asgi_app()` would raise.
* **`getattr(module, "app")` builds something**, and returns a `FastAPI`.
* **`__getattr__` raises `AttributeError`** for any other name, so the hook does
  not swallow typos.
* **Both escape hatches work**: `allow_insecure_session_cookie=True` boots with
  `session_cookie_secure=False`; `serve_spa=False` boots with no `index.html`
  **and** leaves `/app/*` unmounted when a `dist/` does exist.

The suite must not require Redis, Postgres, or a built frontend. Settings are
constructed, not discovered.

## 8. Risks

* **A new refusal breaks somebody's existing run.** Nothing runs this way today —
  the module does not exist — so there is no deployment to break. The risk is
  entirely forward-looking.
* **`make_storage`'s move touches `cli.py`.** Its tests must pass unmodified; a
  test needing a change is a stop-and-report, not a fix.
* **`serve_spa` adds a second way for `/app/*` to be absent.** The boot check is
  what keeps the two distinguishable: silent-because-unbuilt now refuses, and
  silent-because-declared is the only remaining case.
