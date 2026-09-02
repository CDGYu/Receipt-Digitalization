import { useEffect, useMemo, useState } from 'react'
import { ApiError } from './api/client'
import { fetchSettings, saveSettings } from './api/admin'
import type { EditableSetting, SettingsState } from './api/admin'
import styles from './SettingsMenu.module.css'

interface SystemSettingsControlProps {
  /** Whether the signed-in user may change these. Admins can; reviewers see the
   *  values read-only. A courtesy gate -- the API refuses a reviewer's PATCH with
   *  403 regardless. */
  readonly canEdit: boolean
}

/** The form value for one field: a string for text/number inputs, a boolean for
 *  checkboxes. Kept as the raw thing the control produces so what the user typed
 *  is what gets sent; the server owns coercion and validation. */
type Draft = Record<string, string | boolean>

/** Turn the server's typed value into the editable form value.
 *
 * A checkbox needs a real boolean; every other control edits text. A `null`
 * (a blank text field, or an unset number) becomes an empty string so the input
 * is controlled from the first render rather than flipping controlled state. */
function toDraftValue(setting: EditableSetting): string | boolean {
  if (setting.kind === 'bool') {
    return setting.value === true
  }
  return setting.value === null ? '' : String(setting.value)
}

function buildDraft(settings: EditableSetting[]): Draft {
  const draft: Draft = {}
  for (const setting of settings) {
    draft[setting.field] = toDraftValue(setting)
  }
  return draft
}

/** Read, and (for an admin) change, the system's tuning settings.
 *
 * Fetched on mount rather than passed in: these are deployment-global and every
 * place that shows them should agree with the server. The form is a local draft
 * seeded from the server's values; Save sends only the fields the user actually
 * changed, and the server's response (the full refreshed state) replaces both
 * the draft and the baseline in one round trip -- so a save is confirmed by the
 * server, never assumed.
 *
 * A reviewer sees the same values as read-only statements. The save button and
 * the inputs are simply not rendered for them; the API is the real gate.
 *
 * Errors are the server's own words (an out-of-range threshold, a non-number),
 * shown at the form rather than guessed at per-field, because the server
 * validates the whole patch atomically -- the first bad field rejects the save
 * and nothing is written.
 */
export function SystemSettingsControl({ canEdit }: SystemSettingsControlProps) {
  const [state, setState] = useState<SettingsState | null>(null)
  const [draft, setDraft] = useState<Draft>({})
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let live = true
    fetchSettings()
      .then((next) => {
        if (live) {
          setState(next)
          setDraft(buildDraft(next.settings))
        }
      })
      .catch((caught: unknown) => {
        if (live) {
          setLoadError(
            caught instanceof ApiError ? caught.message : 'could not read the settings',
          )
        }
      })
    return () => {
      live = false
    }
  }, [])

  /** The fields whose draft differs from what the server last returned. Only
   *  these are sent, so an untouched form saves nothing and a save is cheap. */
  const changed = useMemo(() => {
    if (state === null) {
      return [] as EditableSetting[]
    }
    return state.settings.filter((setting) => draft[setting.field] !== toDraftValue(setting))
  }, [state, draft])

  function setField(field: string, value: string | boolean): void {
    setSaved(false)
    setDraft((current) => ({ ...current, [field]: value }))
  }

  async function save(): Promise<void> {
    if (changed.length === 0 || busy) {
      return
    }
    setBusy(true)
    setSaveError(null)
    setSaved(false)
    const overrides: Record<string, string | boolean | null> = {}
    for (const setting of changed) {
      const value = draft[setting.field]
      // A blank text/number field clears the setting back to its default; the
      // server reads null (or empty) as "unset".
      overrides[setting.field] = value === '' ? null : value
    }
    try {
      const next = await saveSettings(overrides)
      setState(next)
      setDraft(buildDraft(next.settings))
      setSaved(true)
    } catch (caught) {
      setSaveError(caught instanceof ApiError ? caught.message : 'could not save the settings')
    } finally {
      setBusy(false)
    }
  }

  function resetField(setting: EditableSetting): void {
    // Reset means "clear the override": send an empty value, which the server
    // turns back into the booted default. Staged into the draft so it saves with
    // everything else on the next Save, rather than firing its own request.
    setField(setting.field, setting.kind === 'bool' ? false : '')
  }

  if (loadError !== null) {
    return (
      <div className={styles.section}>
        <h2 className={styles.sectionTitle}>System settings</h2>
        <span className={styles.error} role="alert">
          Could not load the settings: {loadError}
        </span>
      </div>
    )
  }

  if (state === null) {
    return (
      <div className={styles.section}>
        <h2 className={styles.sectionTitle}>System settings</h2>
        <span className={styles.hint}>Loading…</span>
      </div>
    )
  }

  // Group the fields for display, preserving first-seen order of both groups and
  // fields within them, so the screen order follows the allow-list's order.
  const groups: { name: string; fields: EditableSetting[] }[] = []
  for (const setting of state.settings) {
    let group = groups.find((candidate) => candidate.name === setting.group)
    if (group === undefined) {
      group = { name: setting.group, fields: [] }
      groups.push(group)
    }
    group.fields.push(setting)
  }

  return (
    <div className={styles.section}>
      <h2 className={styles.sectionTitle}>System settings</h2>
      {!canEdit && (
        <p className={styles.hint}>Only an administrator can change these.</p>
      )}
      {groups.map((group) => (
        <fieldset key={group.name} className={styles.settingsGroup} disabled={busy || !canEdit}>
          <legend className={styles.settingsGroupTitle}>{group.name}</legend>
          {group.fields.map((setting) => (
            <SettingField
              key={setting.field}
              setting={setting}
              value={draft[setting.field]}
              canEdit={canEdit}
              onChange={(value) => setField(setting.field, value)}
              onReset={() => resetField(setting)}
            />
          ))}
        </fieldset>
      ))}
      {canEdit && (
        <div className={styles.settingsActions}>
          <button
            type="button"
            className={styles.button}
            disabled={busy || changed.length === 0}
            onClick={() => void save()}
          >
            {busy ? 'Saving…' : 'Save changes'}
          </button>
          {saved && changed.length === 0 && (
            <span className={styles.settingsSaved} role="status">
              Saved. New receipts use these settings right away.
            </span>
          )}
        </div>
      )}
      {saveError !== null && (
        <span className={styles.error} role="alert">
          Could not save: {saveError}
        </span>
      )}
    </div>
  )
}

interface SettingFieldProps {
  readonly setting: EditableSetting
  readonly value: string | boolean
  readonly canEdit: boolean
  readonly onChange: (value: string | boolean) => void
  readonly onReset: () => void
}

/** One labelled control: a checkbox for a boolean, a text box for the rest.
 *
 *  A reviewer (or a field with `canEdit` false) sees the value as a plain
 *  statement instead of an input -- a disabled input reads as "you may edit,
 *  just not now", which is not the truth for a reviewer. */
function SettingField({ setting, value, canEdit, onChange, onReset }: SettingFieldProps) {
  const overridden = setting.source === 'override'

  if (!canEdit) {
    const shown =
      setting.kind === 'bool'
        ? setting.value === true
          ? 'On'
          : 'Off'
        : setting.value === null || setting.value === ''
          ? 'Not set'
          : String(setting.value)
    return (
      <div className={styles.settingRow}>
        <span className={styles.settingLabel}>{setting.label}</span>
        <span className={styles.settingReadonly}>{shown}</span>
        <span className={styles.hint}>{setting.help}</span>
      </div>
    )
  }

  if (setting.kind === 'bool') {
    return (
      <label className={styles.settingRow}>
        <span className={styles.settingLabelRow}>
          <input
            type="checkbox"
            checked={value === true}
            onChange={(event) => onChange(event.target.checked)}
          />
          <span className={styles.settingLabel}>{setting.label}</span>
        </span>
        <span className={styles.hint}>{setting.help}</span>
      </label>
    )
  }

  const inputMode = setting.kind === 'int' || setting.kind === 'decimal' ? 'decimal' : 'text'
  return (
    <div className={styles.settingRow}>
      <label className={styles.settingLabel} htmlFor={`setting-${setting.field}`}>
        {setting.label}
      </label>
      <input
        id={`setting-${setting.field}`}
        className={styles.settingInput}
        type="text"
        inputMode={inputMode}
        value={value === true || value === false ? '' : value}
        placeholder={setting.default === null ? 'Not set' : String(setting.default)}
        onChange={(event) => onChange(event.target.value)}
      />
      <span className={styles.hint}>{setting.help}</span>
      {overridden && (
        <button type="button" className={styles.settingReset} onClick={onReset}>
          Reset to default
        </button>
      )}
    </div>
  )
}
