import { useEffect, useRef, useState } from 'react'
import type {
  CSSProperties,
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
} from 'react'
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
  /** Where receipt-level fields sit on the image, keyed by the dotted path the
   *  review form edits them under (`merchant.name`, ...) -- the receipt's
   *  `field_boxes`. Only the field named by `activeFieldPath` is drawn: a
   *  header highlight is a "show me where this one is" affordance, not the
   *  all-boxes-at-once overlay the line items get. */
  readonly fieldBoxes?: Readonly<Record<string, NormalizedBBox>>
  /** The dotted path of the field the reviewer is editing, or `null`. */
  readonly activeFieldPath?: string | null
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

interface Pan {
  readonly x: number
  readonly y: number
}

interface Drag {
  readonly pointerId: number
  readonly startX: number
  readonly startY: number
  readonly panX: number
  readonly panY: number
}

const ZOOM_STEP = 1.25
const MIN_ZOOM = 0.5
const MAX_ZOOM = 4
const QUARTER_TURN = 90
const FULL_TURN = 360
const PAN_KEY_STEP = 32
const ORIGIN: Pan = { x: 0, y: 0 }

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

function clampZoom(value: number): number {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value))
}

export function ImagePane({
  receiptId,
  fetchUrl,
  lineItemBoxes = [],
  activeLineItemPosition = null,
  fieldBoxes = {},
  activeFieldPath = null,
}: ImagePaneProps) {
  const [source, setSource] = useState<Source | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [zoom, setZoom] = useState(1)
  const [rotation, setRotation] = useState(0)
  const [pan, setPan] = useState<Pan>(ORIGIN)
  const [dragging, setDragging] = useState(false)
  /** Whether the one silent re-sign has already been spent. A ref, not state:
   *  two `error` events in one batch must not both read `false`. */
  const retried = useRef(false)
  const drag = useRef<Drag | null>(null)

  useEffect(() => {
    // Reset rather than rely on the caller remounting us: a new receipt gets its
    // own retry budget, and a failure from the previous one must not survive
    // into it. `ReviewScreen` also passes a `key`, so in the app this branch is
    // belt and braces; on its own the component is still correct -- which
    // `starts clean when it is handed a different receipt` pins.
    let live = true
    setSource(null)
    setFailure(null)
    setZoom(1)
    setRotation(0)
    setPan(ORIGIN)
    setDragging(false)
    retried.current = false
    drag.current = null
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

  function zoomIn(): void {
    setZoom((current) => clampZoom(current * ZOOM_STEP))
  }

  function zoomOut(): void {
    setZoom((current) => clampZoom(current / ZOOM_STEP))
  }

  function rotateClockwise(): void {
    setRotation((current) => (current + QUARTER_TURN) % FULL_TURN)
  }

  function resetView(): void {
    setZoom(1)
    setRotation(0)
    setPan(ORIGIN)
  }

  function movePan(dx: number, dy: number): void {
    setPan((current) => ({ x: current.x + dx, y: current.y + dy }))
  }

  function startDrag(event: ReactPointerEvent<HTMLDivElement>): void {
    if (event.button !== 0 || event.isPrimary === false) {
      return
    }
    event.preventDefault()
    event.currentTarget.setPointerCapture?.(event.pointerId)
    drag.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      panX: pan.x,
      panY: pan.y,
    }
    setDragging(true)
  }

  function dragView(event: ReactPointerEvent<HTMLDivElement>): void {
    const current = drag.current
    if (current === null || current.pointerId !== event.pointerId) {
      return
    }
    event.preventDefault()
    setPan({
      x: current.panX + event.clientX - current.startX,
      y: current.panY + event.clientY - current.startY,
    })
  }

  function stopDrag(event: ReactPointerEvent<HTMLDivElement>): void {
    const current = drag.current
    if (current === null || current.pointerId !== event.pointerId) {
      return
    }
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    drag.current = null
    setDragging(false)
  }

  function panWithKeyboard(event: ReactKeyboardEvent<HTMLDivElement>): void {
    switch (event.key) {
      case 'ArrowLeft':
        event.preventDefault()
        movePan(-PAN_KEY_STEP, 0)
        break
      case 'ArrowRight':
        event.preventDefault()
        movePan(PAN_KEY_STEP, 0)
        break
      case 'ArrowUp':
        event.preventDefault()
        movePan(0, -PAN_KEY_STEP)
        break
      case 'ArrowDown':
        event.preventDefault()
        movePan(0, PAN_KEY_STEP)
        break
    }
  }

  const boxes = renderableBoxes(lineItemBoxes, activeLineItemPosition)
  // The one header field the reviewer is editing, if it was placed on the image
  // and its coordinates are well-formed. Only the active field is ever drawn --
  // unlike the line items, whose whole set is faintly outlined -- because a
  // header highlight answers "where is this field" for the field in hand, and a
  // page full of header boxes would just be noise over the same photo. A field
  // with no entry (the grounding pass could not place it) or a malformed one
  // yields `null` and draws nothing, so an unlocatable field is silently no-op
  // rather than a misplaced rectangle.
  const activeFieldStyle =
    activeFieldPath !== null && activeFieldPath in fieldBoxes
      ? styleForBox(fieldBoxes[activeFieldPath])
      : null
  const viewerClass = dragging ? `${styles.viewer} ${styles.viewerDragging}` : styles.viewer

  return (
    <div className={styles.pane}>
      <div className={styles.toolbar}>
        <button
          type="button"
          className={styles.button}
          onClick={zoomIn}
        >
          Zoom in
        </button>
        <button
          type="button"
          className={styles.button}
          onClick={zoomOut}
        >
          Zoom out
        </button>
        <button
          type="button"
          className={styles.button}
          onClick={rotateClockwise}
        >
          Rotate
        </button>
        <button type="button" className={styles.button} onClick={resetView}>
          Reset view
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
          className={viewerClass}
          role="region"
          aria-label="Receipt image viewer"
          tabIndex={0}
          onKeyDown={panWithKeyboard}
          onPointerDown={startDrag}
          onPointerMove={dragView}
          onPointerUp={stopDrag}
          onPointerCancel={stopDrag}
          onLostPointerCapture={stopDrag}
        >
          <div
            className={styles.panLayer}
            style={{ transform: `translate(${pan.x}px, ${pan.y}px)` }}
          >
            <div
              className={styles.stage}
              // Zoom, rotation and boxes share one coordinate plane. Panning is
              // outside this stage so dragging stays screen-aligned after rotate.
              style={{ transform: `scale(${zoom}) rotate(${rotation}deg)` }}
            >
              <img
                key={source.generation}
                className={styles.image}
                src={source.url}
                alt="Receipt"
                onError={handleError}
                draggable={false}
              />
              {boxes.length === 0 && activeFieldStyle === null ? null : (
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
                  {activeFieldStyle === null ? null : (
                    // Always the active style: this box is only ever the one
                    // field the reviewer is on, so it reads like a focused
                    // line-item box rather than the quiet outline the others
                    // get. Keyed and tagged by the dotted path so a test (and a
                    // debugger) can find it the way `data-line-item-position`
                    // finds an item box.
                    <span
                      key={activeFieldPath ?? ''}
                      className={`${styles.highlight} ${styles.highlightActive}`}
                      data-field-path={activeFieldPath ?? undefined}
                      style={activeFieldStyle}
                    />
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
