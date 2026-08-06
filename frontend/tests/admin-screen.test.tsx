import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AdminScreen } from '../src/admin/AdminScreen'
import { StatTiles } from '../src/admin/StatTiles'
import { TaskTable } from '../src/admin/TaskTable'
import { currentRoute } from '../src/route'
import type { Identity, Metrics } from '../src/api/admin'
import type { ReviewTask } from '../src/api/types'

// `globals: true` is deliberately absent from vite.config.ts, so
// `@testing-library/react` never installs its auto-cleanup hook and every render
// here has to be unmounted by this file.
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

/** Design section 4's mark, byte for byte: U+2014 EM DASH. Spelled once so a
 *  test cannot pass against a different glyph than the one `ui/Value` renders. */
const MARK = '—'

// --------------------------------------------------------------------------- //
// Fixtures
// --------------------------------------------------------------------------- //

const ADMIN: Identity = { username: 'root', role: 'admin' }
const REVIEWER: Identity = { username: 'alice', role: 'reviewer' }

/** A task held by somebody who is not the caller -- the row the release action
 *  exists for (ADR-0025: the reviewer who stopped polling). */
const HELD: ReviewTask = {
  id: 't1',
  receipt_id: 'a1',
  reason: 'full re-key',
  priority: 1,
  assigned_to: 'carol',
  state: 'in_progress',
  opened_at: '2026-08-06T09:00:00+00:00',
  closed_at: null,
}

/** The same task after `POST /review/{id}/release`: state back to open, the
 *  assignee cleared, and the prior holder handed back beside it. Measured at
 *  `review_release` in src/receipts/review/api.py -- the body is
 *  `{**_task_summary(task), "released_from": released_from}`, the WHOLE summary
 *  plus that one field, which is what lets the screen update the row without a
 *  second listing call. */
const RELEASED = { ...HELD, assigned_to: null, state: 'open', released_from: 'carol' }

/** An unclaimed row. `assigned_to` is null and must render the mark, never a
 *  blank cell -- an empty cell reads as "assigned to nobody in particular"
 *  rather than "nobody has claimed this" (design section 5.6). */
const UNCLAIMED: ReviewTask = {
  id: 't2',
  receipt_id: 'a2',
  reason: 'quick verify',
  priority: 2,
  assigned_to: null,
  state: 'open',
  opened_at: '2026-08-06T10:00:00+00:00',
  closed_at: null,
}

const METRICS: Metrics = {
  counts_by_status: { auto_approved: 3, needs_review: 1, reviewed: 2 },
  auto_approval_rate: '0.500',
  queue: { open: 2, in_progress: 1, done: 4, total: 7, by_priority: { '1': 1, '2': 1 } },
  thresholds: { auto_approve: '0.850', review: '0.600' },
}

/** A fixed clock, so an age column is a value and not a race. */
const NOW = Date.parse('2026-08-06T11:30:00+00:00')

// --------------------------------------------------------------------------- //
// A `fetch` that answers by path, in the shape review-screen.test.tsx uses
// --------------------------------------------------------------------------- //

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

type Reply = readonly [number, unknown]

/** `fetch`, answering by method and **pathname** -- the query string is dropped
 *  for matching and kept in `mock.calls`, because `/review/tasks` is requested
 *  with parameters and a stub keyed on the whole URL would silently 404 the
 *  moment a parameter was added. An unstubbed path answers 404 naming itself, so
 *  a request the screen was not supposed to make is a readable failure rather
 *  than an undefined body. */
function stubApi(routes: Record<string, Reply>) {
  return vi.fn((url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    const path = url.split('?')[0]
    const reply = routes[`${method} ${path}`] ?? routes[path]
    if (reply === undefined) {
      return Promise.resolve(
        jsonResponse(404, { error: { message: `no stub for ${method} ${url}` } }),
      )
    }
    return Promise.resolve(jsonResponse(reply[0], reply[1]))
  })
}

function callsTo(fetchMock: ReturnType<typeof stubApi>, path: string): string[] {
  return fetchMock.mock.calls.map(([url]) => String(url)).filter((url) => url.split('?')[0] === path)
}

/** Every call as `METHOD /path`, in order -- what a failure should print. */
function chain(fetchMock: ReturnType<typeof stubApi>): string[] {
  return fetchMock.mock.calls.map(
    ([url, init]) => `${(init as RequestInit | undefined)?.method ?? 'GET'} ${String(url)}`,
  )
}

// --------------------------------------------------------------------------- //
// Reading the table by its own headers rather than by a hard-coded index
// --------------------------------------------------------------------------- //

/** The index of the column headed `header`, read off the rendered `<thead>`.
 *
 * A hard-coded `cells[2]` silently follows a reordered column onto the wrong
 * data and goes on passing; this throws instead, and names the columns it did
 * find, so a renamed header is a readable failure. */
function columnIndex(table: HTMLElement, header: string): number {
  const headers = [...table.querySelectorAll('thead th')].map((th) => th.textContent?.trim() ?? '')
  const index = headers.indexOf(header)
  if (index === -1) {
    throw new Error(`no column headed "${header}"; the columns are: ${headers.join(' | ')}`)
  }
  return index
}

function cellUnder(row: HTMLTableRowElement, table: HTMLElement, header: string): HTMLElement {
  return row.cells[columnIndex(table, header)]
}

/** The body rows, so a header row is never mistaken for data. */
function bodyRows(table: HTMLElement): HTMLTableRowElement[] {
  return [...table.querySelectorAll<HTMLTableRowElement>('tbody tr')]
}

// --------------------------------------------------------------------------- //
// The pathname switch
// --------------------------------------------------------------------------- //

describe('the route switch, which is deliberately not a router', () => {
  it('maps each of the three paths', () => {
    expect(currentRoute('/app/login')).toBe('login')
    expect(currentRoute('/app/admin')).toBe('admin')
    expect(currentRoute('/app/review')).toBe('review')
  })

  it('keeps the admin route across a trailing slash, and defaults everything else', () => {
    // The backend serves a history fallback (`_SpaFiles(..., html=True)`), so
    // `/app/admin` and `/app/admin/` are both real reload targets.
    expect(currentRoute('/app/admin/')).toBe('admin')
    expect(currentRoute('/app/')).toBe('review')
    expect(currentRoute('/')).toBe('review')
    expect(currentRoute('/app/anything-else')).toBe('review')
  })

  it('reads the live pathname when it is given none', () => {
    window.history.pushState({}, '', '/app/admin')
    try {
      expect(currentRoute()).toBe('admin')
    } finally {
      window.history.pushState({}, '', '/')
    }
  })

  it('declares no client-side path whose last segment carries a dot', () => {
    // `main.tsx`'s docstring records the rule and the reason: the mount only
    // falls back to the SPA shell when the last segment has no file extension
    // (`_names_a_file` in src/receipts/review/api.py), so `/app/receipt/inv.01`
    // is served as a missing *file* and 404s. Quantified over the literal paths
    // the module actually declares rather than over a list retyped here, so a
    // fourth route is covered the day it is added.
    const source = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', 'src', 'route.ts'), 'utf8')
    const paths = [...source.matchAll(/'(\/app\/[^']*)'/g)].map((match) => match[1])
    expect(paths.length, 'route.ts declares no /app/ path literal at all').toBeGreaterThan(0)
    const withDots = paths.filter((path) => {
      const segments = path.split('/').filter((segment) => segment !== '')
      return (segments[segments.length - 1] ?? '').includes('.')
    })
    expect(withDots).toEqual([])
  })
})

// --------------------------------------------------------------------------- //
// The table: the empty state's scope, and the null rule
// --------------------------------------------------------------------------- //

describe('design section 5.6 -- the empty state names the scope that is empty', () => {
  it('tells an admin there is nothing at all', () => {
    render(
      <TaskTable tasks={[]} scope="all" canRelease onRelease={() => {}} busyTaskId={null} now={NOW} />,
    )

    expect(screen.getByText('No tasks')).toBeDefined()
  })

  it('tells a reviewer which list is empty, not that the queue is broken', () => {
    // ADR-0026: a reviewer sees `state == OPEN` OR `assigned_to == <caller>`, so
    // a bare "No tasks" over a *filtered* page states something the server never
    // said. The two roles get different rows from the same endpoint, and the
    // empty state is the only place the page can say so.
    render(
      <TaskTable
        tasks={[]}
        scope="mine"
        canRelease={false}
        onRelease={() => {}}
        busyTaskId={null}
        now={NOW}
      />,
    )

    expect(screen.getByText('No open tasks, and none assigned to you')).toBeDefined()
    expect(screen.queryByText('No tasks')).toBeNull()
  })
})

describe('design section 4 reaches the task rows', () => {
  it('marks an unclaimed row rather than leaving the cell blank', () => {
    const { container } = render(
      <TaskTable
        tasks={[UNCLAIMED]}
        scope="all"
        canRelease
        onRelease={() => {}}
        busyTaskId={null}
        now={NOW}
      />,
    )

    const table = within(container).getByRole('table')
    const [row] = bodyRows(table)
    const cell = cellUnder(row, table, 'Assigned to')
    // Through the accessibility tree, not through the attribute: a bare `<span>`
    // is `role=generic`, for which ARIA 1.2 prohibits naming, and
    // `getByLabelText` would pass without the role ever reaching a reader.
    expect(within(cell).getByRole('img', { name: 'not extracted' })).toBeDefined()
    expect(cell.textContent).toContain(MARK)
  })

  it('does not paint the mark over a real assignee', () => {
    const { container } = render(
      <TaskTable
        tasks={[HELD]}
        scope="all"
        canRelease
        onRelease={() => {}}
        busyTaskId={null}
        now={NOW}
      />,
    )

    const table = within(container).getByRole('table')
    const cell = cellUnder(bodyRows(table)[0], table, 'Assigned to')
    expect(cell.textContent).toContain('carol')
    expect(within(cell).queryByRole('img', { name: 'not extracted' })).toBeNull()
  })

  it('names the state and the priority in words, never in colour alone', () => {
    // Accessibility contract section 6, High severity: severity, confidence band
    // and task state each carry an icon AND a word.
    const { container } = render(
      <TaskTable
        tasks={[HELD, UNCLAIMED]}
        scope="all"
        canRelease
        onRelease={() => {}}
        busyTaskId={null}
        now={NOW}
      />,
    )

    const table = within(container).getByRole('table')
    const [held, unclaimed] = bodyRows(table)
    expect(cellUnder(held, table, 'State').textContent).toContain('In progress')
    expect(cellUnder(unclaimed, table, 'State').textContent).toContain('Open')
    expect(cellUnder(held, table, 'Priority').textContent).toContain('Full re-key')
    expect(cellUnder(unclaimed, table, 'Priority').textContent).toContain('Quick verify')
  })

  it('marks an age it cannot compute instead of printing NaN', () => {
    const broken = { ...UNCLAIMED, opened_at: 'not a timestamp' }
    const { container } = render(
      <TaskTable
        tasks={[broken]}
        scope="all"
        canRelease
        onRelease={() => {}}
        busyTaskId={null}
        now={NOW}
      />,
    )

    const table = within(container).getByRole('table')
    const cell = cellUnder(bodyRows(table)[0], table, 'Age')
    expect(within(cell).getByRole('img', { name: 'not extracted' })).toBeDefined()
    expect(cell.textContent).not.toContain('NaN')
  })

  it('computes an age against the clock it is given', () => {
    const { container } = render(
      <TaskTable
        tasks={[HELD]}
        scope="all"
        canRelease
        onRelease={() => {}}
        busyTaskId={null}
        now={NOW}
      />,
    )

    const table = within(container).getByRole('table')
    // 09:00 to 11:30 is two and a half hours.
    expect(cellUnder(bodyRows(table)[0], table, 'Age').textContent).toContain('2h')
  })

  it('offers no release control at all when the caller may not release', () => {
    render(
      <TaskTable
        tasks={[HELD]}
        scope="mine"
        canRelease={false}
        onRelease={() => {}}
        busyTaskId={null}
        now={NOW}
      />,
    )

    expect(screen.queryByRole('button', { name: /release/i })).toBeNull()
  })
})

// --------------------------------------------------------------------------- //
// The tiles: null is not zero, and zero is not null
// --------------------------------------------------------------------------- //

describe('design section 5.7 -- a rate that was never defined is not zero', () => {
  it('marks an undefined auto-approval rate rather than reporting 0', () => {
    // `auto_approval_rate` is `str | None` and the API was deliberately built
    // that way: `denominator == 0` yields None, not a confident 0 or 1.0. A UI
    // that renders that as `0%` destroys the distinction at the last inch.
    render(<StatTiles metrics={{ ...METRICS, auto_approval_rate: null }} />)

    const tiles = screen.getByRole('region', { name: 'Queue statistics' })
    expect(within(tiles).getByRole('img', { name: 'not extracted' })).toBeDefined()
    expect(within(tiles).queryByText('0%')).toBeNull()
    expect(within(tiles).queryByText('0')).toBeNull()
    expect(within(tiles).queryByText('0.000')).toBeNull()
  })

  it('renders a rate that really is zero as zero, and marks nothing', () => {
    render(<StatTiles metrics={{ ...METRICS, auto_approval_rate: '0.000' }} />)

    const tiles = screen.getByRole('region', { name: 'Queue statistics' })
    expect(within(tiles).getByText('0.000')).toBeDefined()
    expect(within(tiles).queryByRole('img', { name: 'not extracted' })).toBeNull()
  })

  it('renders an empty queue as 0 and not as the mark', () => {
    render(
      <StatTiles
        metrics={{ ...METRICS, queue: { open: 0, in_progress: 0, done: 0, total: 0, by_priority: {} } }}
      />,
    )

    const tiles = screen.getByRole('region', { name: 'Queue statistics' })
    expect(within(tiles).getAllByText('0')).toHaveLength(3)
    expect(within(tiles).queryByRole('img', { name: 'not extracted' })).toBeNull()
  })

  it('marks a count the body did not carry rather than printing undefined', () => {
    // `request<T>` is an unchecked cast, so a body missing a key arrives as
    // `undefined` and would render as nothing at all.
    const partial = { ...METRICS, queue: { total: 7, by_priority: {} } } as unknown as Metrics
    render(<StatTiles metrics={partial} />)

    const tiles = screen.getByRole('region', { name: 'Queue statistics' })
    expect(within(tiles).getAllByRole('img', { name: 'not extracted' })).toHaveLength(3)
    expect(tiles.textContent).not.toContain('undefined')
  })
})

// --------------------------------------------------------------------------- //
// The screen: the release round trip, and the two failures it can meet
// --------------------------------------------------------------------------- //

describe('the admin screen drives POST /review/{id}/release', () => {
  it('lets an admin release a task assigned to somebody else', async () => {
    const fetchMock = stubApi({
      'GET /review/tasks': [200, { items: [HELD], has_more: false }],
      'GET /metrics': [200, METRICS],
      'POST /review/t1/release': [200, RELEASED],
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<AdminScreen identity={ADMIN} now={NOW} />)

    const table = await screen.findByRole('table')
    expect(cellUnder(bodyRows(table)[0], table, 'Assigned to').textContent).toContain('carol')

    // The confirm is inline and names the current holder: this is a destructive
    // act on somebody else's work (design section 5.6).
    await user.click(within(table).getByRole('button', { name: 'Release' }))
    expect(within(table).getByText(/carol/)).toBeDefined()
    await user.click(within(table).getByRole('button', { name: 'Release from carol' }))

    await waitFor(() => {
      expect(callsTo(fetchMock, '/review/t1/release'), chain(fetchMock).join(' | ')).toHaveLength(1)
    })

    // The row is updated from the release response, which carries the whole task
    // summary and not just `released_from` -- so there is no second listing call.
    await waitFor(() => {
      const row = bodyRows(screen.getByRole('table'))[0]
      expect(cellUnder(row, screen.getByRole('table'), 'State').textContent).toContain('Open')
    })
    const row = bodyRows(screen.getByRole('table'))[0]
    const assignee = cellUnder(row, screen.getByRole('table'), 'Assigned to')
    expect(within(assignee).getByRole('img', { name: 'not extracted' })).toBeDefined()
    expect(callsTo(fetchMock, '/review/tasks'), chain(fetchMock).join(' | ')).toHaveLength(1)
  })

  it('reports a 403 instead of assuming the row went away', async () => {
    // The route is guarded by `Depends(require_role(ROLE_ADMIN))` and the role is
    // re-read per request (ADR-0012), so a caller whose account was demoted
    // between `/auth/me` and the click gets 403 -- not an empty list.
    const fetchMock = stubApi({
      'GET /review/tasks': [200, { items: [HELD], has_more: false }],
      'GET /metrics': [200, METRICS],
      'POST /review/t1/release': [403, { error: { message: 'requires role admin' } }],
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<AdminScreen identity={ADMIN} now={NOW} />)

    const table = await screen.findByRole('table')
    await user.click(within(table).getByRole('button', { name: 'Release' }))
    await user.click(within(table).getByRole('button', { name: 'Release from carol' }))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('requires role admin')
    // The task is still held. A screen that dropped or blanked the row would be
    // reporting a release that the server refused.
    const after = bodyRows(screen.getByRole('table'))[0]
    expect(cellUnder(after, screen.getByRole('table'), 'Assigned to').textContent).toContain('carol')
    expect(cellUnder(after, screen.getByRole('table'), 'State').textContent).toContain('In progress')
  })

  it('gives a reviewer their scoped empty state, not a bare one', async () => {
    const fetchMock = stubApi({
      'GET /review/tasks': [200, { items: [], has_more: false }],
      'GET /metrics': [200, METRICS],
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<AdminScreen identity={REVIEWER} now={NOW} />)

    expect(await screen.findByText('No open tasks, and none assigned to you')).toBeDefined()
    expect(screen.queryByText('No tasks')).toBeNull()
  })

  it('gives an admin the unscoped empty state', async () => {
    const fetchMock = stubApi({
      'GET /review/tasks': [200, { items: [], has_more: false }],
      'GET /metrics': [200, METRICS],
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<AdminScreen identity={ADMIN} now={NOW} />)

    expect(await screen.findByText('No tasks')).toBeDefined()
  })

  it('offers a reviewer no release control, and says why', async () => {
    const fetchMock = stubApi({
      'GET /review/tasks': [200, { items: [HELD], has_more: false }],
      'GET /metrics': [200, METRICS],
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<AdminScreen identity={REVIEWER} now={NOW} />)

    await screen.findByRole('table')
    expect(screen.queryByRole('button', { name: /release/i })).toBeNull()
    expect(screen.getByText(/only an admin can release/i)).toBeDefined()
  })

  it('refuses to render a list it cannot scope', async () => {
    // Identity unknown means the *scope* is unknown, and an empty state that
    // cannot say which list is empty is the failure ADR-0026 names. So the
    // screen asks for nothing at all until it knows who it is talking to.
    const fetchMock = stubApi({
      'GET /review/tasks': [200, { items: [HELD], has_more: false }],
      'GET /metrics': [200, METRICS],
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<AdminScreen identity={null} now={NOW} />)

    expect(screen.queryByRole('table')).toBeNull()
    expect(callsTo(fetchMock, '/review/tasks')).toEqual([])
    expect(screen.getByText(/identity/i)).toBeDefined()
  })

  it('says so when the listing itself fails, rather than showing an empty queue', async () => {
    const fetchMock = stubApi({
      'GET /review/tasks': [500, { error: { message: 'the database is unavailable' } }],
      'GET /metrics': [200, METRICS],
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<AdminScreen identity={ADMIN} now={NOW} />)

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('the database is unavailable')
    expect(screen.queryByText('No tasks')).toBeNull()
  })

  it('says a page was truncated instead of silently showing the first page', async () => {
    const fetchMock = stubApi({
      'GET /review/tasks': [200, { items: [HELD], has_more: true }],
      'GET /metrics': [200, METRICS],
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<AdminScreen identity={ADMIN} now={NOW} />)

    await screen.findByRole('table')
    expect(screen.getByText(/more tasks/i)).toBeDefined()
  })
})

// --------------------------------------------------------------------------- //
// The API module
// --------------------------------------------------------------------------- //

describe('api/admin sends what the routes actually accept', () => {
  it('sends the state filter in the wire spelling, which is lower case', async () => {
    // `ReviewState` is `open` / `in_progress` / `done` (persist/models.py).
    // ADR-0026's prose says `state == OPEN`; sending "OPEN" is a 422, not an
    // empty list.
    const fetchMock = stubApi({ 'GET /review/tasks': [200, { items: [], has_more: false }] })
    vi.stubGlobal('fetch', fetchMock)
    const { fetchTasks } = await import('../src/api/admin')

    await fetchTasks({ state: 'in_progress', limit: 10, offset: 20 })

    const [url] = callsTo(fetchMock, '/review/tasks')
    expect(url).toContain('state=in_progress')
    expect(url).toContain('limit=10')
    expect(url).toContain('offset=20')
    expect(url).not.toContain('IN_PROGRESS')
  })

  it('sends no query string at all when given no parameters', async () => {
    const fetchMock = stubApi({ 'GET /review/tasks': [200, { items: [], has_more: false }] })
    vi.stubGlobal('fetch', fetchMock)
    const { fetchTasks } = await import('../src/api/admin')

    await fetchTasks()

    expect(callsTo(fetchMock, '/review/tasks')).toEqual(['/review/tasks'])
  })

  it('posts the release to the task id it was given', async () => {
    const fetchMock = stubApi({ 'POST /review/t1/release': [200, RELEASED] })
    vi.stubGlobal('fetch', fetchMock)
    const { releaseTask } = await import('../src/api/admin')

    const released = await releaseTask('t1')

    // The whole summary comes back, not just `released_from`.
    expect(released.released_from).toBe('carol')
    expect(released.assigned_to).toBeNull()
    expect(released.state).toBe('open')
    expect(released.id).toBe('t1')
  })
})

// --------------------------------------------------------------------------- //
// The session's identity, and the 401 that arrives through it
// --------------------------------------------------------------------------- //

describe('the session holds an identity, hydrated from GET /auth/me', () => {
  /** A fresh module graph per test: `session.ts` and `client.ts` both hold
   *  module state, and an identity set by one test must not leak into the next.
   *  The same shape `session.test.ts` uses. */
  async function freshSession() {
    vi.resetModules()
    return await import('../src/session')
  }

  beforeEach(() => {
    vi.unstubAllGlobals()
  })

  it('starts with no identity at all -- not with a guess', async () => {
    const session = await freshSession()
    expect(session.currentIdentity()).toBeNull()
  })

  it('replaces the pathname guess with the answer from the server', async () => {
    vi.stubGlobal('fetch', stubApi({ 'GET /auth/me': [200, ADMIN] }))
    const session = await freshSession()

    await session.hydrateIdentity()

    expect(session.currentIdentity()).toEqual(ADMIN)
  })

  it('notifies subscribers when the identity arrives', async () => {
    vi.stubGlobal('fetch', stubApi({ 'GET /auth/me': [200, ADMIN] }))
    const session = await freshSession()
    const listener = vi.fn()
    session.subscribe(listener)

    await session.hydrateIdentity()

    expect(listener).toHaveBeenCalled()
  })

  it('resolves rather than rejecting when the call fails outright', async () => {
    // `ErrorBoundary` catches a throw during *render*; it never sees a rejected
    // promise. An unhandled rejection here would surface as a console error in
    // production and as a failed run under Vitest.
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    const session = await freshSession()

    await expect(session.hydrateIdentity()).resolves.toBeUndefined()
    expect(session.currentIdentity()).toBeNull()
  })

  it('takes the 401 as the sign-out it is, and still does not reject', async () => {
    // `GET /auth/me` answers 401 when signed out (ADR-0026 decision 1) and
    // `request` calls the global handler *and then throws*. The side effect is
    // what corrects the pathname guess; the throw has to be caught deliberately.
    vi.stubGlobal(
      'fetch',
      stubApi({ 'GET /auth/me': [401, { error: { message: 'authentication required' } }] }),
    )
    const session = await freshSession()
    expect(session.isSignedIn()).toBe(true)

    await expect(session.hydrateIdentity()).resolves.toBeUndefined()

    expect(session.isSignedIn()).toBe(false)
    expect(session.currentIdentity()).toBeNull()
  })

  it('clears the identity when any 401 arrives, not only /auth/me s', async () => {
    vi.stubGlobal('fetch', stubApi({ 'GET /auth/me': [200, ADMIN] }))
    const session = await freshSession()
    await session.hydrateIdentity()
    expect(session.currentIdentity()).toEqual(ADMIN)

    const { request, ApiError } = await import('../src/api/client')
    vi.stubGlobal(
      'fetch',
      stubApi({ '/receipts': [401, { error: { message: 'authentication required' } }] }),
    )
    await expect(request('/receipts')).rejects.toBeInstanceOf(ApiError)

    expect(session.currentIdentity()).toBeNull()
    expect(session.isSignedIn()).toBe(false)
  })
})

// --------------------------------------------------------------------------- //
// The class-name guard: under `css: false` nothing else can see a typo
// --------------------------------------------------------------------------- //

describe('every class the admin components reference exists in its stylesheet', () => {
  // Under Vitest's `css: false` a `.module.css` import is a proxy whose keys echo
  // back as strings, so `styles.tille` renders `class="undefined"` and every
  // rendering test above still passes. Anything about the CSS itself therefore
  // has to be read off the file, exactly as `tests/review-null-rule.test.tsx` and
  // `tests/value.test.tsx` read theirs.
  //
  // `dirname(fileURLToPath(import.meta.url))` rather than
  // `new URL(specifier, import.meta.url)`: Vite rewrites that *pattern* into a
  // static-asset import and refuses outright for a `.module.css` specifier with
  // `?url is not supported with CSS modules`.
  const ADMIN_SRC = join(dirname(fileURLToPath(import.meta.url)), '..', 'src', 'admin')

  function readAdminFile(relative: string): string {
    try {
      return readFileSync(join(ADMIN_SRC, relative), 'utf8')
    } catch (cause) {
      throw new Error(
        `a guard in this file cannot read src/admin/${relative}. If that file moved ` +
          `or was renamed, update this path -- the guard is not optional cover.`,
        { cause },
      )
    }
  }

  const GUARDED = [
    { tsx: 'AdminScreen.tsx', css: 'AdminScreen.module.css' },
    { tsx: 'TaskTable.tsx', css: 'TaskTable.module.css' },
    { tsx: 'StatTiles.tsx', css: 'StatTiles.module.css' },
  ] as const

  /** Class selectors a stylesheet declares, comments stripped first -- these
   *  files document the rules they contain, and prose must not answer for code. */
  function declaredClasses(css: string): Set<string> {
    const source = css.replace(/\/\*[\s\S]*?\*\//g, '')
    return new Set(Array.from(source.matchAll(/\.([A-Za-z][\w-]*)/g), (m) => m[1]))
  }

  /** `styles.foo` references a component makes, comments stripped for the same
   *  reason: every one of these files names its own classes in prose. */
  function referencedClasses(tsx: string): Set<string> {
    const source = tsx.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1')
    return new Set(Array.from(source.matchAll(/\bstyles\.([A-Za-z][\w-]*)/g), (m) => m[1]))
  }

  it('extracts from both sides, and is not fooled by a comment', () => {
    expect(declaredClasses('.real { color: red }').has('real')).toBe(true)
    expect(declaredClasses('/* .ghost {} */ .real {}').has('ghost')).toBe(false)
    expect(referencedClasses('x = styles.real').has('real')).toBe(true)
    expect(referencedClasses('/* styles.ghost */ x = styles.real').has('ghost')).toBe(false)
  })

  it('declares every class the three components reach', () => {
    for (const { tsx, css } of GUARDED) {
      const declared = declaredClasses(readAdminFile(css))
      const referenced = referencedClasses(readAdminFile(tsx))
      expect(referenced.size, `${tsx} references no styles.*`).toBeGreaterThan(0)
      const missing = [...referenced].filter((name) => !declared.has(name))
      expect(missing, `${tsx} reaches classes ${css} does not declare`).toEqual([])
    }
  })
})
