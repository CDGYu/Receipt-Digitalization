import { StrictMode } from 'react'
import { cleanup, render, screen } from '@testing-library/react'
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
 *  A path may carry a *queue* of replies instead of one: each call takes the
 *  next and the last repeats, which is how "the detail call fails, then works"
 *  is expressed without a bespoke mock. */
function stubApi(routes: Record<string, Reply | readonly Reply[]>) {
  const pending = new Map<string, Reply[]>(
    Object.entries(routes).map(([path, value]) => [path, isReply(value) ? [value] : [...value]]),
  )
  return vi.fn((path: string) => {
    const queue = pending.get(path)
    if (queue === undefined) {
      return Promise.resolve(jsonResponse(404, { error: { message: `no stub for ${path}` } }))
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
  txn_date: '2026-07-14',
  date_raw: '14/07/2026',
  currency: 'USD',
  created_at: '2026-07-14T09:31:02+00:00',
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
