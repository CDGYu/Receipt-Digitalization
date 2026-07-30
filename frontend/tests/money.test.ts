import { describe, expect, it } from 'vitest'
import type { Money } from '../src/api/types'

/** ADR-0001 in the type system.
 *
 * `Money` is the whole reason this file exists, and nothing else in Task 2
 * consumes it -- Tasks 3 and 4 do. Without these assertions the brand could be
 * silently weakened to a bare `string` and every suite would stay green.
 *
 * **The checker here is `tsc`, not Vitest.** The `@ts-expect-error` directives
 * are the assertions: TypeScript fails the build with "Unused
 * '@ts-expect-error' directive" if the line below one *stops* being an error.
 * So `npm run build` (which runs `tsc -b`, and `tsconfig.test.json` puts this
 * directory in the program) is what enforces them. Proven by mutation:
 * changing `Money` to `string` in src/api/types.ts turns both directives
 * unused and fails the build -- see the task report.
 */
describe('Money', () => {
  it('is a string everywhere a string is wanted', () => {
    // This is what lets a reviewer render "1000.00" with its trailing zeros
    // intact: no formatting, no parsing, no reconstruction.
    const fromApi = '1000.00' as Money
    const asString: string = fromApi
    expect(asString).toBe('1000.00')
    expect(asString.length).toBe(7)
  })

  it('cannot be satisfied by a bare string', () => {
    // The brand is what stops a locally computed value -- anything that did not
    // come off the wire as the API's string -- from being passed off as money.
    // @ts-expect-error a plain string is not a Money; that is the entire point
    const notMoney: Money = '1000.00'
    expect(notMoney).toBe('1000.00')
  })

  it('has no arithmetic defined on it', () => {
    const fromApi = '19.99' as Money
    // The float path ADR-0001 forbids starts exactly here. JavaScript would
    // happily coerce and hand back 39.98 (and 0.1 + 0.2 === 0.30000000000000004
    // for the next reviewer); TypeScript refuses to let the expression compile,
    // which is why the assertion below can only be reached through a directive.
    // @ts-expect-error arithmetic on money is forbidden (ADR-0001)
    const doubled = fromApi * 2
    expect(doubled).toBe(39.98)
  })
})
