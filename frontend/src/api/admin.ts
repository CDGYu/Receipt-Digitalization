import { request } from './client'
import type { ReviewTask } from './types'

/** Who the caller is, as `GET /auth/me` and `POST /auth/login` both return it.
 *
 * The two routes return the *same* body deliberately -- `/auth/me` is the
 * reload path for a shape login already produced, and
 * `test_auth_me_returns_the_same_body_as_login` is what holds them together
 * (ADR-0026 decision 1). So this is one type, not two.
 *
 * `role` is a `string` rather than a `'reviewer' | 'admin'` union on purpose:
 * `request<T>` is an unchecked cast, so a union here would be a claim about the
 * server that nothing validates, and an unrecognised role would type-check as
 * impossible while arriving anyway. Callers compare against `'admin'` and treat
 * everything else as the narrow branch -- the same failure direction
 * `list_review_tasks` takes, which shows a caller too little rather than too
 * much.
 */
export interface Identity {
  username: string
  role: string
}

/** The wire spellings of `ReviewState` (src/receipts/persist/models.py).
 *
 * **Lower case.** ADR-0026's prose says `state == OPEN`, and the enum's
 * *members* are upper case, but its values are not: sending `"OPEN"` gets a 422
 * from FastAPI's enum validation, not an empty list. The union is what stops
 * that at compile time; `tests/admin-screen.test.tsx` pins the emitted query
 * string as well, because a `string` parameter would compile either way.
 */
export type TaskState = 'open' | 'in_progress' | 'done'

/** One page of `_task_summary` rows, mirroring `ReviewTaskListResponse`.
 *
 * `has_more` comes off a `limit + 1` fetch rather than a `COUNT(*)`, so it says
 * "there is at least one more row" and never how many.
 */
export interface TaskPage {
  items: ReviewTask[]
  has_more: boolean
}

/** What `POST /review/{task_id}/release` answers with.
 *
 * **The whole task summary plus `released_from`**, measured at `review_release`
 * in src/receipts/review/api.py: the body is
 * `{**_task_summary(task), "released_from": released_from}`. The plan typed it
 * as `{ released_from: string | null }` alone, which -- because `request<T>` is
 * an unchecked cast -- would have silently discarded the updated row and forced
 * a second listing call to learn what the release actually did.
 *
 * `released_from` is `null` on the idempotent path (the task was already open
 * and nothing was written), which is how a caller tells a real release from a
 * no-op. `assigned_to` is `null` either way: it says who holds the task now,
 * and `released_from` says who held it.
 */
export interface ReleasedTask extends ReviewTask {
  released_from: string | null
}

/** `GET /metrics`, as `MetricsResponse` declares it.
 *
 * **`auto_approval_rate` is `string | null` and the null is load-bearing**: the
 * route returns `None` when `auto_approved + needs_review + reviewed == 0` --
 * an undefined rate, not a `0` or a `1.0` masquerading as one. It is a string
 * for the reason every decimal in this API is one (ADR-0001).
 */
export interface Metrics {
  counts_by_status: Record<string, number>
  auto_approval_rate: string | null
  queue: {
    open: number
    in_progress: number
    done: number
    total: number
    /** Open tasks only, keyed by priority. JSON object keys are strings even
     *  though the server's dict is keyed by `int`. */
    by_priority: Record<string, number>
  }
  thresholds: {
    auto_approve: string
    review: string
  }
}

/** Who the caller is. **Answers 401 when signed out, and `request` throws.**
 *
 * ADR-0026 decision 1 chose 401 over `200 {"user": null}` deliberately: the
 * route stays inside `require_user`, joins the auth matrix as a one-line row,
 * and -- the part that matters here -- `client.ts` fires the global
 * unauthorized handler *before* it throws, so `session.ts` flips to signed out
 * with no new client logic. The side effect is the point; the throw still has
 * to be caught. `session.ts`'s `hydrateIdentity` is where that happens.
 */
export function fetchMe(): Promise<Identity> {
  return request('/auth/me')
}

/** The role values the backend's `ROLES` accepts, for the registration dropdown.
 *
 * Hardcoded rather than fetched: the backend has no route that lists them and
 * `Identity.role` is a bare `string` on purpose (see above), so there is no
 * shared enum to import. These two literals mirror `ROLE_REVIEWER`/`ROLE_ADMIN`
 * in `src/receipts/persist/users.py`; the server validates the value regardless,
 * so a drift here is a 400 the form surfaces, not a silent bad account.
 */
export const ROLES = ['reviewer', 'admin'] as const

/** Create an account and sign it in. **Returns the same body as login.**
 *
 * `POST /auth/register` validates the role, creates the user, and sets the
 * session in one call, so a caller that awaits this is already signed in -- the
 * frontend treats a resolved promise exactly like a resolved login. A duplicate
 * username, an empty field, or an unrecognised role is a 400 carrying the
 * server's own message, which `request` turns into an `ApiError` the form shows.
 */
export function register(body: {
  username: string
  password: string
  role: string
}): Promise<Identity> {
  return request('/auth/register', { method: 'POST', body: JSON.stringify(body) })
}

/** One page of the review queue. **Both roles get 200 with different rows.**
 *
 * `GET /review/tasks` is guarded by `require_user`, not `require_role`: an
 * admin sees every row, a reviewer sees `state == OPEN` or
 * `assigned_to == <caller>` (ADR-0026 decision 2). That difference is invisible
 * from here -- the two responses have the same shape -- which is exactly why
 * the empty state has to name the scope it is empty *for*.
 *
 * The query string is omitted entirely when nothing is passed, rather than sent
 * as `?`, so the server's own defaults (limit 50, offset 0, no state filter)
 * apply and this function does not restate them.
 */
export function fetchTasks(params?: {
  state?: TaskState
  limit?: number
  offset?: number
}): Promise<TaskPage> {
  const query = new URLSearchParams()
  if (params?.state !== undefined) {
    query.set('state', params.state)
  }
  if (params?.limit !== undefined) {
    query.set('limit', String(params.limit))
  }
  if (params?.offset !== undefined) {
    query.set('offset', String(params.offset))
  }
  const search = query.toString()
  return request(search === '' ? '/review/tasks' : `/review/tasks?${search}`)
}

/** Return a claimed task to the open queue. **`taskId` is a review task id.**
 *
 * Admin only, declaratively: the route takes
 * `Depends(require_role(ROLE_ADMIN))`, so a reviewer gets **403** rather than a
 * quietly empty result -- and the role is re-read per request (ADR-0012), so an
 * account demoted after `/auth/me` answered gets the same 403. Callers must
 * handle it; an admin gate in the UI is a courtesy, not the gate.
 *
 * A closed task is refused with 400, because clearing `assigned_to` on a `DONE`
 * row destroys the only record in the system that a human ever looked at that
 * receipt (ADR-0025 decision 2). An unknown id is a 404 from the route itself.
 *
 * `id` is encoded even though every id this app holds came from the API as a
 * UUID: the parameter's type is `string`, and the route parses it as
 * `uuid.UUID`, so anything that is not one must be a 422 rather than a path
 * this function helped build.
 */
export function releaseTask(taskId: string): Promise<ReleasedTask> {
  return request(`/review/${encodeURIComponent(taskId)}/release`, { method: 'POST' })
}

/** Queue depth, status counts and this deployment's thresholds.
 *
 * Not in the plan's `Produces` block, and added because design section 5.7's
 * StatTiles are fed by this route and by nothing else. Guarded by
 * `require_user`, so both roles may read it.
 */
export function fetchMetrics(): Promise<Metrics> {
  return request('/metrics')
}

/** How receipts are processed: pure-local, pure-cloud, or the hybrid ladder.
 *
 * The literal union is a convenience for callers, but the fields are typed
 * `string`/`string[]` because -- exactly like `Identity.role` -- `request<T>` is
 * an unchecked cast and the server owns the vocabulary. A future mode arrives as
 * a plain string the UI can still render rather than a value that type-checks as
 * impossible.
 *
 * `modes` is every mode the UI may list, in offer order. `available` is the
 * subset that is genuinely distinct for this deployment: with no cloud model
 * configured all three build the same local rung, so the UI shows the rest
 * disabled rather than as live choices that silently do nothing.
 */
export type ProcessingMode = 'local' | 'cloud' | 'hybrid'

export interface ProcessingModeState {
  mode: string
  modes: string[]
  available: string[]
}

/** Read the current processing mode. **Readable by any signed-in user.**
 *
 * `GET /processing-mode` is guarded by `require_user`, not `require_role`: a
 * reviewer may see how receipts are being processed even though only an admin
 * may change it -- the same read/write split `PATCH /receipts` and
 * `POST /release` take.
 */
export function fetchProcessingMode(): Promise<ProcessingModeState> {
  return request('/processing-mode')
}

/** Set the processing mode. **Admin only; a reviewer gets 403.**
 *
 * `PATCH /processing-mode` takes `Depends(require_role(ROLE_ADMIN))`, so a
 * reviewer's write is refused with 403 -- the UI hides the control for a
 * reviewer as a courtesy, not as the gate. An unknown mode is a 400 carrying
 * the server's own message, which `request` turns into an `ApiError`. Returns
 * the same shape as `fetchProcessingMode`, so a successful write refreshes the
 * whole state in one round trip.
 */
export function setProcessingMode(mode: string): Promise<ProcessingModeState> {
  return request('/processing-mode', { method: 'PATCH', body: JSON.stringify({ mode }) })
}

/** One operator-editable system setting, as `GET /settings` returns it.
 *
 * `kind` picks the control the UI renders (`bool` a checkbox, the rest a text
 * box). `value` and `default` are `string | boolean | null`: a decimal crosses
 * the wire as a string (ADR-0001), a checkbox as a real boolean, and a blank
 * text field as `null`. `source` is `'override'` when an operator has set it and
 * `'default'` otherwise -- which is what shows a "reset" affordance. `min`/`max`
 * are advisory hints for a number field.
 */
export interface EditableSetting {
  field: string
  label: string
  help: string
  kind: 'decimal' | 'int' | 'bool' | 'text' | 'model'
  group: string
  minimum: string | null
  maximum: string | null
  value: string | boolean | null
  default: string | boolean | null
  source: 'override' | 'default'
}

export interface SettingsState {
  settings: EditableSetting[]
  /** Whether the signed-in user (an admin) may change these. Reviewers get the
   *  same rows with `editable` false so the UI renders them read-only. */
  editable: boolean
}

/** Read the operator-editable system settings. **Any signed-in user.**
 *
 * `GET /settings` is `require_user`, like `/processing-mode` and `/metrics`: a
 * reviewer sees how the system is configured, an admin may change it (the
 * `editable` flag says which). Each row's `value` is what is in force now -- the
 * override if one is stored, else the value the process booted with.
 */
export function fetchSettings(): Promise<SettingsState> {
  return request('/settings')
}

/** Change one or more system settings. **Admin only; a reviewer gets 403.**
 *
 * `PATCH /settings` takes a map of field name to new value. A blank string or
 * `null` clears a setting back to its default. The server validates every value
 * against its real type and bounds and applies the whole patch atomically -- the
 * first bad value is a 400 (with an operator-facing message) and nothing is
 * written. Returns the full refreshed settings so the caller updates in one
 * round trip.
 */
export function saveSettings(
  overrides: Record<string, string | boolean | null>,
): Promise<SettingsState> {
  return request('/settings', { method: 'PATCH', body: JSON.stringify({ overrides }) })
}
