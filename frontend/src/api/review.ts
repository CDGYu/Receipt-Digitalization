import { ApiError, request } from './client'
import type { ReceiptDetail, ReviewNextResponse } from './types'
import { fieldsFromReceipt, findRewrites } from '../review/patch'
import type { FieldMap, Rewrite } from '../review/patch'

/** Claim the next review task for the signed-in reviewer.
 *
 * `{"task": null}` on an empty queue is **200 with a body**, not 204
 * (see `GET /review/next` in review/api.py), so there is one shape to parse and no empty-body
 * special case -- see `ReviewNextResponse` for what each of its two nulls means.
 *
 * Not idempotent: `next_task` assigns the task to the caller and commits
 * (review/api.py:497-506). Calling this twice claims two tasks.
 */
export function fetchNext(): Promise<ReviewNextResponse> {
  return request('/review/next')
}

/** The full receipt: `totals`, `line_items`, `findings`, and the confidence
 *  breakdown that `receipt_summary` leaves out.
 *
 *  `id` is encoded even though every id this app holds came from the API as a
 *  UUID: the parameter's type is `string`, and every receipt route in
 *  `review/api.py` declares `receipt_id: uuid.UUID`, so anything that is not one
 *  is a 422 rather than a path this function helped build.
 */
export function fetchReceipt(id: string): Promise<ReceiptDetail> {
  return request(`/receipts/${encodeURIComponent(id)}`)
}

/** A freshly signed, expiring link to the receipt image.
 *
 * Two separate URLs are involved and only the first one belongs here.
 * `GET /receipts/{id}/image` returns the JSON envelope `{"url": "..."}` whose
 * value is a **relative** link to `GET /receipts/{id}/image/blob`
 * (review/api.py:427-429). The blob is bytes, and `request` always parses its
 * body as JSON, so the blob must never go through it -- it belongs in an
 * `<img src>`. That link is root-relative, so it resolves against the origin
 * and is unaffected by the SPA's `/app/` base.
 *
 * The link is signed for `image_url_ttl_s` (config/settings.py:131, default
 * 300s), which is why `ImagePane` can need a second call to this function for
 * the same receipt.
 *
 * The `undefined` in the response type is not defensive noise: `request`
 * resolves an empty body to `undefined` rather than throwing, so without this
 * check a body-less 200 would surface as `TypeError: Cannot read properties of
 * undefined` instead of a message a caller can put on screen.
 */
export async function fetchImageUrl(id: string): Promise<string> {
  const body = await request<{ url: string } | undefined>(
    `/receipts/${encodeURIComponent(id)}/image`,
  )
  if (body === undefined || typeof body.url !== 'string') {
    throw new ApiError(200, `no image link in the reply for receipt ${id}`)
  }
  return body.url
}

/** Which half of `PATCH` -> `complete` failed. */
export type SubmitStep = 'patch' | 'complete'

/** A failed submission, tagged with the step that failed.
 *
 * The distinction is the whole point: a failed patch wrote nothing and can be
 * retried as-is, while a failed complete means `apply_corrections` already
 * committed -- it sets `receipt.status = REVIEWED` and commits inside its own
 * transaction (persist/repository.py:1060-1061) -- with the queue task still
 * open. The screen must not advance on the second, and must say what survived.
 *
 * `step` and `cause` are declared as fields and assigned in the body rather than
 * written as constructor parameter properties, for the same reason `ApiError`
 * is: `tsconfig.app.json` sets `erasableSyntaxOnly: true`, under which the
 * parameter-property form is
 * `error TS1294: This syntax is not allowed when 'erasableSyntaxOnly' is
 * enabled` -- two distinct diagnostics, one per property, printed four times
 * because `tsc -b` compiles this file under both `tsconfig.app.json` and
 * `tsconfig.test.json`.
 *
 * No line:column here, and no test counts either. Both point at moving targets:
 * the positions are in this very file, so editing this comment shifts them, and
 * a suite total goes stale the next time anyone adds a test -- as the count that
 * used to be here did, one commit after it was written. Measured drift for the
 * positions alone, across successive edits of this block: `(61,5)` -> `(81,5)`
 * -> `(94,5)`, and again when this very sentence was added. The task report
 * carries the current pair, dated.
 *
 * **Vitest does not catch this at all.** Measured by rewriting only this class
 * in the parameter-property form and changing nothing else:
 *
 *     $ npx vitest run tests/submit-chain.test.ts   -> exit 0, every test green
 *     $ npx vitest run                              -> exit 0, every test green
 *     $ npm run typecheck                           -> exit 2, TS1294
 *     $ npm run build                               -> exit 2, TS1294
 *
 * Not "most tests pass" and not one failure in ten -- the entire suite, every
 * file, is green while the build is broken, because esbuild strips the syntax
 * happily and `npm test` never type-checks. Nothing in the runner can tell you
 * about this class of defect. `npm run typecheck` and `npm run build` both can,
 * and they are the only two that can.
 */
export class SubmitError extends Error {
  readonly step: SubmitStep
  readonly cause: unknown

  constructor(step: SubmitStep, cause: unknown) {
    super(`review submit failed at ${step}`)
    this.step = step
    this.cause = cause
    this.name = 'SubmitError'
  }
}

/** Apply a reviewer's edits. **The reply is the new state.**
 *
 * The route returns `receipt_detail(receipt, findings)` for the row it just
 * committed (review/api.py:392-398), so a follow-up `GET /receipts/{id}` would
 * be a second round trip for data already in hand.
 *
 * `patch` is sent flat. Measured: `CorrectionPatch.model_validate({'totals.total':
 * '1000.00', 'receipt.time': None, 'line_items[0].qty': '9.9'})
 * .model_dump(exclude_unset=True, mode='json')` returns those three keys
 * unchanged, so a dotted top-level key bypasses the typed sub-models and reaches
 * `apply_corrections` as written. What that buys is the error currency: also
 * measured, an unmapped path comes back as `cannot apply a correction to unknown
 * field path 'totals.grand_total'`, which names the field. Not measured here:
 * what shape a `RequestValidationError` on this route would take instead --
 * see `ApiErrorBody` in client.ts, which covers both.
 *
 * `request` is an unchecked cast, so the `ReceiptDetail` here is a claim about
 * the route, not a validation of the body.
 */
export function patchReceipt(id: string, patch: FieldMap): Promise<ReceiptDetail> {
  return request(`/receipts/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
}

/** Close a review task. **`taskId` is a review task id, not a receipt id.**
 *
 * `POST /review/{task_id}/complete` looks the id up in `review_tasks`
 * (review/api.py:520-547) and answers 403 unless the caller is the assignee or
 * an admin, so passing a receipt id here is a 404 that reads like a
 * permissions problem.
 */
export function completeTask(taskId: string): Promise<unknown> {
  return request(`/review/${encodeURIComponent(taskId)}/complete`, { method: 'POST' })
}

/** What the submit chain has to say once it has succeeded.
 *
 * Three outcomes rather than a `Rewrite[]`, because "nothing was rewritten" and
 * "we could not tell" are different facts and collapsing them would report the
 * second as the first -- the one direction a warning must never fail in.
 */
export type SubmitOutcome =
  | { readonly kind: 'clean' }
  | { readonly kind: 'rewritten'; readonly rewrites: readonly Rewrite[] }
  | { readonly kind: 'unverified'; readonly why: string }

/** The patch reply as a `FieldMap`, or `null` if it is not a receipt.
 *
 * `request` resolves an empty body to `undefined`, and this route always returns
 * a document, so `undefined` here means something other than the API answered.
 * The shape is checked rather than trusted because `request<T>` is an unchecked
 * cast: `fieldsFromReceipt` reads `.totals` and `.line_items`, and a reply
 * missing either would throw a `TypeError` *after* the write had already landed.
 */
function storedFields(reply: ReceiptDetail | undefined): FieldMap | null {
  if (reply === undefined || reply === null) {
    return null
  }
  if (typeof reply.totals !== 'object' || reply.totals === null) {
    return null
  }
  if (!Array.isArray(reply.line_items)) {
    return null
  }
  return fieldsFromReceipt(reply)
}

/** Strictly sequential. Nothing advances past a step that failed.
 *
 * The patch is always sent, even when it is `{}`: an empty body is legal and
 * means "no changes, still mark reviewed" (review/schemas.py:222-227), so
 * skipping it for an untouched receipt would close the task and leave the row at
 * `needs_review`.
 *
 * The reply is compared against what was sent before the task is closed, because
 * **the server does not always store what it is given**: `_plan_change` runs
 * `redact_pan` over every coerced text value, and measured through the real
 * route, `PATCH {'receipt.date_raw': '4111111111111111'}` reads back as
 * `'************1111'`. The reviewer would otherwise never learn their input did
 * not land. `PATCH` already returns the full `ReceiptDetail`, so this costs no
 * extra request.
 *
 * The comparison runs between the two calls but never blocks the second: the
 * write has landed and the reviewer's work is done, so a rewrite is a notice,
 * not a failure. Stopping here would leave the queue task open over a receipt
 * that is already `reviewed` -- the exact orphan the `complete` step exists to
 * prevent.
 */
export async function submitReview(
  receiptId: string,
  taskId: string,
  patch: FieldMap,
): Promise<SubmitOutcome> {
  let reply: ReceiptDetail | undefined
  try {
    reply = await patchReceipt(receiptId, patch)
  } catch (caught) {
    throw new SubmitError('patch', caught)
  }
  const stored = storedFields(reply)
  const rewrites = stored === null ? [] : findRewrites(patch, stored)

  try {
    await completeTask(taskId)
  } catch (caught) {
    throw new SubmitError('complete', caught)
  }

  if (stored === null) {
    return {
      kind: 'unverified',
      why: 'the reply to the save was not a receipt, so what was stored could not be checked',
    }
  }
  return rewrites.length === 0 ? { kind: 'clean' } : { kind: 'rewritten', rewrites }
}
