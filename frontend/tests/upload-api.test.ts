import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
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

/** The server's own `_ALLOWED_SUFFIXES`, read out of `ingest.py` as text.
 *
 * A client-side copy of a server constant has to be pinned by something that
 * does not read that copy. Iterating `ACCEPTED_SUFFIXES` to check
 * `ACCEPTED_SUFFIXES` cannot fail for the thing it exists to check -- removing
 * an element removes its own assertion (ADR-0051). Reading the Python source is
 * the cheapest independent authority, and other tests in this suite already read
 * repo files this way.
 *
 * `dirname(fileURLToPath(import.meta.url))` rather than
 * `new URL(specifier, import.meta.url)`: Vite rewrites that *pattern* into a
 * static-asset URL, which jsdom resolves against the document base, leaving
 * `readFileSync` an http:// URL it dies on. `admin-screen.test.tsx` and
 * `receipts-screen.test.tsx` read their sources this way for the same reason,
 * and going through `import.meta.url` rather than `process.cwd()` keeps this
 * independent of where the runner was started.
 */
function parseAllowedSuffixes(source: string): string[] {
  const declaration = source.match(/_ALLOWED_SUFFIXES = frozenset\(([^)]*)\)/)
  if (declaration === null) {
    // Loudly. A renamed or reshaped declaration must break this guard, never
    // quietly reduce it to comparing the client's list against nothing.
    throw new Error('no `_ALLOWED_SUFFIXES = frozenset(...)` in ingest.py')
  }
  // `[A-Za-z0-9]`, not `[a-z]`. A class that only spells lowercase letters
  // DROPS `.jp2` or `.HEIC` from the parsed list instead of failing on it, so
  // the length guard never fires and the set equality below still passes --
  // while the client refuses a file the server accepts. That is a silent escape
  // inside a guard whose whole job is to stop one. Exercised on a fixture by
  // the test named `keeps a suffix with a digit or a capital in it`, because
  // proving it needs a suffix `ingest.py` does not currently declare.
  const suffixes = [...declaration[1].matchAll(/"(\.[A-Za-z0-9]+)"/g)].map((match) => match[1])
  if (suffixes.length === 0) {
    throw new Error('`_ALLOWED_SUFFIXES` parsed to nothing; its literal shape must have changed')
  }
  return suffixes
}

function serverAllowedSuffixes(): string[] {
  return parseAllowedSuffixes(
    readFileSync(
      join(
        dirname(fileURLToPath(import.meta.url)),
        '..',
        '..',
        'src',
        'receipts',
        'ingest',
        'ingest.py',
      ),
      'utf8',
    ),
  )
}

describe('what the client refuses before spending an upload', () => {
  it('names the size bound the server enforces, not a rounder one', () => {
    expect(MAX_UPLOAD_MB).toBe(25)
  })

  it('accepts each listed suffix in either case', () => {
    for (const suffix of ACCEPTED_SUFFIXES) {
      expect(rejectionReason({ name: `receipt${suffix}`, size: 1024 })).toBeNull()
      expect(rejectionReason({ name: `RECEIPT${suffix.toUpperCase()}`, size: 1024 })).toBeNull()
    }
  })

  it('keeps a suffix with a digit or a capital in it, rather than dropping it', () => {
    // Against a FIXTURE rather than against `ingest.py`: the failure needs a
    // suffix the server does not declare today, and editing the server's own
    // list to prove a client-side guard would be testing the mutation.
    //
    // Measured 2026-08-24 with the item pattern reverted to `"(\.[a-z]+)"`:
    // this parses to `['.jpg', '.pdf']` with no throw, so `serverAllowedSuffixes`
    // would return a SHORTER list, the length guard would not fire, and the set
    // equality below would go on passing while the client refused `.jp2`.
    const fixture = '_ALLOWED_SUFFIXES = frozenset({".jpg", ".jp2", ".HEIC", ".pdf"})'
    expect(parseAllowedSuffixes(fixture)).toEqual(['.jpg', '.jp2', '.HEIC', '.pdf'])
  })

  it('lists exactly what the server accepts, minus the PDF that cannot work', () => {
    const server = serverAllowedSuffixes()
    // The premise the whole exclusion rests on. If the server ever stops
    // accepting `.pdf`, the module's comment about being deliberately stricter
    // is stale, and the set equality below would go on passing without this.
    expect(server).toContain('.pdf')
    expect([...ACCEPTED_SUFFIXES].sort()).toEqual(
      server.filter((suffix) => suffix !== '.pdf').sort(),
    )
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

  it('refuses a file over the bound, names it, and accepts one exactly at it', () => {
    const tooBig = MAX_UPLOAD_MB * 1024 * 1024 + 1
    expect(rejectionReason({ name: 'big.jpg', size: tooBig })).toMatch(/25/)
    expect(rejectionReason({ name: 'ok.jpg', size: tooBig - 2 })).toBeNull()
    // Exactly at the bound. `ingest.py:112-113` computes `max_bytes = max_mb *
    // 1024 * 1024` and refuses on `>`, so the server ACCEPTS this file. A `>=`
    // here would refuse what the server takes -- the client substituting its
    // own guess for the server's verdict, which is the one thing this module
    // is not allowed to do.
    expect(rejectionReason({ name: 'exact.jpg', size: MAX_UPLOAD_MB * 1024 * 1024 })).toBeNull()
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
    // Bound to a local rather than re-read as `init?.body`: oxlint's
    // `no-unsafe-optional-chaining` fires on `(init?.body as FormData).get(...)`,
    // and it is right that the chain could short-circuit. The assertion below
    // is what makes the cast safe for the line after it.
    const body = init?.body
    expect(body).toBeInstanceOf(FormData)
    // The part name is contract, not decoration: the route declares
    // `file: UploadFile` (src/receipts/review/api.py:561), so `image` here
    // would 422 every real upload while every other assertion stayed green.
    expect((body as FormData).get('file')).toBe(file)
    // The browser must choose the multipart boundary. A Content-Type we set
    // here has no boundary and makes the body unparseable at the server.
    const headers = new Headers(init?.headers)
    expect(headers.get('Content-Type')).toBeNull()
  })

  it("surfaces the server's own reason when the server refuses", async () => {
    stubFetch(400, { detail: 'not a receipt image: image/gif' })
    const file = new File([new Uint8Array([1])], 'sneaky.jpg', { type: 'image/jpeg' })

    // The client checks an extension; the server sniffs bytes. They can
    // legitimately disagree, and the server is the one that knows.
    await expect(uploadReceipt(file)).rejects.toThrow(/not a receipt image/)
  })
})

describe('fetchProgress', () => {
  it('reads the three fields the route returns, from the route that returns them', async () => {
    const calls = stubFetch(200, { status: 'pending', stage: 'extract', detail: 'attempt 1' })
    expect(await fetchProgress('r-1')).toEqual({
      status: 'pending',
      stage: 'extract',
      detail: 'attempt 1',
    })
    // Without this the stub answers any path, so a typo'd route reads its
    // three fields out of a 404 that never happened.
    expect(calls[0][0]).toBe('/receipts/r-1/progress')
  })

  it('carries a null stage through as null, never as empty text', async () => {
    // `null` is not `''` (ADR-0027 decision 5). A null stage means nothing is
    // narrating; an empty string would render a blank row where none belongs.
    const calls = stubFetch(200, { status: 'pending', stage: null, detail: null })
    const report = await fetchProgress('r-1')
    expect(calls[0][0]).toBe('/receipts/r-1/progress')
    expect(report.stage).toBeNull()
    expect(report.detail).toBeNull()
  })

  it('encodes the id into the path instead of pasting it in', async () => {
    // An id is a path SEGMENT. Pasted raw, a `/` inside one silently addresses
    // a different route than the caller asked for. Every other interpolated
    // segment in `src/api/` encodes; this one is not the exception.
    const calls = stubFetch(200, { status: null, stage: null, detail: null })
    await fetchProgress('r 1/../secrets')
    expect(calls[0][0]).toBe('/receipts/r%201%2F..%2Fsecrets/progress')
  })
})
