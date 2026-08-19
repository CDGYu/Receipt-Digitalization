# Results list and admin export button — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A results-list screen at `/app/receipts` showing processed receipts, with an export button only admins see, where the list and the workbook are guaranteed to name the same receipts.

**Architecture:** The list is defined as a projection of the export's own query rather than of `GET /receipts`. One new route, `GET /export/receipts`, pages `query_export_receipts` and serialises rows with `receipt_summary`; `GET /export/xlsx` keeps using the same function to build the workbook. The two routes share the scope predicate and differ only in guard — the list is `require_user`, the workbook stays `require_role(ROLE_ADMIN)`. `GET /receipts` is not touched.

**Tech Stack:** FastAPI + SQLAlchemy + Pydantic (backend); React 19 + TypeScript + CSS Modules, Vitest + Testing Library (frontend). No new runtime dependency in either half.

**Spec:** `docs/superpowers/specs/2026-08-19-results-list-and-export-design.md` — read it before Task 1. Sections 2, 3 and 8 are the load-bearing ones.

**Branch:** `feat/results-list-and-export` (already created; the spec is committed on it at `411d605`).

---

## Global Constraints

Copied from the spec and the repo's non-negotiables. **Every task's requirements implicitly include this section.**

- **Money is a string** end to end. No `<input type="number">`, no `valueAsNumber`, no float ever touching a money path.
- **`null` is not `0` and is not empty** (ADR-0027 decision 5). Every nullable value on screen renders through `ui/Value.tsx`, which emits `—` with `role="img" aria-label="not extracted"`.
- **No raw hex outside `frontend/src/styles/tokens.css`.** No CDN fonts.
- **Severity colours are reserved** — do not reuse them for status.
- **The role mapping must not fail open** (ADR-0026). Compare positively against `'admin'`; every other value takes the narrow branch.
- **One `role="alert"` region on the screen.** Two regions make every single-alert query match two elements and throw.
- **Stage by explicit path, never `git add -A`.** Verify with `git diff --cached --stat` before committing.
- **Commit messages are ASCII only** — use `--` where you want an em dash. Git Bash heredocs break on non-ASCII in this environment; `git commit -m` with a plain ASCII string is fine.
- **All existing tests pass unmodified.** Anything that seems to need an existing test changed is a **stop-and-report**, not a licence to edit it. Task 5 has the one sanctioned exception, and it is additive.
- Run `python -m pytest` (bare — `pyproject.toml` sets `addopts = "-q"`, so `-q` prints no pass count). Frontend: `npm test` **and** `npm run typecheck`, which `npm test` does not do.

---

## File Structure

**Backend**

| file | responsibility | task |
|---|---|---|
| `src/receipts/review/serializers.py` | `query_export_receipts` gains `offset` | 1 |
| `src/receipts/review/schemas.py` | `ExportReceiptListResponse` | 2 |
| `src/receipts/review/api.py` | `GET /export/receipts` in `_install_read_routes` | 2 |
| `tests/test_api_write.py` | offset paging test; the scope-equality property | 1, 2 |
| `tests/test_api_read.py` | one row in the `READ_ROUTES` auth matrix | 2 |

**Frontend**

| file | responsibility | task |
|---|---|---|
| `frontend/src/api/client.ts` | `requestBlob`, sharing 401 + message extraction with `request` | 3 |
| `frontend/src/api/receipts.ts` | `fetchExportReceipts`, `downloadExportWorkbook` | 4 |
| `frontend/src/receipts/ReceiptsScreen.tsx` + `.module.css` | the screen | 5 |
| `frontend/src/route.ts`, `frontend/src/main.tsx` | the fourth route | 6 |
| `frontend/tests/client.test.ts` | `requestBlob` behaviour | 3 |
| `frontend/tests/receipts-screen.test.tsx` | screen behaviour + both-directions class guard | 5 |
| `frontend/tests/stylesheets.test.ts` | `CENSUS` entry for the new stylesheet | 5 |
| `frontend/tests/admin-screen.test.tsx` | one `currentRoute` case beside its siblings | 6 |

---

## Facts verified against the tree on 2026-08-19 — do not re-derive, but do not trust blindly either

These were read from the named symbols. If one is wrong, **stop and report** rather than working around it.

- `query_export_receipts` lives in `src/receipts/review/serializers.py`, is keyword-only after `session`, and takes `limit: int` with **no `offset`**. Its existing callers pass every argument explicitly.
- **It has a second caller outside the API: `src/receipts/cli.py`.** `tests/test_cli_reports.py` pins that the CLI and the route call the identical function. `offset` must therefore be keyword-only **with a default**, so no existing call site changes.
- `_EXPORT_EXCLUDED_BY_DEFAULT` in the same module is `frozenset({ReceiptStatus.PENDING, ReceiptStatus.REJECTED})`.
- `GET /export/xlsx` is registered in **`_install_write_routes`**, not `_install_read_routes`, despite being a GET. The new route goes in `_install_read_routes` anyway — it is a paginated read. Do not move the existing one.
- `PageLimit` / `PageOffset` are in `src/receipts/review/api.py`; `MAX_PAGE_LIMIT` is 200 and `MAX_PAGE_OFFSET` is 1_000_000. **Defaults stay at the call site** — FastAPI raises `AssertionError` at decoration time if a default is set inside `Annotated`.
- `_PageResponse` is in `src/receipts/review/schemas.py`. Each route subclasses it rather than reusing it, deliberately, so OpenAPI gets distinct schema names.
- `receipt_summary(receipt)` returns `id`, `status`, `confidence`, `merchant_name_raw`, `txn_date`, `currency`, `total`, `created_at`.
- The test files are **`tests/test_api_read.py`, `tests/test_api_write.py`, `tests/test_xlsx.py`**. There is no `tests/test_export_xlsx.py` and no `tests/conftest.py` — fixtures are per-module.
- `_receipt_ids_in(response)` already exists in `tests/test_api_write.py` and reads the `receipt_id` column of the `Receipts` sheet. **Reuse it; do not write a second one.**
- `tests/test_api_write.py` fixtures: `storage`, `session_factory`, `settings`, `submitted`, `app`, `reviewer_client`, `key_client`, `receipt_id`, `other_receipt_id`, `pending_receipt_id`, `task_id`, `admin_client`, `client_max_1mb`, `empty_reviewer_client`.
- **`pending_receipt_id` exists in both API test modules and means different things.** In `test_api_write.py` it creates a `PENDING` receipt; in `test_api_read.py` it returns a constant. Task 2's work is in `test_api_write.py`.
- `READ_ROUTES` in `tests/test_api_read.py` is a parametrised auth matrix of `(method, path, allowed_roles)`.
- `frontend/tests/stylesheets.test.ts` **auto-discovers** every `.css` under `frontend/src/` and fails on any without a `CENSUS` entry. Creating a stylesheet turns that suite red until the entry lands. This is deliberate.
- `frontend/src/ui/` provides `Value({value, kind})` where `kind` is `'money' | 'text' | 'count'`, `Button({variant, className, type, ...rest})` where `variant` is `'primary' | 'secondary' | 'danger'`, and `Chip({tone, icon, children})` where **`icon` is required**.
- `request<T>` in `frontend/src/api/client.ts` unconditionally does `response.text()` then `JSON.parse`. `errorMessage(response)` and `messageFrom(body, status)` are module-private helpers already handling both error shapes.
- `currentRoute` tests live in `frontend/tests/admin-screen.test.tsx`, not in a file of their own.

---

## Task ordering and one hard serialisation rule

Tasks 1 → 2 are backend and strictly ordered. Tasks 3 → 4 are frontend and strictly ordered. Task 5 depends on 4. Task 6 depends on 5.

**Task 5 must run alone (ADR-0023 as corrected 2026-08-06).** Creating `ReceiptsScreen.module.css` turns `frontend/tests/stylesheets.test.ts` red the instant the file exists, and that is a **global gate** — any concurrent task whose definition of done is "the frontend suite is green" will be sabotaged by it, even with a disjoint file set. Do not dispatch anything alongside Task 5.

---

### Task 1: `query_export_receipts` learns to page

**Files:**
- Modify: `src/receipts/review/serializers.py` — `query_export_receipts`
- Test: `tests/test_api_write.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `query_export_receipts(session, *, status, merchant_id, date_from, date_to, min_confidence, limit, offset=0) -> list[Receipt]`. Task 2 calls it with both `limit` and `offset`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_api_write.py`, after `test_export_refuses_rather_than_truncating`:

```python
def test_export_query_pages_without_repeating_or_skipping(session_factory, receipt_id, other_receipt_id):
    """``offset`` walks the total order ``created_at, id`` establishes.

    Paged one row at a time, the union of the pages is exactly the unpaged
    result and no id appears twice. Asserted over ids rather than over ORM
    identities, because two sessions return different instances for one row.
    """
    from receipts.review.serializers import query_export_receipts

    def page(offset: int) -> list[str]:
        with session_factory() as session:
            rows = query_export_receipts(
                session, status=None, merchant_id=None, date_from=None,
                date_to=None, min_confidence=None, limit=1, offset=offset,
            )
            return [str(row.id) for row in rows]

    with session_factory() as session:
        unpaged = [
            str(row.id)
            for row in query_export_receipts(
                session, status=None, merchant_id=None, date_from=None,
                date_to=None, min_confidence=None, limit=100,
            )
        ]

    # Anti-vacuity: a fixture yielding fewer than two rows would let a broken
    # offset pass, because page 0 alone would equal the unpaged result.
    assert len(unpaged) >= 2, "fixture must produce at least two exportable receipts"

    walked: list[str] = []
    for offset in range(len(unpaged)):
        walked.extend(page(offset))

    assert walked == unpaged
    assert len(set(walked)) == len(walked)
    assert page(len(unpaged)) == []
```

- [ ] **Step 1b: Write the tie-break test**

The order is `created_at, id` — the `id` half is what makes it *total*, and a
tie is what a naive offset breaks on. **This is not a hypothetical case here:**
`created_at` is `server_default=sa.func.now()`, which on SQLite is
`CURRENT_TIMESTAMP` at **second** resolution, so two rows inserted in the same
second already share it. Today that happens by accident; this makes it
deterministic.

Add beside the previous test. Check the module's existing imports before adding
`datetime`/`UTC` — `date` and `time` are already imported, `datetime` may not be.

```python
def test_export_query_pages_a_created_at_tie_without_losing_a_row(session_factory):
    """The ``id`` half of the order is what makes it total, and paging needs total.

    Two receipts sharing a ``created_at`` are ordered only by ``id``. Without
    that tie-break the database may return them in either order per query, and
    a paged walk would then repeat one and skip the other.
    """
    from datetime import datetime, timezone

    from receipts.persist.models import Receipt
    from receipts.review.serializers import query_export_receipts

    shared = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)
    ids = [uuid.uuid4(), uuid.uuid4()]
    with session_factory() as session:
        for index, receipt_uuid in enumerate(ids):
            session.add(
                Receipt(
                    id=receipt_uuid,
                    status=ReceiptStatus.AUTO_APPROVED,
                    confidence=Decimal("0.900"),
                    merchant_name_raw=f"TIED {index}",
                    currency="USD",
                    total=Decimal("1.00"),
                    image_key=make_image_key(receipt_uuid, "original"),
                    image_phash="",
                    created_at=shared,
                )
            )
        session.commit()

    def page(offset: int) -> list[str]:
        with session_factory() as session:
            return [
                str(row.id)
                for row in query_export_receipts(
                    session, status=None, merchant_id=None, date_from=None,
                    date_to=None, min_confidence=None, limit=1, offset=offset,
                )
            ]

    with session_factory() as session:
        unpaged = [
            str(row.id)
            for row in query_export_receipts(
                session, status=None, merchant_id=None, date_from=None,
                date_to=None, min_confidence=None, limit=100,
            )
        ]

    tied = [str(receipt_uuid) for receipt_uuid in ids]
    # Anti-vacuity: if the two rows did not land adjacent under one timestamp,
    # this test is not exercising a tie at all.
    positions = sorted(unpaged.index(one) for one in tied)
    assert positions[1] - positions[0] == 1, "the two tied rows should be adjacent"

    walked = [one for offset in range(len(unpaged)) for one in page(offset)]
    assert walked == unpaged
    assert sorted(one for one in walked if one in tied) == sorted(tied)
```

If `Receipt(...)` rejects `created_at` as a keyword, or the two rows do not land
adjacent, **stop and report** rather than adjusting the assertion — an adjusted
assertion here produces a test that cannot fail.

- [ ] **Step 2: Run both and confirm they fail for the right reason**

Run: `python -m pytest tests/test_api_write.py -k export_query_pages`

Expected: **FAIL** with `TypeError: query_export_receipts() got an unexpected keyword argument 'offset'`.

If it fails any other way — in particular if it fails on the `len(unpaged) >= 2` assertion — **stop and report**: the fixtures do not supply what this test needs, and changing the assertion to match would make the test vacuous.

- [ ] **Step 3: Add the parameter**

In `src/receipts/review/serializers.py`, add `offset` to the signature as the last keyword-only parameter, **with a default** (the CLI calls this function without it):

```python
    limit: int,
    offset: int = 0,
) -> list[Receipt]:
```

and apply it in the final query expression, which currently reads
`query.order_by(Receipt.created_at, Receipt.id).limit(limit)`:

```python
    query = query.order_by(Receipt.created_at, Receipt.id).limit(limit).offset(offset)
```

Add one sentence to the docstring, next to the existing paragraph about matching `query_receipts`' ordering:

```
    ``offset`` pages that same total order. It defaults to 0 because
    ``receipts.cli`` calls this function without one.
```

- [ ] **Step 4: Run the test and the two suites it could disturb**

Run: `python -m pytest tests/test_api_write.py tests/test_cli_reports.py tests/test_xlsx.py`

Expected: **PASS**, with no existing test modified. `test_cli_reports.py` is included because it pins that the CLI and the route call the identical function.

- [ ] **Step 5: Commit**

```bash
git add src/receipts/review/serializers.py tests/test_api_write.py
git diff --cached --stat
git commit -m "feat(export): query_export_receipts pages its own total order"
```

---

### Task 2: `GET /export/receipts`, and the property that makes this design real

**Files:**
- Modify: `src/receipts/review/schemas.py` — add `ExportReceiptListResponse`
- Modify: `src/receipts/review/api.py` — add the route to `_install_read_routes`
- Test: `tests/test_api_write.py`, `tests/test_api_read.py`

**Interfaces:**
- Consumes: `query_export_receipts(..., limit=, offset=)` from Task 1.
- Produces: `GET /export/receipts` answering `{"items": [<receipt_summary>], "has_more": bool}`, accepting `status`, `merchant_id`, `date_from`, `date_to`, `min_confidence`, `limit` (default 50), `offset` (default 0). Task 4 calls it.

- [ ] **Step 1: Write the failing property test**

This is the deliverable. Append to `tests/test_api_write.py` **after `_receipt_ids_in`** so the helper is in scope:

```python
def _listed_receipt_ids(client, **params) -> set[str]:
    """Every id ``GET /export/receipts`` yields, paged to exhaustion.

    ``limit=2`` forces more than one page on any realistic fixture, so the
    property below covers the paging path rather than only the first window.
    """
    ids: set[str] = set()
    offset = 0
    while True:
        response = client.get(
            "/export/receipts", params={**params, "limit": 2, "offset": offset}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        ids.update(str(row["id"]) for row in body["items"])
        if not body["has_more"]:
            return ids
        offset += 2


def test_the_list_and_the_workbook_name_the_same_receipts(admin_client, pending_receipt_id):
    """One predicate at both ends -- design section 2, and the reason this route exists.

    The list is a projection of the export's own query, so the two cannot
    disagree about scope. Stated as a set equality rather than an enumeration
    of statuses: an enumeration would need editing every time a
    ``ReceiptStatus`` member is added, and the enumeration is what goes stale.
    """
    listed = _listed_receipt_ids(admin_client)
    in_workbook = _receipt_ids_in(admin_client.get("/export/xlsx"))

    # Anti-vacuity, both halves. Two empty sets are equal.
    assert listed, "fixture must produce at least one exportable receipt"
    assert listed == in_workbook

    # And the equality is not trivially "everything": the excluded status is
    # absent from both, and present in both once it is asked for.
    assert str(pending_receipt_id) not in listed

    asked = _listed_receipt_ids(admin_client, status="pending")
    asked_workbook = _receipt_ids_in(
        admin_client.get("/export/xlsx", params={"status": "pending"})
    )
    assert str(pending_receipt_id) in asked
    assert asked == asked_workbook


def test_the_list_is_visible_to_a_reviewer_the_workbook_is_not(reviewer_client):
    """The two routes share a scope predicate and differ only in guard.

    Seeing the ledger and extracting it are different acts (design decision 3).
    Pinned rather than commented, because matching guards is exactly what a
    later reader would "tidy" these two into.
    """
    assert reviewer_client.get("/export/receipts").status_code == 200
    assert reviewer_client.get("/export/xlsx").status_code == 403
```

- [ ] **Step 2: Run them and confirm they fail for the right reason**

Run: `python -m pytest tests/test_api_write.py -k "same_receipts or visible_to_a_reviewer"`

Expected: **FAIL**. Both should fail on the route not existing — a 404 surfacing as the `assert response.status_code == 200, response.text` in the helper, or as the direct assertion in the second test.

**A 404 here is produced by FastAPI for any unregistered path**, so confirm the failure names `/export/receipts` and not something else. A test that would pass before the route exists proves nothing.

- [ ] **Step 3: Add the response model**

In `src/receipts/review/schemas.py`, beside the other `_PageResponse` subclasses:

```python
class ExportReceiptListResponse(_PageResponse):
    """One page of :func:`receipt_summary` rows scoped to the export
    (``GET /export/receipts``).

    A separate model from :class:`ReceiptListResponse` despite the identical
    body, for this module's recorded reason: distinct response models give
    distinct OpenAPI schema names. The two routes also mean different things --
    this one answers "what would the workbook contain", and that is the whole
    point of it existing.
    """
```

- [ ] **Step 4: Add the route**

In `src/receipts/review/api.py`, inside `_install_read_routes`, after the `GET /receipts` handler. Add `ExportReceiptListResponse` to the `schemas` import and `query_export_receipts` is already imported at module level — check before adding a duplicate import.

```python
    @app.get("/export/receipts", response_model=ExportReceiptListResponse)
    def list_export_receipts(
        request: Request,
        user: Annotated[SessionUser, Depends(require_user)],
        status: ReceiptStatus | None = None,
        merchant_id: uuid.UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        min_confidence: Decimal | None = None,
        limit: PageLimit = 50,
        offset: PageOffset = 0,
    ) -> Any:
        """The receipts ``GET /export/xlsx`` would write, one page at a time.

        **Deliberately not a variant of ``GET /receipts``.** That route applies
        no status exclusion and its ``status`` filter is a single equality, so
        it cannot express "every status except these two" -- which is why
        ``query_export_receipts`` exists as a separate function at all. A list
        screen built on it would show rows the workbook silently omits.

        Calling the export's own query instead makes the two agree by
        construction rather than by two rules kept in step. The scope predicate
        is shared; the **guard is not** -- this route is ``require_user`` while
        the workbook is admin-only, because seeing the ledger and extracting it
        are different acts. ``GET /receipts`` already serves ``receipt_summary``
        rows to any signed-in user unscoped, so this discloses nothing new.

        ``has_more`` comes from a ``limit + 1`` fetch, matching every other
        paginated route here.
        """
        with request.app.state.session_factory() as session:
            rows = query_export_receipts(
                session,
                status=status,
                merchant_id=merchant_id,
                date_from=date_from,
                date_to=date_to,
                min_confidence=min_confidence,
                limit=limit + 1,
                offset=offset,
            )
            items = [receipt_summary(receipt) for receipt in rows[:limit]]
        return {"items": items, "has_more": len(rows) > limit}
```

- [ ] **Step 5: Add the auth-matrix row**

In `tests/test_api_read.py`, add one row to `READ_ROUTES`, beside the `/export/xlsx` row:

```python
    ("GET", "/export/receipts", {"reviewer", "admin"}),
```

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests/test_api_write.py tests/test_api_read.py`

Expected: **PASS**, including the auth matrix's anonymous/api_key 401 and the reviewer/admin 200 cases for the new row.

- [ ] **Step 7: Prove the property can fail**

Do not skip this. A pin never proven red is not a pin.

Temporarily change the route's call from `query_export_receipts` to `query_receipts` (imported in the same module), keeping every argument that both accept and dropping the rest. Run:

`python -m pytest tests/test_api_write.py -k same_receipts`

Expected: **FAIL** on `listed == in_workbook`, because the pending receipt now appears in the list and not in the workbook. **Revert the change** and confirm the test is green again before committing. Record the observed failure message in your report.

- [ ] **Step 8: Commit**

```bash
git add src/receipts/review/api.py src/receipts/review/schemas.py tests/test_api_write.py tests/test_api_read.py
git diff --cached --stat
git commit -m "feat(api): GET /export/receipts lists what the workbook contains"
```

---

### Task 3: `requestBlob`

**Files:**
- Modify: `frontend/src/api/client.ts`
- Test: `frontend/tests/client.test.ts`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `requestBlob(path: string, init?: RequestInit): Promise<{ blob: Blob; filename: string | null }>`. Task 4 calls it.

Read `frontend/src/api/client.ts` in full before starting. `request` is the model; `errorMessage` and `messageFrom` are the helpers to reuse.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/tests/client.test.ts`. That file stubs fetch with
`vi.stubGlobal('fetch', vi.fn().mockResolvedValue(...))` and has a
`jsonResponse(status, body)` helper at the top; a `beforeEach` already resets
`onUnauthorized`. Add `requestBlob` to the existing import from
`../src/api/client` rather than writing a second import line.

```ts
/** A binary body, which `jsonResponse` cannot express. */
function blobResponse(status: number, body: string, headers?: Record<string, string>): Response {
  return new Response(new Blob([body]), { status, headers })
}

describe('requestBlob', () => {
  it('returns the body as a blob on success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(blobResponse(200, 'xlsx-bytes')))
    const { blob } = await requestBlob('/export/xlsx')
    expect(await blob.text()).toBe('xlsx-bytes')
  })

  it('reads the filename out of Content-Disposition', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        blobResponse(200, 'x', {
          'Content-Disposition': 'attachment; filename="receipts-export.xlsx"',
        }),
      ),
    )
    const { filename } = await requestBlob('/export/xlsx')
    expect(filename).toBe('receipts-export.xlsx')
  })

  it('reports no filename when the header is absent, rather than inventing one', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(blobResponse(200, 'x')))
    const { filename } = await requestBlob('/export/xlsx')
    expect(filename).toBeNull()
  })

  it("surfaces the server's message on a 400, not a generic one", async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(400, { error: { message: 'narrow the filter and try again' } }),
      ),
    )
    await expect(requestBlob('/export/xlsx')).rejects.toThrow('narrow the filter and try again')
  })

  it('fires the unauthorized handler on a 401, like request does', async () => {
    const handler = vi.fn()
    onUnauthorized(handler)
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(401, { error: { message: 'not authenticated' } })),
    )
    await expect(requestBlob('/export/xlsx')).rejects.toThrow()
    expect(handler).toHaveBeenCalledOnce()
  })
})
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd frontend && npx vitest run tests/client.test.ts`

Expected: **FAIL** — `requestBlob` is not exported.

- [ ] **Step 3: Implement it**

In `frontend/src/api/client.ts`, beside `request`:

```ts
/** The filename a `Content-Disposition: attachment` header names, or `null`.
 *
 *  Deliberately narrow: it reads the quoted `filename="..."` form the export
 *  route actually sends and returns `null` for anything else, rather than
 *  growing a parser for RFC 6266's full grammar including `filename*`. A
 *  caller that gets `null` supplies its own name; a caller that gets a wrong
 *  name would not know.
 */
function attachmentFilename(response: Response): string | null {
  const header = response.headers.get('Content-Disposition')
  const match = header?.match(/filename="([^"]+)"/)
  return match ? match[1] : null
}

/** `request`, for a body that is not JSON.
 *
 *  Everything up to `response.ok` is identical -- same credentials, same 401
 *  side effect, same `ApiError` carrying the server's own message -- because
 *  **the export route's failures are still JSON even though its successes are
 *  not.** Only the success path differs.
 *
 *  This exists because `request<T>` unconditionally calls `response.text()`
 *  and `JSON.parse`s it, so a workbook reaches the caller as
 *  `expected JSON from /export/xlsx` rather than as bytes.
 */
export async function requestBlob(
  path: string,
  init?: RequestInit,
): Promise<{ blob: Blob; filename: string | null }> {
  const response = await fetch(path, {
    ...init,
    credentials: 'same-origin',
    headers: mergeHeaders(init),
  })
  if (response.status === 401) {
    unauthorizedHandler()
    throw new ApiError(401, await errorMessage(response))
  }
  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response))
  }
  return { blob: await response.blob(), filename: attachmentFilename(response) }
}
```

- [ ] **Step 4: Run the tests and the typecheck**

Run: `cd frontend && npx vitest run tests/client.test.ts && npm run typecheck`

Expected: **PASS** both. `npm test` does not typecheck, so the second half is not optional.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/client.ts frontend/tests/client.test.ts
git diff --cached --stat
git commit -m "feat(api): requestBlob, for a body that is not JSON"
```

---

### Task 4: The two API functions

**Files:**
- Create: `frontend/src/api/receipts.ts`
- Test: `frontend/tests/receipts-api.test.ts`

**Interfaces:**
- Consumes: `requestBlob` from Task 3; `request` and `ReceiptSummary` which already exist.
- Produces:
  - `fetchExportReceipts(params?: { limit?: number; offset?: number }): Promise<ExportReceiptPage>`
  - `downloadExportWorkbook(): Promise<void>`
  - `interface ExportReceiptPage { items: ReceiptSummary[]; has_more: boolean }`

  Task 5 calls both.

- [ ] **Step 1: Write the failing tests**

Create `frontend/tests/receipts-api.test.ts`, following
`frontend/tests/review-api.test.ts`'s established shape: an
`afterEach(() => vi.unstubAllGlobals())`, a `jsonResponse(status, body)`
helper, and a `stub(response)` helper that installs the mock and returns it.
Copy those three rather than inventing new ones.

```ts
/** A binary body, which `jsonResponse` cannot express. */
function blobResponse(status: number, body: string, headers?: Record<string, string>): Response {
  return new Response(new Blob([body]), { status, headers })
}

/** Capture the anchor `downloadExportWorkbook` builds, without navigating.
 *
 *  jsdom does not act on `click`, so nothing escapes the test; the spy exists
 *  to read `download` and `href` back off the element. */
function spyOnAnchorClick(): HTMLAnchorElement {
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:stub')
  const anchor = document.createElement('a')
  vi.spyOn(anchor, 'click').mockImplementation(() => {})
  vi.spyOn(document, 'createElement').mockReturnValue(anchor)
  return anchor
}

it('asks for a page with the limit and offset it was given', async () => {
  const fetchMock = stub(jsonResponse(200, { items: [], has_more: false }))
  await fetchExportReceipts({ limit: 50, offset: 50 })
  const url = String(fetchMock.mock.calls[0]?.[0])
  expect(url).toContain('limit=50')
  expect(url).toContain('offset=50')
})

it('asks for the export scope, not the unfiltered receipts list', async () => {
  // The whole design rests on this path. `/receipts` would silently widen it.
  const fetchMock = stub(jsonResponse(200, { items: [], has_more: false }))
  await fetchExportReceipts()
  expect(String(fetchMock.mock.calls[0]?.[0])).toContain('/export/receipts')
})

it('names the downloaded file from the header when there is one', async () => {
  stub(
    blobResponse(200, 'x', {
      'Content-Disposition': 'attachment; filename="receipts-export.xlsx"',
    }),
  )
  const anchor = spyOnAnchorClick()
  await downloadExportWorkbook()
  expect(anchor.download).toBe('receipts-export.xlsx')
})

it('falls back to a constant name when the header is absent', async () => {
  stub(blobResponse(200, 'x'))
  const anchor = spyOnAnchorClick()
  await downloadExportWorkbook()
  expect(anchor.download).toBe('receipts-export.xlsx')
})

it('revokes the object URL it created', async () => {
  stub(blobResponse(200, 'x'))
  const revoke = vi.spyOn(URL, 'revokeObjectURL')
  spyOnAnchorClick()
  await downloadExportWorkbook()
  expect(revoke).toHaveBeenCalledOnce()
})
```

**Note on the two filename tests:** they assert the same string for opposite
reasons — one that the header is read, one that the fallback is used. That is
deliberate but it makes each a weak witness alone, so if you change
`FALLBACK_FILENAME`, the first must keep passing and the second must fail. Say
so in your report if you touch either.

- [ ] **Step 2: Run and confirm failure**

Run: `cd frontend && npx vitest run tests/receipts-api.test.ts`

Expected: **FAIL** — the module does not exist.

- [ ] **Step 3: Implement**

Create `frontend/src/api/receipts.ts`:

```ts
import { request, requestBlob } from './client'
import type { ReceiptSummary } from './types'

/** The fallback filename, used only when the response carries no
 *  `Content-Disposition`. Fetching a body as a blob means the browser no
 *  longer honours that header, so `download` has to be set explicitly -- and
 *  a hardcoded name here would be a second copy of the server's that can
 *  drift from it, so the header wins when present. */
const FALLBACK_FILENAME = 'receipts-export.xlsx'

export interface ExportReceiptPage {
  items: ReceiptSummary[]
  has_more: boolean
}

/** One page of the receipts the export would contain.
 *
 *  Not `GET /receipts`: that route applies no status exclusion, so a list
 *  built on it shows rows the workbook omits.
 */
export function fetchExportReceipts(params?: {
  limit?: number
  offset?: number
}): Promise<ExportReceiptPage> {
  const query = new URLSearchParams()
  if (params?.limit !== undefined) query.set('limit', String(params.limit))
  if (params?.offset !== undefined) query.set('offset', String(params.offset))
  const suffix = query.toString() === '' ? '' : `?${query.toString()}`
  return request<ExportReceiptPage>(`/export/receipts${suffix}`)
}

/** Download the workbook. Admin-only at the route; the button that calls this
 *  is not rendered for anyone else, and the route 403s if it is reached anyway. */
export async function downloadExportWorkbook(): Promise<void> {
  const { blob, filename } = await requestBlob('/export/xlsx')
  const url = URL.createObjectURL(blob)
  try {
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename ?? FALLBACK_FILENAME
    anchor.click()
  } finally {
    URL.revokeObjectURL(url)
  }
}
```

- [ ] **Step 4: Run tests and typecheck**

Run: `cd frontend && npx vitest run tests/receipts-api.test.ts && npm run typecheck`

Expected: **PASS** both.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/receipts.ts frontend/tests/receipts-api.test.ts
git diff --cached --stat
git commit -m "feat(api): fetch a page of exportable receipts, and download the workbook"
```

---

### Task 5: The screen — RUNS ALONE

**Do not dispatch any other task alongside this one.** Creating the stylesheet turns `frontend/tests/stylesheets.test.ts` red until its `CENSUS` entry lands, and that suite is a global gate.

**Files:**
- Create: `frontend/src/receipts/ReceiptsScreen.tsx`, `frontend/src/receipts/ReceiptsScreen.module.css`
- Modify: `frontend/tests/stylesheets.test.ts` — add the `CENSUS` entry (**the one sanctioned edit to an existing test**, and it is additive)
- Test: `frontend/tests/receipts-screen.test.tsx`

**Interfaces:**
- Consumes: `fetchExportReceipts`, `downloadExportWorkbook`, `ExportReceiptPage` from Task 4; `Identity` from `api/admin`; `Value` and `Button` from `ui/`.
- Produces: `ReceiptsScreen({ identity }: { identity: Identity | null })`. Task 6 mounts it.

Read `frontend/src/admin/AdminScreen.tsx` in full first. Its identity handling, its single alert region and its load/error state are the pattern to follow; deviating from them is a stop-and-report, not a judgement call.

- [ ] **Step 1: Write the failing behaviour tests**

Create `frontend/tests/receipts-screen.test.tsx`:

```tsx
it('renders a wait branch while the identity is unknown', () => {
  render(<ReceiptsScreen identity={null} />)
  // null means "not yet answered", never "not an admin".
  expect(screen.queryByRole('button', { name: /export/i })).not.toBeInTheDocument()
  expect(screen.getByText(/waiting/i)).toBeInTheDocument()
})

it('shows the export button to an admin', async () => {
  stubPage({ items: [rowFixture()], has_more: false })
  render(<ReceiptsScreen identity={{ username: 'ada', role: 'admin' }} />)
  expect(await screen.findByRole('button', { name: /export/i })).toBeInTheDocument()
})

it('hides the export button from a reviewer', async () => {
  stubPage({ items: [rowFixture()], has_more: false })
  render(<ReceiptsScreen identity={{ username: 'bob', role: 'reviewer' }} />)
  await screen.findByText('Summit Fuel')
  expect(screen.queryByRole('button', { name: /export/i })).not.toBeInTheDocument()
})

it('hides the export button from an unrecognised role, rather than failing open', async () => {
  stubPage({ items: [rowFixture()], has_more: false })
  render(<ReceiptsScreen identity={{ username: 'eve', role: 'auditor' }} />)
  await screen.findByText('Summit Fuel')
  expect(screen.queryByRole('button', { name: /export/i })).not.toBeInTheDocument()
})

it('renders a null field as not-extracted, not as an empty cell', async () => {
  stubPage({ items: [rowFixture({ merchant_name_raw: null, total: null })], has_more: false })
  render(<ReceiptsScreen identity={{ username: 'ada', role: 'admin' }} />)
  const marks = await screen.findAllByLabelText('not extracted')
  expect(marks.length).toBeGreaterThanOrEqual(2)
})

it('offers Load more only while has_more is true, and appends', async () => {
  stubPages([
    { items: [rowFixture({ merchant_name_raw: 'First' })], has_more: true },
    { items: [rowFixture({ merchant_name_raw: 'Second' })], has_more: false },
  ])
  render(<ReceiptsScreen identity={{ username: 'ada', role: 'admin' }} />)
  await userEvent.click(await screen.findByRole('button', { name: /load more/i }))
  expect(screen.getByText('First')).toBeInTheDocument()
  expect(screen.getByText('Second')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /load more/i })).not.toBeInTheDocument()
})

it("surfaces the export's own message in the one alert region", async () => {
  stubPage({ items: [rowFixture()], has_more: false })
  stubDownloadRejection(new ApiError(400, 'this export matches more than 5000 receipts'))
  render(<ReceiptsScreen identity={{ username: 'ada', role: 'admin' }} />)
  await userEvent.click(await screen.findByRole('button', { name: /export/i }))
  const alerts = await screen.findAllByRole('alert')
  expect(alerts).toHaveLength(1)
  expect(alerts[0]).toHaveTextContent(/more than 5000/i)
})

it('does not fire a second download while one is in flight', async () => {
  stubPage({ items: [rowFixture()], has_more: false })
  const download = stubSlowDownload()
  render(<ReceiptsScreen identity={{ username: 'ada', role: 'admin' }} />)
  const button = await screen.findByRole('button', { name: /export/i })
  await userEvent.click(button)
  await userEvent.click(button)
  expect(download).toHaveBeenCalledOnce()
})
```

`rowFixture(overrides)` returns a `ReceiptSummary` with `merchant_name_raw: 'Summit Fuel'` and every other field populated; `stubPage` / `stubPages` / `stubDownloadRejection` / `stubSlowDownload` mock `../src/api/receipts`. Write them at the top of the file.

- [ ] **Step 2: Run and confirm failure**

Run: `cd frontend && npx vitest run tests/receipts-screen.test.tsx`

Expected: **FAIL** — the component does not exist.

- [ ] **Step 3: Build the component and its stylesheet**

Write `ReceiptsScreen.tsx` and `ReceiptsScreen.module.css` to satisfy the tests. Binding requirements, all from the spec and Global Constraints:

- Columns in this order: `txn_date`, `merchant_name_raw`, `total` (with `currency`), `status`, `confidence`.
- Every nullable value goes through `<Value value={...} kind={...} />` — `kind="money"` for `total`, `kind="text"` for `merchant_name_raw` and `txn_date`, `kind="count"` for `confidence`. **Never render a bare `{value}` for a nullable field.**
- **Status is plain text, not a `Chip`.** `Chip` requires an `icon` per tone, and which icon each `ReceiptStatus` gets is a design decision nobody has made. Report it rather than inventing one.
- The export button is `<Button variant="primary">`, rendered only when `identity.role === 'admin'` — compared positively.
- **Exactly one `role="alert"` region**, shared by the list's load failure and the export's. Two make `findByRole('alert')` throw.
- No raw hex in the stylesheet; use the tokens in `frontend/src/styles/tokens.css`.

- [ ] **Step 4: Add the CENSUS entry**

`npx vitest run tests/stylesheets.test.ts` is now red, naming the new file. Add its entry to `CENSUS` in `frontend/tests/stylesheets.test.ts`, following the shape of the entries already there. This is additive — do not alter any existing entry.

- [ ] **Step 5: Add the both-directions class guard**

Append to `frontend/tests/receipts-screen.test.tsx`, modelled on the guard in `frontend/tests/admin-screen.test.tsx` (read it — it has two directions, and gained the second one on 2026-08-14 for exactly this reason):

- every `styles.NAME` referenced in `ReceiptsScreen.tsx` is declared in `ReceiptsScreen.module.css`, **and**
- every class declared in the stylesheet is referenced by the component.

Strip block comments before matching on both sides. Prose must not answer for code — a comment naming a class has already made one of these guards pass falsely in this repo.

- [ ] **Step 6: Run the whole frontend suite and the typecheck**

Run: `cd frontend && npm test && npm run typecheck`

Expected: **PASS**, with `stylesheets.test.ts` green again.

- [ ] **Step 7: Prove the class guard can fail**

Rename one class in `ReceiptsScreen.module.css` without touching the TSX. Run `npx vitest run tests/receipts-screen.test.tsx`.

Expected: **FAIL**. Then rename the reference in the TSX and not the CSS, and confirm it fails the other way too. **Revert both.** Vitest sets `css: false`, so a `.module.css` import answers for any key — without a guard proven red in both directions, a renamed class ships unpainted with every gate green.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/receipts/ frontend/tests/receipts-screen.test.tsx frontend/tests/stylesheets.test.ts
git diff --cached --stat
git commit -m "feat(ui): a results list, with the export button admins alone see"
```

---

### Task 6: The fourth route

**Files:**
- Modify: `frontend/src/route.ts`, `frontend/src/main.tsx`
- Test: `frontend/tests/admin-screen.test.tsx` (additive — this is where the `currentRoute` cases live). **That is the only test file this task touches**; `receipts-screen.test.tsx` belongs to Task 5 and is already green.

**Interfaces:**
- Consumes: `ReceiptsScreen` from Task 5.
- Produces: `/app/receipts` renders the screen. Nothing later depends on it.

- [ ] **Step 1: Write the failing tests**

In `frontend/tests/admin-screen.test.tsx`, beside the existing `currentRoute` assertions:

```ts
expect(currentRoute('/app/receipts')).toBe('receipts')
expect(currentRoute('/app/receipts/')).toBe('receipts')
```

Leave `expect(currentRoute('/app/anything-else')).toBe('review')` untouched — it must keep passing.

- [ ] **Step 2: Run and confirm failure**

Run: `cd frontend && npx vitest run tests/admin-screen.test.tsx`

Expected: **FAIL** — `currentRoute('/app/receipts')` returns `'review'`.

- [ ] **Step 3: Add the route**

In `frontend/src/route.ts`:

```ts
export type Route = 'login' | 'review' | 'admin' | 'receipts'
```

and, before the final `return 'review'`, mirroring the admin branch's `startsWith` (so a browser's trailing slash is the same route):

```ts
  if (pathname.startsWith('/app/receipts')) {
    return 'receipts'
  }
```

`/app/receipts` has no dot in its last segment, so the backend's SPA fallback serves it on reload. **Do not add a path built from receipt data** — rows are not clickable, and a receipt id in a path segment is served as a missing file and 404s.

- [ ] **Step 4: Mount it**

In `frontend/src/main.tsx`, import `ReceiptsScreen` and extend the route switch. The existing ternary becomes a three-way; keep `ReviewScreen` as the default branch, and pass `identity` exactly as `AdminScreen` receives it.

- [ ] **Step 5: Run everything**

Run: `cd frontend && npm test && npm run typecheck`

Expected: **PASS**.

- [ ] **Step 6: Run the full gate set**

Run: `python scripts/verify.py`

**Background it — it exceeds a two-minute tool timeout, and do not edit any file while it runs.** A backgrounded run during an edit has previously reported a phantom `FAIL build` on an error that no longer existed.

Expected: all five gates **PASS**.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/route.ts frontend/src/main.tsx frontend/tests/admin-screen.test.tsx
git diff --cached --stat
git commit -m "feat(ui): /app/receipts is the fourth screen"
```

---

## What this plan does not do

- **No filters, sorting, row navigation or `buyer` column.** Spec sections 9 and 10.
- **No ADR.** Decision 3 — the two routes sharing a scope predicate while differing in guard — is the candidate, and it is the thing most likely to be "tidied" into matching guards later. Task 2 step 1 pins it behaviourally; whether that deserves an ADR is a call for the close.
- **Nothing is seen in a browser.** jsdom lays nothing out and renders no colour, so no step above can tell you how this looks. A new table with a new stylesheet should be looked at by a person before the branch is called done.
- **`RECEIPT_SYSTEM_SPEC.md` section 14.9's route inventory gains no row.** The same gap `GET /receipts/{id}/corrections` was left in; recorded here so it is a decision rather than an oversight.

---

## Dated defect log

*(This plan does not self-amend. Append findings here as they are found, with the date. Read this section before trusting any task above — every milestone in this repo's history has found defects in its own plan, and every one was the controller's.)*

- *(none yet)*
