# Upload and processing screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A receipt can enter the system from a browser, and the person who dropped it watches the pipeline work instead of watching nothing.

**Architecture:** One new route `/app/upload` carrying two states in one mount. A drop zone produces a list of files; each uploads through `POST /upload`; when the list holds exactly one item, that item's processing view fills the screen. **The screen becomes the processing view in place** — no navigation, because ADR-0027 decision 4 makes every route change a real document load and a page flash at that moment is the demo's worst beat. Progress comes from polling `GET /receipts/{id}/progress`, which plan 1 shipped.

**Tech Stack:** React 19, Vite, TypeScript, CSS Modules, Vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-08-23-upload-and-visual-refresh-design.md` — §3 (decisions 5-9) and §4 (decisions 10-11). *(Dated the day before this plan; verified present 2026-08-24, not guessed from this plan's own date.)*

**This is plan 2 of 3.** Plan 1 (the progress mechanism) is merged into this branch. **Plan 3 is the visual refresh and is NOT this plan** — build this screen in the *existing* visual language, with the existing tokens. Do not introduce the Editorial palette, the grotesque display face, or any new token. Plan 3 changes token values, and a screen built against tokens gets that for free.

## Global Constraints

- **`npm test` is `vitest run`.** A single file is `npx vitest run tests/<file>` from `frontend/`.
- **Vitest sets `css: false`.** A `.module.css` import returns a proxy answering for **any** key, so **class names are unpinnable by rendering tests** — a renamed class ships unpainted with every gate green. Never assert a class name in a rendering test. Guard by the stylesheet census (`frontend/tests/stylesheets.test.ts`) and a reference-to-declaration guard, and know that **neither joins a class to the DOM**.
- **No new runtime dependency.** Runtime deps are exactly `react`, `react-dom` and two `@fontsource` packages (ADR-0027 decisions 2 and 3). No router, no upload library, no date library.
- **`/app/*` only, and every path literal's last segment must be free of a dot.** The SPA mount falls back to the shell only when the final segment has no file extension, so `/app/receipt/inv-2026.01` 404s as a missing *file*. Pinned by `it('declares no client-side path whose last segment carries a dot')` in `frontend/tests/admin-screen.test.tsx`.
- **`null` is not `0` and neither is empty** (ADR-0027 decision 5).
- **Money is a string**; no `<input type="number">`, no `valueAsNumber` (ADR-0015). Not exercised here, but the guard test `frontend/tests/no-float-in-money-path.test.ts` runs over the whole tree.
- **A screen nothing mounts is not delivered** (ADR-0046 decision 5). The route, the switch and the mount land in the same task as the screen.
- **The client shows the server's reason, never its own guess**, for anything the server rejected. `request<T>` throws `ApiError(status, message)` carrying the server's message.
- **Progress is narration; `status` is truth.** The screen decides work is finished from `status`, never from `stage` going quiet.
- **Stage by explicit path, never `git add -A`.**

---

## What is already true, measured 2026-08-24

Do not re-derive these; do check any you are about to depend on.

| fact | where |
|---|---|
| `POST /upload` takes **one file**, returns `202 {receipt_id, image_key, status}` | `src/receipts/review/api.py` |
| `require_upload` is *API key **or** any signed-in user* — a reviewer may upload | `src/receipts/review/auth.py` |
| Accepted suffixes: `.jpg .jpeg .png .webp .pdf .heic .heif`; bound `settings.max_upload_mb`, default **25** | `src/receipts/ingest/ingest.py` |
| **A PDF is accepted and then always fails at `preprocess`** | ISSUE-027 |
| `GET /receipts/{id}/progress` returns `{status, stage, detail}`; `stage`/`detail` are `null` when nothing is narrating | plan 1 |
| `request<T>` sets `Content-Type: application/json` **unless the body is `FormData`** | `frontend/src/api/client.ts` |
| `request<T>` throws `ApiError(status, message)` on any non-2xx, and fires the 401 handler | `frontend/src/api/client.ts` |
| Nothing in the app polls anything | `main.tsx`, `ReceiptsScreen`, `ReviewScreen` all say so |
| `Route` is `'login' \| 'review' \| 'admin' \| 'receipts'`; the switch uses `startsWith` and defaults to `review` | `frontend/src/route.ts` |
| UI components available: `Button`, `Chip`, `Value` | `frontend/src/ui/` |

---

## File Structure

| file | responsibility |
|---|---|
| **Create** `frontend/src/api/upload.ts` | `uploadReceipt`, `fetchProgress`, and the accepted-type/size bounds as data. No React. |
| **Create** `frontend/tests/upload-api.test.ts` | Task 1's pins. |
| **Create** `frontend/src/upload/UploadScreen.tsx` | The drop zone, the list, and the in-place switch to processing. |
| **Create** `frontend/src/upload/UploadScreen.module.css` | Its styles, in the **existing** token vocabulary. |
| **Create** `frontend/src/upload/ProcessingView.tsx` | Receipt left, timeline right. Polls, narrates, stops on a terminal status. |
| **Create** `frontend/tests/upload-screen.test.tsx` | Tasks 2 and 3's pins. |
| **Modify** `frontend/src/route.ts` | `'upload'` in the union and the switch. |
| **Modify** `frontend/src/main.tsx` | Mount it. |
| **Modify** `frontend/tests/admin-screen.test.tsx` | Extend the route-switch and dot-rule pins. |

---

## Task 1: The upload and progress API module

**Files:**
- Create: `frontend/src/api/upload.ts`
- Test: `frontend/tests/upload-api.test.ts`

**Interfaces — Produces:**
```ts
export const ACCEPTED_SUFFIXES: readonly string[]   // what the client will send: the
                                                    // server's list MINUS `.pdf` (ISSUE-027)
export const MAX_UPLOAD_MB: number                  // 25
export interface UploadAccepted { receipt_id: string; image_key: string; status: string }
export interface ProgressReport { status: string | null; stage: string | null; detail: string | null }
export function rejectionReason(file: {name: string; size: number}): string | null
export function uploadReceipt(file: File): Promise<UploadAccepted>
export function fetchProgress(receiptId: string): Promise<ProgressReport>
```

- [ ] **Step 1: Write the failing tests**

Create `frontend/tests/upload-api.test.ts`:

```ts
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

describe('what the client refuses before spending an upload', () => {
  it('names the size bound the server enforces, not a rounder one', () => {
    expect(MAX_UPLOAD_MB).toBe(25)
  })

  it('accepts every suffix the server accepts, in either case', () => {
    for (const suffix of ACCEPTED_SUFFIXES) {
      expect(rejectionReason({ name: `receipt${suffix}`, size: 1024 })).toBeNull()
      expect(rejectionReason({ name: `RECEIPT${suffix.toUpperCase()}`, size: 1024 })).toBeNull()
    }
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

  it('refuses a file over the bound and names the bound', () => {
    const tooBig = MAX_UPLOAD_MB * 1024 * 1024 + 1
    expect(rejectionReason({ name: 'big.jpg', size: tooBig })).toMatch(/25/)
    expect(rejectionReason({ name: 'ok.jpg', size: tooBig - 2 })).toBeNull()
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
    expect(init?.body).toBeInstanceOf(FormData)
    // The browser must choose the multipart boundary. A Content-Type we set
    // here has no boundary and makes the body unparseable at the server.
    const headers = new Headers(init?.headers)
    expect(headers.get('Content-Type')).toBeNull()
  })

  it('surfaces the server-s own reason when the server refuses', async () => {
    stubFetch(400, { detail: 'not a receipt image: image/gif' })
    const file = new File([new Uint8Array([1])], 'sneaky.jpg', { type: 'image/jpeg' })

    // The client checks an extension; the server sniffs bytes. They can
    // legitimately disagree, and the server is the one that knows.
    await expect(uploadReceipt(file)).rejects.toThrow(/not a receipt image/)
  })
})

describe('fetchProgress', () => {
  it('reads the three fields the route returns', async () => {
    stubFetch(200, { status: 'pending', stage: 'extract', detail: 'attempt 1' })
    expect(await fetchProgress('r-1')).toEqual({
      status: 'pending',
      stage: 'extract',
      detail: 'attempt 1',
    })
  })

  it('carries a null stage through as null, never as empty text', async () => {
    // `null` is not `''` (ADR-0027 decision 5). A null stage means nothing is
    // narrating; an empty string would render a blank row where none belongs.
    stubFetch(200, { status: 'pending', stage: null, detail: null })
    const report = await fetchProgress('r-1')
    expect(report.stage).toBeNull()
    expect(report.detail).toBeNull()
  })
})
```

- [ ] **Step 2: Run to verify it fails**

From `frontend/`: `npx vitest run tests/upload-api.test.ts`
Expected: FAIL — cannot resolve `../src/api/upload`.

- [ ] **Step 3: Implement**

Create `frontend/src/api/upload.ts`:

```ts
import { request } from './client'

/** The suffixes `validate_upload` accepts, minus the one that cannot work.
 *
 * `.pdf` is deliberately ABSENT. The server accepts it -- it is in
 * `_ALLOWED_SUFFIXES` -- and then every PDF dies at `preprocess`, because
 * `expand_pdf` has no caller and `load_image` refuses the suffix (ISSUE-027).
 * Refusing here is stricter than the server on purpose: accepting a file that
 * is guaranteed to fail is the worst of the available behaviours.
 */
export const ACCEPTED_SUFFIXES: readonly string[] = [
  '.jpg',
  '.jpeg',
  '.png',
  '.webp',
  '.heic',
  '.heif',
]

/** `settings.max_upload_mb`'s default. The server is the authority; this is a
 *  courtesy check so an oversized file does not cost an upload first. */
export const MAX_UPLOAD_MB = 25

export interface UploadAccepted {
  receipt_id: string
  image_key: string
  status: string
}

export interface ProgressReport {
  status: string | null
  stage: string | null
  detail: string | null
}

/** Why this file will not be sent, or `null` if it will.
 *
 * **A courtesy, never an authority.** This reads a filename; the server sniffs
 * magic bytes. When they disagree the server is right, and `uploadReceipt`
 * surfaces the server's own message rather than a guess made here.
 */
export function rejectionReason(file: { name: string; size: number }): string | null {
  const dot = file.name.lastIndexOf('.')
  const suffix = dot === -1 ? '' : file.name.slice(dot).toLowerCase()
  if (suffix === '.pdf') {
    return 'PDFs cannot be processed yet (ISSUE-027). Upload a photograph instead.'
  }
  if (!ACCEPTED_SUFFIXES.includes(suffix)) {
    return `Accepted types are ${ACCEPTED_SUFFIXES.join(', ')}.`
  }
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
    return `Larger than the ${MAX_UPLOAD_MB} MB limit.`
  }
  return null
}

/** Store one receipt and queue it. One file per request: the route takes one. */
export function uploadReceipt(file: File): Promise<UploadAccepted> {
  const body = new FormData()
  body.append('file', file)
  // No `Content-Type` header: `mergeHeaders` skips its JSON default for a
  // FormData body precisely so the browser can set the multipart boundary.
  return request<UploadAccepted>('/upload', { method: 'POST', body })
}

/** What this receipt is doing, if anything is narrating it.
 *
 * `status` is the truth and `stage` is narration: a caller decides the work is
 * finished from `status`, never from `stage` going quiet. A dead worker stops
 * writing progress, and a screen waiting for a terminal *stage* waits forever.
 */
export function fetchProgress(receiptId: string): Promise<ProgressReport> {
  return request<ProgressReport>(`/receipts/${receiptId}/progress`)
}
```

- [ ] **Step 4: Run to verify it passes**

From `frontend/`: `npx vitest run tests/upload-api.test.ts`
Expected: PASS.

- [ ] **Step 5: Prove two pins red, one at a time, in the subject**

**(a)** In `uploadReceipt`, add `headers: { 'Content-Type': 'multipart/form-data' }` to the request init. Run. Expected: FAIL on the header assertion — that is the pin that stops a boundary-less Content-Type reaching the server. **Revert.**

**(b)** In `rejectionReason`, delete the `.pdf` branch. Run. Expected: FAIL on the PDF test **only** — the other refusals still pass, which proves the PDF case is pinned by itself and not riding on the unknown-suffix branch. **Revert.**

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/upload.ts frontend/tests/upload-api.test.ts
git diff --cached --stat
git commit -m "feat(upload): the client half of upload and progress"
```

---

## Task 2: The upload screen, its route, and its mount

**Files:**
- Create: `frontend/src/upload/UploadScreen.tsx`, `frontend/src/upload/UploadScreen.module.css`
- Modify: `frontend/src/route.ts`, `frontend/src/main.tsx`
- Test: `frontend/tests/upload-screen.test.tsx`, `frontend/tests/admin-screen.test.tsx`

**Interfaces:**
- Consumes: `rejectionReason`, `uploadReceipt`, `UploadAccepted` (Task 1).
- Produces: `export function UploadScreen(): JSX.Element`; `Route` gains `'upload'`.

**They land together on purpose.** A screen nothing mounts is deletable with every gate green (ADR-0046 decision 5), and that happened on this project in the screen immediately after a test was built to close it for `/app/admin`.

- [ ] **Step 1: Extend the route pins first**

In `frontend/tests/admin-screen.test.tsx`, inside `describe('the route switch, which is deliberately not a router')`, add to the existing exact-path test and the trailing-slash test:

```ts
    expect(currentRoute('/app/upload')).toBe('upload')
```
```ts
    expect(currentRoute('/app/upload/')).toBe('upload')
```

**Read the two tests first and add the lines to them** rather than writing new ones — they already enumerate every route, and a fifth route belongs in the same enumeration.

**The dot-rule test needs no change, and this was checked rather than assumed.** `it('declares no client-side path whose last segment carries a dot')` reads `src/route.ts` as text and derives its list with `/'(\/app\/[^']*)'/g`, so a new literal is covered the moment it is declared. Its own comment says so.

**But that comment says "so a fourth route is covered the day it is added", and yours is the fifth.** Fix that clause while you are there — a count in a comment is a number that moves without its sentence changing (review standard 5), and this one moves today. Prefer no number: "so a new route is covered the day it is added".

- [ ] **Step 2: Run to verify they fail**

From `frontend/`: `npx vitest run tests/admin-screen.test.tsx`
Expected: FAIL — `currentRoute('/app/upload')` returns `'review'`, the default.

**That failure is the honest one**: the default is `review`, so an unrouted path does not throw. A test asserting "not review" would have passed before the route existed.

- [ ] **Step 3: Add the route**

In `frontend/src/route.ts`:

```ts
export type Route = 'login' | 'review' | 'admin' | 'receipts' | 'upload'
```

and, beside the other `startsWith` branches:

```ts
  // `startsWith`, like its siblings, so the trailing slash a browser adds is
  // the same route rather than a silent fall-through to the review queue.
  if (pathname.startsWith('/app/upload')) {
    return 'upload'
  }
```

- [ ] **Step 4: Run to verify they pass**

From `frontend/`: `npx vitest run tests/admin-screen.test.tsx`
Expected: PASS.

- [ ] **Step 5: Write the screen's failing tests**

Create `frontend/tests/upload-screen.test.tsx`:

```tsx
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { UploadScreen } from '../src/upload/UploadScreen'

afterEach(cleanup)

function jpeg(name = 'receipt.jpg', bytes = 3): File {
  return new File([new Uint8Array(bytes)], name, { type: 'image/jpeg' })
}

describe('UploadScreen', () => {
  it('offers a file input a reviewer can find by its label', () => {
    render(<UploadScreen upload={vi.fn()} />)
    expect(screen.getByLabelText(/receipt/i)).toBeTruthy()
  })

  it('refuses a PDF without spending an upload, and says why', async () => {
    const upload = vi.fn()
    render(<UploadScreen upload={upload} />)

    await userEvent.upload(
      screen.getByLabelText(/receipt/i) as HTMLInputElement,
      new File([new Uint8Array(1)], 'scan.pdf', { type: 'application/pdf' }),
    )

    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(upload).not.toHaveBeenCalled()
  })

  it('shows the server-s own words when the server refuses', async () => {
    const upload = vi.fn().mockRejectedValue(new Error('not a receipt image: image/gif'))
    render(<UploadScreen upload={upload} />)

    await userEvent.upload(screen.getByLabelText(/receipt/i) as HTMLInputElement, jpeg())

    const alert = await screen.findByRole('alert')
    // The client checked a suffix and was happy; only the server knows this.
    // Inventing our own wording here would tell the reviewer something false.
    expect(alert.textContent).toContain('not a receipt image: image/gif')
  })

  it('hands one accepted file to the processing view, in place', async () => {
    const upload = vi
      .fn()
      .mockResolvedValue({ receipt_id: 'r-1', image_key: 'k', status: 'pending' })
    render(<UploadScreen upload={upload} progress={vi.fn().mockResolvedValue({
      status: 'pending', stage: 'triage', detail: null,
    })} />)

    await userEvent.upload(screen.getByLabelText(/receipt/i) as HTMLInputElement, jpeg())

    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1))
    // The drop zone is gone and the processing view is here -- same route, no
    // navigation. A page load at this moment is the beat this design avoids.
    await waitFor(() => expect(screen.queryByLabelText(/receipt/i)).toBeNull())
  })
})
```

- [ ] **Step 6: Run to verify they fail**

From `frontend/`: `npx vitest run tests/upload-screen.test.tsx`
Expected: FAIL — cannot resolve `../src/upload/UploadScreen`.

- [ ] **Step 7: Build the screen**

`UploadScreen` takes `upload` and `progress` as props defaulting to the real functions, so tests inject fakes and never touch `fetch` — the same seam `create_app`'s `submit` uses on the server. It holds a list of accepted receipts; when the list has exactly one entry it renders `ProcessingView` for it (Task 3 builds that; for this task render a placeholder element and replace it in Task 3).

Follow `frontend/src/receipts/ReceiptsScreen.tsx` for the shape: a `<main className={styles.screen}>`, a heading, `useState` per concern, and `ApiError`'s message surfaced verbatim. The error region must carry `role="alert"` and must always render when there is an error (ADR-0024).

**Write the CSS in the existing token vocabulary only** — `var(--space-*)`, `var(--color-*)`, `var(--radius-*)`. No raw hex outside `tokens.css`, and no new token: plan 3 owns the visual language.

- [ ] **Step 8: Mount it**

In `frontend/src/main.tsx`, add the branch to the existing chain, beside `receipts`:

```tsx
      ) : route === 'upload' ? (
        <UploadScreen />
```

and its import beside the others.

- [ ] **Step 9: Run both files, then the whole suite**

From `frontend/`: `npx vitest run tests/upload-screen.test.tsx tests/admin-screen.test.tsx`, then `npm test`.
Expected: PASS, no existing test edited beyond the two route lines in Step 1.

- [ ] **Step 10: Prove the mount is real**

Delete the `route === 'upload'` branch from `main.tsx` and run `npm test`.
**Expected: at least one test red.** If the whole suite stays green, the screen is mounted by nothing that any test can see — stop and report it, because that is exactly ADR-0046 decision 5's defect and it has shipped on this project before. **Revert either way.**

- [ ] **Step 11: Commit**

```bash
git add frontend/src/upload/ frontend/src/route.ts frontend/src/main.tsx frontend/tests/upload-screen.test.tsx frontend/tests/admin-screen.test.tsx
git diff --cached --stat
git commit -m "feat(upload): a receipt can enter the system from a browser"
```

---

## Task 3: The processing view

**Files:**
- Create: `frontend/src/upload/ProcessingView.tsx`
- Modify: `frontend/src/upload/UploadScreen.tsx` (render it), `frontend/src/upload/UploadScreen.module.css`
- Test: `frontend/tests/upload-screen.test.tsx`

**Interfaces:**
- Consumes: `fetchProgress`, `ProgressReport` (Task 1).
- Produces: `export function ProcessingView(props: { receiptId: string; fileName: string; progress?: (id: string) => Promise<ProgressReport>; poll?: (fn: () => void) => () => void }): JSX.Element`

**The polling seam is injected, not timed.** `poll` takes a callback and returns a cancel function; its default uses `setInterval`. Tests pass a `poll` that fires synchronously on demand, so **no test needs fake timers** and none is flaky. This mirrors `AdminScreen`'s injected `now`.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/tests/upload-screen.test.tsx`:

```tsx
import { ProcessingView } from '../src/upload/ProcessingView'

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
```

- [ ] **Step 2: Run to verify they fail**

From `frontend/`: `npx vitest run tests/upload-screen.test.tsx`
Expected: FAIL — cannot resolve `../src/upload/ProcessingView`.

- [ ] **Step 3: Build it**

Receipt on the left, timeline on the right — the same two-pane shape `ReviewScreen` uses, so the photograph does not move when processing ends. Completed stages collapse to a quiet line; the active row carries the weight.

Rules the code must hold, each stated in a comment where it applies:

- **Stop on `status`, never on `stage`.** A terminal status is anything other than `pending`.
- **A failed poll is not a failed receipt.** Keep polling; surface nothing alarming.
- **No count in any copy.** Not "checking 30 rules" — the rule count has already moved. Say what it is doing; the findings it produced are the number worth showing.
- **Any elapsed figure is labelled elapsed, never latency.** `VLM_TIMEOUT_S` bounds one HTTP attempt and the SDK retries, so no figure available here is a per-call measurement (ADR-0047 decision 8).
- **`null` renders as nothing, not as an empty row.**

- [ ] **Step 4: Run to verify they pass**

From `frontend/`: `npx vitest run tests/upload-screen.test.tsx`
Expected: PASS.

- [ ] **Step 5: Prove the load-bearing pin red, in the subject**

In `ProcessingView`, change the stop condition from `status` to `stage` — stop when `stage` is null instead of when `status` is terminal. Run.

**Expected: `keeps waiting on a null stage while the status is still pending` fails.** That is the design's decision 3 pinned: a dead worker that stops narrating must not be mistaken for a finished receipt. **Revert.**

- [ ] **Step 6: Run the gates**

From the repo root: `python scripts/verify.py` — **background it**, it exceeds a two-minute timeout, and do not edit source while it runs. All five must pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/upload/ frontend/tests/upload-screen.test.tsx
git diff --cached --stat
git commit -m "feat(upload): the wait is narrated, and status is what ends it"
```

---

## Self-Review

**Spec coverage.** §3 decision 5 (a list of one is still a list) → Task 2 Step 7. Decision 6 (in place, no navigation) → Task 2's fourth test. Decision 7 (the server's reason wins) → Task 1's `uploadReceipt` rejection test and Task 2's third test. Decision 8 (PDFs refused) → Task 1's `rejectionReason` and its Step 5(b) mutation. Decision 9 (HEIC degrades to a chip) → **GAP, see soft spot 1.** §4's layout → Task 3 Step 3. Decision 10 (elapsed not latency) and 11 (no counts) → Task 3 Step 3's stated rules, **enforced by review rather than by a test** — neither is mechanically checkable, and asserting on copy would pin a quotation that ages (this repo has two recorded instances of exactly that).

**Placeholder scan.** Task 2 Step 7 and Task 3 Step 3 describe the component rather than showing its full source. That is deliberate and it is a real weakness: the tests define the contract, the shape follows `ReceiptsScreen`, and a 200-line TSX listing written blind would be transcribed wrongly. **The implementer is expected to write the component, not paste it.**

**Type consistency.** `ProgressReport`, `UploadAccepted`, `rejectionReason`, `uploadReceipt`, `fetchProgress` are spelled identically in Tasks 1, 2 and 3. `progress` is the prop name in both `UploadScreen` and `ProcessingView`; `poll` only in `ProcessingView`.

**Known soft spots, stated rather than hidden.**

1. **HEIC degrading to a chip is specified in the design and pinned by nothing here.** A browser cannot render HEIC in an `<img>`, so a thumbnail must fall back to a filename and a type chip — but jsdom renders no images at all and cannot tell a broken one from a good one. This is ADR-0029's blind spot, and asserting it in Vitest would be theatre. **It needs the browser pass**, which is plan 3's decision 14.
2. **No test renders the two-pane layout as a layout.** jsdom lays nothing out. The receipt-does-not-move property — the whole reason for this shape — is invisible to every gate here and belongs to the same browser pass.
3. **Task 2 Step 10's mutation may pass for the wrong reason.** If the screen's own tests import `UploadScreen` directly, deleting the `main.tsx` branch leaves them green and only a mount-level test reddens. If nothing reddens, that is the finding — report it rather than inventing an assertion to cover it.
4. **The route default is `review`**, so every "wrong route" assertion in this plan must assert the *positive* — `toBe('upload')` — never "not review". A negative assertion there passes before the route exists.
