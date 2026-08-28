// @vitest-environment node
//
// A filesystem scan plus a TypeScript parse: jsdom buys nothing, and under it
// `import.meta.url` is the http:// URL Vite serves modules from, so
// `fileURLToPath` fails with "The URL must be of scheme file". Resolving off
// `import.meta.url` rather than `process.cwd()` keeps the guard independent of
// where the runner was started; if this docblock ever stops taking effect, the
// call throws loudly instead of quietly scanning nothing.
import { readFileSync, readdirSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'
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
 * ## Why this reads the AST and not the text
 *
 * The first three versions of this guard matched regular expressions against
 * source text with comments and string literals stripped by a hand-written
 * scanner. Three review rounds found five distinct holes and four false
 * positives, all of them the same defect: **regular expressions cannot lex
 * JavaScript.** One apostrophe in JSX prose (`<p>You're signed out</p>`) opened
 * a "string" that ran to end of file; `//` inside a template literal blinded the
 * rest of the line; `(?<![-+])` could tell `a++` from `a - +x` but not from
 * `++i`; and the operator-context set that decided whether a `+` was unary was
 * defeated by TypeScript's postfix `!`.
 *
 * `ts.createSourceFile` is the lexer the compiler itself uses. On the tree:
 *
 * * a unary `+` is a `PrefixUnaryExpression` with a `PlusToken`, and `++i` is
 *   the same node kind with a `PlusPlusToken` -- structurally different, so that
 *   false positive cannot occur. Every preceding-token position the regex had to
 *   enumerate collapses into one check;
 * * `count! + offset` is a `BinaryExpression` whose left operand is a
 *   `NonNullExpression`, not a prefix unary at all;
 * * comments, string literals, template text, regular expressions and JSX text
 *   are not expression nodes, so the whole apostrophe / `//` / two-quotes-on-a-
 *   line / regex-character-class class of hole stops existing -- along with the
 *   scanner, its two scan views and the ratio heuristic that used to (fail to)
 *   protect them.
 *
 * ## Anti-vacuity
 *
 * Modelled on `tests/test_no_float_in_money_path.py`, including the thing that
 * test gets right and most guards get wrong: **it proves it is not passing
 * vacuously.** The checks in the first `describe` establish that the scan reads
 * real files of both extensions, that every one of them parses without a syntax
 * error, that the walk reaches a non-trivial tree, that every rule fires on its
 * plain form and on the shapes three reviews measured, that none of them fires
 * on legitimate integer work, and that the allowlist excuses only the exact file
 * and rule named. Every fixture used anywhere in this file is itself asserted to
 * be valid syntax, because a fixture that does not parse would make a
 * must-not-fire row pass for the wrong reason.
 */

const SRC = fileURLToPath(new URL('../src', import.meta.url))

// --------------------------------------------------------------------------- //
// Rules
// --------------------------------------------------------------------------- //

interface Rule {
  readonly name: string
  readonly why: string
  readonly matches: (node: ts.Node) => boolean
}

/** A call or a `new`. Both node kinds hold the callee on `.expression`.
 *
 * `new` is included because `new Number("1000.00").valueOf()` is a float, and a
 * `NewExpression` is not a `CallExpression` -- so a rule that checked only the
 * latter was silent on it. The task brief originally listed `new Number(1)` as
 * must-not-fire and was revised: a boxed number is rare enough that firing is the
 * right default, and ALLOWLIST is the escape hatch.
 */
function isCallLike(node: ts.Node): node is ts.CallExpression | ts.NewExpression {
  return ts.isCallExpression(node) || ts.isNewExpression(node)
}

/** The name being *called*, for `f(x)`, `o.f(x)` and `new C(x)`.
 *
 * Returning the property name rather than the whole callee expression is what
 * makes one check cover `Number(x)` and `globalThis.Number(x)`, and
 * `parseFloat(x)` and `Number.parseFloat(x)`, while leaving `Number.isInteger(n)`
 * alone -- its called name is `isInteger` -- and `new Intl.NumberFormat(...)`
 * alone, whose called name is `NumberFormat`.
 */
function calledName(node: ts.CallExpression | ts.NewExpression): string | null {
  const callee = node.expression
  if (ts.isIdentifier(callee)) {
    return callee.text
  }
  if (ts.isPropertyAccessExpression(callee)) {
    return callee.name.text
  }
  return null
}

/** The property name being read, for `o.p`, `o['p']`, and destructuring.
 *
 * The `BindingElement` arm is not optional: `const { valueAsNumber } = el` and
 * `({ currentTarget: { valueAsNumber } }) => ...` read the property just as much
 * as `el.valueAsNumber` does, the second is idiomatic React, and a version of
 * this helper without it was silent on all four destructuring shapes.
 *
 * For `{ p: local }` the *property* is `propertyName` and `local` is only the new
 * binding, so `propertyName ?? name` is the name being read.
 */
function accessedName(node: ts.Node): string | null {
  if (ts.isPropertyAccessExpression(node)) {
    return node.name.text
  }
  if (ts.isElementAccessExpression(node) && ts.isStringLiteralLike(node.argumentExpression)) {
    return node.argumentExpression.text
  }
  if (ts.isBindingElement(node)) {
    const source = node.propertyName ?? node.name
    if (ts.isIdentifier(source) || ts.isStringLiteralLike(source)) {
      return source.text
    }
    if (ts.isComputedPropertyName(source) && ts.isStringLiteralLike(source.expression)) {
      return source.expression.text
    }
  }
  return null
}

/** Strip the wrappers that do not change a value, so the literal inside is
 *  reachable: `("number")`, `"number" as const`, `"number" satisfies string`,
 *  `"number"!`. Without this, only a bare literal was matched. */
function unwrapValue(node: ts.Expression): ts.Expression {
  let current = node
  while (
    ts.isParenthesizedExpression(current) ||
    ts.isAsExpression(current) ||
    ts.isSatisfiesExpression(current) ||
    ts.isNonNullExpression(current)
  ) {
    current = current.expression
  }
  return current
}

/** HTML's `type` is an enumerated attribute, matched **ASCII case-insensitively**
 *  by the browser -- so `<input type="NUMBER" />` really is a number input. */
const NUMBER_VALUE = /^number$/i

/** A JSX `type="number"` attribute, in any of its spellings.
 *
 * A `JsxAttribute` is structurally distinct from `const type = 'number'`, from a
 * destructured prop default, and from the object key `{ type: 'number' }`, so no
 * whitespace-based narrowing is needed. `data-type="number"` has the attribute
 * name `data-type` and is likewise not this. `{...props}` is a
 * `JsxSpreadAttribute` and does not hide a real `type` attribute beside it.
 *
 * Consequence of matching the attribute rather than the string: a `type` prop
 * built by `React.createElement("input", { type: "number" })` is **not** caught,
 * because that is an object literal and `{ type: 'number' }` has to stay silent.
 */
function isJsxTypeNumber(node: ts.Node): boolean {
  if (!ts.isJsxAttribute(node) || !ts.isIdentifier(node.name) || node.name.text !== 'type') {
    return false
  }
  const initializer = node.initializer
  if (initializer === undefined) {
    return false
  }
  if (ts.isStringLiteral(initializer)) {
    return NUMBER_VALUE.test(initializer.text)
  }
  if (ts.isJsxExpression(initializer) && initializer.expression !== undefined) {
    const inner = unwrapValue(initializer.expression)
    return ts.isStringLiteralLike(inner) && NUMBER_VALUE.test(inner.text)
  }
  return false
}

const RULES: readonly Rule[] = [
  {
    name: 'Number(',
    why: 'Number("1000.00") is 1000 -- the trailing zeros are gone and it is a float now',
    matches: (node) => isCallLike(node) && calledName(node) === 'Number',
  },
  {
    name: 'parseFloat(',
    why: 'the float path ADR-0001 exists to forbid; the answer is a server round-trip',
    matches: (node) => isCallLike(node) && calledName(node) === 'parseFloat',
  },
  {
    name: 'parseInt(',
    why: 'parseInt("19.99") is 19 -- it truncates money silently',
    matches: (node) => isCallLike(node) && calledName(node) === 'parseInt',
  },
  {
    name: '.toFixed',
    why: 'toFixed rounds a float; the API already sent the exact string to display',
    matches: (node) => accessedName(node) === 'toFixed',
  },
  {
    // No carve-out for a numeric-literal operand (`+1`). Every exception is a
    // hole, three rounds of them have been found in this file already, and a
    // unary `+` on a literal is pointless code -- so it fires, and MEASURED
    // below says so out loud rather than leaving it to be discovered.
    name: 'unary +',
    why: '+money is Number(money) with less punctuation',
    matches: (node) =>
      ts.isPrefixUnaryExpression(node) && node.operator === ts.SyntaxKind.PlusToken,
  },
  {
    // ADR-0015 bans `<input type="number">` on money fields in the same breath
    // as the float path, for the same reason. Banned everywhere rather than "on
    // money fields" because nothing here knows which field an input is bound to.
    // `position` is the one genuinely numeric correctable field
    // (`_LINE_ITEM_FIELDS` in persist/repository.py), so an input for it belongs
    // in ALLOWLIST with that reason written down.
    name: 'input type="number"',
    why: 'the browser reformats the value and rounds it (ADR-0015); use type="text" inputMode="decimal"',
    matches: isJsxTypeNumber,
  },
  {
    // The second door into the same room: `valueAsNumber` is a property of every
    // HTMLInputElement, so `e.currentTarget.valueAsNumber` needs no
    // `type="number"` attribute to compile and banning the attribute alone would
    // leave it reachable. It returns a float or NaN; there is no non-float use.
    //
    // Reached through `accessedName`, so it covers the property read, the
    // `el['valueAsNumber']` index, and all four destructuring shapes -- see
    // MEASURED. Not covered: an alias that loses the name (`const { valueAsNumber:
    // n } = el` IS covered because the property name survives, but
    // `rows.map(Number)` and `const N = Number; N(total)` are not, which is
    // recorded as accepted in the task report).
    //
    // `Intl.NumberFormat` is deliberately NOT banned. Its `format()` accepts a
    // *string* and preserves the exact decimal (measured:
    // `format('12345678901234567890.99')` gives "$12,345,678,901,234,567,890.99"
    // while the number form gives "...567,000.00"), so it is a correct display
    // path, not a float path -- and passing it `Number(m)` instead is caught by
    // the `Number(` rule. It does round to the currency's fraction digits
    // (`format('19.999')` gives "$20.00"), so it is for display only and must
    // never feed a value back into an edit field. `new Intl.NumberFormat(...)` is
    // a `NewExpression` whose called name is `NumberFormat`, so the exemption
    // costs no false positive either.
    name: 'valueAsNumber',
    why: 'valueAsNumber is a float or NaN -- read .value and keep the string (ADR-0015)',
    matches: (node) => accessedName(node) === 'valueAsNumber',
  },
]

// --------------------------------------------------------------------------- //
// Allowlist
// --------------------------------------------------------------------------- //

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
 * matching is pinned in all four directions.
 */
const ALLOWLIST: readonly AllowlistEntry[] = [
  {
    file: 'ui/ConfidenceChip.tsx',
    name: '.toFixed',
    why:
      'SVG path geometry, not money. `wedge()` rounds the gauge glyph\'s arc end ' +
      'point (endX, endY) -- values computed from Math.sin/Math.cos over the ' +
      'geometry constants CX/CY/R, never from a Money string -- to three decimals ' +
      'so the "d" attribute is not a 17-digit float. This is the frontend twin of ' +
      'the Python guard allowlisting LineItem.bbox: pixel geometry that is not ' +
      'money and never becomes money.',
  },
]

// --------------------------------------------------------------------------- //
// Parsing and walking
// --------------------------------------------------------------------------- //

/** `parseDiagnostics` is real but `@internal`, so it is absent from the public
 *  `.d.ts`. Declared optional here on purpose: the anti-vacuity test asserts it
 *  is an array, so if a TypeScript upgrade ever removes it the guard fails
 *  loudly instead of quietly stopping checking whether the parse succeeded. */
interface ParsedSourceFile extends ts.SourceFile {
  readonly parseDiagnostics?: readonly ts.Diagnostic[]
}

function parse(file: string, source: string): ParsedSourceFile {
  // The kind comes from the real extension, which matters: `.ts` and `.tsx` do
  // NOT agree on everything. Under `ScriptKind.TS` a leading `<span>` is a type
  // assertion, so `<span>Total: +VAT included</span>` parses as a cast of a unary
  // `+VAT` and fires; some JSX rows do not parse as `.ts` at all. The shipped
  // guard is unaffected -- JSX only occurs in `.tsx` files and those are parsed
  // as TSX -- and `it('changes nothing except for the JSX fixtures')` pins the
  // exact set of rows that diverge, rather than claiming there are none.
  const kind = file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS
  return ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, kind)
}

function walk(sourceFile: ts.SourceFile, visit: (node: ts.Node) => void): void {
  const step = (node: ts.Node): void => {
    visit(node)
    ts.forEachChild(node, step)
  }
  ts.forEachChild(sourceFile, step)
}

function syntaxErrorsIn(parsed: ParsedSourceFile): string[] {
  return (parsed.parseDiagnostics ?? []).map((diagnostic) =>
    ts.flattenDiagnosticMessageText(diagnostic.messageText, ' '),
  )
}

interface Violation {
  readonly name: string
  readonly line: number
}

function violationsIn(source: string, file = 'fixture.tsx'): Violation[] {
  const sourceFile = parse(file, source)
  const found: Violation[] = []
  walk(sourceFile, (node) => {
    for (const rule of RULES) {
      if (rule.matches(node)) {
        const { line } = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile))
        found.push({ name: rule.name, line: line + 1 })
      }
    }
  })
  return found
}

/** Rule names only -- what the fixture tests assert on. */
function ruleNames(source: string, file = 'fixture.tsx'): string[] {
  return violationsIn(source, file).map((violation) => violation.name)
}

/** The unexcused violations in one file's source. Exported so the allowlist
 *  logic can be tested against synthetic input -- the real tree is clean, so the
 *  guard below can never exercise the excusing branch at all. */
export function offendersFor(
  file: string,
  source: string,
  allowlist: readonly AllowlistEntry[],
): string[] {
  return violationsIn(source, file)
    .filter(
      (violation) =>
        !allowlist.some((entry) => entry.file === file && entry.name === violation.name),
    )
    .map((violation) => {
      const why = RULES.find((rule) => rule.name === violation.name)?.why
      return `${file}:${violation.line}: ${violation.name} -- ${why}`
    })
}

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

const FILES = sourceFiles(SRC)
const shortName = (file: string): string => relative(SRC, file).replace(/\\/g, '/')

// --------------------------------------------------------------------------- //
// Fixtures. Hoisted so `it('every fixture in this file is valid syntax')` can
// check all of them -- a fixture that does not parse would make a must-not-fire
// row pass for the wrong reason, which is the vacuity this describe denies.
// --------------------------------------------------------------------------- //

/** One plain form per rule: the minimum proof that each rule can fire at all. */
const PLAIN: readonly (readonly [string, string])[] = [
  ['Number(', 'const n = Number(receipt.totals.total)'],
  ['parseFloat(', 'const n = parseFloat(receipt.totals.total)'],
  ['parseInt(', 'const n = parseInt(item.qty)'],
  ['.toFixed', 'const shown = total.toFixed(2)'],
  ['unary +', 'const n = +receipt.totals.total'],
  ['input type="number"', '<input type="number" value={total} />'],
  ['valueAsNumber', 'const n = e.currentTarget.valueAsNumber'],
]

/** The shapes three review rounds measured, including every one a regex-based
 *  version of this guard let through. */
const MEASURED: readonly (readonly [string, string])[] = [
  // Aliased and namespaced spellings of the globals.
  ['Number(', 'const n = globalThis.Number(x)'],
  ['parseFloat(', 'const n = Number.parseFloat(x)'],
  ['parseInt(', 'const n = Number.parseInt(x)'],
  ['Number(', 'const s = f.format(Number(total))'],
  ['.toFixed', "const shown = x['toFixed'](2)"],
  ['valueAsNumber', "const n = el['valueAsNumber']"],
  // Inside a template interpolation, which is an expression like any other.
  ['.toFixed', 'const shown = `$${total.toFixed(2)}`'],
  // S6: the "sort by total silently lies" bug money.test.ts warns about.
  ['unary +', 'rows.sort((a, b) => +a.totals.total - +b.totals.total)'],
  // S7: a PATCH body built by coercion.
  ['unary +', 'function f() { return { totals: { total: +receipt.totals.total } } }'],
  // type="number" in every spelling, plus placements a text scan special-cased.
  ['input type="number"', "<input type='number' value={total} />"],
  ['input type="number"', '<input type={"number"} value={total} />'],
  ['input type="number"', "<input type={'number'} value={total} />"],
  ['input type="number"', '<input\n\ttype="number"\n\tvalue={total}\n/>'],
  ['input type="number"', '<input type="number" />'],
  ['input type="number"', '<input {...props} type="number" />'],
  // HTML matches the `type` attribute ASCII case-insensitively, so these really
  // are number inputs in the browser.
  ['input type="number"', '<input type="NUMBER" value={total} />'],
  ['input type="number"', '<input type="Number" value={total} />'],
  // ...and the value can be wrapped in things that do not change it.
  ['input type="number"', '<input type={("number")} value={total} />'],
  ['input type="number"', '<input type={"number" as const} value={total} />'],
  ['input type="number"', '<input type={"number" satisfies string} value={total} />'],
  ['input type="number"', '<input type={`number`} value={total} />'],
  // valueAsNumber needs no type="number" to exist.
  ['valueAsNumber', '<input type="text" onChange={(e) => f(e.currentTarget.valueAsNumber)} />'],
  // ...and it does not have to be reached through a property access at all. The
  // last of these is idiomatic React and is the door ADR-0015 names.
  ['valueAsNumber', 'const { valueAsNumber } = e.currentTarget'],
  ['valueAsNumber', 'const { valueAsNumber: n } = e.currentTarget'],
  ['valueAsNumber', '({ valueAsNumber }: HTMLInputElement) => valueAsNumber'],
  [
    'valueAsNumber',
    '<input onChange={({ currentTarget: { valueAsNumber } }) => f(valueAsNumber)} />',
  ],
  ['valueAsNumber', "const { ['valueAsNumber']: n } = el"],
  // A consequence of the same `BindingElement` arm rather than a separate
  // decision: `.toFixed` is reached through `accessedName` too, so destructuring
  // it now fires where it used to be silent. Pinned here so the behaviour is
  // recorded instead of latent.
  ['.toFixed', 'const { toFixed } = x'],
  // `new Number("1000.00").valueOf()` is a float, and a NewExpression is not a
  // CallExpression -- so this needs the `isCallLike` widening.
  ['Number(', 'const n = new Number(total)'],
  ['Number(', 'const n = new Number("1000.00").valueOf()'],
  // A unary + on a numeric literal fires too. Deliberate: see the rule comment.
  ['unary +', 'const a = [+1, -1]'],
]

/** A unary `+` is the same node wherever it appears. One row per syntactic
 *  position, including the four the regex version deliberately gave up on: after
 *  `>`, after `)`, after `}`, and at statement position with no preceding `;`
 *  (round 2's stated miss was "`+x` opening a file, or after an ASI line break
 *  with no semicolon" -- the last four rows below are exactly that). */
const UNARY_POSITIONS: readonly (readonly [string, string])[] = [
  ['after :', 'const o = { total: +x }'],
  ['after ?', 'const v = c ? +a : 0'],
  ['after =>', 'const f = () => +x'],
  ['after -', 'const d = a - +x'],
  ['after !', 'const v = !+x'],
  ['after &&', 'const v = a && +x'],
  ['after ||', 'const v = a || +x'],
  ['after ??', 'const v = a ?? +x'],
  ['after <', 'const v = a < +x'],
  ['after >', 'const v = a > +x'],
  ['after ; on a new line', 'let a = 1;\n+x'],
  ['after ,', 'f(a, +b)'],
  ['after (', 'f(+a)'],
  ['after [', 'const a = [+x]'],
  ['after { (a block)', 'function f(x: string) { { +x } }'],
  ['after =', 'const v = +x'],
  ['after *', 'const v = a * +x'],
  ['after /', 'const v = a / +x'],
  ['after %', 'const v = a % +x'],
  ['after ~', 'const v = ~+x'],
  ['after ^', 'const v = a ^ +x'],
  ['after &', 'const v = a & +x'],
  ['after |', 'const v = a | +x'],
  ['after ) (an if body)', 'function f(c: boolean, x: string) { if (c) +x }'],
  ['after } (a block, then a statement)', 'function f(x: string) { { } +x }'],
  ['after return', 'function f(x: string) { return +x }'],
  ['after typeof', 'const t = typeof +x'],
  ['after void', 'const v = void +x'],
  ['after delete', 'const v = delete +x'],
  ['after await', 'async function f(x: string) { return await +x }'],
  ['after yield', 'function* g(x: string) { yield +x }'],
  ['after throw', 'function f(x: string): never { throw +x }'],
  ['after case', 'function f(x: number) { switch (x) { case +1: return 1 } return 0 }'],
  ['after in', "const v = 'a' in +x"],
  ['after of', 'function f(x: string) { for (const v of +x) { void v } }'],
  ['inside a JSX expression', '<td>{+total}</td>'],
  // Statement position with nothing before it, and after constructs that end a
  // statement without a `;` -- round 2's stated miss.
  ['as the whole program', '+x'],
  ['opening the file, ASI after it', '+total\nconst a = 1'],
  ['after a function declaration, no ;', 'function f() {}\n+x'],
  ['after an import, no ;', "import './a'\n+x"],
]

/** Every shape that hid a violation from a regex-based version of this guard.
 *  The violation is always on a line *after* the confusing construct. */
const PREVIOUSLY_HIDDEN: readonly (readonly [string, string, readonly string[]])[] = [
  [
    'an apostrophe in JSX prose above the violation',
    'export function B({ total }: { total: string }) {\n' +
      "  return <p>You're signed out. Total was {Number(total).toFixed(2)}</p>\n" +
      '}',
    ['Number(', '.toFixed'],
  ],
  [
    'two same-kind quotes with the violation between them',
    "const a = 'it'\nconst n = Number(q)\nconst b = 'x'",
    ['Number('],
  ],
  [
    'an apostrophe followed by a string containing /*',
    'export function B() {\n' +
      "  return <p>You're at {f('/*')}</p>\n" +
      '}\n' +
      'const n = Number(x)\n' +
      'const m = parseFloat(y)',
    ['Number(', 'parseFloat('],
  ],
  [
    'an apostrophe, a string containing //, then a JSX attribute',
    'export function B() {\n' +
      '  return (\n' +
      "    <p>You're at {f('https://x')}<input type=\"number\" /></p>\n" +
      '  )\n' +
      '}',
    ['input type="number"'],
  ],
  ['// inside a template literal', 'const s = `a // b`\nconst n = Number(x)', ['Number(']],
  ['a regex character class containing //', 'const re = /[//]/\nconst n = Number(x)', ['Number(']],
  [
    'a regex character class containing quotes',
    'const re = /[\'"]/\nconst n = Number(x)',
    ['Number('],
  ],
]

/** Everything three reviews confirmed legitimate. An over-broad guard that
 *  flagged any of these would be worse than no guard -- implementers would learn
 *  to route around it. */
const LEGITIMATE: readonly string[] = [
  // The four false positives the regex version shipped.
  'for (let i = 0; i < items.length; ++i) { void i }',
  'const shown = count! + offset',
  '<span>Total: +VAT included</span>',
  'const s = `Total: +${n} more`',
  // type= shapes that are not JSX attributes. The case-insensitive match applies
  // only to a real `type` attribute, so these stay silent whatever their casing.
  "const type = 'number'",
  "const type = 'NUMBER'",
  "function F({ type = 'number' }) { return type }",
  'const inputType = "number"',
  '<input data-type="number" />',
  '<input data-type="NUMBER" />',
  "const o = { type: 'number' }",
  '<input type="text" inputMode="decimal" value={total} />',
  '<input type="tel" value={total} />',
  // Real integer arithmetic: position, lengths, indices, counters.
  'const next = item.position + 1',
  'const last = items.length - 1',
  'const b = Number.isInteger(n)',
  'const a = [1, 2, 3].map((n) => n + 1)',
  'const s = rows.reduce((acc, r) => acc + 1, 0)',
  'function f(n: number) { let c = 0; for (let i = 0; i < n; i++) { c += 1 } return c }',
  'const page = offset + limit',
  'const row = lineItems[index]',
  'if (task.priority > 2) { void 0 }',
  'const label = `item ${item.position + 1} of ${items.length}`',
  // Binary + reached through every operator context and keyword that appears in
  // UNARY_POSITIONS above. One row per context, so "none of these may fire" is a
  // statement about the same set the unary rows cover, not a subset of it.
  'const v = a ?? b + c',
  'const v = x < y + z',
  'const v = x > y + z',
  'const v = !flag + count',
  'const v = a && b + c',
  'const v = a || b + c',
  'const v = i - j + k',
  'const v = a * b + c',
  'const v = a / b + c',
  'const v = a % b + c',
  'const v = a ^ b + c',
  'const v = a & b + c',
  'const v = a | b + c',
  'const v = ~a + b',
  'const f = () => a + b',
  'const v = (a) + b',
  'const v = arr[a + b]',
  'f(a, b + c)',
  'let q = 1; const v = b + c',
  'const o = { total: a + b }',
  'const v = void a + b',
  'const v = delete o[a + b]',
  "function f(): never { throw new Error('a' + 'b') }",
  "const v = 'a' in { a: b + c }",
  'function f(xs: number[]) { for (const x of xs) { void (x + 1) } }',
  'function f(x: number, a: number, b: number) { switch (x) { case 1: return a + b } return 0 }',
  'lbl: { const v = a + b; void v }',
  'const v = c ? a + b : d + e',
  'const t = typeof x + y',
  'function f() { return a + b }',
  'function* g() { yield a + b }',
  'async function f() { return await a + b }',
  'const v = new Date() + off',
  'const v = items[i] + items[j]',
  'const v = f(a) + g(b)',
  'const v = "a" + b',
  'const v = `a` + b',
  'const v = a?.b + c',
  'const v = (a as number) + b',
  'const v = f<T>(a) + b',
  'const v = a++ + b',
  'const v = a-- + b',
  'const v = --i',
  'const t = a\n  + b',
  'const total = subtotal + tax + tip',
  // Comments, prose and regex literals are not code.
  'const re = /[+-]?\\d/',
  "const msg = 'valueAsNumber is banned'",
  '// a comment about Number( and parseFloat( and +x\nconst a = 1',
  '/* a block comment about total.toFixed(2) */\nconst a = 1',
  // The Intl exemption, and the mapped-type modifier the regex had to carve out.
  "const nf = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })",
  'const s = f.format(total)',
  'type Frozen<T> = { readonly [K in keyof T]: T[K] }',
  'type Frozen2<T> = { +readonly [K in keyof T]: T[K] }',
  'const flags = { readonly: true }',
]

/** Places where a `+` following the named token is necessarily the **binary**
 *  operator, so there is nothing for any guard to catch there. Asserted, not
 *  asserted *about*: each must parse to a `BinaryExpression` and no prefix unary.
 *
 *  These are not "the positions the regex excluded" -- two of those (`>` and `}`)
 *  are in UNARY_POSITIONS above and do fire. What these three share is that the
 *  token before the `+` ends an expression, so the `+` cannot be unary whatever a
 *  scanner believes. */
const BINARY_NOT_UNARY: readonly (readonly [string, string])[] = [
  ['after ] at expression level', 'const v = a[0]\n+x'],
  ['after ) at expression level', 'const v = f()\n+x'],
  ['at line start with no terminator (ASI joins it)', 'const t = a\n  + b'],
]

/** LEGITIMATE rows that do **not** parse under `ScriptKind.TS`, and rows that
 *  parse under both kinds but produce a different hit set.
 *
 *  Both lists are measured by `it('changes nothing except for the JSX
 *  fixtures')`, which fails if either set moves -- so the claim in `parse`'s
 *  comment stays honest instead of being asserted in prose. Every unparseable row
 *  is a JSX element; the differing list is empty, because among the rows that do
 *  parse as both, the kind changes nothing. */
const NOT_PARSEABLE_AS_TS: readonly string[] = [
  '<span>Total: +VAT included</span>',
  '<input data-type="number" />',
  '<input data-type="NUMBER" />',
  '<input type="text" inputMode="decimal" value={total} />',
  '<input type="tel" value={total} />',
]

const KIND_SENSITIVE: readonly string[] = []

const ALL_FIXTURES: readonly string[] = [
  ...PLAIN.map(([, code]) => code),
  ...MEASURED.map(([, code]) => code),
  ...UNARY_POSITIONS.map(([, code]) => code),
  ...PREVIOUSLY_HIDDEN.map(([, code]) => code),
  ...LEGITIMATE,
  ...BINARY_NOT_UNARY.map(([, code]) => code),
]

// --------------------------------------------------------------------------- //
// Anti-vacuity: the scan must be real before its silence means anything
// --------------------------------------------------------------------------- //

describe('the guard is not passing vacuously', () => {
  it('reads the real source tree, both extensions', () => {
    const seen = FILES.map(shortName)
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
    // A glob that quietly stopped matching one extension would leave either the
    // components or the API layer unscanned.
    expect(seen.filter((file) => file.endsWith('.tsx')).length).toBeGreaterThan(0)
    expect(seen.filter((file) => file.endsWith('.ts')).length).toBeGreaterThan(0)
    const bytes = FILES.reduce((sum, file) => sum + readFileSync(file, 'utf8').length, 0)
    expect(bytes).toBeGreaterThan(2000)
  })

  it('parses every source file without a syntax error', () => {
    // The replacement for the ratio heuristic that used to (not) detect a
    // runaway scanner. A file the parser choked on would yield a stunted tree
    // and the guard would find nothing in it.
    //
    // **Positive control first.** "No syntax errors anywhere" is worthless unless
    // the detector can report one, and `parseDiagnostics` is a TypeScript
    // internal that an upgrade could remove. Checking `Array.isArray` on the
    // property is not enough: a `syntaxErrorsIn` that stopped reading it would
    // return `[]` forever while the property itself still existed, and that
    // mutation survived a first version of this test (recorded as A9 in the task
    // report). Running the detector over deliberately broken source is what
    // actually pins it.
    expect(
      syntaxErrorsIn(parse('broken.tsx', 'const a = ')),
      'the syntax-error detector reports nothing even for broken source',
    ).not.toEqual([])
    expect(
      Array.isArray(parse('ok.tsx', 'const a = 1').parseDiagnostics),
      'parseDiagnostics is gone',
    ).toBe(true)

    for (const file of FILES) {
      const parsed = parse(shortName(file), readFileSync(file, 'utf8'))
      expect(syntaxErrorsIn(parsed), `${shortName(file)} did not parse`).toEqual([])
    }
  })

  it('walks a non-trivial tree in every source file', () => {
    // Thresholds taken from measurement, not guessed. Node counts today:
    //   client.ts 464, types.ts 276, LoginPage.tsx 273, session.ts 97,
    //   main.tsx 91, ReviewScreen.tsx 13 (a placeholder Task 3 replaces).
    //   total 1214
    // So no useful *per-file* floor exists -- a legitimately tiny file is 13
    // nodes. The per-file check is therefore structural (every file declares or
    // imports something), and the quantitative floor is on the tree total, which
    // only grows as Tasks 3-4 add code and collapses if the walk breaks.
    let total = 0
    for (const file of FILES) {
      let nodes = 0
      const kinds = new Set<ts.SyntaxKind>()
      walk(parse(shortName(file), readFileSync(file, 'utf8')), (node) => {
        nodes += 1
        kinds.add(node.kind)
      })
      expect(nodes, `${shortName(file)} produced no nodes at all`).toBeGreaterThan(0)
      const structural = [
        ts.SyntaxKind.ImportDeclaration,
        ts.SyntaxKind.FunctionDeclaration,
        ts.SyntaxKind.VariableStatement,
        ts.SyntaxKind.InterfaceDeclaration,
        ts.SyntaxKind.TypeAliasDeclaration,
      ]
      expect(
        structural.some((kind) => kinds.has(kind)),
        `${shortName(file)} produced no top-level declaration`,
      ).toBe(true)
      total += nodes
    }
    expect(total, 'the whole tree walked to almost nothing').toBeGreaterThan(500)
  })

  it('every fixture in this file is valid syntax', () => {
    // A must-not-fire fixture that does not parse passes for the wrong reason.
    for (const code of ALL_FIXTURES) {
      expect(
        syntaxErrorsIn(parse('fixture.tsx', code)),
        `fixture does not parse: ${JSON.stringify(code)}`,
      ).toEqual([])
    }
    expect(ALL_FIXTURES.length).toBeGreaterThan(100)
  })

  it('changes nothing except for the JSX fixtures, whose grammar differs', () => {
    // `parse` takes its `ScriptKind` from the file extension. A round-4 review
    // caught this file claiming the two kinds "behave identically" -- they do not,
    // and this is the assertion that would have caught it. Measured: five JSX rows
    // fail to parse as `.ts`, and of those, `<span>Total: +VAT included</span>`
    // also *fires* there, because under `ScriptKind.TS` a leading `<span>` is a
    // type assertion and `+VAT` inside it is a prefix unary. Among the rows that
    // do parse as both kinds, nothing differs. Both sets are pinned, so neither
    // can grow unnoticed.
    const differing: string[] = []
    const unparseable: string[] = []
    for (const code of LEGITIMATE) {
      if (syntaxErrorsIn(parse('fixture.ts', code)).length > 0) {
        unparseable.push(code)
        continue
      }
      if (
        JSON.stringify(ruleNames(code, 'fixture.ts')) !==
        JSON.stringify(ruleNames(code, 'fixture.tsx'))
      ) {
        differing.push(code)
      }
    }
    expect(unparseable).toEqual([...NOT_PARSEABLE_AS_TS])
    expect(differing).toEqual([...KIND_SENSITIVE])

    // ...and the divergence itself, so the description above is executable.
    expect(ruleNames('<span>Total: +VAT included</span>', 'fixture.tsx')).toEqual([])
    expect(ruleNames('<span>Total: +VAT included</span>', 'fixture.ts')).toContain('unary +')
  })

  it('every rule fires on its plain form', () => {
    // One row per rule, so a rule that stopped matching anything at all cannot
    // hide behind another rule's coverage.
    expect(PLAIN.map(([name]) => name).sort()).toEqual(RULES.map((rule) => rule.name).sort())
    for (const [name, code] of PLAIN) {
      expect(ruleNames(code), `should have caught: ${code}`).toContain(name)
    }
  })

  it('catches the coercion shapes the reviews measured', () => {
    for (const [name, code] of MEASURED) {
      expect(ruleNames(code), `should have caught: ${code}`).toContain(name)
    }
  })

  it('catches a unary + in every syntactic position', () => {
    for (const [label, code] of UNARY_POSITIONS) {
      expect(ruleNames(code), `missed a unary + ${label}: ${code}`).toContain('unary +')
    }
  })

  it('catches a violation that a text-based scan hid', () => {
    for (const [label, code, expected] of PREVIOUSLY_HIDDEN) {
      expect(ruleNames(code), `hidden by ${label}`).toEqual(expect.arrayContaining([...expected]))
    }
  })

  it('fires on none of the legitimate work Tasks 3-4 will write', () => {
    for (const code of LEGITIMATE) {
      expect(violationsIn(code), `false positive on: ${code}`).toEqual([])
    }
  })

  it('records where a unary + cannot occur, so nothing is being missed there', () => {
    // Three places where the token before the `+` ends an expression, so the `+`
    // is necessarily the binary operator and there is nothing to catch. NOT a
    // re-slicing of the positions the regex excluded -- two of those (`>` and a
    // block-closing `}`) are in UNARY_POSITIONS and do fire. Measured rather than
    // argued: each row must yield no prefix unary and exactly one binary +.
    for (const [label, code] of BINARY_NOT_UNARY) {
      let prefixPlus = 0
      let binaryPlus = 0
      walk(parse('fixture.tsx', code), (node) => {
        if (ts.isPrefixUnaryExpression(node) && node.operator === ts.SyntaxKind.PlusToken) {
          prefixPlus += 1
        }
        if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.PlusToken) {
          binaryPlus += 1
        }
      })
      expect(prefixPlus, `${label} unexpectedly parsed as a unary +`).toBe(0)
      expect(binaryPlus, `${label} did not parse as a binary +`).toBe(1)
    }
  })

  it('reports the file, the line, the rule and the reason', () => {
    const [reported] = offendersFor('a.tsx', '\n\nconst n = Number(total)', [])
    expect(reported).toBe(
      'a.tsx:3: Number( -- Number("1000.00") is 1000 -- the trailing zeros are gone and it is a float now',
    )
  })

  it('honours the allowlist, and only for the exact file and pattern', () => {
    // The allowlist is the one mechanism that can silently defang the guard, and
    // the real tree is clean, so `finds none` below never reaches the excusing
    // branch. Forcing `excused = true` once left every test green even with a
    // real violation present in `src`.
    const violation = 'const n = Number(receipt.totals.total)'
    const excuse = (file: string, name: string): AllowlistEntry[] => [
      { file, name, why: 'test fixture' },
    ]

    // Not excused at all: the violation must be reported.
    expect(offendersFor('a.tsx', violation, [])).toHaveLength(1)

    // Excused by an exact match: reported no longer.
    expect(offendersFor('a.tsx', violation, excuse('a.tsx', 'Number('))).toEqual([])

    // ...but only exactly. A different file or a different rule must not excuse
    // it, or one entry would quietly cover the whole tree.
    expect(offendersFor('a.tsx', violation, excuse('b.tsx', 'Number('))).toHaveLength(1)
    expect(offendersFor('a.tsx', violation, excuse('a.tsx', 'parseInt('))).toHaveLength(1)
  })
})

// --------------------------------------------------------------------------- //
// The guard itself
// --------------------------------------------------------------------------- //

describe('no float coercion in frontend/src', () => {
  it('finds none', () => {
    const offenders = FILES.flatMap((file) =>
      offendersFor(shortName(file), readFileSync(file, 'utf8'), ALLOWLIST),
    )
    expect(
      offenders,
      'money must stay a string end to end (ADR-0001). If one of these is ' +
        'genuinely not money -- an index, a position, a page size -- add it to ' +
        'ALLOWLIST with the reason, the way the Python guard allowlists bbox.',
    ).toEqual([])
  })
})
