import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  ACCEPTED_SUFFIXES,
  MAX_UPLOAD_MB,
  fetchProgress,
  rejectionReason,
  uploadReceipt,
} from '../src/api/upload'

afterEach(() => {
  vi.unstubAllGlobals()
})

/** A fetch that records what it was called with and replies once. */
function stubFetch(status: number, body: unknown) {
  const calls: Array<[string, RequestInit | undefined]> = []
  vi.stubGlobal('fetch', (path: string, init?: RequestInit) => {
    calls.push([path, init])
    return Promise.resolve(
      new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
  })
  return calls
}

describe('what the client refuses before spending an upload', () => {
  it('names the size bound the server enforces, not a rounder one', () => {
    expect(MAX_UPLOAD_MB).toBe(25)
  })

  it('accepts every suffix the server accepts, in either case', () => {
    for (const suffix of ACCEPTED_SUFFIXES) {
      expect(rejectionReason({ name: `receipt${suffix}`, size: 1024 })).toBeNull()
      expect(rejectionReason({ name: `RECEIPT${suffix.toUpperCase()}`, size: 1024 })).toBeNull()
    }
  })

  it('refuses a PDF, which the server accepts and then always fails to process', () => {
    // ISSUE-027: `.pdf` is in the server's accepted suffixes, so this refusal
    // is deliberately STRICTER than the server. Accepting a file guaranteed to
    // die at `preprocess` is the worst of the options.
    const reason = rejectionReason({ name: 'receipt.pdf', size: 1024 })
    expect(reason).not.toBeNull()
    expect(reason).toMatch(/pdf/i)
  })

  it('refuses an unknown suffix and says what it accepts', () => {
    const reason = rejectionReason({ name: 'notes.txt', size: 1024 })
    expect(reason).toMatch(/\.jpg/)
  })

  it('refuses a file over the bound and names the bound', () => {
    const tooBig = MAX_UPLOAD_MB * 1024 * 1024 + 1
    expect(rejectionReason({ name: 'big.jpg', size: tooBig })).toMatch(/25/)
    expect(rejectionReason({ name: 'ok.jpg', size: tooBig - 2 })).toBeNull()
  })

  it('refuses a name with no suffix at all rather than letting it through', () => {
    expect(rejectionReason({ name: 'receipt', size: 1024 })).not.toBeNull()
  })
})

describe('uploadReceipt', () => {
  it('sends the file as multipart and lets the browser set the boundary', async () => {
    const calls = stubFetch(202, { receipt_id: 'r-1', image_key: 'k', status: 'pending' })
    const file = new File([new Uint8Array([1, 2, 3])], 'receipt.jpg', { type: 'image/jpeg' })

    const accepted = await uploadReceipt(file)

    expect(accepted.receipt_id).toBe('r-1')
    const [path, init] = calls[0]
    expect(path).toBe('/upload')
    expect(init?.method).toBe('POST')
    expect(init?.body).toBeInstanceOf(FormData)
    // The browser must choose the multipart boundary. A Content-Type we set
    // here has no boundary and makes the body unparseable at the server.
    const headers = new Headers(init?.headers)
    expect(headers.get('Content-Type')).toBeNull()
  })

  it('surfaces the server-s own reason when the server refuses', async () => {
    stubFetch(400, { detail: 'not a receipt image: image/gif' })
    const file = new File([new Uint8Array([1])], 'sneaky.jpg', { type: 'image/jpeg' })

    // The client checks an extension; the server sniffs bytes. They can
    // legitimately disagree, and the server is the one that knows.
    await expect(uploadReceipt(file)).rejects.toThrow(/not a receipt image/)
  })
})

describe('fetchProgress', () => {
  it('reads the three fields the route returns', async () => {
    stubFetch(200, { status: 'pending', stage: 'extract', detail: 'attempt 1' })
    expect(await fetchProgress('r-1')).toEqual({
      status: 'pending',
      stage: 'extract',
      detail: 'attempt 1',
    })
  })

  it('carries a null stage through as null, never as empty text', async () => {
    // `null` is not `''` (ADR-0027 decision 5). A null stage means nothing is
    // narrating; an empty string would render a blank row where none belongs.
    stubFetch(200, { status: 'pending', stage: null, detail: null })
    const report = await fetchProgress('r-1')
    expect(report.stage).toBeNull()
    expect(report.detail).toBeNull()
  })
})
