# ADR 0036 — One image, two commands

**Status:** **SUPERSEDED 2026-08-31** by an owner ruling: Docker is not wanted.
The `Dockerfile`, `docker-compose.yml` and `.dockerignore` this ADR describes
were deleted, and the service now runs **natively on the host** — see
`docs/DEPLOYMENT.md` ("no containers") and its §6 runbook. The
`.github/workflows/ci.yml` `image` job that built and booted the artefact was
removed at `f268e5d`. Everything below describes an image that was built, run and
verified (2026-08-11) and has since been removed; it is kept because the
*reasoning* is still the reasoning — the one-artefact-vs-drift trade, the
UI-build-in-the-image argument, migrations as an operator step, and the
`python -m receipts.worker` entry point (which survives the removal and is still
how a worker is run). **What is superseded is the packaging shape, not the
service's boot contract** (ADR-0035) or the gate runner (ADR-0017).
**Builds on:** ADR-0035 (the ASGI entry point, which deliberately left
containerisation undecided), ADR-0004 (portable persistence and docker Postgres),
ADR-0014 (optional dependencies stay out of every import path)
**Relates to:** ADR-0017 (the gate runner), ADR-0032 §3 (anchors are where rot
lives)

Derived 2026-08-11 against `feat/containerisation`, **by building the image and
running it**. Every number and status code below came from that run. **Re-derive
rather than quote** (ADR-0028 rule 1).

## Context

ADR-0035 gave the service a supported entry point and stopped there, listing
containerisation, a run-book and CI as decisions it was not making. This one
makes the first two.

## Decision

### 1. One image, two commands

A single image installs `.[api,worker,postgres,pipeline]`. The API takes the
default `CMD`; the worker overrides it with `python -m receipts.worker`.

One thing is built, tagged and promoted, so there is one known-good artefact
rather than two that drift. **The cost is real and is not hidden:** the API layer
carries `pillow` and `opencv-python-headless` for the worker's sake and never
imports them. Measured: **683 MB**, Python 3.13.15.

**`worker` is not the worker's extra alone.** The API needs `rq` and `redis` too,
because `_default_submit` reaches RQ to *enqueue* and ADR-0035 made `REDIS_URL` a
boot requirement. An API image built without it would start cleanly and fail on
every upload.

**`pipeline` genuinely is the worker's.** Measured rather than assumed: the API
path calls `ingest_bytes`, which imports only the standard library and
`.storage`; `pypdfium2` is lazy inside `expand_pdf`, which no API route calls.

### 2. The image builds the review UI

A `node:22-slim` stage runs `npm run build`; the runtime stage copies `dist/` in.
Node does not exist in the final image.

`frontend/dist` is gitignored, so the alternative — expecting a built `dist` in
the build context — would ship whatever a developer happened to have lying
around, and ADR-0035's `SERVE_SPA` check could not catch it: a stale
`index.html` is still an `index.html`. `.dockerignore` excludes `frontend/dist`
for exactly that reason.

### 3. Migrations are an operator step, not an entrypoint

`alembic upgrade head` is documented in `docs/DEPLOYMENT.md` and run by nothing
automatically.

An entrypoint that migrated would have every replica race on startup, and would
turn a bad migration into a crashloop instead of one failed command whose output
somebody can read. The cost is a step that can be skipped; the mitigation is that
it is the first thing in the guide's run section.

### 4. The package is installed, and its source is deleted

`pip install` runs from `/build`, which is removed in the same layer. `/app`
holds **only** `alembic/`, `alembic.ini` and `frontend/dist`.

This is not tidiness. `config` is a top-level package — a sibling of `src/`, per
pyproject's `packages.find` — so a copy left at `/app/config` **shadows the
installed one**, because Python puts the working directory first and the
container runs from `/app`.

Found by the review, measured before the fix:

```
cd /app && python -c "import config; print(config.__file__)"
  ->  /app/config/__init__.py          # not site-packages
```

The two copies were identical, so nothing misbehaved — and they were one edit
away from not being, with the running copy the one nobody would guess. The first
build also left `build/` and `receipts.egg-info/` behind.

`alembic/` stays because migrations need it, and **that path was re-tested after
the change**: `python -m alembic upgrade head` still applies both revisions from
`/app` and exits 0.

### 5. Non-root, and `/app` is not writable

The image runs as uid 10001. Verified: `touch /app/probe` → permission denied.

This is a deliberate constraint rather than an oversight, and the guide states
its consequences: blobs must go to a mounted volume or S3, and a SQLite
`DATABASE_URL` pointed inside `/app` will fail.

### 6. Compose runs the whole stack, and declares itself unsafe

`docker-compose.yml` gains `redis`, `api` and `worker` alongside the existing
`postgres` and `ollama`. **Redis was missing entirely**, and `receipts.asgi` now
refuses to boot without it.

The `api` service sets `SESSION_COOKIE_SECURE=false` **and**
`ALLOW_INSECURE_SESSION_COOKIE=true`. That pair is the worked example of why
ADR-0035 gave the hatch a name: the stack is plain HTTP on loopback, so running
insecure is correct here and had to be written down to happen.

`SESSION_SECRET` has **no default** — compose refuses to start without it.
Verified: `required variable SESSION_SECRET is missing a value`.

## `python -m receipts.worker` did not exist

`run_worker` was defined and nothing invoked it: no `__main__`, no console
script. The queue had the same gap the review API had before ADR-0035 — a
function nobody could run.

A `__main__` block was added to `receipts/worker.py`. It parses no arguments:
every knob `run_worker` accepts is already an environment variable read through
`Settings`, and a second way to say the same thing is a second thing to keep in
agreement. Defaults are what a service wants — the default queue, and
`burst=False` so it runs until stopped.

**This was found by writing the compose file**, whose `command:` had to name
something real. It is the second time in two milestones that documenting a thing
revealed the thing did not exist.

## Verified by running it, not by reading it

A Dockerfile that has never been built is a guess. This one was built and run
(2026-08-11):

| check | result |
|---|---|
| `docker build` | succeeds; every dependency resolves to a wheel, no build toolchain needed |
| container with no configuration | refuses, naming `DATABASE_URL` and `REDIS_URL` |
| `GET /health` | `200 {"status":"ok"}` |
| `GET /app/` | `200 text/html` — the UI the Node stage built |
| `GET /receipts` with no session | `401` |
| `python -m receipts.worker`, no broker | fails **connecting** to Redis, not importing |
| `docker compose config` | validates; five services |
| compose with `SESSION_SECRET` unset | refuses, with the message the file supplies |

## Consequences

- **The service can be deployed as an artefact**, not just started from a
  checkout.
- **The API image is larger than it needs to be**, by the `pipeline` extra. The
  exit is two images, and ADR-0036 can be revisited if the size ever costs more
  than the drift would.
- **Compose is no longer just dev services.** `docker compose up -d` now starts
  the application, which is convenient and is why the api service carries the
  loudest comments in the file.
- **`python -m receipts.worker` is now public surface.** It is the documented way
  to run a worker, so its defaults are a contract.

## What this ADR does not decide

CI, a registry or image-promotion policy, orchestration manifests, a secret
manager, backup and restore, or observability beyond stdout. Each is a real
decision; none is blocked by anything here.

Nor the base image beyond "it works": `python:3.13-slim` was chosen because the
package requires `>=3.11` and every dependency has a 3.13 wheel. The development
interpreter is 3.14.4, so **the image runs a different minor version than the
test suite does** — stated here because it is the kind of divergence that
explains a bug six months from now.

## References

`docs/DEPLOYMENT.md`; `docs/adr/0035-the-asgi-entry-point.md`;
`Dockerfile`; `.dockerignore`; `docker-compose.yml`;
`src/receipts/worker.py` (the `__main__` block).
