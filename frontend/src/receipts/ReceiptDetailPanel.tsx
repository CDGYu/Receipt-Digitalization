import { useEffect, useState } from 'react'
import {
  fetchImageUrl as defaultFetchImageUrl,
  fetchReceipt as defaultFetchReceipt,
  patchReceipt as defaultPatchReceipt,
} from '../api/review'
import { ConfidenceRail } from '../review/ConfidenceRail'
import { FindingsPanel } from '../review/FindingsPanel'
import { ImagePane } from '../review/ImagePane'
import { LineItemsTable } from '../review/LineItemsTable'
import { ReceiptForm } from '../review/ReceiptForm'
import { buildPatch, fieldsFromReceipt, type FieldMap } from '../review/patch'
import type { ReceiptDetail } from '../api/types'
import styles from './ReceiptDetailPanel.module.css'

export interface ReceiptDetailPanelProps {
  readonly receiptId: string
  readonly onClose: () => void
  /** Injected so a test drives the panel without a `fetch`, the seam
   *  `UploadScreen` uses for the same reason. Defaults are the real client. */
  readonly fetchReceipt?: (id: string) => Promise<ReceiptDetail>
  readonly fetchImageUrl?: (id: string) => Promise<string>
  readonly patchReceipt?: (id: string, patch: FieldMap) => Promise<ReceiptDetail>
}

/** One finished receipt, opened from the results list without leaving it.
 *
 * ## A second entry point, never a second write path
 *
 * Every part of this is a `src/review` component and every save goes through
 * `buildPatch` + `patchReceipt` -- the same pair `ReviewScreen` uses. Two ways
 * to *reach* an edit, one implementation of the edit. That is not tidiness:
 * PAN redaction lives server-side in `_plan_change`, and `buildPatch` is what
 * makes an untouched field stay out of the request, so a second client-side
 * correction path is how both protections quietly stop applying on one route.
 *
 * ## What it deliberately does NOT do
 *
 * **No `completeTask`.** `ReviewScreen.approve()` is a PATCH *plus* a task
 * close. This receipt was reached from a list, not claimed from the queue, so
 * there is no task of this caller's to close -- and closing one anyway would
 * close a reviewer's. `patch_receipt` requires only an authenticated user and
 * no claim, which is exactly what makes the PATCH half stand alone.
 *
 * **No stash.** `review/stash.ts` is one module-level slot keyed by `taskId`,
 * overwritten unconditionally by `remember()`. An edit here has no task to key
 * by, and stashing would evict a reviewer's in-flight draft -- then
 * `SignOutControl`, which gates on `hasDirtyEdits()`, would demand
 * confirmation naming a task that does not exist. A draft that survives a 401
 * here would need its own mechanism keyed by receipt id, and its own design.
 *
 * **No typed inputs.** The controls come from `ReceiptForm` unchanged, and its
 * fields are plain text on purpose: `<input type="date">` renders `value=''`
 * for a misread `"1L/O7/2O26"`, discarding the very string a reviewer opened
 * the field to fix, and `<input type="time">` sends `HH:MM` over a stored
 * `HH:MM:SS`. Do not "improve" them here.
 */
export function ReceiptDetailPanel({
  receiptId,
  onClose,
  fetchReceipt = defaultFetchReceipt,
  fetchImageUrl = defaultFetchImageUrl,
  patchReceipt = defaultPatchReceipt,
}: ReceiptDetailPanelProps) {
  const [detail, setDetail] = useState<ReceiptDetail | null>(null)
  const [original, setOriginal] = useState<FieldMap>({})
  const [fields, setFields] = useState<FieldMap>({})
  const [failure, setFailure] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    let live = true
    void (async () => {
      try {
        const received = await fetchReceipt(receiptId)
        if (!live) return
        setDetail(received)
        const map = fieldsFromReceipt(received)
        // Two copies on purpose: `buildPatch` diffs the edited map against the
        // one that arrived, so the original has to survive editing.
        setOriginal(map)
        setFields(map)
      } catch {
        if (live) setFailure('This receipt could not be loaded.')
      }
    })()
    return () => {
      live = false
    }
  }, [receiptId, fetchReceipt])

  function onChange(path: string, value: string | null): void {
    setSaved(false)
    setFields((current) => ({ ...current, [path]: value }))
  }

  async function save(): Promise<void> {
    const patch = buildPatch(original, fields)
    // An untouched receipt sends nothing at all. `ReviewScreen` records the
    // same behaviour: an empty patch is a request nobody needs to make.
    if (Object.keys(patch).length === 0) {
      setSaved(true)
      return
    }
    setFailure(null)
    setSaving(true)
    try {
      const stored = await patchReceipt(receiptId, patch)
      setDetail(stored)
      const map = fieldsFromReceipt(stored)
      setOriginal(map)
      setFields(map)
      setSaved(true)
    } catch {
      setFailure('The correction did not reach the API.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <aside className={styles.panel} aria-label="Receipt detail">
      <header className={styles.bar}>
        <h2 className={styles.heading}>Receipt</h2>
        <div className={styles.actions}>
          <button
            type="button"
            className={styles.save}
            disabled={saving || detail === null}
            onClick={() => void save()}
          >
            {saving ? 'Saving' : 'Save'}
          </button>
          <button type="button" className={styles.close} onClick={onClose}>
            Close
          </button>
        </div>
      </header>

      {failure !== null && <p className={styles.failure}>{failure}</p>}
      {saved && failure === null && <p className={styles.saved}>Saved.</p>}

      {detail === null ? (
        <p className={styles.loading}>Loading the receipt.</p>
      ) : (
        <div className={styles.body}>
          <ImagePane key={detail.id} receiptId={detail.id} fetchUrl={fetchImageUrl} />
          <div className={styles.side}>
            <ConfidenceRail
              confidence={detail.confidence}
              reasons={detail.confidence_reasons}
            />
            <FindingsPanel findings={detail.findings} />
            <ReceiptForm fields={fields} onChange={onChange} />
            <LineItemsTable items={detail.line_items} fields={fields} onChange={onChange} />
          </div>
        </div>
      )}
    </aside>
  )
}
