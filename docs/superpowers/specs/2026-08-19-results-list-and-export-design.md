# The results list and the admin export button ("M2")

**Status:** Design, agreed 2026-08-19. No plan written yet.
**Asked for:** 2026-08-18, in the user's words — *"work on the output since I
want it to directly go in the excel or make another function for the UI/UX of
this project that will show the lists of results."* Design was agreed in that
session and then displaced by the Summit Fuel buyer defect, which became the
2026-08-19 milestone. This is the first document for it.

**Every claim about the tree below was derived on 2026-08-19 against `main` at
the pair commit, by reading the named symbol.** Re-derive rather than quote
(ADR-0028, ADR-0045). Symbols are named rather than cited by line, because
`path:NNN` citations are the residual this repo is trying not to grow
(ADR-0028 section 5, review standard 21).

---

## 1. What this is, and what it is not

A fourth screen listing processed receipts, with an export button that only
admins see. **No filters in v1**, by ruling. Rows are **not clickable** — the
screen is a register of what has been processed, not a second way into review.

That last decision is load-bearing beyond the UI: with no row navigation,
nothing on this screen is built from receipt data, so no receipt id ever enters
a path segment. `route.ts`'s no-dot rule — a client-side path whose last
segment carries a file extension is served as a missing *file* and 404s — is
therefore never approached, rather than approached and guarded.

**Not in scope:** filters, sorting, a detail view, row selection, column
choice, and `buyer` on the list. Section 10 records why each is out.

---

## 2. The defect this design exists to close

`GET /receipts` and `GET /export/xlsx` **disagree about which receipts are in
scope**, and with no filters the disagreement is invisible.

- `query_receipts` applies no status exclusion. Its `status` filter is a single
  equality, so it has no way to express "every status except these two" — the
  reason `query_export_receipts` exists as a separate function at all, which
  that function's own docstring states.
- `query_export_receipts` excludes `_EXPORT_EXCLUDED_BY_DEFAULT`, which is
  `PENDING` and `REJECTED`, unless `status` names one of them explicitly.

So a screen built on `GET /receipts` shows rows the workbook will omit. A
viewer sees a list, clicks Export, and receives strictly fewer receipts with no
notice. That is the shape the non-negotiables call *nothing silently dropped*,
and it would be **branch-introduced**: today no frontend surface lists
receipts at all, so today no row can vanish.

**Closed by one predicate at both ends, not by two rules that must agree.**
This is the same corrective ADR-0043 applied to the duplicate finders after the
Phase 6 close: `find_duplicate_by_content` refuses to *offer* what
`mark_duplicate` would refuse to *link*. Here, the list is defined as *the rows
the export contains*, so the two cannot disagree — there is no second scope to
keep in step.

Two alternatives were considered and rejected:

- **A `scope` parameter on `GET /receipts`.** The broad default survives beside
  the narrow one, so correctness still depends on every caller choosing the
  right value. That is an enumerated defence wearing a flag (review standard
  19), and it widens a live public contract.
- **Narrowing `GET /receipts` itself.** Genuinely one predicate, but a breaking
  change to a public unscoped route, and because `status` is a single equality
  it would leave `PENDING` and `REJECTED` reachable only one status at a time.

---

## 3. Decisions

1. **The list is a projection of the export's query, not of `GET /receipts`.**
   One new route, `GET /export/receipts`, pages `query_export_receipts` and
   serialises each row with `receipt_summary`.
2. **`GET /receipts` is not touched.** It has no frontend caller today — the
   exported functions in `frontend/src/api/` are `fetchMe`, `fetchTasks`,
   `releaseTask`, `fetchMetrics`, `onUnauthorized`, `request`, `fetchNext`,
   `fetchReceipt`, `fetchImageUrl`, `patchReceipt`, `completeTask` and
   `submitReview`, and none of them fetches a list — but it is public API and a
   contract that does not need to move should not move.
3. **The two export routes differ in guard, and only in guard.**
   `GET /export/receipts` is `require_user`; `GET /export/xlsx` stays
   `require_role(ROLE_ADMIN)`. Seeing the ledger and extracting it are different
   acts. This discloses nothing new: `GET /receipts` already serves
   `receipt_summary` rows to any signed-in user unscoped, which is the premise
   ADR-0031's 403-not-404 reasoning already rests on. **The scope predicate is
   shared; the permission is not.**
4. **`query_export_receipts` gains `offset`.** It takes `limit` only today. Its
   ordering is already `created_at` then `id` — a total order chosen so that
   paging cannot repeat or skip a row when two receipts share a timestamp —
   so offset is safe by construction, and its docstring already says why.
5. **The row shape is unchanged.** `receipt_summary` is reused as-is, so the
   frontend's existing `ReceiptSummary` interface needs no edit and stays read
   off the serializer. `receipt_summary` returns `id`, `status`, `confidence`,
   `merchant_name_raw`, `txn_date`, `currency`, `total` and `created_at`.
6. **The workbook download does not go through `request<T>`.** That function
   unconditionally reads `response.text()` and `JSON.parse`s it, so an xlsx body
   throws `expected JSON from ...`. A sibling, `requestBlob`, shares everything
   up to `response.ok` and diverges only on the success body.
7. **One `role="alert"` region on the screen**, shared by the list's load
   failure and the export's. `AdminScreen`'s docstring records why: two regions
   make every single-alert query match two elements and throw.

---

## 4. What gets built

**Backend**

| thing | where | note |
|---|---|---|
| `offset` parameter | `query_export_receipts` (`review/serializers.py`) | keyword-only, defaulting to 0, matching `query_receipts` |
| `GET /export/receipts` | `_install_read_routes` (`review/api.py`) | `require_user`; `PageLimit`/`PageOffset` per ADR-0034 |

**The new route goes in `_install_read_routes`, and its sibling does not live
there.** `GET /export/xlsx` is registered in `_install_write_routes` despite
being a GET. The installers group by what a route does, and this one is a pure
paginated read declaring the shared page bound, so it belongs with the reads.
Recorded here because the two routes are designed as a pair and a later reader
finding them in different installers will otherwise assume one is misplaced and
"tidy" them together.
| `ExportReceiptListResponse` | `review/schemas.py` | subclasses `_PageResponse`, per that class's own recorded reason: distinct response models give distinct OpenAPI schema names |

The route fetches `limit + 1` rows and reports `has_more` off the extra one —
the same trick `GET /receipts` and `GET /export/xlsx` already use, rather than a
`COUNT(*)` per page.

**Frontend**

| thing | where |
|---|---|
| `ReceiptsScreen.tsx` + `.module.css` | `frontend/src/receipts/` |
| `fetchExportReceipts`, `downloadExportWorkbook` | `frontend/src/api/` |
| `requestBlob` | `frontend/src/api/client.ts` |
| `'receipts'` added to the `Route` union and the pathname switch | `frontend/src/route.ts` |
| the screen wired into `App` | `frontend/src/main.tsx` |

---

## 5. Flow

```
query_export_receipts(status, merchant, dates, min_confidence, limit, offset)
        |
        +--> GET /export/receipts   receipt_summary rows   require_user
        |         |
        |         +--> ReceiptsScreen: the table, "Load more"
        |
        +--> GET /export/xlsx       the workbook           require_role(admin)
                  |
                  +--> the Export button, admin-only

GET /receipts  ----  unchanged, no caller moves
```

---

## 6. The screen

Columns, all read off `receipt_summary`:

| `txn_date` | `merchant_name_raw` | `total` with `currency` | `status` | `confidence` |

**Four of those five are nullable**, so each renders through the existing null
treatment rather than as an empty cell — ADR-0027 decision 5, `null` is not `0`
and is not empty. This is the highest-risk part of the screen for a defect no
gate can see: a green suite cannot tell a null rendered correctly from a null
rendered as blank, which is review standard 22 and what ADR-0029 section 4
exists to list.

**Identity handling copies `AdminScreen` exactly**, because that is already the
fail-closed pattern:

- `identity === null` renders a wait branch. Null means *not yet answered*,
  never *not an admin*.
- The gate is `identity.role === 'admin'`, compared positively, so every other
  value takes the narrow branch. `role` is a `string` rather than a union
  because `request<T>` is an unchecked cast.

**Paging is a "Load more" button** driven by `has_more`, appending to the rows
already shown. No page numbers and no offset arithmetic in the UI; the button
is simply absent when `has_more` is false.

---

## 7. The export button, and how it fails

`requestBlob` shares the 401 handler and `errorMessage` with `request`. That
sharing is exact rather than approximate, because **the export route's failure
responses are still JSON** — so only the success body differs.

Note that they are not all the *same* JSON. `_install_error_handlers` reshapes
`ValueError`, `DBAPIError` and `StarletteHTTPException` into
`{"error": {"message": ...}}`, but it does not cover FastAPI's
`RequestValidationError`, so a 422 arrives in FastAPI's own `detail` shape with
no `error` key at all. `messageFrom` already reads both, which is precisely why
`requestBlob` must reuse it rather than grow its own message extraction.

Download is `createObjectURL` -> anchor -> `revokeObjectURL`. Fetching the body
as a blob means **the browser no longer honours `Content-Disposition`**, so
`a.download` must be set explicitly. Read the filename from the header (the app
is same-origin, so the header is readable) with a constant fallback, rather than
writing a second copy of the server's filename that can drift from it.

Failure modes, all landing in the screen's single alert region:

- **400, more than `_EXPORT_MAX_ROWS` matching receipts.** The route refuses
  rather than truncating, on the recorded ground that a silently shortened
  export reads as a complete ledger. Its message advises narrowing by status,
  merchant or date range. **v1 has no filters, so that advice names controls
  this screen does not offer.** Surfaced verbatim anyway: ADR-0024 says the
  classifier never invents copy, and inventing kinder text here would describe a
  remedy that does not exist either. Section 9 records this as a known bound.
- **403.** Unreachable through the UI, since the button does not render for a
  non-admin. It fails closed if reached by other means.
- **401.** The shared handler fires and the session lands on login, exactly as
  it does for every other call.
- **Backend unreachable.** An `ApiError` in the same region.

**The button holds a pending state.** The workbook is built synchronously and
wholly in memory before the response is handed to Starlette, so a second click
while the first is in flight is a real hazard, not a theoretical one.

---

## 8. Testing

**The load-bearing pin is a property, not an example.** For the same filters,
the set of receipt ids returned by `GET /export/receipts` equals the set of
receipt ids the workbook from `GET /export/xlsx` contains.

That is what makes decision 1 enforced rather than merely asserted: it fails on
the next change to either side, and it is the bounded-property shape review
standard 19 and ADR-0045 decision 5 both ask for. Stated as an enumeration of
statuses instead, it would need editing every time a `ReceiptStatus` member is
added — and the enumeration is what goes stale.

Supporting pins:

- Paging over `query_export_receipts` with an offset repeats no row and skips
  none, including when two receipts share a `created_at`. This is the guarantee
  the total order exists for, and adding `offset` is what first makes it
  reachable.
- `GET /export/receipts` answers 200 for a reviewer and `GET /export/xlsx`
  answers 403 for the same session. Decision 3 is the one most likely to be
  "tidied" into matching guards by a later reader, so the asymmetry is pinned
  rather than commented.
- `requestBlob` surfaces the server's message on a 400 and fires the
  unauthorized handler on a 401 — the two behaviours it inherits from `request`
  and could silently lose by being written as a separate function.
- Both branches of the admin gate, and a role that is neither `admin` nor
  `reviewer` taking the narrow branch.
- Each nullable column renders its null treatment rather than an empty cell.

**Frontend class names are unpinnable by rendering tests.** Vitest sets
`css: false`, so a `.module.css` import returns a proxy answering for any key,
and a renamed class ships unpainted with every gate green. The new stylesheet
therefore joins the census in `frontend/tests/stylesheets.test.ts`, and gets a
reference-to-declaration guard **in both directions** — a one-directional guard
cannot see a wrapper that loses its `className` entirely.

**What no gate here can check:** how any of this looks. jsdom lays nothing out
and renders no colour — that much is a property of the gate set, not a claim
about any past milestone. `docs/MEMORY.md`'s record of the 2026-08-14 close
reports a layout regression that reached the merge with every gate and every
review green, caught only by measuring a real browser; that is its measurement,
not one re-derived here. This screen is a new table with a new stylesheet and
should be seen by a person before it is called done.

---

## 9. Known bounds, recorded rather than designed around

- **Above `_EXPORT_MAX_ROWS` matching receipts, the export button cannot
  succeed**, and its refusal advises filters v1 does not have. The list itself
  still pages normally. Building filters to dodge this would reverse the
  no-filters ruling; the honest v1 shows the refusal.
- **`buyer` is not on the list.** It reached the export and `receipt_detail` in
  the 2026-08-19 milestone but is not a `receipt_summary` field, and adding it
  widens a response contract three routes read. It belongs with a columns
  decision, not with this screen.
- **The screen does not poll.** Like `AdminScreen`, it is current as of its last
  render.

---

## 10. What this design does not decide

- **Filters, sorting and column choice.** Ruled out of v1. When they arrive,
  `GET /export/receipts` already accepts the same filter arguments as the
  workbook route, so the shared-predicate property in section 8 keeps holding
  without change — which is the main reason to define the list this way now.
- **Whether rows should ever become clickable.** Doing so would put a receipt id
  in a URL, and `route.ts`'s no-dot rule then becomes live rather than
  irrelevant. The recorded remedy is a query string, not a path segment.
- **Whether `GET /receipts` should keep its broad default at all.** Untouched
  here deliberately. It now has no frontend caller and one narrow sibling, which
  is an argument someone may want to make later; this design does not make it.
- **ISSUE-006's review-UI half.** A reviewer who mis-flags the sole purchase on
  a receipt gets zero findings at any severity and the row leaves the export
  silently. That defect is upstream of this screen: the row is already gone from
  `query_export_receipts`' results before either the list or the workbook sees
  it, so **this screen shows the same wrong answer consistently rather than
  fixing or worsening it.** Surfacing the flag is a separate design decision on
  the review screen, and the two touch the same surface — the ordering between
  them is a user ruling that has not been given.
