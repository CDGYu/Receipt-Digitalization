import { describe, expect, it, vi, beforeEach } from 'vitest'
import { ApiError, request, requestBlob, onUnauthorized } from '../src/api/client'

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

beforeEach(() => {
  onUnauthorized(() => {})
})

describe('request', () => {
  it('returns the parsed body on success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(200, { ok: true })))
    await expect(request<{ ok: boolean }>('/health')).resolves.toEqual({ ok: true })
  })

  it('unwraps the API error envelope', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(400, { error: { message: 'no such path' } })),
    )
    await expect(request('/receipts/x')).rejects.toMatchObject({
      status: 400,
      message: 'no such path',
    })
  })

  it('does not throw a parse error when the body is not JSON', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('<html>502</html>', { status: 502 })),
    )
    // `request<never>`, not a bare `request`: with `T` inferred as `unknown` the
    // promise is `Promise<unknown>`, `.catch` widens back to `unknown`, and
    // `error.status` below is `TS18046: 'error' is of type 'unknown'`. This call
    // is only ever expected to reject, so `never` is the honest success type.
    const error = await request<never>('/receipts').catch((e) => e as ApiError)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(502)
  })

  it('calls the unauthorized handler on 401 and still rejects', async () => {
    const handler = vi.fn()
    onUnauthorized(handler)
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(401, { error: { message: 'not authenticated' } })),
    )
    await expect(request('/receipts')).rejects.toBeInstanceOf(ApiError)
    expect(handler).toHaveBeenCalledOnce()
  })
})

// --------------------------------------------------------------------------- //
// The success path (fix round 1, finding 1)
// --------------------------------------------------------------------------- //

describe('request on a success with no JSON to parse', () => {
  it('resolves for a 204, which POST /auth/logout really returns', async () => {
    // The logout handler in `src/receipts/review/auth.py` ends
    // `return Response(status_code=204)`.
    // `.json()` on an empty body throws SyntaxError, which is not an ApiError,
    // so every consumer that discriminates on ApiError loses the status.
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })))
    await expect(request('/auth/logout', { method: 'POST' })).resolves.toBeUndefined()
  })

  it('raises an ApiError carrying the real status when a 200 body is not JSON', async () => {
    // A proxy or a crashed worker answering 200 with an HTML error page. The
    // error path already degrades gracefully; the success path must too.
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response('<html>hello</html>', {
          status: 200,
          headers: { 'Content-Type': 'text/html' },
        }),
      ),
    )
    const error = await request<never>('/receipts').catch((e) => e as ApiError)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(200)
  })
})

// --------------------------------------------------------------------------- //
// The error envelope is NOT universal (fix round 1, finding 2)
// --------------------------------------------------------------------------- //

describe('request on a body outside the {error:{message}} envelope', () => {
  it("surfaces FastAPI's 422 validation detail rather than a bare status", async () => {
    // `_install_error_handlers` (api.py:128-151) covers ValueError, DBAPIError
    // and StarletteHTTPException -- NOT RequestValidationError, so a 422 keeps
    // FastAPI's own `detail` list. PATCH /receipts/{id} is the route most
    // likely to produce one, which is Task 4's whole surface.
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(422, {
          detail: [
            { type: 'missing', loc: ['body'], msg: 'Field required' },
            { type: 'decimal_parsing', loc: ['body', 'totals', 'total'], msg: 'Input should be a valid decimal' },
          ],
        }),
      ),
    )
    const error = await request<never>('/receipts/x').catch((e) => e as ApiError)
    expect(error.status).toBe(422)
    expect(error.message).toBe('Field required; Input should be a valid decimal')
  })

  it('surfaces a string detail', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(403, { detail: 'insufficient role' })),
    )
    const error = await request<never>('/export/xlsx').catch((e) => e as ApiError)
    expect(error.message).toBe('insufficient role')
  })

  it('still prefers the envelope when both are present', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(400, { error: { message: 'from the envelope' }, detail: 'from detail' }),
      ),
    )
    const error = await request<never>('/receipts').catch((e) => e as ApiError)
    expect(error.message).toBe('from the envelope')
  })

  it('falls back to the status when a JSON body carries neither', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(500, { unexpected: true })))
    const error = await request<never>('/receipts').catch((e) => e as ApiError)
    expect(error.message).toBe('request failed (500)')
  })
})

// --------------------------------------------------------------------------- //
// Caller-supplied headers (fix round 1, finding 3)
// --------------------------------------------------------------------------- //

/** What `fetch` was actually called with, normalised so the assertion does not
 *  depend on which of the three legal `HeadersInit` shapes came back. */
function sentHeaders(fetchMock: { mock: { calls: unknown[][] } }): Headers {
  const init = fetchMock.mock.calls[0][1] as RequestInit
  return new Headers(init.headers)
}

describe('request headers', () => {
  it('preserves a Headers instance', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, {}))
    vi.stubGlobal('fetch', fetchMock)
    await request('/receipts', { headers: new Headers({ 'X-Correlation-Id': 'abc' }) })
    const sent = sentHeaders(fetchMock)
    expect(sent.get('X-Correlation-Id')).toBe('abc')
    expect(sent.get('Content-Type')).toBe('application/json')
  })

  it('preserves a tuple array', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, {}))
    vi.stubGlobal('fetch', fetchMock)
    await request('/receipts', { headers: [['X-Correlation-Id', 'abc']] })
    const sent = sentHeaders(fetchMock)
    expect(sent.get('X-Correlation-Id')).toBe('abc')
    expect(sent.get('Content-Type')).toBe('application/json')
  })

  it('preserves a plain record', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, {}))
    vi.stubGlobal('fetch', fetchMock)
    await request('/receipts', { headers: { 'X-Correlation-Id': 'abc' } })
    expect(sentHeaders(fetchMock).get('X-Correlation-Id')).toBe('abc')
  })

  it('lets the caller override Content-Type instead of duplicating it', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, {}))
    vi.stubGlobal('fetch', fetchMock)
    await request('/receipts', { headers: { 'Content-Type': 'application/merge-patch+json' } })
    expect(sentHeaders(fetchMock).get('Content-Type')).toBe('application/merge-patch+json')
  })

  it('leaves Content-Type to the browser for a FormData body', async () => {
    // POST /upload takes multipart. Only the browser can write the boundary
    // parameter, so a default `application/json` here makes the upload
    // unparseable -- and a caller cannot un-set a header we already set.
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(202, {}))
    vi.stubGlobal('fetch', fetchMock)
    const body = new FormData()
    body.append('file', new Blob(['x']), 'receipt.jpg')
    await request('/upload', { method: 'POST', body })
    expect(sentHeaders(fetchMock).get('Content-Type')).toBeNull()
  })
})

/** A binary body, which `jsonResponse` cannot express.
 *
 *  The bytes go in as a `Uint8Array` rather than as `new Blob([body])`, which
 *  throws `TypeError: object.stream is not a function` here. Under
 *  `environment: 'jsdom'` the two globals come from different implementations:
 *  jsdom supplies `Blob` (and its Blob has no `stream()` -- measured on jsdom
 *  30.0.1) while jsdom supplies no `Response` at all, so `Response` is Node's.
 *  Node's constructor accepts the jsdom Blob as blob-like on its
 *  `arrayBuffer`/`Symbol.toStringTag` duck-type and then calls `stream()` on
 *  it. A `Uint8Array` is read by the same one implementation at both ends.
 */
function blobResponse(status: number, body: string, headers?: Record<string, string>): Response {
  return new Response(new TextEncoder().encode(body), { status, headers })
}

describe('requestBlob', () => {
  it('returns the body as a blob on success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(blobResponse(200, 'xlsx-bytes')))
    const { blob } = await requestBlob('/export/xlsx')
    expect(await blob.text()).toBe('xlsx-bytes')
  })

  it('reads the filename out of Content-Disposition', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        blobResponse(200, 'x', {
          'Content-Disposition': 'attachment; filename="receipts-export.xlsx"',
        }),
      ),
    )
    const { filename } = await requestBlob('/export/xlsx')
    expect(filename).toBe('receipts-export.xlsx')
  })

  it('reports no filename when the header is absent, rather than inventing one', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(blobResponse(200, 'x')))
    const { filename } = await requestBlob('/export/xlsx')
    expect(filename).toBeNull()
  })

  it("surfaces the server's message on a 400, not a generic one", async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(400, { error: { message: 'narrow the filter and try again' } }),
      ),
    )
    await expect(requestBlob('/export/xlsx')).rejects.toThrow('narrow the filter and try again')
  })

  it('fires the unauthorized handler on a 401, like request does', async () => {
    const handler = vi.fn()
    onUnauthorized(handler)
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(401, { error: { message: 'not authenticated' } })),
    )
    await expect(requestBlob('/export/xlsx')).rejects.toThrow()
    expect(handler).toHaveBeenCalledOnce()
  })

  // `rejects.toThrow(string)` is only a substring match against `.message`, and
  // `rejects.toThrow()` matches any thrown Error at all -- so both tests above
  // stay green if these throws become `new Error(...)`. The type and the status
  // are what Task 4 discriminates on, and they are what `request`'s own failure
  // tests pin. Pinning the message alone pins nothing.
  it('throws an ApiError carrying the status on a 400, not a bare Error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(400, { error: { message: 'narrow the filter and try again' } }),
      ),
    )
    const error = await requestBlob('/export/xlsx').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(400)
  })

  it('throws an ApiError carrying the status on a 401, not a bare Error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(401, { error: { message: 'not authenticated' } })),
    )
    const error = await requestBlob('/export/xlsx').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(401)
  })

  it('turns a body it cannot read into an ApiError, like request does', async () => {
    // `fetch` resolves as soon as the headers arrive, so a connection dropped
    // mid-download rejects `response.blob()` with a raw `TypeError` -- the most
    // likely real failure of a large .xlsx export, which is the whole reason
    // this function exists. `parseSuccess` guards the equivalent read for the
    // same reason: every consumer that discriminates on `ApiError` falls into
    // its generic branch on a raw TypeError and loses the status.
    const truncated = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('partial'))
        controller.error(new TypeError('terminated'))
      },
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(truncated, { status: 200 })))
    const error = await requestBlob('/export/xlsx').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).message).toBe('the response to /export/xlsx could not be read')
  })
})
