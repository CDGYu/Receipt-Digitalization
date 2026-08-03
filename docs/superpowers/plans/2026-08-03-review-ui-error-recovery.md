# Review-UI Error Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the five design §5 error-recovery rows the Phase 5 plan dropped: a logout control, 401-with-edits-preserved, inline field errors, terminal 403/404 handling on the submit path, and a distinct 503 backend-down state.

**Architecture:** One pure client-side failure classifier (`failure.ts`) labels every caught API failure; an in-memory stash (`stash.ts`) carries dirty edits across the 401 → re-login → ADR-0016-resume cycle; `ReviewScreen`, `App`, and the form components render the classifications. The backend's Python behaviour is untouched — the only Python change is route-level pins of the message texts the classifier encodes.

**Tech Stack:** React 19 + TypeScript (Vitest, @testing-library/react) in `frontend/`; pytest + FastAPI TestClient for the pins.

**Design doc:** `docs/superpowers/specs/2026-08-03-review-ui-error-recovery-design.md` — read it first; §1 carries the measured facts every task below leans on.

## Global Constraints

- **Backend `src/` is untouched.** Task 1 adds tests only. If any task seems to need a `src/` change, STOP and report — that is a plan defect, not a judgment call.
- **`python -m pytest` stays offline and Node-free**; `python scripts/verify.py` is what "passing" means (ADR-0017).
- **`npm test` does NOT type-check.** Every frontend task runs BOTH `npm test` AND `npm run typecheck` (plus `npm run build` at task end). This trap fired three times in one milestone.
- **Money is a string end to end** (ADR-0015). Never `<input type="number">`, never `valueAsNumber`, no arithmetic on money values. `tests/no-float-in-money-path.test.ts` is measured sound — trust its verdict, not its prose.
- **No `CORSMiddleware`. SPA lives under `/app/*` only. No client-side path may gain a dotted final segment** (this plan adds no routes at all).
- **`tsconfig.app.json` sets `erasableSyntaxOnly: true`** — constructor parameter properties (`constructor(readonly x: T)`) break `npm run build` while Vitest stays green. Declare fields and assign in the body (see `ApiError` in client.ts for the pattern).
- **Do not edit `frontend/src/review/patch.ts` or `tests/test_repository.py`.** Both carry parked comment-bundles that must not be triggered by this milestone. `buildPatch` is imported, never modified.
- **Quote the server.** Error copy shown to the reviewer carries the API's own message; composed prose only frames it.
- **Every new test is proven to fail** (revert the guarantee, run, watch it go red, restore — review standard 2). A test pinning existing behaviour is proven non-vacuous by a single-variable source mutation instead (standard 3/4). Record the RED evidence in your report.
- **No comment may assert behaviour nobody executed** (standard 13). If you write "measured", include the command and output in your report.
- Stage only the files your task names. Conventional commit messages. Commit after each task's final green run.
- Piped pytest output can lose its final summary line — run with `--junitxml` and read counts from the XML when in doubt.

## File Map

| File | Task | Responsibility |
|---|---|---|
| `tests/test_api_write.py` | 1 (modify) | Route-level pins of the 400 texts, the dotted-key/422 division, logout 204 |
| `frontend/src/review/failure.ts` | 2 (create) | Pure failure classifier |
| `frontend/tests/failure.test.ts` | 2 (create) | Classifier unit tests |
| `frontend/src/review/stash.ts` | 3 (create) | In-memory dirty-edit stash |
| `frontend/tests/stash.test.ts` | 3 (create) | Stash unit tests |
| `frontend/src/SignOutControl.tsx` | 4 (create) | Logout control with dirty-confirm |
| `frontend/src/main.tsx` | 4 (modify) | Header rendering the control when signed in |
| `frontend/tests/sign-out.test.tsx` | 4 (create) | Logout behaviour tests |
| `frontend/src/review/ReviewScreen.tsx` | 5, 6, 7 (modify) | Stash integration; classification wiring; error threading |
| `frontend/tests/review-screen.test.tsx` | 5, 6, 7 (modify) | Flow tests (uses the file's existing `stubApi` harness) |
| `frontend/src/review/MoneyInput.tsx` | 7 (modify) | Optional `error` prop |
| `frontend/src/review/ReceiptForm.tsx` | 7 (modify) | Optional `errors` prop, per-field slots |
| `frontend/src/review/LineItemsTable.tsx` | 7 (modify) | Optional `errors` prop, per-cell slots |
| `frontend/tests/receipt-form.test.tsx` | 7 (modify) | Inline rendering tests |

Dependency order: 1 → 2 → 3 → 4 → 5 → 6 → 7. Task 4 needs 3; task 5 needs 3; task 6 needs 2 and 5; task 7 needs 6.

---

### Task 1: Pin the server message surface the client will encode

**Files:**
- Modify: `tests/test_api_write.py` (append; do not reorder existing tests)

**Interfaces:**
- Consumes: existing fixtures in this module — `reviewer_client` (logged-in `TestClient`), `receipt_id`, `task_id`. Read the fixture bodies (lines 79–274) before writing anything.
- Produces: the pinned message texts Task 2's classifier encodes verbatim.

**Context:** `_install_error_handlers` (src/receipts/review/api.py:128-151) wraps any `ValueError` as `400 {"error": {"message": str(exc)}}`. The texts below were measured this session by executing the coercers (`_CURRENCY_BOUND`, `_coerce_money`, `_coerce_date`, `_coerce_time` in src/receipts/persist/repository.py:1044-1170). If any assertion fails against the real route, STOP — do not adjust the expectation to match; report the discrepancy (the design's §1.3 inventory would be wrong, which is a finding).

- [ ] **Step 1: Write the failing-or-green pins**

Append to `tests/test_api_write.py`:

```python
# --------------------------------------------------------------------------- #
# The 400 texts the review UI's failure classifier encodes (error-recovery
# milestone). The client matches quoted spans in these messages against the
# paths and values it just sent, so the exact wording is load-bearing on the
# other side of the wire. See
# docs/superpowers/specs/2026-08-03-review-ui-error-recovery-design.md §1.3.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"totals.total": "abc"}, "not a decimal amount: 'abc'"),
        (
            {"totals.total": "nan"},
            "money must be a finite amount, not 'nan'; a non-finite value "
            "would destroy the stored amount and make the corrections audit "
            "row disagree with the column",
        ),
        (
            {"receipt.date": "14/07/2026"},
            "not an ISO 8601 date (YYYY-MM-DD): '14/07/2026'",
        ),
        ({"receipt.time": "2.30pm"}, "not an ISO 8601 time (HH:MM): '2.30pm'"),
        (
            {"receipt.currency": "EUROS"},
            "currency holds at most 3 characters, got 5 ('EUROS')",
        ),
    ],
)
def test_the_400_texts_the_client_matcher_encodes(
    reviewer_client, receipt_id, body, message
):
    """Each row is a value a reviewer can actually type into the UI.

    The value-coercion messages quote only the offending value, never the
    field path -- the classifier's value-quote rule exists because of that,
    so a wording change here must be mirrored in
    frontend/src/review/failure.ts and its tests.
    """
    response = reviewer_client.patch(f"/receipts/{receipt_id}", json=body)
    assert response.status_code == 400
    assert response.json() == {"error": {"message": message}}


def test_a_dotted_key_with_a_bad_value_is_the_valueerror_400_not_a_422(
    reviewer_client, receipt_id
):
    """The UI sends flat dotted keys, which bypass CorrectionPatch's typed
    sub-models (extra="allow", review/schemas.py:149) -- so even a JSON float
    smuggled under one reaches `_coerce_money` and comes back as the enveloped
    400, never FastAPI's 422 shape. The classifier's whole 400 orientation
    rests on this division."""
    response = reviewer_client.patch(f"/receipts/{receipt_id}", json={"totals.total": 1.5})
    assert response.status_code == 400
    body = response.json()
    assert "detail" not in body
    assert body["error"]["message"] == (
        "money must be a Decimal or a string, not float (1.5); "
        "a float cannot represent an exact amount"
    )


def test_logout_returns_204_with_an_empty_body_and_ends_the_session(
    reviewer_client, receipt_id
):
    """The SignOutControl's contract: 204, no body (client.ts resolves an
    empty body to `undefined`), and the session is really over."""
    response = reviewer_client.post("/auth/logout")
    assert response.status_code == 204
    assert response.content == b""
    after = reviewer_client.get(f"/receipts/{receipt_id}")
    assert after.status_code == 401
```

- [ ] **Step 2: Run the new tests**

Run: `python -m pytest tests/test_api_write.py -k "matcher_encodes or dotted_key_with_a_bad_value or logout_returns_204" -v`
Expected: ALL PASS (these pin existing behaviour). If any fails, STOP and report the actual text — do not edit the expectation.

- [ ] **Step 3: Prove each pin non-vacuous by source mutation (then restore)**

These tests cannot go RED by reverting a fix (there is no fix). Instead, one single-variable mutation per guarantee, run, restore:

1. In `src/receipts/persist/repository.py:1114`, change `not a decimal amount` to `not a decimal amount!` → the `'abc'` row must fail. Restore.
2. Same file, `:1068`, change `holds at most` to `holds at-most` → the currency row must fail. Restore.
3. In `src/receipts/review/auth.py:183`, change `status_code=204` to `status_code=200` → the logout pin must fail. Restore.

Record each command + failing assertion in your report. `git diff` must be empty over `src/` when you finish.

- [ ] **Step 4: Full suite + lint**

Run: `python -m pytest` (expect all pass, count grows by 7) and `python -m ruff check .`

- [ ] **Step 5: Commit**

```bash
git add tests/test_api_write.py
git commit -m "test(api): pin the 400 texts and logout contract the review UI encodes"
```

---

### Task 2: The failure classifier

**Files:**
- Create: `frontend/src/review/failure.ts`
- Create: `frontend/tests/failure.test.ts`

**Interfaces:**
- Consumes: `ApiError` from `../api/client` (fields: `status: number`, `message: string`); `FieldMap` type from `./patch` (`Record<string, string | null>`).
- Produces (Tasks 6 and 7 rely on these exact names):
  - `type Failure = { kind: 'backend-down' | 'taken' | 'gone' | 'other'; message: string } | { kind: 'field'; path: string; message: string }`
  - `classifyFailure(caught: unknown, options: { sentPatch?: FieldMap; fallback: string }): Failure`

- [ ] **Step 1: Write the failing tests**

`frontend/tests/failure.test.ts`:

```typescript
import { describe, expect, it } from 'vitest'
import { ApiError } from '../src/api/client'
import { classifyFailure } from '../src/review/failure'

const FALLBACK = 'the review could not be submitted'

describe('classifyFailure', () => {
  it('labels a 503 backend-down with the server words', () => {
    expect(classifyFailure(new ApiError(503, 'database unavailable'), { fallback: FALLBACK })).toEqual({
      kind: 'backend-down',
      message: 'database unavailable',
    })
  })

  it('labels a 403 taken and a 404 gone', () => {
    expect(
      classifyFailure(new ApiError(403, 'only the assignee or an admin may complete this task'), {
        fallback: FALLBACK,
      }).kind,
    ).toBe('taken')
    expect(
      classifyFailure(new ApiError(404, 'no review task with id t1'), { fallback: FALLBACK }).kind,
    ).toBe('gone')
  })

  it('matches a 400 that quotes a sent path', () => {
    // The path-quoting family, pinned server-side in tests/test_api_write.py:
    //   cannot apply a correction to 'line_items[9].qty': receipt <id> has no
    //   line item at position 9
    const failure = classifyFailure(
      new ApiError(400, "cannot apply a correction to 'line_items[9].qty': receipt a1 has no line item at position 9"),
      { sentPatch: { 'line_items[9].qty': '2' }, fallback: FALLBACK },
    )
    expect(failure).toEqual({
      kind: 'field',
      path: 'line_items[9].qty',
      message: "cannot apply a correction to 'line_items[9].qty': receipt a1 has no line item at position 9",
    })
  })

  it('matches a value-quoting 400 to the one dirty field holding that value', () => {
    // "not a decimal amount: 'abc'" quotes only the value -- the classifier
    // finds the field by what was sent.
    const failure = classifyFailure(new ApiError(400, "not a decimal amount: 'abc'"), {
      sentPatch: { 'totals.total': 'abc', 'receipt.time': '14:30:45' },
      fallback: FALLBACK,
    })
    expect(failure).toEqual({ kind: 'field', path: 'totals.total', message: "not a decimal amount: 'abc'" })
  })

  it('matches the currency bound message, whose value sits in parentheses', () => {
    const failure = classifyFailure(
      new ApiError(400, "currency holds at most 3 characters, got 5 ('EUROS')"),
      { sentPatch: { 'receipt.currency': 'EUROS' }, fallback: FALLBACK },
    )
    expect(failure).toEqual({
      kind: 'field',
      path: 'receipt.currency',
      message: "currency holds at most 3 characters, got 5 ('EUROS')",
    })
  })

  it('degrades to other when two dirty fields hold the rejected value', () => {
    const failure = classifyFailure(new ApiError(400, "not a decimal amount: 'abc'"), {
      sentPatch: { 'totals.total': 'abc', 'totals.tax': 'abc' },
      fallback: FALLBACK,
    })
    expect(failure).toEqual({ kind: 'other', message: "not a decimal amount: 'abc'" })
  })

  it('degrades to other for a 400 with no quoted span matching anything sent', () => {
    const failure = classifyFailure(new ApiError(400, 'not a boolean: None'), {
      sentPatch: { 'totals.total': '1.00' },
      fallback: FALLBACK,
    })
    expect(failure).toEqual({ kind: 'other', message: 'not a boolean: None' })
  })

  it('never matches a field without a sentPatch', () => {
    expect(
      classifyFailure(new ApiError(400, "not a decimal amount: 'abc'"), { fallback: FALLBACK }).kind,
    ).toBe('other')
  })

  it('uses the fallback for anything that is not an ApiError', () => {
    expect(classifyFailure(new TypeError('Failed to fetch'), { fallback: FALLBACK })).toEqual({
      kind: 'other',
      message: FALLBACK,
    })
  })

  it('null values never value-match (the server reprs None unquoted)', () => {
    const failure = classifyFailure(new ApiError(400, "not a decimal amount: 'null'"), {
      sentPatch: { 'totals.total': null },
      fallback: FALLBACK,
    })
    expect(failure.kind).toBe('other')
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run tests/failure.test.ts`
Expected: FAIL — cannot resolve `../src/review/failure`.

- [ ] **Step 3: Implement**

`frontend/src/review/failure.ts`:

```typescript
import { ApiError } from '../api/client'
import type { FieldMap } from './patch'

/** One caught failure, labelled once, so every render site branches on a
 * name instead of re-deriving status semantics.
 *
 * The `field` kind exists for the 400 `ValueError` boundary only. A
 * field-level 422 is unreachable from this client -- the patch goes up as
 * flat dotted keys, which bypass `CorrectionPatch`'s typed sub-models
 * (`extra="allow"`), and every value is already a string; even a smuggled
 * float comes back as the enveloped 400. Pinned server-side by
 * `test_a_dotted_key_with_a_bad_value_is_the_valueerror_400_not_a_422`.
 *
 * 401 is deliberately absent: `client.ts` owns it at the transport
 * (`onUnauthorized`), before any screen logic runs.
 */
export type Failure =
  | { readonly kind: 'backend-down'; readonly message: string }
  | { readonly kind: 'taken'; readonly message: string }
  | { readonly kind: 'gone'; readonly message: string }
  | { readonly kind: 'field'; readonly path: string; readonly message: string }
  | { readonly kind: 'other'; readonly message: string }

/** Every `'…'`-quoted span in a server message.
 *
 * The 400 texts come in two families, both pinned in
 * tests/test_api_write.py: path-quoting ("cannot apply a correction to
 * 'line_items[9].qty': …") and value-quoting ("not a decimal amount:
 * 'abc'", "currency holds at most 3 characters, got 5 ('EUROS')"). A
 * value whose Python repr switches to double quotes (it contains an
 * apostrophe) simply yields no span here and degrades to `other` -- the
 * summary alert, which is exactly what ships today.
 */
function quotedSpans(message: string): string[] {
  return [...message.matchAll(/'([^']*)'/g)].map((match) => match[1])
}

function matchField(message: string, sent: FieldMap): string | null {
  const spans = quotedSpans(message)
  const paths = Object.keys(sent)

  const pathMatches = paths.filter((path) => spans.includes(path))
  if (pathMatches.length === 1) {
    return pathMatches[0]
  }
  if (pathMatches.length > 1) {
    return null
  }

  const valueMatches = paths.filter((path) => {
    const value = sent[path]
    return typeof value === 'string' && spans.includes(value)
  })
  return valueMatches.length === 1 ? valueMatches[0] : null
}

/** Label `caught`. `fallback` is the caller's sentence for a failure that
 * carries no server words (a network `TypeError`); the classifier never
 * invents copy of its own. `sentPatch` -- the exact dirty map just sent --
 * enables the `field` kind; without it a 400 is `other`.
 */
export function classifyFailure(
  caught: unknown,
  options: { readonly sentPatch?: FieldMap; readonly fallback: string },
): Failure {
  if (!(caught instanceof ApiError)) {
    return { kind: 'other', message: options.fallback }
  }
  if (caught.status === 503) {
    return { kind: 'backend-down', message: caught.message }
  }
  if (caught.status === 403) {
    return { kind: 'taken', message: caught.message }
  }
  if (caught.status === 404) {
    return { kind: 'gone', message: caught.message }
  }
  if (caught.status === 400 && options.sentPatch !== undefined) {
    const path = matchField(caught.message, options.sentPatch)
    if (path !== null) {
      return { kind: 'field', path, message: caught.message }
    }
  }
  return { kind: 'other', message: caught.message }
}
```

- [ ] **Step 4: Run tests, typecheck, build**

Run: `cd frontend && npx vitest run tests/failure.test.ts && npm run typecheck && npm run build`
Expected: all green.

- [ ] **Step 5: RED-proof the two matching rules (then restore)**

1. Change `pathMatches.length === 1` to `>= 1` — the ambiguous-path behaviour is not directly tested (no message quotes two paths today), so instead delete the `pathMatches` block entirely: the path-quote test must fail (the message also quotes `receipt a1`? it does not — only the path is quoted, so deletion drops to value-matching, which finds no value span equal to `'2'`... the quoted spans are the path only, so the test fails with `kind: 'other'`). Verify, restore.
2. Change `valueMatches.length === 1` to `>= 1` — the two-fields-`'abc'` test must fail. Verify, restore.

Record both runs. Then `cd frontend && npm test` (full Vitest) — all green.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/review/failure.ts frontend/tests/failure.test.ts
git commit -m "feat(frontend): classify API failures once, by status and quoted spans"
```

---

### Task 3: The stash

**Files:**
- Create: `frontend/src/review/stash.ts`
- Create: `frontend/tests/stash.test.ts`

**Interfaces:**
- Consumes: `FieldMap` from `./patch`.
- Produces (Tasks 4, 5, 6 rely on these exact names):
  - `remember(taskId: string, overlay: FieldMap): void`
  - `restore(taskId: string): FieldMap | null` — non-consuming
  - `hasDirtyEdits(): boolean` — true iff a stash exists with a non-empty overlay
  - `clear(): void`

- [ ] **Step 1: Write the failing tests**

`frontend/tests/stash.test.ts`:

```typescript
import { afterEach, describe, expect, it } from 'vitest'
import { clear, hasDirtyEdits, remember, restore } from '../src/review/stash'

// Module state, so every test starts from nothing (same discipline as
// session.test.ts applies to session.ts's module state).
afterEach(() => {
  clear()
})

describe('the edit stash', () => {
  it('returns the overlay for the task that stored it', () => {
    remember('t1', { 'totals.total': '99.00' })
    expect(restore('t1')).toEqual({ 'totals.total': '99.00' })
  })

  it('returns null for a different task', () => {
    remember('t1', { 'totals.total': '99.00' })
    expect(restore('t2')).toBeNull()
  })

  it('is non-consuming: a second restore still answers', () => {
    // A second 401 before any new edit must not lose what the first kept.
    remember('t1', { 'totals.total': '99.00' })
    restore('t1')
    expect(restore('t1')).toEqual({ 'totals.total': '99.00' })
  })

  it('hands out copies, not its own object', () => {
    const overlay = { 'totals.total': '99.00' }
    remember('t1', overlay)
    overlay['totals.total'] = 'mutated'
    const first = restore('t1')!
    first['totals.total'] = 'also mutated'
    expect(restore('t1')).toEqual({ 'totals.total': '99.00' })
  })

  it('a later remember replaces the earlier one, whatever the task', () => {
    remember('t1', { 'totals.total': '99.00' })
    remember('t2', { 'totals.tax': '1.00' })
    expect(restore('t1')).toBeNull()
    expect(restore('t2')).toEqual({ 'totals.tax': '1.00' })
  })

  it('hasDirtyEdits is false when empty, false for an empty overlay, true otherwise', () => {
    expect(hasDirtyEdits()).toBe(false)
    remember('t1', {})
    expect(hasDirtyEdits()).toBe(false)
    remember('t1', { 'totals.total': '99.00' })
    expect(hasDirtyEdits()).toBe(true)
  })

  it('clear forgets everything', () => {
    remember('t1', { 'totals.total': '99.00' })
    clear()
    expect(restore('t1')).toBeNull()
    expect(hasDirtyEdits()).toBe(false)
  })

  it('a null value (a cleared field) survives the round trip', () => {
    remember('t1', { 'merchant.name': null })
    expect(restore('t1')).toEqual({ 'merchant.name': null })
    expect(hasDirtyEdits()).toBe(true)
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run tests/stash.test.ts`
Expected: FAIL — cannot resolve `../src/review/stash`.

- [ ] **Step 3: Implement**

`frontend/src/review/stash.ts`:

```typescript
import type { FieldMap } from './patch'

/** The reviewer's unsubmitted edits, surviving a 401's unmount.
 *
 * Module state, deliberately -- the same choice `session.ts` records for the
 * signed-in flag. A 401 unmounts `ReviewScreen`; on re-login ADR-0016 hands
 * the same task back (`GET /review/next` resumes the caller's own
 * `IN_PROGRESS` row), and this is where the edits wait in between. Nothing
 * touches browser storage: a full page reload starts clean, exactly as it
 * did before this module existed -- that trade is a user ruling recorded in
 * the design doc (§2).
 *
 * The overlay is the **dirty diff** (`buildPatch(original, fields)`), never
 * the whole form: restoring is `{ ...freshOriginal, ...overlay }`, so paths
 * the reviewer never touched always show what the server holds now. After a
 * complete-step 401 (the PATCH landed, the close did not) the fresh original
 * already contains the applied values, the overlay overlays equals onto
 * equals, and the form comes back clean rather than falsely dirty --
 * review-screen.test.tsx pins that.
 *
 * At most one entry. A reviewer holds at most one claimed task (`fetchNext`
 * is called at most once per task in hand), so a second `remember` for a
 * different task means the first task is gone -- keeping its edits would be
 * a leak, not a kindness.
 */
let stashed: { readonly taskId: string; readonly overlay: FieldMap } | null = null

export function remember(taskId: string, overlay: FieldMap): void {
  stashed = { taskId, overlay: { ...overlay } }
}

/** The overlay for `taskId`, or null. Non-consuming: a second 401 before any
 *  new edit must not lose what the first one kept. Returns a copy. */
export function restore(taskId: string): FieldMap | null {
  if (stashed === null || stashed.taskId !== taskId) {
    return null
  }
  return { ...stashed.overlay }
}

/** Whether anything worth confirming away is held (the sign-out gate). */
export function hasDirtyEdits(): boolean {
  return stashed !== null && Object.keys(stashed.overlay).length > 0
}

export function clear(): void {
  stashed = null
}
```

- [ ] **Step 4: Run tests, typecheck**

Run: `cd frontend && npx vitest run tests/stash.test.ts && npm run typecheck`
Expected: all green.

- [ ] **Step 5: RED-proof (then restore)**

1. Make `restore` consuming (`const out = { ...stashed.overlay }; stashed = null; return out`) — the non-consuming test must fail. Restore.
2. Make `remember` store the caller's object (`overlay` without the spread) — the copies test must fail. Restore.

Run the full suite: `cd frontend && npm test` — green.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/review/stash.ts frontend/tests/stash.test.ts
git commit -m "feat(frontend): an in-memory stash for unsubmitted edits"
```

---

### Task 4: The sign-out control

**Files:**
- Create: `frontend/src/SignOutControl.tsx`
- Modify: `frontend/src/main.tsx` (the `App` function, lines 29-36)
- Create: `frontend/tests/sign-out.test.tsx`

**Interfaces:**
- Consumes: `request`, `ApiError` from `./api/client`; `setSignedIn` from `./session`; `clear`, `hasDirtyEdits` from `./review/stash` (Task 3).
- Produces: `SignOutControl(): JSX element` — no props. `App` renders it in a `<header>` above `ReviewScreen` when signed in.

**Context:** `POST /auth/logout` → 204 empty body (pinned in Task 1); `request` resolves the empty body to `undefined`. A 401 from the call means the session was already dead — `client.ts` fires `onUnauthorized` **before** throwing, so `setSignedIn(false)` has already happened; the control only clears the stash on that path. The stash-clearing rule (design §4.2): **cleared exactly when the session actually ends** (204 or 401); any other failure stays signed in with the stash intact.

- [ ] **Step 1: Write the failing tests**

`frontend/tests/sign-out.test.tsx`:

```typescript
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SignOutControl } from '../src/SignOutControl'
import { setSignedIn, isSignedIn } from '../src/session'
import { clear, hasDirtyEdits, remember, restore } from '../src/review/stash'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  clear()
  setSignedIn(true)
})

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('the sign-out control', () => {
  it('signs out on a 204 and clears the stash', async () => {
    setSignedIn(true)
    remember('t1', { 'totals.total': '99.00' })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })))
    render(<SignOutControl />)

    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    // Dirty, so the first click arms the confirm; the discard button completes it.
    await userEvent.click(screen.getByRole('button', { name: 'Discard edits and sign out' }))

    expect(isSignedIn()).toBe(false)
    expect(restore('t1')).toBeNull()
  })

  it('signs out without a confirm step when nothing is dirty', async () => {
    setSignedIn(true)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })))
    render(<SignOutControl />)

    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))

    expect(isSignedIn()).toBe(false)
  })

  it('cancel keeps the session and the edits', async () => {
    setSignedIn(true)
    remember('t1', { 'totals.total': '99.00' })
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    render(<SignOutControl />)

    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(fetchMock).not.toHaveBeenCalled()
    expect(isSignedIn()).toBe(true)
    expect(hasDirtyEdits()).toBe(true)
    // The control is back to its resting state.
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeTruthy()
  })

  it('stays signed in, keeps the stash, and says why when logout fails', async () => {
    setSignedIn(true)
    remember('t1', { 'totals.total': '99.00' })
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(503, { error: { message: 'database unavailable' } })),
    )
    render(<SignOutControl />)

    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    await userEvent.click(screen.getByRole('button', { name: 'Discard edits and sign out' }))

    expect(await screen.findByRole('alert')).toHaveProperty(
      'textContent',
      expect.stringContaining('database unavailable'),
    )
    expect(isSignedIn()).toBe(true)
    expect(hasDirtyEdits()).toBe(true)
  })

  it('a 401 ends the session client-side and clears the stash', async () => {
    setSignedIn(true)
    remember('t1', { 'totals.total': '99.00' })
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(401, { error: { message: 'not signed in' } })),
    )
    render(<SignOutControl />)

    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    await userEvent.click(screen.getByRole('button', { name: 'Discard edits and sign out' }))

    // client.ts fired onUnauthorized before throwing, so the session module
    // already flipped; the control's own job is the stash.
    expect(isSignedIn()).toBe(false)
    expect(restore('t1')).toBeNull()
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run tests/sign-out.test.tsx`
Expected: FAIL — cannot resolve `../src/SignOutControl`.

- [ ] **Step 3: Implement the control**

`frontend/src/SignOutControl.tsx`:

```tsx
import { useState } from 'react'
import { ApiError, request } from './api/client'
import { setSignedIn } from './session'
import { clear, hasDirtyEdits } from './review/stash'

/** Sign out, honestly.
 *
 * The session cookie is server state, so this control never pretends: on any
 * failure that leaves the cookie alive it stays signed in and shows the
 * server's words. The stash is cleared exactly when the session actually
 * ends -- a 204, or a 401 that means it was already over (`client.ts` fires
 * `onUnauthorized` before throwing, so the signed-in flag has flipped by the
 * time the catch runs; only the stash is left to clean). Any other ending
 * keeps the stash: the discard did not happen, the edits are still live on
 * screen, and the stash keeps tracking them.
 *
 * Dirty edits gate the click behind a two-step inline confirm rather than
 * `window.confirm` -- the same explicit-DOM choice the rest of this app
 * makes, and testable the same way. A held claimed task is deliberately left
 * alone: ADR-0016 hands it back at the next sign-in.
 */
export function SignOutControl() {
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function signOut(): Promise<void> {
    setBusy(true)
    setError(null)
    try {
      await request('/auth/logout', { method: 'POST' })
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        clear()
        return
      }
      setBusy(false)
      setConfirming(false)
      setError(caught instanceof ApiError ? caught.message : 'could not sign out')
      return
    }
    clear()
    setSignedIn(false)
  }

  if (confirming) {
    return (
      <span>
        <span role="alert">You have unsaved edits on this receipt.</span>
        <button type="button" disabled={busy} onClick={() => void signOut()}>
          Discard edits and sign out
        </button>
        <button type="button" disabled={busy} onClick={() => setConfirming(false)}>
          Cancel
        </button>
      </span>
    )
  }
  return (
    <span>
      <button
        type="button"
        disabled={busy}
        onClick={() => {
          if (hasDirtyEdits()) {
            setConfirming(true)
            return
          }
          void signOut()
        }}
      >
        Sign out
      </button>
      {error !== null && <span role="alert">Could not sign out: {error}</span>}
    </span>
  )
}
```

- [ ] **Step 4: Wire it into `App`**

In `frontend/src/main.tsx`, add the import and change only `App`'s signed-in return (the docstring gains one sentence noting the header):

```tsx
import { SignOutControl } from './SignOutControl'
```

```tsx
function App() {
  const signedIn = useSyncExternalStore(subscribe, isSignedIn)

  if (!signedIn) {
    return <LoginPage onSignedIn={() => setSignedIn(true)} />
  }
  return (
    <>
      <header>
        <SignOutControl />
      </header>
      <ReviewScreen />
    </>
  )
}
```

- [ ] **Step 5: Run everything**

Run: `cd frontend && npx vitest run tests/sign-out.test.tsx && npm test && npm run typecheck && npm run build`
Expected: all green — including `tests/app-root.test.tsx`, which still passes because a render throw from `ReviewScreen` reaches the boundary above `App` and replaces the whole tree, header included. If app-root fails, STOP and report; do not restructure it.

- [ ] **Step 6: RED-proof (then restore)**

1. Remove the `clear()` on the 204 path — the first test's `restore('t1')` assertion must fail. Restore.
2. Swap the failure branch to `setSignedIn(false)` — the 503 test must fail on `isSignedIn()`. Restore.
3. Remove the `hasDirtyEdits()` gate — the cancel test must fail (fetch called). Restore.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/SignOutControl.tsx frontend/src/main.tsx frontend/tests/sign-out.test.tsx
git commit -m "feat(frontend): a sign-out control that never pretends"
```

---

### Task 5: ReviewScreen keeps edits across a 401

**Files:**
- Modify: `frontend/src/review/ReviewScreen.tsx`
- Modify: `frontend/tests/review-screen.test.tsx` (append; use the file's existing `stubApi`/`TASK`/`RECEIPT` helpers — read lines 1-130 first)

**Interfaces:**
- Consumes: `remember`, `restore`, `clear` from `./stash` (Task 3); `buildPatch` from `./patch` (unchanged).
- Produces: the stash lifecycle later tasks extend (Task 6 adds two more clear points).

**Context:** `ReviewScreen`'s `load()` (lines 179-211) claims-or-resumes then fetches the receipt; `edit()` (268-274) updates `fields` inside a `setPhase` updater; `approve`/`closeTaskOnly`/`skipHeldTask` null `claimed.current` after a successful close. The remember-hook must NOT live inside the `setPhase` updater (updaters must be pure and StrictMode double-invokes them) — use an effect on `phase`.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/tests/review-screen.test.tsx` (inside the top-level `describe`, or as a new `describe('the edit stash', ...)` block; import `clear` and `restore` from `../src/review/stash` at the top of the file, and add `clear()` to the existing `afterEach`):

```tsx
describe('the edit stash across a 401', () => {
  it('restores unsubmitted edits when ADR-0016 hands the same task back', async () => {
    // First mount: edit a field, then unmount -- the 401 path unmounts the
    // screen exactly this way (App swaps to LoginPage).
    const first = stubApi({
      '/review/next': [200, { task: TASK, receipt: SUMMARY }],
      '/receipts/a1': [200, RECEIPT],
    })
    vi.stubGlobal('fetch', first)
    const { unmount } = render(<StrictMode><ReviewScreen /></StrictMode>)
    const total = await screen.findByLabelText('Total')
    await userEvent.clear(total)
    await userEvent.type(total, '99.00')
    unmount()

    // Second mount, fresh claim state: the resume returns the same task and
    // the same stored receipt; the edit must come back dirty.
    const second = stubApi({
      '/review/next': [200, { task: TASK, receipt: SUMMARY }],
      '/receipts/a1': [200, RECEIPT],
    })
    vi.stubGlobal('fetch', second)
    render(<StrictMode><ReviewScreen /></StrictMode>)

    const restored = await screen.findByLabelText('Total')
    expect((restored as HTMLInputElement).value).toBe('99.00')
  })

  it('does not restore onto a different task', async () => {
    const first = stubApi({
      '/review/next': [200, { task: TASK, receipt: SUMMARY }],
      '/receipts/a1': [200, RECEIPT],
    })
    vi.stubGlobal('fetch', first)
    const { unmount } = render(<StrictMode><ReviewScreen /></StrictMode>)
    const total = await screen.findByLabelText('Total')
    await userEvent.clear(total)
    await userEvent.type(total, '99.00')
    unmount()

    const otherTask = { ...TASK, id: 't2', receipt_id: 'a1' }
    const second = stubApi({
      '/review/next': [200, { task: otherTask, receipt: SUMMARY }],
      '/receipts/a1': [200, RECEIPT],
    })
    vi.stubGlobal('fetch', second)
    render(<StrictMode><ReviewScreen /></StrictMode>)

    const fresh = await screen.findByLabelText('Total')
    expect((fresh as HTMLInputElement).value).toBe(RECEIPT.totals.total)
  })

  it('comes back clean after a complete-step 401: the patch landed, so the fresh original already holds the edit', async () => {
    // PATCH succeeds and returns the receipt WITH the new total; complete 401s.
    const patched = {
      ...RECEIPT,
      totals: { ...RECEIPT.totals, total: '99.0000' as Money },
    }
    const first = stubApi({
      '/review/next': [200, { task: TASK, receipt: SUMMARY }],
      'GET /receipts/a1': [200, RECEIPT],
      'PATCH /receipts/a1': [200, patched],
      '/review/t1/complete': [401, { error: { message: 'session expired' } }],
    })
    vi.stubGlobal('fetch', first)
    const { unmount } = render(<StrictMode><ReviewScreen /></StrictMode>)
    const total = await screen.findByLabelText('Total')
    await userEvent.clear(total)
    await userEvent.type(total, '99.0000')
    await userEvent.keyboard('{Control>}{Enter}{/Control}')
    await screen.findByRole('alert')
    unmount()

    // Re-login: the resume returns the same task; the receipt now stores the
    // patched value. The overlay overlays equals onto equals: approving again
    // must send an empty patch, not a spurious re-correction.
    const second = stubApi({
      '/review/next': [200, { task: TASK, receipt: SUMMARY }],
      'GET /receipts/a1': [200, patched],
      'PATCH /receipts/a1': [200, patched],
      '/review/t1/complete': [200, { ...TASK, state: 'done' }],
    })
    vi.stubGlobal('fetch', second)
    render(<StrictMode><ReviewScreen /></StrictMode>)
    await screen.findByLabelText('Total')
    await userEvent.keyboard('{Control>}{Enter}{/Control}')
    await waitFor(() => {
      expect(patchBody(second)).toEqual({})
    })
  })

  it('a submitted receipt leaves nothing to restore', async () => {
    const fetchMock = stubApi({
      '/review/next': [
        [200, { task: TASK, receipt: SUMMARY }],
        [200, { task: null }],
      ],
      'GET /receipts/a1': [200, RECEIPT],
      'PATCH /receipts/a1': [200, RECEIPT],
      '/review/t1/complete': [200, { ...TASK, state: 'done' }],
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<StrictMode><ReviewScreen /></StrictMode>)
    const total = await screen.findByLabelText('Total')
    await userEvent.clear(total)
    await userEvent.type(total, '99.00')
    await userEvent.keyboard('{Control>}{Enter}{/Control}')
    await screen.findByText('The review queue is empty.')

    expect(restore('t1')).toBeNull()
  })
})
```

(Adjust helper imports to what the file already has — `waitFor`, `Money`; do not duplicate existing imports. If `screen.findByLabelText('Total')` collides with line-item labels, use the exact-match form the existing tests use.)

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run tests/review-screen.test.tsx`
Expected: the four new tests FAIL (no stash wiring); every pre-existing test still PASSES.

- [ ] **Step 3: Implement in `ReviewScreen.tsx`**

Three changes, nothing else:

1. Import: `import { clear as clearStash, remember, restore } from './stash'`
2. In `load()`, replace the two lines that build `original`/`fields`:

```typescript
      const receipt = await fetchReceipt(task.receipt_id)
      const original = fieldsFromReceipt(receipt)
      // The edits a 401 unmounted, if this is the task they belonged to --
      // ADR-0016 hands the same task back after re-login, and the overlay
      // holds only dirty entries, so untouched paths always show the stored
      // value (design §4.1).
      const overlay = restore(task.id)
      const fields = overlay === null ? { ...original } : { ...original, ...overlay }
      setPhase({ kind: 'claimed', task, receipt, original, fields })
```

3. After the `edit` callback, the remember-effect (an effect, not a line inside the `setPhase` updater — updaters must stay pure, and StrictMode double-invokes them):

```typescript
  // Mirror the dirty diff into the stash on every committed change. Runs
  // after render, so it sees the fields React actually kept; idempotent, so
  // StrictMode's double-invocation is harmless.
  useEffect(() => {
    if (phase.kind === 'claimed') {
      remember(phase.task.id, buildPatch(phase.original, phase.fields))
    }
  }, [phase])
```

4. Clear the stash at every point `claimed.current` is nulled after a successful close — one line, `clearStash()`, immediately after each `claimed.current = null` in `approve` (the success path) and `closeTaskOnly`, and after the one in `skipHeldTask`.

- [ ] **Step 4: Run the file, then everything**

Run: `cd frontend && npx vitest run tests/review-screen.test.tsx && npm test && npm run typecheck && npm run build`
Expected: all green.

- [ ] **Step 5: RED-proof (then restore)**

1. Delete the `overlay` restore (use `{ ...original }` unconditionally) — tests 1 and 3-second-half must fail. Restore.
2. Delete the `clearStash()` in `approve` — the leaves-nothing-to-restore test must fail. Restore.
3. Change the effect to `remember(phase.task.id, phase.fields)` (whole form, not the diff) — the complete-step-401 test must fail (`patchBody` is the whole form, not `{}`)... **verify this actually fails**; if it passes, the mutation is not discriminated by the suite — report that rather than inventing a weaker claim, and pin it with an explicit `restore('t1')` shape assertion in test 1 (`expect(restore('t1')).toEqual({'totals.total': '99.00'})`).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/review/ReviewScreen.tsx frontend/tests/review-screen.test.tsx
git commit -m "feat(frontend): unsubmitted edits survive a 401 via the stash"
```

---

### Task 6: Terminal states — taken, gone, backend-down, and the skip dead-end

**Files:**
- Modify: `frontend/src/review/ReviewScreen.tsx`
- Modify: `frontend/tests/review-screen.test.tsx` (append)

**Interfaces:**
- Consumes: `classifyFailure`, `Failure` from `./failure` (Task 2); the stash clears from Task 5.
- Produces (Task 7 relies on these): `Submit`'s `failed` variant gains `readonly failure: Failure`; `Phase`'s `failed` variant gains `readonly failure: Failure`; a new `Submit` variant `{ kind: 'lost'; flavor: 'taken' | 'gone'; message: string }`.

**Context:** the design's §6. The fallback sentences already in the file stay exactly as they are: `'the review could not be submitted'` (apiMessage), `'could not load the review queue'` (load), `'the request did not reach the API'` (skip).

- [ ] **Step 1: Write the failing tests**

Append to `frontend/tests/review-screen.test.tsx`:

```tsx
describe('terminal submit and load states', () => {
  it('a 403 on complete says what survived and offers only Next receipt', async () => {
    const fetchMock = stubApi({
      '/review/next': [
        [200, { task: TASK, receipt: SUMMARY }],
        [200, { task: null }],
      ],
      'GET /receipts/a1': [200, RECEIPT],
      'PATCH /receipts/a1': [200, RECEIPT],
      '/review/t1/complete': [
        403,
        { error: { message: 'only the assignee or an admin may complete this task' } },
      ],
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<StrictMode><ReviewScreen /></StrictMode>)
    await screen.findByLabelText('Total')
    await userEvent.keyboard('{Control>}{Enter}{/Control}')

    const notice = await screen.findByText('Saved, but this task was taken over by someone else')
    expect(notice).toBeTruthy()
    expect(screen.getByText(/only the assignee or an admin/)).toBeTruthy()
    // No retry affordances -- they would fail identically forever.
    expect(screen.queryByRole('button', { name: 'Close task' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Approve (⌘↵)' })).toBeNull()

    // The chord is dead here: it must not re-run the chain.
    const patches = chain(fetchMock).filter((c) => c.startsWith('PATCH')).length
    await userEvent.keyboard('{Control>}{Enter}{/Control}')
    expect(chain(fetchMock).filter((c) => c.startsWith('PATCH')).length).toBe(patches)

    // The one exit advances.
    await userEvent.click(screen.getByRole('button', { name: 'Next receipt' }))
    await screen.findByText('The review queue is empty.')
  })

  it('a 404 on complete reads as gone, with the same single exit', async () => {
    const fetchMock = stubApi({
      '/review/next': [
        [200, { task: TASK, receipt: SUMMARY }],
        [200, { task: null }],
      ],
      'GET /receipts/a1': [200, RECEIPT],
      'PATCH /receipts/a1': [200, RECEIPT],
      '/review/t1/complete': [404, { error: { message: 'no review task with id t1' } }],
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<StrictMode><ReviewScreen /></StrictMode>)
    await screen.findByLabelText('Total')
    await userEvent.keyboard('{Control>}{Enter}{/Control}')

    await screen.findByText('Saved, but this task no longer exists')
    expect(screen.queryByRole('button', { name: 'Close task' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Next receipt' }))
    await screen.findByText('The review queue is empty.')
  })

  it('a 503 on submit is a distinct backend-down state that keeps the narrow retry', async () => {
    const fetchMock = stubApi({
      '/review/next': [200, { task: TASK, receipt: SUMMARY }],
      'GET /receipts/a1': [200, RECEIPT],
      'PATCH /receipts/a1': [503, { error: { message: 'database unavailable' } }],
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<StrictMode><ReviewScreen /></StrictMode>)
    await screen.findByLabelText('Total')
    await userEvent.keyboard('{Control>}{Enter}{/Control}')

    await screen.findByText('The database is unavailable — nothing can be saved right now.')
    // The chain can be retried once the database is back: Approve survives.
    expect(screen.getByRole('button', { name: 'Approve (⌘↵)' })).toBeTruthy()
  })

  it('a 503 on load is backend-down and does NOT offer Skip', async () => {
    const fetchMock = stubApi({
      '/review/next': [200, { task: TASK, receipt: SUMMARY }],
      'GET /receipts/a1': [503, { error: { message: 'database unavailable' } }],
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<StrictMode><ReviewScreen /></StrictMode>)

    await screen.findByText('The database is unavailable — nothing can be saved right now.')
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy()
    // Skip's completeTask needs the same database; offering it is a false exit.
    expect(screen.queryByRole('button', { name: 'Skip this receipt' })).toBeNull()
  })

  it('a receipt-404 with a live task still offers Skip (unchanged)', async () => {
    const fetchMock = stubApi({
      '/review/next': [200, { task: TASK, receipt: SUMMARY }],
      'GET /receipts/a1': [404, { error: { message: 'no receipt with id a1' } }],
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<StrictMode><ReviewScreen /></StrictMode>)

    await screen.findByRole('alert')
    expect(screen.getByRole('button', { name: 'Skip this receipt' })).toBeTruthy()
  })

  it("skip's own completeTask answering 404 releases and moves on instead of dead-ending", async () => {
    const fetchMock = stubApi({
      '/review/next': [
        [200, { task: TASK, receipt: SUMMARY }],
        [200, { task: null }],
      ],
      'GET /receipts/a1': [404, { error: { message: 'no receipt with id a1' } }],
      '/review/t1/complete': [404, { error: { message: 'no review task with id t1' } }],
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<StrictMode><ReviewScreen /></StrictMode>)

    await screen.findByRole('alert')
    await userEvent.click(screen.getByRole('button', { name: 'Skip this receipt' }))

    await screen.findByText('The review queue is empty.')
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run tests/review-screen.test.tsx`
Expected: the six new tests FAIL; every pre-existing test still PASSES. (The pre-existing skip test `a skipped receipt stays recoverable` in test_api_write.py is Python and untouched.)

- [ ] **Step 3: Implement in `ReviewScreen.tsx`**

1. Import: `import { classifyFailure } from './failure'` and `import type { Failure } from './failure'`.
2. Extend the two state unions:

```typescript
  | {
      readonly kind: 'failed'
      readonly message: string
      readonly heldTask: ReviewTask | null
      /** What kind of failure this is -- backend-down suppresses the Skip
       *  escape, because Skip's own completeTask needs the same database. */
      readonly failure: Failure
    }
```

```typescript
type Submit =
  | { readonly kind: 'idle' }
  | { readonly kind: 'busy' }
  | {
      readonly kind: 'failed'
      readonly message: string
      readonly openTaskId: string | null
      readonly failure: Failure
    }
  /** The chain's close was refused in a way no retry can fix: the task was
   *  taken over (403) or deleted (404). The PATCH landed -- the state says
   *  what survived -- and the only exit is an explicit advance. No
   *  auto-advance, for the same measured muscle-memory reason as
   *  `StoredDifferently`; `submittedTask` stays set so the chord is dead. */
  | { readonly kind: 'lost'; readonly flavor: 'taken' | 'gone'; readonly message: string }
  | { readonly kind: 'held'; readonly outcome: Held }
```

3. Rework `submitFailure` (keep `apiMessage` as is) and its caller:

```typescript
function submitFailure(caught: unknown, taskId: string, sentPatch: FieldMap): Submit {
  const cause = caught instanceof SubmitError ? caught.cause : caught
  const step = caught instanceof SubmitError ? caught.step : null
  const failure = classifyFailure(cause, {
    sentPatch: step === 'patch' ? sentPatch : undefined,
    fallback: 'the review could not be submitted',
  })
  if (step === 'complete' && (failure.kind === 'taken' || failure.kind === 'gone')) {
    return { kind: 'lost', flavor: failure.kind, message: failure.message }
  }
  const message = apiMessage(caught)
  if (step === 'complete') {
    return {
      kind: 'failed',
      message: `Saved, but the task is still open: ${message}`,
      openTaskId: taskId,
      failure,
    }
  }
  return { kind: 'failed', message: `Not saved: ${message}`, openTaskId: null, failure }
}
```

In `approve`, hoist the patch so both the send and the classification see the identical object, and keep the chord dead on `lost`:

```typescript
    const { task, receipt, original, fields } = phase
    const sentPatch = buildPatch(original, fields)
    submittedTask.current = task.id
    setSubmit({ kind: 'busy' })
    let outcome: SubmitOutcome
    try {
      outcome = await submitReview(receipt.id, task.id, sentPatch)
    } catch (caught) {
      const next = submitFailure(caught, task.id, sentPatch)
      // A lost task cannot be resubmitted -- the guard stays armed and the
      // only exit is the explicit advance. Every other failure is retryable.
      if (next.kind !== 'lost') {
        submittedTask.current = null
      }
      setSubmit(next)
      return
    }
```

`closeTaskOnly`'s catch gets the same treatment (classify with no `sentPatch`; `taken`/`gone` → `lost` and the guard stays armed; otherwise today's failed state plus the `failure` field).

4. Classify in `load()`'s catch:

```typescript
    } catch (caught) {
      const failure = classifyFailure(caught, { fallback: 'could not load the review queue' })
      setPhase({
        kind: 'failed',
        message: caught instanceof ApiError ? caught.message : 'could not load the review queue',
        heldTask: claimed.current,
        failure,
      })
    }
```

5. Rework `skipHeldTask`'s catch:

```typescript
    try {
      await completeTask(task.id)
    } catch (caught) {
      const failure = classifyFailure(caught, { fallback: 'the request did not reach the API' })
      if (failure.kind === 'gone' || failure.kind === 'taken') {
        // The task is not this reviewer's to release any more -- it was
        // deleted, or an admin moved it. Nothing is held; move on.
        claimed.current = null
        clearStash()
        await load()
        return
      }
      setPhase({
        kind: 'failed',
        message: `could not release this receipt: ${failure.message}`,
        heldTask: task,
        failure,
      })
      return
    }
```

6. Renders. The failed phase gains the backend-down branch and the Skip suppression:

```tsx
  if (phase.kind === 'failed') {
    const held = phase.heldTask
    const backendDown = phase.failure.kind === 'backend-down'
    return (
      <main>
        {backendDown ? (
          <p role="alert">The database is unavailable — nothing can be saved right now.</p>
        ) : null}
        <p role="alert">{phase.message}</p>
        <button type="button" onClick={() => void load()}>
          Try again
        </button>
        {held === null || backendDown ? null : (
          <>
            <button type="button" onClick={() => void skipHeldTask(held)}>
              Skip this receipt
            </button>
            <p>Closes this receipt&rsquo;s review task without reviewing it, and moves on.</p>
          </>
        )}
      </main>
    )
  }
```

The claimed render: the backend-down line joins the failed-submit alert, and `lost` takes the Approve slot's place alongside `held`:

```tsx
      {submit.kind === 'failed' && submit.failure.kind === 'backend-down' ? (
        <p role="alert">The database is unavailable — nothing can be saved right now.</p>
      ) : null}
      {submit.kind === 'failed' ? <p role="alert">{submit.message}</p> : null}
      {submit.kind === 'lost' ? (
        <section role="alert">
          <h2>
            {submit.flavor === 'taken'
              ? 'Saved, but this task was taken over by someone else'
              : 'Saved, but this task no longer exists'}
          </h2>
          <p>{submit.message}</p>
          <button
            type="button"
            onClick={() => {
              claimed.current = null
              clearStash()
              void load()
            }}
          >
            Next receipt
          </button>
        </section>
      ) : submit.kind === 'held' ? (
        <StoredDifferently outcome={submit.outcome} onAcknowledge={() => void load()} />
      ) : (
        <button type="button" onClick={() => void approve()} disabled={busy}>
          Approve (⌘↵)
        </button>
      )}
```

(`openTaskId` hoisting stays; the `Close task` button already renders only when `openTaskId !== null`, which a `lost` state never sets.)

- [ ] **Step 4: Run the file, then everything**

Run: `cd frontend && npx vitest run tests/review-screen.test.tsx && npm test && npm run typecheck && npm run build`
Expected: all green.

- [ ] **Step 5: RED-proof each new guarantee separately (then restore each)**

1. In `submitFailure`, drop the `lost` branch — the 403 and 404 tests fail (Close task reappears). Restore.
2. In `approve`'s catch, always clear `submittedTask.current` — the chord-is-dead assertion fails (a second PATCH appears). Restore.
3. In the failed-phase render, drop `|| backendDown` — the 503-load test fails (Skip offered). Restore.
4. In `skipHeldTask`, drop the `gone`/`taken` branch — the skip-404 test fails (dead-end again). Restore.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/review/ReviewScreen.tsx frontend/tests/review-screen.test.tsx
git commit -m "feat(frontend): terminal taken/gone/backend-down states on both paths"
```

---

### Task 7: Inline field errors

**Files:**
- Modify: `frontend/src/review/MoneyInput.tsx`
- Modify: `frontend/src/review/ReceiptForm.tsx`
- Modify: `frontend/src/review/LineItemsTable.tsx`
- Modify: `frontend/src/review/ReviewScreen.tsx` (threading only)
- Modify: `frontend/tests/receipt-form.test.tsx` (append)
- Modify: `frontend/tests/review-screen.test.tsx` (append one end-to-end case)

**Interfaces:**
- Consumes: `Submit`'s `failed.failure` from Task 6.
- Produces:
  - `MoneyInputProps` gains `readonly error?: string | null`
  - `ReceiptFormProps` and `LineItemsTableProps` gain `readonly errors?: Readonly<Record<string, string>>` (keyed by the same dotted paths as `fields`)

- [ ] **Step 1: Write the failing tests**

Append to `frontend/tests/receipt-form.test.tsx` (follow the file's existing render helpers):

```tsx
describe('inline field errors', () => {
  it('renders the server message beside the matched field, linked by aria-describedby', () => {
    render(
      <ReceiptForm
        fields={FIELDS}
        onChange={() => {}}
        errors={{ 'totals.total': "not a decimal amount: 'abc'" }}
      />,
    )
    const input = screen.getByLabelText('Total') as HTMLInputElement
    const describedBy = input.getAttribute('aria-describedby')
    expect(describedBy).not.toBeNull()
    const description = document.getElementById(describedBy!)
    expect(description?.textContent).toBe("not a decimal amount: 'abc'")
    expect(description?.getAttribute('role')).toBe('alert')
  })

  it('renders no describedby and no alert for untouched fields', () => {
    render(
      <ReceiptForm
        fields={FIELDS}
        onChange={() => {}}
        errors={{ 'totals.total': "not a decimal amount: 'abc'" }}
      />,
    )
    const clean = screen.getByLabelText('Subtotal') as HTMLInputElement
    expect(clean.getAttribute('aria-describedby')).toBeNull()
  })

  it('a text field carries its error the same way', () => {
    render(
      <ReceiptForm
        fields={FIELDS}
        onChange={() => {}}
        errors={{ 'receipt.currency': "currency holds at most 3 characters, got 5 ('EUROS')" }}
      />,
    )
    const input = screen.getByLabelText('Currency') as HTMLInputElement
    const describedBy = input.getAttribute('aria-describedby')
    expect(document.getElementById(describedBy!)?.textContent).toContain('at most 3 characters')
  })
})
```

(`FIELDS` is whatever complete `FieldMap` fixture the file already uses; if it has none, build one with `fieldsFromReceipt` over the file's receipt fixture.)

And one end-to-end case in `frontend/tests/review-screen.test.tsx`:

```tsx
  it('a value-quoting 400 lands beside the field that sent it, and the summary stays', async () => {
    const fetchMock = stubApi({
      '/review/next': [200, { task: TASK, receipt: SUMMARY }],
      'GET /receipts/a1': [200, RECEIPT],
      'PATCH /receipts/a1': [400, { error: { message: "not a decimal amount: 'abc'" } }],
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<StrictMode><ReviewScreen /></StrictMode>)
    const total = await screen.findByLabelText('Total')
    await userEvent.clear(total)
    await userEvent.type(total, 'abc')
    await userEvent.keyboard('{Control>}{Enter}{/Control}')

    // The summary alert (unchanged behaviour) ...
    await screen.findByText("Not saved: not a decimal amount: 'abc'")
    // ... and the inline slot, on the input that sent 'abc'.
    const described = (total as HTMLInputElement).getAttribute('aria-describedby')
    expect(described).not.toBeNull()
    expect(document.getElementById(described!)?.textContent).toBe("not a decimal amount: 'abc'")
  })
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run tests/receipt-form.test.tsx tests/review-screen.test.tsx`
Expected: the new tests FAIL (unknown `errors` prop / no describedby); pre-existing tests PASS.

- [ ] **Step 3: Implement**

`MoneyInput.tsx` — the error joins the label it already owns:

```tsx
export interface MoneyInputProps {
  readonly label: string
  readonly value: string | null
  readonly onChange: (next: string | null) => void
  /** The server's words for this field, verbatim, when the last submit was
   *  refused because of it. Rendering is additive: the summary alert at the
   *  bottom of the screen still carries the same message. */
  readonly error?: string | null
}

export function MoneyInput({ label, value, onChange, error }: MoneyInputProps) {
  const id = useId()
  const errorId = useId()
  const active = error != null
  return (
    <label htmlFor={id}>
      {label}
      <input
        id={id}
        type="text"
        inputMode="decimal"
        value={value ?? ''}
        aria-describedby={active ? errorId : undefined}
        onChange={(e) => onChange(e.target.value === '' ? null : e.target.value)}
      />
      {active ? (
        <p role="alert" id={errorId}>
          {error}
        </p>
      ) : null}
    </label>
  )
}
```

`ReceiptForm.tsx` — extract the text control so it can own ids (`useId` cannot be called in a `.map` callback), thread `errors`:

```tsx
export interface ReceiptFormProps {
  readonly fields: FieldMap
  readonly onChange: (path: string, value: string | null) => void
  /** Server messages keyed by the same dotted paths as `fields`. */
  readonly errors?: Readonly<Record<string, string>>
}

/** One free-text control, owning its ids. Extracted because `useId` is a
 *  hook and the fields render from a `.map`. */
function TextField({
  label,
  value,
  error,
  onChange,
}: {
  readonly label: string
  readonly value: string | null
  readonly error: string | undefined
  readonly onChange: (value: string | null) => void
}) {
  const errorId = useId()
  return (
    <label>
      {label}
      <input
        type="text"
        value={value ?? ''}
        aria-describedby={error !== undefined ? errorId : undefined}
        onChange={(e) => onChange(e.target.value === '' ? null : e.target.value)}
      />
      {error !== undefined ? (
        <p role="alert" id={errorId}>
          {error}
        </p>
      ) : null}
    </label>
  )
}
```

with the two maps becoming:

```tsx
      {TEXT_FIELDS.map(([path, label]) => (
        <TextField
          key={path}
          label={label}
          value={fields[path]}
          error={errors?.[path]}
          onChange={(value) => onChange(path, value)}
        />
      ))}

      {MONEY_FIELDS.map(([path, label]) => (
        <MoneyInput
          key={path}
          label={label}
          value={fields[path]}
          error={errors?.[path]}
          onChange={(value) => onChange(path, value)}
        />
      ))}
```

(`import { useId } from 'react'` joins the imports. The select and the two checkboxes get no slot: `meta.legibility` is a closed `<select>` and the booleans are checkboxes — their coercers are unreachable from these controls, measured in the design's §1.3/§10. Say exactly that in a one-line comment.)

`LineItemsTable.tsx` — same shape: add `errors?: Readonly<Record<string, string>>` to the props, pass `error={errors?.[`${at}.qty`]}` (and `unit_price`, `line_total`) into the three `MoneyInput`s, and extract the same `TextField`-style wrapper for the three plain inputs (description/sku/unit) with their `aria-label`s preserved. Line-item text paths cannot produce a 400 today (`_coerce_text`/`_coerce_optional_text` never raise) but the slot is uniform — a matcher hit on any path must have somewhere to land.

`ReviewScreen.tsx` — threading only:

```tsx
  const fieldErrors =
    submit.kind === 'failed' && submit.failure.kind === 'field'
      ? { [submit.failure.path]: submit.failure.message }
      : undefined
```

and pass `errors={fieldErrors}` to both `<ReceiptForm …>` and `<LineItemsTable …>`.

- [ ] **Step 4: Run the two files, then everything**

Run: `cd frontend && npx vitest run tests/receipt-form.test.tsx tests/review-screen.test.tsx && npm test && npm run typecheck && npm run build`
Expected: all green.

- [ ] **Step 5: RED-proof (then restore)**

1. In `ReviewScreen`, pass `errors={undefined}` unconditionally — the end-to-end inline test fails while the summary-alert half still passes. Restore.
2. In `MoneyInput`, drop the `aria-describedby` attribute — the linkage assertions fail. Restore.

- [ ] **Step 6: Full gates**

Run from the repo root: `python scripts/verify.py`
Expected: all five gates PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/review/MoneyInput.tsx frontend/src/review/ReceiptForm.tsx frontend/src/review/LineItemsTable.tsx frontend/src/review/ReviewScreen.tsx frontend/tests/receipt-form.test.tsx frontend/tests/review-screen.test.tsx
git commit -m "feat(frontend): the server's field refusal lands beside the field that sent it"
```

---

## Plan self-review (run by the author, recorded here)

- **Spec coverage:** §3 classifier → Task 2; §4.1 stash → Tasks 3+5; §4.2 logout → Task 4; §5 inline → Task 7; §6.1 submit terminals → Task 6; §6.2 load/skip terminals → Task 6; §8 Python pins → Task 1; §8 typecheck-with-suite → every task's run steps. The §1.2 route-level 400-not-422 pin → Task 1. No spec row is unowned.
- **Placeholders:** none — every step carries its code or its exact command.
- **Type consistency:** `Failure` (Task 2) is consumed by name in Task 6's unions and Task 7's threading; `remember/restore/clear/hasDirtyEdits` (Task 3) match Tasks 4/5/6's imports; `error?: string | null` on `MoneyInput` matches `errors?.[path]`'s `string | undefined` because `?.` on a `Record<string, string>` yields `string | undefined` and the prop accepts `undefined` via optionality — the `error != null` guard in `MoneyInput` covers both.
- **Known risk, stated:** Task 5's mutation 3 may not discriminate; the step says what to do when it does not, and the fallback assertion to add. Task 1's texts were measured by executing the coercers this session; the route adds nothing (`str(exc)` passthrough read at api.py:128-151), and any mismatch is a stop-and-report, never an expectation edit.
