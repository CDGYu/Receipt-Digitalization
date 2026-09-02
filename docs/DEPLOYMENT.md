# Running the receipt service

The system is two processes over shared infrastructure: the review **API**
(`uvicorn receipts.asgi:app`) and the queue **worker** (`python -m
receipts.worker`). Both read the same `.env`. The entry point is **ADR-0035**;
the app object it serves builds nothing at import time (**ADR-0014**).

Everything runs **natively on the host** — no containers. The three pieces of
infrastructure (a database, Redis, and Ollama) run as ordinary host services,
and the two Python processes read them through their URLs.

**If you just want to start it**, skip to **§6**, the ordered runbook. §1–§5 are
what a real deployment has to know; §6 is the local development stack.

---

## 1. Install

```
pip install -e ".[api,worker,pipeline,openai]"
```

What each extra is for:

| extra | what needs it |
|---|---|
| `api` | fastapi, uvicorn, python-multipart, itsdangerous — the review service |
| `worker` | rq, redis. **The API needs this too** — `_default_submit` reaches RQ to *enqueue*, so an API without it fails on every upload |
| `pipeline` | pillow, opencv, heif, pdfium, openpyxl. The **worker's**, not the API's — the API path calls `ingest_bytes`, which imports only stdlib and `.storage` |
| `openai` | the OpenAI-compatible SDK, which is how the client talks to Ollama. Without it the worker can only run `vlm_provider="fake"` |

Add `postgres` (`pip install -e ".[postgres]"`) only if you point `DATABASE_URL`
at Postgres; SQLite needs no driver. The base install plus these extras is all
the runtime needs.

The review UI is a separate build step — see §6 step 6. It is only required if
you set `SERVE_SPA=true`.

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

### Worth setting

| variable | default | notes |
|---|---|---|
| `STORAGE_BACKEND` | `local` | `s3` requires `S3_BUCKET` |
| `STORAGE_ROOT` | `var/blobs` | where local blobs are written, relative to the working directory. Must be writable by the process |
| `FRONTEND_DIST` | `frontend/dist` | where the built UI lives, relative to the working directory. Only read when `SERVE_SPA=true` |
| `RECEIPTS_API_KEY` | unset | the machine-upload key. Unset rejects the header path outright |
| `SESSION_TTL_S` | `43200` | 12h. Logout cannot revoke an exfiltrated cookie; this is the exposure window |
| `DOCS_ENABLED` | `false` | `/docs`, `/redoc`, `/openapi.json`. None takes a session or a key |

### Self-consistency, and what it costs

Four settings that matter to the **worker** — `process_receipt` runs there, and
`review/api.py` mentions it in one docstring without ever calling it. Setting
them for the API process gives you four values that read as live and decide
nothing.

| variable | default | notes |
|---|---|---|
| `CONSISTENCY_ENABLED` | `false` | extracts a handwritten or low-legibility receipt `CONSISTENCY_RUNS` times and votes |
| `CONSISTENCY_RUNS` | `3` | the smallest n that can produce a majority; two can only agree or disagree |
| `CONSISTENCY_CRITICAL_RUNS` | `0` | a second, larger n, spent only when a critical field failed to resolve. `0` disables it; any value ≤ `CONSISTENCY_RUNS` is inert |
| `CONSISTENCY_CRITICAL_FIELDS` | the §12 triple | **a JSON array** — see below |

**`CONSISTENCY_ENABLED` is the most expensive flag in the service.** It costs
`CONSISTENCY_RUNS` *extra* model calls on exactly the receipts that are already
slowest, and ADR-0039 measures one extract on a CPU-only box in minutes. Turn it
on deliberately, on hardware that can afford it, and measure — nobody has yet
established that it improves precision here.

**`CONSISTENCY_CRITICAL_RUNS` is spent on demand, not always.** No field can be
sampled on its own — every path comes out of the same whole-receipt call — so
the extra evidence is whole extra passes. The pass runs `CONSISTENCY_RUNS`, and
escalates only when the total, date or merchant came back with **no majority**
and was nulled; then it re-votes over all the runs in hand. A receipt whose
critical fields all resolve still costs `CONSISTENCY_RUNS`.

The trigger is deliberately not "the field was disputed". `disputed` means *not
unanimous*, and these calls run at a non-zero temperature so that the runs
differ — escalating on it would spend the extra passes on nearly every
handwritten receipt, which is what setting `CONSISTENCY_RUNS=5` already does
more simply.

**`CONSISTENCY_CRITICAL_FIELDS` is a JSON array, not a comma-separated list.**
`Settings` is a pydantic `BaseSettings` and the field is a `tuple[str, ...]`, so
the value is parsed as JSON. Measured rather than assumed:

```
CONSISTENCY_CRITICAL_FIELDS=totals.total,receipt.date
  -> SettingsError: error parsing value for field "consistency_critical_fields"
```

The service refuses to boot, which is the right failure — but the syntax catches
people out. Paths use `extract.paths` grammar (`totals.total`,
`line_items[2].qty`). The default is the §12 triple: the same three fields
`score.confidence` penalises for being missing and the eval harness scores as
`critical_correct`.

---

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

**Nothing runs migrations for you.** Run them yourself, before the first
request:

```
python -m alembic upgrade head
```

This is deliberate. A boot path that migrated would have every process race on
startup, and would turn a bad migration into a crashloop rather than one failed
command whose output you can read.

Run it after **every** `git pull` as well as on a fresh database — a schema that
has drifted from the code fails at insert, not at boot.

---

## 4. Run

Two processes, both reading the same `.env`. Run them in separate terminals (or
under a process supervisor):

```
# the API
uvicorn receipts.asgi:app --host 0.0.0.0 --port 8000

# the worker
python -m receipts.worker
```

ADR-0035 deliberately kept host, port and worker count out of the app object:
they belong to the invocation. `--host 0.0.0.0` binds all interfaces; drop it
(uvicorn defaults to `127.0.0.1`) if you only want loopback.

Verified behaviour:

| request | result |
|---|---|
| `GET /health` | `200 {"status":"ok"}` |
| `GET /app/` | `200 text/html` when `SERVE_SPA=true` and the UI is built |
| `GET /receipts` with no session | `401` |
| `python -m receipts.worker` with no broker | fails **connecting** to Redis, not importing |
| `POST /auth/login` with a real account | `200 {"username":...,"role":...}` + session cookie |
| `POST /upload` (multipart `file=@…jpg`) | `202 {"receipts":[{"receipt_id":…,"image_key":…}],"status":"pending"}` |
| `GET /receipts/{id}/progress` right after | `200 {"status":"pending","stage":"triage","detail":null}` |

An anonymous load of `/app/` logs **two 401s** in the browser console
(`/auth/me`, `/metrics`). Those are **expected, not a fault**: `GET /auth/me`
is deliberately inside `require_user`, so an anonymous cold load always logs one
— `build_auth_router`'s docstring records the trade and ADR-0026 is the
decision.

---

## 5. What a real deployment has to provide

* **TLS, terminated upstream.** The service speaks plain HTTP and expects a
  proxy in front. Keep `SESSION_COOKIE_SECURE=true`; the cookie is a bearer
  credential in front of financial records.
* **A writable `STORAGE_ROOT`** (or S3). The worker writes and reads blobs
  there. A SQLite `DATABASE_URL` and the blob directory both need to live
  somewhere the process can write.
* **Process supervision and replicas.** Each `uvicorn` is one process; scale
  with your supervisor (systemd, supervisord, a process manager), not with
  `--workers`, unless you have measured that you want in-process workers. Run as
  many `python -m receipts.worker` processes as you want draining the queue.
* **`/health` is liveness, not readiness.** It does not check Redis, storage, or
  that migrations have run. Do not gate a rollout on it and assume more.

---

## 6. Running the whole system locally — the ordered runbook

Five pieces: a database, Redis, Ollama, the API, and the worker. **Every step
below is required on a fresh machine.** Run them in order — several fail quietly
if skipped (a missing model pull does not fail at start, it fails at the first
receipt).

This assumes Python 3.11+ and, for the UI, Node. Redis and Ollama are installed
however your platform installs them (`apt`, `brew`, `winget`, the Ollama
installer).

### Step 1 — install the package

```
pip install -e ".[api,worker,pipeline,openai]"
```

See §1. Add `.[dev]` too if you plan to run the gate suite (step 8).

### Step 2 — write `.env`

```
cp .env.example .env
```

Then edit it. The three that block boot:

* `DATABASE_URL` — `.env.example` ships `sqlite:///receipts.db`, which needs
  nothing else running. For Postgres, install and start it, create the database,
  and set `postgresql+psycopg://receipts:receipts@localhost:5432/receipts`.
* `REDIS_URL` — `redis://localhost:6379/0`, once Redis is running (step 3).
* `SESSION_SECRET` — generate one; it is empty in the template:

  ```
  python -c "import secrets; print(secrets.token_urlsafe(32))"
  ```

`.env.example` also sets `SESSION_COOKIE_SECURE=false` and
`ALLOW_INSECURE_SESSION_COOKIE=true` for plain-HTTP local work, and
`SERVE_SPA=false` so the API runs without a UI build. Flip `SERVE_SPA` to `true`
once you have done step 6.

### Step 3 — start Redis

```
redis-server            # foreground; or start it as a service
redis-cli ping          # -> PONG
```

The worker fails at **connecting** to Redis, not importing it, so a worker that
exits complaining about a connection is telling you Redis is not up.

### Step 4 — migrate

```
python -m alembic upgrade head
```

Nothing else runs migrations (§3). Re-run after every `git pull`.

### Step 5 — create an account

**Without this you cannot sign in at all** — there is no bootstrap account, no
seeded admin, and no self-registration route. This is the step most likely to be
missing when someone reports "the UI just shows a login form".

```
# does one already exist?
receipts users list

# create one -- the password comes from stdin, never a flag
echo "your-password-here" | receipts users add alice --role admin
```

Roles are `admin` and `reviewer`; `--role` defaults to `reviewer`. There is no
`--password` flag and `receipts users add` will never grow one — it would land
in shell history and in `ps`. If the command hangs with no output, a TTY was
allocated and `_read_password` is waiting at an interactive prompt; pipe the
password in as shown.

### Step 6 — build the review UI (only if you want it)

Skip this if `SERVE_SPA=false`. To serve the UI from the API:

```
cd frontend
npm install
npm run build            # produces frontend/dist
cd ..
```

Then set `SERVE_SPA=true` in `.env`. `frontend/dist` is gitignored, so a fresh
checkout has no `index.html`; with `SERVE_SPA=true` the API refuses to start
until this build exists, rather than 404ing `/app/*` with no explanation.

### Step 7 — pull the vision model

```
ollama serve                              # if not already running as a service
ollama pull granite3.2-vision:2b
ollama list
curl -s http://localhost:11434/api/tags   # confirm the daemon answers
```

This is the model `.env` names in both `VLM_MODEL_EXTRACT` and
`VLM_MODEL_TRIAGE`. Without it every triage call fails at the model layer — the
API still accepts uploads and the worker still picks them up, so the failure
shows up as a **stuck receipt** rather than a startup error.

The native daemon answers on **`localhost:11434`** (Ollama's default), which is
what `VLM_BASE_URL` reads. The `:cloud` entries Ollama also lists are used only
for the golden-set evaluation; routing an uploaded receipt to a hosted model is
a decision to take explicitly, not a default.

### Step 8 — start the two processes and smoke-test

In one terminal:

```
uvicorn receipts.asgi:app --host 0.0.0.0 --port 8000
```

In another:

```
python -m receipts.worker
```

Then:

```
curl -s http://localhost:8000/health                 # {"status":"ok"}
curl -s http://localhost:8000/receipts               # 401, no session

curl -s -c cookies.txt -H 'Content-Type: application/json' \
     -d '{"username":"alice","password":"your-password-here"}' \
     http://localhost:8000/auth/login                # 200 + Set-Cookie

curl -s -b cookies.txt http://localhost:8000/metrics
```

### Step 9 — drive it: upload a receipt end to end

```
curl -s -b cookies.txt -F "file=@eval/golden/images/r001.jpg" \
     http://localhost:8000/upload
# 202 {"receipts":[{"receipt_id":"<id>","image_key":"receipts/2026/08/<id>/original.jpg"}],
#      "status":"pending"}

curl -s -b cookies.txt http://localhost:8000/receipts/<id>/progress
```

Or do it in a browser at **<http://localhost:8000/app/>** (needs step 6). Watch
the worker's terminal — it logs `Processing receipt <id> from api` when it picks
the job up.

**On CPU-only hardware, expect it to take roughly half an hour, and do not read
that as a hang.** ADR-0039 measured **~1896s per receipt** on a CPU-only box and
rules local inference a *liveness check, never a measurement*. The way to tell
"working" from "wedged" is Ollama's CPU: a busy `ollama` process (well above
100% of one core) with the API and worker near idle is the pipeline running.

`VLM_TIMEOUT_S=3600` in `.env` exists for exactly this. It derives three other
timeouts, measured by calling the functions rather than by arithmetic:

```
one_call = 3600 x 3 SDK attempts       = 10800s   (3h)
job ceiling (worker.job_timeout_for)   = 32580s   (9.05h)
sweep started_cutoff                   = 21600s   (6h)
sweep unstarted_cutoff                 = 388800s  (4.5 DAYS)
```

The 4.5-day unstarted window is the one to watch: a receipt enqueued and never
picked up (a dead worker) is not swept until then, and the progress route sweeps
its own row on the same clock, so a waiting screen waits just as long. Lower
`VLM_TIMEOUT_S` and all four come down together.

**Keep the API and worker on the same `VLM_TIMEOUT_S`.** They read the same
`.env`, so they cannot drift here — but the reason the value is shared is a real
defect it caused: when the two disagreed (the API on a 120s default, the worker
on 3600), the API's progress route decided a receipt was stranded after twelve
minutes while the worker was legitimately hours into it, and swept a healthy
receipt to `needs_review`. A single value in one file is what removes that.

#### A stranded receipt is not the same as a dead worker

If a receipt reaches `needs_review` with every field `null`, `confidence 0.000`,
`review_tasks.priority 1`, and reason `processing was interrupted at … and never
resumed`, that is `receipts.sweep.strand_receipt` — the progress route deciding
the receipt was too old, on a `started_cutoff` derived from `VLM_TIMEOUT_S`. The
worker may still be working it. A killed work-horse is a different event: check
the worker's log for a terminated job before concluding the run actually died.
Both can happen at once, which is exactly why they are easy to conflate.

### Step 10 — run the gates

```
python scripts/verify.py
```

Five gates, each named with its command:

```
PASS    pytest     python -m pytest
PASS    ruff       python -m ruff check .
PASS    typecheck  npm run typecheck
PASS    vitest     npm test
PASS    build      npm run build
```

Needs `pip install -e ".[dev]"` and an `npm install` in `frontend/`; the npm
gates skip rather than fail if npm is absent, so read the summary line — "every
gate that **ran** passed" is not the same claim as five PASS rows.

`scripts/verify.py` does **not** run Playwright, and green gates have shipped
defects a person could see in a browser and no gate could — a contrast
regression under the accessibility floor, and a zero-width table column. On any
visual change, load `/app/` and look at it.

---

## 7. When it does not work

| symptom | cause | fix |
|---|---|---|
| `receipts.asgi refuses to start: DATABASE_URL is not set …` | required infra vars missing from `.env` | §2 — set `DATABASE_URL`, `REDIS_URL`, `SESSION_SECRET` |
| the worker exits complaining it cannot connect to Redis | Redis is not running | step 3 — `redis-server`, then `redis-cli ping` |
| the UI only ever shows the sign-in form | no account exists | step 5 |
| `/app/` refuses to start / 404s | `SERVE_SPA=true` with no build | step 6, or set `SERVE_SPA=false` |
| the one-click launcher shows an old UI after editing `frontend/src` | the served bundle in `frontend/dist` was stale | nothing with the launcher — `scripts/launch_app.py` now rebuilds `dist` before starting the API whenever the source is newer. Building by hand instead? re-run `npm run build` (or `npx vite build`) in `frontend/` |
| `/app/` logs two 401s on load | `/auth/me` and `/metrics` fired anonymously | nothing — expected, ADR-0026 |
| a receipt sits at `stage: triage` forever | either the model was never pulled, or it is simply slow | `ollama list`, then watch Ollama's CPU — a busy process means it is working |
| a receipt reaches `needs_review`, every field `null`, `confidence 0.000`, `review_tasks.priority 1`, reason `processing was interrupted at …` | the sweep stranded it on a `started_cutoff` derived from `VLM_TIMEOUT_S`; the worker may still be working it | check the worker's log for a killed job before concluding it died — §6 step 9. **Not** the job ceiling |
| `receipts users add` hangs with no output | a TTY was allocated, so `_read_password` prompts instead of reading the pipe | pipe the password in: `echo "…" | receipts users add …` |

---

## 8. What this does not cover

No CI pipeline, no secret manager, no backup or restore procedure, and no
observability beyond the logs uvicorn writes to stdout. Each is a real decision
and none is blocked by anything here.

None of this affects the `receipts` console script, which **works**: the wrapper
is generated into the scripts directory of whichever install the package went
into, and on a `--user` install that is not the directory a system-wide `PATH`
points at (ADR-0014's consequences, and ADR-0035's closing note). Install into a
virtualenv and `receipts` is on `PATH` as a command.
