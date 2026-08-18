# P5.T0 / P5.T1 — the review UI

**Date:** 2026-07-29 · **Base:** `master @ 94fa023` · **Status:** approved, not yet implemented
**Implements:** IMPLEMENTATION_PLAN P5.T0 (stack decision) and P5.T1 (review screen). SPEC §15 M4.
**Does not implement:** P5.T2 (upload / list / queue / export pages) — a separate task on the same scaffold.

---

## 1. Context

The API this screen consumes is finished and enforced: eleven routes, session
auth with roles, a machine upload key, signed image URLs, and a closed set of
correctable field paths (ADR-0012, ADR-0006). Nothing on the backend needs to
change for the review screen to work — with one exception, §3.3.

Four things were established by reading the code before designing, and two of
them changed the scope the plan describes. They are recorded here because the
plan's prose is reliable and its assumptions about existing APIs are not.

### 1.1 `line_items[].bbox` has no data behind it

`bbox` is declared in `extract/schema.py:76` (*"normalised 0-1 **if model
supports grounding**"*), persisted at `persist/models.py:242`, copied through at
`persist/repository.py:453`, and returned to the client at
`review/serializers.py:109`. **`extract/prompts.py` never mentions it**, and
nothing in `preprocess/` or `lineitem_align` computes it. It is `None` on every
row. `repository.py:926` also excludes it from the correctable map deliberately.

P5.T1's headline requirement — *"bounding-box highlighting from
`line_items[].bbox`"* — therefore has nothing to draw, and
`IMPLEMENTATION_PLAN.md:300` justifies its React recommendation as *"richest
bbox/image UX"*, a rationale that does not survive the finding.

**Decision D2 (below): bbox highlighting is out of scope.** The image pane is
pan/zoom/rotate only. This is deliberately *not* worked around by asking the
model for coordinates, because that costs a `PROMPT_VERSION` bump plus an eval
re-run to prove no regression — and that re-run is blocked on ISSUE-001, so it
would mean shipping an unmeasured prompt change. VLM grounding coordinates are
also unreliable, and wrong boxes cost more reviewer trust than no boxes.

**Connection worth keeping:** this is the same missing capability as the parked
P2.T2 decision. R060/R061 need a raw text layer nothing produces; bbox needs
coordinates nothing produces. A cheap OCR pass would yield both. If P2.T2 is
ever resolved that way, bbox highlighting becomes a small additive change to
this screen rather than a redesign — which is why the screen is built so that
line-item rows are already the highlight unit.

### 1.2 There is no CORS middleware

`review/auth.py:92` installs `SessionMiddleware` with `same_site="lax"`. No
`CORSMiddleware` exists anywhere in the codebase. A Vite dev server on `:5173`
calling an API on `:8000` is cross-origin, so the session cookie would not be
sent and every authenticated request would fail.

**This is designed out rather than middlewared away** — see §3.2. The cookie
configuration is not touched, and no `SameSite=None` / `Secure` downgrade is
introduced.

### 1.3 Corrections never re-run validation

`apply_corrections` (`persist/repository.py:1001`) applies the planned changes,
writes one `corrections` row per **changed** path, sets
`status = ReceiptStatus.REVIEWED`, and commits. It does not touch
`validation_findings`. `PATCH /receipts/{id}` calls `get_findings` afterwards,
but that re-reads the same rows.

So findings go stale the instant a reviewer edits: fix a null total and
`[R010] total is null` is still what comes back.

**Decision D3: the panel is labelled as what the machine found at extraction
time and does not pretend to update.** A dry-run validate endpoint was
considered and deferred (§7).

### 1.4 Money crosses the wire as strings, on purpose

`review/serializers.py:65` — *"A JSON number is a float (ADR-0001), so every
`Decimal` this API returns passes through here first."* `confidence` uses the
same function, and `repository.py:274` encodes `confidence_reasons` as
`[{"reason": str, "penalty": str}]` for the same reason.

This makes one frontend rule non-negotiable (§4.4).

## 2. Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **React 19 + Vite + TypeScript**, `frontend/` at the repo root | The user's call, taken with the bbox rationale already removed. TypeScript earns its place here specifically because the money-as-string rule can be enforced by the type system rather than by review. |
| D2 | **No bounding-box highlighting.** Image pane is pan/zoom/rotate | `bbox` is structurally `None` (§1.1). The alternative costs a `PROMPT_VERSION` bump and an eval re-run that ISSUE-001 blocks. |
| D3 | **Findings are historical, and say so** | `apply_corrections` does not re-validate (§1.3). Labelling them is honest and costs nothing; the alternatives change load-bearing persistence code or add a route. |
| D4 | **Same origin in dev *and* prod** — Vite proxy, then `StaticFiles` | Closes the CORS gap by construction. `auth.py` is not modified and the cookie keeps `same_site="lax"`. |
| D5 | **SPA pages live under `/app/*`** | The API owns the bare paths, including `/review` — see §3.3. Moving the API under `/api` would break every existing test and ADR-0012's documented contract. |
| D6 | **⌘/Ctrl+Enter approves; plain Enter advances a field** | A deliberate deviation from `IMPLEMENTATION_PLAN.md:304` ("Enter to approve"). See §4.3. |

## 3. Architecture

### 3.1 Shape

```
frontend/
  index.html
  vite.config.ts        proxy config (dev)
  src/
    main.tsx            router: /app/login, /app/review
    api/client.ts       fetch wrapper: error envelope, 401 handling
    api/types.ts        Money branded type, response shapes
    review/             the screen (§4)
  tests/                Vitest
  e2e/                  Playwright
```

No state management library. The screen holds one receipt at a time; `useState`
plus the fetch wrapper is the whole state story. Adding Redux/Zustand here would
be ceremony around a single form.

### 3.2 One origin, always

- **Dev:** Vite `server.proxy` forwards `/receipts`, `/review`, `/auth`,
  `/upload`, `/export`, `/health`, `/metrics` to `http://localhost:8000`. The
  browser only ever addresses `:5173`, so the session cookie is same-origin.
- **Prod:** `npm run build` → `frontend/dist`, served by the existing FastAPI
  app.

Consequence: **no `CORSMiddleware`, no `SameSite=None`, no `Secure` downgrade,
and no change to `auth.py`.**

### 3.3 The one backend change

A guarded static mount at the end of `create_app` in `review/api.py`. Nothing
else on the backend moves.

The API owns the bare paths `/receipts`, `/review`, `/upload`, `/export`,
`/auth`, `/health`, `/metrics`. `GET /review/next` is an API route, so a SPA
client-side route also called `/review/...` would collide.

Therefore:

- SPA pages are served under **`/app/*`**; built assets under `/assets/*`.
- **Two independent things keep API paths safe, and either one alone is
  enough.** The `/app` **prefix**: a Starlette mount only ever intercepts paths
  under its own prefix, so a mount at `/app` cannot compete with `/health` or
  `/review/next` at *any* registration order. And **registration order**:
  Starlette matches routes in the order they were added, so a mount installed
  after `/health` loses to `/health` even from the root. Established by mutating
  each separately — moving the mount to `/` while it stays registered last
  leaves `/health` at `200 application/json`; only moving it to `/` **and**
  registering it before the read routes turns `/health` into the shell. The
  regression test therefore goes red on the conjunction alone, not on either
  change by itself (§6.1).
- The SPA history fallback applies **only under `/app`**, and only to
  navigations — see the dated note below.
- **API paths are unchanged.** No existing test or documented contract moves.

Two guards, both ADR-0014-shaped:

1. The mount is **skipped entirely unless `frontend/dist` exists and holds an
   `index.html`.** `StaticFiles(directory=...)` raises at construction, so an
   unguarded mount would break `create_app` for a base install, for CI, and for
   every test run on a machine that has never run `npm`. The `index.html` check
   is the same guard applied to a *half*-build: an interrupted `npm run build`,
   or `FRONTEND_DIST` aimed at some other real directory, would otherwise mount
   and serve whatever happens to be in it while every SPA page 404s. The skip is
   silent either way — CI and base installs take it normally.
2. `create_app` gains **no import that a base install lacks.** `StaticFiles` is
   Starlette, already present via the `api` extra — no new dependency, runtime
   or otherwise.

**2026-07-29 — the history fallback is navigation-only.** The `index.html`
fallback originally applied to every 404 under `/app`, so *every* missing file
there answered `200 text/html`. With the content-hashed Vite build behind this
mount (Task 2) that is a trap: a browser holding a cached `index.html` requests
an asset hash that has since been purged, receives HTML where JavaScript was
expected, and fails with `Unexpected token '<'` — with no 404 anywhere for
anyone to point at. That is a failure path terminating in something the reviewer
cannot see, which §5 forbids. The fallback is now restricted to requests whose
final path segment carries **no file extension** — the only shape a client-side
route takes. Anything that names a file (`/app/assets/index-abc123.js`,
`/app/favicon.ico`) keeps its 404.

This implements ADR-0015's stated intent more precisely; it does not reverse it.
ADR-0015 asks that "a hard refresh on `/app/review` returns the shell instead of
a 404" — a navigation. `/app/review` names no file, so that sentence stays
literally true, for every client rather than only for browsers (which is why the
discriminator is the path shape and not the `Accept` header: an `Accept`-based
rule would 404 a `curl` of `/app/review` and so would narrow the ADR's own
example). What changed is only the set of requests that were never navigations
in the first place. **ADR-0015 itself is unchanged.** The price of the rule is
that a client-side route must not carry a dot in its final segment; `/app/login`
and `/app/review` (§3.1) do not, and Task 2's router must keep it that way.

### 3.4 Auth flow

Any 401 from the fetch wrapper redirects to `/app/login` and returns to the
receipt afterwards. Login posts to `POST /auth/login`; logout to
`POST /auth/logout`. **The SPA stores no token** — there isn't one. Identity is
the session cookie, which is the entire reason session auth was chosen over a
shared key (ADR-0012): a correction must be attributable to a real account.

## 4. The review screen

### 4.1 Data flow

```
GET  /review/next            → {task, receipt} | {task: null}   claims the task
GET  /receipts/{receipt_id}  → detail: line_items, findings, confidence_reasons
GET  /receipts/{id}/image    → {"url": "/receipts/.../blob?variant&exp&sig"}
     ↓ reviewer edits
PATCH /receipts/{receipt_id} → nested patch of ONLY dirty paths
POST /review/{task.id}/complete
     ↓ loop
GET  /review/next
```

`GET /review/next` returns the light `receipt_summary` by design, so the detail
fetch is a second call, not a redundancy. `{"task": null}` (200, not 204)
renders an explicit *queue empty* state.

The image URL is **relative** and its signature expires after
`image_url_ttl_s`. A reviewer can outlive it on a single receipt, so `<img
onError>` re-fetches the URL once before showing a failed-image state —
otherwise the pane silently blanks mid-review.

### 4.2 The editable set is exactly the closed map

The correctable receipt paths are exactly the keys of `_RECEIPT_FIELDS`
(`src/receipts/persist/repository.py`), and the line-item ones exactly the keys
of `_LINE_ITEM_FIELDS` beside it. Nothing invented; an unlisted path is a
`ValueError` by design, never a silent no-op.

**No count here, and no second copy of either list.** This paragraph carried
both, and both went false on the branch that grew the maps: it said "17 receipt
paths" and enumerated them without `buyer.*` after `_RECEIPT_FIELDS` had grown,
and "7 per line item" after `_LINE_ITEM_FIELDS` gained `is_template_row`. A
design document that copies a closed map is a third place to keep in step, and
it is the place nobody re-derives. The maps are the authority;
`test_every_correctable_receipt_path_is_offered_by_the_review_client`
(`tests/test_repository.py`) is what binds the review client to them.

- `date_raw` renders as **read-only evidence** beside the date field: it is what
  was actually printed.
- **`line_items[].position` is read-only.** `apply_corrections` documents that
  swapping two positions trips the non-deferrable
  `uq_line_items_receipt_position` at flush time (`repository.py:1023`).
  Editable positions buy a reviewer nothing and hand them a 400.
- **No add/remove line item.** `line_items[i]` addresses the item at *position*
  `i` among existing rows; there is no path that creates or deletes one.
- `meta.legibility` renders as a select over the `Legibility` enum values, since
  `_coerce_legibility` accepts nothing else.
- **The line-item row is the highlight unit.** Focusing any cell highlights its
  whole row. This is the affordance bbox would have refined rather than
  replaced, so if P2.T2 ever produces coordinates (§1.1), highlighting a region
  of the image is an additive change to an existing concept.

### 4.3 Keyboard model

Tab order is native — that is what actually buys the time target, and it is
something SPAs usually have to re-implement rather than inherit.

**⌘/Ctrl+Enter approves. Plain Enter advances a field.** This deviates from
`IMPLEMENTATION_PLAN.md:304` deliberately: approve is a three-part action — it
writes corrections, flips `status` to `reviewed`, closes the task, and advances
— and ADR-0012 makes `reviewed` sticky against machine runs. A stray Enter
mid-typing should not do all of that. An explicit `Approve (⌘↵)` button carries
the same action for the mouse.

### 4.4 Money is a string end to end

```ts
type Money = string & { readonly __money: unique symbol }
```

No arithmetic is defined on it. **`<input type="number">` is banned on money
fields** — `valueAsNumber` and the browser's own reformatting are precisely the
float path ADR-0001 forbids — in favour of `type="text" inputMode="decimal"`.
`confidence` and every `penalty` are the same type.

The backend does defend itself (`_coerce_money` refuses a float outright, so a
mistake is a 400 rather than silent corruption), but it is designed out on this
side too.

### 4.5 The patch is dirty-fields-only

The client tracks which paths changed and sends only those, nested.
`exclude_unset=True` on the server then distinguishes *never mentioned* from
*explicitly set to null*. An approve with no edits sends `{}`, which
`apply_corrections` accepts as "no changes, still mark reviewed" — a reviewer
confirming an already-correct receipt is still a review.

### 4.6 Confidence rail

Renders the score and each `{reason, penalty}` verbatim. They provably sum to
the stored score, which is why they are persisted rather than recomputed
(ADR-0012 D2 — a read-time recompute is impossible, since `explain_confidence`
needs `TriageResult` and `meta.ambiguous_fields`, neither of which is stored).

The rail distinguishes the two nulls the serializer is careful about:
**`null` = not recorded; `[]` = nothing lowered the score.** Different facts,
shown differently.

### 4.7 Findings panel

Headed as what the machine found **at extraction time**. Not re-fetched after a
patch, because a re-fetch would return the same rows and imply a freshness that
does not exist (§1.3).

## 5. Error handling

Every failure uses one envelope — `{"error": {"message": "..."}}`
(`review/api.py:118`), with `ValueError → 400`, `DBAPIError → 503 "database
unavailable"`, and `HTTPException →` its own status. One parser, no special
cases.

**The submit chain is strictly sequential and stops on failure:**
`PATCH` → `complete` → `next`.

- **`PATCH` fails** → nothing was written. Every path is resolved and coerced
  before anything mutates, so a rejected patch leaves the database exactly as it
  was. Dirty state is preserved, the message is shown against the offending
  field (the error text names the path), and the reviewer retries.
- **`PATCH` succeeds, `complete` fails** → the receipt is `reviewed` but its
  task is open. **The screen does not advance.** Advancing would orphan a queue
  entry silently, which is the frontend spelling of a receipt being dropped. The
  retry calls `complete` only.

**Retrying a `PATCH` is safe, as a property of the backend rather than a hope.**
`_plan_change` returns `None` for any path whose stored value already matches,
and no `corrections` row is written for a no-op. A re-send after a network
timeout — where the client cannot know whether the first landed — writes zero
duplicate audit rows.

| Condition | Response |
|---|---|
| 401, session expired mid-review | redirect to `/app/login`, return to the receipt |
| 400 unmappable path / float money / constraint refusal | inline against the field; dirty state preserved |
| 403 on `complete` (not the assignee) | surface, re-fetch `next` |
| 404 receipt or task gone | surface, re-fetch `next` |
| 503 database unavailable | distinct backend-down state; never a silent blank form |
| Expired image signature | re-fetch the signed URL once, then a failed-image state |

**No `catch` in this screen may end in a no-op or a console log.** Every failure
terminates in something the reviewer can see. A correction that looks saved and
is not is the exact failure this system exists to prevent.

## 6. Testing

**The Python/Node boundary is absolute.** `python -m pytest` gains no Node
dependency and no build step, and must still pass on a machine with no `npm`
installed. The frontend adds zero Python test dependencies.

### 6.1 Python — the guards on the one backend change

1. **`create_app` succeeds when `frontend/dist` is absent.** This is the guard
   against the defect class this project shipped twice: an unbuilt frontend must
   not break app creation for a base install or CI.
2. With a `dist` fixture (a tmp dir holding an `index.html` and one hashed
   asset, not a real build), `GET /app/` serves the shell, `GET
   /app/assets/index-abc123.js` serves the asset, and `GET /app/review` — a
   deep link — falls back to the shell.
3. **`GET /health` still returns the API's JSON, not `index.html`.** What this
   test actually catches was established by mutating each guarantee separately:
   moving the mount to `/` while it stays registered last leaves `/health` at
   `200 application/json` and the test green; only moving it to `/` **and**
   registering it before the read routes turns `/health` into the shell and
   fails it. So it catches the *conjunction* and neither change alone — two
   independent things keep the SPA off `/health` (the `/app` prefix and
   registration order, §3.3) and this test goes red only when both are gone.
   It must not be described as an ordering guard or as a `/`-move guard.
4. **A missing file under `/app` is a 404, not the shell** —
   `/app/assets/index-deadbeef.js`, `.css` and `/app/favicon.ico`. The
   navigation-only narrowing recorded in §3.3.
5. **A `dist` directory with no `index.html` does not mount at all**: `/health`
   still answers, `/app/` 404s, and a file that *is* present in that directory
   is not served.
6. **A non-404 from the mount still propagates.** A `PermissionError` (→ 401)
   is the probe that pins this; `POST /app/` → 405 does not, because
   `StaticFiles` re-raises the same 405 from inside the fallback call, so a
   bare swallow leaves it unchanged. Both are asserted; only the first is
   load-bearing.

Tests 4 and 5 were proven by a RED run. Tests 1, 3, 6 and the asset case in 2
assert the *absence* of breakage and so cannot be (ADR-0015); each was proven
instead by reverting its own guarantee separately and observing the right test —
and only that test — go red.

### 6.2 Vitest — component and unit

- typing `1000.00` into a money field round-trips as the string `"1000.00"`,
  never `1000`
- the dirty-patch builder emits only changed paths
- the confidence rail renders `null` and `[]` differently
- the submit chain halts on a failed step and does not advance

### 6.3 Playwright — acceptance

Against a real API on SQLite, seeded by `scripts/seed_review_e2e.py` — a Python
fixture script reusing the repository rather than hand-written SQL, so the seed
cannot drift from the schema. It creates a reviewer account, one `needs_review`
receipt with line items, findings and a persisted `confidence_reasons`
breakdown, and its open review task.

The scenario: log in, edit fields, approve, and **assert the `corrections` rows
through the API** — not by reading the UI's own success message, which would be
circular.

### 6.4 What the timing test does and does not prove

The plan's acceptance is *"measure a scripted correction completes under 60s"*.
A scripted browser does it in roughly two seconds, so asserting `< 60s` in CI is
close to vacuous — it would pass even if the UI had become badly slow.

Therefore the automated budget is set at **10 seconds** — roughly five times the
expected scripted time, loose enough not to flake on a cold CI runner, tight
enough that a real slowdown trips it long before 60s would. **The 60-second
figure is recorded as a human target requiring a human trial.** A green CI run
does not establish it.
This is the standard already applied to ISSUE-001 and the eval artifact ban: an
unmeasured number does not get to look measured.

### 6.5 Discipline

Every new test is proven to fail with its fix reverted (project review standard
#2). CI keeps the existing Python job untouched and adds a Node job for Vitest
and Playwright.

## 7. Deferred, with reasons

- **P5.T2** (upload, list, queue, export pages) — a separate task on this
  scaffold.
- **A dry-run `POST /validate` endpoint** for live findings. Attractive: the
  validator is already pure, deterministic, never raises, and needs no model
  call, so it is the cheapest possible live feedback and reuses the real rules
  rather than duplicating 28 of them in JS. Deferred because it is a new route
  (ADR-0012 territory) with its own auth and tests, and D3 makes the screen
  honest without it.
- **Re-validating inside `apply_corrections`** — rejected, not merely deferred.
  It changes a function ADR-0006 and ADR-0012 both constrain and makes the
  corrections path import the validate package, which is a live ADR-0014
  question.
- **bbox highlighting** — revisit only if P2.T2 is resolved with an OCR pass
  (§1.1).
- **An `original` / `processed` image toggle** — cheap and genuinely useful
  ("what did the model actually see?"), but not required by P5.T1. Default is
  `original`.

## 8. Risks

- **A long review session outliving `session_ttl_s`** — handled by the 401
  redirect, but a reviewer mid-edit loses dirty state on redirect. Mitigation:
  the login redirect preserves the receipt id and returns to it; unsaved edits
  are not preserved across it. Acceptable for v1, worth revisiting if reviewers
  report it.
- **A 13–19 digit `receipt.number` is masked by `redact_pan` the moment a
  reviewer merely confirms it**, and a spurious `corrections` row is written —
  the parked finding from the review-API branch. This screen is where a human
  will finally hit it. Not fixed here (it is a repository-side fix), but it is
  now a *reachable* bug rather than a theoretical one, and it should be fixed
  before this UI meets real reviewers. The current corpus's invoice numbers are
  7 digits, so it is not blocking today.
- **No login rate limiting** (parked): a login form makes
  `POST /auth/login` reachable from a browser, and each attempt costs a full
  scrypt derivation (~16 MB, ~57 ms). Unchanged by this work, but the surface
  becomes friendlier to use. Address before this faces more than a LAN.
