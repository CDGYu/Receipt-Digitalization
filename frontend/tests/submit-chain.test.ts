import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../src/api/client'
import { SubmitError, completeTask, patchReceipt, submitReview } from '../src/api/review'
import type { FieldMap } from '../src/review/patch'

/** `submitReview`, expected to reject.
 *
 * `.catch((e) => e as SubmitError)` -- what the plan used -- types as
 * `void | SubmitError` and fails `tsc -b` with
 * `TS2339: Property 'step' does not exist on type 'void'`, and at runtime a
 * `submitReview` that wrongly *resolved* would hand the assertions `undefined`
 * and fail with a `TypeError` about reading a property, not with the reason.
 * This says so instead.
 */
async function rejection(receiptId: string, taskId: string, patch: FieldMap): Promise<SubmitError> {
  try {
    await submitReview(receiptId, taskId, patch)
  } catch (caught) {
    return caught as SubmitError
  }
  throw new Error('submitReview resolved when it was expected to reject')
}

const CALLS: string[] = []
const BODIES: (string | null)[] = []

function stubFetch(behaviour: (path: string, method: string) => Response) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      CALLS.push(`${method} ${path}`)
      BODIES.push(typeof init?.body === 'string' ? init.body : null)
      return behaviour(path, method)
    }),
  )
}

function ok(body: unknown = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

function fail(status: number, message: string): Response {
  return new Response(JSON.stringify({ error: { message } }), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

beforeEach(() => {
  CALLS.length = 0
  BODIES.length = 0
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('submitReview', () => {
  it('patches, then completes, in that order', async () => {
    stubFetch(() => ok())
    await submitReview('r1', 't1', { 'totals.total': '1000.00' })
    expect(CALLS).toEqual(['PATCH /receipts/r1', 'POST /review/t1/complete'])
  })

  it('does not re-read the receipt after a patch that succeeded', async () => {
    // `PATCH /receipts/{id}` returns the full `ReceiptDetail` it just wrote
    // (review/api.py:392-398), so the reply *is* the new state. A follow-up GET
    // would be a second round trip for data already in hand -- and the exact
    // equality above is what forbids it, so it is stated here rather than left
    // implicit in another test's assertion.
    stubFetch(() => ok())
    await submitReview('r1', 't1', {})
    expect(CALLS.filter((call) => call.startsWith('GET '))).toEqual([])
  })

  it('sends the flat dotted object, with nothing nested and nothing dropped', async () => {
    // Dotted top-level keys bypass the typed sub-models and reach
    // `apply_corrections` unchanged -- measured against the real model:
    //   CorrectionPatch.model_validate({'totals.total': '1000.00',
    //     'receipt.time': None, 'line_items[0].qty': '9.9'})
    //     .model_dump(exclude_unset=True, mode='json')
    //   -> {'totals.total': '1000.00', 'receipt.time': None,
    //       'line_items[0].qty': '9.9'}
    stubFetch(() => ok())
    await submitReview('r1', 't1', {
      'totals.total': '1000.00',
      'receipt.time': null,
      'line_items[0].qty': '9.9',
    })
    expect(BODIES[0]).toBe(
      '{"totals.total":"1000.00","receipt.time":null,"line_items[0].qty":"9.9"}',
    )
  })

  it('sends an empty body for a confirmation, because {} still marks it reviewed', async () => {
    // `{}` is legal and means "no changes, still mark reviewed"
    // (review/schemas.py:222-227). Skipping the PATCH entirely would leave the
    // receipt at `needs_review` with its task closed.
    stubFetch(() => ok())
    await submitReview('r1', 't1', {})
    expect(BODIES[0]).toBe('{}')
    expect(CALLS).toEqual(['PATCH /receipts/r1', 'POST /review/t1/complete'])
  })

  it('does not complete when the patch was rejected', async () => {
    stubFetch((_path, method) => (method === 'PATCH' ? fail(400, 'unknown field path') : ok()))
    const error = await rejection('r1', 't1', {})
    expect(error.step).toBe('patch')
    expect(CALLS).toEqual(['PATCH /receipts/r1'])
  })

  it('carries the server\'s own words for a rejected path', async () => {
    // The 400 names the offending path exactly; nothing the client could
    // compose would be more useful, so `cause` has to survive the wrapping.
    const message = "cannot apply a correction to unknown field path 'totals.grand_total'"
    stubFetch((_path, method) => (method === 'PATCH' ? fail(400, message) : ok()))
    const error = await rejection('r1', 't1', {})
    expect(error.cause).toBeInstanceOf(ApiError)
    expect((error.cause as ApiError).message).toBe(message)
    expect((error.cause as ApiError).status).toBe(400)
  })

  it('reports which step failed when the patch landed but the close did not', async () => {
    stubFetch((_path, method) =>
      method === 'POST' ? fail(403, 'only the assignee may complete this task') : ok(),
    )
    const error = await rejection('r1', 't1', {})
    expect(error.step).toBe('complete')
    expect(error.cause).toBeInstanceOf(ApiError)
  })

  it('is an Error, so an unprepared catch still has something to print', async () => {
    stubFetch((_path, method) => (method === 'PATCH' ? fail(503, 'database unavailable') : ok()))
    const error = await rejection('r1', 't1', {})
    expect(error).toBeInstanceOf(Error)
    expect(error.name).toBe('SubmitError')
    expect(error.message).toBe('review submit failed at patch')
  })
})

describe('the two calls the chain is made of', () => {
  it('patches the receipt id and completes the task id, which are different things', async () => {
    // `POST /review/{task_id}/complete` takes a **review task** id, not a
    // receipt id (review/api.py:520-535). Passing the receipt id there is a 404
    // that looks like a permissions problem.
    stubFetch(() => ok())
    await patchReceipt('receipt-1', {})
    await completeTask('task-1')
    expect(CALLS).toEqual(['PATCH /receipts/receipt-1', 'POST /review/task-1/complete'])
  })

  it('encodes an id that is not the UUID the route parses', async () => {
    stubFetch(() => ok())
    await patchReceipt('a/b', {})
    await completeTask('a/b')
    expect(CALLS).toEqual(['PATCH /receipts/a%2Fb', 'POST /review/a%2Fb/complete'])
  })
})

/** A `ReceiptDetail` good enough for `fieldsFromReceipt`, with overrides. */
function detail(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 'r1',
    status: 'reviewed',
    confidence: '0.620',
    confidence_reasons: [],
    merchant_name_raw: 'METRO OIL',
    receipt_number: 'INV-1',
    txn_date: '2026-07-30',
    date_raw: '30/07/2026',
    txn_time: '14:30:45',
    currency: 'USD',
    created_at: '2026-07-30T09:31:02+00:00',
    payment_method: 'VISA',
    card_last4: '4242',
    is_handwritten: false,
    legibility: 'good',
    duplicate_of: null,
    receipt_is_inconsistent: false,
    totals: {
      subtotal: '1000.0000',
      tax: null,
      discount: null,
      total: '1000.0000',
      tender: null,
      change: null,
    },
    line_items: [],
    findings: [],
    ...over,
  }
}

describe('submitReview: what the server actually stored', () => {
  it('reports clean when the reply matches what was sent', async () => {
    stubFetch(() => ok(detail()))
    expect(await submitReview('r1', 't1', { 'merchant.name': 'METRO OIL' })).toEqual({
      kind: 'clean',
    })
  })

  it('treats the column display scale as clean, not as a rewrite', async () => {
    // Measured through the real route: every money field comes back at the
    // column's scale (`'1000.00'` in, `'1000.0000'` out). Warning on that would
    // fire on every money edit ever made.
    stubFetch(() => ok(detail()))
    expect(await submitReview('r1', 't1', { 'totals.total': '1000.00' })).toEqual({ kind: 'clean' })
  })

  it('reports a redacted value, naming the field and both sides', async () => {
    stubFetch(() => ok(detail({ date_raw: '**********3456' })))
    expect(await submitReview('r1', 't1', { 'receipt.date_raw': '20260730123456' })).toEqual({
      kind: 'rewritten',
      rewrites: [
        { path: 'receipt.date_raw', sent: '20260730123456', stored: '**********3456' },
      ],
    })
  })

  it('still closes the task when the server rewrote something', async () => {
    // The write landed and the reviewer's work is done; the warning is a notice,
    // not a failure. Stopping the chain here would leave the queue task open
    // over a receipt that is already `reviewed`.
    stubFetch(() => ok(detail({ date_raw: '**********3456' })))
    await submitReview('r1', 't1', { 'receipt.date_raw': '20260730123456' })
    expect(CALLS).toEqual(['PATCH /receipts/r1', 'POST /review/t1/complete'])
  })

  it('says so when the reply cannot be checked, rather than claiming it was clean', async () => {
    // `request` resolves an empty body to `undefined`. This route always returns
    // a document, so that means something other than the API answered -- and
    // "we could not check" must not be reported as "nothing was rewritten".
    vi.stubGlobal(
      'fetch',
      vi.fn(async (path: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        CALLS.push(`${method} ${path}`)
        return new Response('', { status: 200 })
      }),
    )
    const outcome = await submitReview('r1', 't1', { 'totals.total': '1000.00' })
    expect(outcome.kind).toBe('unverified')
    expect(CALLS).toEqual(['PATCH /receipts/r1', 'POST /review/t1/complete'])
  })

  it('is clean for a confirmation, which sent nothing to check', async () => {
    stubFetch(() => ok(detail()))
    expect(await submitReview('r1', 't1', {})).toEqual({ kind: 'clean' })
  })
})
