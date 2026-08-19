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
 *  to read `download` and `href` back off the element. */
function spyOnAnchorClick(): HTMLAnchorElement {
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:stub')
  const anchor = document.createElement('a')
  vi.spyOn(anchor, 'click').mockImplementation(() => {})
  vi.spyOn(document, 'createElement').mockReturnValue(anchor)
  return anchor
}

describe('fetchExportReceipts', () => {
  it('asks for a page with the limit and offset it was given', async () => {
    const fetchMock = stub(jsonResponse(200, { items: [], has_more: false }))
    await fetchExportReceipts({ limit: 50, offset: 50 })
    const url = String(fetchMock.mock.calls[0]?.[0])
    expect(url).toContain('limit=50')
    expect(url).toContain('offset=50')
  })

  it('asks for the export scope, not the unfiltered receipts list', async () => {
    // The whole design rests on this path. `/receipts` would silently widen it.
    const fetchMock = stub(jsonResponse(200, { items: [], has_more: false }))
    await fetchExportReceipts()
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain('/export/receipts')
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
  })

  it('falls back to a constant name when the header is absent', async () => {
    stub(blobResponse(200, 'x'))
    const anchor = spyOnAnchorClick()
    await downloadExportWorkbook()
    expect(anchor.download).toBe('receipts-export.xlsx')
  })

  it('revokes the object URL it created', async () => {
    stub(blobResponse(200, 'x'))
    const revoke = vi.spyOn(URL, 'revokeObjectURL')
    spyOnAnchorClick()
    await downloadExportWorkbook()
    expect(revoke).toHaveBeenCalledOnce()
  })
})
