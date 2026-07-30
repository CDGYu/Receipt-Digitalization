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

/** `fetch`, answering by exact path. An unstubbed path is a 404 naming itself,
 *  so a request the screen was not supposed to make shows up as a readable
 *  failure instead of an undefined body. */
function stubApi(routes: Record<string, readonly [number, unknown]>) {
  return vi.fn((path: string) => {
    const route = routes[path]
    return Promise.resolve(
      route === undefined
        ? jsonResponse(404, { error: { message: `no stub for ${path}` } })
        : jsonResponse(route[0], route[1]),
    )
  })
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
    // reviewer edits, so the heading must not imply current state.
    expect(screen.getByRole('heading', { name: /at extraction time/i })).toBeDefined()
    expect(screen.queryByRole('alert')).toBeNull()
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
