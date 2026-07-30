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
 * a stripper that ate the file, a regex that never fires, an allowlist that
 * excuses everything -- would be green and worthless. The checks in the first
 * `describe` establish that the scan reads real files, that the stripper keeps
 * real code and cannot run past a newline, that every pattern can fire, that
 * none of them fires on legitimate integer work, and that the allowlist excuses
 * only the exact file and pattern named.
 *
 * Every one of those checks exists because something got past an earlier version
 * of this file. See the "Fix round 2" section of the task report.
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

/** Every token after which a `+` **cannot** be the binary operator.
 *
 * A `+` is unary exactly when what precedes it is an operator, an opening
 * delimiter, a separator, or a keyword that starts an expression. So the rule is
 * sound in one direction by construction: `a + b`, `item.position + 1`,
 * `items[i] + items[j]` and `f(a) + g(b)` can never match, because an
 * identifier, a `)` and a `]` are all absent from this set.
 *
 * `(?<![-+])` on the single-character alternative is what keeps `a++ + b` and
 * `a-- + b` out: without it the second `+` of `++` reads as an operator context
 * for the third, and the binary `+` gets flagged. `(?!readonly\b)` excludes the
 * mapped-type modifier `{ +readonly [K in keyof T]: T[K] }`, which is valid
 * TypeScript and not arithmetic at all.
 *
 * **What is deliberately NOT in the set, and why** -- an accurate narrow claim
 * beats a confident broad one:
 *
 * * `>` -- `a > +b` is a genuine unary position, but `>` is also the end of a
 *   JSX opening tag, so `<span>+VAT</span>` (a literal plus in JSX text) would
 *   be flagged. `=>` is included as its own two-character alternative, which is
 *   the case that actually matters. Missing: `a > +b`.
 * * `}` and `)` and `]` -- `} +x` at statement position is unary, but these also
 *   close object literals, calls and index expressions, where `+` is binary
 *   (`f(a) + 1`). Not separable textually. Missing: `+x` as the first statement
 *   after a block.
 * * start-of-line -- `^` with the `m` flag would catch `+x` at statement
 *   position, but it would also flag the continuation line of a multi-line
 *   binary expression (`const t = a\n  + b`), which is a formatting style, not a
 *   bug. `;` is in the set instead, which covers `;\n  +x` soundly. Missing:
 *   `+x` opening a file, or after an ASI line break with no semicolon.
 */
const UNARY_PLUS_CONTEXT = /(?:=>|&&|\|\||\?\?|(?<![-+])[-+*/%!~^&|<=([{,;:?]|\b(?:return|typeof|void|delete|await|yield|throw|case|in|of)\b)/

const UNARY_PLUS = new RegExp(
  `${UNARY_PLUS_CONTEXT.source}\\s*\\+\\s*(?!readonly\\b)[A-Za-z_$(]`,
)

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
    name: 'unary + (numeric coercion)',
    pattern: UNARY_PLUS,
    scan: 'code',
    why: '+money is Number(money) with less punctuation',
  },
  {
    // Beyond the tokens above, and flagged as such in the task report: ADR-0015
    // bans `<input type="number">` on money fields in the same breath, for the
    // same reason. Banned everywhere rather than "on money fields" because text
    // cannot tell which field an input is bound to. `position` is the one
    // genuinely numeric correctable field (`_LINE_ITEM_FIELDS` in
    // persist/repository.py), so an input for it belongs in ALLOWLIST with that
    // reason written down.
    //
    // `type=` with **no whitespace around the `=`** is what makes this a JSX
    // attribute rather than an assignment: `const type = 'number'` and a prop
    // default `function F({ type = 'number' })` both space the `=` and are
    // therefore not flagged. The cost is that the unconventional
    // `<input type = "number">` is missed.
    name: 'input type="number"',
    pattern: /(?:^|[\s{])type=(?:"number"|'number'|\{\s*['"]number['"]\s*\})/,
    scan: 'code+strings',
    why: 'the browser reformats the value and rounds it (ADR-0015); use type="text" inputMode="decimal"',
  },
  {
    // The second door into the same room. ADR-0015 names `valueAsNumber` as the
    // mechanism `type="number"` exposes -- but it is a property of every
    // HTMLInputElement, so `e.currentTarget.valueAsNumber` needs no
    // `type="number"` attribute to compile, and banning only the attribute
    // leaves it open. It returns a float or NaN; there is no non-float use.
    //
    // `Intl.NumberFormat` is deliberately NOT banned. Its `format()` accepts a
    // *string* and preserves the exact decimal (verified by execution:
    // `format('12345678901234567890.99')` gives "$12,345,678,901,234,567,890.99"
    // while the number form gives "...567,000.00"), so it is a correct display
    // path, not a float path -- and passing it `Number(m)` instead is already
    // caught by the `Number(` rule above. It does round to the currency's
    // fraction digits (`format('19.999')` gives "$20.00"), so it is for display
    // only and must never feed a value back into an edit field.
    name: 'valueAsNumber',
    pattern: /\bvalueAsNumber\b/,
    scan: 'code',
    why: 'valueAsNumber is a float or NaN -- read .value and keep the string (ADR-0015)',
  },
]

interface AllowlistEntry {
  readonly file: string
  readonly name: string
  readonly why: string
}

/** Deliberate exceptions, each with the reason written down.
 *
 * Mirrors `_ALLOWED_FLOAT_FIELDS` in the Python guard, whose single entry is
 * `LineItem.bbox` -- pixel geometry, genuinely not money. Empty today. An entry
 * is justified when the value provably is not money and never becomes money:
 * an array index, a `position`, a page size. It is NOT justified for "the
 * number happens to be right in this case".
 *
 * This is the one mechanism that can silently defang the whole guard, which is
 * why `it('honours the allowlist, and only for the exact file and pattern')`
 * exists: an over-broad entry has to be a visible code change here, and the
 * matching itself is pinned in both directions.
 */
const ALLOWLIST: readonly AllowlistEntry[] = []

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

/** The index of the quote that closes the literal opened at `start`, or -1.
 *
 * **Bounded at a newline**, which is the whole point. A JavaScript string
 * literal cannot span a raw line break, so a quote with no partner before the
 * next newline is not opening a string at all -- it is an apostrophe in JSX
 * prose (`<p>You're signed out</p>`) or a quote inside a regex literal
 * (`/['"]/`). A backslash still consumes the following character, so a genuine
 * `\`-continued literal is handled.
 */
function closingQuoteOnSameLine(source: string, start: number): number {
  const quote = source[start]
  for (let i = start + 1; i < source.length; i++) {
    const c = source[i]
    if (c === '\\') {
      i++
      continue
    }
    if (c === '\n') {
      return -1
    }
    if (c === quote) {
      return i
    }
  }
  return -1
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
 * **Residual limitation, stated exactly.** Because a literal is bounded at a
 * newline, a stray quote can now cost at most the remainder of its own line, and
 * only when a *second* quote of the same kind appears on that line: in
 * `<p>Don't worry, it's fine</p>` the run between the two apostrophes is treated
 * as a string and dropped from the `'code'` view, so a banned token written
 * between them on that one line would be missed. The `'code+strings'` view still
 * sees it, so `type="number"` and anything else scanned there is unaffected.
 * There is no ratio heuristic protecting this and there never was -- an earlier
 * version of this docstring claimed `it('strips no more than it should')` caught
 * a runaway scanner, which was measured to be false (a whole-file runaway left
 * the ratio at 0.457, comfortably above the 0.15 threshold). What actually
 * protects the file now is the newline bound itself, pinned by
 * `it('treats a quote with no partner on its line as ordinary text')`.
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
      const end = closingQuoteOnSameLine(source, i)
      if (end === -1) {
        // Not a string literal. Emit it as the ordinary character it is.
        out += c
        i++
        continue
      }
      // When dropping: a placeholder, so the tokens either side of the literal
      // cannot fuse into a new one.
      out += dropStrings ? '""' : source.slice(i, end + 1)
      i = end + 1
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

/** The unexcused violations in one file's source. Exported so the allowlist
 *  logic can be tested against synthetic input -- the real tree is clean, so
 *  the guard below can never exercise the excusing branch at all. */
export function offendersFor(
  file: string,
  source: string,
  allowlist: readonly AllowlistEntry[],
): string[] {
  const offenders: string[] = []
  for (const name of violationsIn(source)) {
    const excused = allowlist.some((entry) => entry.file === file && entry.name === name)
    if (!excused) {
      offenders.push(`${file}: ${name} -- ${BANNED.find((b) => b.name === name)?.why}`)
    }
  }
  return offenders
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

  it('treats a quote with no partner on its line as ordinary text', () => {
    // A string literal cannot span a raw newline, so an unpartnered quote is an
    // apostrophe or part of a regex -- not the start of a literal. Before the
    // newline bound it opened a "string" that ran to end of file.
    expect(strip("<p>You're signed out</p>\nconst n = Number(x)", true)).toContain('Number(x)')
    expect(strip('const re = /[\'"]/\nconst n = Number(x)', true)).toContain('Number(x)')
    expect(strip('const unterminated = "oops\nconst n = Number(x)', true)).toContain('Number(x)')
    // ...while a properly quoted string containing an apostrophe is still a string.
    expect(strip('const msg = "Don\'t"\nconst n = Number(x)', true)).not.toContain('Don')
    expect(strip('const msg = "Don\'t"\nconst n = Number(x)', true)).toContain('Number(x)')
  })

  it('does not let an apostrophe in JSX prose hide a violation below it', () => {
    // The measured defect, end to end through violationsIn rather than through
    // `strip` alone: one apostrophe used to disarm all five 'code' patterns for
    // the remainder of the file.
    const component = [
      'export function Banner({ total }: { total: string }) {',
      "  return <p>You're signed out. Total was {Number(total).toFixed(2)}</p>",
      '}',
    ].join('\n')
    expect(violationsIn(component)).toEqual(
      expect.arrayContaining(['Number(', '.toFixed(']),
    )
  })

  it('strips no more than it should', () => {
    // Catches a stripper that collapses a file wholesale -- the R6f shape, where
    // `strip` returns nothing at all. It does NOT catch a partial runaway; the
    // newline bound in `closingQuoteOnSameLine` is what handles that, and the
    // test above is what pins it. Recording the division of labour because an
    // earlier comment credited this test with both.
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
      ['.toFixed(', 'const shown = `$${total.toFixed(2)}`'],
      ['valueAsNumber', 'const n = e.currentTarget.valueAsNumber'],
      ['input type="number"', '<input type="number" value={total} />'],
      ['input type="number"', '<input type={"number"} value={total} />'],
      ['input type="number"', '<input\n  type="number"\n  value={total}\n/>'],
      // Unary +: every context in UNARY_PLUS_CONTEXT, and the two realistic
      // shapes the re-review measured as silent before this round.
      ['unary + (numeric coercion)', 'const n = +receipt.totals.total'],
      ['unary + (numeric coercion)', 'sum(+a, b)'],
      ['unary + (numeric coercion)', 'return +total'],
      ['unary + (numeric coercion)', '<td>{+total}</td>'],
      ['unary + (numeric coercion)', 'const o = { total: +x }'],
      ['unary + (numeric coercion)', 'const v = cond ? +a : 0'],
      ['unary + (numeric coercion)', 'const f = () => +x'],
      ['unary + (numeric coercion)', 'const d = a - +x'],
      ['unary + (numeric coercion)', 'if (!+x) return'],
      ['unary + (numeric coercion)', 'const v = ok && +x'],
      ['unary + (numeric coercion)', 'const v = cached ?? +x'],
      ['unary + (numeric coercion)', 'if (limit < +x) return'],
      ['unary + (numeric coercion)', 'doThing();\n  +x'],
      ['unary + (numeric coercion)', 'const arr = [+x, y]'],
      ['unary + (numeric coercion)', 'const t = typeof +x'],
      ['unary + (numeric coercion)', 'const p = a * +x'],
      ['unary + (numeric coercion)', 'const q = a / +x'],
      ['unary + (numeric coercion)', 'const r = a % +x'],
      ['unary + (numeric coercion)', 'const s = ~+x'],
      // S6 from the re-review: the "sort by total silently lies" bug that
      // money.test.ts warns about, written the way someone would actually write it.
      [
        'unary + (numeric coercion)',
        'rows.sort((a, b) => +a.totals.total - +b.totals.total)',
      ],
      // S7 from the re-review: a PATCH body built by coercion.
      [
        'unary + (numeric coercion)',
        'return { totals: { total: +receipt.totals.total } }',
      ],
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
      // Binary + reached through the operator contexts, which must stay clean.
      'const total = subtotal + tax + tip',
      'const n = items[i] + items[j]',
      'const n = f(a) + g(b)',
      'const n = a-- + b',
      'const n = a++ + b',
      'const n = (a) + (b)',
      // Mapped-type modifier: valid TypeScript, not arithmetic.
      'type Frozen<T> = { +readonly [K in keyof T]: T[K] }',
      // The type= false positives the re-review measured.
      "const type = 'number'",
      "function F({ type = 'number' }) { return type }",
      'const inputType = "number"',
      // A literal plus in JSX prose, which is why `>` is not a unary context.
      '<span>+VAT included</span>',
    ]
    for (const code of legitimate) {
      expect(violationsIn(code), `false positive on: ${code}`).toEqual([])
    }
  })

  it('honours the allowlist, and only for the exact file and pattern', () => {
    // The allowlist is the one mechanism that can silently defang the guard, and
    // the real tree is clean, so `finds none` below never reaches the excusing
    // branch. Forcing `excused = true` used to leave all seven tests green even
    // with a real violation present in `src`.
    const violation = 'const n = Number(receipt.totals.total)'
    const excuse = (file: string, name: string): AllowlistEntry[] => [
      { file, name, why: 'test fixture' },
    ]

    // Not excused at all: the violation must be reported.
    expect(offendersFor('a.tsx', violation, [])).toHaveLength(1)

    // Excused by an exact match: reported no longer.
    expect(offendersFor('a.tsx', violation, excuse('a.tsx', 'Number('))).toEqual([])

    // ...but only exactly. A different file or a different pattern must not
    // excuse it, or one entry would quietly cover the whole tree.
    expect(offendersFor('a.tsx', violation, excuse('b.tsx', 'Number('))).toHaveLength(1)
    expect(offendersFor('a.tsx', violation, excuse('a.tsx', 'parseInt('))).toHaveLength(1)

    // And the reported string names the file, the pattern, and the reason, so a
    // failure tells the next author what to do about it.
    const [reported] = offendersFor('a.tsx', violation, [])
    expect(reported).toContain('a.tsx')
    expect(reported).toContain('Number(')
    expect(reported).toContain('trailing zeros')
  })
})

// --------------------------------------------------------------------------- //
// The guard itself
// --------------------------------------------------------------------------- //

describe('no float coercion in frontend/src', () => {
  it('finds none', () => {
    const offenders = FILES.flatMap((file) =>
      offendersFor(
        relative(SRC, file).replace(/\\/g, '/'),
        readFileSync(file, 'utf8'),
        ALLOWLIST,
      ),
    )
    expect(
      offenders,
      'money must stay a string end to end (ADR-0001). If one of these is ' +
        'genuinely not money -- an index, a position, a page size -- add it to ' +
        'ALLOWLIST with the reason, the way the Python guard allowlists bbox.',
    ).toEqual([])
  })
})
