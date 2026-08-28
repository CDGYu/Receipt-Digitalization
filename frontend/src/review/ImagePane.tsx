import { useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import type { NormalizedBBox } from '../api/types'
import styles from './ImagePane.module.css'

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
 * `fetchNext`, which is a claiming write.
 *
 * The reason for that has changed since this file was written, though the rule
 * has not. It used to be that a page reload stranded the reviewer's queue task
 * for good; ADR-0016 landed afterwards and made `GET /review/next` resume the
 * caller's own in-progress task, so a reload now hands the same receipt back.
 * What a needless `fetchNext` from here would cost today is a *second* claim in
 * the pre-commit window the ADR records as self-correcting but real -- and the
 * pane has no business spending queue state to re-sign an image link either
 * way.
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
  readonly lineItemBoxes?: readonly LineItemBox[]
  readonly activeLineItemPosition?: number | null
}

export interface LineItemBox {
  readonly position: number
  readonly bbox: NormalizedBBox | null
}

interface Source {
  readonly url: string
  readonly generation: number
}

interface RenderedBox {
  readonly position: number
  readonly active: boolean
  readonly style: CSSProperties
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

function isUnit(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1
}

function styleForBox(bbox: NormalizedBBox | null): CSSProperties | null {
  if (bbox === null || !Array.isArray(bbox) || bbox.length !== 4) {
    return null
  }
  const [x0, y0, x1, y1] = bbox
  if (!isUnit(x0) || !isUnit(y0) || !isUnit(x1) || !isUnit(y1)) {
    return null
  }
  if (x1 <= x0 || y1 <= y0) {
    return null
  }
  return {
    left: `${x0 * 100}%`,
    top: `${y0 * 100}%`,
    width: `${(x1 - x0) * 100}%`,
    height: `${(y1 - y0) * 100}%`,
  }
}

function renderableBoxes(
  lineItemBoxes: readonly LineItemBox[],
  activeLineItemPosition: number | null,
): RenderedBox[] {
  const boxes: RenderedBox[] = []
  for (const box of lineItemBoxes) {
    const style = styleForBox(box.bbox)
    if (style === null) {
      continue
    }
    boxes.push({
      position: box.position,
      active: box.position === activeLineItemPosition,
      style,
    })
  }
  return boxes
}

export function ImagePane({
  receiptId,
  fetchUrl,
  lineItemBoxes = [],
  activeLineItemPosition = null,
}: ImagePaneProps) {
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

  const boxes = renderableBoxes(lineItemBoxes, activeLineItemPosition)

  return (
    <div className={styles.pane}>
      <div className={styles.toolbar}>
        <button
          type="button"
          className={styles.button}
          onClick={() => setZoom((current) => current * ZOOM_STEP)}
        >
          Zoom in
        </button>
        <button
          type="button"
          className={styles.button}
          onClick={() => setZoom((current) => current / ZOOM_STEP)}
        >
          Zoom out
        </button>
        <button
          type="button"
          className={styles.button}
          onClick={() => setRotation((current) => (current + QUARTER_TURN) % FULL_TURN)}
        >
          Rotate
        </button>
      </div>
      {failure !== null ? (
        // Only the image is replaced. The controls above survive, and so does a
        // way forward that does not cost a queue task.
        <div className={styles.failure}>
          <p className={styles.alert} role="alert">
            {failure}
          </p>
          <button type="button" className={styles.button} onClick={askForLinkAgain}>
            Try loading the image again
          </button>
        </div>
      ) : source === null ? (
        <p className={styles.loading}>Loading the receipt image…</p>
      ) : (
        <div
          className={styles.stage}
          // Zoom, rotation and boxes share one coordinate plane. The transform
          // lives on the stage so the photograph and its overlay move together.
          style={{ transform: `scale(${zoom}) rotate(${rotation}deg)` }}
        >
          <img
            key={source.generation}
            className={styles.image}
            src={source.url}
            alt="Receipt"
            onError={handleError}
          />
          {boxes.length === 0 ? null : (
            <div className={styles.highlights} aria-hidden="true">
              {boxes.map((box) => (
                <span
                  key={box.position}
                  className={
                    box.active
                      ? `${styles.highlight} ${styles.highlightActive}`
                      : styles.highlight
                  }
                  data-line-item-position={box.position}
                  style={box.style}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
