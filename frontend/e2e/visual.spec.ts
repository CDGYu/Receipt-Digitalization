import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'
import type { Browser, Locator, Page, Route } from '@playwright/test'
// Typed, not `Record<string, unknown>`. The untyped literal is what let these
// fixtures fall behind the API: `buyer` was added to `ReceiptDetail` and every
// one of them went on omitting it, `tsc -b` compiled them anyway, and
// `fieldsFromReceipt` threw in the browser -- 8 of 15 specs painting the
// load-failure state, with all five gates green. `Money` is a branded string,
// so an amount needs `as Money`; that is the cost, and it is the same pattern
// tests/patch.test.ts and tests/review-screen.test.tsx already use.
import type { Metrics } from '../src/api/admin'
import type { ConfidenceReason, Finding, LineItem, Money, ReceiptDetail, ReviewTask } from '../src/api/types'

/** The browser pass: put every surface on a real screen and record what it looks
 *  like -- plan Task 5, ADR-0027's "a browser pass is part of done".
 *
 * ## This file asserts almost nothing about appearance, on purpose
 *
 * There is **no `toHaveScreenshot`, no snapshot, and no pixel baseline** here,
 * and there must not be one: nothing in this milestone has ever been looked at,
 * so a baseline captured from it would pin whatever is currently broken and turn
 * the first-ever visual review into a regression suite for its own defects. The
 * screenshots are **evidence a human reads**, and the findings live in
 * `docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md`.
 *
 * What this file *does* assert is the two things a screenshot cannot show:
 *
 *   * that each synthetic state was actually **reached** (the right words are on
 *     screen before the shutter opens), and
 *   * that every route stub was actually **hit**. A `page.route` glob that
 *     silently fails to match produces a screenshot of the *real* page, which is
 *     indistinguishable from success at review time and is the one failure mode
 *     that would make this whole exercise report fiction. Every stub carries a
 *     counter and `expectHits` fails the run if one stayed at zero.
 *
 * Measurements that are numbers rather than judgements -- contrast ratios, hit
 * target sizes, horizontal overflow, the focus outline the browser actually
 * computes, whether the money font really has tabular figures -- are taken in
 * the page and written to `var/e2e/visual/measurements.json` beside the images.
 * Most of them are still recorded and asserted nowhere: a threshold for a hit
 * target or a focus ring is a judgement nobody in this repository has made.
 *
 * **Two of them are now asserted, and the reason is a measurement.** The
 * whole-branch review reverted three of Task 5's fixes one at a time and all
 * three left every gate green -- including `.field` going back to `inline-flex`,
 * which puts a 246px money control in a 92px cell, and the dark `--color-null`
 * lift going back to 3.91:1. This file computed `cellOverflow` and 488 contrast
 * ratios per run while both of those were live, and asserted neither. So the
 * floor and the overflow are asserted now, in `assertMeasured`, which explains
 * at length why asserting a *computed number against a documented threshold* is
 * not the pixel baseline this file still refuses to become.
 *
 * **And this file is still not a gate.** `scripts/verify.py` runs five gates and
 * says in as many words that the Playwright run is not one of them, so those two
 * assertions are only as good as somebody choosing to run
 * `npx playwright test visual`. The declaration-level half of the same pin --
 * every rule's declarations, and the token contrast computed from the hex -- is
 * in `tests/stylesheets.test.ts`, which the `vitest` gate does run.
 *
 * ## Interception, and why it is the right tool rather than a compromise
 *
 * `scripts/seed_review_e2e.py` builds one receipt with **no null column**, one
 * reviewer (no admin), two severities (no INFO) and exactly one queued task --
 * and `e2e/review.spec.ts`'s acceptance run depends on every one of those, so
 * the seed is not this task's to change. Meanwhile the five ADR-0024 error
 * states are 503/403/404/400/401 responses that a healthy server does not
 * produce at all. So every synthetic state here is `page.route`d, and only the
 * baseline login and the seeded review screen go through the real API.
 *
 * The stubbed tests never sign in: `session.ts` guesses `signedIn` from the
 * pathname (`window.location.pathname !== '/app/login'`), so navigating straight
 * to `/app/review` renders the screen and every request it makes is one of ours.
 * **`GET /auth/me` must be stubbed on every one of those pages** -- unstubbed it
 * reaches the real server with no cookie, answers 401, and `client.ts` fires the
 * unauthorized handler, which drops the app back to the login form. That is
 * exactly the "screenshot of the wrong page" this file's counters exist to
 * catch, and it was measured while writing it.
 *
 * ## The seeded flow may be entered repeatedly, but never completed
 *
 * `GET /review/next` **resumes before it claims** (ADR-0016, `_resume_stmt` in
 * `queue.py` filters on `assigned_to == <caller>`), so signing in as the seeded
 * reviewer from six fresh browser contexts hands back the same task six times.
 * Nothing here approves, skips or completes anything, so the one queued task
 * survives this file. It does not survive `review.spec.ts`, which closes it --
 * so run this on a fresh seed (`npx playwright test visual` re-seeds, because
 * `webServer.command` chains build, seed and serve and `reuseExistingServer` is
 * false). If the queue is drained the seeded test fails with a sentence saying
 * so rather than photographing the empty state and calling it a review screen.
 *
 * ## Viewport heights are deliberately taller than a real window
 *
 * 375x1400, 1024x1400 and 1440x1400. The widths are the three the plan names and
 * are the only thing the layout keys on (`ReviewScreen.module.css` has one
 * breakpoint, `max-width: 1023px`); the height is stretched so one shot carries
 * enough of a long screen to be worth reading. **Nothing in the report may
 * therefore claim anything about "the fold"** -- one extra capture per width at a
 * realistic 900px is taken for the review screen alone, and only that one can
 * speak to it.
 */

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
const MANIFEST = path.join(REPO_ROOT, 'var', 'e2e', 'seed.json')

/** Under `var/`, which is git-ignored: these are pictures of receipt data and of
 *  a reviewer's screen, and `var/` is the rule that keeps both out of git. */
const SHOTS = path.join(REPO_ROOT, 'var', 'e2e', 'visual')

interface Viewport {
  readonly name: string
  readonly width: number
  readonly height: number
}

const WIDE: Viewport = { name: '1440', width: 1440, height: 1400 }
const MID: Viewport = { name: '1024', width: 1024, height: 1400 }
const TABLET: Viewport = { name: '768', width: 768, height: 1400 }
const NARROW: Viewport = { name: '375', width: 375, height: 1400 }
/** In the order a reader will want them.
 *
 *  **768 is not decoration.** 1024 and 1440 both sit on the wide side of the
 *  layouts' only breakpoint (`max-width: 1023px`), so without it the collapsed
 *  layout is only ever seen at its narrowest -- and a two-pane collapse goes
 *  wrong at 768 in ways that look fine at 375, where everything is stacked
 *  anyway. Added 2026-08-24 for the Editorial refresh's browser pass (design
 *  decision 14). No count is stated here on purpose: a count in prose rots on
 *  the next width somebody adds. */
const ALL_WIDTHS: readonly Viewport[] = [NARROW, TABLET, MID, WIDE]
/** 1024 and 1440 are the same layout -- the grid's only breakpoint is
 *  `max-width: 1023px` -- so the states whose interest is the message rather
 *  than the column count are captured at the two ends only. */
const ENDS: readonly Viewport[] = [NARROW, WIDE]

/** **One theme since the owner's 2026-08-25 ruling.**
 *
 *  This was `['light', 'dark']` and drove fourteen loops below, capturing every
 *  screen twice. `tokens.css` no longer ships a dark palette by either route,
 *  so a `colorScheme: 'dark'` context now renders **exactly the light page** --
 *  every one of those pairs would have been two identical screenshots, one of
 *  them labelled `-dark`, which is worse than not taking it: a reviewer
 *  comparing them would conclude dark mode was fine.
 *
 *  Left as an array rather than collapsed to a scalar so that restoring a theme
 *  is a one-line change here and not a re-write of fourteen call sites. */
const THEMES = ['light'] as const
type Theme = 'light' | 'dark'

interface Fixture {
  readonly db_url: string
  readonly receipt_id: string
  readonly username: string
  readonly password: string
}

// ---------------------------------------------------------------------------
// Synthetic data
// ---------------------------------------------------------------------------

const TASK_ID = '3f1b7c52-0000-4000-8000-000000000001'
const RECEIPT_ID = '3f1b7c52-0000-4000-8000-000000000002'

function task(overrides: Partial<ReviewTask> = {}): ReviewTask {
  return {
    id: TASK_ID,
    receipt_id: RECEIPT_ID,
    reason: 'needs_review',
    priority: 1,
    assigned_to: 'alice',
    state: 'in_progress',
    opened_at: new Date(Date.now() - 47 * 60_000).toISOString(),
    closed_at: null,
    ...overrides,
  }
}

function finding(
  ruleId: string,
  severity: string,
  message: string,
  extra: Partial<Finding> = {},
): Finding {
  return { rule_id: ruleId, severity, message, context: null, resolved_by_repair: false, ...extra }
}

function lineItem(position: number, values: Partial<LineItem> = {}): LineItem {
  return {
    position,
    description_raw: null,
    sku: null,
    qty: null,
    unit: null,
    unit_price: null,
    line_total: null,
    is_template_row: null,
    modifiers: [],
    line_confidence: null,
    ...values,
  }
}

/** A receipt with every column populated, at the API's own four-decimal scale.
 *
 * The scale is not decoration: `Numeric(_, 4)` is what the real route reads back
 * (`review.spec.ts` records `'1234.56'` in, `'1234.5600'` out), so a fixture that
 * used two decimals would make the money column line up better here than it does
 * in production. */
function fullReceipt(overrides: Partial<ReceiptDetail> = {}): ReceiptDetail {
  return {
    id: RECEIPT_ID,
    status: 'needs_review',
    // The document's stated tax convention. `null` is the ordinary reading and
    // the right default for a fixture: none of these receipts prints one.
    prices_include_tax: null,
    confidence: '0.570' as Money,
    confidence_reasons: [
      { reason: 'totals do not reconcile', penalty: '-0.350' as Money },
      { reason: 'date looks implausible', penalty: '-0.080' as Money },
    ] satisfies ConfidenceReason[],
    merchant_name_raw: 'TOTAL WINE',
    // These fixtures are untyped object literals, so `tsc -b` cannot say when
    // one falls behind the reply it stands for -- and `fieldsFromReceipt`
    // dereferences `receipt.buyer.name` with no guard of its own. Omitting this
    // key does not render a blank buyer, it throws in the browser and the
    // review screen never paints.
    buyer: { name: 'IDEAL SOURCE', tax_id: '009-123-456-000' },
    receipt_number: 'OR-2026-0042',
    txn_date: '2026-07-02',
    date_raw: '02/07/2026',
    txn_time: '14:30:45',
    currency: 'USD',
    created_at: '2026-07-02T14:31:00',
    payment_method: 'VISA',
    card_last4: '4242',
    is_handwritten: true,
    legibility: 'fair',
    duplicate_of: null,
    receipt_is_inconsistent: true,
    totals: {
      subtotal: '925.0000' as Money,
      tax: '80.0000' as Money,
      discount: '5.0000' as Money,
      total: '1000.0000' as Money,
      tender: '1100.0000' as Money,
      change: '100.0000' as Money,
      // The printed VAT bands. Empty here: these fixtures
      // predate the `tax_bands` table and none of them
      // exercises a breakdown.
      tax_breakdown: [],
    },
    line_items: [
      lineItem(0, {
        description_raw: 'CABERNET SAUVIGNON 2019',
        sku: 'SKU-1001',
        qty: '2.0000' as Money,
        unit: 'btl',
        unit_price: '45.0000' as Money,
        line_total: '90.0000' as Money,
      }),
      lineItem(1, {
        description_raw: 'SPARKLING WATER 750ML',
        sku: 'SKU-2002',
        qty: '3.0000' as Money,
        unit: 'btl',
        unit_price: '4.5000' as Money,
        line_total: '13.5000' as Money,
      }),
    ],
    findings: [
      finding('R020', 'error', 'totals do not reconcile: 925.00 + 80.00 - 5.00 != 1000.00'),
      finding('R011', 'warn', 'date looks implausible'),
    ],
    ...overrides,
  }
}

/** The receipt the whole milestone exists for: nulls and zeros side by side.
 *
 * The seed cannot produce this -- every column it writes is populated -- and the
 * headline question ("is a null field visibly different from a zero?") is
 * unanswerable without it. The pairs are deliberately adjacent in render order:
 *
 *   Subtotal `0.0000` (a real zero)   Tax `null`
 *   Discount `0.0000` (a real zero)   Total `null`      <- the one that matters
 *   Tender `null`                     Change `0.0000`
 *
 * and the same pairing runs down the line-items table, where row 1 also carries
 * `description_raw: ''` -- the third state, which the database itself cannot
 * tell from `null` (`_coerce_text(None)` returns `''`).
 *
 * `confidence: null` with `confidence_reasons: null` is the rail's "never
 * recorded" branch, which no seeded row reaches either. */
function nullReceipt(): ReceiptDetail {
  return fullReceipt({
    confidence: null,
    confidence_reasons: null,
    merchant_name_raw: 'BLUE RIDGE HARDWARE',
    // A receipt with no Sold To block, which is a real BIR form and not an
    // exotic one. Both halves null, so the screenshot shows what a reviewer
    // actually sees for an unread buyer -- the one thing jsdom cannot answer.
    buyer: { name: null, tax_id: null },
    receipt_number: null,
    txn_date: null,
    date_raw: '1L/O7/2O26',
    txn_time: null,
    currency: 'USD',
    payment_method: null,
    card_last4: null,
    totals: {
      subtotal: '0.0000' as Money,
      tax: null,
      discount: '0.0000' as Money,
      total: null,
      tender: null,
      change: '0.0000' as Money,
      // The printed VAT bands. Empty here: these fixtures
      // predate the `tax_bands` table and none of them
      // exercises a breakdown.
      tax_breakdown: [],
    },
    line_items: [
      lineItem(0, {
        description_raw: 'GALVANISED BOLT M8',
        sku: 'SKU-7781',
        qty: '12.0000' as Money,
        unit: 'ea',
        unit_price: '0.0000' as Money,
        line_total: '0.0000' as Money,
      }),
      lineItem(1, {
        description_raw: '',
        sku: null,
        qty: null,
        unit: null,
        unit_price: null,
        line_total: null,
      }),
    ],
    findings: [finding('R031', 'error', "no total was extracted: 'totals.total' is null")],
  })
}

/** All three severities, which the seed cannot produce either (it writes one
 *  ERROR and one WARN; `Severity` has a third member and nothing seeds it). One
 *  finding carries a `context` payload so the disclosure has something to open
 *  onto, and one is flagged `resolved_by_repair`. */
function severitiesReceipt(): ReceiptDetail {
  return fullReceipt({
    findings: [
      finding('R020', 'error', 'totals do not reconcile: 925.00 + 80.00 - 5.00 != 1000.00', {
        context: { expected: '1000.00', computed: '1000.00', paths: ['totals.total'] },
      }),
      finding('R011', 'warn', 'date looks implausible: 2026-07-02 is in the future'),
      finding('R002', 'info', 'merchant matched a known prior by name', {
        resolved_by_repair: true,
      }),
    ],
  })
}

function metrics(overrides: Partial<Metrics> = {}): Metrics {
  return {
    counts_by_status: { auto_approved: 128, needs_review: 9, reviewed: 74 },
    auto_approval_rate: '0.598',
    queue: { open: 9, in_progress: 2, done: 74, total: 85, by_priority: { '0': 1, '1': 5, '2': 3 } },
    thresholds: { auto_approve: '0.85', review: '0.60' },
    ...overrides,
  }
}

function taskRows() {
  const minutes = (n: number) => new Date(Date.now() - n * 60_000).toISOString()
  return [
    {
      id: `${TASK_ID.slice(0, -1)}a`,
      receipt_id: RECEIPT_ID,
      reason: 'validation errors and no total',
      priority: 0,
      assigned_to: null,
      state: 'open',
      opened_at: minutes(6),
      closed_at: null,
    },
    {
      id: `${TASK_ID.slice(0, -1)}b`,
      receipt_id: RECEIPT_ID,
      reason: 'needs_review',
      priority: 1,
      assigned_to: 'carol',
      state: 'in_progress',
      opened_at: minutes(94),
      closed_at: null,
    },
    {
      id: `${TASK_ID.slice(0, -1)}c`,
      receipt_id: RECEIPT_ID,
      reason: 'low confidence',
      priority: 2,
      assigned_to: null,
      state: 'open',
      opened_at: minutes(3 * 24 * 60 + 200),
      closed_at: null,
    },
    {
      id: `${TASK_ID.slice(0, -1)}d`,
      receipt_id: RECEIPT_ID,
      reason: 'needs_review',
      priority: 1,
      assigned_to: 'alice',
      state: 'done',
      opened_at: minutes(300),
      closed_at: minutes(20),
    },
  ]
}

/** A receipt-shaped image, because the seed's is a 1x1 transparent PNG.
 *
 * §5.5's question -- "is the receipt legible against its surround?" -- cannot be
 * asked of a single transparent pixel, and the seed's blob is exactly that (and
 * deliberately so: its job is to make the blob route answer 200). This is white
 * paper with black print, so the pane's surround, border and inset have
 * something real to fail against. It is served as SVG rather than PNG because
 * generating a PNG here would mean a compressor; an `<img>` renders either. */
const RECEIPT_IMAGE = `<svg xmlns="http://www.w3.org/2000/svg" width="440" height="700" viewBox="0 0 440 700">
  <rect width="440" height="700" fill="#fdfcf8"/>
  <g font-family="monospace" font-size="19" fill="#1a1a1a">
    <text x="220" y="54" text-anchor="middle" font-size="24">TOTAL WINE</text>
    <text x="220" y="82" text-anchor="middle" font-size="15">1471 MARKET ST</text>
    <text x="28" y="140">OR-2026-0042</text>
    <text x="28" y="168">02/07/2026  14:30</text>
    <text x="28" y="222">CABERNET SAUV  2 @ 45.00</text>
    <text x="392" y="222" text-anchor="end">90.00</text>
    <text x="28" y="250">SPARKLING WTR  3 @  4.50</text>
    <text x="392" y="250" text-anchor="end">13.50</text>
    <text x="28" y="322">SUBTOTAL</text>
    <text x="392" y="322" text-anchor="end">925.00</text>
    <text x="28" y="350">TAX</text>
    <text x="392" y="350" text-anchor="end">80.00</text>
    <text x="28" y="378">DISCOUNT</text>
    <text x="392" y="378" text-anchor="end">-5.00</text>
    <text x="28" y="420" font-size="23">TOTAL</text>
    <text x="392" y="420" text-anchor="end" font-size="23">1000.00</text>
    <text x="28" y="470">VISA ****4242</text>
    <text x="28" y="498">TENDER</text>
    <text x="392" y="498" text-anchor="end">1100.00</text>
    <text x="28" y="526">CHANGE</text>
    <text x="392" y="526" text-anchor="end">100.00</text>
    <text x="220" y="600" text-anchor="middle" font-size="15">THANK YOU</text>
  </g>
</svg>`

// ---------------------------------------------------------------------------
// Stubs, with the counter that proves they fired
// ---------------------------------------------------------------------------

function envelope(message: string) {
  return { error: { message } }
}

async function json(route: Route, status: number, body: unknown): Promise<void> {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

interface Stubs {
  /** Register a handler and count every request it answers. */
  on(name: string, glob: string, handler: (route: Route) => Promise<void>): Promise<void>
  /** Fail the test unless each named stub answered at least once. */
  expectHits(...names: string[]): void
  readonly counts: Record<string, number>
}

function stubs(page: Page): Stubs {
  const counts: Record<string, number> = {}
  return {
    counts,
    async on(name, glob, handler) {
      counts[name] = 0
      await page.route(glob, async (route) => {
        counts[name] += 1
        await handler(route)
      })
    },
    expectHits(...names) {
      for (const name of names) {
        // Not `toBeGreaterThan(0)` on a bare number: the message has to name the
        // stub, because a zero here means the screenshot is of the real page.
        expect(counts[name], `route stub "${name}" never matched -- the screenshot would be of the real page, not the synthetic state`).toBeGreaterThan(0)
      }
    },
  }
}

/** The stubs every signed-in synthetic page needs.
 *
 * `/auth/me` first and always: unstubbed it 401s, `client.ts` fires the
 * unauthorized handler, and the app renders the login form instead of whatever
 * this test meant to photograph. */
async function baseStubs(page: Page, identity: { username: string; role: string }): Promise<Stubs> {
  const s = stubs(page)
  await s.on('auth/me', '**/auth/me', (route) => json(route, 200, identity))
  return s
}

/** The image chain: the signed-link envelope, then the blob it points at. */
async function imageStubs(s: Stubs): Promise<void> {
  await s.on('image/link', '**/receipts/*/image', (route) =>
    json(route, 200, { url: `/receipts/${RECEIPT_ID}/image/blob?exp=9999999999&sig=stub` }),
  )
  await s.on('image/blob', '**/receipts/*/image/blob*', (route) =>
    route.fulfill({ status: 200, contentType: 'image/svg+xml', body: RECEIPT_IMAGE }),
  )
}

// ---------------------------------------------------------------------------
// Capture plumbing
// ---------------------------------------------------------------------------

interface Measurement {
  readonly surface: string
  readonly width: number
  readonly theme: Theme
  readonly data: unknown
}

const measurements: Measurement[] = []
const captured: string[] = []

function fileFor(surface: string, viewport: Viewport, theme: Theme): string {
  return path.join(SHOTS, `${surface}--${viewport.name}-${theme}.png`)
}

/** Wait for the things that make a screenshot mean what it looks like: the
 *  webfonts (a shot taken mid-swap shows the fallback stack, and "does the money
 *  column line up" is a question about Fira Code specifically) and one animation
 *  frame after them. */
async function settle(page: Page): Promise<void> {
  await page.evaluate(async () => {
    await document.fonts.ready
    await new Promise((resolve) => requestAnimationFrame(() => resolve(null)))
  })
}

async function shot(
  page: Page,
  surface: string,
  viewport: Viewport,
  theme: Theme,
  target?: Locator,
): Promise<void> {
  await settle(page)
  const file = fileFor(surface, viewport, theme)
  // Viewport-sized, never `fullPage`: a full-page shot of this screen at 375 is
  // ~1:10 and is scaled to illegibility by every image reader. The tall viewport
  // above is what buys coverage instead.
  await (target === undefined ? page.screenshot({ path: file }) : target.screenshot({ path: file }))
  captured.push(path.basename(file))
}

async function withPage(
  browser: Browser,
  baseURL: string,
  viewport: Viewport,
  theme: Theme,
  body: (page: Page) => Promise<void>,
): Promise<void> {
  const context = await browser.newContext({
    baseURL,
    viewport: { width: viewport.width, height: viewport.height },
    // The OS route into dark, which is the one that exercises
    // `:root:not([data-theme='light'])` inside the `prefers-color-scheme` block.
    // The app ships no theme toggle, so this and an explicit `data-theme` are the
    // only two ways in; the precedence test below drives the other.
    colorScheme: theme,
    deviceScaleFactor: 1,
  })
  const page = await context.newPage()
  try {
    await body(page)
  } finally {
    await context.close()
  }
}

function baseURLOf(use: { baseURL?: string }): string {
  const baseURL = use.baseURL
  if (baseURL === undefined) {
    throw new Error('playwright.config.ts must set use.baseURL; this file will not guess one')
  }
  return baseURL
}

// ---------------------------------------------------------------------------
// In-page measurement
// ---------------------------------------------------------------------------

/** Everything about a rendered page that is a number rather than a judgement.
 *
 * Taken in the browser because that is the only place the answers exist: a
 * contrast ratio needs the *used* colours after the cascade and after the
 * theme's media query, a hit target needs a layout box, and "does this font have
 * tabular figures" needs the font that actually loaded. jsdom has none of them,
 * which is why three milestones of green Vitest runs could not answer any of
 * these questions. */
async function measure(page: Page) {
  return page.evaluate(() => {
    interface Rgb {
      r: number
      g: number
      b: number
      a: number
    }

    function parseColor(value: string): Rgb | null {
      const match = value.match(/rgba?\(([^)]+)\)/)
      if (match === null) {
        return null
      }
      const parts = match[1]
        .split(/[,\s/]+/)
        .filter((part) => part !== '')
        .map((part) => Number(part))
      if (parts.length < 3) {
        return null
      }
      return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 }
    }

    function luminance(color: Rgb): number {
      const channel = (value: number): number => {
        const scaled = value / 255
        return scaled <= 0.03928 ? scaled / 12.92 : Math.pow((scaled + 0.055) / 1.055, 2.4)
      }
      return 0.2126 * channel(color.r) + 0.7152 * channel(color.g) + 0.0722 * channel(color.b)
    }

    function over(top: Rgb, bottom: Rgb): Rgb {
      const a = top.a
      return {
        r: top.r * a + bottom.r * (1 - a),
        g: top.g * a + bottom.g * (1 - a),
        b: top.b * a + bottom.b * (1 - a),
        a: 1,
      }
    }

    /** The colour actually behind an element: the first ancestor that paints
     *  one, composited down to the page background. */
    function backgroundOf(element: Element): Rgb {
      let node: Element | null = element
      let result: Rgb = { r: 255, g: 255, b: 255, a: 1 }
      const stack: Rgb[] = []
      while (node !== null) {
        const parsed = parseColor(getComputedStyle(node).backgroundColor)
        if (parsed !== null && parsed.a > 0) {
          stack.push(parsed)
          if (parsed.a === 1) {
            break
          }
        }
        node = node.parentElement
      }
      for (let i = stack.length - 1; i >= 0; i -= 1) {
        result = over(stack[i], result)
      }
      return result
    }

    function ratio(foreground: Rgb, background: Rgb): number {
      const front = foreground.a < 1 ? over(foreground, background) : foreground
      const first = luminance(front)
      const second = luminance(background)
      const light = Math.max(first, second)
      const dark = Math.min(first, second)
      return Math.round(((light + 0.05) / (dark + 0.05)) * 100) / 100
    }

    /** Cumulative opacity, which `color` does not carry: a disabled button is
     *  painted at 0.5 and its computed colour still reads full strength. */
    function opacityOf(element: Element): number {
      let node: Element | null = element
      let total = 1
      while (node !== null) {
        total *= Number(getComputedStyle(node).opacity)
        node = node.parentElement
      }
      return Math.round(total * 100) / 100
    }

    function labelFor(element: Element): string {
      const aria = element.getAttribute('aria-label')
      if (aria !== null && aria !== '') {
        return aria
      }
      const text = (element.textContent ?? '').trim().replace(/\s+/g, ' ')
      if (text !== '') {
        return text.slice(0, 60)
      }
      const owner = element.closest('label')
      if (owner !== null) {
        return (owner.textContent ?? '').trim().replace(/\s+/g, ' ').slice(0, 60)
      }
      return element.getAttribute('placeholder') ?? ''
    }

    function describe(element: Element): string {
      const tag = element.tagName.toLowerCase()
      const label = labelFor(element)
      return label === '' ? tag : `${tag}: ${label}`
    }

    const contrast: { what: string; color: string; background: string; ratio: number; opacity: number; size: string }[] = []
    const seen = new Set<string>()
    function sample(what: string, element: Element | null, pseudo?: string): void {
      if (element === null || seen.has(what)) {
        return
      }
      seen.add(what)
      const style = getComputedStyle(element, pseudo)
      const foreground = parseColor(style.color)
      if (foreground === null) {
        return
      }
      const background = backgroundOf(element)
      contrast.push({
        what,
        color: style.color,
        background: `rgb(${Math.round(background.r)}, ${Math.round(background.g)}, ${Math.round(background.b)})`,
        ratio: ratio(foreground, background),
        opacity: opacityOf(element),
        size: `${style.fontSize} ${style.fontWeight}`,
      })
    }

    // Named samples, chosen because each answers a question the design asks.
    sample('body text (first paragraph)', document.querySelector('main p'))
    sample('h1', document.querySelector('h1'))
    sample('field label', document.querySelector('label'))
    sample('field value (input)', document.querySelector('input'))
    sample('input placeholder (the null mark)', document.querySelector('input'), '::placeholder')
    sample('null mark (Value)', document.querySelector('[role="img"][aria-label="not extracted"]'))
    sample('table header', document.querySelector('th'))
    sample('table cell', document.querySelector('td'))
    for (const severity of ['error', 'warn', 'info']) {
      const node = Array.from(document.querySelectorAll('em')).find(
        (element) => (element.textContent ?? '').trim() === severity,
      )
      sample(`severity word: ${severity}`, node ?? null)
    }
    sample('summary alert', document.querySelector('[role="alert"]'))
    const rail = document.querySelector('aside')
    sample('confidence band', rail?.querySelector('p:nth-of-type(2)') ?? null)
    sample('confidence reason', rail?.querySelector('li span') ?? null)
    for (const element of Array.from(document.querySelectorAll('p, span, li, td, th, summary'))) {
      const text = (element.textContent ?? '').trim()
      if (text === '' || element.children.length > 0) {
        continue
      }
      const style = getComputedStyle(element)
      const foreground = parseColor(style.color)
      if (foreground === null) {
        continue
      }
      const value = ratio(foreground, backgroundOf(element))
      if (value < 4.5) {
        sample(`BELOW 4.5:1 -- ${describe(element)}`, element)
      }
    }

    // Hit targets. Every interactive element, with the ones under 44 in either
    // dimension called out -- design section 6 asks for 44x44 with 8px
    // separation and records that the pre-styling controls were smaller.
    const interactive = Array.from(
      document.querySelectorAll('button, input, select, textarea, a[href], summary, [role="button"]'),
    )
    const targets = interactive.map((element) => {
      const box = element.getBoundingClientRect()
      return {
        what: describe(element),
        width: Math.round(box.width * 10) / 10,
        height: Math.round(box.height * 10) / 10,
        undersized: box.width < 44 || box.height < 44,
      }
    })

    // A control against the table cell that is supposed to contain it. Under
    // `table-layout: fixed` a cell does not grow to its content, so a control
    // wider than its column paints over the columns beside it -- and the
    // difference is the number that says so.
    //
    // `cellsMeasured` counts every (cell, control) pair examined, and exists so
    // that "nothing overflowed" can be told apart from "nothing was looked at".
    // An empty `cellOverflow` is the pass condition and is also what a page with
    // no table returns, so the count is the witness that makes the assertion in
    // `assertMeasured` non-vacuous.
    const cellOverflow: { column: string; cell: number; control: number; overflowsBy: number }[] = []
    let cellsMeasured = 0
    const headers = Array.from(document.querySelectorAll('thead th')).map((th) =>
      (th.textContent ?? '').trim(),
    )
    for (const cell of Array.from(document.querySelectorAll('tbody td'))) {
      const control = cell.querySelector('input')
      if (control === null) {
        continue
      }
      cellsMeasured += 1
      const outer = cell.getBoundingClientRect()
      const inner = control.getBoundingClientRect()
      const index = Array.from(cell.parentElement?.children ?? []).indexOf(cell)
      if (inner.width > outer.width + 1) {
        cellOverflow.push({
          column: headers[index] ?? `column ${index}`,
          cell: Math.round(outer.width),
          control: Math.round(inner.width),
          overflowsBy: Math.round(inner.width - outer.width),
        })
      }
    }

    // A checkbox is 20px by design; the label around it is what the 44px rule is
    // met with (`ReceiptForm.module.css`'s `.check`). Both boxes, so the claim is
    // measured rather than read off the stylesheet.
    const checkboxTargets = Array.from(
      document.querySelectorAll('input[type="checkbox"]'),
    ).map((box) => {
      const owner = box.closest('label')
      const inner = box.getBoundingClientRect()
      const outer = (owner ?? box).getBoundingClientRect()
      return {
        what: labelFor(box),
        input: `${Math.round(inner.width)}x${Math.round(inner.height)}`,
        effective: `${Math.round(outer.width)}x${Math.round(outer.height)}`,
        wrappedByLabel: owner !== null,
      }
    })

    // Horizontal overflow, and what is doing it.
    const limit = document.documentElement.clientWidth
    const spilling = Array.from(document.querySelectorAll('*'))
      .filter((element) => {
        const box = element.getBoundingClientRect()
        return box.right > limit + 1 && box.width > 0
      })
      .slice(0, 12)
      .map((element) => ({
        what: describe(element),
        right: Math.round(element.getBoundingClientRect().right),
      }))

    // The money column. Right edges of every money control, the font they are
    // rendered in, and whether that font's digits really are the same width --
    // the property the whole "a transposed digit looks wrong" argument rests on.
    const moneyInputs = Array.from(document.querySelectorAll('input[inputmode="decimal"]'))
    const canvas = document.createElement('canvas')
    const pen = canvas.getContext('2d')
    let tabular: { one: number; zero: number; nine: number; font: string } | null = null
    if (pen !== null && moneyInputs.length > 0) {
      const style = getComputedStyle(moneyInputs[0])
      const font = `${style.fontSize} ${style.fontFamily}`
      pen.font = font
      tabular = {
        font,
        one: Math.round(pen.measureText('1111111111').width * 100) / 100,
        zero: Math.round(pen.measureText('0000000000').width * 100) / 100,
        nine: Math.round(pen.measureText('9999999999').width * 100) / 100,
      }
    }
    const money = {
      count: moneyInputs.length,
      fontFamily: moneyInputs.length > 0 ? getComputedStyle(moneyInputs[0]).fontFamily : null,
      textAlign: moneyInputs.length > 0 ? getComputedStyle(moneyInputs[0]).textAlign : null,
      fontVariantNumeric:
        moneyInputs.length > 0 ? getComputedStyle(moneyInputs[0]).fontVariantNumeric : null,
      rightEdges: moneyInputs.map((element) => Math.round(element.getBoundingClientRect().right)),
      tabular,
    }

    return {
      theme: {
        colorScheme: getComputedStyle(document.documentElement).colorScheme,
        background: getComputedStyle(document.body).backgroundColor,
        foreground: getComputedStyle(document.body).color,
        dataTheme: document.documentElement.getAttribute('data-theme'),
        prefersDark: matchMedia('(prefers-color-scheme: dark)').matches,
      },
      fonts: {
        firaSansLoaded: document.fonts.check('16px "Fira Sans"'),
        firaCodeLoaded: document.fonts.check('16px "Fira Code"'),
        bodyFamily: getComputedStyle(document.body).fontFamily,
      },
      overflow: {
        documentScrollWidth: document.documentElement.scrollWidth,
        clientWidth: limit,
        overflows: document.documentElement.scrollWidth > limit + 1,
        spilling,
      },
      contrast,
      targets: {
        total: targets.length,
        undersized: targets.filter((target) => target.undersized),
        checkboxTargets,
      },
      cellOverflow,
      cellsMeasured,
      money,
    }
  })
}

/** Tab through the page and record what the browser actually paints on the
 *  focused element. Keyboard focus rather than `element.focus()` on purpose:
 *  `:focus-visible` is what `tokens.css` styles, and a programmatic focus does
 *  not always match it -- so a ring measured that way would be a claim about a
 *  state a reviewer never reaches. */
async function focusWalk(page: Page, stops: number) {
  const seen: unknown[] = []
  for (let index = 0; index < stops; index += 1) {
    await page.keyboard.press('Tab')
    const stop = await page.evaluate(() => {
      const element = document.activeElement
      if (element === null || element === document.body) {
        return null
      }
      const style = getComputedStyle(element)
      const box = element.getBoundingClientRect()
      const label =
        element.getAttribute('aria-label') ??
        (element.closest('label')?.textContent ?? element.textContent ?? '').trim().slice(0, 40)
      return {
        what: `${element.tagName.toLowerCase()}: ${label}`,
        focusVisible: element.matches(':focus-visible'),
        outline: `${style.outlineWidth} ${style.outlineStyle} ${style.outlineColor}`,
        outlineOffset: style.outlineOffset,
        boxShadow: style.boxShadow,
        size: `${Math.round(box.width)}x${Math.round(box.height)}`,
      }
    })
    if (stop === null) {
      break
    }
    seen.push(stop)
  }
  return seen
}

// ---------------------------------------------------------------------------
// The two measurements that are asserted, and why only two
// ---------------------------------------------------------------------------

/** Design §6's body-text floor, flat -- no large-text discount.
 *
 *  The sweep in `measure` above already flags anything under 4.5 whatever its
 *  size, so taking the discount here would make the two disagree. The tree's
 *  measured minimum is 4.76 (`--color-null` on white), so the flat floor holds
 *  with margin rather than by luck. `tests/stylesheets.test.ts` uses the same
 *  number and the same arithmetic on the token values themselves. */
const AA_FLOOR = 4.5

interface ContrastSample {
  readonly what: string
  readonly ratio: number
  readonly color: string
  readonly background: string
}

interface CellOverflow {
  readonly column: string
  readonly cell: number
  readonly control: number
  readonly overflowsBy: number
}

/** How much this run actually looked at, so `afterAll` can refuse to call an
 *  empty check a pass. */
let cellsChecked = 0

/** The measurements that stopped being merely recorded, and the reason.
 *
 * **This is not a pixel baseline and must not become one.** There is still no
 * `toHaveScreenshot`, no snapshot and no image comparison anywhere in this file,
 * for the reason the docblock at the top gives. What is asserted here are two
 * *numbers the page computed* -- a contrast ratio and a box-width difference --
 * each against a threshold the design document names. A baseline says "it looks
 * like it did last time"; these say "it clears the floor", which is a claim that
 * stays true when the design changes and false when the guarantee breaks. Every
 * other measurement -- hit target sizes, focus rings, tabular figures, document
 * overflow -- is still recorded and still asserted nowhere, because a threshold
 * for those is a judgement nobody has made yet.
 *
 * These are the two the whole-branch review proved were unheld: reverting
 * `MoneyInput.module.css`'s `.field` to `inline-flex` and reverting the dark
 * `--color-null` lift both left all five gates green, and this file computed the
 * evidence for both and asserted neither.
 *
 * **`expect.soft`, not `expect`.** A hard failure would abort the surface loop
 * and lose every screenshot after it, which would turn one contrast regression
 * into a run with no evidence in it -- the opposite of what this file is for.
 * Soft failures let all sixty-odd captures complete, write `measurements.json`,
 * and then fail the run with every offending sample named at once. */
function assertMeasured(where: string, data: unknown): void {
  const measured = data as {
    contrast?: readonly ContrastSample[]
    cellOverflow?: readonly CellOverflow[]
    cellsMeasured?: number
  }

  if (measured.contrast !== undefined) {
    // A page whose sampler returned nothing would satisfy the loop below
    // perfectly. The smallest real record is the 503 screen at two samples.
    expect
      .soft(
        measured.contrast.length,
        `${where}: no contrast sample at all -- the sampler in \`measure\` stopped ` +
          `matching, so the floor below is being checked against nothing`,
      )
      .toBeGreaterThan(0)
    for (const sample of measured.contrast) {
      expect
        .soft(
          sample.ratio,
          `${where} -- ${sample.what}: ${sample.color} on ${sample.background} is ` +
            `${sample.ratio}:1, below design §6's ${AA_FLOOR}:1 body-text floor`,
        )
        .toBeGreaterThanOrEqual(AA_FLOOR)
    }
  }

  if (measured.cellOverflow !== undefined) {
    cellsChecked += measured.cellsMeasured ?? 0
    expect
      .soft(
        measured.cellOverflow,
        `${where}: a control is wider than the table cell holding it. Under ` +
          `\`table-layout: fixed\` the cell does not grow, so the control paints over ` +
          `the column beside it and its right-aligned content -- the em dash that ` +
          `says a value was never extracted -- is pushed outside the clipped ` +
          `scroller. \`MoneyInput.module.css\`'s \`.field\` being block-level rather ` +
          `than inline-level is what holds this.`,
      )
      .toEqual([])
  }
}

function record(surface: string, viewport: Viewport, theme: Theme, data: unknown): void {
  measurements.push({ surface, width: viewport.width, theme, data })
  assertMeasured(`${surface} @${viewport.width} ${theme}`, data)
}

// ---------------------------------------------------------------------------
// Shared page setups
// ---------------------------------------------------------------------------

function fixture(): Fixture {
  return JSON.parse(fs.readFileSync(MANIFEST, 'utf8')) as Fixture
}

/** The real login, against the real API, with the seeded reviewer. */
async function signIn(page: Page, seed: Fixture): Promise<void> {
  await page.goto('/app/login')
  await page.getByLabel('Username').fill(seed.username)
  await page.getByLabel('Password').fill(seed.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  const table = page.getByRole('table')
  const drained = page.getByText('The review queue is empty.')
  await expect(table.or(drained).first()).toBeVisible({ timeout: 15_000 })
  if (await drained.isVisible()) {
    throw new Error(
      'the seeded queue is empty, so this is not the review screen: something closed the one ' +
        'task this fixture holds (review.spec.ts does, by design). Re-run as ' +
        '`npx playwright test visual`, which re-seeds.',
    )
  }
}

/** A stubbed, signed-in review screen showing `receipt`. */
async function stubbedReview(page: Page, receipt: unknown): Promise<Stubs> {
  const s = await baseStubs(page, { username: 'alice', role: 'reviewer' })
  await s.on('review/next', '**/review/next', (route) => json(route, 200, { task: task() }))
  await s.on('receipt', '**/receipts/*', (route) => json(route, 200, receipt))
  await imageStubs(s)
  await page.goto('/app/review')
  await expect(page.getByRole('table')).toBeVisible()
  await expect(page.locator('img[alt="Receipt"]')).toBeVisible()
  return s
}

const formSection = (page: Page): Locator =>
  page.locator('section').filter({ has: page.getByRole('heading', { name: 'Receipt', exact: true }) })

const findingsSection = (page: Page): Locator =>
  page.locator('section').filter({ hasText: 'What the machine found at extraction time' })

/** The line-items table's `overflow-x` wrapper -- the box a reviewer sees. */
const scrollerOf = (page: Page): Locator =>
  page.locator('section').filter({ has: page.getByRole('table') })

// ---------------------------------------------------------------------------
// The pass
// ---------------------------------------------------------------------------

test.beforeAll(() => {
  fs.rmSync(SHOTS, { recursive: true, force: true })
  fs.mkdirSync(SHOTS, { recursive: true })
})

test.afterAll(() => {
  // The artefacts are written FIRST, before anything below can throw: the
  // screenshots and the measurements are the whole product of this file, and a
  // run that fails its own coverage check is exactly the run whose evidence
  // someone needs to read.
  fs.writeFileSync(
    path.join(SHOTS, 'measurements.json'),
    `${JSON.stringify(measurements, null, 2)}\n`,
    'utf8',
  )
  fs.writeFileSync(path.join(SHOTS, 'captured.txt'), `${captured.join('\n')}\n`, 'utf8')
  // eslint-disable-next-line no-console
  console.log(
    `\n${captured.length} screenshots in ${SHOTS}\n` +
      `${measurements.length} measurement records, ${cellsChecked} table cells checked for overflow`,
  )

  // The cell-overflow assertion passes on an empty list, and a page with no
  // table returns an empty list -- so without this, a selector change in
  // `measure` would silently reduce that check to nothing while every surface
  // still went green. `expect`, not `expect.soft`: there is nothing left to
  // collect.
  //
  // A run filtered to surfaces that have no line-items table (`-g "login"`) will
  // trip this, and that is the intended reading rather than a wrinkle: such a
  // run is not evidence about cell overflow and should not be quoted as if it
  // were. A full run measures several hundred pairs.
  expect(
    cellsChecked,
    'this run examined no table cell at all, so its clean cell-overflow result ' +
      'says nothing. Either `measure` stopped finding controls in `tbody td`, or ' +
      'the run was filtered to surfaces that have no line-items table.',
  ).toBeGreaterThan(0)
})

test('login, at three widths', async ({ browser }, testInfo) => {
  test.setTimeout(120_000)
  const baseURL = baseURLOf(testInfo.project.use)
  for (const viewport of ALL_WIDTHS) {
    for (const theme of THEMES) {
      await withPage(browser, baseURL, viewport, theme, async (page) => {
        await page.goto('/app/login')
        await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible()
        await shot(page, 'login', viewport, theme)
        record('login', viewport, theme, {
          ...(await measure(page)),
          focus: await focusWalk(page, 4),
        })
      })
    }
  }
})

test('the review screen, real seeded data', async ({ browser }, testInfo) => {
  test.setTimeout(180_000)
  const baseURL = baseURLOf(testInfo.project.use)
  const seed = fixture()
  for (const viewport of ALL_WIDTHS) {
    for (const theme of THEMES) {
      await withPage(browser, baseURL, viewport, theme, async (page) => {
        await signIn(page, seed)
        await shot(page, 'review-real', viewport, theme)
        // The **scroller**, not the `<table>`: the table's own box is 44rem wide
        // by `min-width`, so at 375 it is wider than the viewport, and Playwright's
        // element screenshot of a box that exceeds the viewport captured a region
        // of the page that was not the table at all (measured -- the first run's
        // `review-real-table--375-light.png` was a picture of the form). The
        // scroller is what a reviewer actually sees, clipping included.
        await shot(page, 'review-real-table', viewport, theme, scrollerOf(page))
        if (viewport === MID) {
          await shot(page, 'review-real-imagepane', viewport, theme, page.locator('main > div').first())
        }
        if (viewport === NARROW) {
          await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
          await shot(page, 'review-real-bottom', viewport, theme)
        }
        // Last, because it leaves focus somewhere: a ring in the middle of an
        // otherwise idle screenshot reads as a defect and is not one.
        record('review-real', viewport, theme, {
          ...(await measure(page)),
          focus: await focusWalk(page, 26),
        })
      })
    }
  }
  // What is actually above the fold on a real laptop, since every shot above
  // uses a 1400px-tall viewport that no window has.
  await withPage(browser, baseURL, { name: '1440x900', width: 1440, height: 900 }, 'light', async (page) => {
    await signIn(page, seed)
    await shot(page, 'review-real-fold', { name: '1440x900', width: 1440, height: 900 }, 'light')
  })
})

test('the review screen with null fields, beside real zeros', async ({ browser }, testInfo) => {
  test.setTimeout(180_000)
  const baseURL = baseURLOf(testInfo.project.use)
  for (const viewport of ALL_WIDTHS) {
    for (const theme of THEMES) {
      await withPage(browser, baseURL, viewport, theme, async (page) => {
        const s = await stubbedReview(page, nullReceipt())
        // The state is reached, not assumed: an empty Total box beside a filled
        // Subtotal is the whole point of the capture.
        await expect(page.getByLabel('Total', { exact: true })).toHaveValue('')
        await expect(page.getByLabel('Subtotal', { exact: true })).toHaveValue('0.0000')
        s.expectHits('auth/me', 'review/next', 'receipt', 'image/link', 'image/blob')
        await shot(page, 'review-null', viewport, theme)
        record('review-null', viewport, theme, await measure(page))
        await shot(page, 'review-null-table', viewport, theme, scrollerOf(page))
        if (viewport === MID) {
          await shot(page, 'review-null-form', viewport, theme, formSection(page))
          await shot(page, 'review-null-rail', viewport, theme, page.locator('aside'))
        }
      })
    }
  }
})

test('findings at all three severities', async ({ browser }, testInfo) => {
  test.setTimeout(180_000)
  const baseURL = baseURLOf(testInfo.project.use)
  for (const viewport of ALL_WIDTHS) {
    for (const theme of THEMES) {
      await withPage(browser, baseURL, viewport, theme, async (page) => {
        const s = await stubbedReview(page, severitiesReceipt())
        for (const severity of ['error', 'warn', 'info']) {
          await expect(page.getByText(severity, { exact: true }).first()).toBeVisible()
        }
        s.expectHits('receipt')
        // One disclosure open, so the `context` payload is on screen too.
        await page.locator('details').first().locator('summary').click()
        await shot(page, 'findings-severities', viewport, theme)
        record('findings-severities', viewport, theme, await measure(page))
        if (viewport === MID) {
          await shot(page, 'findings-panel', viewport, theme, findingsSection(page))
        }
      })
    }
  }
})

test('ADR-0024 state 1 of 5: the distinct 503, with the Skip escape suppressed', async ({
  browser,
}, testInfo) => {
  test.setTimeout(120_000)
  const baseURL = baseURLOf(testInfo.project.use)
  for (const viewport of ENDS) {
    for (const theme of THEMES) {
      await withPage(browser, baseURL, viewport, theme, async (page) => {
        const s = await baseStubs(page, { username: 'alice', role: 'reviewer' })
        // The claim succeeds and the load fails, so a task is held: that is the
        // arrangement in which the Skip escape would otherwise be offered, and
        // ADR-0024 section 4 says a 503 must suppress it.
        await s.on('review/next', '**/review/next', (route) => json(route, 200, { task: task() }))
        await s.on('receipt', '**/receipts/*', (route) =>
          json(route, 503, envelope('the database is unavailable')),
        )
        await page.goto('/app/review')
        // The load path's explanation, quoted in full: this string is exactly
        // what the JSX transform emits for that paragraph, so a reword there
        // must move it here.
        await expect(
          page.getByText(
            'Your assigned tasks are unaffected — this is a server problem, not a change to your queue.',
          ),
        ).toBeVisible()
        await expect(page.getByRole('alert')).toHaveText('the database is unavailable')
        await expect(page.getByRole('button', { name: 'Skip this receipt' })).toHaveCount(0)
        s.expectHits('review/next', 'receipt')
        await shot(page, 'error-503-backend-down', viewport, theme)
        record('error-503-backend-down', viewport, theme, {
          ...(await measure(page)),
          focus: await focusWalk(page, 3),
        })
      })
    }
  }
})

test('ADR-0024 state 2 of 5: a 403 on the close, the terminal taken state', async ({
  browser,
}, testInfo) => {
  test.setTimeout(120_000)
  const baseURL = baseURLOf(testInfo.project.use)
  for (const viewport of ENDS) {
    for (const theme of THEMES) {
      await withPage(browser, baseURL, viewport, theme, async (page) => {
        const s = await stubbedReview(page, fullReceipt())
        await s.on('patch', '**/receipts/*', async (route) => {
          if (route.request().method() === 'PATCH') {
            await json(route, 200, fullReceipt())
            return
          }
          await json(route, 200, fullReceipt())
        })
        await s.on('complete', '**/review/*/complete', (route) =>
          json(route, 403, envelope('review task 3f1b7c52 is assigned to carol')),
        )
        await page.getByLabel('Total', { exact: true }).fill('1234.56')
        await page.keyboard.press('ControlOrMeta+Enter')
        await expect(
          page.getByRole('heading', { name: 'Saved, but this task was taken over by someone else' }),
        ).toBeVisible()
        s.expectHits('patch', 'complete')
        await shot(page, 'error-403-taken', viewport, theme)
        record('error-403-taken', viewport, theme, await measure(page))
      })
    }
  }
})

test('ADR-0024 state 3 of 5: a 404 on the close, the terminal gone state', async ({
  browser,
}, testInfo) => {
  test.setTimeout(120_000)
  const baseURL = baseURLOf(testInfo.project.use)
  for (const viewport of ENDS) {
    for (const theme of THEMES) {
      await withPage(browser, baseURL, viewport, theme, async (page) => {
        const s = await stubbedReview(page, fullReceipt())
        await s.on('patch', '**/receipts/*', (route) => json(route, 200, fullReceipt()))
        await s.on('complete', '**/review/*/complete', (route) =>
          json(route, 404, envelope('no review task 3f1b7c52-0000-4000-8000-000000000001')),
        )
        await page.getByLabel('Total', { exact: true }).fill('1234.56')
        await page.keyboard.press('ControlOrMeta+Enter')
        await expect(
          page.getByRole('heading', { name: 'Saved, but this task no longer exists' }),
        ).toBeVisible()
        s.expectHits('patch', 'complete')
        await shot(page, 'error-404-gone', viewport, theme)
        record('error-404-gone', viewport, theme, await measure(page))
      })
    }
  }
})

test('ADR-0024 state 4 of 5: a 400 blamed on one field, inline and additive', async ({
  browser,
}, testInfo) => {
  test.setTimeout(120_000)
  const baseURL = baseURLOf(testInfo.project.use)
  for (const viewport of ENDS) {
    for (const theme of THEMES) {
      await withPage(browser, baseURL, viewport, theme, async (page) => {
        const s = await stubbedReview(page, fullReceipt())
        // The exact text the real route produces for this input, quoted in
        // `ReviewScreen.tsx`: the classifier matches on the quoted *value*, so a
        // reworded message would degrade to summary-only and this capture would
        // be of a different state than its filename claims.
        await s.on('patch', '**/receipts/*', async (route) => {
          if (route.request().method() === 'PATCH') {
            await json(route, 400, envelope("not a decimal amount: 'abc'"))
            return
          }
          await json(route, 200, fullReceipt())
        })
        await page.getByLabel('Total', { exact: true }).fill('abc')
        await page.keyboard.press('ControlOrMeta+Enter')
        // Additive: the inline message beside the field AND the summary alert.
        await expect(page.getByRole('alert').filter({ hasText: "not a decimal amount: 'abc'" })).toHaveCount(2)
        s.expectHits('patch')
        await shot(page, 'error-400-field', viewport, theme)
        if (viewport === WIDE) {
          await shot(page, 'error-400-field-form', viewport, theme, formSection(page))
        }
        record('error-400-field', viewport, theme, await measure(page))
      })
    }
  }
})

test('ADR-0024 state 5 of 5: a 401 to the login page, and back to the receipt', async ({
  browser,
}, testInfo) => {
  test.setTimeout(120_000)
  const baseURL = baseURLOf(testInfo.project.use)
  for (const theme of THEMES) {
    await withPage(browser, baseURL, MID, theme, async (page) => {
      const s = await stubbedReview(page, fullReceipt())
      await s.on('patch', '**/receipts/*', async (route) => {
        if (route.request().method() === 'PATCH') {
          await json(route, 401, envelope('not authenticated'))
          return
        }
        await json(route, 200, fullReceipt())
      })
      await s.on('login', '**/auth/login', (route) =>
        json(route, 200, { username: 'alice', role: 'reviewer' }),
      )
      // An edit, then a 401 on the save. `client.ts` owns 401 at the transport,
      // so the whole screen is replaced by the login form -- with the edit held
      // in the in-memory stash (ADR-0024 section 2: never in browser storage).
      await page.getByLabel('Total', { exact: true }).fill('9999.99')
      await page.keyboard.press('ControlOrMeta+Enter')
      await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible()
      s.expectHits('patch')
      await shot(page, 'error-401-login', MID, theme)
      record('error-401-login', MID, theme, await measure(page))

      await page.getByLabel('Username').fill('alice')
      await page.getByLabel('Password').fill('pw-alice')
      await page.getByRole('button', { name: 'Sign in' }).click()
      // ADR-0016 hands the same task back and the overlay is re-applied, so the
      // reviewer's unsaved edit is on screen again.
      await expect(page.getByLabel('Total', { exact: true })).toHaveValue('9999.99')
      s.expectHits('login')
      await shot(page, 'error-401-restored', MID, theme)
      record('error-401-restored', MID, theme, await measure(page))
    })
  }
})

test('the load failure that does offer the Skip escape', async ({ browser }, testInfo) => {
  test.setTimeout(120_000)
  const baseURL = baseURLOf(testInfo.project.use)
  for (const theme of THEMES) {
    await withPage(browser, baseURL, MID, theme, async (page) => {
      const s = await baseStubs(page, { username: 'alice', role: 'reviewer' })
      await s.on('review/next', '**/review/next', (route) => json(route, 200, { task: task() }))
      await s.on('receipt', '**/receipts/*', (route) =>
        json(route, 500, envelope('request failed (500)')),
      )
      await page.goto('/app/review')
      await expect(page.getByRole('button', { name: 'Skip this receipt' })).toBeVisible()
      s.expectHits('receipt')
      await shot(page, 'error-500-skip-escape', MID, theme)
      record('error-500-skip-escape', MID, theme, await measure(page))
    })
  }
})

test('the sign-out control, and its unsaved-edits confirm', async ({ browser }, testInfo) => {
  test.setTimeout(120_000)
  const baseURL = baseURLOf(testInfo.project.use)
  for (const theme of THEMES) {
    await withPage(browser, baseURL, MID, theme, async (page) => {
      await stubbedReview(page, fullReceipt())
      await page.getByLabel('Total', { exact: true }).fill('1234.56')
      await page.getByRole('button', { name: 'Sign out' }).click()
      await expect(page.getByText('You have unsaved edits on this receipt.')).toBeVisible()
      await shot(page, 'sign-out-confirm', MID, theme, page.locator('header'))
      record('sign-out-confirm', MID, theme, await measure(page))
    })
  }
})

test('the admin surface with tasks, as an admin', async ({ browser }, testInfo) => {
  test.setTimeout(180_000)
  const baseURL = baseURLOf(testInfo.project.use)
  for (const viewport of ALL_WIDTHS) {
    for (const theme of THEMES) {
      await withPage(browser, baseURL, viewport, theme, async (page) => {
        const s = await baseStubs(page, { username: 'dana', role: 'admin' })
        await s.on('tasks', '**/review/tasks*', (route) =>
          json(route, 200, { items: taskRows(), has_more: true }),
        )
        await s.on('metrics', '**/metrics', (route) => json(route, 200, metrics()))
        await page.goto('/app/admin')
        await expect(page.getByRole('table')).toBeVisible()
        await expect(page.getByText('Signed in as dana (admin).')).toBeVisible()
        s.expectHits('auth/me', 'tasks', 'metrics')
        await shot(page, 'admin-admin', viewport, theme)
        record('admin-admin', viewport, theme, {
          ...(await measure(page)),
          focus: await focusWalk(page, 8),
        })
        if (viewport === MID) {
          await shot(page, 'admin-tiles', viewport, theme, page.locator('section[aria-label="Queue statistics"]'))
          // The release confirm, which names its holder only in the accessible
          // name -- so what it *looks* like is the whole question.
          await page.getByRole('button', { name: 'Release', exact: true }).first().click()
          await expect(page.getByText('Return this task to the open queue?')).toBeVisible()
          await shot(page, 'admin-release-confirm', viewport, theme, page.getByRole('table'))
        }
      })
    }
  }
})

test('the admin surface empty, as a reviewer', async ({ browser }, testInfo) => {
  test.setTimeout(180_000)
  const baseURL = baseURLOf(testInfo.project.use)
  for (const viewport of ALL_WIDTHS) {
    for (const theme of THEMES) {
      await withPage(browser, baseURL, viewport, theme, async (page) => {
        const s = await baseStubs(page, { username: 'alice', role: 'reviewer' })
        await s.on('tasks', '**/review/tasks*', (route) =>
          json(route, 200, { items: [], has_more: false }),
        )
        // A reviewer may read /metrics, and the rate is null here on purpose:
        // section 5.7's load-bearing null, which must not render as 0%.
        await s.on('metrics', '**/metrics', (route) =>
          json(route, 200, metrics({ auto_approval_rate: null, counts_by_status: {} })),
        )
        await page.goto('/app/admin')
        await expect(page.getByText('No open tasks, and none assigned to you')).toBeVisible()
        s.expectHits('tasks', 'metrics')
        await shot(page, 'admin-reviewer-empty', viewport, theme)
        record('admin-reviewer-empty', viewport, theme, await measure(page))
      })
    }
  }
})

// **Deleted 2026-08-25: 'the theme switch: an explicit choice must beat the OS
// preference'.**
//
// It drove `data-theme` by hand and asserted the precedence rule
// `:root:not([data-theme='light'])` implemented. That selector, the
// `prefers-color-scheme: dark` block around it and the `data-theme` opt-in were
// all removed from `tokens.css` when the owner ruled the app light-only, so
// there is no precedence left to beat.
//
// **It would have kept passing, and that is why it is deleted rather than
// left.** Its assertions were `Sign in` is visible plus two screenshots -- both
// still true against a light page under either OS preference. It would have
// gone on reporting green while measuring nothing, and its name would have gone
// on telling the next reader this app has a theme switch.

test('focus rings, as the browser actually paints them', async ({ browser }, testInfo) => {
  test.setTimeout(120_000)
  const baseURL = baseURLOf(testInfo.project.use)
  for (const theme of THEMES) {
    await withPage(browser, baseURL, MID, theme, async (page) => {
      await stubbedReview(page, fullReceipt())
      // Keyboard focus, so `:focus-visible` really applies. The crops are tight
      // because a 2px ring is invisible in a whole-page shot.
      await page.getByLabel('Total', { exact: true }).focus()
      await page.keyboard.press('Shift+Tab')
      await page.keyboard.press('Tab')
      await shot(page, 'focus-money-input', MID, theme, formSection(page))
      const approve = page.getByRole('button', { name: 'Approve' })
      await approve.focus()
      await page.keyboard.press('Shift+Tab')
      await page.keyboard.press('Tab')
      await shot(page, 'focus-approve-button', MID, theme, approve)
      // `<summary>` is **not** in `tokens.css`'s `:where(a, button, input, select,
      // textarea):focus-visible` list, so the findings rows fall back to the
      // browser's own ring. What that looks like is a claim only a picture can
      // settle, so here is the picture.
      const summary = page.locator('details summary').first()
      await summary.focus()
      await page.keyboard.press('Shift+Tab')
      await page.keyboard.press('Tab')
      await shot(page, 'focus-finding-summary', MID, theme, findingsSection(page))
      record('focus-rings', MID, theme, { focus: await focusWalk(page, 6) })
    })
  }
})
