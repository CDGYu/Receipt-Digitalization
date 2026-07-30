import { cleanup, render, screen, waitFor, fireEvent } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ImagePane } from '../src/review/ImagePane'
import { ApiError } from '../src/api/client'

/** Unmount between tests. Not optional here, and not a style preference.
 *
 * `globals: true` is absent from vite.config.ts on purpose, so
 * `@testing-library/react` installs no auto-cleanup. The plan's version of this
 * file had no `afterEach`, and the failure was measured rather than guessed: the
 * second test's `findByAltText` matched the **first** test's leaked `<img>` --
 * the fresh pane still showed "Loading the receipt image…" and had no image of
 * its own yet -- so `fireEvent.error` went to the finished component, the new
 * pane's `fetchUrl` was never called a second time, and the run failed with
 * `expected "vi.fn()" to be called 2 times, but got 1 times`. The plan's own
 * `ImagePane`, pasted in verbatim, failed the same way.
 */
afterEach(cleanup)

describe('ImagePane', () => {
  it('re-fetches the signed URL once when the signature has expired', async () => {
    const fetchUrl = vi
      .fn()
      .mockResolvedValueOnce('/receipts/r1/image/blob?sig=stale')
      .mockResolvedValueOnce('/receipts/r1/image/blob?sig=fresh')

    render(<ImagePane receiptId="r1" fetchUrl={fetchUrl} />)

    const image = await screen.findByAltText(/receipt/i)
    fireEvent.error(image)

    await waitFor(() => expect(fetchUrl).toHaveBeenCalledTimes(2))
    // Silently: one expired link is an expected event on a 300s TTL, not
    // something to interrupt a reviewer with.
    await waitFor(() =>
      expect(screen.getByAltText(/receipt/i).getAttribute('src')).toBe(
        '/receipts/r1/image/blob?sig=fresh',
      ),
    )
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('shows a visible failure rather than a blank pane after the retry fails', async () => {
    // The same URL twice, which is the case a changing `src` would not cover:
    // `exp` only moves once a second, and a load failing because the blob is
    // missing from storage never resolves by re-signing at all.
    const fetchUrl = vi.fn().mockResolvedValue('/receipts/r1/image/blob?sig=stale')
    render(<ImagePane receiptId="r1" fetchUrl={fetchUrl} />)

    const image = await screen.findByAltText(/receipt/i)
    fireEvent.error(image)
    await waitFor(() => expect(fetchUrl).toHaveBeenCalledTimes(2))
    fireEvent.error(screen.getByAltText(/receipt/i))

    await waitFor(() => expect(screen.getByRole('alert')).toBeDefined())
    // Once, not until it gives up: a link that will not work is not worth a
    // retry loop against the API.
    expect(fetchUrl).toHaveBeenCalledTimes(2)
  })

  it('remounts the image when the re-signed link comes back byte-identical', async () => {
    // Two calls inside the same second sign the same `exp`, so the same `sig`,
    // so the same URL -- and a load failing because the blob is missing from
    // storage will never resolve by re-signing at all. Measured with a
    // `MutationObserver`: re-rendering an `<img>` with an unchanged `src` gives
    // zero attribute mutations (a changed one gives `["src"]`), so without a
    // fresh element nothing is re-requested, no second `error` arrives, and the
    // pane sits on a broken image for ever. A *different* DOM node is what makes
    // the retry real, and it is the half of this that jsdom can actually show.
    const fetchUrl = vi.fn().mockResolvedValue('/receipts/r1/image/blob?sig=same')
    render(<ImagePane receiptId="r1" fetchUrl={fetchUrl} />)

    const first = await screen.findByAltText(/receipt/i)
    fireEvent.error(first)
    await waitFor(() => expect(fetchUrl).toHaveBeenCalledTimes(2))

    await waitFor(() => expect(screen.getByAltText(/receipt/i)).not.toBe(first))
    expect(screen.getByAltText(/receipt/i).getAttribute('src')).toBe(first.getAttribute('src'))
  })

  it('says so on screen when the first link request fails outright', async () => {
    // The plan attached no rejection handler to this promise, so a 404 or a
    // dropped connection became an unhandled rejection and the pane stayed
    // blank -- a failure path ending in nothing at all.
    const fetchUrl = vi.fn().mockRejectedValue(new ApiError(404, 'no receipt with id r1'))
    render(<ImagePane receiptId="r1" fetchUrl={fetchUrl} />)

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('no receipt with id r1')
    expect(screen.queryByAltText(/receipt/i)).toBeNull()
  })

  it('says so on screen when re-signing the link fails', async () => {
    // The plan's retry was `setUrl(await fetchUrl(receiptId))` inside an async
    // event handler: nothing catches that rejection either.
    const fetchUrl = vi
      .fn()
      .mockResolvedValueOnce('/receipts/r1/image/blob?sig=stale')
      .mockRejectedValueOnce(new ApiError(401, 'not signed in'))
    render(<ImagePane receiptId="r1" fetchUrl={fetchUrl} />)

    fireEvent.error(await screen.findByAltText(/receipt/i))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('not signed in')
  })

  it('zooms and rotates the image it is showing', async () => {
    const fetchUrl = vi.fn().mockResolvedValue('/receipts/r1/image/blob?sig=s')
    render(<ImagePane receiptId="r1" fetchUrl={fetchUrl} />)

    const image = await screen.findByAltText(/receipt/i)
    expect(image.getAttribute('style')).toBe('transform: scale(1) rotate(0deg);')

    fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }))
    fireEvent.click(screen.getByRole('button', { name: 'Rotate' }))

    expect(screen.getByAltText(/receipt/i).getAttribute('style')).toBe(
      'transform: scale(1.25) rotate(90deg);',
    )
  })
})
