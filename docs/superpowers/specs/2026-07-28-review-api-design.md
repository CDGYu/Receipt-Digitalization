# P4.T3 — `review/api.py`, session auth, and role checks

**Date:** 2026-07-28 · **Branch:** `feat/service` · **Status:** approved, not yet implemented
**Implements:** SPEC §14.9 (review API), the P4.T2 auth decision, and the P4.T3 fold-ins.

---

## 1. Context

Phase 4 has `process_receipt`, the RQ worker, and the two VLM guards (P4.T4,
ADR-0011). What is missing is the service that a human and a machine talk to: the
FastAPI app of §14.9, the auth the user decided on 2026-07-28 (session auth with
`reviewer`/`admin` roles, plus a separate API key for machine upload), and the
three fold-ins recorded against this task.

Exploration turned up two facts that change what this task is:

- **No identity exists anywhere.** The seven-table ORM has no `users`, and
  nothing in `src/` or `config/` mentions roles or credentials. Session auth
  needs somewhere for accounts to live — which matters precisely because
  `corrections.corrected_by` is the audit trail the auth decision was made to
  protect.
- **The confidence explanation cannot be recomputed at read time.**
  `explain_confidence` needs the `TriageResult` and `receipt.meta.ambiguous_fields`;
  neither is persisted. `legibility`, `is_handwritten` and the findings are, so a
  read-time recompute would systematically under-penalize and hand a reviewer a
  breakdown that does not sum to the stored `confidence`.

Both were settled by the user, along with the permission matrix and whether
`/upload` writes a row. Those four decisions are §2.

## 2. Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | Accounts live in a new **`users` table** (8th table) + Alembic revision | The audit trail is the reason session auth was chosen; a real account is what `corrections.corrected_by` should point at. Env-declared users make a password change a redeploy; an external IdP blocks this task on infrastructure that does not exist. |
| D2 | **Persist the confidence reasons** at process time in a new `receipts.confidence_reasons` column | The only way `GET /receipts/{id}` can show a breakdown that provably sums to the stored score. The alternative shows a confident wrong number on the screen where a human decides. |
| D3 | **admin = `/export/xlsx` + user management**; reviewer+admin = everything else; the API key authorizes **`POST /upload` and nothing else** | Bulk egress of every receipt's financials is the one operation worth separating. The key is a machine, not a person, so it must never be able to write a correction. |
| D4 | **`POST /upload` inserts a `PENDING` receipt row** before queueing | A job the queue loses otherwise leaves a blob on disk and nothing in the database — a vanished job, invisible to every query. A stuck `PENDING` row is visible, and `receipts process`/`reprocess` (P4.T5) can find it. |

D4's cost is explicit: `save_extraction` becomes update-or-insert, which changes
already-reviewed P4.T4 code. `_persist_failure` already updates an existing row
in place, so the shape is not new — but `_persist_outcome` and
`_persist_duplicate` both insert today and both must tolerate the pending row.

## 3. Architecture

### 3.1 App factory with injected collaborators

```python
def create_app(
    *,
    session_factory: Callable[[], Session],
    storage: StorageBackend,
    submit: Callable[[ReceiptJob], object] | None = None,
    settings: Settings | None = None,
) -> FastAPI
```

The same injection `process_receipt` uses. Tests build an app over SQLite +
`LocalStorage(tmp_path)` + a recording `submit`; no Redis, no network, no
monkeypatching of module globals. The conventional FastAPI alternative — a
module-level `app` plus `dependency_overrides` — makes tests mutate global state,
which fights every other module in this codebase.

`submit` defaults to the RQ enqueue in `receipts.worker`, imported lazily behind
the existing `worker` extra, so `POST /upload` never runs a model call inline and
`python -m pytest` stays offline.

`create_app` **raises at construction** when `SESSION_SECRET` is unset. A random
per-process default would log every user out on restart and hide the
misconfiguration; failing at startup is the honest behaviour.

### 3.2 Modules — one purpose each

| File | Purpose |
|---|---|
| `persist/models.py` | `+User`, `+Receipt.confidence_reasons` |
| `alembic/versions/<rev>_users_and_confidence_reasons.py` | one revision, both changes, `down_revision = b9342906a5a6` |
| `persist/users.py` | `create_user`, `get_user`, `verify_credentials`, `set_role`, `deactivate`, `list_users` — §14.8 conventions: session first, **caller commits**, `ValueError` boundary. Plus a `__main__` bootstrap (§7). |
| `review/auth.py` | scrypt hash/verify, session wiring, and the three dependencies: `require_user`, `require_role("admin")`, `require_upload` |
| `review/schemas.py` | request/response models |
| `review/serializers.py` | ORM → response payloads; ORM → `(ReceiptExtraction, ReceiptExportRow)` for export |
| `review/api.py` | `create_app` + the routes |
| `pipeline.py`, `persist/repository.py` | persist `confidence_reasons`; `create_pending_receipt`; `get_findings`; `save_extraction` update-or-insert |

New `api` extra: `fastapi`, `python-multipart`, `itsdangerous`, `uvicorn`;
`httpx` added to `dev` for `TestClient`. The base install is unchanged. API tests
guard with `importorskip`, matching the pipeline tests, and CI installs
`.[dev,pipeline,api]`.

## 4. Data model

### 4.1 `users`

```
id            UUID     primary key
username      Text     UNIQUE, not null
password_hash Text     not null
role          String(16) not null      -- 'reviewer' | 'admin'
is_active     Boolean  not null, default true
created_at    timestamptz not null
updated_at    timestamptz not null
```

`role` is deliberately **not** a database ENUM. The `compare_metadata` drift
guard runs on SQLite only and cannot see a new ENUM member, so an ENUM here would
pass locally and fail on Postgres — the trap already recorded in `docs/MEMORY.md`.
Validation lives in Python, next to the role constants the guards use.

Hashing is stdlib `hashlib.scrypt` (n=2¹⁴, r=8, p=1) with a per-user random salt,
stored as `scrypt$n$r$p$<salt_b64>$<hash_b64>` and verified with
`hmac.compare_digest`. No passlib, no bcrypt, no new dependency. An unknown
username still runs a dummy hash, so login timing does not enumerate accounts.

### 4.2 `receipts.confidence_reasons`

Portable JSON/JSONB (the existing `_jsonb()` helper), **nullable**:

```json
[{"reason": "validation error", "penalty": "-0.35"},
 {"reason": "poor legibility",  "penalty": "-0.20"}]
```

Penalties are strings so `Decimal` survives the round trip (ADR-0001). The column
is nullable on purpose: `NULL` means *not recorded* (a row written before this
migration), `[]` means *nothing lowered the score* — a genuinely clean receipt.
Collapsing the two would let the API tell a reviewer "no reasons" about a row
that never captured them.

`process_receipt` already holds every input `explain_confidence` needs at the
moment it calls `score_confidence`, so this is one extra call threaded through
`save_extraction`.

## 5. Auth

### 5.1 Sessions

Starlette `SessionMiddleware`, signed with `SESSION_SECRET`. Cookie is
`httponly`, `samesite=lax`, and `secure` by default (`SESSION_COOKIE_SECURE=false`
for local dev over http).

The cookie carries the **username only**. The role and `is_active` are re-read
from the database on every request, so a demotion or a deactivation takes effect
immediately instead of whenever a cookie happens to expire.

This forces `POST /auth/login` and `POST /auth/logout`, which §14.9 does not
list — session auth is unimplementable without them. Recorded as deliberate spec
drift (§9).

### 5.2 The machine key

`X-API-Key` compared against `RECEIPTS_API_KEY` with `hmac.compare_digest`. It
authorizes `POST /upload` and nothing else: it cannot read a receipt, cannot
`PATCH`, cannot claim review work.

**If `RECEIPTS_API_KEY` is unset, the header path is rejected outright** — never
"unset key equals unset header", which is the standard way this becomes an open
door.

### 5.3 Permission matrix (D3)

```
route                       key  reviewer  admin
--------------------------------------------------
GET  /health                 y      y       y      (open)
POST /auth/login             y      y       y      (open)
POST /auth/logout            -      y       y
POST /upload                 y      y       y
GET  /receipts               -      y       y
GET  /receipts/{id}          -      y       y
PATCH /receipts/{id}         -      y       y
GET  /receipts/{id}/image    -      y       y
GET  /review/next            -      y       y
POST /review/{id}/complete   -      y       y
GET  /metrics                -      y       y
GET  /export/xlsx            -      -       y
```

### 5.4 Accepted limits

- **CSRF:** `SameSite=Lax` plus a required JSON content-type on state-changing
  routes. Proportionate for an internal tool behind a session cookie; stated
  rather than dressed up as a token scheme that is not there.
- **No login rate limiting.** Worth adding when this faces anything but a LAN.

## 6. Routes

| Route | Behaviour |
|---|---|
| `GET /health` | version + `SELECT 1`; **503** when the database is unreachable |
| `POST /auth/login` | JSON credentials → session; **401** identical for unknown user, wrong password, and deactivated account |
| `POST /auth/logout` | clears the cookie, **204** |
| `POST /upload` | bounded read → `ingest_bytes(..., max_mb=settings.max_upload_mb)` → `create_pending_receipt` → `submit(job)` → **202** `{receipt_id, image_key, status: "pending"}` (§6.4) |
| `GET /receipts` | `query_receipts` filters (`status`, `merchant_id`, `date_from`, `date_to`, `min_confidence`); `limit` capped at 200; fetches `limit+1` to report `has_more` without a `COUNT(*)` per page |
| `GET /receipts/{id}` | record + line items + findings + `confidence_reasons`; **404** unknown |
| `PATCH /receipts/{id}` | `apply_corrections(..., corrected_by=<session username>)`; `ValueError` → **400**; returns the re-read record |
| `GET /receipts/{id}/image` | `{"url": ...}` — an app-signed expiring link (§6.1) |
| `GET /review/next` | `next_task(assignee=username)` plus a compact receipt payload in the same response; `{"task": null}` when the queue is empty |
| `POST /review/{id}/complete` | `{id}` is the **task** id (it follows `/review/next` in §14.9); assignee or admin only, else **403**; `close_task` is already idempotent |
| `GET /export/xlsx` | filtered rows → `export_workbook` → streamed file (§6.3) |
| `GET /metrics` | `queue_stats` + counts by status + auto-approval rate (§6.2) |

### 6.1 The image URL is app-signed, not `storage.url()`

`LocalStorage.url()` returns a `file://` URI — unusable in a browser and a
disclosure of server paths — while `S3Storage.url()` presigns properly, so the
two backends would behave differently in the review UI.

`GET /receipts/{id}/image` instead returns a link to a blob sub-route carrying
`exp` and an HMAC over `(receipt_id, variant, exp)`, keyed by `SESSION_SECRET`.
The blob route requires **no session** — that is the point, it goes in an `<img>`
tag — but the signature pins it to one receipt, so it cannot be used to walk the
store. Expiry is `IMAGE_URL_TTL_S` (default 300s). `?variant=processed` falls back
to the original when `processed_image_key` is null.

### 6.2 `/metrics` returns `null`, not `0`, for an undefined rate

Zero receipts means the auto-approval rate is undefined. Reporting `1.0` on an
empty set is exactly the artifact currently sitting untracked in `eval/results/`.
The response also echoes the routing thresholds from `Settings`.

### 6.3 `/export/xlsx` refuses rather than truncates

Past `_EXPORT_MAX_ROWS` (5000 — the bound the deferred `write_only` streaming
note already names) the route returns **400** telling the caller to narrow the
filter. A silently truncated export reads as a complete ledger.

Rows are built by `serializers` from the ORM columns: `ReceiptExtraction` for the
data sheets and `ReceiptExportRow` for status/confidence/review metadata, with
`review_reason`/`review_priority` joined from `review_tasks`. The mapping is
lossy against the full extraction schema (`tax_breakdown`, `prices_include_tax`,
`ambiguous_fields`, merchant address/TIN are not columns) but **lossless for every
§13 header**, which is the contract that matters: the database is the source of
truth and Excel is output only (ADR-0010 keeps export decoupled from the ORM —
the serializer lives on the API side of that boundary, not inside `export/`).

Image links in the workbook use `EXPORT_IMAGE_URL_TTL_S` (default 24h), and the
documentation says plainly that anyone holding the workbook can open those images
until it expires.

### 6.4 The pending row carries no data, and must not be mistaken for one

`create_pending_receipt` writes `status=PENDING`, `confidence=0`, the `image_key`
from the job, and `image_phash=""` — the perceptual hash is computed in the
worker's preprocess stage and inventing one here would be a value nothing read
off the image. `find_duplicate_by_phash` already skips empty hashes, so a pending
row can never become the "original" that a later upload is marked a duplicate of.

`GET /receipts` lists pending rows by default: visibility is the entire point of
D4. `GET /export/xlsx` **excludes `PENDING` and `REJECTED` unless `status=` asks
for them explicitly** — a pending row is an upload in flight rather than a
transaction, and a rejected one is a duplicate the pipeline deliberately keeps
out of exports.

### 6.5 Serialization

Money **and** confidence serialize as strings, matching the golden labels. On
`PATCH`, a JSON *number* for a money field is rejected with **422** and a message
saying to send it as a string: `json.loads` produces a `float`, and quietly
converting it would reintroduce the drift ADR-0001 exists to prevent.
`_coerce_money` stays the last line of defence, not the first.

### 6.6 Error contract

One handler, mapping the layer's existing conventions: `ValueError` from the
repository/queue → **400**; unknown id → **404**; missing or invalid credentials →
**401**; wrong role → **403**; upload rejection → **400** carrying the ingest
reason; database unreachable → **503**. No traceback, no storage path, and no SQL
in a response body.

## 7. Bootstrapping the first admin

`python -m receipts.persist.users create <username> --role admin`, reading the
password from stdin (never `argv` — that lands in shell history and `ps`).
P4.T5 wraps this as `receipts users add`; the logic lives in `persist/users.py`
either way.

## 8. Fold-ins

Agreed with the task, plus three found while exploring:

1. **`enqueue_review` insert-safe.** Insert inside `session.begin_nested()`
   (SAVEPOINT); on `IntegrityError`, re-select and apply the same
   more-urgent-wins update. Portable across SQLite and Postgres; ADR-0008
   semantics unchanged.
2. **Thresholds consolidated — there are four copies, not three:** `route()`
   defaults, `Settings`, `eval/metrics.py:39`, and `export/xlsx.py:67`
   (`_CONFIDENCE_FLOOR`). A new `score/thresholds.py` holds the two constants and
   all four import it. Not the reverse: putting them in `Settings` would make a
   pure domain module depend on environment config.
3. **`CostGuard._as_money` gains the `is_finite()` gate** (ADR-0011's recorded
   gap): a `Decimal("NaN")` cost makes `spent` NaN, and `NaN >= ceiling` is always
   `False`, so the ceiling would silently never fire.
4. **`ingest_bytes` / `ingest_file` gain `max_mb`.** They hardcode
   `_DEFAULT_MAX_MB` today, so `MAX_UPLOAD_MB` is unenforceable from the API.
   `POST /upload` depends on this one, and `GET /metrics` on the thresholds
   above — which is why T3b lands before the routes.
5. **`get_findings` added to the repository.** `GET /receipts/{id}` needs findings
   and there is no read helper for them.
6. **Delete `eval/results/2026-07-27-1.0.0.json`** — an empty-set artifact
   reporting `auto_approval_precision: 1.0` on zero receipts. Untracked; never
   commit or cite it.

## 9. Spec drift to absorb

- **§17** gains `VLM_MAX_CONCURRENCY`, `MAX_COST_USD_PER_RECEIPT`, `STORAGE_ROOT`
  (already drifted, ADR-0011) plus `SESSION_SECRET`, `RECEIPTS_API_KEY`,
  `SESSION_COOKIE_SECURE`, `IMAGE_URL_TTL_S`, `EXPORT_IMAGE_URL_TTL_S`.
- **§14.9** gains `POST /auth/login`, `POST /auth/logout`, and the image blob
  sub-route.
- **§6** gains the `users` table and `receipts.confidence_reasons`.
- A new ADR (0012) records D1–D4, the app-factory shape, and the app-signed image
  URL.

## 10. Testing

Offline, TDD, SQLite + `LocalStorage(tmp_path)` + a fake `submit`. `python -m
pytest` must stay green with no Redis and no network.

The centrepiece is a **table-driven auth matrix**: every route × {no credentials,
API key, reviewer, admin} asserting 401 / 403 / allowed against §5.3. A route
added without an explicit decision fails it.

Then, per area:

- **Auth:** login sets a session; logout clears it; a deactivated user's existing
  cookie stops working on the next request; an unknown user and a wrong password
  are indistinguishable; an unset `RECEIPTS_API_KEY` rejects both a missing and
  an empty `X-API-Key`; `create_app` raises without `SESSION_SECRET`.
- **Upload:** a `PENDING` row exists before `submit` is called; an oversized file
  is rejected at `settings.max_upload_mb`; a rejected upload writes no row; the
  worker's persist path updates that row rather than colliding on the primary key
  (and does not duplicate it on a re-run).
- **Receipts:** filters compose; `has_more` paginates; `GET /receipts/{id}`
  returns findings and reasons, and distinguishes `NULL` from `[]`; `PATCH`
  writes a `corrections` row attributed to the **session user** — the whole point
  of the auth model; a JSON float for money returns 422.
- **Image:** a valid signature streams bytes; an expired one and a tampered one
  are rejected; a signature for receipt A does not open receipt B.
- **Review:** `/review/next` claims one task per caller; a second caller gets a
  different task or null; completing someone else's task is 403 for a reviewer
  and allowed for an admin; double-complete does not move `closed_at`.
- **Export:** admin only; over the row cap returns 400 rather than truncating;
  the workbook has all four sheets.
- **Metrics:** an empty database returns `null` rates, not `0` or `1.0`.
- **Fold-ins:** two concurrent `enqueue_review` calls for one receipt both
  succeed; `CostGuard` rejects a non-finite cost; the four threshold copies are
  one import.

## 11. Task split

Sequential, one fresh `general-purpose` implementer subagent each, commit per
task, controller re-runs `pytest` + `ruff` independently after each.

| Task | Scope |
|---|---|
| **T3a — schema** | `users` table, `confidence_reasons` column, one Alembic revision, `persist/users.py` (+ bootstrap `__main__`), `save_extraction` update-or-insert + `confidence_reasons`, `create_pending_receipt`, `get_findings`, `process_receipt` passing the reasons |
| **T3b — shared fixes** | The four small fold-ins: `enqueue_review` SAVEPOINT, `score/thresholds.py` consolidation across all four copies, `CostGuard.is_finite()`, `ingest` `max_mb`. Independent of the API, and the API depends on two of them |
| **T3c — auth** | `review/auth.py`, login/logout, the three dependencies, the role constants, and the auth-matrix harness |
| **T3d — routes** | `review/api.py`, `schemas.py`, `serializers.py`: all remaining routes, image signing, export |

Then, controller-side: ADR-0012, the §9 spec edits, `docs/MEMORY.md` and the
progress ledger, and deleting the vacuous eval artifact.

## 12. Out of scope

Frontend (P5), `cli.py` (P4.T5/T6), merchant registry (P6), self-consistency
(P7), calibration (P8, blocked on ISSUE-001). No accuracy claim is made or
implied by this task: there are still no measured numbers until ISSUE-001 runs.
