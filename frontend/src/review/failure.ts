import { ApiError } from '../api/client'
import type { FieldMap } from './patch'

/** One caught failure, labelled once, so every render site branches on a
 * name instead of re-deriving status semantics.
 *
 * The `field` kind exists for the 400 `ValueError` boundary only. A
 * field-level 422 is unreachable from this client -- the patch goes up as
 * flat dotted keys, which bypass `CorrectionPatch`'s typed sub-models
 * (`extra="allow"`), and every value is already a string; even a smuggled
 * float comes back as the enveloped 400. Pinned server-side by
 * `test_a_dotted_key_with_a_bad_value_is_the_valueerror_400_not_a_422`.
 *
 * 401 is deliberately absent: `client.ts` owns it at the transport
 * (`onUnauthorized`), before any screen logic runs.
 */
export type Failure =
  | { readonly kind: 'backend-down'; readonly message: string }
  | { readonly kind: 'taken'; readonly message: string }
  | { readonly kind: 'gone'; readonly message: string }
  | { readonly kind: 'field'; readonly path: string; readonly message: string }
  | { readonly kind: 'other'; readonly message: string }

/** Every `'…'`-quoted span in a server message.
 *
 * The 400 texts come in two families, both pinned in
 * tests/test_api_write.py: path-quoting ("cannot apply a correction to
 * 'line_items[9].qty': …") and value-quoting ("not a decimal amount:
 * 'abc'", "currency holds at most 3 characters, got 5 ('EUROS')"). A
 * value whose Python repr switches to double quotes (it contains an
 * apostrophe) simply yields no span here and degrades to `other` -- the
 * summary alert, which is exactly what ships today.
 */
function quotedSpans(message: string): string[] {
  return [...message.matchAll(/'([^']*)'/g)].map((match) => match[1])
}

function matchField(message: string, sent: FieldMap): string | null {
  const spans = quotedSpans(message)
  const paths = Object.keys(sent)

  const pathMatches = paths.filter((path) => spans.includes(path))
  if (pathMatches.length === 1) {
    return pathMatches[0]
  }
  if (pathMatches.length > 1) {
    return null
  }

  const valueMatches = paths.filter((path) => {
    const value = sent[path]
    return typeof value === 'string' && spans.includes(value)
  })
  return valueMatches.length === 1 ? valueMatches[0] : null
}

/** Label `caught`. `fallback` is the caller's sentence for a failure that
 * carries no server words (a network `TypeError`); the classifier never
 * invents copy of its own. `sentPatch` -- the exact dirty map just sent --
 * enables the `field` kind; without it a 400 is `other`.
 */
export function classifyFailure(
  caught: unknown,
  options: { readonly sentPatch?: FieldMap; readonly fallback: string },
): Failure {
  if (!(caught instanceof ApiError)) {
    return { kind: 'other', message: options.fallback }
  }
  if (caught.status === 503) {
    return { kind: 'backend-down', message: caught.message }
  }
  if (caught.status === 403) {
    return { kind: 'taken', message: caught.message }
  }
  if (caught.status === 404) {
    return { kind: 'gone', message: caught.message }
  }
  if (caught.status === 400 && options.sentPatch !== undefined) {
    const path = matchField(caught.message, options.sentPatch)
    if (path !== null) {
      return { kind: 'field', path, message: caught.message }
    }
  }
  return { kind: 'other', message: caught.message }
}
