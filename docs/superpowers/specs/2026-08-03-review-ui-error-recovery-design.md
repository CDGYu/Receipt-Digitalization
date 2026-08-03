# Review-UI error recovery: the five §5 rows that never shipped

The Phase 5 whole-branch review found that five rows of the review-ui design's
error-handling table (docs/superpowers/specs/2026-07-29-review-ui-design.md,
§5) silently did not ship — the plan dropped the table wholesale, so no task
owned any of them (the eleventh plan defect of that milestone). This design
implements those five rows against the code as it exists now, which has moved
since the table was written: ADR-0016 made `GET /review/next` resume the
caller's own task, and the "Skip this receipt" escape already reinterprets one
row (`ReviewScreen.tsx:213-237`) against that reality.

The sixth row of the table — expired image signature → one silent re-sign,
then a failed-image state — **did ship**, in `ImagePane.tsx` (its docstring
enumerates the three failure paths and the one-retry budget). This milestone
is exactly the remaining five:

| §5 row | Today | This design |
|---|---|---|
| 401 mid-review → login, return to the receipt | Login swap happens (`session.ts:47`); the receipt returns via ADR-0016's resume; the reviewer's unsubmitted edits are lost with the unmount | §4: edits preserved in memory |
| 400 → inline against the field; dirty state preserved | Dirty state survives; the message is one summary alert, never adjacent to the field | §3 + §5: classifier + inline rendering |
| 403 on `complete` → surface, re-fetch next | "Saved, but the task is still open" + a `Close task` retry that would 403 forever | §6: terminal `taken` state |
| 404 receipt or task gone → surface, re-fetch next | Load-path receipt-404 has the Skip exit; a task-404 from `complete` (or from Skip's own `completeTask`) dead-ends | §6: terminal `gone` state |
| 503 → distinct backend-down state | The 503 message is quoted but rendered identically to every other failure, and Skip is still offered while the DB is down | §6: distinct state, Skip suppressed |

## 1. Context, measured

### 1.1 What the API can actually send this client

`_install_error_handlers` (src/receipts/review/api.py:128-151) maps
`ValueError → 400`, `DBAPIError → 503 "database unavailable"`, and
`StarletteHTTPException →` its own status, all in the one
`{"error": {"message": ...}}` envelope. The statuses this design
discriminates on, read from the routes this session:

- `POST /review/{task_id}/complete` → **404** `no review task with id {id}`
  when the task row is gone, **403** `only the assignee or an admin may
  complete this task` otherwise-unauthorized (api.py:536-544). The 403's
  realistic producer is the queued admin-release follow-up (today no code
  path reassigns a claim); designing for it now is what makes that follow-up
  additive.
- `POST /auth/logout` → **204**, `request.session.clear()`
  (src/receipts/review/auth.py:180-183). The client's `request` already
  resolves the empty body to `undefined` (client.ts `parseSuccess`).
- `PATCH /receipts/{id}` failures are the `ValueError` boundary
  (ADR-0006): `apply_corrections` raises, the handler wraps to 400.

### 1.2 A field-level 422 is unreachable from this client's own patches

The UI sends the patch **flat** (`patch.ts` `FieldMap`, dotted keys), and
flat top-level keys bypass `CorrectionPatch`'s typed sub-models — measured in
api/review.ts:120-128 (`model_validate` on dotted keys returns them
untouched, `extra="allow"` at every level, review/schemas.py:149) — and
every value the UI can produce is `string | null`. Even a float smuggled
under a dotted key is caught by `_coerce_money` as a **400**, not a 422
(schemas.py:121-127 records exactly this division of labour). What remains
of 422 (malformed JSON, a non-object body) carries no usable field
identity. Consequence: **inline field errors are built on the 400 text, and
the 422-`loc` mapper is rejected scope** — its fixtures could only be
shapes the real route cannot emit, which review standard 1 exists to
forbid. This closes, by recorded decision, the Task-2 parked minor
"surfacing `loc` is one line and is Task 4's call": it is nobody's call to
make for a shape the client cannot receive. `messageFrom`'s existing 422
text handling stays as the degradation path, and its "loc is deliberately
not surfaced" comment is updated to carry this measurement instead of the
old rationale.

The plan must pin the load-bearing half of this at route level (a dotted-key
patch with a bad value → 400, never 422) so the classifier's 400
orientation rests on an executed test, not on this paragraph.

### 1.3 The 400 texts, and which of them name the field

Measured verbatim (recorded in ReviewScreen.tsx:133-148 from execution
against the real route):

- `cannot apply a correction to unknown field path 'totals.grand_total'` —
  **quotes the path**;
- `cannot apply a correction to 'line_items[9].qty': receipt <id> has no
  line item at position 9` — **quotes the path**;
- `not a decimal amount: 'abc'` · `not a boolean: 'maybe'` ·
  `not an ISO 8601 date (YYYY-MM-DD): …` · `not an ISO 8601 time (HH:MM):
  '2.30pm'` — **quote only the offending value**.

The coercion class — the one a reviewer actually triggers by typing — does
not name the path. Any inline mechanism must therefore match on both: the
quoted path when present, else the quoted value against what was just sent.
The patch is all-or-nothing (§5 of the review-ui design: every path is
resolved and coerced before anything mutates), so one attempt surfaces one
failure; serial discovery for multiple typos is the honest behaviour and is
documented, not disguised.

Not yet measured: the bounded-text overflow wording
(`_bounded_optional_text`, ADR-0006/0007) as it leaves the route. The plan
measures it before the matcher is written and pins it with the rest.

## 2. Decisions already made (this session, plus standing rulings honored)

1. **Approach: one client-side classifier** (user ruling today). The
   backend stays untouched, honoring the Task-2 ruling that kept the
   RequestValidationError-handler alternative out of a frontend milestone.
   That alternative stays raisable later as its own API-contract milestone;
   nothing here is wasted by it (the classifier would lose one fallback
   branch, not its structure).
2. **401 mid-review preserves the reviewer's edits in memory** (user ruling
   today). Not sessionStorage — no receipt-adjacent text enters browser
   storage; a full page reload starts clean, exactly as it does today.
3. The five rows are one milestone; `src/` (Python) gains no behavioural
   change, only test pins.

## 3. The failure classifier

New pure module `frontend/src/review/failure.ts`:

    classifyFailure(caught: unknown, sentPatch?: FieldMap) →
      | { kind: 'backend-down'; message: string }   // ApiError, status 503
      | { kind: 'taken';        message: string }   // ApiError, status 403
      | { kind: 'gone';         message: string }   // ApiError, status 404
      | { kind: 'field'; path: string; message: string }
      | { kind: 'other';        message: string }   // incl. non-ApiError

`field` fires only for a 400 with `sentPatch` provided, by two rules in
order:

1. **Path quote**: the message contains `'<path>'` for exactly one key of
   `sentPatch`.
2. **Value quote**: the message's final `'…'`-quoted span equals the sent
   value of exactly **one** entry of `sentPatch`.

Ambiguity (two dirty fields holding the same rejected value, an unquoted
`None`, a message shape the inventory does not know) degrades to `other` —
which renders exactly what ships today, so the matcher can only add
precision, never subtract it. 401 is deliberately absent from the union:
`client.ts` owns it at the transport (`onUnauthorized`), before any screen
logic runs.

The classifier is pure and takes no dependency on React; its message-shape
assumptions are pinned twice — Vitest on the matcher itself, and the Python
route-level pins of §1.2/§1.3.

## 4. Logout, and the 401 stash

### 4.1 The stash

New module `frontend/src/review/stash.ts`, holding at most one entry:

    remember(taskId: string, overlay: FieldMap): void   // overlay = buildPatch(original, fields)
    restore(taskId: string): FieldMap | null            // non-consuming
    clear(): void

- `ReviewScreen.edit()` calls `remember` with the current dirty diff on
  every change (`buildPatch` is already the dirty-diff primitive,
  patch.ts:136-144; the stash stores only changed entries, never the whole
  form).
- `load()` consults `restore` after the fetches succeed: when ADR-0016
  hands back the same task id, fields become
  `{ ...freshOriginal, ...overlay }`. Restore is **non-consuming**: a
  second 401 before any new edit must not lose what the first one kept.
- **The stash's lifecycle mirrors `claimed.current`'s** (whose clear points
  ReviewScreen.tsx:76-83 documents): cleared wherever the claim is nulled
  after a successful close — approve success (both the clean and the held
  outcome: the write landed), `skipHeldTask` success, `closeTaskOnly`
  success — plus on logout (§4.2) and when the terminal `taken`/`gone`
  states advance (§6).

A property that falls out and gets a test rather than a comment: after a
`complete`-step 401 (PATCH landed, close did not — `require_user` rejects
before the route body, so a *patch*-step 401 wrote nothing), the re-login
fetch returns a receipt whose values already include the applied edits, so
the restored overlay overlays equal values and `buildPatch` goes back to
empty — no false dirty state, no spurious re-corrections.

The §5 row's "redirect to `/app/login`" remains the state swap it is today
(`setSignedIn(false)` → `LoginPage` renders); the URL does not move, and
the deferred router/history minor stays deferred.

### 4.2 The logout control

`App` (main.tsx) gains a header rendered only when signed in, holding the
one new control: **Sign out**.

- Click → `POST /auth/logout`. Success (204) → `stash.clear()`,
  `setSignedIn(false)`.
- A **401** from the logout call means the session was already dead: the
  transport handler flips the signed-in state, and the stash is cleared
  the same way — **the stash is cleared exactly when the session actually
  ends** (204 or 401), so a confirmed discard is honored on both endings
  rather than resurfacing at the next sign-in via ADR-0016's resume.
- **Any other failure → stay signed in, and say so** (inline
  `role="alert"` by the control), stash untouched — the discard did not
  happen, the edits are still live on screen, and the stash keeps
  tracking them. The session cookie is server state; a client that
  pretends to be signed out while the cookie lives has manufactured the
  exact looks-done-but-is-not state this project bans.
- **Dirty edits gate it**: when the stash holds a non-empty overlay, the
  control takes a two-step inline confirm ("Discard unsaved edits and sign
  out?" with an explicit cancel) — not `window.confirm`. Sign-out is a
  deliberate departure, so confirming clears the stash.
- A held claimed task is left untouched by logout — ADR-0016 returns it at
  the next sign-in, which is that ADR working as designed; the header does
  not pretend otherwise.

## 5. Inline field errors

`ReceiptForm` and `LineItemsTable` gain an optional
`errors: Readonly<Record<string, string>>` prop keyed by the same dotted
paths as `fields`. A `field` classification from a failed PATCH renders its
message adjacent to the matched input (`role="alert"`, associated via
`aria-describedby`); everything else about the failed-submit state is
unchanged — the summary alert stays in **all** cases (inline is additive),
dirty state stays on screen, and the retry path is untouched.

No client-side pre-validation duplicating `_coerce_*` rules: the server's
words stay the only authority, for the same reason schemas.py refuses to
re-declare the receipt shape — a second copy of the rules is a place for
the two to drift apart silently.

## 6. Terminal states — 403/404/503 on both paths

### 6.1 The submit path

`submitFailure` classifies before shaping state:

- **`taken` (403 on `complete`)** and **`gone` (404 on `complete`)**: the
  PATCH landed; the task is no longer this reviewer's to close. The state
  says what survived — "Saved, but this task was taken over by someone
  else" / "…no longer exists" — and offers exactly one exit, **Next
  receipt**, which clears the claim and the stash and calls `load()`.
  **No auto-advance** (the same measured muscle-memory rationale as
  `StoredDifferently`, ReviewScreen.tsx:399-410: information the reviewer
  is about to move past must not be dismissible by reflex), **no `Close
  task` retry** (it would fail identically forever), and the ⌘↵ chord is
  dead here: `submittedTask` stays set in these branches, so `approve()`'s
  existing guard refuses. The `openTaskId` retry machinery is reserved for
  retryable failures.
- **`backend-down` (503, either step)**: a distinct state — "The database
  is unavailable; nothing can be saved right now" — with the existing
  narrow retries kept: `Try again` re-runs the chain for a patch-step
  failure, `Close task` re-runs only the close for a complete-step failure.
- **`field` / `other` (patch step)**: today's failed-submit state, plus §5's
  inline rendering when matched.

> **Dated note (2026-08-03, implementation ruling):** §6's "distinct
> state" was planned as a second `role="alert"` paragraph beside the
> existing message alert. Measured during implementation: a second alert
> makes every single-alert query in the pre-existing suite ambiguous (six
> tests break), colliding with this milestone's pre-existing-tests-pass
> constraint. **User ruling: the distinct backend-down sentence renders
> without the alert role and is pinned by text; the always-present message
> alert continues to announce.** The ledger carries the ruling of record.

> **Dated note (2026-08-03, implementation narrowing):** the `backend-down`
> bullet above says a 503 gets a distinct state on *either* step. The
> shipped code narrows that to the **patch** step: `ReviewScreen.tsx` gates
> the distinct sentence on `openTaskId === null`, so a 503 on the **close**
> renders the message alert alone. The sentence is simply false there —
> `apply_corrections` commits in its own transaction, so the write landed
> before `complete` was ever called. Unsuppressed, the screen rendered "The
> database is unavailable — nothing can be saved right now." directly above
> "Saved, but the task is still open: database unavailable": two
> contradictory claims about one receipt, with nothing on screen to tell a
> reviewer which is true. What the bullet promises for that step is
> otherwise kept — the narrow `Close task` retry is still offered, because a
> 503 is transient and closing the task is all that is left to do. Commit
> `717c1c8`, covered by the test `a 503 on the close does not also claim
> nothing could be saved`.

> **Dated correction (2026-08-03, same day, the fix wave's):** the ruling
> note above says "six tests break". Re-measured at the milestone head, by
> restoring `role="alert"` at the failed-phase render site: it is **four**.
> The count was right when it was taken and the suite has changed since,
> which is exactly why the code comment that carried it now states the
> mechanism rather than a number (the house rule at
> `frontend/src/api/review.ts:80-86`). The ruling itself is unchanged, and
> no longer rests on a count: both 503 tests now assert that the sentence
> carries no `role` at all. Recorded by dated note rather than by rewriting
> the note above, per the convention this project uses for ADRs.

### 6.2 The load path

`load()`'s and `skipHeldTask()`'s catches classify too:

- **`backend-down`**: the distinct message, `Try again` kept, and **"Skip
  this receipt" suppressed** — Skip's own `completeTask` needs the same
  database, so while the DB is down the button is a false exit that would
  also spend a task the moment the DB recovered mid-click.
- **Skip's `completeTask` answering `gone`/`taken`** (task 404, or 403
  because an admin moved it): the task is not this reviewer's to release —
  treat it as already released: clear the claim and the stash, `load()`.
  This converts today's dead-end (`skipHeldTask`'s catch keeps `heldTask`
  unconditionally, ReviewScreen.tsx:244-254) into the row's "surface,
  re-fetch next".
- A receipt-404 with a live task keeps today's Skip exit unchanged — that
  path already implements its row (its docstring records the ADR-0016
  reinterpretation).

## 7. What must not change

- **`src/` Python behaviour: untouched.** New Python tests only (§8).
- ADR-0015 holds: money stays a string end to end, no
  `<input type="number">`/`valueAsNumber` (the guard test is measured
  sound — trust its verdicts, not its prose), no `CORSMiddleware`, SPA
  under `/app/*` only, and **no client-side path gains a dotted final
  segment** (the header and confirm UI add no routes at all).
- ADR-0016 semantics are load-bearing for §4 and are not altered.
- `patch.ts` is deliberately not edited (`buildPatch` is imported as-is);
  its parked count-rot comment (patch.ts:188) waits for a legitimate edit
  of that file. If the plan finds an edit unavoidable, the parked bundle
  rides along per the standing rule.
- The Python message pins go in the API-write test module, **not**
  `tests/test_repository.py`, whose own parked bundle should not be
  triggered by this milestone.
- **ADR-0022 is not extended — but not for the reason first written here**
  (corrected 2026-08-03, the fix wave's). This bullet used to say the
  inline slots "display the same already-redacted API text". That is
  false. `_install_error_handlers` answers a `ValueError` with `str(exc)`
  verbatim, and the coercers interpolate the reviewer's own value with
  `!r`; nothing between the two redacts. Measured (2026-08-03):
  `_coerce_date('4111 1111 1111 1111')` raises `not an ISO 8601 date
  (YYYY-MM-DD): '4111 1111 1111 1111'`, and that is what reaches the 400
  body. The exemption nevertheless stands, for a different reason:
  ADR-0022 redacts at **process egresses**, and its inventory is
  `_persist_failure`'s carrier, the failure log, the engine's statement
  parameters, and the CLI's uncontained print. The browser DOM is none of
  those — the text is the viewer's own keystrokes returning to the viewer
  who typed them, on the screen they typed them on. §5 moves that text
  from the summary alert to a slot beside the input; it changes neither
  where the text goes nor who can see it. So: **no new persistence, no new
  process egress, and no `redact_pan` claim about this path.**
- The submit chain stays strictly sequential; `fetchNext` remains a
  claiming write called at most once per task in hand; nothing here adds a
  call site.

## 8. Tests

All Vitest except the route-level pins:

- **Classifier** (pure): every kind; path-quote match; value-quote match
  unique vs ambiguous (two dirty fields sharing the rejected value →
  `other`); unquoted `None` → `other`; non-ApiError → `other`.
- **Stash**: remember/restore round-trip keyed by task id; non-consuming
  restore; every clear point (approve clean, approve held→acknowledge,
  skip success, close-task success, logout, taken/gone advance); the
  complete-step-401 no-false-dirty property of §4.1.
- **Logout**: 204 → signed out + stash cleared; 401 → signed out + stash
  cleared (the session-already-dead ending); any other failure → still
  signed in with the message on screen and the stash intact; dirty
  overlay → confirm gate with a working cancel.
- **Screen flows**: 403-complete and 404-complete render the terminal
  state, offer only Next receipt, keep ⌘↵ dead, and advance clears
  claim+stash; 503 on submit renders backend-down with the narrow retry;
  503 on load renders backend-down **without** Skip; skip's 404/403 clears
  and re-fetches; the 401→re-login flow restores edits onto the resumed
  task (mocked transport, both the patch-step and complete-step variants).
- **Inline rendering**: matched path renders adjacent (`aria-describedby`
  linkage asserted), summary alert still present; unmatched degrades to
  summary-only.
- **Python route pins** (API-write test module): the §1.3 message
  inventory including the measured bounded-text wording; dotted-key patch
  with a bad value → 400 never 422; `POST /auth/logout` → 204 empty body.

Discipline: every new test proven RED with its guarantee reverted (review
standard 2); absence-of-breakage guarantees reverted separately (standard
3); no prose claim of measurement without the run recorded (standard 13).
`npm run typecheck` runs with the suite — Vitest alone does not type-check.

## 9. Verification

`python scripts/verify.py` all five gates, both suites, on every task
commit and at the close; the Vitest count and the Python count both grow
and the exact totals belong to the reports, not to this document.

## 10. Open facts the plan must settle before briefing (probe, don't assume)

1. The bounded-text 400 wording as it exits the route (§1.3).
2. `ReceiptForm`/`LineItemsTable` internals: how each of the seventeen
   paths renders today (in particular whether `meta.is_handwritten` is
   free-text or constrained — it decides whether `not a boolean` is
   reachable), and where the error slot sits in each.
3. The exact name of the API-write test module the pins join.
4. Whether `App`'s header placement collides with any existing layout test.
