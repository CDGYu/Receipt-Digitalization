import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { HomeScreen } from '../src/home/HomeScreen'

/** The landing screen, as a person meets it on opening the app.
 *
 * Until this existed `/app/` was the review queue, because `route.ts` returned
 * `review` for every path it did not recognise. A signed-in person with an
 * empty queue therefore opened the app onto the words "The review queue is
 * empty." and no way forward -- the dead end this screen replaces.
 *
 * The counts come from `GET /metrics`, which `AdminScreen` already reads; this
 * screen reuses `fetchMetrics` rather than restating the shape.
 *
 * Nothing here asserts a class name: Vitest runs with `css: false`, so a
 * `.module.css` import echoes its keys back and a renamed class ships
 * unpainted while every render test stays green. The last test in
 * this file is the one that can see that, and it reads both files as text.
 */

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function metricsResponse(queue: Record<string, unknown>, body: Record<string, unknown> = {}): Response {
  return new Response(
    JSON.stringify({
      counts_by_status: {},
      auto_approval_rate: null,
      queue: { open: 0, in_progress: 0, done: 0, total: 0, by_priority: {}, ...queue },
      thresholds: { auto_approve: '0.85', review: '0.60' },
      ...body,
    }),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  )
}

describe('HomeScreen', () => {
  it('offers a way into every screen the work runs through', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(metricsResponse({}))))
    render(<HomeScreen />)

    // Matched on the *start* of the accessible name, because each link carries
    // its hint inside it: the name really is "Upload a receipt One photograph
    // at a time...", which is what a screen reader should hear. An `aria-label`
    // of just the label would read shorter and hide the hint from assistive
    // technology entirely, which is the worse trade.
    expect(
      (await screen.findByRole('link', { name: /^Upload a receipt/ })).getAttribute('href'),
    ).toBe('/app/upload')
    expect(screen.getByRole('link', { name: /^Review the queue/ }).getAttribute('href')).toBe(
      '/app/review',
    )
    expect(screen.getByRole('link', { name: /^Processed receipts/ }).getAttribute('href')).toBe(
      '/app/receipts',
    )
  })
})

describe('the queue depth', () => {
  it('shows what GET /metrics reports', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(metricsResponse({ open: 4, in_progress: 2, done: 9 }))),
    )
    render(<HomeScreen />)

    // `StatTiles` renders these now, under its own landmark. This screen used
    // to restate three of its four tiles in its own markup -- without the
    // auto-approval rate, and without `Value`'s null handling, so a null rate
    // read as the word "null" here and as an em dash on the admin screen.
    //
    // Re-found INSIDE `waitFor` rather than captured before it. The old version
    // captured the `Queue depth` region -- which only exists while `metrics` is
    // null -- and then asserted against that detached element forever, so it
    // reported `expected 'Reading the queue...' to contain 'Open4'` no matter
    // what the fetch returned.
    await waitFor(() => {
      const tiles = screen.getByRole('region', { name: 'Queue statistics' })
      expect(tiles.textContent).toContain('Open backlog4')
      expect(tiles.textContent).toContain('In progress2')
      expect(tiles.textContent).toContain('Done9')
    })
  })

  it('names the confidence line the auto-approval rate is a rate against', async () => {
    // A percentage with no threshold beside it cannot be acted on: raising the
    // bar lowers the rate, and that trade is the decision this screen informs.
    // Both numbers come from the response, so this cannot pass by agreeing with
    // a constant it also supplies.
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(metricsResponse({}, { thresholds: { auto_approve: '0.91', review: '0.55' } })),
      ),
    )
    render(<HomeScreen />)

    const panel = await screen.findByRole('region', { name: 'Where the confidence line sits' })
    expect(panel.textContent).toContain('0.91')
    expect(panel.textContent).toContain('0.55')
  })

  it('lists the statuses that have receipts, commonest first, and drops the empty ones', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          metricsResponse({}, { counts_by_status: { needs_review: 3, reviewed: 11, failed: 0 } }),
        ),
      ),
    )
    render(<HomeScreen />)

    const panel = await screen.findByRole('region', { name: 'Receipts by status' })
    const rows = panel.textContent ?? ''
    // Commonest first: `reviewed` (11) before `needs_review` (3). Object key
    // order would have given the opposite, so this fails if the sort goes.
    expect(rows.indexOf('reviewed')).toBeLessThan(rows.indexOf('needs review'))
    // A zero is not information on a landing screen, and six zeroes would bury
    // the two rows that matter.
    expect(rows).not.toContain('failed')
  })

  it('says the receipts are absent rather than showing an empty list', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(metricsResponse({}))))
    render(<HomeScreen />)

    const panel = await screen.findByRole('region', { name: 'Receipts by status' })
    expect(panel.textContent).toContain('No receipts have been ingested yet.')
  })

  it('says so when the count cannot be read, and still offers the ways forward', async () => {
    // The design decision this pins: the links are static destinations and do
    // not wait for the fetch. A landing screen that hid its navigation behind a
    // failed request would be a worse dead end than the review queue it
    // replaced -- which is the whole reason this screen exists.
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          new Response(JSON.stringify({ error: { message: 'metrics are down' } }), {
            status: 500,
            headers: { 'Content-Type': 'application/json' },
          }),
        ),
      ),
    )
    render(<HomeScreen />)

    expect(await screen.findByText(/The queue count is unavailable/)).toBeTruthy()
    expect(screen.getByRole('link', { name: /^Upload a receipt/ }).getAttribute('href')).toBe(
      '/app/upload',
    )
  })
})

describe('the stylesheet and the component agree', () => {
  it('names no class the stylesheet does not define', () => {
    // Same guard, same reason as `nav.test.tsx`'s: Vitest runs with
    // `css: false`, so a `.module.css` import echoes its keys and a typo ships
    // unpainted with every render test above still green.
    // `value.test.tsx` is explicitly bounded to its own COMPONENTS list, so a
    // new component arrives unguarded unless it brings one.
    const here = dirname(fileURLToPath(import.meta.url))
    const css = readFileSync(join(here, '..', 'src', 'home', 'HomeScreen.module.css'), 'utf8')
    const tsx = readFileSync(join(here, '..', 'src', 'home', 'HomeScreen.tsx'), 'utf8')

    const referenced = [...tsx.matchAll(/styles\.([A-Za-z0-9_]+)/g)].map((m) => m[1])
    expect(referenced.length).toBeGreaterThan(0)

    const defined = new Set(
      [...css.matchAll(/\.([A-Za-z0-9_-]+)(?=[\s,:{])/g)].map((m) => m[1]),
    )

    for (const name of referenced) {
      expect(
        defined.has(name),
        `styles.${name} has no .${name} rule -- it ships unpainted`,
      ).toBe(true)
    }
  })
})

describe('a fetch that never answers', () => {
  it('falls back to its own words when the failure carries none', async () => {
    // The 500 above is an `ApiError` and has a server sentence to show. A
    // rejected fetch -- offline, DNS, a dropped connection -- is a `TypeError`
    // with a browser-specific message, so the screen supplies its own. Without
    // this test that fallback string is unreachable by any test in the suite
    // and could be deleted with every gate green.
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))))
    render(<HomeScreen />)

    expect(await screen.findByText(/could not read the queue/)).toBeTruthy()
    expect(screen.getByRole('link', { name: /^Upload a receipt/ }).getAttribute('href')).toBe(
      '/app/upload',
    )
  })
})
