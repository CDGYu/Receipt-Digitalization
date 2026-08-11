# Deploying the receipt service

The service is one image that runs either half: the review API, or the queue
worker. The decision and its reasoning are **ADR-0036**; the entry point it
serves is **ADR-0035**.

Everything below was run against the image built from this repository on
2026-08-11. **Re-derive rather than trust** (ADR-0028 rule 1) — the commands are
here so you can.

---

## 1. Build

```
docker build -t receipts .
```

Two stages. A `node:22-slim` stage runs `npm run build` and produces the review
UI; a `python:3.13-slim` stage installs the package and copies that build in.
Node does not exist in the final image.

The image installs `.[api,worker,postgres,pipeline]`:

| extra | what needs it |
|---|---|
| `api` | fastapi, uvicorn, python-multipart, itsdangerous |
| `worker` | rq, redis. **The API needs this too** — `_default_submit` reaches RQ to *enqueue*, so an API without it fails on every upload |
| `postgres` | psycopg. Production is Postgres (ADR-0004); SQLite is for tests |
| `pipeline` | pillow, opencv, heif, pdfium, openpyxl. The **worker's**, not the API's — the API path calls `ingest_bytes`, which imports only stdlib and `.storage` |

That last row is the cost of one image rather than two: the API layer carries
image libraries it never imports. Measured 2026-08-11: **683 MB**, Python
3.13.15.

`/app` in the final image holds **only** `alembic/`, `alembic.ini` and
`frontend/dist` — the things the runtime actually reads. The package is
installed into site-packages and the source tree is deleted in the layer that
installs it, because a leftover `/app/config` would **shadow** the installed
package — ADR-0036 §4 has the measurement.

---

## 2. Configure

The service **refuses to start** rather than running misconfigured, and reports
every problem at once rather than one per restart. With nothing set:

```
ValueError: receipts.asgi refuses to start:
  - DATABASE_URL is not set. Without it the service would run on
    'sqlite:///receipts.db', a local file, and say nothing about it.
  - REDIS_URL is not set, so POST /upload could not queue work. ...
```

### Required

| variable | why it is required |
|---|---|
| `DATABASE_URL` | unset, `make_engine` falls back to a local SQLite file **silently**. This is the check the entry point exists for |
| `REDIS_URL` | `POST /upload` cannot queue without it; the failure would otherwise appear at the first upload |
| `SESSION_SECRET` | signs the session cookie and image URLs. A per-process random default would sign every reviewer out on each restart and hide the misconfiguration |

`SESSION_COOKIE_SECURE` defaults to `true` and the service refuses to start if
it is `false` — see the escape hatch below.

`FRONTEND_DIST` is set by the image to `/app/frontend/dist`. It is absolute
because the default is relative to the working directory.

### Worth setting

| variable | default | notes |
|---|---|---|
| `STORAGE_BACKEND` | `local` | `s3` requires `S3_BUCKET` |
| `STORAGE_ROOT` | `var/blobs` | must be a **writable volume** — see §5 |
| `RECEIPTS_API_KEY` | unset | the machine-upload key. Unset rejects the header path outright |
| `SESSION_TTL_S` | `43200` | 12h. Logout cannot revoke an exfiltrated cookie; this is the exposure window |
| `DOCS_ENABLED` | `false` | `/docs`, `/redoc`, `/openapi.json`. None takes a session or a key |

### The two escape hatches

Both default safe, and both exist so that doing the unsafe thing is a line
somebody wrote rather than a default nobody noticed.

* **`ALLOW_INSECURE_SESSION_COOKIE=true`** permits booting with
  `SESSION_COOKIE_SECURE=false`. Only for plain-HTTP local work. It does not
  weaken the cookie by itself — `SESSION_COOKIE_SECURE` does that.
* **`SERVE_SPA=false`** skips the review UI entirely, for an API-only
  deployment. Left `true`, the service refuses to start unless a built
  `index.html` is present, which is what stops `/app/*` 404ing unexplained.

---

## 3. Migrate

**The image does not run migrations.** Run them yourself, before the first
request:

```
docker run --rm -e DATABASE_URL="postgresql+psycopg://..." receipts \
    python -m alembic upgrade head
```

This is deliberate. An entrypoint that migrated would have every replica race on
startup, and would turn a bad migration into a crashloop rather than one failed
command whose output you can read.

---

## 4. Run

```
# the API -- the image's default command
docker run -d -p 8000:8000 --env-file .env receipts

# the worker -- same image, different command
docker run -d --env-file .env receipts python -m receipts.worker
```

`--host 0.0.0.0` is already in the image's `CMD`. ADR-0035 deliberately kept
host, port and worker count out of the app object: they belong to the
invocation, and the `CMD` is one. Override it freely.

Verified against the running container on 2026-08-11:

| request | result |
|---|---|
| `GET /health` | `200 {"status":"ok"}` |
| `GET /app/` | `200 text/html` — the UI the Node stage built |
| `GET /receipts` with no session | `401` |
| `python -m receipts.worker` with no broker | fails **connecting** to Redis, not importing |

---

## 5. What the platform has to provide

* **TLS, terminated upstream.** The service speaks plain HTTP and expects a
  proxy in front. Keep `SESSION_COOKIE_SECURE=true`; the cookie is a bearer
  credential in front of financial records.
* **A writable volume for `STORAGE_ROOT`.** The container runs as uid 10001 and
  **`/app` is not writable** — verified: `touch /app/probe` → permission denied.
  Blobs must go to a mounted volume or S3, and a SQLite `DATABASE_URL` pointed
  inside `/app` will fail.
* **Process supervision and replicas.** The image runs one uvicorn process. Scale
  with your platform, not with `--workers`, unless you have measured that you
  want in-process workers.
* **`/health` is liveness, not readiness.** It does not check Redis, storage, or
  that migrations have run. Do not gate a rollout on it and assume more.

---

## 6. Local development stack

`docker-compose.yml` runs the whole thing — Postgres, Redis, the API, the
worker, and Ollama:

```
export SESSION_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
docker compose up -d --build
docker compose run --rm api python -m alembic upgrade head
```

Compose **fails to start** if `SESSION_SECRET` is unset rather than inventing
one — verified: `required variable SESSION_SECRET is missing a value`.

The `api` service sets `SESSION_COOKIE_SECURE=false` **and**
`ALLOW_INSECURE_SESSION_COOKIE=true`, because the stack is plain HTTP on
loopback. That pair is exactly what a real deployment must not copy.

---

## 7. What this does not cover

No CI pipeline, no registry or image-promotion policy, no orchestration
manifests, no secret manager, no backup or restore procedure, and no
observability beyond the logs uvicorn writes to stdout. Each is a real decision
and none is blocked by anything here.

The `receipts` console script is also still unresolved: `pyproject.toml`
declares it and the distribution records the entry point, but no wrapper is
generated in some environments. Use `python -m receipts.cli` until that is
settled.
