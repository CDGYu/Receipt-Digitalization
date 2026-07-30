import { describe, expect, it, vi, beforeEach } from 'vitest'
import { ApiError, request, onUnauthorized } from '../src/api/client'

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
