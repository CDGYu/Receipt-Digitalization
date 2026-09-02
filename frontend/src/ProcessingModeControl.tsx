import { useEffect, useState } from 'react'
import { ApiError } from './api/client'
import { fetchProcessingMode, setProcessingMode } from './api/admin'
import type { ProcessingModeState } from './api/admin'
import styles from './SettingsMenu.module.css'

/** The three modes, with the human-facing label and one line of what it does.
 *
 * The tokens (`local`/`cloud`/`hybrid`) are the server's vocabulary and are
 * spelled here to render a stable order and description; the server still owns
 * the list and validates the write, so an unknown token arriving in `modes`
 * from the API falls through to a bare-token label rather than being hidden.
 */
const MODE_COPY: Record<string, { label: string; hint: string }> = {
  hybrid: {
    label: 'Hybrid (recommended)',
    hint: 'Tries this computer first, then automatically hands off to the online service if this computer is too slow or cannot read the receipt. A good balance of speed, cost, and privacy.',
  },
  local: {
    label: 'Offline — this computer only',
    hint: 'Reads every receipt using only this computer. Your receipts never leave the machine, and it works without internet, but it can be slower.',
  },
  cloud: {
    label: 'Online — cloud service only',
    hint: 'Sends every receipt to the online service to be read. Usually faster and more accurate, but it needs internet and your receipts are sent off this machine.',
  },
}

function labelFor(mode: string): string {
  return MODE_COPY[mode]?.label ?? mode
}

interface ProcessingModeControlProps {
  /** Whether the signed-in user may change the mode. Admins can; reviewers see
   *  it read-only. This is a courtesy gate -- the API refuses a reviewer's PATCH
   *  with 403 regardless -- so a reviewer sees the current mode and why it is not
   *  theirs to change, rather than a control that 403s on click. */
  readonly canEdit: boolean
}

/** Read, and (for an admin) change, how receipts are processed.
 *
 * The state is fetched from `GET /processing-mode` on mount rather than passed
 * in: the mode is deployment-global, it changes rarely, and every place that
 * shows it should agree with the server rather than with a prop threaded down
 * from `main.tsx`. A failed read leaves the control saying so and offers no
 * radios -- a mode picker that cannot show the current mode must not invite a
 * change it cannot ground.
 *
 * A write is optimistic only after the server confirms it: `setProcessingMode`
 * returns the whole refreshed state (mode + which modes are distinct for this
 * deployment), so a successful PATCH replaces the local state with the server's
 * answer in one round trip and a failed one leaves the previous selection
 * standing under the server's error.
 *
 * `available` narrows which radios are live: with no cloud model configured all
 * three modes build the same local rung, so `cloud` and `hybrid` are shown
 * disabled with a note rather than as switches that would silently do nothing.
 */
export function ProcessingModeControl({ canEdit }: ProcessingModeControlProps) {
  const [state, setState] = useState<ProcessingModeState | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [writeError, setWriteError] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    fetchProcessingMode()
      .then((next) => {
        if (live) {
          setState(next)
        }
      })
      .catch((caught: unknown) => {
        if (live) {
          setLoadError(caught instanceof ApiError ? caught.message : 'could not read the mode')
        }
      })
    return () => {
      live = false
    }
  }, [])

  async function choose(mode: string): Promise<void> {
    if (state === null || mode === state.mode || busy) {
      return
    }
    setBusy(true)
    setWriteError(null)
    try {
      setState(await setProcessingMode(mode))
    } catch (caught) {
      setWriteError(caught instanceof ApiError ? caught.message : 'could not change the mode')
    } finally {
      setBusy(false)
    }
  }

  if (loadError !== null) {
    return (
      <div className={styles.section}>
        <h2 className={styles.sectionTitle}>Processing mode</h2>
        <span className={styles.error} role="alert">
          Could not load the processing mode: {loadError}
        </span>
      </div>
    )
  }

  if (state === null) {
    return (
      <div className={styles.section}>
        <h2 className={styles.sectionTitle}>Processing mode</h2>
        <span className={styles.hint}>Loading…</span>
      </div>
    )
  }

  // A reviewer cannot change it, so there is nothing to choose among -- show the
  // current mode and its description as a plain statement rather than a disabled
  // radio group, which would read as "you may pick, but not now".
  if (!canEdit) {
    return (
      <div className={styles.section}>
        <h2 className={styles.sectionTitle}>Processing mode</h2>
        <p className={styles.readonlyValue}>{labelFor(state.mode)}</p>
        <p className={styles.hint}>{MODE_COPY[state.mode]?.hint ?? ''}</p>
        <p className={styles.hint}>Only an administrator can change this.</p>
      </div>
    )
  }

  return (
    <fieldset className={styles.section} disabled={busy}>
      <legend className={styles.sectionTitle}>Processing mode</legend>
      {state.modes.map((mode) => {
        const distinct = state.available.includes(mode)
        const copy = MODE_COPY[mode]
        return (
          <label key={mode} className={styles.modeOption}>
            <input
              type="radio"
              name="processing-mode"
              value={mode}
              // The accessible name is the mode's own label, not the label plus
              // every hint in the row: a non-distinct mode's hint mentions
              // another mode by name, which would otherwise make one radio
              // addressable under two mode names. Screen readers announce the
              // label; the hints are supporting text beside it.
              aria-label={copy?.label ?? mode}
              checked={state.mode === mode}
              // A mode that is not distinct for this deployment builds the same
              // rung as the current one; disable it rather than offer a no-op.
              // The current mode is never disabled even if it is the only
              // distinct one, so the checked radio is always interactive-looking.
              disabled={!distinct && state.mode !== mode}
              onChange={() => void choose(mode)}
            />
            <span className={styles.modeText}>
              <span className={styles.modeLabel}>{copy?.label ?? mode}</span>
              {copy !== undefined && <span className={styles.hint}>{copy.hint}</span>}
              {!distinct && state.mode !== mode && (
                <span className={styles.hint}>
                  The online service isn’t set up on this system, so this option works the
                  same as “Offline — this computer only.”
                </span>
              )}
            </span>
          </label>
        )
      })}
      {writeError !== null && (
        <span className={styles.error} role="alert">
          Could not change the mode: {writeError}
        </span>
      )}
    </fieldset>
  )
}
