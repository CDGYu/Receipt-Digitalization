# Deploying the receipt service

The service is one image that runs either half: the review API, or the queue
worker. The decision and its reasoning are **ADR-0036**; the entry point it
serves is **ADR-0035**.

Everything below was run against the image built from this repository on
2026-08-11, and §4 and §6 were **re-run end to end on 2026-08-25** on the
compose stack — every command in §6 was executed and its output read, not
recalled. **Re-derive rather than trust** (ADR-0028 rule 1) — the commands are
here so you can.

**If you just want to start it**, skip to **§6**, which is the ordered runbook.
§1–§5 are what a real deployment has to know; §6 is the local stack.

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

Re-verified on 2026-08-25 against the compose stack (§6), via `curl` against
`localhost:8000` and a Playwright load of `/app/`. The first three rows above
still hold; the fourth was **not** re-run, and stays a 2026-08-11 observation.
What was added:

| request | result |
|---|---|
| `POST /auth/login` with a real account | `200 {"username":...,"role":"admin"}` + session cookie |
| `GET /auth/me` with that cookie | `200` — same body |
| `GET /receipts`, `GET /metrics` with that cookie | `200`, real rows |
| `POST /upload` (multipart `file=@…jpg`) | `202 {"receipts":[{"receipt_id":…,"image_key":…}],"status":"pending"}` |
| `GET /receipts/{id}/progress` right after | `200 {"status":"pending","stage":"triage","detail":null}` |
| the worker's log, same moment | `Processing receipt {id} from api` — it picked the job up |
| `/app/` in a browser, anonymous | sign-in form renders; **two 401s in the console** (`/metrics`, `/auth/me`) |

Those two console 401s are **expected, not a fault**: `GET /auth/me` is
deliberately inside `require_user`, so an anonymous cold load always logs one —
`build_auth_router`'s docstring records the trade and ADR-0026 is the decision.

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

## 6. Running the whole system locally — the ordered runbook

`docker-compose.yml` runs all five pieces: Postgres, Redis, the API, the queue
worker, and Ollama. **Every step below is required on a fresh machine**, and
three of them (0, 4, 5) used to be missing from this document — each was found
by a session that could not get the system running without it.

Run the steps in order. Nothing here needs a Python or Node install on the host
**except step 8**, which is the gate suite and runs outside Docker.

---

### Step 0 — create the `ollama` model volume

```
docker volume create ollama
```

The compose file declares this volume **`external: true`** so that pulled
models survive a `docker compose down -v`. The cost is that compose will not
create it: with it absent, **every** compose command fails with

```
external volume "ollama" not found
```

before anything starts. Verified 2026-08-25 with a throwaway compose file
naming a volume that did not exist — the message above is that probe's, with
the name substituted. `docker volume create` on a volume that already exists is
a no-op, so this step is safe to repeat.

### Step 1 — set `SESSION_SECRET`

```
export SESSION_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
```

Compose **refuses to run** rather than inventing one — verified 2026-08-25:

```
error while interpolating services.api.environment.SESSION_SECRET:
required variable SESSION_SECRET is missing a value
```

Three things about this that cost time:

* **`.env` does not contain it** as of 2026-08-25, so the export is not
  optional. Put it in `.env` if you want it to survive a new shell; the
  variable is read by compose, not by the image.
* **It blocks every compose subcommand, not just `up`.** Compose interpolates
  the whole file before it decides which service you meant, so
  `docker compose exec ollama ollama list` fails on it too. Either keep the
  export set, or address a container directly — `docker exec ollama ollama list`
  needs no interpolation and works regardless.
* **Changing it signs every reviewer out**, because it signs the session
  cookie. That is the same property §2 relies on; here it just means don't
  regenerate it casually mid-session.

### Step 2 — build and start

```
docker compose up -d --build
```

Five containers: `receipts-postgres`, `receipts-redis`, `receipts-api`,
`receipts-worker`, `ollama`. Postgres and Redis have healthchecks and the API
and worker `depends_on` them being **healthy**, so the ordering is handled —
you do not need to stagger it.

```
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
```

`receipts-worker` in `Restarting` and `receipts-postgres`/`receipts-redis` in
`Exited` is the signature of a stack that was left half-up (the worker cannot
reach a broker that is not running); `docker compose up -d` again fixes it.

### Step 3 — migrate

```
docker compose run --rm api python -m alembic upgrade head
```

Nothing in the compose file runs migrations, deliberately (§3). Run this after
**every** `git pull` as well as on a fresh database — on 2026-08-25 a stack that
had been up for 18 hours still needed `c7f1a9e4d208, receipt progress
heartbeat` applied.

### Step 4 — create an account

**Without this you cannot sign in at all**, and there is no bootstrap account,
no seeded admin, and no self-registration route. This is the step most likely to
be missing when someone reports "the UI just shows a login form".

```
# does one already exist?
docker compose run --rm -T api receipts users list

# create one -- the password comes from stdin, never a flag
echo "your-password-here" | docker compose run --rm -T api receipts users add alice --role admin
```

`-T` matters: without it compose allocates a TTY, `_read_password` sees an
interactive terminal and prompts instead of reading the pipe. Roles are
`admin` and `reviewer`; `--role` defaults to `reviewer`. There is no
`--password` flag and `receipts users add` will never grow one — it would land
in shell history and in `ps`.

### Step 5 — pull the vision model

```
docker exec ollama ollama pull granite3.2-vision:2b
docker exec ollama ollama list
```

This is the model the `worker` service names in **both** `VLM_MODEL_EXTRACT`
and `VLM_MODEL_TRIAGE`. Without it every triage call fails at the model layer —
the API still accepts uploads and the worker still picks them up, so the failure
shows up as a stuck receipt rather than a startup error.

**Two Ollamas are easy to confuse.** This project reads the **Docker** one,
published on **`localhost:11435`** (`11434` is left free for a Windows-native
install, which the project does not read). Inside the compose network the
worker addresses it as `http://ollama:11434/v1` — the service name and the
*container* port, not the published one. From the host:

```
curl -s http://localhost:11435/api/tags
```

The `:cloud` entries Ollama also lists are **not** used by this stack. Cloud
egress is authorised for the golden-set evaluation alone; routing an uploaded
receipt to a hosted model is a decision nobody has taken.

### Step 6 — smoke-test the API

```
curl -s http://localhost:8000/health                 # {"status":"ok"}
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/app/   # 200
curl -s http://localhost:8000/receipts               # 401, no session

curl -s -c cookies.txt -H 'Content-Type: application/json' \
     -d '{"username":"alice","password":"your-password-here"}' \
     http://localhost:8000/auth/login                # 200 + Set-Cookie

curl -s -b cookies.txt http://localhost:8000/metrics
```

All five verified 2026-08-25 — see the second table in §4 for the bodies.

### Step 7 — drive it: upload a receipt end to end

```
curl -s -b cookies.txt -F "file=@eval/golden/images/r001.jpg" \
     http://localhost:8000/upload
# 202 {"receipts":[{"receipt_id":"<id>","image_key":"receipts/2026/08/<id>/original.jpg"}],
#      "status":"pending"}

curl -s -b cookies.txt http://localhost:8000/receipts/<id>/progress
docker logs receipts-worker --tail 5
```

Or do it in a browser: **<http://localhost:8000/app/>**, sign in, and use the
Upload screen. Both paths reach the same queue.

**Expect it to take roughly half an hour, and do not read that as a hang.**
Inference here is CPU-only — ADR-0039 measured **~1896s per receipt** on this
box and rules local inference a *liveness check, never a measurement*. The way
to tell "working" from "wedged" is the model container's CPU:

```
docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}'
```

Measured 2026-08-25 while a real upload was in `stage: triage`: `ollama` at
**195% CPU / 3.94 GiB**, every other container near zero. That is the pipeline
running. `VLM_TIMEOUT_S: "3600"` in the compose file exists for exactly this,
and it derives three other timeouts — the comment on that line in
`docker-compose.yml` has the four numbers and why the 4.5-day unstarted window
is the one to watch.

#### What that upload actually did, measured

**It did not produce an extraction, and you should expect the same.** Receipt
`9a21e64d`, `eval/golden/images/r001.jpg`, on 2026-08-25, from the worker's own
timestamps:

| t | event |
|---|---|
| `06:44:44` | `Processing receipt 9a21e64d… from api` |
| `07:05:43` | `POST http://ollama:11434/v1/chat/completions "HTTP/1.1 200 OK"`, then the OpenAI SDK **retries** |
| `07:06:44` | `killed horse pid 14` — `Work-horse terminated unexpectedly; waitpid returned None` |

**1320s, and the job died.** The receipt is nonetheless terminal —
`status: needs_review`, `stage: extract`, `confidence: 0.000`, every field
`null`, no line items, no findings.

Three things follow, and the order matters:

* **This was NOT the job ceiling.** Verified by calling the real function in
  the running container rather than doing the arithmetic: `VLM_TIMEOUT_S=3600`
  gives `job_timeout_for(settings) = 32580` — 9.05 hours. The horse died at
  1320s, 4% of the way to it. **ISSUE-029's fix is in place and is not the
  cause here**; do not "fix" this by raising the ceiling again.
* **The terminal-state guarantee fired — but it fired for the wrong reason,
  and an earlier version of this section wrongly called that a success.** The
  receipt did reach a terminal state, and a SIGKILLed work-horse raises no
  Python exception, so before ADR-0054 it would have sat `pending` forever.
  What actually marked it, though, was not the pipeline noticing a dead job. It
  was **`receipts.sweep.strand_receipt`, called from the API's progress route,
  deciding the receipt was too old** — identified from the discriminator rather
  than assumed, because `_persist_failure` and `strand_receipt` write different
  rows:

  ```
  review_tasks.priority -> 1   (_STRANDED_PRIORITY, sweep.py:59)
  review_tasks.reason   -> "processing was interrupted at extract and never resumed"
                           (sweep.py:110, verbatim)
  ```

  **And it should not have been able to reach that conclusion**, which is the
  next bullet.

* **The API and the worker disagree about what "too long" means, by a factor
  of 30.** `docker-compose.yml` sets the `VLM_*` block on the **`worker`
  service only**, so the API container runs the 120s default. Measured by
  calling `_cutoffs` inside each running container, not by arithmetic:

  | container | `vlm_timeout_s` | `started_cutoff` |
  |---|---|---|
  | `worker` | 3600 | **21600s** (6h) |
  | `api` | 120 (unset → default) | **720s** (12 min) |

  The worker will spend hours on one model call. The API's progress route
  sweeps its own row and gives up after **twelve minutes**. A receipt well
  inside the worker's budget is far outside the API's.

* **So this is the default outcome on this box, not bad luck.** The heartbeat
  (`receipts.progress_at`) updates per stage, not during a model call —
  measured on a healthy in-flight receipt whose heartbeat age tracked elapsed
  time 1:1 at 353s while the worker was actively working it. Triage alone
  measured **1259s** on `9a21e64d`. So a perfectly healthy receipt crosses the
  API's 720s line roughly **nine minutes before triage can finish**, and
  **anyone opening the processing screen at that moment strands it** — which is
  the exact screen the single-row sweep was added to serve.

  **Do not read a stranded receipt here as a dead worker.** Check
  `docker logs receipts-worker` for `killed horse` first; without it, the job
  is very likely still running and the row is simply wrong.

* **Editing `docker-compose.yml` fixes nothing until the container is
  recreated**, and this is the trap the above walked into twice. The `api`
  service was given `VLM_TIMEOUT_S: "3600"` on 2026-08-25, and **the running
  container kept `120` afterwards** — measured inside it, not read off the
  file:

  ```
  docker compose exec api python -c "from config.settings import Settings; print(Settings().vlm_timeout_s)"
  ```

  Recreate just the one service, leaving the worker and anything it is
  mid-receipt on untouched:

  ```
  docker compose up -d --no-deps api
  ```

  **Always ask the running container what it thinks, not the file.** The whole
  defect above was two containers disagreeing about one value, and every
  instrument that reads the repository rather than the runtime — including
  `git show`, including this document — would have said they agreed.
* **The cause of the kill is NOT established.** The leading hypothesis is the
  kernel OOM killer — 7.59 GiB total on this box, `ollama` already holding 3.94
  GiB, and the horse died 61s into a retry that would ask for a second
  inference. But the container's own `OOMKilled` flag is `false` with 0
  restarts, which is consistent with the *child* being killed while PID 1
  survived and is **not** evidence for OOM. Nobody has measured it. Treat it as
  a lead.

So: on this hardware the runbook above proves the **plumbing** end to end —
auth, upload, blob, queue, worker, a real HTTP 200 from a real model, and a
terminal state instead of an indefinite `pending`. It does **not** demonstrate
a working extraction, and no run on this box has. It does **not** demonstrate
the terminal-state guarantee behaving correctly either — the state was reached
by a premature strand, and a reader who took it as the guarantee working would
inherit a wrong model of it. ADR-0039 already rules local inference a liveness
check and never a measurement; this is what that looks like from the operator's
side.

**One more thing the operator cannot see.** `extraction_runs` was unchanged at
3 across all of this — the killed horse wrote nothing on its way out. So a
receipt with every field `null` carries **no database evidence that a run was
ever attempted**. The only record is the worker log, which is not persisted
anywhere. If you need to know whether a receipt was tried, capture
`docker logs receipts-worker` before the container is replaced.

### Step 8 — run the gates

On the **host**, not in a container:

```
python scripts/verify.py
```

Five gates, and it names each one and its command:

```
PASS    pytest     python -m pytest
PASS    ruff       python -m ruff check .
PASS    typecheck  npm run typecheck
PASS    vitest     npm test
PASS    build      npm run build
```

Run twice on 2026-08-25, **all five PASS both times**: once at `3d0a979`, and
again at `824bf46` after a frontend commit landed. Needs `pip install -e
".[dev]"` and an `npm install` in `frontend/`; the npm gates skip rather than
fail if npm is absent, so read the summary line — "every gate that **ran**
passed" is not the same claim as five PASS rows.

**Always name the commit a gate run covered.** Three of those five gates read
`frontend/`, so a green from before a frontend commit does not certify the tree
after it — the second run above exists precisely because the first had gone
stale that way. And the gates read the **working tree, not `HEAD`**: a run is
only a statement about a commit if the tree was otherwise clean, which is worth
checking with `git status --porcelain` before quoting the result.

**`scripts/verify.py` does not run Playwright**, and green gates have twice
shipped defects a person could see in a browser and no gate could — a contrast
regression under the accessibility floor, and a zero-width table column. On any
visual change, load `/app/` and look at it.

### Teardown

```
docker compose down          # keeps the database and the blobs
docker compose down -v       # also drops receipts_pgdata and receipts_blobs
```

Neither removes the `ollama` volume — it is external (step 0), which is the
point: `down -v` will not cost you the model pull.

---

### What this stack does that a real deployment must not copy

The `api` service sets `SESSION_COOKIE_SECURE=false` **and**
`ALLOW_INSECURE_SESSION_COOKIE=true`, because the stack is plain HTTP on
loopback. That pair is exactly what §2's escape hatches exist to make
deliberate — and exactly what a deployment behind TLS sets neither of.
Postgres also runs with the password `receipts`, and `5432` and `6379` are
published to the host.

---

## 7. When it does not work

| symptom | cause | fix |
|---|---|---|
| any `docker compose` command: `external volume "ollama" not found` | the model volume was never created | step 0 |
| any `docker compose` command: `required variable SESSION_SECRET is missing a value` | not exported, and not in `.env` | step 1 — or use `docker exec` to skip interpolation |
| `receipts-worker` restarting, Postgres/Redis exited | half-up stack; the worker cannot reach the broker | `docker compose up -d` |
| the UI only ever shows the sign-in form | no account exists | step 4 |
| `/app/` logs two 401s on load | `/auth/me` and `/metrics` fired anonymously | nothing — expected, ADR-0026 |
| a receipt sits at `stage: triage` forever | either the model was never pulled, or it is simply slow | `docker exec ollama ollama list`, then `docker stats` — high `ollama` CPU means it is working |
| a receipt reaches `needs_review` with every field `null` and `confidence 0.000` | the work-horse was killed mid-pipeline; the terminal-state guarantee marked it rather than leaving it stuck | `docker logs receipts-worker` and look for `killed horse` — see §6 step 7. **Not** the job ceiling; check `job_timeout_for` before assuming it is |
| `receipts users add` hangs with no output | a TTY was allocated, so `_read_password` took the `getpass` branch instead of reading the pipe | add `-T` to `docker compose run` |

**Which of those were actually seen, and which are derived.** Rows 2, 3, 5 and
**7** were observed directly on 2026-08-25 — row 7 on receipt `9a21e64d`, with
the worker's timestamps in §6 step 7. Row 1's message was produced by a
throwaway compose file naming a volume that did not exist, not by removing the
`ollama` volume — the name in the table is substituted. Rows 4, 6 and 8 are
derived from the code (`build_auth_router` has no bootstrap account and no
registration route; `_read_password` branches on `isatty()`) and were **not**
reproduced. Treat the derived rows as leads, not as findings.

**Row 7's *cause* is a lead even though the row itself was observed.** That the
horse was killed and the receipt still went terminal is measured; *why* it was
killed is not. The two halves of that row have different standing.

---

## 8. What this does not cover

No CI pipeline, no registry or image-promotion policy, no orchestration
manifests, no secret manager, no backup or restore procedure, and no
observability beyond the logs uvicorn writes to stdout. Each is a real decision
and none is blocked by anything here.

None of this affects the `receipts` console script, which **works**: the wrapper
is generated into the scripts directory of whichever install the package went
into, and on a `--user` install that is not the directory a system-wide `PATH`
points at (ADR-0014's consequences, and ADR-0035's closing note). Inside the
image this does not arise — the package is installed system-wide, so `receipts`
is on `PATH` as a command.
