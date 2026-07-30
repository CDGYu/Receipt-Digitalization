import { describe, expect, it } from 'vitest'
import type { Money } from '../src/api/types'

/** ADR-0001 in the type system -- and precisely how far it reaches.
 *
 * `Money` is the whole reason this file exists, and nothing else in Task 2
 * consumes it: Tasks 3 and 4 do. Without these assertions the brand could be
 * silently weakened and every suite would stay green.
 *
 * **The checker here is `tsc`, not Vitest.** The `@ts-expect-error` directives
 * are the assertions: TypeScript fails with `TS2578: Unused '@ts-expect-error'
 * directive` if the line below one *stops* being an error. So `npm run
 * typecheck` / `npm run build` is what enforces them -- `tsconfig.test.json`
 * puts this directory in the program.
 *
 * **What each mutation actually catches** (measured; the earlier version of this
 * comment claimed both directives go unused under `Money = string`, which is
 * false):
 *
 * * `Money = string` -- only `cannot be satisfied by a bare string` fails. The
 *   arithmetic directive stays *used*, because `string * 2` is an error with or
 *   without the brand.
 * * `Money = number & {...}` -- `rejects the arithmetic operators` and `is a
 *   string everywhere a string is wanted` fail.
 *
 * So no single mutation catches all three; they are non-vacuous as a set. Being
 * exact about that is the point -- ADR-0015 exists because the first version of
 * this milestone shipped a test described as proving more than it did.
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

  it('rejects the arithmetic operators', () => {
    const fromApi = '19.99' as Money
    // The float path ADR-0001 forbids starts exactly here. JavaScript would
    // coerce and hand back 39.98 (and 0.1 + 0.2 === 0.30000000000000004 for the
    // next reviewer); TypeScript refuses to compile the expression, which is why
    // the assertion below is only reachable through a directive.
    // @ts-expect-error arithmetic on money is forbidden (ADR-0001)
    const doubled = fromApi * 2
    expect(doubled).toBe(39.98)
  })

  it('does NOT stop the coercions that fail silently', () => {
    // Deliberately asserting the *limit* of the brand rather than its power.
    // Everything below compiles clean, which is why
    // `tests/no-float-in-money-path.test.ts` has to scan the source text: the
    // type system cannot see any of it, because the input is a string and a
    // Money is a string.
    const a = '19.99' as Money
    const b = '5.00' as Money

    // `+` on two strings concatenates instead of adding, and nothing complains.
    expect(a + b).toBe('19.995.00')

    // The exact-decimal string becomes a float, and the trailing zeros a
    // reviewer was reading are gone for good.
    expect(Number('1000.00' as Money)).toBe(1000)
    expect(String(Number('1000.00' as Money))).toBe('1000')

    // Comparison is lexicographic, so "9.00" sorts *before* "10.00" -- which is
    // how a "sort by total" column silently lies. Through variables rather than
    // literals so oxlint's no-constant-binary-expression does not (fairly) flag
    // the comparison as constant.
    const nine = '9.00' as Money
    const ten = '10.00' as Money
    expect(nine < ten).toBe(false)
    expect(ten < nine).toBe(true)
  })
})
