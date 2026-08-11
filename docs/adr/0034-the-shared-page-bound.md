# ADR 0034 — The shared page bound

**Status:** Accepted (2026-08-11)
**Builds on:** ADR-0031 (which reported this defect and left the decision open),
ADR-0006 (the `ValueError` boundary, and what the error handlers do and do not
catch)
**Relates to:** ADR-0028 (enumerate from the artefact), review standards 14, 17
and 19

Derived 2026-08-11 against `feat/shared-page-bound`. **Re-derive rather than
quote** (ADR-0028 rule 1).

## Context

Three routes page: `GET /receipts`, `GET /review/tasks`, and
`GET /receipts/{receipt_id}/corrections`. Each declared its own window,
verbatim:

```python
limit: int = Query(50, ge=1, le=200)
offset: int = Query(0, ge=0)
```

`limit` was bounded at both ends. **`offset` had no ceiling**, so
`?offset=9223372036854775808` (`2**63`) satisfied `ge=0`, reached SQLite and
raised `OverflowError: Python int too large to convert to SQLite INTEGER`.

`OverflowError` is an `ArithmeticError`, not a `ValueError`, so none of
`_install_error_handlers`' three handlers caught it. The failure escaped **both**
contracts at once: the status contract (an unhandled 500) and the body contract
(Starlette's plain `Internal Server Error`, not `{"error": {"message": ...}}`).

ADR-0031 measured it per caller class and reported it rather than fixing it,
under review standard 19. Two of the three routes have no scope gate, so any
signed-in caller reached the 500 there; on the corrections route a reviewer
holding nothing is refused 403 before the offset ever reaches the database.

**The triplication is the reason the defect spread.** The third route did not
reinvent the flaw — it copied the declaration verbatim from a plan. A fourth
paginated route would have copied it again.

## Decision

### 1. One bound, declared once, used by every paginated route

`receipts.review.api` exports two reusable annotated parameters, and no route
spells out its own `Query(...)` for a page window:

```python
MAX_PAGE_LIMIT = 200
MAX_PAGE_OFFSET = 1_000_000

PageLimit = Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)]
PageOffset = Annotated[int, Query(ge=0, le=MAX_PAGE_OFFSET)]
```

The defaults stay at each call site (`limit: PageLimit = 50`) because FastAPI
refuses them in the alias, at decoration time. Measured 2026-08-11:
`Annotated[int, Query(50, ge=1, le=200)]` raises ``AssertionError: `Query`
default value cannot be set in `Annotated` for 'limit'. Set the default value
with `=` instead.``

They live in `api.py`, not `schemas.py`. `fastapi` is an optional extra
(ADR-0014) and `schemas.py` is pure Pydantic with exactly one importer; moving
`Query` into it would widen the fastapi-requiring surface for no gain, since
all three routes are in `api.py` already.

### 2. Out of range is a 422, in both directions

An over-large offset now behaves exactly as `offset=-1` already did: refused by
request validation, before any query runs. This is deliberately **not** routed
through the `{"error": {"message": ...}}` shape — FastAPI's
`RequestValidationError` never was, and `offset=-1` has always answered with
FastAPI's `detail` body. The fix makes the two ends of the range agree with each
other rather than inventing a third behaviour.

### 3. A million is a policy, and it is the only judgement call here

Any ceiling below `2**63` stops the overflow, so the value is not forced by
correctness. It is chosen because deep offsets are a sequential scan no index
removes, and because on the two routes that list across the whole table there
is a better tool for the job: `GET /receipts` takes `status`, `merchant_id`,
`date_from`, `date_to` and `min_confidence`, and `GET /review/tasks` takes
`state`.

**`GET /receipts/{receipt_id}/corrections` takes no filter at all** — only the
path's `receipt_id` — so that argument does not apply to it. It is bounded
anyway, because *shared* is the property and one route opting out is how the
triplication started. A million corrections against a single receipt is not a
shape this schema produces.

**It is a single constant.** Raising it is one edit; raising it *past the
overflow* is not, because the tests carry literal `2**63 - 1` and `2**63` cases
alongside the constant-derived ones.

### 4. What changes for a caller

| offset | before | after |
|---|---|---|
| `0` … `1_000_000` | 200 | 200 |
| `1_000_001` … `2**63 - 1` | 200 | **422** |
| `2**63` and above | **500** (unhandled) | **422** |
| `-1` | 422 | 422 |

The middle row is the one behaviour change a working caller could notice: an
offset above a million that used to answer 200 now answers 422. No deployment
here has a million rows in any of these tables, and the alternative — bounding
only at `2**63 - 1` — would have fixed the crash while leaving the scan
unbounded.

## How it is pinned

The property is stated over the **built app**, not over three declarations, so
it converges (review standards 17 and 19): a fourth paginated route that
re-declares `offset` by hand fails without anyone having thought of that route.

* `test_every_paginated_route_shares_one_page_bound` walks `app.routes`,
  recursing through `.original_router.routes`, and asserts every `offset` and
  every `limit` query param declares an upper bound **equal to** the shared
  constant. Equality, not mere presence — *shared* is the property, so a route
  that invents its own ceiling fails too.
* `test_the_behavioural_cases_cover_every_paginated_route` derives the route
  list from the app and compares it to the list the behavioural cases iterate,
  because a list written down is a claim (review standard 20).
* `test_an_out_of_range_offset_is_refused_by_validation_on_every_paged_route`
  drives all three routes at `0`, `MAX_PAGE_OFFSET`, `MAX_PAGE_OFFSET + 1`,
  `2**63 - 1` and `2**63`.
* `test_no_offset_reaches_the_database_as_a_500` sweeps the same range. Note
  that under `TestClient` the pre-fix failure surfaces as a **propagated
  `OverflowError`**, not as a 500 response — `raise_server_exceptions` defaults
  to true. The 500 is what a real ASGI server returns for the same input.

Constraints are read from `field_info.metadata` (a list of `annotated_types`
objects under Pydantic v2). There is no `field_info.le`: reading it directly
returns absent for every parameter, bounded or not, which would make the helper
answer `None` always and the pin vacuous. Probed against the built app before
the helper was written.

### Proven red, three ways

Each mutation applied alone and reverted before the next (review standard 4):

| mutation | result |
|---|---|
| drop `le=MAX_PAGE_OFFSET` from `PageOffset` | 13 failed |
| give `GET /receipts` its own `le=100` for `limit` | `[limit-200]` failed |
| `MAX_PAGE_OFFSET = 2**64` | 12 failed |

The second exists because the `limit` half of the shared-bound assertion was
**green from the start** — `limit` was already bounded at 200 everywhere — so
it was never proven red by the fix itself. A pin never proven red is not a pin
(review standard 14).

The third is the one that protects the policy knob: raising the constant back
above the overflow threshold cannot pass.

## Consequences

- **A fourth paginated route inherits the bound** instead of copying a
  declaration, which is how the third route acquired the defect.
- **A shipped contract narrowed.** See the table in decision 4.
- **`limit` and `offset` now change together.** They are one decision with two
  parameters; separating them again would reintroduce the triplication.
- **Validation now sits ahead of ADR-0031's existence-then-scope ordering.**
  That ADR states "existence is checked before scope, and the order is the
  contract". Request validation runs before either, so on the corrections route
  a reviewer holding nothing used to get **403 at every offset** and now gets
  **422** at an out-of-range one. Measured 2026-08-11, all five caller classes:
  the full order is **authentication → validation → existence → scope**, and
  anonymous and machine-key callers still get 401 at every offset, in range or
  not.

  This leaks nothing. The 422 is identical for every authenticated caller and
  names only the parameter, so it distinguishes neither whether the receipt
  exists nor whether the caller may read it — strictly less than the 403 it
  replaces. ADR-0031's ordering still holds for every request that reaches the
  route body.
- **The error-body contract still has a gap this does not close.** Only the
  overflow shape is fixed. Any other unhandled non-`ValueError` exception in a
  route still escapes as a plain-text 500 — `_install_error_handlers` catches
  `ValueError`, `DBAPIError` and `StarletteHTTPException`, and nothing else.
  Whether a catch-all handler should exist is not decided here.

## What this ADR does not decide

Whether `1_000_000` is the right number for a deployment with more rows than
that. It is one constant, and the tests bound where it may move, not what it
must be.

Nor whether the same treatment belongs on `GET /export/xlsx`, which caps rows
through `_EXPORT_MAX_ROWS` and refuses rather than paging — a different shape,
and out of scope.

## References

`docs/adr/0031-the-corrections-read-route.md` (§ "The `offset` ceiling", which
carries the per-caller measurement closed to `20d9bb9`);
`docs/adr/0014-optional-dependency-import-discipline.md` (why the bound is not
in `schemas.py`); `docs/adr/0028-claims-about-the-tree-are-re-derived.md` §3
(enumerate from the built app, and the `_IncludedRouter` trap the route walk
recurses through); `docs/adr/0032-a-document-cannot-certify-itself.md` §3 (why
the measurement in ADR-0031 was left standing rather than rewritten);
`tests/test_api_read.py` § "The shared page bound".
