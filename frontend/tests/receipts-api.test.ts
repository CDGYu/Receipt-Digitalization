import { afterEach, describe, expect, it, vi } from 'vitest'
import { downloadExportWorkbook, fetchExportReceipts } from '../src/api/receipts'

afterEach(() => {
  vi.unstubAllGlobals()
})

// `vi.unstubAllGlobals` does not undo `vi.spyOn`, and no config here sets
// `restoreMocks`, so `spyOnAnchorClick`'s `document.createElement` stub would
// otherwise outlive the test that installed it -- and the *next*
// `spyOnAnchorClick` would then call the stub for its own `createElement('a')`
// and be handed the previous test's element, `download` already set.
//
// **Without this hook the fallback test cannot fail.** Measured, by replacing
// `anchor.download = filename ?? FALLBACK_FILENAME` with
// `if (filename !== null) anchor.download = filename` -- deleting the fallback
// this file exists to pin: with this hook, 1 failed | 4 passed; with it
// disabled, 5 passed. The header test runs first and leaves
// `download === 'receipts-export.xlsx'` on the shared anchor, which is the
// value the fallback test then reads back as its own.
//
// (The stub also answers *every* tag with the anchor, so a stray
// `createElement('div')` anywhere later in the file would get one too.)
afterEach(() => {
  vi.restoreAllMocks()
})

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function stub(response: Response) {
  const fetchMock = vi.fn().mockResolvedValue(response)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

/** A binary body, which `jsonResponse` cannot express. */
function blobResponse(status: number, body: string, headers?: Record<string, string>): Response {
  // Encoded bytes, not a `Blob`: under `environment: 'jsdom'` the global
  // `Blob` is jsdom's and has no `stream()`, while jsdom supplies no
  // `Response`, so the global `Response` is Node's undici -- which duck-types
  // the jsdom Blob as blob-like and then calls `stream()` on it. Measured:
  // `TypeError: object.stream is not a function`. The two can never combine.
  return new Response(new TextEncoder().encode(body), { status, headers })
}

/** Capture the anchor `downloadExportWorkbook` builds, without navigating.
 *
 *  jsdom does not act on `click`, so nothing escapes the test; the spy exists
 *  to read `download` and `href` back off the element -- both of which the
 *  header test does read, so this is a description of the file and not of an
 *  intention.
 *
 *  `createObjectURL` is stubbed for two jobs at once: it makes the object URL
 *  a known constant (`blob:stub`) that `href` and `revokeObjectURL` can be
 *  pinned against, and it records the blob it was handed, which is the only
 *  link between the bytes `requestBlob` returned and the thing the anchor
 *  points at. Read it back with `vi.mocked(URL.createObjectURL).mock.calls`. */
function spyOnAnchorClick(): HTMLAnchorElement {
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:stub')
  const anchor = document.createElement('a')
  vi.spyOn(anchor, 'click').mockImplementation(() => {})
  vi.spyOn(document, 'createElement').mockReturnValue(anchor)
  return anchor
}

describe('fetchExportReceipts', () => {
  it('asks for a page with the limit and offset it was given', async () => {
    // **Distinct values, and the whole URL.** `{limit: 50, offset: 50}` cannot
    // tell the two parameters apart -- swapping the `query.set` calls passed --
    // and `toContain('limit=50')` is satisfied by `limit=500` as well.
    const fetchMock = stub(jsonResponse(200, { items: [], has_more: false }))
    await fetchExportReceipts({ limit: 25, offset: 50 })
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/export/receipts?limit=25&offset=50')
  })

  it('forwards the status and confidence filters under the names the route reads', async () => {
    // **The wire names, not the caller's.** `GET /export/receipts` declares
    // `status` and `min_confidence`; TypeScript spells the second one
    // `minConfidence`, and a filter sent as `minconfidence` or `min_conf` is
    // ignored in silence by FastAPI — the page comes back unfiltered and looks
    // exactly like a page that had nothing to filter.
    //
    // Distinct values and the whole URL, for the reason the test above gives.
    const fetchMock = stub(jsonResponse(200, { items: [], has_more: false }))
    await fetchExportReceipts({
      limit: 25,
      offset: 50,
      status: 'needs_review',
      minConfidence: '0.75',
    })
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/export/receipts?limit=25&offset=50&status=needs_review&min_confidence=0.75',
    )
  })

  it('omits a filter that was not chosen rather than sending it empty', async () => {
    // `status=` with no value is not "no filter" to FastAPI: it fails
    // validation against `ReceiptStatus | None` and the page 422s. Leaving the
    // key out entirely is what "all receipts" means on the wire.
    const fetchMock = stub(jsonResponse(200, { items: [], has_more: false }))
    await fetchExportReceipts({ limit: 25, offset: 0 })
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/export/receipts?limit=25&offset=0')
  })

  it('asks for the export scope, not the unfiltered receipts list', async () => {
    // The whole design rests on this path. `/receipts` would silently widen it.
    // A non-empty page with `has_more: true`, so that a body invented by this
    // function rather than read off the response cannot match.
    const page = {
      items: [
        {
          id: '1f0b2c3d',
          status: 'needs_review',
          confidence: '0.42',
          merchant_name_raw: 'Kopi Roasters',
          txn_date: '2026-08-01',
          currency: 'PHP',
          total: '19.99',
          created_at: '2026-08-01T09:15:00+00:00',
        },
      ],
      has_more: true,
    }
    const fetchMock = stub(jsonResponse(200, page))
    await expect(fetchExportReceipts()).resolves.toEqual(page)
    // Exactly this path, which pins the suffix ternary too: with no params the
    // query string is omitted entirely, so a bare trailing `?` fails here.
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/export/receipts')
  })
})

describe('downloadExportWorkbook', () => {
  it('names the downloaded file from the header when there is one', async () => {
    stub(
      blobResponse(200, 'x', {
        'Content-Disposition': 'attachment; filename="receipts-export.xlsx"',
      }),
    )
    const anchor = spyOnAnchorClick()
    await downloadExportWorkbook()
    expect(anchor.download).toBe('receipts-export.xlsx')
    // **A `download` anchor with no `href` downloads nothing in a browser**, and
    // until this line every test passed with `anchor.href = url` deleted -- the
    // feature's whole user-visible effect could regress green. Read off the
    // property rather than `getAttribute`: measured, jsdom leaves a `blob:` URL
    // opaque, so both return exactly the assigned string here.
    expect(anchor.href).toBe('blob:stub')
    // ...and that URL is made from the bytes that arrived. Nothing else ties
    // `requestBlob`'s body to the anchor, so `URL.createObjectURL(new Blob())`
    // also passed. Asserted by content, not `toBeInstanceOf(Blob)`: the body
    // comes back as Node's Blob, which is not the jsdom global (measured).
    const created = vi.mocked(URL.createObjectURL).mock.calls[0]?.[0]
    expect(await (created as Blob).text()).toBe('x')
  })

  it('falls back to a constant name when the header is absent', async () => {
    stub(blobResponse(200, 'x'))
    const anchor = spyOnAnchorClick()
    await downloadExportWorkbook()
    expect(anchor.download).toBe('receipts-export.xlsx')
  })

  it('forwards workbook filters under the same names as the preview list', async () => {
    const fetchMock = stub(blobResponse(200, 'x'))
    spyOnAnchorClick()
    await downloadExportWorkbook({ status: 'needs_review', minConfidence: '0.75' })
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/export/xlsx?status=needs_review&min_confidence=0.75',
    )
  })

  it('revokes the object URL it created', async () => {
    stub(blobResponse(200, 'x'))
    const revoke = vi.spyOn(URL, 'revokeObjectURL')
    spyOnAnchorClick()
    await downloadExportWorkbook()
    // The URL it created, not merely *a* URL: revoking some other string leaves
    // the blob attached to the document for its lifetime, and a bare call count
    // cannot see that.
    expect(revoke).toHaveBeenCalledExactlyOnceWith('blob:stub')
  })
})
