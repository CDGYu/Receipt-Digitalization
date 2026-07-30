/** A failed API call, carrying the HTTP status alongside the message.
 *
 * `status` is declared as a field and assigned in the body rather than written
 * as a constructor parameter property (`constructor(readonly status: number)`).
 * `create-vite`'s `tsconfig.app.json` sets `erasableSyntaxOnly: true`, under
 * which a parameter property is `error TS1294: This syntax is not allowed when
 * 'erasableSyntaxOnly' is enabled` -- so the shorter form compiles under
 * Vitest (esbuild strips it happily) but breaks `npm run build`, which runs
 * `tsc -b` first. The public shape is identical either way.
 */
export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

let unauthorizedHandler: () => void = () => {}

/** Register what happens on a 401 (in the app: redirect to /app/login). */
export function onUnauthorized(handler: () => void): void {
  unauthorizedHandler = handler
}

async function errorMessage(response: Response): Promise<string> {
  // Every API failure uses {"error": {"message": ...}}, but a proxy or a
  // crashed worker can still return HTML -- so a body that will not parse
  // must degrade to a usable message rather than throwing a second error
  // that hides the first.
  try {
    const body = (await response.json()) as { error?: { message?: string } }
    return body?.error?.message ?? `request failed (${response.status})`
  } catch {
    return `request failed (${response.status})`
  }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (response.status === 401) {
    unauthorizedHandler()
    throw new ApiError(401, await errorMessage(response))
  }
  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response))
  }
  return (await response.json()) as T
}
