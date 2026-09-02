import { useEffect, useId, useRef, useState } from 'react'
import type { Identity } from './api/admin'
import { ProcessingModeControl } from './ProcessingModeControl'
import { SignOutControl } from './SignOutControl'
import { SystemSettingsControl } from './SystemSettingsControl'
import styles from './SettingsMenu.module.css'

interface SettingsMenuProps {
  /** Who is asking. `null` while `/auth/me` is still in flight -- treated as a
   *  non-admin, the same narrow-branch default `Nav` takes, so a reviewer's
   *  view never flashes admin controls before the identity resolves. */
  readonly identity: Identity | null
}

/** The header's settings menu: a disclosure button that opens a panel holding
 *  the processing-mode selector and the sign-out control.
 *
 *  This replaces the bare `SignOutControl` that used to sit in `main.tsx`'s
 *  header. Sign out now lives *inside* this menu rather than beside it, which is
 *  the whole point of the change -- ending the session is a settings action, not
 *  a primary navigation control competing with the nav links.
 *
 *  **The panel is a real open/closed disclosure, not an always-open block.** It
 *  is rendered only while open, so a closed menu is just the `Settings` button;
 *  `aria-expanded` and `aria-controls` tie the button to the panel for a screen
 *  reader. That means the `Sign out` button is not in the document until the
 *  menu is opened -- `app-header.test.tsx` opens it before asserting the control
 *  is reachable, because the deliverable it guards ("sign out is wired into the
 *  header") is now "reachable through the settings menu" rather than "sitting in
 *  the header bar".
 *
 *  It closes on `Escape` and on a click outside, the two conventions a menu
 *  opened by a button owes a keyboard and a pointer user. It does **not** close
 *  when a control inside it is used: changing the mode or arming the sign-out
 *  confirm should leave the panel open so the result (or the confirm) is
 *  visible. Sign-out itself navigates away, so there is nothing to close.
 */
export function SettingsMenu({ identity }: SettingsMenuProps) {
  const [open, setOpen] = useState(false)
  const panelId = useId()
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) {
      return
    }
    function onPointerDown(event: MouseEvent): void {
      if (rootRef.current !== null && !rootRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    function onKeyDown(event: KeyboardEvent): void {
      if (event.key === 'Escape') {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  return (
    <div className={styles.root} ref={rootRef}>
      <button
        type="button"
        className={styles.trigger}
        aria-expanded={open}
        aria-controls={panelId}
        aria-haspopup="true"
        onClick={() => setOpen((wasOpen) => !wasOpen)}
      >
        Settings
      </button>
      {open && (
        <div className={styles.panel} id={panelId} role="menu" aria-label="Settings">
          <ProcessingModeControl canEdit={identity?.role === 'admin'} />
          <SystemSettingsControl canEdit={identity?.role === 'admin'} />
          <div className={styles.section}>
            <h2 className={styles.sectionTitle}>Session</h2>
            <SignOutControl />
          </div>
        </div>
      )}
    </div>
  )
}
