import { readFileSync, readdirSync } from 'node:fs'
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
// The real mapping, so the exit link is asserted to REACH the review queue
// rather than to spell a string this file also spells.
import { currentRoute } from '../src/route'
import { ProcessingView } from '../src/upload/ProcessingView'
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
 * the branch the unknown-suffix test below exercises. (That sentence named the
 * PDF test until ISSUE-027 was fixed and a PDF stopped being refused.)
 *
 * Driving that test with `userEvent.upload` would therefore assert against a
 * file that never reached the component -- green for the wrong reason, and green
 * again on the day somebody deletes the refusal. `fireEvent.change` delivers the
 * file the way a browser delivers it, so it is used for every file in this file
 * rather than for the awkward one only.
 */

const HERE = dirname(fileURLToPath(import.meta.url))

const UPLOAD_DIR = join(HERE, '..', 'src', 'upload')

function readUploadFile(name: string): string {
  const path = join(UPLOAD_DIR, name)
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

/** Several files arriving at once, the way a multi-select picker delivers them.
 *
 * The input carries `multiple`, so `files` is a list of more than one and the
 * screen offers each in turn. */
function chooseMany(input: HTMLInputElement, files: File[]): void {
  Object.defineProperty(input, 'files', { value: files, configurable: true })
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

  it('prints the limits from the module that enforces them, not from copy', async () => {
    // The sentence under the chooser claims to be derived. Asserting it against
    // the real `MAX_UPLOAD_MB` would not test that claim -- `25` typed into the
    // markup renders identically. So the module is replaced with different
    // values and the screen is re-imported: a literal in the copy cannot follow.
    //
    // `doMock` + `resetModules` + a dynamic import. New here: nothing else in
    // this repository calls `vi.doMock`. The hoisted `vi.mock` that
    // `app-admin-route.test.tsx` uses would not do -- it is file-scoped, so it
    // would rewire every test in this file rather than this one. The statically
    // imported `UploadScreen` the others hold is a different module object and
    // is untouched by this.
    vi.resetModules()
    vi.doMock('../src/api/upload', async (importOriginal) => ({
      ...(await importOriginal<typeof import('../src/api/upload')>()),
      ACCEPTED_SUFFIXES: ['.aaa', '.bbb'],
      MAX_UPLOAD_MB: 7,
    }))
    try {
      const { UploadScreen: Rewired } = await import('../src/upload/UploadScreen')
      render(<Rewired upload={vi.fn()} />)

      const text = document.body.textContent ?? ''
      expect(text, 'the size limit is typed into the copy').toContain('7 MB')
      expect(text, 'the suffix list is typed into the copy').toContain('.aaa, .bbb')
      // The `accept` attribute belongs here rather than beside its own test.
      // `toBe(ACCEPTED_SUFFIXES.join(','))` up there is a string identity a
      // retyped literal satisfies -- the same hole `toContain('25 MB')` had --
      // and only the rewired module can tell a derived attribute from a copied
      // one.
      expect(
        field().getAttribute('accept'),
        "the accept attribute is a second list, not the module's",
      ).toBe('.aaa,.bbb')
    } finally {
      vi.doUnmock('../src/api/upload')
      vi.resetModules()
    }
  })

  it('sends a PDF now that ingest expands one into a receipt per page', () => {
    // The inverse of what this file asserted until ISSUE-027 was fixed: the
    // screen used to refuse a PDF client-side because the server accepted one
    // and then every PDF died at `preprocess`. Both halves are pinned -- no
    // alert, and the upload actually spent -- because a screen that silently
    // did nothing would also raise no alert.
    const upload = vi.fn().mockReturnValue(new Promise<UploadAccepted>(() => {}))
    render(<UploadScreen upload={upload} />)

    choose(field(), new File([new Uint8Array(1)], 'scan.pdf', { type: 'application/pdf' }))

    expect(screen.queryByRole('alert')).toBeNull()
    expect(upload).toHaveBeenCalledTimes(1)
  })

  it('names no internal tracker id in any refusal it renders', () => {
    // The screen owns this, not `upload.ts`. **No refusal carries a citation
    // today**: the one that did was `rejectionReason`'s PDF branch, and
    // ISSUE-027's fix deleted it along with the refusal. The scrub and this test
    // stay because the defence is against the NEXT citation somebody writes into
    // a refusal, not against the one that used to be there -- deleting the guard
    // with the instance it guarded is how a class of defect comes back.
    //
    // Quantified over every refusal `rejectionReason` can still produce -- the
    // two remaining branches, one file each -- and asserted on what the ALERT
    // REGION renders rather than on the function's return value, because a scrub
    // applied anywhere but the last step before the DOM can be walked around.
    const oversized = jpeg('huge.jpg', 1)
    Object.defineProperty(oversized, 'size', { value: MAX_UPLOAD_MB * 1024 * 1024 + 1 })
    const refused = [new File([new Uint8Array(1)], 'notes.txt', { type: 'text/plain' }), oversized]

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

  it('still says what is wrong and what is accepted, having dropped the id', () => {
    // The other half of the scrub: a refusal stripped down to nothing would pass
    // the check above and tell the reader less than the raw string did.
    //
    // This asserted the PDF refusal's wording until ISSUE-027 was fixed. It is
    // re-pointed at the unknown-suffix refusal rather than deleted: the scrub it
    // balances still runs, and a scrub with nothing checking that it left
    // something behind is how an alert becomes an empty box.
    render(<UploadScreen upload={vi.fn()} />)
    choose(field(), new File([new Uint8Array(1)], 'notes.txt', { type: 'text/plain' }))

    const text = screen.getByRole('alert').textContent ?? ''
    expect(text).toContain('Accepted types are')
    expect(text).toContain('.pdf')
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

  it('appends an accepted file to the list and keeps the chooser open', async () => {
    const upload = vi
      .fn()
      .mockResolvedValue({
        receipts: [{ receipt_id: 'r-1', image_key: 'k' }],
        status: 'pending',
      })
    const progress = vi
      .fn()
      .mockResolvedValue({ status: 'pending', stage: 'triage', detail: null })
    render(<UploadScreen upload={upload} progress={progress} />)

    choose(field(), jpeg())

    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1))
    // The receipt is now followed in the list, and the chooser is STILL here --
    // that is the batch flow: hand over one and immediately add the next, no
    // navigation. This is the inverse of the first version, which asserted the
    // chooser disappeared.
    await waitFor(() => expect(document.body.textContent).toContain('r-1'))
    expect(screen.getByLabelText(/receipt/i), 'the chooser was replaced by the receipt').toBeTruthy()
    // The injected `progress` reached the view, with the id the server just
    // returned. Without this the forwarding is deletable in silence: the view
    // falls back to the real `fetchProgress`, which rejects under jsdom straight
    // into the handler that deliberately swallows it, and `r-1` still renders
    // from the receipt pane -- so `UploadScreenProps.progress` goes back to
    // being an unread prop.
    await waitFor(() => expect(progress).toHaveBeenCalledWith('r-1'))
  })

  it('queues several files chosen at once, one row each', async () => {
    // The batch: `multiple` on the input and a picker that hands over more than
    // one file. Each is uploaded and each becomes its own followed row.
    const upload = vi
      .fn()
      .mockResolvedValueOnce({ receipts: [{ receipt_id: 'r-1', image_key: 'k1' }], status: 'pending' })
      .mockResolvedValueOnce({ receipts: [{ receipt_id: 'r-2', image_key: 'k2' }], status: 'pending' })
    const progress = vi.fn().mockResolvedValue({ status: 'pending', stage: 'triage', detail: null })
    render(<UploadScreen upload={upload} progress={progress} />)

    chooseMany(field(), [jpeg('one.jpg'), jpeg('two.jpg')])

    await waitFor(() => expect(upload).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(document.body.textContent).toContain('r-1'))
    await waitFor(() => expect(document.body.textContent).toContain('r-2'))
    // Both files were sent, in the order they were chosen.
    expect((upload.mock.calls[0][0] as File).name).toBe('one.jpg')
    expect((upload.mock.calls[1][0] as File).name).toBe('two.jpg')
    // The chooser is still open for the next batch.
    expect(screen.getByLabelText(/receipt/i)).toBeTruthy()
  })

  it('expands one PDF into a row per page', async () => {
    // A single file can become several receipts (ISSUE-027). Each page gets its
    // own followed row and its own id, labelled with the page number so two rows
    // from one file are told apart.
    const upload = vi.fn().mockResolvedValue({
      receipts: [
        { receipt_id: 'p-1', image_key: 'k1' },
        { receipt_id: 'p-2', image_key: 'k2' },
      ],
      status: 'pending',
    })
    const progress = vi.fn().mockResolvedValue({ status: 'pending', stage: null, detail: null })
    render(<UploadScreen upload={upload} progress={progress} />)

    choose(field(), new File([new Uint8Array(1)], 'invoice.pdf', { type: 'application/pdf' }))

    await waitFor(() => expect(document.body.textContent).toContain('p-1'))
    await waitFor(() => expect(document.body.textContent).toContain('p-2'))
    const text = document.body.textContent ?? ''
    expect(text).toContain('invoice.pdf (page 1)')
    expect(text).toContain('invoice.pdf (page 2)')
  })

  it('offers "Upload another" once there is a receipt, and it reaches the chooser', async () => {
    const upload = vi.fn().mockResolvedValue({
      receipts: [{ receipt_id: 'r-1', image_key: 'k' }],
      status: 'pending',
    })
    const progress = vi.fn().mockResolvedValue({ status: 'pending', stage: null, detail: null })
    render(<UploadScreen upload={upload} progress={progress} />)

    // Absent before anything is queued: the button belongs to the list, and
    // there is no list yet.
    expect(screen.queryByRole('button', { name: /upload another/i })).toBeNull()

    choose(field(), jpeg())
    const another = await screen.findByRole('button', { name: /upload another/i })

    // It opens the same chooser rather than being a second upload path. jsdom
    // does not open a native picker, so what is asserted is that the click
    // reaches the input -- the control the whole flow already goes through.
    const clicked = vi.fn()
    field().addEventListener('click', clicked)
    fireEvent.click(another)
    expect(clicked).toHaveBeenCalled()
  })

  it('clears a refusal the moment the next attempt starts, not when it finishes', async () => {
    // A message about a file the person has already replaced is worse than no
    // message: it reads as a refusal of the file they are now looking at.
    //
    // The chooser stays on screen throughout now, so the alert region is always
    // present -- its absence after a fresh choice is a real assertion about the
    // clear rather than about a screen that swapped itself away.
    const upload = vi.fn().mockReturnValue(new Promise<UploadAccepted>(() => {}))
    render(<UploadScreen upload={upload} />)

    const input = field()
    // A `.txt`: an unknown suffix is refused client-side, so an alert appears.
    choose(input, new File([new Uint8Array(1)], 'notes.txt', { type: 'text/plain' }))
    expect(screen.getByRole('alert')).toBeTruthy()

    choose(input, jpeg())
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1))
    expect(screen.queryByRole('alert')).toBeNull()
    // The chooser is never shut now -- uploads are concurrent and the point is
    // to accept the next file while the last is still going. The input carries
    // no `disabled` attribute at any time.
    expect(field().hasAttribute('disabled'), 'the chooser locked while sending').toBe(false)
  })
})

/** A poll seam the test drives by hand: no timers, no flake. */
function manualPoll() {
  let tick: (() => void) | null = null
  const poll = (fn: () => void) => {
    tick = fn
    return () => {
      tick = null
    }
  }
  return { poll, fire: () => tick?.(), stopped: () => tick === null }
}

describe('ProcessingView', () => {
  it('narrates the stage the route reports', async () => {
    const { poll, fire } = manualPoll()
    const progress = vi
      .fn()
      .mockResolvedValue({ status: 'pending', stage: 'extract', detail: 'attempt 1' })

    render(
      <ProcessingView receiptId="r-1" fileName="receipt.jpg" progress={progress} poll={poll} />,
    )
    fire()

    expect(await screen.findByText(/extract/i)).toBeTruthy()
    expect(await screen.findByText(/attempt 1/i)).toBeTruthy()
  })

  it('stops polling when status goes terminal, not when the stage goes quiet', async () => {
    // The load-bearing rule: `status` is truth, `stage` is narration. A dead
    // worker stops writing progress, and a view that waited for a terminal
    // STAGE would poll forever.
    const { poll, fire, stopped } = manualPoll()
    const progress = vi
      .fn()
      .mockResolvedValue({ status: 'needs_review', stage: null, detail: null })

    render(
      <ProcessingView receiptId="r-1" fileName="receipt.jpg" progress={progress} poll={poll} />,
    )
    fire()

    await waitFor(() => expect(stopped()).toBe(true))
  })

  it('keeps waiting on a null stage while the status is still pending', async () => {
    const { poll, fire, stopped } = manualPoll()
    const progress = vi.fn().mockResolvedValue({ status: 'pending', stage: null, detail: null })

    render(
      <ProcessingView receiptId="r-1" fileName="receipt.jpg" progress={progress} poll={poll} />,
    )
    fire()

    await waitFor(() => expect(progress).toHaveBeenCalled())
    expect(stopped()).toBe(false)
  })

  it('keeps the whole sequence the active stage narrates, not just its last word', async () => {
    // Design section 4's hero beat: `extract` says what it is doing as it
    // repairs its own answer, and the audience watches the system find its own
    // mistake and then DECLINE a repair that made things worse. A view holding
    // only the LAST report replaces each line with the next one and there is no
    // sequence to watch -- which is what this was before the fix round that
    // added it.
    //
    // The three strings are the shapes `extract` really writes, read off
    // `_report` and the best-attempt event in
    // src/receipts/extract/extractor.py: `attempt N (pass): M errors`, then
    // `kept attempt K of T`, with `pass` one of extract, re_extract, repair.
    // The view treats a detail as opaque text, so the shape changes nothing here
    // -- but a fixture that looks like production data and is not is a lie a
    // later reader has to discover.
    const { poll, fire } = manualPoll()
    const progress = vi
      .fn()
      .mockResolvedValueOnce({
        status: 'pending',
        stage: 'extract',
        detail: 'attempt 1 (extract): 3 errors',
      })
      .mockResolvedValueOnce({
        status: 'pending',
        stage: 'extract',
        detail: 'attempt 2 (repair): 5 errors',
      })
      .mockResolvedValue({ status: 'pending', stage: 'extract', detail: 'kept attempt 1 of 2' })

    render(
      <ProcessingView receiptId="r-1" fileName="receipt.jpg" progress={progress} poll={poll} />,
    )

    expect(await screen.findByText('attempt 1 (extract): 3 errors')).toBeTruthy()
    fire()
    expect(await screen.findByText('attempt 2 (repair): 5 errors')).toBeTruthy()
    fire()
    // The repair scored worse and the first attempt is the one kept. That beat
    // is only visible because all three lines are still on screen together.
    expect(await screen.findByText('kept attempt 1 of 2')).toBeTruthy()

    // All three at once, and in the order they were said. Read structurally --
    // the details list is the one `<ol>` inside the steps `<ol>` -- because a
    // class name is unpinnable by rendering under `css: false`.
    const narrated = Array.from(document.querySelectorAll('ol ol li'), (li) => li.textContent)
    expect(narrated).toEqual([
      'attempt 1 (extract): 3 errors',
      'attempt 2 (repair): 5 errors',
      'kept attempt 1 of 2',
    ])
  })

  it('says a repeated detail once, because an ask is not an event', async () => {
    // The route reports the CURRENT detail, so an unchanged one arrives again
    // on every ask. Without this the sequence above repeats one line for as long
    // as the attempt behind it runs.
    const { poll, fire } = manualPoll()
    const repeated = {
      status: 'pending',
      stage: 'extract',
      detail: 'attempt 1 (extract): 3 errors',
    }
    const progress = vi
      .fn()
      .mockResolvedValueOnce(repeated)
      .mockResolvedValueOnce(repeated)
      .mockResolvedValue({
        status: 'pending',
        stage: 'extract',
        detail: 'attempt 2 (repair): 0 errors',
      })

    render(
      <ProcessingView receiptId="r-1" fileName="receipt.jpg" progress={progress} poll={poll} />,
    )
    expect(await screen.findByText('attempt 1 (extract): 3 errors')).toBeTruthy()
    fire() // the repeat
    fire() // a genuinely new line, which is the barrier
    // Barriered on the DOM, not on `progress.mock.calls.length`. `fire()` runs
    // `ask` synchronously, so by this point the count is already past any
    // threshold two `fire()`s can be given -- measured 2026-08-24 by putting
    // `expect(progress.mock.calls.length).toBeGreaterThan(2)` right here, with
    // no `await` before it, where it passed. Nothing can have rendered yet: no
    // microtask has run. So a count barrier gates on the asks rather than on the
    // answers. A line that can only be on screen once the THIRD answer landed
    // waits for the second one too.
    expect(await screen.findByText('attempt 2 (repair): 0 errors')).toBeTruthy()

    // Two lines, not three: the repeat in the middle contributed nothing.
    expect(Array.from(document.querySelectorAll('ol ol li'), (li) => li.textContent)).toEqual([
      'attempt 1 (extract): 3 errors',
      'attempt 2 (repair): 0 errors',
    ])
  })

  it('drops the previous stage sequence when a new stage starts', async () => {
    // The sequence belongs to the stage that is running. Carrying `extract`'s
    // attempts into `score` would put one stage's narration under another's
    // name, and the completed stage is meant to collapse to its quiet line.
    const { poll, fire } = manualPoll()
    const progress = vi
      .fn()
      .mockResolvedValueOnce({
        status: 'pending',
        stage: 'extract',
        detail: 'attempt 1 (extract): 3 errors',
      })
      .mockResolvedValue({ status: 'pending', stage: 'score', detail: 'weighing' })

    render(
      <ProcessingView receiptId="r-1" fileName="receipt.jpg" progress={progress} poll={poll} />,
    )
    expect(await screen.findByText('attempt 1 (extract): 3 errors')).toBeTruthy()
    fire()
    expect(await screen.findByText('weighing')).toBeTruthy()

    expect(Array.from(document.querySelectorAll('ol ol li'), (li) => li.textContent)).toEqual([
      'weighing',
    ])
    // ...and `extract` is still on the timeline, as the quiet line it collapsed
    // to. Dropping its detail must not drop the stage.
    expect(screen.getByText('extract')).toBeTruthy()
  })

  it('renders a null detail as nothing, never as an empty row', async () => {
    // ADR-0027 decision 5. A styled element rendered unconditionally around a
    // `null` contributes no text, so every assertion about text is happy while a
    // browser shows a row with nothing in it. This repository keeps a whole file
    // -- `tests/review-null-rule.test.tsx` -- for that rule on the review
    // screen; this is the same rule on this one.
    const { poll, fire } = manualPoll()
    const progress = vi
      .fn()
      .mockResolvedValue({ status: 'pending', stage: 'triage', detail: null })

    render(
      <ProcessingView receiptId="r-1" fileName="receipt.jpg" progress={progress} poll={poll} />,
    )
    fire()

    const active = await screen.findByText('triage')
    const row = active.parentElement
    expect(row, 'the active stage is not inside a row').toBeTruthy()
    expect(
      Array.from(row?.children ?? []).length,
      'the active row carries an element beside the stage when the detail is null',
    ).toBe(1)
  })

  it('asks again on every tick, and shows what came back', async () => {
    // The four tests around this one are all satisfied by a view that asks once
    // at mount and registers a tick that does nothing: `progress` has been
    // called, the seam is registered, and `stopped()` is false. Measured by
    // replacing the tick's callback with `() => {}` -- every other test in this
    // file passed and this one failed on the second stage never arriving. So
    // this is the assertion that the waiting actually waits, and it is made on
    // what reaches the DOM rather than on a call count, because a view that
    // asked and dropped the answer would satisfy a count.
    const { poll, fire } = manualPoll()
    const progress = vi
      .fn()
      .mockResolvedValueOnce({ status: 'pending', stage: 'triage', detail: null })
      .mockResolvedValue({ status: 'pending', stage: 'extract', detail: null })

    render(
      <ProcessingView receiptId="r-1" fileName="receipt.jpg" progress={progress} poll={poll} />,
    )

    expect(await screen.findByText(/triage/i)).toBeTruthy()
    fire()
    expect(await screen.findByText(/extract/i)).toBeTruthy()
    // The step that has been and gone is still on screen: the timeline is what
    // this page watched, not just what it is watching.
    expect(screen.getByText(/triage/i)).toBeTruthy()
  })

  it('ends the wait visibly, and only once the status says so', async () => {
    // A view can stop polling and say nothing about it, and the four tests above
    // would not notice: `stopped()` is what they read. This is the other half --
    // the wait has to END on screen, with the word the server ended it on and
    // the way onward.
    const { poll, fire } = manualPoll()
    const stillWorking = vi
      .fn()
      .mockResolvedValue({ status: 'pending', stage: 'extract', detail: null })

    render(
      <ProcessingView receiptId="r-1" fileName="receipt.jpg" progress={stillWorking} poll={poll} />,
    )
    fire()

    // Waited for, not assumed: before the first report lands there is nothing on
    // screen either way, so asserting the absence straight after `render` would
    // pass against a view that never finishes anything.
    expect(await screen.findByText(/extract/i)).toBeTruthy()
    // The exit is offered in every state now -- the test below is why -- so an
    // absent link no longer tells the two states apart. The OUTCOME sentence
    // does: it exists only once the server ended the wait.
    expect(
      screen.queryByText(/the pipeline is done with it/i),
      'the wait was declared over while the receipt was still pending',
    ).toBeNull()
    cleanup()

    const { poll: poll2, fire: fire2 } = manualPoll()
    const done = vi.fn().mockResolvedValue({ status: 'needs_review', stage: null, detail: null })
    render(
      <ProcessingView receiptId="r-1" fileName="receipt.jpg" progress={done} poll={poll2} />,
    )
    fire2()

    // User-facing copy, not the database spelling the API reports.
    expect(await screen.findByText(/needs reviews/)).toBeTruthy()
    // Asserted through `currentRoute` rather than against the literal the
    // subject writes. `toHaveAttribute('href', '/app/review')` is a string
    // matching itself: it stays green if the app's review path moves, and green
    // for a path the backend would 404. This asks the module that owns the
    // mapping what the URL actually reaches.
    const exit = await waitFor(() => {
      const found = document.querySelector('a[href]')
      expect(found, 'the finished screen offers no exit').toBeTruthy()
      return found as HTMLAnchorElement
    })
    const href = exit.getAttribute('href') ?? ''
    expect(currentRoute(href), `the exit points at ${href}, which is not the review queue`).toBe(
      'review',
    )
    // `currentRoute` falls back to `review` for anything it does not recognise,
    // so the line above passes for a typo. The last segment carrying no dot is
    // what makes the backend serve the app at all rather than look for a file
    // (`route.ts`, and the rule `admin-screen.test.tsx` pins), so it is checked
    // separately.
    const lastSegment = href.slice(href.lastIndexOf('/') + 1)
    expect(lastSegment, `${href} ends in a segment with a dot, which the SPA mount 404s`).not.toMatch(
      /\./,
    )
    expect(href.startsWith('/app/'), `${href} is not under the app`).toBe(true)
  })

  it('offers a way off the screen while the receipt is still pending', async () => {
    // Decision 3 says the wait never ends on silence, so a receipt whose worker
    // never starts is narrated for as long as the tab is open. While the exit
    // lived inside the `finished` branch that state had no navigation off the
    // screen at all -- a dead end on the failure a live demo is likeliest to
    // hit. Measured 2026-08-24 by putting the link back inside that branch: this
    // test failed and every other test in this file passed.
    const { poll, fire } = manualPoll()
    const progress = vi.fn().mockResolvedValue({ status: 'pending', stage: null, detail: null })

    render(
      <ProcessingView receiptId="r-1" fileName="receipt.jpg" progress={progress} poll={poll} />,
    )
    fire()

    // The bleakest state this view has: pending, and nothing narrating.
    expect(await screen.findByText(/no step is reporting/i)).toBeTruthy()
    const exit = document.querySelector('a[href]')
    expect(exit, 'a receipt whose worker never started is a dead end').toBeTruthy()
    // Where it points is pinned by the test above, against `currentRoute`. This
    // one is about the link existing at all in a state that is not finished.
    const href = exit?.getAttribute('href') ?? ''
    expect(href.startsWith('/app/'), `the escape points at ${href}`).toBe(true)
  })

  it('keeps narrating when a poll fails, because narration is not the answer', async () => {
    const { poll, fire, stopped } = manualPoll()
    const progress = vi.fn().mockRejectedValue(new Error('gateway timeout'))

    render(
      <ProcessingView receiptId="r-1" fileName="receipt.jpg" progress={progress} poll={poll} />,
    )
    fire()

    await waitFor(() => expect(progress).toHaveBeenCalled())
    // A failed poll is not a failed receipt. Stopping here would strand a
    // receipt that is processing perfectly well.
    expect(stopped()).toBe(false)
  })
})

// --------------------------------------------------------------------------- //
// How this file drives the input, which is not how the rest of the suite does
// --------------------------------------------------------------------------- //

describe('the file input is driven the way a browser drives one', () => {
  // A gate where the header has an argument, and it is nothing to do with
  // painting -- which is why it lives here rather than in the stylesheet
  // block below. Measured across `tests/` on 2026-08-24: eleven files
  // import user-event, and this is the ONLY file that simulates an
  // interaction without it -- every other file using `fireEvent`, `.click()`
  // or `dispatchEvent` imports it too. So the house reflex points squarely
  // the wrong way in here, where user-event would deliver nothing for any
  // file `accept` does not name and pass for that reason.
  //
  // (The review that asked for this gate said this was the only file in the
  // suite not using user-event. Re-derived before being repeated: twenty files
  // do not import it. The narrower claim above is the one that holds.)
  //
  // The package name is assembled at run time so that naming it here does not
  // make the check fail on itself.
  it('does not reach for the picker faker', () => {
    const source = readFileSync(fileURLToPath(import.meta.url), 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/(^|[^:])\/\/[^\n]*/g, '$1')
    expect(
      source.includes(['@testing-library', 'user-event'].join('/')),
      'this file imports user-event. It must not: user-event enforces the input ' +
        "`accept` attribute and delivers nothing when a file does not match, which no " +
        'browser does, so the PDF refusal would be asserted against a file that ' +
        'never arrived. The header carries the measurement.',
    ).toBe(false)
  })
})

// --------------------------------------------------------------------------- //
// The stylesheet, which no rendering test in this repository can see
// --------------------------------------------------------------------------- //

/** `css: false` makes a class name unpinnable by rendering: the CSS-module proxy
 *  answers for any key, so a renamed class ships unpainted with every gate
 *  green. These read both files as text instead. The same guard
 *  `receipts-screen.test.tsx` carries, for the same measured reason.
 *
 *  Both directions run over every component in `src/upload/`, paired with the
 *  stylesheet beside it. Enumerated from the directory rather than listed, so a
 *  component added here later is guarded by the fact that it exists rather than
 *  by somebody remembering to add it. `stylesheets.test.ts` enumerates the whole
 *  tree for the same reason, and records the stylesheet that shipped unguarded
 *  when no guard in the repository knew it existed.
 *
 *  The bound: this pairs `Name.tsx` with `Name.module.css` unconditionally, so a
 *  `.tsx` here that paints nothing would fail on a stylesheet that does not
 *  exist. That is loud and one decision away from fixed, which is the right way
 *  round for a guard. */
describe('every component in src/upload is actually painted', () => {
  /** `Name.tsx` and the `Name.module.css` it is expected to paint from. */
  function painted(): { readonly tsx: string; readonly css: string }[] {
    return readdirSync(UPLOAD_DIR)
      .filter((name) => name.endsWith('.tsx'))
      .sort()
      .map((tsx) => ({ tsx, css: `${tsx.slice(0, -'.tsx'.length)}.module.css` }))
  }

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

  it('enumerates both components, so neither can leave the guard silently', () => {
    // Two failures this closes, not one. The enumeration answering `[]` would
    // make both directions below pass over nothing at all -- green, and guarding
    // nothing. And a component MOVED out of `src/upload/` simply stops being
    // enumerated, which is the same silence one file at a time. Naming them is
    // the only part of this guard that is a list, and it is a list of two.
    expect(painted().map((pair) => pair.tsx)).toEqual([
      'ProcessingView.tsx',
      'UploadScreen.tsx',
    ])
  })

  it('declares every class each component reaches', () => {
    for (const { tsx, css } of painted()) {
      const declared = declaredClasses(readUploadFile(css))
      const referenced = referencedClasses(readUploadFile(tsx))
      expect(referenced.size, `${tsx} references no styles.*`).toBeGreaterThan(0)
      const missing = [...referenced].filter((name) => !declared.has(name))
      expect(missing, `${tsx} reaches classes ${css} does not declare`).toEqual([])
    }
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
  // Measured when this was written, and again when `ProcessingView` joined:
  // neither component indexes `styles`.
  it('reaches every class its stylesheet declares, so a rule cannot be left dead', () => {
    for (const { tsx, css } of painted()) {
      const declared = declaredClasses(readUploadFile(css))
      const referenced = referencedClasses(readUploadFile(tsx))
      expect(declared.size, `${css} declares no classes`).toBeGreaterThan(0)
      const dead = [...declared].filter((name) => !referenced.has(name))
      expect(dead, `${css} declares classes ${tsx} never reaches`).toEqual([])
    }
  })

  it('paints from tokens, with no raw hex', () => {
    // The Global Constraint, and a thing no rendering test can see. The census
    // in `stylesheets.test.ts` records that a colour declaration exists; it does
    // not care what the value is.
    for (const { css } of painted()) {
      const source = readUploadFile(css).replace(/\/\*[\s\S]*?\*\//g, '')
      expect(source.match(/#[0-9A-Fa-f]{3,8}\b/g) ?? [], `${css} has a raw hex`).toEqual([])
    }
  })
})

/** The label that wraps the input, which is the drop target.
 *
 *  Found through the input rather than by a test id: the target has to be the
 *  thing a person sees and aims at, and the input's own label is that box. If
 *  the drop handlers ever move off it, this throws rather than silently
 *  testing a `<main>` that accepts everything.
 */
function dropZone(): HTMLElement {
  const label = field().closest('label')
  if (label === null) {
    throw new Error('the file input is not inside a label -- the drop target moved')
  }
  return label
}

/** A drop, the way a browser delivers one.
 *
 *  `types: ['Files']` is part of the shape: a drag carrying text sets
 *  `types: ['text/plain']` and no `files`, and a handler that reads `files`
 *  without looking would treat it as an empty drop.
 */
function drop(zone: HTMLElement, file: File): void {
  fireEvent.drop(zone, { dataTransfer: { files: [file], types: ['Files'] } })
}

describe('UploadScreen drag-and-drop (P5.T2)', () => {
  it('sends a dropped photograph down the same path a chosen one takes', async () => {
    const upload = vi.fn().mockResolvedValue({
      receipts: [{ receipt_id: 'r-1', image_key: 'k' }],
      status: 'pending',
    })
    const progress = vi.fn().mockResolvedValue({ status: 'pending', stage: null, detail: null })
    render(<UploadScreen upload={upload} progress={progress} />)

    drop(dropZone(), jpeg())

    // The SAME `offer`, not a second copy of the accept-then-upload logic. A
    // parallel path is how a refusal ends up enforced on one route and not the
    // other.
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1))
    expect((upload.mock.calls[0][0] as File).name).toBe('receipt.jpg')
  })

  it('refuses a dropped file the client refuses from the picker, and uploads nothing', async () => {
    const upload = vi.fn()
    render(<UploadScreen upload={upload} />)

    drop(dropZone(), new File([new Uint8Array(3)], 'notes.txt', { type: 'text/plain' }))

    // **This is the case `accept` cannot cover.** A drag-and-drop ignores the
    // input's `accept` outright, so the refusal has to live in
    // `rejectionReason` and the drop has to go through it. A drop that
    // bypassed it would upload a file the picker would have refused.
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('Accepted types are')
    expect(upload).not.toHaveBeenCalled()
  })

  it('prevents the default on dragover, or the browser leaves the app', async () => {
    render(<UploadScreen upload={vi.fn()} />)

    const dragover = new Event('dragover', { bubbles: true, cancelable: true })
    dropZone().dispatchEvent(dragover)

    // Without this the browser treats the drag as a navigation and OPENS the
    // file, replacing the page. The drop handler never runs and the failure
    // looks like "drag-and-drop does nothing" rather than like a missing
    // `preventDefault`. Nothing else on the screen can show this.
    expect(dragover.defaultPrevented).toBe(true)
  })

  it('accepts a drop while an earlier send is still in flight', async () => {
    // The inverse of the first version, which rejected a second file mid-flight
    // because the screen could only follow one. The batch flow accepts the next
    // file while the last is still going: uploads are concurrent, so both are
    // sent.
    const upload = vi.fn().mockReturnValue(new Promise<UploadAccepted>(() => {}))
    render(<UploadScreen upload={upload} />)

    choose(field(), jpeg('first.jpg'))
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1))
    drop(dropZone(), jpeg('second.jpg'))

    await waitFor(() => expect(upload).toHaveBeenCalledTimes(2))
    expect((upload.mock.calls[0][0] as File).name).toBe('first.jpg')
    expect((upload.mock.calls[1][0] as File).name).toBe('second.jpg')
  })

  it('sends every file in a multi-file drop', async () => {
    // A drop can carry a whole selection. `accept` does not apply to a drop, so
    // each file still goes through `rejectionReason`; here all are valid.
    const upload = vi.fn().mockResolvedValue({
      receipts: [{ receipt_id: 'r-1', image_key: 'k' }],
      status: 'pending',
    })
    const progress = vi.fn().mockResolvedValue({ status: 'pending', stage: null, detail: null })
    render(<UploadScreen upload={upload} progress={progress} />)

    fireEvent.drop(dropZone(), {
      dataTransfer: { files: [jpeg('a.jpg'), jpeg('b.jpg')], types: ['Files'] },
    })

    await waitFor(() => expect(upload).toHaveBeenCalledTimes(2))
    expect((upload.mock.calls[0][0] as File).name).toBe('a.jpg')
    expect((upload.mock.calls[1][0] as File).name).toBe('b.jpg')
  })
})
