import { useEffect, useRef, useState } from 'react'

/** The receipt image, with the one retry its signed link needs.
 *
 * `GET /receipts/{id}/image` mints a link signed for `image_url_ttl_s`
 * (config/settings.py:131, default 300s) -- minutes, which a reviewer working a
 * single awkward receipt can outlive. Once it lapses the blob sub-route answers
 * `403 invalid or expired image link` (review/api.py:458-464). The `<img>`'s
 * `onError` is this component's only signal that anything went wrong with a
 * load, so one silent re-fetch is wired to it and a second failure is shown.
 *
 * **No test here drives `onError` through a real request.** The suite runs on
 * jsdom with no `resources: 'usable'` (vite.config.ts), so nothing fetches an
 * image and the tests call `fireEvent.error` directly. What a browser does with
 * a 403 image response is therefore **not measured**; what *is* measured is that
 * each of the three failure paths below puts words on screen.
 *
 * The three, none of which may end in a no-op or a console line:
 *
 *   1. the first `fetchUrl` rejects (401, 404, a dropped connection) -- there is
 *      no link to render, so the pane says so. The plan's version had no
 *      rejection handler on this promise at all, which made it an unhandled
 *      rejection and left the pane blank for ever.
 *   2. the image fails to load once -- re-fetch, silently, exactly once.
 *   3. the retry's `fetchUrl` rejects, or the second load fails too -- shown.
 *
 * "Exactly once" is true **by construction**, not by event timing: the spent-retry
 * flag is a `useRef`, so the second of two `error` events dispatched inside one
 * `act()` sees it already set. Held in `useState` it did not -- both handlers read
 * the pre-update value and both re-fetched (measured: 3 calls to `fetchUrl` where
 * the contract allows 2, pinned by `re-signs once even when two error events
 * arrive in the same batch`).
 *
 * **The failure is not a dead end.** It replaces only the image, never the pane:
 * the zoom and rotate controls stay put and an explicit retry sits beside the
 * message. That retry re-asks for a link and nothing else -- it must never reach
 * `fetchNext`, which is a claiming write, so the only escape from a broken image
 * is not a page reload that strands the reviewer's queue task.
 *
 * **Why the retry does not depend on the URL changing.** A re-signed link is
 * usually different (`exp` moves, so `sig` moves), but two calls inside the same
 * second produce byte-identical URLs -- and if the load is failing for a reason
 * expiry never explains, such as the blob being absent from storage
 * (review/api.py:472-477), an identical link is the normal case rather than a
 * corner. Re-rendering with an unchanged `src` is then a no-op all the way down:
 * **measured** with a `MutationObserver` over the `<img>`, React records zero
 * attribute mutations for a same-value `src` and exactly one (`["src"]`) for a
 * changed one. Nothing is written, so nothing is re-requested and no second
 * `error` can arrive. `generation` -- bumped every time a link is installed, and
 * used as the `<img>` key -- forces a fresh element instead, which the tests pin
 * by asserting the node identity changes.
 *
 * What a browser does with that fresh element is **not measured** here; jsdom
 * loads no images. What is measured is the DOM half: same URL in, different node
 * out, and the failure still reaching the screen.
 */
export interface ImagePaneProps {
  readonly receiptId: string
  readonly fetchUrl: (id: string) => Promise<string>
}

interface Source {
  readonly url: string
  readonly generation: number
}

const ZOOM_STEP = 1.25
const QUARTER_TURN = 90
const FULL_TURN = 360

/** Shared by the mount effect and the explicit retry -- both are "ask for a link
 *  from nothing", and a reviewer should not get two different sentences for the
 *  same failure depending on which one asked. */
const LINK_FAILED = 'Could not get a link to the receipt image'

/** A caught value as one line a reviewer can read and quote.
 *
 * `ApiError` extends `Error`, so this surfaces the API's own message (the
 * `{"error": {"message": ...}}` body, or FastAPI's `detail`) rather than
 * flattening every failure into one house sentence.
 */
function messageFor(prefix: string, caught: unknown): string {
  return caught instanceof Error ? `${prefix}: ${caught.message}` : prefix
}

export function ImagePane({ receiptId, fetchUrl }: ImagePaneProps) {
  const [source, setSource] = useState<Source | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [zoom, setZoom] = useState(1)
  const [rotation, setRotation] = useState(0)
  /** Whether the one silent re-sign has already been spent. A ref, not state:
   *  two `error` events in one batch must not both read `false`. */
  const retried = useRef(false)

  useEffect(() => {
    // Reset rather than rely on the caller remounting us: a new receipt gets its
    // own retry budget, and a failure from the previous one must not survive
    // into it. `ReviewScreen` also passes a `key`, so in the app this branch is
    // belt and braces; on its own the component is still correct -- which
    // `starts clean when it is handed a different receipt` pins.
    let live = true
    setSource(null)
    setFailure(null)
    retried.current = false
    fetchUrl(receiptId).then(
      (url) => {
        if (live) {
          setSource({ url, generation: 0 })
        }
      },
      (caught: unknown) => {
        if (live) {
          setFailure(messageFor(LINK_FAILED, caught))
        }
      },
    )
    return () => {
      live = false
    }
  }, [receiptId, fetchUrl])

  /** Install a link, bumping `generation` so an identical URL still remounts. */
  function installLink(url: string): void {
    setSource((current) => ({ url, generation: (current === null ? 0 : current.generation) + 1 }))
  }

  // Not `async`: an async event handler's rejection is nobody's to catch, and
  // the plan's version (`setUrl(await fetchUrl(...))`) had exactly that hole.
  // Both settlement paths are passed to `then`, so neither can go unhandled.
  function handleError(): void {
    if (retried.current) {
      setFailure('Could not load the receipt image, even with a freshly signed link.')
      return
    }
    retried.current = true
    fetchUrl(receiptId).then(installLink, (caught: unknown) => {
      setFailure(messageFor('Could not re-sign the receipt image link', caught))
    })
  }

  /** The reviewer asking again after a visible failure. Re-asks for a link and
   *  restores the retry budget; deliberately touches nothing but this pane. */
  function askForLinkAgain(): void {
    setFailure(null)
    setSource(null)
    retried.current = false
    fetchUrl(receiptId).then(installLink, (caught: unknown) => {
      setFailure(messageFor(LINK_FAILED, caught))
    })
  }

  return (
    <div>
      <div>
        <button type="button" onClick={() => setZoom((current) => current * ZOOM_STEP)}>
          Zoom in
        </button>
        <button type="button" onClick={() => setZoom((current) => current / ZOOM_STEP)}>
          Zoom out
        </button>
        <button
          type="button"
          onClick={() => setRotation((current) => (current + QUARTER_TURN) % FULL_TURN)}
        >
          Rotate
        </button>
      </div>
      {failure !== null ? (
        // Only the image is replaced. The controls above survive, and so does a
        // way forward that does not cost a queue task.
        <div>
          <p role="alert">{failure}</p>
          <button type="button" onClick={askForLinkAgain}>
            Try loading the image again
          </button>
        </div>
      ) : source === null ? (
        <p>Loading the receipt image…</p>
      ) : (
        <img
          key={source.generation}
          src={source.url}
          alt="Receipt"
          onError={handleError}
          style={{ transform: `scale(${zoom}) rotate(${rotation}deg)` }}
        />
      )}
    </div>
  )
}
