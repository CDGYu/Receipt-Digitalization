# ADR 0046 — The list is a projection of the export's query, and a screen nothing mounts is not delivered

**Status:** Accepted (2026-08-20)
**Builds on:** ADR-0034 (the shared page bound — its built-app guard is what
forces a new paginated route to register), ADR-0031 (`GET /receipts` being
unscoped is the premise decision 2 rests on), ADR-0027 (the design system:
`null` is not `0` is not empty), ADR-0045 (a brief is a claim about the tree —
nine of this milestone's defects were its subject matter)
**Relates to:** ADR-0029 (what the gates certify and what they cannot),
ADR-0043 (one predicate at both ends, applied to the duplicate finders),
ADR-0010 (the database is the source of truth; Excel is output only)

Derived 2026-08-19/20 on `feat/results-list-and-export`. **Re-derive rather than
quote** — every count here is a property of the tree at a moment.

---

## Context

The user asked for "the lists of results" with output going to Excel. The
obvious build is a screen over `GET /receipts`, the route that already returns
`receipt_summary` rows.

That build is wrong, and the reason is not obvious from either route's
signature. `query_receipts` applies **no status exclusion**, and its `status`
filter is a **single equality**, so it cannot express "every status except these
two". `query_export_receipts` — which is why that function exists separately at
all — excludes `PENDING` and `REJECTED` unless `status` names one explicitly.

A screen built on the first, with an export button calling the second, shows
rows the workbook silently omits. A viewer sees a list, clicks Export, and
receives strictly fewer receipts with no notice. That is the shape the
non-negotiables call *nothing silently dropped*, and it would have been
**branch-introduced**: before this milestone no frontend surface listed
receipts, so no row could vanish.

---

## Decision

### 1. The list is served by the export's own query, not by `GET /receipts`.

`GET /export/receipts` pages `query_export_receipts` and serialises with
`receipt_summary`. The list and the workbook are then the *same query*, so they
cannot disagree about scope — there is no second rule to keep in step.

This is ADR-0043's corrective applied to a new pair: **one predicate at both
ends**, not two rules that must agree. `find_duplicate_by_content` refuses to
*offer* what `mark_duplicate` would refuse to *link*; here the list refuses to
*show* what the workbook would refuse to *write*.

**`GET /receipts` was not touched.** It has no frontend caller, but it is public
API and a contract that does not need to move should not move. Two alternatives
were rejected: a `scope` parameter on `GET /receipts` (the broad default
survives beside the narrow one, so correctness still depends on every caller
choosing right — an enumerated defence wearing a flag), and narrowing
`GET /receipts` itself (a breaking change that would leave `PENDING` and
`REJECTED` reachable only one status at a time).

### 2. The two export routes share the scope predicate and differ only in guard.

`GET /export/receipts` is `require_user`; `GET /export/xlsx` stays
`require_role(ROLE_ADMIN)`. **Seeing the ledger and extracting it are different
acts.**

The relaxation discloses nothing new: `GET /receipts` already serves
`receipt_summary` rows to any signed-in user unscoped, which is the premise
ADR-0031's 403-not-404 reasoning rests on.

**This asymmetry is the thing a later reader is most likely to "tidy" into
matching guards**, so it is pinned behaviourally rather than commented —
`test_the_list_is_visible_to_a_reviewer_the_workbook_is_not`.

### 3. A new paginated route registers with the built-app guards. That is compliance, not a test edit.

`test_the_behavioural_cases_cover_every_paginated_route` derives the paginated
set from the **built app** and compares it to `PAGINATED_PATHS`. A new paginated
route therefore **fails it by construction** until somebody adds the entry.

That failure is the guard working. The standing rule that existing tests pass
unmodified exists to stop an implementer weakening a test to fit their code;
this is the opposite case, and ADR-0034's sibling guard says so in its own
docstring. Registering also enrols the route in the offset-bound sweeps for
free.

**No count is written beside `PAGINATED_PATHS`** — it was "the three routes that
page" until this milestone made it four.

### 4. A response body that is not JSON does not go through `request<T>`.

`request<T>` unconditionally calls `response.text()` and `JSON.parse`s it, so a
workbook reaches the caller as `expected JSON from ...` rather than as bytes.
`requestBlob` is its sibling: identical up to `response.ok` — same credentials,
same 401 side effect, same `ApiError` carrying the server's own message, same
guarded body read — diverging only on how the success body is read.

The sharing is exact rather than approximate because **the export route's
failures are still JSON even though its successes are not.**

Fetching the body as a blob means the browser **no longer honours
`Content-Disposition`**, so `a.download` must be set explicitly. The header is
read when present, with a constant fallback.

### 5. A screen that nothing mounts is not delivered, and reachability is pinned rather than assumed.

The entire results list — its tests, its stylesheet, its export button, and the
backend route behind it — was **deletable with all five gates green**. Removing
the import and the route branch from `main.tsx` left `tsc -b` at exit 0 and the
whole frontend suite passing. No user could reach the screen; nothing said so.

`frontend/tests/app-admin-route.test.tsx` **exists because the identical
measurement was made for `/app/admin`**, and its docstring records it. The class
recurred anyway, in the very next screen anybody built. Route mapping and
component behaviour can both be fully tested while nothing joins them.

**Both directions are asserted.** A switch that mounts the screen *everywhere*
is as broken as one that mounts it nowhere, and only the negative half
distinguishes them.

### 6. A mutation that does not compile proves nothing.

Twice on this branch a red run was produced by a **syntax error** rather than by
the property under test, and one of them nearly confirmed a real finding on that
evidence.

So: when proving a pin red by deleting code, **check the mutated tree still
compiles.** `noUnusedLocals: true` makes this sharper than it sounds — deleting
a route branch but leaving its import fails the *build*, and that red says
nothing about reachability.

This is review standard 15 with a compiler attached: a mutation that kills the
right test for the wrong reason proves nothing.

---

## Consequences

**The scope gap is now unrepresentable rather than merely absent.** Nobody has
to remember the rule, because there is no second scope to forget.

**Its cost is a shared query doing work the list does not need.**
`query_export_receipts` eager-loads `line_items` and `merchant` for
`build_export_rows`; `receipt_summary` touches neither. Every page of the list
therefore issues two extra batched SELECTs and materialises line items it
discards. Correctness is unaffected; this is the price of the shared predicate
and it is recorded rather than hidden.

**The filter surfaces are converged by a test, not by prose.** The design
originally asserted that adding filters later needed no new pin, because both
routes already accept the same arguments. That was false — the scope property is
witnessed on the `status` axis only. Rather than weaken the sentence, a test now
compares the two routes' declared query parameters over the built app, so a
filter added to one and not the other fails without anybody naming a filter.
**Its bound:** it reads *directly declared* parameters; one arriving through a
`Depends(...)` is invisible to it.

**What the gates still cannot see is the whole user-visible effect.** Nobody has
opened `/app/receipts` in a browser. The download in particular has never run in
one, and `downloadExportWorkbook` uses a **detached** anchor plus a
**synchronous** `revokeObjectURL` — the two documented cross-browser failure
modes for blob downloads. jsdom stubs `click`, `css: false` means class names
are unpinnable by rendering tests, and `e2e/**` is excluded from the Vitest run.
**ISSUE-010** is that gap. A sentence claiming the census entries *had* been
seen through a browser was written into `frontend/tests/stylesheets.test.ts` and
deleted at the whole-branch review; deleting it removed the claim, not the gap.

**Nine plan defects, every one the controller's, none in shipped behaviour.**
Three were assertions that could not fail; two "proofs" were themselves wrong.
Every one was caught by an implementer or reviewer who ran the mutation instead
of reasoning about it — which is ADR-0045's thesis, measured again by the
session that followed it.

---

## What this ADR does not decide

- **Whether rows should ever become clickable.** Doing so puts a receipt id in a
  URL, and `route.ts`'s no-dot rule becomes live rather than irrelevant: a path
  whose last segment carries a dot is served as a missing *file* and 404s. The
  recorded remedy is a query string, never a path segment.
- **Filters, sorting, or column choice**, including `buyer` on the list — it is
  on the export and on `receipt_detail`, but not on `receipt_summary`, and
  adding it widens a response contract three routes read.
- **Whether `GET /receipts` should keep its broad default.** It now has no
  frontend caller and one narrow sibling. Someone may want to make that
  argument; this ADR does not.
- **Whether the shared query should stop eager-loading for the list's sake.**
  Splitting the loader options would reintroduce a second thing to keep in step,
  which is exactly what decision 1 exists to avoid.
