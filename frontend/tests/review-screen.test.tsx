import { StrictMode } from 'react'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ReviewScreen } from '../src/review/ReviewScreen'
import { clear, hasDirtyEdits, restore } from '../src/review/stash'
import type { Money, ReceiptDetail, ReceiptSummary, ReviewTask } from '../src/api/types'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  // Module state outlives a test the way it outlives a 401 -- without this, one
  // test's unsubmitted edits would restore themselves onto the next test's task.
  clear()
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

/** The task waiting behind the one the reviewer is stuck on. */
const SECOND_TASK: ReviewTask = { ...TASK, id: 't2', receipt_id: 'b2', priority: 1 }
const SECOND_SUMMARY: ReceiptSummary = { ...SUMMARY, id: 'b2', merchant_name_raw: 'Second Merchant' }
const SECOND_RECEIPT: ReceiptDetail = { ...RECEIPT, id: 'b2', merchant_name_raw: 'Second Merchant' }

/** `fetch` with `/review/next` behaving the way ADR-0016 makes it behave.
 *
 *  **The claimed task comes back on every poll until it is completed.** That is
 *  the decision the ADR records -- a reviewer who reloads is handed the receipt
 *  they were part-way through -- and it is exactly why a stuck receipt cannot
 *  be escaped by asking the queue again. Modelled here rather than expressed as
 *  a reply queue, because a reply queue would hand out a *different* task on
 *  the second poll and quietly test the pre-ADR behaviour instead.
 *
 *  Measured against the real backend, not assumed: `tests/test_api_write.py::
 *  test_review_next_returns_the_same_task_when_a_reviewer_reloads`. */
function resumingApi(routes: Record<string, Reply | readonly Reply[]>) {
  const base = stubApi(routes)
  let completed = false
  return vi.fn((path: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    if (method === 'POST' && path === `/review/${TASK.id}/complete`) {
      completed = true
      return Promise.resolve(jsonResponse(200, { ...TASK, state: 'done' }))
    }
    if (path === '/review/next') {
      return Promise.resolve(
        jsonResponse(
          200,
          completed
            ? { task: SECOND_TASK, receipt: SECOND_SUMMARY }
            : { task: TASK, receipt: SUMMARY },
        ),
      )
    }
    return base(path, init)
  })
}

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

  it('lets the reviewer give up on a receipt that never loads, when the database is not what failed', async () => {
    // Supersedes this row's 503 form: design §6.2 renders a 503 as backend-down
    // and suppresses Skip there, because Skip's own `completeTask` needs the
    // same database -- pinned by `a 503 on load is backend-down and does NOT
    // offer Skip`. The escape itself is unchanged for every other failure, and
    // that is what this measures, end to end, including the close it spends.
    //
    // The bug: `claimed.current` is set before `fetchReceipt` and never cleared
    // when it fails, "Try again" re-runs only the failing call, and ADR-0016
    // guarantees a fresh poll hands back *the same task*. A receipt that fails
    // once is a nuisance; a receipt that fails every time took the reviewer out
    // of service, with everything behind it in the queue unreachable.
    const fetchMock = resumingApi({
      'GET /receipts/a1': [500, { error: { message: 'the receipt could not be read' } }],
      'GET /receipts/b2': [200, SECOND_RECEIPT],
      '/receipts/b2/image': [200, { url: '/receipts/b2/image/blob?exp=1&sig=s' }],
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<ReviewScreen />)
    expect((await screen.findByRole('alert')).textContent).toBe('the receipt could not be read')

    // "Try again" is not an escape: it re-runs the call that is failing, and it
    // is right not to re-enter `fetchNext`, which is a claiming write.
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    await screen.findByRole('alert')
    expect(callsTo(fetchMock, '/receipts/a1')).toBe(2)
    expect(callsTo(fetchMock, '/review/next')).toBe(1)

    // The escape: close the held task, so the next poll draws from the queue
    // instead of resuming this one.
    await user.click(screen.getByRole('button', { name: /skip this receipt/i }))

    expect(await screen.findByRole('heading', { level: 1, name: 'Second Merchant' })).toBeDefined()
    expect(chain(fetchMock)).toContain('POST /review/t1/complete')
    expect(callsTo(fetchMock, '/review/next')).toBe(2)
  })

  it('offers nothing to skip when no task was claimed in the first place', async () => {
    // The queue call itself failed, so there is no task in hand. A "skip" here
    // would have nothing to close and would be an offer the screen cannot keep.
    vi.stubGlobal(
      'fetch',
      stubApi({ '/review/next': [503, { error: { message: 'database unavailable' } }] }),
    )

    render(<ReviewScreen />)

    await screen.findByRole('alert')
    expect(screen.getByRole('button', { name: 'Try again' })).toBeDefined()
    expect(screen.queryByRole('button', { name: /skip this receipt/i })).toBeNull()
  })

  it('treats a 403 on the skip as already released, and moves on', async () => {
    // Supersedes `says so when the skip itself fails, and leaves the escape on
    // screen`: design §6.2 makes a `taken`/`gone` answer to the release mean
    // the task is not this reviewer's to release -- so it is released, not
    // re-offered. This is the `taken` half of that branch; `skip's own
    // completeTask answering 404 …` is the `gone` half. (Its 503 load is gone
    // too: §6.2 suppresses Skip entirely while the database is down.)
    //
    // Silence would still be the worst of both, which is why the screen moves
    // rather than sitting on an escape it cannot spend: a dead end here left
    // the reviewer clicking a button that could only ever 403 again.
    const fetchMock = stubApi({
      '/review/next': [
        [200, { task: TASK, receipt: SUMMARY }],
        [200, { task: null }],
      ],
      'GET /receipts/a1': [404, { error: { message: 'no receipt with id a1' } }],
      'POST /review/t1/complete': [403, { error: { message: 'not your task' } }],
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<ReviewScreen />)
    await screen.findByRole('alert')
    await user.click(screen.getByRole('button', { name: /skip this receipt/i }))

    expect(await screen.findByText(/review queue is empty/i)).toBeDefined()
    expect(screen.queryByRole('button', { name: /skip this receipt/i })).toBeNull()
    expect(callsTo(fetchMock, '/review/next')).toBe(2)
  })

  it('says so when the skip fails in a way that is not a release, and leaves the escape on screen', async () => {
    // The *other* half of `skipHeldTask`'s catch, and the half the rewrite above
    // took over. `treats a 403 on the skip as already released` now owns the
    // `taken`/`gone` branch, which leaves this one -- anything else -- with no
    // test at all, so deleting `heldTask: task`, or the whole `setPhase`, went
    // unnoticed. A failure that is neither means the task is *still* this
    // reviewer's, so the phase is re-rendered with the task held and the escape
    // stays clickable. Silence, or an escape that quietly vanished, would leave
    // a reviewer believing they had moved on from a task still in hand.
    const fetchMock = stubApi({
      '/review/next': [200, { task: TASK, receipt: SUMMARY }],
      'GET /receipts/a1': [404, { error: { message: 'no receipt with id a1' } }],
      'POST /review/t1/complete': [500, { error: { message: 'the task could not be closed' } }],
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<ReviewScreen />)
    await screen.findByRole('alert')
    await user.click(screen.getByRole('button', { name: /skip this receipt/i }))

    // Pinned by its text rather than by the role, so a stale alert from the
    // failed *load* cannot satisfy the wait.
    const alert = await screen.findByText(
      'could not release this receipt: the task could not be closed',
    )
    expect(alert.getAttribute('role')).toBe('alert')
    // Still held, so the one escape must survive its own failure.
    expect(screen.getByRole('button', { name: /skip this receipt/i })).toBeDefined()
    // And nothing advanced: `fetchNext` is a claiming write, and this task is
    // still in this reviewer's hands.
    expect(callsTo(fetchMock, '/review/next')).toBe(1)
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

  it('says what survived a refused close, and its one exit is not a second submit', async () => {
    // Supersedes `says the receipt was saved but the task is still open when
    // only the close fails`: design §6.1 replaces that state's `Close task`
    // retry with the terminal lost state, because a 403/404 on `complete` would
    // answer a retry identically forever. What has not changed is why the
    // screen stops: `apply_corrections` commits inside its own transaction, so
    // the receipt is `reviewed` while the queue entry is out of this reviewer's
    // hands, and advancing past that silently is the thing being prevented.
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
    // No auto-advance, and no retry that could only fail the same way.
    expect(callsTo(fetchMock, '/review/next')).toBe(1)
    expect(screen.queryByRole('button', { name: /close task/i })).toBeNull()

    // The one exit advances and sends nothing: the *second* `complete` reply
    // stubbed above is the trap -- a re-close would answer 200 and pass unseen.
    await user.click(within(alert).getByRole('button', { name: /next receipt/i }))
    expect(await screen.findByText(/review queue is empty/i)).toBeDefined()
    expect(chain(fetchMock).filter((call) => call === 'PATCH /receipts/a1')).toHaveLength(1)
    expect(chain(fetchMock).filter((call) => call === 'POST /review/t1/complete')).toHaveLength(1)
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

describe('the edit stash across a 401', () => {
  it('restores unsubmitted edits when ADR-0016 hands the same task back', async () => {
    // First mount: edit a field, then unmount -- the 401 path unmounts the
    // screen exactly this way (App swaps to LoginPage).
    const first = stubApi({
      '/review/next': [200, { task: TASK, receipt: SUMMARY }],
      '/receipts/a1': [200, RECEIPT],
    })
    vi.stubGlobal('fetch', first)
    const { unmount } = render(
      <StrictMode>
        <ReviewScreen />
      </StrictMode>,
    )
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
    render(
      <StrictMode>
        <ReviewScreen />
      </StrictMode>,
    )

    const restored = await screen.findByLabelText('Total')
    expect((restored as HTMLInputElement).value).toBe('99.00')
    // The overlay is the dirty diff, not the whole form: Step 5's third mutation
    // (remembering `phase.fields`) is otherwise indistinguishable from this.
    expect(restore('t1')).toEqual({ 'totals.total': '99.00' })
  })

  it('does not restore onto a different task', async () => {
    const first = stubApi({
      '/review/next': [200, { task: TASK, receipt: SUMMARY }],
      '/receipts/a1': [200, RECEIPT],
    })
    vi.stubGlobal('fetch', first)
    const { unmount } = render(
      <StrictMode>
        <ReviewScreen />
      </StrictMode>,
    )
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
    render(
      <StrictMode>
        <ReviewScreen />
      </StrictMode>,
    )

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
      // Stubbed only so `findByRole('alert')` below is unambiguous: an
      // unstubbed image route makes ImagePane render an alert of its own, and
      // the query then matches two elements and throws.
      '/receipts/a1/image': [200, { url: '/receipts/a1/image/blob?variant=original&exp=1&sig=s' }],
    })
    vi.stubGlobal('fetch', first)
    const { unmount } = render(
      <StrictMode>
        <ReviewScreen />
      </StrictMode>,
    )
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
    render(
      <StrictMode>
        <ReviewScreen />
      </StrictMode>,
    )
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
      // The reply must agree with what was sent, or `findRewrites` reports a
      // rewrite, the screen holds on `StoredDifferently` and never advances --
      // which would fail this test for a reason that has nothing to do with
      // the stash.
      'PATCH /receipts/a1': [200, storedTotal('99.00')],
      '/review/t1/complete': [200, { ...TASK, state: 'done' }],
    })
    vi.stubGlobal('fetch', fetchMock)
    render(
      <StrictMode>
        <ReviewScreen />
      </StrictMode>,
    )
    const total = await screen.findByLabelText('Total')
    await userEvent.clear(total)
    await userEvent.type(total, '99.00')
    await userEvent.keyboard('{Control>}{Enter}{/Control}')
    await screen.findByText('The review queue is empty.')

    expect(restore('t1')).toBeNull()
  })

  it('does not re-stash edits typed while the screen holds a closed task', async () => {
    // The `held` state means the PATCH landed and the task is closed, with the
    // receipt -- and its still-editable form -- left on screen to be read. An
    // overlay remembered now is unrestorable: ADR-0016 resumes only an
    // `IN_PROGRESS` row, and this task is `DONE`. It is also not free, because
    // `hasDirtyEdits` is the sign-out gate (design §4.2): a stash re-armed here
    // makes Sign out demand confirmation for edits that exist nowhere but this
    // screen and cannot be recovered by confirming anything.
    const fetchMock = stubApi({
      ...DRAINING,
      'PATCH /receipts/a1': [200, storedAs({ date_raw: '**********3456' })],
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<ReviewScreen />)
    await screen.findByRole('heading', { level: 1, name: 'Whole Foods Market' })
    const printed = screen.getByLabelText('Printed date')
    await user.clear(printed)
    await user.type(printed, '20260730123456')
    await user.click(screen.getByRole('button', { name: /approve/i }))
    await screen.findByRole('heading', { name: /stored something different/i })
    // The successful chain cleared the stash on its way into this state.
    expect(restore('t1')).toBeNull()

    await user.type(screen.getByLabelText('Total'), '1')

    expect(restore('t1')).toBeNull()
    expect(hasDirtyEdits()).toBe(false)
  })
})

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
    render(
      <StrictMode>
        <ReviewScreen />
      </StrictMode>,
    )
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
    // Nothing dirty survives the advance. This pins the end state, not the
    // `clearStash()` in the Next receipt handler specifically: see the report's
    // M2 note -- once the `lost` state clears the stash on entry, that call is
    // measurably redundant and deleting it leaves this assertion green.
    expect(restore('t1')).toBeNull()
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
    render(
      <StrictMode>
        <ReviewScreen />
      </StrictMode>,
    )
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
    render(
      <StrictMode>
        <ReviewScreen />
      </StrictMode>,
    )
    await screen.findByLabelText('Total')
    await userEvent.keyboard('{Control>}{Enter}{/Control}')

    await screen.findByText('The database is unavailable — nothing can be saved right now.')
    // The chain can be retried once the database is back: Approve survives.
    expect(screen.getByRole('button', { name: 'Approve (⌘↵)' })).toBeTruthy()
  })

  it('a 503 on the close does not also claim nothing could be saved', async () => {
    // Both sentences render in the same place, and on this one path the first
    // is false: `apply_corrections` commits in its own transaction, so the
    // PATCH landed before `complete` was ever called. Unsuppressed, the screen
    // said "The database is unavailable — nothing can be saved right now."
    // directly above "Saved, but the task is still open: database unavailable",
    // which is a contradiction a reviewer cannot resolve from the screen.
    const fetchMock = stubApi({
      ...DRAINING,
      'POST /review/t1/complete': [503, { error: { message: 'database unavailable' } }],
    })
    vi.stubGlobal('fetch', fetchMock)

    const user = await claimAndEditTheTotal(fetchMock)
    await user.click(screen.getByRole('button', { name: /approve/i }))

    expect((await screen.findByRole('alert')).textContent).toBe(
      'Saved, but the task is still open: database unavailable',
    )
    expect(
      screen.queryByText('The database is unavailable — nothing can be saved right now.'),
    ).toBeNull()
    // The narrow retry is still right to stay: a 503 is transient, and the only
    // thing left to do is close the task.
    expect(screen.getByRole('button', { name: /close task/i })).toBeDefined()
  })

  it('a 503 on load is backend-down and does NOT offer Skip', async () => {
    const fetchMock = stubApi({
      '/review/next': [200, { task: TASK, receipt: SUMMARY }],
      'GET /receipts/a1': [503, { error: { message: 'database unavailable' } }],
    })
    vi.stubGlobal('fetch', fetchMock)
    render(
      <StrictMode>
        <ReviewScreen />
      </StrictMode>,
    )

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
    render(
      <StrictMode>
        <ReviewScreen />
      </StrictMode>,
    )

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
    render(
      <StrictMode>
        <ReviewScreen />
      </StrictMode>,
    )

    await screen.findByRole('alert')
    await userEvent.click(screen.getByRole('button', { name: 'Skip this receipt' }))

    await screen.findByText('The review queue is empty.')
  })

  it('a lost chain leaves nothing dirty behind, before the reviewer advances', async () => {
    // The `approve` half of the same rule. `lost` is reachable only from the
    // `complete` step, so the PATCH landed: these edits are in the database,
    // and ADR-0016 cannot hand this task back to restore them onto -- it
    // resumes only the caller's own `IN_PROGRESS` row, and this one is taken.
    // Design §4.1 clears the stash wherever the write landed; the plan simply
    // omitted the site when it added `lost`. What it costs to omit is not
    // cosmetic: `hasDirtyEdits` is the sign-out gate (design §4.2), so Sign
    // out demanded confirmation over edits that confirming cannot recover.
    //
    // Asserted before any `Next receipt` click, because that handler clears
    // the stash too and would make the omission invisible.
    const fetchMock = stubApi({
      ...DRAINING,
      'POST /review/t1/complete': [
        403,
        { error: { message: 'only the assignee or an admin may complete this task' } },
      ],
    })
    vi.stubGlobal('fetch', fetchMock)

    const user = await claimAndEditTheTotal(fetchMock)
    // The edit is stashed while the chain can still be retried, so the clear
    // below is a transition and not a state that was always empty.
    expect(hasDirtyEdits()).toBe(true)

    await user.click(screen.getByRole('button', { name: /approve/i }))
    await screen.findByRole('heading', {
      name: 'Saved, but this task was taken over by someone else',
    })

    expect(restore('t1')).toBeNull()
    expect(hasDirtyEdits()).toBe(false)
    // Still on screen and still editable, which is why the stash has to be
    // cleared rather than left to the advance: this is where a reviewer sits.
    expect(screen.getByLabelText('Total')).toBeDefined()
  })

  it('a Close task that finds the task taken lands in the same terminal state', async () => {
    // `closeTaskOnly`'s own `lost` branch, which nothing reached before. It is
    // not a hypothetical: a 500 on the chain's `complete` is retryable, and it
    // is exactly the state that renders `Close task` -- so between that render
    // and the click, an admin can take the task or delete it. Reaching the dead
    // end by the narrower button has to read the same as reaching it by the
    // chain, because it *is* the same dead end.
    const fetchMock = stubApi({
      ...DRAINING,
      'POST /review/t1/complete': [
        [500, { error: { message: 'the task could not be closed' } }],
        [403, { error: { message: 'only the assignee or an admin may complete this task' } }],
      ],
    })
    vi.stubGlobal('fetch', fetchMock)

    const user = await claimAndEditTheTotal(fetchMock)
    await user.click(screen.getByRole('button', { name: /approve/i }))

    // First stop: the PATCH landed, the task is still open, and the narrow
    // retry is offered -- a 500 is not forever.
    expect((await screen.findByRole('alert')).textContent).toBe(
      'Saved, but the task is still open: the task could not be closed',
    )
    // The stash still holds the edits here, and rightly: this failure is
    // retryable, so they are still worth something.
    expect(hasDirtyEdits()).toBe(true)
    await user.click(screen.getByRole('button', { name: /close task/i }))

    // Second stop: it is forever now.
    expect(
      await screen.findByRole('heading', {
        name: 'Saved, but this task was taken over by someone else',
      }),
    ).toBeDefined()
    expect(screen.getByText('only the assignee or an admin may complete this task')).toBeDefined()
    // And now it is empty -- as the terminal state renders, before the advance
    // that would otherwise clear it and hide the omission. The patch landed, so
    // these edits are in the database and the overlay can restore nothing.
    expect(restore('t1')).toBeNull()
    expect(hasDirtyEdits()).toBe(false)
    // Neither retry survives: both could only fail identically from here.
    expect(screen.queryByRole('button', { name: /close task/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /approve/i })).toBeNull()

    // One exit, and it advances without sending anything more.
    await user.click(screen.getByRole('button', { name: /next receipt/i }))
    expect(await screen.findByText(/review queue is empty/i)).toBeDefined()
    expect(chain(fetchMock).filter((call) => call === 'PATCH /receipts/a1')).toHaveLength(1)
    expect(chain(fetchMock).filter((call) => call === 'POST /review/t1/complete')).toHaveLength(2)
  })
})

describe('a refused field, beside the field', () => {
  it('a value-quoting 400 lands beside the field that sent it, and the summary stays', async () => {
    const fetchMock = stubApi({
      '/review/next': [200, { task: TASK, receipt: SUMMARY }],
      'GET /receipts/a1': [200, RECEIPT],
      'PATCH /receipts/a1': [400, { error: { message: "not a decimal amount: 'abc'" } }],
    })
    vi.stubGlobal('fetch', fetchMock)
    render(
      <StrictMode>
        <ReviewScreen />
      </StrictMode>,
    )
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
})
