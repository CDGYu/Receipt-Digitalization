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

function metricsResponse(queue: Record<string, unknown>): Response {
  return new Response(
    JSON.stringify({
      counts_by_status: {},
      auto_approval_rate: null,
      queue: { open: 0, in_progress: 0, done: 0, total: 0, by_priority: {}, ...queue },
      thresholds: { auto_approve: '0.85', review: '0.60' },
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

    const counts = await screen.findByRole('region', { name: 'Queue depth' })
    await waitFor(() => {
      expect(counts.textContent).toContain('Open4')
      expect(counts.textContent).toContain('In progress2')
      expect(counts.textContent).toContain('Done9')
    })
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
