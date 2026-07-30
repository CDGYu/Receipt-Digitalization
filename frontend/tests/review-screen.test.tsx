import { StrictMode } from 'react'
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ReviewScreen } from '../src/review/ReviewScreen'
import type { Money, ReceiptDetail, ReceiptSummary, ReviewTask } from '../src/api/types'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

type Reply = readonly [number, unknown]

function isReply(value: Reply | readonly Reply[]): value is Reply {
  return typeof value[0] === 'number'
}

/** `fetch`, answering by exact path. An unstubbed path is a 404 naming itself,
 *  so a request the screen was not supposed to make shows up as a readable
 *  failure instead of an undefined body.
 *
 *  A key may be a bare path (`/receipts/a1`, any method) or a method and a path
 *  (`PATCH /receipts/a1`); the specific one wins. `GET /receipts/{id}` and
 *  `PATCH /receipts/{id}` are the same URL and answer with different bodies, so
 *  path alone stopped being enough once the submit chain existed.
 *
 *  A key may carry a *queue* of replies instead of one: each call takes the
 *  next and the last repeats, which is how "the detail call fails, then works"
 *  is expressed without a bespoke mock. */
function stubApi(routes: Record<string, Reply | readonly Reply[]>) {
  const pending = new Map<string, Reply[]>(
    Object.entries(routes).map(([path, value]) => [path, isReply(value) ? [value] : [...value]]),
  )
  return vi.fn((path: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    const queue = pending.get(`${method} ${path}`) ?? pending.get(path)
    if (queue === undefined) {
      return Promise.resolve(
        jsonResponse(404, { error: { message: `no stub for ${method} ${path}` } }),
      )
    }
    const reply = queue.length > 1 ? queue.shift()! : queue[0]
    return Promise.resolve(jsonResponse(reply[0], reply[1]))
  })
}

/** How many times `path` was requested. The whole point of the two claim tests
 *  is a count, not a presence. */
function callsTo(fetchMock: ReturnType<typeof stubApi>, path: string): number {
  return fetchMock.mock.calls.filter(([called]) => called === path).length
}

/** Every call as `METHOD /path`, in order. */
function chain(fetchMock: ReturnType<typeof stubApi>): string[] {
  return fetchMock.mock.calls.map(
    ([path, init]) => `${(init as RequestInit | undefined)?.method ?? 'GET'} ${path}`,
  )
}

/** The body of the first `PATCH`, parsed. Says what went wrong when there was
 *  no PATCH at all, rather than throwing a `TypeError` about `undefined`. */
function patchBody(fetchMock: ReturnType<typeof stubApi>): unknown {
  const call = fetchMock.mock.calls.find(
    ([, init]) => (init as RequestInit | undefined)?.method === 'PATCH',
  )
  if (call === undefined) {
    throw new Error(`no PATCH was issued; the calls were ${chain(fetchMock).join(', ')}`)
  }
  return JSON.parse(String((call[1] as RequestInit).body))
}

const TASK: ReviewTask = {
  id: 't1',
  receipt_id: 'a1',
  reason: 'full re-key',
  priority: 1,
  assigned_to: 'alice',
  state: 'in_progress',
  opened_at: '2026-07-14T09:40:00+00:00',
  closed_at: null,
}

/** What `GET /review/next` actually puts in `receipt`: the light summary, with
 *  `total` at the top level and no findings and no breakdown. */
const SUMMARY: ReceiptSummary = {
  id: 'a1',
  status: 'needs_review',
  confidence: '0.620' as Money,
  merchant_name_raw: 'Whole Foods Market',
  txn_date: '2026-07-14',
  currency: 'USD',
  total: '97.43' as Money,
  created_at: '2026-07-14T09:31:02+00:00',
}

const RECEIPT: ReceiptDetail = {
  id: 'a1',
  status: 'needs_review',
  confidence: '0.620' as Money,
  confidence_reasons: [{ reason: 'validation errors present', penalty: '-0.35' as Money }],
  merchant_name_raw: 'Whole Foods Market',
  receipt_number: 'WF-100244',
  txn_date: '2026-07-14',
  // Garbled, so `confirms an untouched receipt with an empty patch` also proves
  // that a printed date nobody edited stays out of the patch.
  date_raw: "  1L/O7/2O26 '~ ",
  // `HH:MM:SS`, the way `_iso_time` renders it. See `ReceiptDetail.txn_time`.
  txn_time: '09:31:02',
  currency: 'USD',
  created_at: '2026-07-14T09:31:02+00:00',
  payment_method: 'VISA',
  card_last4: '4242',
  is_handwritten: false,
  legibility: 'good',
  duplicate_of: null,
  receipt_is_inconsistent: false,
  totals: {
    subtotal: '90.00' as Money,
    tax: '7.43' as Money,
    discount: null,
    total: '97.43' as Money,
    tender: '100.00' as Money,
    change: '2.57' as Money,
  },
  line_items: [],
  findings: [
    {
      rule_id: 'R020',
      severity: 'error',
      message: 'subtotal + tax does not equal total',
      context: null,
      resolved_by_repair: false,
    },
  ],
}

const CLAIMED_ROUTES = {
  '/review/next': [200, { task: TASK, receipt: SUMMARY }],
  '/receipts/a1': [200, RECEIPT],
  '/receipts/a1/image': [200, { url: '/receipts/a1/image/blob?variant=original&exp=1&sig=s' }],
} as const

describe('ReviewScreen', () => {
  it('treats an empty queue as a state and never asks for a receipt', async () => {
    // `{"task": null}` arrives as 200 with a body (src/receipts/review/api.py
    // :496-500). Rendering it as an error, or letting it reach
    // `task.receipt_id`, are the two ways to get this wrong.
    const fetchMock = stubApi({ '/review/next': [200, { task: null }] })
    vi.stubGlobal('fetch', fetchMock)

    render(<ReviewScreen />)

    expect(await screen.findByText(/review queue is empty/i)).toBeDefined()
    expect(screen.queryByRole('alert')).toBeNull()
    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual(['/review/next'])
  })

  it('follows the claimed task with the full receipt and shows it', async () => {
    const fetchMock = stubApi(CLAIMED_ROUTES)
    vi.stubGlobal('fetch', fetchMock)

    render(<ReviewScreen />)

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Whole Foods Market' }),
    ).toBeDefined()
    // The second call is the point: `receipt_summary` in the first reply carries
    // neither findings nor the confidence breakdown, so both of these can only
    // have come from `GET /receipts/{id}`.
    expect(fetchMock.mock.calls.map(([path]) => path)).toContain('/receipts/a1')
    expect(screen.getByText('R020')).toBeDefined()
    expect(screen.getByText('validation errors present')).toBeDefined()
    expect(screen.getByText('-0.35')).toBeDefined()
    // Findings are what the extraction run found; nothing re-checks them when a
    // reviewer edits, so neither the heading nor the note may imply current
    // state. Both are asserted -- the note carries the part a heading cannot
    // say, and was previously unpinned.
    expect(screen.getByRole('heading', { name: /at extraction time/i })).toBeDefined()
    expect(screen.getByText(/not re-checked when you edit/i)).toBeDefined()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('claims exactly one task when React mounts the tree twice', async () => {
    // `main.tsx` renders under `<StrictMode>`, which invokes the mount effect
    // twice. `fetchNext` is a claiming write, so an unguarded effect makes the
    // very first thing the app does a double claim -- and the second task is
    // stranded, because nothing returns an `IN_PROGRESS` row to `OPEN`.
    const fetchMock = stubApi(CLAIMED_ROUTES)
    vi.stubGlobal('fetch', fetchMock)

    render(
      <StrictMode>
        <ReviewScreen />
      </StrictMode>,
    )

    await screen.findByRole('heading', { level: 1, name: 'Whole Foods Market' })
    expect(callsTo(fetchMock, '/review/next')).toBe(1)
  })

  it('resumes the task it already holds instead of claiming another', async () => {
    // No StrictMode here: this is the production path. `fetchNext` succeeds and
    // charges the queue, `fetchReceipt` then fails, and the reviewer clicks
    // "Try again". Re-entering `fetchNext` would claim a second task and lose
    // the first for good.
    const fetchMock = stubApi({
      '/review/next': [200, { task: TASK, receipt: SUMMARY }],
      '/receipts/a1': [
        [503, { error: { message: 'database unavailable' } }],
        [200, RECEIPT],
      ],
      '/receipts/a1/image': [200, { url: '/receipts/a1/image/blob?variant=original&exp=1&sig=s' }],
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<ReviewScreen />)
    expect((await screen.findByRole('alert')).textContent).toBe('database unavailable')
    await user.click(screen.getByRole('button', { name: 'Try again' }))

    await screen.findByRole('heading', { level: 1, name: 'Whole Foods Market' })
    expect(callsTo(fetchMock, '/review/next')).toBe(1)
    expect(callsTo(fetchMock, '/receipts/a1')).toBe(2)
  })

  it("shows the API's own message when the queue call fails", async () => {
    vi.stubGlobal(
      'fetch',
      stubApi({ '/review/next': [503, { error: { message: 'database unavailable' } }] }),
    )

    render(<ReviewScreen />)

    expect((await screen.findByRole('alert')).textContent).toBe('database unavailable')
  })

  it('shows something readable when the request never reaches the API', async () => {
    // A dev server that is not up rejects `fetch` with a TypeError, so there is
    // no status and no message worth quoting -- but there still has to be one on
    // screen. Same branch `LoginPage` covers.
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    render(<ReviewScreen />)

    expect((await screen.findByRole('alert')).textContent).toBe('could not load the review queue')
  })

  it('loads again when the reviewer asks after a failure', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(503, { error: { message: 'database unavailable' } }))
      .mockResolvedValueOnce(jsonResponse(200, { task: null }))
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<ReviewScreen />)
    await screen.findByRole('alert')
    await user.click(screen.getByRole('button', { name: 'Try again' }))

    expect(await screen.findByText(/review queue is empty/i)).toBeDefined()
    expect(screen.queryByRole('alert')).toBeNull()
  })
})

/** The receipt as the server would return it after storing an edit.
 *
 *  `PATCH` replies with the full `ReceiptDetail` it just wrote, and the screen
 *  now compares that against what it sent -- so a stub that echoes the *old*
 *  state is not merely lazy, it is a receipt the server never could have
 *  returned. Amounts are given at the column scale (`Numeric(14, 4)`), which is
 *  what the real route does: measured, `'97.43'` in comes back `'97.4300'`. */
function storedAs(over: Partial<ReceiptDetail>): ReceiptDetail {
  return { ...RECEIPT, ...over }
}

function storedTotal(total: string): ReceiptDetail {
  return storedAs({ totals: { ...RECEIPT.totals, total: total as Money } })
}

/** The queue drains: the claimed task first, then nothing. Reaching the second
 *  reply is what proves the screen asked again rather than re-opening what it
 *  had just finished. */
const DRAINING = {
  '/review/next': [
    [200, { task: TASK, receipt: SUMMARY }],
    [200, { task: null }],
  ],
  'GET /receipts/a1': [200, RECEIPT],
  // Every test that edits the total types a `1` onto `97.43`; the column scale
  // is what comes back.
  'PATCH /receipts/a1': [200, storedTotal('97.4310')],
  'POST /review/t1/complete': [200, { ...TASK, state: 'done', closed_at: '2026-07-14T10:00:00Z' }],
  '/receipts/a1/image': [200, { url: '/receipts/a1/image/blob?variant=original&exp=1&sig=s' }],
} as const

async function claimAndEditTheTotal(fetchMock: ReturnType<typeof stubApi>) {
  const user = userEvent.setup()
  render(<ReviewScreen />)
  await screen.findByRole('heading', { level: 1, name: 'Whole Foods Market' })
  await user.type(screen.getByLabelText('Total'), '1')
  expect(callsTo(fetchMock, '/review/next')).toBe(1)
  return user
}

describe('ReviewScreen: editing and approval', () => {
  it('sends only what the reviewer changed, then closes the task, then asks for the next', async () => {
    const fetchMock = stubApi(DRAINING)
    vi.stubGlobal('fetch', fetchMock)

    const user = await claimAndEditTheTotal(fetchMock)
    await user.click(screen.getByRole('button', { name: /approve/i }))

    expect(await screen.findByText(/review queue is empty/i)).toBeDefined()
    // `97.43` with a `1` typed on the end. Every other one of the seventeen
    // paths was left alone and must therefore be absent -- `exclude_unset` is
    // what makes "absent" mean "do not touch".
    expect(patchBody(fetchMock)).toEqual({ 'totals.total': '97.431' })
    expect(chain(fetchMock)).toEqual([
      'GET /review/next',
      'GET /receipts/a1',
      'GET /receipts/a1/image',
      'PATCH /receipts/a1',
      'POST /review/t1/complete',
      'GET /review/next',
    ])
  })

  it('confirms an untouched receipt with an empty patch', async () => {
    // `{}` is legal and means "no changes, still mark reviewed". Every value the
    // form seeds itself with has to survive the round trip untouched for this to
    // be empty -- the `HH:MM:SS` time above all.
    const fetchMock = stubApi(DRAINING)
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<ReviewScreen />)
    await screen.findByRole('heading', { level: 1, name: 'Whole Foods Market' })
    await user.click(screen.getByRole('button', { name: /approve/i }))

    await screen.findByText(/review queue is empty/i)
    expect(patchBody(fetchMock)).toEqual({})
  })

  it('approves on Ctrl+Enter without intercepting anything else', async () => {
    const fetchMock = stubApi(DRAINING)
    vi.stubGlobal('fetch', fetchMock)

    const user = await claimAndEditTheTotal(fetchMock)
    await user.keyboard('{Control>}{Enter}{/Control}')

    expect(await screen.findByText(/review queue is empty/i)).toBeDefined()
    expect(chain(fetchMock)).toContain('POST /review/t1/complete')
  })

  it('does not approve on a bare Enter', async () => {
    // Enter moves focus on through a form; approving on it would submit a
    // half-keyed receipt. An absence assertion: the mutation that breaks it is
    // dropping the `metaKey || ctrlKey` test.
    const fetchMock = stubApi(DRAINING)
    vi.stubGlobal('fetch', fetchMock)

    const user = await claimAndEditTheTotal(fetchMock)
    await user.keyboard('{Enter}')

    expect(chain(fetchMock)).not.toContain('PATCH /receipts/a1')
    expect(screen.getByRole('heading', { level: 1, name: 'Whole Foods Market' })).toBeDefined()
  })

  it('submits once when Ctrl+Enter is pressed twice in a row', async () => {
    const fetchMock = stubApi(DRAINING)
    vi.stubGlobal('fetch', fetchMock)

    const user = await claimAndEditTheTotal(fetchMock)
    await user.keyboard('{Control>}{Enter}{Enter}{/Control}')

    await screen.findByText(/review queue is empty/i)
    expect(chain(fetchMock).filter((call) => call === 'PATCH /receipts/a1')).toHaveLength(1)
  })

  it('keeps the edits and never closes the task when the patch is rejected', async () => {
    const message = "cannot apply a correction to unknown field path 'totals.grand_total'"
    const fetchMock = stubApi({
      ...DRAINING,
      'PATCH /receipts/a1': [400, { error: { message } }],
    })
    vi.stubGlobal('fetch', fetchMock)

    const user = await claimAndEditTheTotal(fetchMock)
    await user.click(screen.getByRole('button', { name: /approve/i }))

    expect((await screen.findByRole('alert')).textContent).toContain(message)
    // Nothing was written, so the reviewer's typing must still be there to retry
    // with -- and the task must not have been closed over a receipt that never
    // took the edit.
    expect((screen.getByLabelText('Total') as HTMLInputElement).value).toBe('97.431')
    expect(chain(fetchMock)).not.toContain('POST /review/t1/complete')
    expect(callsTo(fetchMock, '/review/next')).toBe(1)
    expect(screen.queryByRole('button', { name: /close task/i })).toBeNull()
  })

  it('says the receipt was saved but the task is still open when only the close fails', async () => {
    // `apply_corrections` commits inside its own transaction, so a 403 from
    // `complete` leaves a `reviewed` receipt with an open queue entry. Advancing
    // here would orphan it silently.
    const fetchMock = stubApi({
      ...DRAINING,
      'POST /review/t1/complete': [
        [403, { error: { message: 'only the assignee or an admin may complete this task' } }],
        [200, { ...TASK, state: 'done' }],
      ],
    })
    vi.stubGlobal('fetch', fetchMock)

    const user = await claimAndEditTheTotal(fetchMock)
    await user.click(screen.getByRole('button', { name: /approve/i }))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toMatch(/saved/i)
    expect(alert.textContent).toContain('only the assignee or an admin may complete this task')
    expect(callsTo(fetchMock, '/review/next')).toBe(1)

    // ...and the offered repair closes the task alone, without patching again.
    await user.click(screen.getByRole('button', { name: /close task/i }))
    expect(await screen.findByText(/review queue is empty/i)).toBeDefined()
    expect(chain(fetchMock).filter((call) => call === 'PATCH /receipts/a1')).toHaveLength(1)
    expect(chain(fetchMock).filter((call) => call === 'POST /review/t1/complete')).toHaveLength(2)
  })

  it('says something on screen when the submit never reaches the API', async () => {
    const fetchMock = stubApi(DRAINING)
    vi.stubGlobal('fetch', fetchMock)
    const user = await claimAndEditTheTotal(fetchMock)
    // A dev server that went away between the load and the approval: no status,
    // no message worth quoting, but silence is not an option.
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    await user.click(screen.getByRole('button', { name: /approve/i }))

    expect((await screen.findByRole('alert')).textContent).toMatch(/could not be submitted/i)
  })

  it('sends a repaired printed date verbatim, and only once it is dirty', async () => {
    // The whole point of `receipt.date_raw` being correctable: the model misread
    // the printed date, and the reviewer retypes what the paper says. What this
    // test pins is the **request**: the exact characters reach the wire, and a
    // field nobody touched is not on it at all. Measured through the real PATCH
    // route, an unchanged value writes no `corrections` row -- but the server
    // does rewrite some inputs on the way into the column (see
    // `ReceiptForm`'s docblock), so this is not a claim about what gets stored.
    const fetchMock = stubApi({
      ...DRAINING,
      'PATCH /receipts/a1': [200, storedAs({ date_raw: '14 JUL 2026' })],
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<ReviewScreen />)
    await screen.findByRole('heading', { level: 1, name: 'Whole Foods Market' })
    const printed = screen.getByLabelText('Printed date')
    await user.clear(printed)
    await user.type(printed, '14 JUL 2026')
    await user.click(screen.getByRole('button', { name: /approve/i }))

    await screen.findByText(/review queue is empty/i)
    expect(patchBody(fetchMock)).toEqual({ 'receipt.date_raw': '14 JUL 2026' })
  })

  it('edits a line item by its position and leaves the rest of the row alone', async () => {
    const withItems: ReceiptDetail = {
      ...RECEIPT,
      line_items: [
        {
          position: 3,
          description_raw: 'AVOCADO',
          sku: null,
          qty: '2.000' as Money,
          unit: null,
          unit_price: '3.50' as Money,
          line_total: '7.00' as Money,
          modifiers: [],
          line_confidence: null,
        },
      ],
    }
    const fetchMock = stubApi({
      ...DRAINING,
      'GET /receipts/a1': [200, withItems],
      'PATCH /receipts/a1': [
        200,
        {
          ...withItems,
          line_items: [{ ...withItems.line_items[0], line_total: '7.0010' as Money }],
        },
      ],
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<ReviewScreen />)
    await screen.findByRole('heading', { level: 1, name: 'Whole Foods Market' })
    await user.type(screen.getByLabelText('Line total 3'), '1')
    await user.click(screen.getByRole('button', { name: /approve/i }))

    await screen.findByText(/review queue is empty/i)
    expect(patchBody(fetchMock)).toEqual({ 'line_items[3].line_total': '7.001' })
  })
})

describe('ReviewScreen: what the server actually stored', () => {
  /** A printed date the reviewer types that `redact_pan` will mask. Measured:
   *  `redact_pan('20260730123456')` is `'**********3456'`, and 14 digits is a
   *  plausible thing to read off a slip. */
  const TYPED = '20260730123456'
  const MASKED = '**********3456'

  function rewritingApi() {
    return stubApi({
      ...DRAINING,
      'PATCH /receipts/a1': [200, storedAs({ date_raw: MASKED })],
    })
  }

  async function editThePrintedDate(user: ReturnType<typeof userEvent.setup>) {
    const printed = screen.getByLabelText('Printed date')
    await user.clear(printed)
    await user.type(printed, TYPED)
    await user.click(screen.getByRole('button', { name: /approve/i }))
  }

  it('holds the screen and names the field and both values', async () => {
    const fetchMock = rewritingApi()
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<ReviewScreen />)
    await screen.findByRole('heading', { level: 1, name: 'Whole Foods Market' })
    await editThePrintedDate(user)

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('receipt.date_raw')
    expect(alert.textContent).toContain(TYPED)
    expect(alert.textContent).toContain(MASKED)
    // The task IS closed -- the write landed and the reviewer's work is done --
    // but the queue is not asked for another receipt until they have seen this.
    expect(chain(fetchMock)).toContain('POST /review/t1/complete')
    expect(callsTo(fetchMock, '/review/next')).toBe(1)
    expect(screen.queryByText(/review queue is empty/i)).toBeNull()
  })

  it('moves on only once the reviewer acknowledges it', async () => {
    const fetchMock = rewritingApi()
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<ReviewScreen />)
    await screen.findByRole('heading', { level: 1, name: 'Whole Foods Market' })
    await editThePrintedDate(user)
    await screen.findByRole('alert')

    await user.click(screen.getByRole('button', { name: /next receipt/i }))

    expect(await screen.findByText(/review queue is empty/i)).toBeDefined()
    expect(callsTo(fetchMock, '/review/next')).toBe(2)
    // Acknowledging is not a second submit.
    expect(chain(fetchMock).filter((c) => c === 'PATCH /receipts/a1')).toHaveLength(1)
    expect(chain(fetchMock).filter((c) => c === 'POST /review/t1/complete')).toHaveLength(1)
  })

  it('leaves no focused control that a stray keystroke could dismiss it with', async () => {
    // The regression this pins: `Approve` and the acknowledgement used to be two
    // buttons alternating in one JSX slot, so React reconciled them into the same
    // DOM node and the relabel happened under the reviewer's finger. Measured
    // before the fix -- `document.activeElement.textContent` was `'Next receipt'`,
    // `focused === approve` was true, and a bare Enter took /review/next from 1
    // to 2. Click-to-approve is the ordinary path, so that is one keystroke of
    // muscle memory between a reviewer and a warning they never read.
    const fetchMock = rewritingApi()
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<ReviewScreen />)
    await screen.findByRole('heading', { level: 1, name: 'Whole Foods Market' })
    const approve = screen.getByRole('button', { name: /approve/i })
    await editThePrintedDate(user)
    await screen.findByRole('alert')

    // The Approve button is gone, not relabelled.
    expect(screen.queryByRole('button', { name: /approve/i })).toBeNull()
    const acknowledge = screen.getByRole('button', { name: /next receipt/i })
    expect(acknowledge).not.toBe(approve)
    expect(document.activeElement).not.toBe(acknowledge)

    // ...so neither bare key does anything.
    const before = callsTo(fetchMock, '/review/next')
    await user.keyboard('{Enter}')
    await user.keyboard(' ')
    expect(callsTo(fetchMock, '/review/next')).toBe(before)
    expect(screen.getByRole('alert')).toBeDefined()
  })

  it('puts the acknowledgement inside the notice, where the reviewer is looking', async () => {
    const fetchMock = rewritingApi()
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<ReviewScreen />)
    await screen.findByRole('heading', { level: 1, name: 'Whole Foods Market' })
    await editThePrintedDate(user)

    const alert = await screen.findByRole('alert')
    expect(within(alert).getByRole('button', { name: /next receipt/i })).toBeDefined()
  })

  it('does not cry wolf when only the column scale differs', async () => {
    // The false positive that would make this warning worthless. `DRAINING`
    // replies `'97.4310'` to a typed `'97.431'` -- exactly what the real route
    // does -- and the screen must advance without a word.
    const fetchMock = stubApi(DRAINING)
    vi.stubGlobal('fetch', fetchMock)

    const user = await claimAndEditTheTotal(fetchMock)
    await user.click(screen.getByRole('button', { name: /approve/i }))

    expect(await screen.findByText(/review queue is empty/i)).toBeDefined()
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.queryByRole('button', { name: /next receipt/i })).toBeNull()
  })

  it('holds the screen when the reply could not be checked at all', async () => {
    // A body-less 200 means something other than the API answered. "Could not
    // check" must not be shown as "nothing was rewritten".
    const fetchMock = vi.fn((path: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      if (method === 'PATCH') {
        return Promise.resolve(new Response('', { status: 200 }))
      }
      return stubApi(DRAINING)(path, init)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<ReviewScreen />)
    await screen.findByRole('heading', { level: 1, name: 'Whole Foods Market' })
    await user.click(screen.getByRole('button', { name: /approve/i }))

    expect((await screen.findByRole('alert')).textContent).toMatch(/could not be checked/i)
    expect(screen.getByRole('button', { name: /next receipt/i })).toBeDefined()
  })
})
