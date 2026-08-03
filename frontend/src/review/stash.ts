import type { FieldMap } from './patch'

/** The reviewer's unsubmitted edits, surviving a 401's unmount.
 *
 * Module state, deliberately -- the same choice `session.ts` records for the
 * signed-in flag. A 401 unmounts `ReviewScreen`; on re-login ADR-0016 hands
 * the same task back (`GET /review/next` resumes the caller's own
 * `IN_PROGRESS` row), and this is where the edits wait in between. Nothing
 * touches browser storage: a full page reload starts clean, exactly as it
 * did before this module existed -- that trade is a user ruling recorded in
 * the design doc (§2).
 *
 * The overlay is the **dirty diff** (`buildPatch(original, fields)`), never
 * the whole form: restoring is `{ ...freshOriginal, ...overlay }`, so paths
 * the reviewer never touched always show what the server holds now. After a
 * complete-step 401 (the PATCH landed, the close did not) the fresh original
 * already contains the applied values, the overlay overlays equals onto
 * equals, and the form comes back clean rather than falsely dirty --
 * review-screen.test.tsx pins that.
 *
 * At most one entry. A reviewer holds at most one claimed task (`fetchNext`
 * is called at most once per task in hand), so a second `remember` for a
 * different task means the first task is gone -- keeping its edits would be
 * a leak, not a kindness.
 */
let stashed: { readonly taskId: string; readonly overlay: FieldMap } | null = null

export function remember(taskId: string, overlay: FieldMap): void {
  stashed = { taskId, overlay: { ...overlay } }
}

/** The overlay for `taskId`, or null. Non-consuming: a second 401 before any
 *  new edit must not lose what the first one kept. Returns a copy. */
export function restore(taskId: string): FieldMap | null {
  if (stashed === null || stashed.taskId !== taskId) {
    return null
  }
  return { ...stashed.overlay }
}

/** Whether anything worth confirming away is held (the sign-out gate). */
export function hasDirtyEdits(): boolean {
  return stashed !== null && Object.keys(stashed.overlay).length > 0
}

export function clear(): void {
  stashed = null
}
