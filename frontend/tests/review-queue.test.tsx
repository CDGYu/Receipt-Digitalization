import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ReviewQueue } from '../src/review/ReviewQueue'
import type { Money, ReceiptSummary, ReviewTask } from '../src/api/types'

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

/** `fetch`, answering by exact path, keyed `METHOD path` or a bare path.
 *
 *  An unstubbed path answers 404 naming itself, so a request this screen was
 *  not supposed to make surfaces as a readable failure rather than an undefined
 *  body -- the same shape `review-screen.test.tsx` uses.
 */
function stubApi(routes: Record<string, readonly [number, unknown]>) {
  return vi.fn((path: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    const reply = routes[`${method} ${path}`] ?? routes[path]
    if (reply === undefined) {
      return Promise.resolve(
        jsonResponse(404, { error: { message: `no stub for ${method} ${path}` } }),
      )
    }
    return Promise.resolve(jsonResponse(reply[0], reply[1]))
  })
}

function task(over: Partial<ReviewTask>): ReviewTask {
  return {
    id: 't-1',
    receipt_id: 'r-1',
    reason: 'quick verify',
    priority: 5,
    assigned_to: null,
    state: 'open',
    opened_at: '2026-08-25T09:30:00+00:00',
    closed_at: null,
    ...over,
  }
}

function receipt(over: Partial<ReceiptSummary>): ReceiptSummary {
  return {
    id: 'r-1',
    status: 'needs_review',
    confidence: '0.41' as Money,
    merchant_name_raw: 'Tesco',
    txn_date: '2026-08-20',
    currency: 'GBP',
    total: '12.40' as Money,
    created_at: '2026-08-25T09:00:00+00:00',
    ...over,
  }
}

const TASKS_PATH = '/review/tasks'
const RECEIPTS_PATH = '/receipts?status=needs_review'

/** Two open tasks, the reviewer's own in-progress one, and a closed one. */
function aQueue() {
  return {
    [TASKS_PATH]: [
      200,
      {
        items: [
          task({ id: 't-urgent', receipt_id: 'r-urgent', priority: 0, reason: 'urgent: no total' }),
          task({ id: 't-quick', receipt_id: 'r-quick', priority: 5 }),
          task({
            id: 't-mine',
            receipt_id: 'r-mine',
            state: 'in_progress',
            assigned_to: 'alice',
          }),
          task({ id: 't-done', receipt_id: 'r-done', state: 'done', assigned_to: 'alice' }),
        ],
        has_more: false,
      },
    ],
    [RECEIPTS_PATH]: [
      200,
      {
        items: [
          receipt({ id: 'r-urgent', merchant_name_raw: 'Sainsburys', total: null }),
          receipt({ id: 'r-quick', merchant_name_raw: 'Tesco', total: '12.40' as Money }),
          receipt({ id: 'r-mine', merchant_name_raw: 'Costa', total: '4.20' as Money }),
        ],
        has_more: false,
      },
    ],
  } as Record<string, readonly [number, unknown]>
}

async function renderQueue(
  routes: Record<string, readonly [number, unknown]>,
  navigate = vi.fn(),
) {
  const fetchMock = stubApi(routes)
  vi.stubGlobal('fetch', fetchMock)
  render(<ReviewQueue navigate={navigate} />)
  await screen.findByRole('heading', { name: 'Receipts waiting for review' })
  return { fetchMock, navigate }
}

describe('the review queue list', () => {
  it('shows every waiting receipt, not just the one the queue would hand out', async () => {
    // The whole point. `GET /review/next` returns one task; this screen exists
    // because a reviewer could not see what else was there.
    await renderQueue(aQueue())

    // Two tables, deliberately: the reviewer's own task is separated from the
    // backlog, so this asks for both rather than assuming one.
    const tables = screen.getAllByRole('table')
    expect(tables.length).toBe(2)
    const backlog = tables[tables.length - 1]
    // Header row plus both open tasks.
    expect(within(backlog).getAllByRole('row').length).toBe(3)
    expect(screen.getByText('Sainsburys')).toBeTruthy()
    expect(screen.getByText('Tesco')).toBeTruthy()
  })

  it('keeps the queue order the server sent rather than re-sorting', async () => {
    // `list_tasks` orders by `priority, opened_at, id` -- the same total order
    // `_claim_stmt` claims in -- so the first backlog row is genuinely the row
    // `GET /review/next` would hand out. Re-sorting here would make the list
    // disagree with the queue while looking tidier.
    await renderQueue(aQueue())

    const rendered = screen.getAllByRole('button', { name: 'Review' })
    expect(rendered.length).toBe(2)
    const rows = screen.getAllByRole('row').map((row) => row.textContent ?? '')
    const urgent = rows.findIndex((text) => text.includes('urgent: no total'))
    const quick = rows.findIndex((text) => text.includes('quick verify') && text.includes('Tesco'))
    expect(urgent).toBeLessThan(quick)
  })

  it('renders a task whose receipt is not on the joined page', async () => {
    // Two requests paginate independently. Dropping the row would hide a
    // reviewable receipt because a DIFFERENT request ran out of page, and the
    // task row is the thing that makes it claimable at all.
    const routes = aQueue()
    routes[RECEIPTS_PATH] = [200, { items: [], has_more: false }]

    await renderQueue(routes)

    // THREE, not two: the reviewer's own in-progress row loses its receipt on
    // the same empty page, and it must survive for the same reason -- it is
    // the row that resumes their work. Written as 2 first, from counting the
    // backlog and forgetting the row above it.
    expect(screen.getAllByText('receipt not on this page').length).toBe(3)
    expect(screen.getAllByRole('button', { name: 'Review' }).length).toBe(2)
    expect(screen.getByRole('button', { name: 'Resume' })).toBeTruthy()
  })

  it("separates the reviewer's own task and offers it as a resume", async () => {
    await renderQueue(aQueue())

    const mine = screen.getByRole('heading', { name: 'Already in your hands' })
    expect(mine).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Resume' })).toBeTruthy()
    expect(screen.getByText('Costa')).toBeTruthy()
  })

  it('shows no row at all for a closed task, in either section', async () => {
    // `list_tasks` scopes a reviewer to open rows PLUS THEIR OWN IN ANY STATE
    // (ADR-0026), so a reviewer's finished work comes back on this call. It is
    // history, not work to pick up.
    //
    // **This assertion was vacuous when first written** and is kept as a
    // warning: it read `queryByText('r-done')` -- a receipt id this screen
    // never renders -- plus a button count that a `done` row could not change,
    // because a row matching neither render filter appears nowhere regardless.
    // Deleting the component's `!== 'done'` filter left it GREEN. What it
    // asserts now is the reachable failure: a backlog filter widened from
    // `=== 'open'` to `!== 'in_progress'` would sweep closed work into the list
    // a reviewer picks from, and THAT this can see.
    await renderQueue(aQueue())

    const merchants = screen.getAllByRole('row').map((row) => row.textContent ?? '')
    expect(merchants.some((text) => text.includes('r-done'))).toBe(false)
    // Header row + 1 resume row, and header row + 2 backlog rows.
    const tables = screen.getAllByRole('table')
    expect(within(tables[0]).getAllByRole('row').length).toBe(2)
    expect(within(tables[1]).getAllByRole('row').length).toBe(3)
  })

  it('says so when nothing is waiting', async () => {
    const routes = aQueue()
    routes[TASKS_PATH] = [200, { items: [], has_more: false }]

    await renderQueue(routes)

    expect(screen.getByText('Nothing is waiting for review right now.')).toBeTruthy()
  })
})

describe('picking a receipt', () => {
  it('claims the row that was clicked, by id, and leaves for the reviewer', async () => {
    // The defect this pins: without `POST /review/{id}/claim` the only way to
    // claim was `GET /review/next`, which takes the HEAD of the queue -- so a
    // button on the second row would have opened the first. The clicked row
    // here is deliberately NOT the head.
    const routes = aQueue()
    routes['POST /review/t-quick/claim'] = [
      200,
      { task: task({ id: 't-quick', state: 'in_progress', assigned_to: 'alice' }), receipt: null },
    ]
    const { fetchMock, navigate } = await renderQueue(routes)

    await userEvent.click(screen.getAllByRole('button', { name: 'Review' })[1])

    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/app/review'))
    const claimCalls = fetchMock.mock.calls.filter(([path]) => String(path).includes('/claim'))
    expect(claimCalls.length).toBe(1)
    expect(String(claimCalls[0][0])).toBe('/review/t-quick/claim')
  })

  it('resumes the held task through the same call', async () => {
    // Re-claiming a task you already hold is idempotent at the route, which is
    // why Resume needs no second endpoint.
    const routes = aQueue()
    routes['POST /review/t-mine/claim'] = [
      200,
      { task: task({ id: 't-mine', state: 'in_progress', assigned_to: 'alice' }), receipt: null },
    ]
    const { navigate } = await renderQueue(routes)

    await userEvent.click(screen.getByRole('button', { name: 'Resume' }))

    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/app/review'))
  })

  it("shows the API's own words when the claim is refused, and stays put", async () => {
    // A 409 names who holds the row, or which task is already in this
    // reviewer's hands. Both are what they need to decide what to click next,
    // and neither survives being replaced with "could not open that receipt".
    const routes = aQueue()
    routes['POST /review/t-quick/claim'] = [
      409,
      { error: { message: 'review task t-quick is already held by bob' } },
    ]
    const { navigate } = await renderQueue(routes)

    await userEvent.click(screen.getAllByRole('button', { name: 'Review' })[1])

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('already held by bob')
    expect(navigate).not.toHaveBeenCalled()
  })

  it('does not navigate when the queue call itself fails', async () => {
    const { navigate } = { navigate: vi.fn() }
    const fetchMock = stubApi({})
    vi.stubGlobal('fetch', fetchMock)
    render(<ReviewQueue navigate={navigate} />)

    await screen.findByRole('alert')
    expect(navigate).not.toHaveBeenCalled()
  })
})
