import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SettingsMenu } from '../src/SettingsMenu'
import type { Identity } from '../src/api/admin'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const ADMIN: Identity = { username: 'ada', role: 'admin' }
const REVIEWER: Identity = { username: 'rob', role: 'reviewer' }

const MODES = ['hybrid', 'local', 'cloud']

/** The editable settings the tests exercise, in the server's row shape. A small
 *  fixed set keeps the assertions legible; the real list is longer. */
function settingsRows(
  threshold: string,
  thresholdSource: 'default' | 'override',
  model: string | null = null,
) {
  return [
    {
      field: 'auto_approve_threshold',
      label: 'Auto-approve confidence',
      help: 'How sure the system must be before it approves without a person.',
      kind: 'decimal',
      group: 'Approval',
      minimum: '0',
      maximum: '1',
      value: threshold,
      default: '0.95',
      source: thresholdSource,
    },
    {
      field: 'consistency_enabled',
      label: 'Double-check handwritten receipts',
      help: 'Reads each handwritten receipt several times and compares.',
      kind: 'bool',
      group: 'Accuracy',
      minimum: null,
      maximum: null,
      value: false,
      default: false,
      source: 'default',
    },
    {
      field: 'vlm_model_extract',
      label: 'Reading model (this computer)',
      help: 'The model this computer uses to read receipts. Must match a served model.',
      kind: 'model',
      group: 'Models (advanced)',
      minimum: null,
      maximum: null,
      value: model,
      default: 'granite3.2-vision:2b',
      source: model === null ? 'default' : 'override',
    },
  ]
}

/** A fetch answering both /processing-mode and /settings from small state
 *  machines, so a PATCH is reflected by the next read the way the real server
 *  does. Any other path 404s, surfacing a stray call as a readable failure. */
function stubApi(options?: {
  mode?: string
  available?: string[]
  editable?: boolean
  threshold?: string
}) {
  let mode = { mode: options?.mode ?? 'hybrid', modes: MODES, available: options?.available ?? MODES }
  const editable = options?.editable ?? true
  let threshold = options?.threshold ?? '0.95'
  let thresholdSource: 'default' | 'override' = 'default'
  let model: string | null = null

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'

    if (url.endsWith('/processing-mode')) {
      if (method === 'GET') {
        return jsonResponse(200, mode)
      }
      const body = JSON.parse(String(init!.body)) as { mode: string }
      mode = { ...mode, mode: body.mode }
      return jsonResponse(200, mode)
    }

    if (url.endsWith('/settings')) {
      if (method === 'GET') {
        return jsonResponse(200, {
          settings: settingsRows(threshold, thresholdSource, model),
          editable,
        })
      }
      const body = JSON.parse(String(init!.body)) as {
        overrides: Record<string, string | null>
      }
      const next = body.overrides.auto_approve_threshold
      if (next !== undefined && next !== null) {
        // The server's own bound: reject > 1 with an operator-facing 400.
        if (Number(next) > 1) {
          return jsonResponse(400, {
            error: { message: "'Auto-approve confidence' must be at most 1" },
          })
        }
        threshold = String(next)
        thresholdSource = 'override'
      }
      if ('vlm_model_extract' in body.overrides) {
        const m = body.overrides.vlm_model_extract
        model = m === null || m === '' ? null : String(m)
      }
      return jsonResponse(200, {
        settings: settingsRows(threshold, thresholdSource, model),
        editable,
      })
    }

    return jsonResponse(404, { error: { message: `unexpected ${url}` } })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

async function openMenu(): Promise<void> {
  await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
}

describe('the settings menu', () => {
  it('opens on the Settings button and closes on Escape', async () => {
    stubApi()
    render(<SettingsMenu identity={ADMIN} />)

    expect(screen.queryByRole('button', { name: 'Sign out' })).toBeNull()
    await openMenu()
    expect(await screen.findByRole('button', { name: 'Sign out' })).toBeTruthy()

    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('button', { name: 'Sign out' })).toBeNull()
  })

  it('nests the sign-out control inside the open panel', async () => {
    stubApi()
    render(<SettingsMenu identity={ADMIN} />)
    await openMenu()
    const panel = await screen.findByRole('menu', { name: 'Settings' })
    expect(within(panel).getByRole('button', { name: 'Sign out' })).toBeTruthy()
  })

  it('shows an admin the three modes and PATCHes the chosen one', async () => {
    const fetchMock = stubApi()
    render(<SettingsMenu identity={ADMIN} />)
    await openMenu()

    const hybrid = await screen.findByRole('radio', { name: /Hybrid/ })
    expect((hybrid as HTMLInputElement).checked).toBe(true)

    await userEvent.click(screen.getByRole('radio', { name: /Offline/ }))

    const patch = fetchMock.mock.calls.find(
      ([url, init]) => String(url).endsWith('/processing-mode') && (init as RequestInit)?.method === 'PATCH',
    )
    expect(patch).toBeTruthy()
    expect(JSON.parse(String((patch![1] as RequestInit).body))).toEqual({ mode: 'local' })

    const offline = await screen.findByRole('radio', { name: /Offline/ })
    expect((offline as HTMLInputElement).checked).toBe(true)
  })

  it('disables modes that are not distinct for a deployment with no cloud model', async () => {
    stubApi({ mode: 'local', available: ['local'] })
    render(<SettingsMenu identity={ADMIN} />)
    await openMenu()

    expect((await screen.findByRole('radio', { name: /Offline/ }) as HTMLInputElement).disabled).toBe(false)
    expect((screen.getByRole('radio', { name: /Hybrid/ }) as HTMLInputElement).disabled).toBe(true)
    expect((screen.getByRole('radio', { name: /Online/ }) as HTMLInputElement).disabled).toBe(true)
  })

  it('shows a reviewer the mode read-only, with no radios', async () => {
    stubApi({ mode: 'cloud', editable: false })
    render(<SettingsMenu identity={REVIEWER} />)
    await openMenu()

    expect(await screen.findByText('Online — cloud service only')).toBeTruthy()
    expect(screen.queryByRole('radio')).toBeNull()
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeTruthy()
  })

  it('surfaces a failed mode read as an alert', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/processing-mode')) {
        return jsonResponse(503, { error: { message: 'database unavailable' } })
      }
      // /settings answers fine, so the only alert is the mode read's.
      return jsonResponse(200, { settings: settingsRows('0.95', 'default'), editable: true })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<SettingsMenu identity={ADMIN} />)
    await openMenu()

    expect(await screen.findByText(/database unavailable/)).toBeTruthy()
    expect(screen.queryByRole('radio')).toBeNull()
  })
})

describe('the system settings editor', () => {
  it('lets an admin change a setting and saves only what changed', async () => {
    const fetchMock = stubApi()
    render(<SettingsMenu identity={ADMIN} />)
    await openMenu()

    const input = await screen.findByLabelText('Auto-approve confidence')
    expect((input as HTMLInputElement).value).toBe('0.95')

    await userEvent.clear(input)
    await userEvent.type(input, '0.99')
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))

    const patch = fetchMock.mock.calls.find(
      ([url, init]) => String(url).endsWith('/settings') && (init as RequestInit)?.method === 'PATCH',
    )
    expect(patch).toBeTruthy()
    // Only the changed field is sent, and the untouched checkbox is not.
    expect(JSON.parse(String((patch![1] as RequestInit).body))).toEqual({
      overrides: { auto_approve_threshold: '0.99' },
    })

    // The server echoes it back as the effective value.
    expect(((await screen.findByLabelText('Auto-approve confidence')) as HTMLInputElement).value).toBe('0.99')
  })

  it('shows the server’s validation message and does not lose the edit', async () => {
    stubApi()
    render(<SettingsMenu identity={ADMIN} />)
    await openMenu()

    const input = await screen.findByLabelText('Auto-approve confidence')
    await userEvent.clear(input)
    await userEvent.type(input, '2')
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))

    expect(await screen.findByText(/must be at most 1/)).toBeTruthy()
    // The rejected edit is still in the box for the user to correct.
    expect(((await screen.findByLabelText('Auto-approve confidence')) as HTMLInputElement).value).toBe('2')
  })

  it('lets an admin change the reading model', async () => {
    const fetchMock = stubApi()
    render(<SettingsMenu identity={ADMIN} />)
    await openMenu()

    const input = await screen.findByLabelText('Reading model (this computer)')
    // Its placeholder shows the configured default so the operator sees what is
    // in force before typing.
    expect((input as HTMLInputElement).placeholder).toBe('granite3.2-vision:2b')

    await userEvent.type(input, 'granite3.2-vision:9b')
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))

    const patch = fetchMock.mock.calls.find(
      ([url, init]) => String(url).endsWith('/settings') && (init as RequestInit)?.method === 'PATCH',
    )
    expect(JSON.parse(String((patch![1] as RequestInit).body))).toEqual({
      overrides: { vlm_model_extract: 'granite3.2-vision:9b' },
    })
    expect(
      ((await screen.findByLabelText('Reading model (this computer)')) as HTMLInputElement).value,
    ).toBe('granite3.2-vision:9b')
  })

  it('shows a reviewer the settings read-only with no save button', async () => {
    stubApi({ editable: false })
    render(<SettingsMenu identity={REVIEWER} />)
    await openMenu()

    // The label is present as text, but there is no editable input for it.
    expect(await screen.findByText('Auto-approve confidence')).toBeTruthy()
    expect(screen.queryByLabelText('Auto-approve confidence')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Save changes' })).toBeNull()
  })
})
