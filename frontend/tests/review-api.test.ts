import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../src/api/client'
import { fetchImageUrl, fetchNext, fetchReceipt } from '../src/api/review'

afterEach(() => {
  vi.unstubAllGlobals()
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

describe('fetchNext', () => {
  it('returns the empty-queue body as a value rather than treating it as an error', async () => {
    // 200 with `{"task": null}` (src/receipts/review/api.py:496-500). If this
    // ever rejected, the screen would show a failure for a working, idle queue.
    const fetchMock = stub(jsonResponse(200, { task: null }))

    await expect(fetchNext()).resolves.toEqual({ task: null })
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/review/next')
  })
})

describe('fetchReceipt', () => {
  it('asks for the receipt by id, with the id encoded', async () => {
    const fetchMock = stub(jsonResponse(200, { id: 'a b/c' }))

    await fetchReceipt('a b/c')

    // The route parses a UUID, so an unencoded `/` would silently address a
    // different path (`/receipts/a b/c` is a 404 on an unrelated route shape)
    // instead of reaching the receipt route and being refused as a 422.
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/receipts/a%20b%2Fc')
  })
})

describe('fetchImageUrl', () => {
  it('unwraps the {url} envelope and never sends the blob through request', async () => {
    const signed = '/receipts/a1/image/blob?variant=original&exp=1780000000&sig=abc'
    const fetchMock = stub(jsonResponse(200, { url: signed }))

    await expect(fetchImageUrl('a1')).resolves.toBe(signed)
    // The JSON envelope, not the bytes: `request` always parses its body, so the
    // blob sub-route must only ever be reached by an `<img src>`.
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/receipts/a1/image')
  })

  it('encodes the id here too, not only on the detail route', async () => {
    // `fetchReceipt` and this function build their paths independently, so
    // pinning one says nothing about the other -- fix round 1 found this one
    // unbound while the table implied both were covered.
    const fetchMock = stub(jsonResponse(200, { url: '/blob' }))

    await fetchImageUrl('a b/c')

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/receipts/a%20b%2Fc/image')
  })

  it('raises an ApiError, not a TypeError, when the reply carries no url', async () => {
    // `request` resolves an empty body to `undefined` rather than throwing, so
    // without the guard this is `Cannot read properties of undefined (reading
    // 'url')` -- a message that names nothing a reviewer or an engineer can act
    // on, arriving from a helper rather than from the failure.
    // `null`, not `''`: the `Response` constructor refuses a 204 with any body
    // at all, which is the same reason `request` has an empty-body branch.
    stub(new Response(null, { status: 204 }))

    await expect(fetchImageUrl('a1')).rejects.toThrow(ApiError)
    await expect(fetchImageUrl('a1')).rejects.toThrow('no image link in the reply for receipt a1')
  })
})
