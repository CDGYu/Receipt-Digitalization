import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
// The real class, never a mock: the screen discriminates on `caught instanceof
// ApiError`, and a mocked module would hand the test a different class object
// than the component holds -- so that branch would be exercised against a lie.
import { ApiError } from '../src/api/client'
import { ACCEPTED_SUFFIXES, MAX_UPLOAD_MB } from '../src/api/upload'
import type { UploadAccepted } from '../src/api/upload'
import { UploadScreen } from '../src/upload/UploadScreen'

/** The upload screen: what it refuses, whose words it uses, and what it becomes.
 *
 * ## `@testing-library/jest-dom` is not in this repository
 *
 * No `toBeInTheDocument`, no `toHaveTextContent`, no `toHaveAttribute` -- there
 * is no `setupFiles` and no matcher package. Everything below is `toBeNull`,
 * `toBeTruthy`, `.textContent` and `.getAttribute`, the idiom the rest of this
 * suite already uses. `receipts-screen.test.tsx` records the same thing.
 *
 * ## The file input is driven by `fireEvent.change`, not by `userEvent.upload`
 *
 * `userEvent.upload` was probed first, on 2026-08-24, under this jsdom and with
 * the house's direct-call pattern (no `setup()`), and it works: one file in,
 * one `change` event out, with the right `name`, `size` and `files.length`, and
 * a second call on the same input fires again.
 *
 * It is not used here because **it enforces the input's `accept` attribute and
 * silently delivers nothing when a file does not match**. Measured in the same
 * probe: an `<input accept=".jpg,...">` given a `scan.pdf` fires no `change` at
 * all and ends with `files.length === 0`. No browser behaves that way. `accept`
 * filters the file picker's default view, and a person can switch it to "all
 * files"; a drag-and-drop ignores it outright. So a file that `accept` does not
 * name really does arrive at the element, and refusing it is the whole job of
 * the branch the PDF test below exercises.
 *
 * Driving that test with `userEvent.upload` would therefore assert against a
 * file that never reached the component -- green for the wrong reason, and green
 * again on the day somebody deletes the refusal. `fireEvent.change` delivers the
 * file the way a browser delivers it, so it is used for every file in this file
 * rather than for the awkward one only.
 */

const HERE = dirname(fileURLToPath(import.meta.url))

function readUploadFile(name: string): string {
  const path = join(HERE, '..', 'src', 'upload', name)
  try {
    return readFileSync(path, 'utf8')
  } catch (cause) {
    throw new Error(
      `${name} is not at ${path}. If the upload screen moved or was renamed, ` +
        `update this path -- the guard is not optional cover.`,
      { cause },
    )
  }
}

afterEach(cleanup)

function jpeg(name = 'receipt.jpg', bytes = 3): File {
  return new File([new Uint8Array(bytes)], name, { type: 'image/jpeg' })
}

/** A file arriving at the input, the way a browser delivers one.
 *
 * `configurable: true` because a test may deliver twice to the same element,
 * and a non-configurable shadow would throw on the second. */
function choose(input: HTMLInputElement, file: File): void {
  Object.defineProperty(input, 'files', { value: [file], configurable: true })
  fireEvent.change(input)
}

function field(): HTMLInputElement {
  return screen.getByLabelText(/receipt/i) as HTMLInputElement
}

/** An internal tracker citation of any shape: `ISSUE-27`, `ADR-0051`, `ABC-9`.
 *
 * Deliberately wider than the one form `withoutTracker` removes. The transform
 * is narrow so it cannot eat real copy; this is the property, so a citation in
 * a shape nothing strips is a failure here rather than a string on a screen. */
const TRACKER = /[A-Z]{2,}-\d+/

describe('UploadScreen', () => {
  it('offers a file input a reviewer can find by its label', () => {
    render(<UploadScreen upload={vi.fn()} />)
    expect(screen.getByLabelText(/receipt/i)).toBeTruthy()
  })

  it('offers the picker the suffixes the client accepts, and keeps no second list', () => {
    // Derived from `ACCEPTED_SUFFIXES` rather than retyped in the markup: two
    // copies of one list is how the picker comes to offer a suffix the screen
    // then refuses. This asserts an attribute, which is a real thing in the DOM
    // -- unlike a class name, which `css: false` makes unpinnable here.
    render(<UploadScreen upload={vi.fn()} />)
    expect(field().getAttribute('accept')).toBe(ACCEPTED_SUFFIXES.join(','))
  })

  it('refuses a PDF without spending an upload, and says why', () => {
    const upload = vi.fn()
    render(<UploadScreen upload={upload} />)

    choose(field(), new File([new Uint8Array(1)], 'scan.pdf', { type: 'application/pdf' }))

    const alert = screen.getByRole('alert')
    expect(alert.textContent).toContain('PDF')
    expect(upload).not.toHaveBeenCalled()
  })

  it('names no internal tracker id in any refusal it renders', () => {
    // The screen owns this, not `upload.ts`: `rejectionReason`'s PDF branch
    // cites ISSUE-027 and `upload-api.test.ts` pins that string, so the citation
    // is correct where it is written and wrong where it is read out. Measured
    // 2026-08-24: strip every comment from every `.ts`, `.tsx` and `.css` file
    // under `frontend/src` and search what is left for `[A-Z]{2,}-\d+`, and
    // exactly ONE line matches -- that `return`.
    //
    // Quantified over every refusal `rejectionReason` can produce -- the three
    // branches, one file each -- rather than over the one that carries a
    // citation today, and asserted on what the ALERT REGION renders rather than
    // on the function's return value, because a scrub applied anywhere but the
    // last step before the DOM is a scrub that can be walked around.
    const oversized = jpeg('huge.jpg', 1)
    Object.defineProperty(oversized, 'size', { value: MAX_UPLOAD_MB * 1024 * 1024 + 1 })
    const refused = [
      new File([new Uint8Array(1)], 'scan.pdf', { type: 'application/pdf' }),
      new File([new Uint8Array(1)], 'notes.txt', { type: 'text/plain' }),
      oversized,
    ]

    for (const file of refused) {
      const upload = vi.fn()
      render(<UploadScreen upload={upload} />)
      choose(field(), file)

      const alert = screen.getByRole('alert')
      const text = alert.textContent ?? ''
      expect(text.length, `${file.name} produced an empty alert`).toBeGreaterThan(0)
      expect(text, `${file.name}'s refusal carries a tracker id`).not.toMatch(TRACKER)
      expect(upload, `${file.name} was sent anyway`).not.toHaveBeenCalled()
      cleanup()
    }
  })

  it('still says what a PDF is and what to do instead, having dropped the id', () => {
    // The other half of the scrub: a refusal stripped down to nothing would pass
    // the check above and tell the reader less than the raw string did.
    render(<UploadScreen upload={vi.fn()} />)
    choose(field(), new File([new Uint8Array(1)], 'scan.pdf', { type: 'application/pdf' }))

    const text = screen.getByRole('alert').textContent ?? ''
    expect(text).toContain('PDFs cannot be processed yet')
    expect(text).toContain('Upload a photograph instead')
  })

  it('shows the words the server itself used when the server refuses', async () => {
    const upload = vi.fn().mockRejectedValue(new ApiError(415, 'not a receipt image: image/gif'))
    render(<UploadScreen upload={upload} />)

    choose(field(), jpeg())

    const alert = await screen.findByRole('alert')
    // The client checked a suffix and was happy; only the server knows this.
    // Inventing our own wording here would tell the reviewer something false.
    expect(alert.textContent).toContain('not a receipt image: image/gif')
  })

  it('says something rather than nothing when the API is not reachable at all', async () => {
    // A `TypeError: Failed to fetch` from a server that is not running carries
    // nothing a reader can act on, so this is the one case where the screen
    // supplies the sentence. The split `AdminScreen`, `ReviewScreen`,
    // `ReceiptsScreen` and `LoginPage` already make.
    const upload = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    render(<UploadScreen upload={upload} />)

    choose(field(), jpeg())

    const alert = await screen.findByRole('alert')
    expect((alert.textContent ?? '').length).toBeGreaterThan(0)
    expect(alert.textContent).not.toContain('Failed to fetch')
  })

  it('hands one accepted file to the processing view, in place', async () => {
    const upload = vi
      .fn()
      .mockResolvedValue({ receipt_id: 'r-1', image_key: 'k', status: 'pending' })
    render(
      <UploadScreen
        upload={upload}
        progress={vi.fn().mockResolvedValue({ status: 'pending', stage: 'triage', detail: null })}
      />,
    )

    choose(field(), jpeg())

    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1))
    // The file chooser is gone and the processing view is here -- same route, no
    // navigation. A page load at this moment is the beat this design avoids.
    await waitFor(() => expect(screen.queryByLabelText(/receipt/i)).toBeNull())
    expect(document.body.textContent).toContain('r-1')
  })

  it('clears a refusal the moment the next attempt starts, not when it finishes', async () => {
    // A message about a file the person has already replaced is worse than no
    // message: it reads as a refusal of the file they are now looking at.
    //
    // Observed WHILE the upload is in flight, and that is the whole design of
    // this test. The first version asserted it after a successful upload and was
    // **vacuous** -- success swaps the entire screen for the processing view,
    // which has no alert region at all, so `queryByRole('alert')` was null for a
    // reason that had nothing to do with the clear. Measured on 2026-08-24 by
    // deleting `setError(null)` from `offer`: all 13 tests in this file passed.
    // A promise that never settles keeps the chooser on screen, so the absence
    // of the alert is an assertion about the state and not about the branch.
    const upload = vi.fn().mockReturnValue(new Promise<UploadAccepted>(() => {}))
    render(<UploadScreen upload={upload} />)

    const input = field()
    choose(input, new File([new Uint8Array(1)], 'scan.pdf', { type: 'application/pdf' }))
    expect(screen.getByRole('alert')).toBeTruthy()

    choose(input, jpeg())
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1))
    expect(screen.getByLabelText(/receipt/i), 'the chooser left before anything settled').toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
  })
})

// --------------------------------------------------------------------------- //
// The stylesheet, which no rendering test in this repository can see
// --------------------------------------------------------------------------- //

/** `css: false` makes a class name unpinnable by rendering: the CSS-module proxy
 *  answers for any key, so a renamed class ships unpainted with every gate
 *  green. These read both files as text instead. The same guard
 *  `receipts-screen.test.tsx` carries, for the same measured reason. */
describe('the upload screen is actually painted', () => {
  function declaredClasses(css: string): Set<string> {
    const source = css.replace(/\/\*[\s\S]*?\*\//g, '')
    return new Set(Array.from(source.matchAll(/\.([A-Za-z][\w-]*)/g), (m) => m[1]))
  }

  function referencedClasses(tsx: string): Set<string> {
    const source = tsx.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1')
    return new Set(Array.from(source.matchAll(/\bstyles\.([A-Za-z][\w-]*)/g), (m) => m[1]))
  }

  it('extracts from both sides, and is not fooled by a comment', () => {
    expect(declaredClasses('.real { color: red }').has('real')).toBe(true)
    expect(declaredClasses('/* .ghost {} */ .real {}').has('ghost')).toBe(false)
    expect(referencedClasses('x = styles.real').has('real')).toBe(true)
    expect(referencedClasses('/* styles.ghost */ x = styles.real').has('ghost')).toBe(false)
    expect(referencedClasses('// styles.ghost\nx = styles.real').has('ghost')).toBe(false)
  })

  it('declares every class the component reaches', () => {
    const declared = declaredClasses(readUploadFile('UploadScreen.module.css'))
    const referenced = referencedClasses(readUploadFile('UploadScreen.tsx'))
    expect(referenced.size, 'UploadScreen.tsx references no styles.*').toBeGreaterThan(0)
    const missing = [...referenced].filter((name) => !declared.has(name))
    expect(
      missing,
      'UploadScreen.tsx reaches classes UploadScreen.module.css does not declare',
    ).toEqual([])
  })

  // The other direction, and not symmetry for its own sake: the check above can
  // only fail on a reference with no declaration, so deleting a `className`
  // outright is invisible to it. Measured in `admin-screen.test.tsx` on
  // 2026-08-14 by deleting `<div className={styles.grid}>` from `StatTiles.tsx`
  // -- whole suite green, `tsc -b` clean, and the tiles rendered as four
  // full-width rows.
  //
  // The bound: `referencedClasses` matches `styles.NAME` only, so a class
  // reached by dynamic indexing is invisible to it and would fail here.
  // Measured when this was written: `UploadScreen.tsx` does not index `styles`.
  it('reaches every class its stylesheet declares, so a rule cannot be left dead', () => {
    const declared = declaredClasses(readUploadFile('UploadScreen.module.css'))
    const referenced = referencedClasses(readUploadFile('UploadScreen.tsx'))
    expect(declared.size, 'UploadScreen.module.css declares no classes').toBeGreaterThan(0)
    const dead = [...declared].filter((name) => !referenced.has(name))
    expect(
      dead,
      'UploadScreen.module.css declares classes UploadScreen.tsx never reaches',
    ).toEqual([])
  })

  it('paints from tokens, with no raw hex', () => {
    // The Global Constraint, and a thing no rendering test can see. The census
    // in `stylesheets.test.ts` records that a colour declaration exists; it does
    // not care what the value is.
    const css = readUploadFile('UploadScreen.module.css').replace(/\/\*[\s\S]*?\*\//g, '')
    expect(css.match(/#[0-9A-Fa-f]{3,8}\b/g) ?? []).toEqual([])
  })
})
