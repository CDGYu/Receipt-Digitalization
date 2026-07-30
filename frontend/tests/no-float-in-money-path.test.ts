// @vitest-environment node
//
// A pure filesystem scan: jsdom buys nothing, and under it `import.meta.url` is
// the http:// URL Vite serves modules from, so `fileURLToPath` fails with "The
// URL must be of scheme file". Resolving off `import.meta.url` rather than
// `process.cwd()` keeps the guard independent of where the runner was started;
// if this docblock ever stops taking effect, the call throws loudly instead of
// quietly scanning nothing.
import { readFileSync, readdirSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

/** Global-constraint guard: no float coercion anywhere in `frontend/src`.
 *
 * The browser is the easiest place in the whole system to reintroduce the float
 * ADR-0001 forbids: JavaScript has no decimal type, `"1000.00"` becomes `1000`
 * the instant anything coerces it, and the trailing zeros a reviewer is looking
 * at are gone. The `Money` brand blocks the operators that fail *loudly*
 * (`m * 2`, `m.toFixed()`); it cannot block the ones that fail *silently*
 * (`Number(m)`, `parseFloat(m)`, `+m`) because their input type is `string` and
 * a `Money` is a string. This test is what covers that gap.
 *
 * Modelled on `tests/test_no_float_in_money_path.py`, including the thing that
 * test gets right and most guards get wrong: **it proves it is not passing
 * vacuously.** A textual scan that silently matched nothing -- wrong directory,
 * over-eager comment stripping, a regex that never fires -- would be green and
 * worthless. The checks below establish, in order, that the scan reads real
 * files, that the stripper keeps real code, that every pattern can fire, and
 * that none of them fires on legitimate integer work.
 */

const SRC = fileURLToPath(new URL('../src', import.meta.url))

interface Banned {
  readonly name: string
  readonly pattern: RegExp
  /** Which view of the source the pattern is matched against.
   *
   * `'code'` -- comments and quoted strings both removed. Right for anything
   * that is an identifier or an operator, and necessary because this codebase
   * discusses `parseFloat` and `Number(` in prose constantly.
   *
   * `'code+strings'` -- comments removed, strings kept. Required when the thing
   * being banned *lives inside* a string literal, which `type="number"` does.
   * The trade-off is that a comment is still stripped but a string mentioning
   * the pattern is not; that is the narrower risk of the two.
   */
  readonly scan: 'code' | 'code+strings'
  readonly why: string
}

const BANNED: readonly Banned[] = [
  {
    name: 'Number(',
    pattern: /\bNumber\s*\(/,
    scan: 'code',
    why: 'Number("1000.00") is 1000 -- the trailing zeros are gone and it is a float now',
  },
  {
    name: 'parseFloat(',
    pattern: /\bparseFloat\s*\(/,
    scan: 'code',
    why: 'the float path ADR-0001 exists to forbid; the answer is a server round-trip',
  },
  {
    name: 'parseInt(',
    pattern: /\bparseInt\s*\(/,
    scan: 'code',
    why: 'parseInt("19.99") is 19 -- it truncates money silently',
  },
  {
    name: '.toFixed(',
    pattern: /\.\s*toFixed\s*\(/,
    scan: 'code',
    why: 'toFixed rounds a float; the API already sent the exact string to display',
  },
  {
    // Sound but deliberately incomplete: only positions where a `+` CANNOT be
    // the binary operator. `a + b` is never matched, so legitimate integer
    // arithmetic on `position`/indices/counts is safe. `+x` after `=>`, `:` or
    // `?` is missed -- text cannot see the grammar, and a guard that guessed
    // would fire on `item.position + 1`, which is exactly the false positive
    // that teaches implementers to route around it.
    name: 'unary + (numeric coercion)',
    pattern: /(?:[(,={[]|\breturn\b)\s*\+\s*[A-Za-z_$(]/,
    scan: 'code',
    why: '+money is Number(money) with less punctuation',
  },
  {
    // Beyond the four tokens above, and flagged as such in the task report:
    // ADR-0015 bans `<input type="number">` on money fields in the same breath,
    // for the same reason (`valueAsNumber` and the browser's own reformatting).
    // Banned everywhere rather than "on money fields" because text cannot tell
    // which field an input is bound to. `position` is the one genuinely numeric
    // correctable field (`_LINE_ITEM_FIELDS` in persist/repository.py), so an
    // input for it belongs in ALLOWLIST with that reason written down.
    name: 'input type="number"',
    pattern: /type\s*=\s*(?:"number"|'number'|\{\s*['"]number['"]\s*\})/,
    scan: 'code+strings',
    why: 'valueAsNumber and the browser\'s reformatting are the float path (ADR-0015); use type="text" inputMode="decimal"',
  },
]

/** Deliberate exceptions, each with the reason written down.
 *
 * Mirrors `_ALLOWED_FLOAT_FIELDS` in the Python guard, whose single entry is
 * `LineItem.bbox` -- pixel geometry, genuinely not money. Empty today. An entry
 * is justified when the value provably is not money and never becomes money:
 * an array index, a `position`, a page size. It is NOT justified for "the
 * number happens to be right in this case".
 */
const ALLOWLIST: readonly { file: string; name: string; why: string }[] = []

function sourceFiles(dir: string): string[] {
  const found: string[] = []
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) {
      found.push(...sourceFiles(full))
    } else if (/\.tsx?$/.test(entry.name)) {
      found.push(full)
    }
  }
  return found.sort()
}

/** Remove comments, and optionally quoted strings too.
 *
 * String awareness is **not** optional even when `dropStrings` is false: the
 * scanner still has to walk into a literal to know that the `//` inside
 * `'http://localhost:8000'` does not start a comment.
 *
 * **Template literals are deliberately left in.** `` `$${total.toFixed(2)}` ``
 * is precisely how someone formats money for display, so the interpolation has
 * to stay visible to the scan. The cost is that a banned token written as
 * literal text inside a backtick string would be flagged; that is what
 * ALLOWLIST is for, and it has never happened.
 *
 * Known limitation: a regex literal containing a quote character (`/['"]/`)
 * would be mis-read as the start of a string. There are none in `src` today,
 * and `it('strips no more than it should')` below fails loudly if the scanner
 * ever runs away and swallows a file.
 */
export function strip(source: string, dropStrings: boolean): string {
  let out = ''
  let i = 0
  while (i < source.length) {
    const c = source[i]
    const next = source[i + 1]
    if (c === '/' && next === '/') {
      while (i < source.length && source[i] !== '\n') i++
      continue
    }
    if (c === '/' && next === '*') {
      i += 2
      while (i < source.length && !(source[i] === '*' && source[i + 1] === '/')) i++
      i = Math.min(i + 2, source.length)
      continue
    }
    if (c === '"' || c === "'") {
      const quote = c
      const start = i
      i++
      while (i < source.length && source[i] !== quote) {
        if (source[i] === '\\') i++
        i++
      }
      i++
      // When dropping: a placeholder, so the tokens either side of the literal
      // cannot fuse into a new one.
      out += dropStrings ? '""' : source.slice(start, Math.min(i, source.length))
      continue
    }
    out += c
    i++
  }
  return out
}

function violationsIn(code: string): string[] {
  // Two views, because one is not enough. `Number(` must be matched with
  // strings removed (this codebase discusses it in prose), while `type="number"`
  // lives *inside* a string literal and vanishes under the same treatment --
  // which `it('every banned pattern actually fires')` caught when this function
  // used a single view.
  const views = {
    code: strip(code, true),
    'code+strings': strip(code, false),
  } as const
  return BANNED.filter((banned) => banned.pattern.test(views[banned.scan])).map(
    (banned) => banned.name,
  )
}

const FILES = sourceFiles(SRC)

// --------------------------------------------------------------------------- //
// Anti-vacuity: the scan must be real before its silence means anything
// --------------------------------------------------------------------------- //

describe('the guard is not passing vacuously', () => {
  it('reads the real source tree', () => {
    const seen = FILES.map((f) => relative(SRC, f).replace(/\\/g, '/'))
    // If the recursion or the directory URL were wrong, the guard would find
    // nothing and report success. Name the files it must have reached.
    expect(seen).toEqual(
      expect.arrayContaining([
        'api/client.ts',
        'api/types.ts',
        'login/LoginPage.tsx',
        'main.tsx',
        'review/ReviewScreen.tsx',
        'session.ts',
      ]),
    )
    const bytes = FILES.reduce((sum, f) => sum + readFileSync(f, 'utf8').length, 0)
    expect(bytes).toBeGreaterThan(2000)
  })

  it('strips comments in both modes, and strings only when asked', () => {
    const source = [
      '// the answer is a server round-trip, not a parseFloat(x)',
      '/* Number(y) in a block comment */',
      "const label = 'call parseInt(z) here'",
      'const real = Number(w)',
      '<input type="number" />',
    ].join('\n')

    const code = strip(source, true)
    expect(code).not.toContain('parseFloat(') // line comment gone
    expect(code).not.toContain('parseInt(') // string contents gone
    expect(code).not.toContain('"number"') // ...which is why type= needs mode 2
    expect(code).toContain('Number(w)') // real code survives

    const withStrings = strip(source, false)
    expect(withStrings).not.toContain('parseFloat(') // comments still gone
    expect(withStrings).not.toContain('Number(y)') // block comment still gone
    expect(withStrings).toContain('parseInt(z)') // strings kept
    expect(withStrings).toContain('type="number"') // the whole point
  })

  it('does not mistake // inside a string for a comment', () => {
    // Without this, `'http://localhost:8000'` would swallow the rest of the line
    // and quietly hide anything after it.
    const kept = strip("const target = 'http://localhost:8000'\nconst n = Number(x)", false)
    expect(kept).toContain('Number(x)')
    expect(strip("const t = 'http://x'\nconst n = Number(x)", true)).toContain('Number(x)')
  })

  it('strips no more than it should', () => {
    // A runaway scanner (an unterminated quote, a mis-read regex literal) would
    // swallow the rest of a file and make every pattern silently un-matchable.
    for (const file of FILES) {
      const source = readFileSync(file, 'utf8')
      const stripped = strip(source, true)
      expect(stripped, `${relative(SRC, file)} was stripped to nothing`).toMatch(
        /\b(import|export)\b/,
      )
      expect(
        stripped.length / source.length,
        `${relative(SRC, file)} lost too much to stripping`,
      ).toBeGreaterThan(0.15)
    }
  })

  it('every banned pattern actually fires', () => {
    const offenders = [
      ['Number(', 'const n = Number(receipt.totals.total)'],
      ['parseFloat(', 'const n = parseFloat(receipt.totals.total)'],
      ['parseInt(', 'const n = parseInt(item.qty)'],
      ['.toFixed(', 'const shown = total.toFixed(2)'],
      ['unary + (numeric coercion)', 'const n = +receipt.totals.total'],
      ['unary + (numeric coercion)', 'sum(+a, b)'],
      ['unary + (numeric coercion)', 'return +total'],
      ['unary + (numeric coercion)', '<td>{+total}</td>'],
      ['.toFixed(', 'const shown = `$${total.toFixed(2)}`'],
      ['input type="number"', '<input type="number" value={total} />'],
      ['input type="number"', '<input type={"number"} value={total} />'],
    ] as const
    for (const [name, code] of offenders) {
      expect(violationsIn(code), `should have caught: ${code}`).toContain(name)
    }
  })

  it('fires on none of the legitimate integer work Tasks 3-4 will write', () => {
    // `line_items[].position` is a real number and so are lengths and indices.
    // An over-broad guard that flagged these would be worse than no guard --
    // implementers would learn to route around it.
    const legitimate = [
      'const next = item.position + 1',
      'const last = items.length - 1',
      'for (let i = 0; i < items.length; i++) { total += 1 }',
      'const row = lineItems[index]',
      'if (task.priority > 2) return null',
      'const shown = Number.isInteger(item.position)',
      'const page = offset + limit',
      'const label = `item ${item.position + 1} of ${items.length}`',
      '<input type="text" inputMode="decimal" value={total} />',
      'const swapped = a === b ? a : b',
      'let count = 0; count += 1',
      'const flags = { readonly: true }',
    ]
    for (const code of legitimate) {
      expect(violationsIn(code), `false positive on: ${code}`).toEqual([])
    }
  })
})

// --------------------------------------------------------------------------- //
// The guard itself
// --------------------------------------------------------------------------- //

describe('no float coercion in frontend/src', () => {
  it('finds none', () => {
    const offenders: string[] = []
    for (const file of FILES) {
      const rel = relative(SRC, file).replace(/\\/g, '/')
      for (const name of violationsIn(readFileSync(file, 'utf8'))) {
        const excused = ALLOWLIST.some((a) => a.file === rel && a.name === name)
        if (!excused) {
          const why = BANNED.find((b) => b.name === name)?.why
          offenders.push(`${rel}: ${name} -- ${why}`)
        }
      }
    }
    expect(
      offenders,
      'money must stay a string end to end (ADR-0001). If one of these is ' +
        'genuinely not money -- an index, a position, a page size -- add it to ' +
        'ALLOWLIST with the reason, the way the Python guard allowlists bbox.',
    ).toEqual([])
  })
})
