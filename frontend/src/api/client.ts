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

/** The two error shapes this API can actually produce.
 *
 * `{"error": {"message": ...}}` is what `_install_error_handlers`
 * (src/receipts/review/api.py:128-151) reshapes `ValueError`, `DBAPIError` and
 * `StarletteHTTPException` into -- which covers most of the surface, including a
 * 404 on an unknown path and a 405 on a wrong method.
 *
 * **It is not universal, despite the plan saying so.** Those handlers do not
 * cover FastAPI's `RequestValidationError`, so a 422 arrives in FastAPI's own
 * shape and carries no `error` key at all:
 *
 *     POST /auth/login (no body) -> 422
 *     {"detail":[{"type":"missing","loc":["body"],"msg":"Field required"}]}
 *
 * `PATCH /receipts/{id}` is the route most likely to produce one, so reading
 * only `error.message` would render Task 4's most common failure as
 * `request failed (422)` -- visible, and useless.
 */
interface ApiErrorBody {
  error?: { message?: string }
  detail?: string | { msg?: string }[]
}

function messageFrom(body: ApiErrorBody, status: number): string {
  if (typeof body.error?.message === 'string' && body.error.message !== '') {
    return body.error.message
  }
  if (typeof body.detail === 'string' && body.detail !== '') {
    return body.detail
  }
  if (Array.isArray(body.detail)) {
    // `loc` is deliberately not surfaced: it is the server's own field path
    // (["body","totals","total"]), and Task 4 maps its own paths to its own
    // labels. The messages alone are what a reviewer can act on.
    const messages = body.detail
      .map((item) => item?.msg)
      .filter((msg): msg is string => typeof msg === 'string' && msg !== '')
    if (messages.length > 0) {
      return messages.join('; ')
    }
  }
  return `request failed (${status})`
}

async function errorMessage(response: Response): Promise<string> {
  // A proxy or a crashed worker can still return HTML -- so a body that will
  // not parse must degrade to a usable message rather than throwing a second
  // error that hides the first.
  try {
    return messageFrom((await response.json()) as ApiErrorBody, response.status)
  } catch {
    return `request failed (${response.status})`
  }
}

/** Read a successful response, tolerating the two bodies that are not JSON.
 *
 * The error path has always degraded gracefully; this one used to be a bare
 * `await response.json()`, which throws a **`SyntaxError`, not an `ApiError`**,
 * for two responses that really happen:
 *
 * * `POST /auth/logout` returns 204 with no body at all -- its handler in
 *   `src/receipts/review/auth.py` ends `return Response(status_code=204)`;
 * * a proxy answering 200 with an HTML error page.
 *
 * Every consumer that discriminates on `ApiError` -- `LoginPage`'s catch today,
 * Task 4's submit chain tomorrow -- falls into its generic branch on a
 * `SyntaxError` and loses the status.
 */
async function parseSuccess<T>(response: Response, path: string): Promise<T> {
  let text: string
  try {
    text = await response.text()
  } catch {
    throw new ApiError(response.status, `the response to ${path} could not be read`)
  }
  if (text.trim() === '') {
    // 204/205, or any success with an empty body. There is nothing to parse and
    // nothing for the caller to read; `undefined` is the honest answer.
    return undefined as T
  }
  try {
    return JSON.parse(text) as T
  } catch {
    throw new ApiError(response.status, `expected JSON from ${path} (${response.status})`)
  }
}

/** Merge the caller's headers with the JSON default, preserving all three shapes.
 *
 * `{ 'Content-Type': ..., ...init?.headers }` silently dropped two of the three
 * legal `HeadersInit` forms, both of which type-check clean: a `Headers`
 * instance spreads to nothing (its data is behind methods, not own properties),
 * and a tuple array spreads to `{"0": ["X-Correlation-Id", "abc"]}`. Going
 * through the `Headers` constructor is the only merge that understands all
 * three.
 */
function mergeHeaders(init?: RequestInit): Headers {
  const headers = new Headers(init?.headers)
  // Only when absent, so a caller can send application/merge-patch+json. And
  // never for FormData: only the browser can write the multipart boundary
  // parameter, and a caller cannot un-set a header this function already set --
  // which would make `POST /upload` unparseable.
  if (!headers.has('Content-Type') && !(init?.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }
  return headers
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: 'same-origin',
    headers: mergeHeaders(init),
  })
  if (response.status === 401) {
    unauthorizedHandler()
    throw new ApiError(401, await errorMessage(response))
  }
  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response))
  }
  return parseSuccess<T>(response, path)
}

/** The filename a `Content-Disposition: attachment` header names, or `null`.
 *
 *  Deliberately narrow: it reads the quoted `filename="..."` form the export
 *  route actually sends and returns `null` for anything else, rather than
 *  growing a parser for RFC 6266's full grammar including `filename*`. A
 *  caller that gets `null` supplies its own name; a caller that gets a wrong
 *  name would not know.
 */
function attachmentFilename(response: Response): string | null {
  const header = response.headers.get('Content-Disposition')
  const match = header?.match(/filename="([^"]+)"/)
  return match ? match[1] : null
}

/** `request`, for a body that is not JSON.
 *
 *  Everything up to `response.ok` is identical -- same credentials, same 401
 *  side effect, same `ApiError` carrying the server's own message -- because
 *  **the export route's failures are still JSON even though its successes are
 *  not.** Only the success path differs.
 *
 *  This exists because `request<T>` unconditionally calls `response.text()`
 *  and `JSON.parse`s it, so a workbook reaches the caller as
 *  `expected JSON from /export/xlsx` rather than as bytes.
 */
export async function requestBlob(
  path: string,
  init?: RequestInit,
): Promise<{ blob: Blob; filename: string | null }> {
  const response = await fetch(path, {
    ...init,
    credentials: 'same-origin',
    headers: mergeHeaders(init),
  })
  if (response.status === 401) {
    unauthorizedHandler()
    throw new ApiError(401, await errorMessage(response))
  }
  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response))
  }
  return { blob: await response.blob(), filename: attachmentFilename(response) }
}
