# ADR 0024 — The review UI's error-recovery contract

**Status:** Accepted (2026-08-03; merged 2026-08-04)
**Builds on:** ADR-0015 (the review UI is served same-origin under `/app`,
money is a string), ADR-0016 (`GET /review/next` resumes the caller's own
task), ADR-0006 (the `ValueError` boundary), ADR-0012 (the error envelope).
**Supersedes, in part:** the error-handling table in
`docs/superpowers/specs/2026-07-29-review-ui-design.md` §5, whose five rows
this record replaces with what actually shipped.

## Context

Phase 5's whole-branch review found that five rows of the review UI's design
§5 error table had silently not shipped: no logout control, no
return-to-receipt after a 401, no inline field errors, no distinct 503 state,
and no re-fetch after a 403/404. The plan had dropped the table wholesale, so
no task owned any of them — the eleventh plan defect of that milestone.

They shipped in the review-UI error-recovery milestone
(`docs/superpowers/specs/2026-08-03-review-ui-error-recovery-design.md`,
merged `7c811fa` → `02edcd0`). This ADR records the contract, because the
next person to touch these files will otherwise re-derive it from the code
and get three things wrong — each of which is a user ruling, not a
preference.

Two facts about the server bound everything below, both measured against the
real routes and pinned in `tests/test_api_write.py`:

* **A field-level 422 is unreachable from this client.** The UI sends a flat,
  dotted patch, which bypasses `CorrectionPatch`'s typed sub-models
  (`extra="allow"`), and every value it can produce is `string | null`. Even
  a float smuggled under a dotted key comes back as the enveloped **400**.
  So inline errors are built on 400 text, and mapping 422 `loc` is rejected
  scope — its fixtures could only be shapes the route cannot emit.
* **The 400 boundary is one-error-at-a-time, and the blamed field is chosen
  by sort order.** `apply_corrections` iterates `sorted(flatten(patch).items())`
  and raises on the first failure — measured, a patch with a bad
  `totals.total` and a bad `receipt.currency` reports the *currency*, because
  it sorts first. The UI therefore cannot show every invalid field at once,
  and the field it blames is not necessarily the one the reviewer cares about.
  Serial discovery across retries is the honest behaviour and is documented
  as such at the threading site.

## Decision

### 1. One classifier labels every caught failure

`frontend/src/review/failure.ts` is pure, React-free, and the single place
status semantics live:

    classifyFailure(caught, { sentPatch?, fallback }) →
      { kind: 'backend-down' | 'taken' | 'gone' | 'other', message }
      | { kind: 'field', path, message }

`503 → backend-down`, `403 → taken`, `404 → gone`. **401 is deliberately
absent**: `client.ts` owns it at the transport (`onUnauthorized` fires before
the throw), so no screen branches on it.

`field` fires only for a 400 with `sentPatch`, by two rules in order:
**quoted path** (the message quotes exactly one key of the patch), then
**quoted value** (the message's quoted span equals the sent value of exactly
one entry). Any ambiguity degrades to `other`, which renders exactly what
shipped before the milestone — so the matcher can only add precision, never
subtract it. `matchField` can only ever return a key of `sentPatch`, so a
`field` failure always carries a path the form can index.

**The classifier never invents copy.** Every `ApiError` kind carries the
server's message verbatim; `fallback` is the caller's sentence for a failure
that carries no server words.

### 2. The stash is memory only, and clears where the write landed

`frontend/src/review/stash.ts` holds at most one entry — the dirty diff
(`buildPatch(original, fields)`), never the whole form — keyed by task id.
`restore` is non-consuming and returns a copy; `remember` replaces rather
than merges.

**User ruling: nothing enters browser storage.** Not `sessionStorage`, not
`localStorage`. A 401 unmounts the screen, re-login brings the same task back
via ADR-0016's resume, and the overlay is re-applied as
`{ ...freshOriginal, ...overlay }`. A full page reload starts clean, exactly
as it did before the stash existed. The trade is deliberate: no
receipt-adjacent text is written to disk by the browser.

The stash is cleared **exactly where a write landed or the session ended** —
approve success (clean and held), skip success, close-task success, entering
either terminal state, the terminal advance, and a logout that really ended
the session (204 or 401). It is *not* cleared on a retryable failure, because
those edits can still be resubmitted. The mirroring effect declines to stash
at all while the chain is armed, so a closed task cannot re-accumulate edits
that could never be restored.

### 3. Terminal states end in one exit, never a retry that cannot work

A 403 or 404 on `complete` means the PATCH landed and the task is no longer
the reviewer's to close. That renders a terminal state saying what survived,
offering exactly one exit (**Next receipt**), with no `Close task` retry — it
would fail identically forever — and with the ⌘↵ chord dead, because the
submit guard stays armed.

**This supersedes the previous contract** (a message plus a `Close task`
retry). Three pre-existing tests pinned the old behaviour and were rewritten
to pin the new one, each renamed to say what it now pins. That was a user
ruling: the approved design governs, and the superseded tests are updated
rather than the design narrowed.

Skip's own `completeTask` answering 403/404 is treated as *already released*:
clear the claim and the stash and move on, rather than the dead end it was.

### 4. Backend-down is distinct, and suppresses what it must

A 503 renders a distinct sentence and suppresses the Skip escape on the load
path — Skip's own call needs the same database, so offering it is a false
exit. On the **complete** step the distinct sentence is suppressed instead
(gated on `openTaskId === null`), because "nothing can be saved right now" is
false once `apply_corrections` has committed; the narrow `Close task` retry
stays, since a 503 is transient.

**User ruling: that sentence carries no `role="alert"`.** A second alert in
the same region makes the suite's single-alert queries ambiguous and breaks
pre-existing tests; the server's own words beside it still announce. The cost
is recorded rather than hidden: a screen-reader user hears the raw message,
not the plain-language explanation.

### 5. Inline errors are additive, and live outside the `<label>`

A `field` failure renders the server's message beside the input that sent it,
linked by `aria-describedby` and carrying `role="alert"`. **The summary alert
still renders in every failure case** — inline never replaces it.

The error element is a **sibling of the `<label>`, never a child**. Nesting
it inside pollutes the field's accessible name: name-from-content walks the
label's subtree, so the refusal would become part of the field's *name* and
the field would lose its short one. `aria-describedby` is an IDREF and needs
no containment. Every id comes from `useId`; none is derived from a path or a
row index.

No client-side re-implementation of the server's coercion rules: the server's
words are the only authority, for the same reason `schemas.py` refuses to
re-declare the receipt shape.

## Consequences

* The backend is untouched by all of this. `src/` gained no behavioural
  change in the milestone — only route-level test pins of the exact message
  texts the classifier matches on. **Those pins are the contract**: reword a
  coercer and the pin fails, which is the intended coupling.
* The alternative — adding a `RequestValidationError` handler so ADR-0012's
  envelope is truly universal — remains raisable as its own API-contract
  milestone. Nothing here is wasted by it; the classifier would lose one
  fallback branch, not its structure.
* Inline attribution is **best-effort by construction**. A value whose Python
  repr uses double quotes yields no usable span and degrades to
  summary-only. That is a degrade, never a wrong blame.
* The admin release for a claimed task (`IN_PROGRESS` → `OPEN`) now has a
  consumer: the terminal `taken` state was designed for exactly the 403 it
  will produce. Until it ships, that path is reachable only in tests.
* Nothing in this milestone was ever viewed in a browser. The error surfaces
  are unstyled `<p>` elements; the gates prove they render and build, not
  that they read well.
