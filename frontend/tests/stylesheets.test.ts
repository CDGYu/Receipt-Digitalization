// @vitest-environment node
//
// A filesystem read of every stylesheet the app ships, as text. Nothing here
// renders anything, so jsdom buys nothing; `tokens.test.ts` carries the same
// directive for the same reason.
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

/** The declaration guard for the whole stylesheet tree -- the pin the browser
 *  pass (plan Task 5, ADR-0027) bought and nothing was holding.
 *
 * ## Why this file exists
 *
 * The whole-branch review measured it and the controller reproduced it: **every
 * one of Task 5's four fixes reverted with all five gates green.** Across the
 * sixteen stylesheets `src/` held **at that time** (22 today), exactly three
 * rules had any declaration
 * asserted anywhere -- `tokens.css`'s token block, `ui/Value.module.css`'s
 * `.notExtracted`, and `LineItemsTable.module.css`'s `.scroller`. Every other
 * declaration in the tree was deletable in silence. The class-*name* guard in
 * `value.test.tsx` covers only the files its `COMPONENTS` list names, and cannot
 * see this at all: it compares the two sides' class names, so emptying every
 * rule body to `{}` while keeping the names leaves it perfectly green, and that
 * mutation was run.
 *
 * ## The property, stated once and bounded
 *
 * **Every declaration in every stylesheet this app ships is named below, in
 * source order, and every keyword-valued one is named together with its
 * keyword.**
 *
 * That is the whole claim. It is one property over the whole tree, not a list of
 * rules somebody thought were important -- `CENSUS` is compared against what the
 * files actually contain, so a declaration added, removed, renamed or reordered
 * is a failure naming its file and its rule.
 *
 * ### Why keywords by value and quantities by presence
 *
 * A declaration's value is one of two things. A **keyword** is a single
 * identifier drawn from a closed set the CSS spec defines, and it selects a
 * *behaviour*: `display: flex` is a different box model from `display:
 * inline-flex`, `table-layout: fixed` is a different layout algorithm from
 * `auto`, and a reader can judge the swap from the text alone. A **quantity** --
 * a length, a colour, a token reference, a shorthand -- selects an *appearance*,
 * and whether `24rem` or `var(--color-null)` is the right one is a question
 * about a rendered page that no reader of the source can answer. So the census
 * pins keywords by value and quantities by presence, and the quantities are
 * judged where they mean something: in the browser, on numbers a real engine
 * computed.
 *
 * Both halves were needed. The dark-theme `--color-null` lift is a quantity and
 * is caught by the contrast property below rather than by the census; the
 * `MoneyInput` `.field` block-level fix is a keyword and is caught by the
 * census; emptying `LoginPage.module.css` is a deletion and is caught by the
 * census.
 *
 * ### Order is part of the census, and that is not incidental
 *
 * `admin/AdminScreen.module.css`'s `.alert` declares `border` and then
 * `border-left-width`. Swapping those two silently drops the thicker left edge,
 * because a shorthand resets every longhand it covers. Source order is therefore
 * load-bearing wherever a shorthand and its longhand share a rule, and the
 * census records it rather than sorting it away.
 *
 * ### What this does NOT cover, stated rather than implied
 *
 *   * **Quantities.** A colour, length or token reference can change to any
 *     other value of the same kind and this file stays green. That is the
 *     deliberate half above, and `e2e/visual.spec.ts` is the other half: it now
 *     asserts that no control overflows its table cell and that no sampled text
 *     falls below the WCAG AA floor, on the measurements it was already taking.
 *   * **And that other half is not a gate.** `scripts/verify.py` runs five gates
 *     and says in as many words that the Playwright run is not one of them, so
 *     `npx playwright test visual` is a step somebody has to choose to run. The
 *     census and the contrast property here are gated; the layout half is not.
 *     A `display` keyword is pinned by this file, but *what it does to a table
 *     cell* is pinned only by a run nothing forces.
 *   * **Cascade.** This is a per-rule census. Two rules that fight over an
 *     element, a specificity change, an `!important` -- none of that is visible
 *     to a text reader, and none of it is claimed.
 *   * **Whether a rule is reached at all.** `value.test.tsx` owns that for the
 *     components it guards. `LineItemsTable.module.css`'s `.rowActive` is
 *     declared and referenced by nothing today (its own comment records why),
 *     and the census is content with that: it audits declarations, not reach.
 */

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..', 'src')

/** Every stylesheet under `src/`, path-relative to it, with `/` separators.
 *
 *  Enumerated rather than listed, so a stylesheet added to the tree without an
 *  entry in `CENSUS` fails here instead of arriving unguarded -- which is
 *  exactly how `login/LoginPage.module.css` shipped: it was created during the
 *  browser pass and no guard in the repository knew it existed. */
function stylesheets(directory: string = SRC, prefix = ''): string[] {
  const found: string[] = []
  for (const entry of readdirSync(directory).sort()) {
    const full = join(directory, entry)
    const relative = prefix === '' ? entry : `${prefix}/${entry}`
    if (statSync(full).isDirectory()) {
      found.push(...stylesheets(full, relative))
    } else if (entry.endsWith('.css')) {
      found.push(relative)
    }
  }
  return found.sort()
}

const read = (relative: string): string => readFileSync(join(SRC, relative), 'utf8')

interface Rule {
  /** The rule's selector, qualified by any at-rule it sits inside. */
  readonly selector: string
  /** `(property, value)` in source order. */
  readonly declarations: readonly (readonly [string, string])[]
}

/** Every rule in a stylesheet, innermost blocks only.
 *
 *  A single left-to-right walk. On `{` the accumulated prelude is the selector;
 *  the block is scanned to its matching `}`, and a block that contains another
 *  `{` is an at-rule whose prelude is pushed onto the context stack and prefixed
 *  onto the rules inside it -- so the `prefers-color-scheme` copy of the dark
 *  tokens is a different census key from the `data-theme` one, which is the
 *  whole point of `tokens.css` carrying both.
 *
 *  **Comments are stripped first, and that is not optional.** `tokens.test.ts`
 *  records the round where `indexOf` matched the comment above a rule and left
 *  the rule's deletion green, and this tree is commented far more heavily than
 *  it is coded -- `MoneyInput.module.css`'s docblock contains the literal text
 *  `::before { content: '$' }`, braces and all, which this parser would read as
 *  a rule.
 *
 *  **A `;` outside a block resets the prelude**, so a statement at-rule
 *  (`@import`, `@charset`) is discarded rather than glued onto the front of the
 *  next selector. None exists today; `tokens.test.ts` pins that no `@import`
 *  reaches the network, not that none exists.
 *
 *  What this is **not** is a CSS parser. It assumes a value carries no braces
 *  and no semicolons, which holds for every file in the tree -- the only
 *  `content` values are `'+'` and `'\2212'`, both in `FindingsPanel`, and
 *  `MoneyInput`'s `content: '$'` is inside a comment -- and is not claimed
 *  beyond them. **No count is stated here on purpose:** this said "these
 *  sixteen files" while the tree held 22, and a count in prose rots on the next
 *  stylesheet somebody adds. The claim is about every file, checked by
 *  re-reading the `content` declarations, not about a number.
 *
 *  **A value that breaks the assumption is SILENT, not loud.** Corrected
 *  2026-08-07; this said such a value "would split a declaration in two and show
 *  up as a census mismatch, which is loud rather than silent." Falsified by
 *  mutation at the milestone's close: changing `.summary::after`'s
 *  `content: '+'` to `content: '+;XX'` splits on the embedded `;` into
 *  `content: '+` -- whose census key is still the quantity `content` -- and a
 *  fragment with no colon, which is dropped. The census entry comes out
 *  byte-identical, **346/346 stayed green, typecheck and build passed, and the
 *  changed glyph shipped to `dist`.** So the bound above is a real blind spot,
 *  not a graceful degradation. ADR-0029 section 4 does not list it: it is
 *  neither layout, nor cascade, nor one of the three narrower surfaces. Treat a
 *  semicolon or brace inside a value as **unpinned**, and if one is ever
 *  introduced, this parser must be replaced rather than trusted to complain. */
function rulesIn(css: string): Rule[] {
  const code = css.replace(/\/\*[\s\S]*?\*\//g, '')
  const rules: Rule[] = []
  const context: string[] = []
  let prelude = ''
  for (let i = 0; i < code.length; i += 1) {
    const character = code[i]
    if (character === '{') {
      const selector = prelude.trim().replace(/\s+/g, ' ')
      prelude = ''
      let depth = 1
      let end = i + 1
      let body = ''
      while (end < code.length && depth > 0) {
        if (code[end] === '{') {
          depth += 1
        } else if (code[end] === '}') {
          depth -= 1
        }
        if (depth > 0) {
          body += code[end]
        }
        end += 1
      }
      if (body.includes('{')) {
        context.push(selector)
        continue
      }
      const declarations: (readonly [string, string])[] = []
      for (const part of body.split(';')) {
        const colon = part.indexOf(':')
        if (colon !== -1) {
          declarations.push([part.slice(0, colon).trim(), part.slice(colon + 1).trim()] as const)
        }
      }
      rules.push({ selector: [...context, selector].join(' '), declarations })
      // `end` is one past the closing brace; the loop's own `i += 1` steps onto
      // it, so this rule's `}` never reaches the context-popping branch below.
      i = end - 1
    } else if (character === '}') {
      context.pop()
      prelude = ''
    } else if (character === ';') {
      prelude = ''
    } else {
      prelude += character
    }
  }
  return rules
}

/** A single CSS identifier, and nothing else: the shape of a keyword value.
 *
 *  `flex`, `inline-flex`, `border-box`, `nowrap`, `tabular-nums`, `none`. Not
 *  `1px solid var(--color-border)`, not `#7C8CA2`, not `0.5`, not
 *  `var(--space-md)`, not `'+'`. Anchored at both ends so a shorthand whose
 *  first word is a keyword cannot pass as one. */
const KEYWORD = /^[a-z][a-z-]*$/

/** One rule's declarations as the census records them: `property` for a
 *  quantity, `property: keyword` for a keyword, comma-joined in source order. */
function censusOf(rule: Rule): string {
  return rule.declarations
    .map(([property, value]) => (KEYWORD.test(value) ? `${property}: ${value}` : property))
    .join(', ')
}

/** One stylesheet's rules, keyed by selector.
 *
 *  Throws on a duplicate selector rather than letting the later rule overwrite
 *  the earlier one in the record -- which would hide a whole rule from the
 *  census. Measured at the time of writing: no stylesheet in the tree declares
 *  one selector twice. */
function censusFor(relative: string): Record<string, string> {
  const census: Record<string, string> = {}
  for (const rule of rulesIn(read(relative))) {
    if (rule.selector in census) {
      throw new Error(
        `${relative} declares \`${rule.selector}\` twice. The census is keyed by ` +
          `selector, so the second rule would silently replace the first and go ` +
          `unguarded. Fold them into one rule.`,
      )
    }
    census[rule.selector] = censusOf(rule)
  }
  return census
}

/** Every declaration in the tree, in source order.
 *
 *  Derived from the files by `censusFor`, so updating it is a mechanical
 *  transcription rather than a judgement -- and *having* to update it is the
 *  point. A change to any entry below should be a deliberate edit in two places
 *  rather than an invisible one in one. */
const CENSUS: Readonly<Record<string, Readonly<Record<string, string>>>> = {
  // Derived by running `censusFor` against the file and transcribing what the
  // assertion printed, the same mechanical way as every entry below.
  'home/HomeScreen.module.css': {
    '.screen':
      'box-sizing: border-box, display: flex, flex-direction: column, align-items: stretch, gap, max-width, margin, padding, color, font-family',
    '.heading': 'margin, font-family, font-size, font-weight, line-height',
    '.counts': 'display: flex, flex-wrap: wrap, gap',
    '.waiting': 'margin, color, font-size, line-height',
    '.count':
      'display: flex, flex-direction: column, gap, min-width, margin, padding, border, border-radius, background',
    '.countLabel': 'color, font-size, font-weight, letter-spacing, text-transform: uppercase',
    '.countValue': 'font-family, font-size, line-height',
    '.ways': 'display: flex, flex-direction: column, gap',
    '.way':
      'display: flex, flex-direction: column, gap, padding, border, border-radius, background, box-shadow, text-decoration: none, transition',
    '.way:hover': 'border-color',
    '.wayLabel': 'color, font-size, font-weight, line-height',
    '.wayHint': 'color, font-size, line-height',
  },
  // Derived the same mechanical way as its neighbours: `censusFor` was run
  // against the file and its output transcribed, not read off the stylesheet by
  // eye. `.bar` is worn by `main.tsx`'s `<header>` and the rest by the `<nav>`
  // inside it -- one bar, so one stylesheet.
  'Nav.module.css': {
    '.bar':
      'display: flex, flex-wrap: wrap, align-items: center, gap, padding, border-bottom, background',
    '.nav': 'display: flex, flex-wrap: wrap, align-items: center, gap, margin-right: auto',
    '.link':
      'padding, border-bottom, color, font-family, font-size, font-weight, text-decoration: none, transition',
    '.link:hover': 'color',
    '.current': 'border-bottom-color, color',
  },
  // Derived by applying `censusOf`'s own rule to the file, not transcribed by
  // eye -- the header above calls this mechanical, and doing it by hand is how
  // a census drifts from the stylesheet it is supposed to guard.
  'ThemeControl.module.css': {
    '.control': 'display: inline-flex, align-items: center, gap, font-family, font-size',
    '.label': 'color, font-weight',
    '.select':
      'min-height, padding, border, border-radius, background, color, font-family, font-size, line-height, cursor: pointer, transition',
    '.select:hover': 'border-color',
  },
  'SignOutControl.module.css': {
    '.control': 'display: inline-flex, align-items: center, gap, font-family, font-size',
    '.confirm':
      'display: inline-flex, flex-wrap: wrap, align-items: center, gap, padding, border, border-radius, background, box-shadow, font-family, font-size',
    '.button':
      'min-height, min-width, padding, border, border-radius, background, color, font-family, font-size, font-weight, line-height, cursor: pointer, transition',
    '.button:hover:not(:disabled)': 'border-color',
    '.button:disabled': 'opacity, cursor: not-allowed',
    '.danger': 'border-color: transparent, background, color',
    '.warning': 'font-weight',
    '.error': 'color',
  },
  'admin/AdminScreen.module.css': {
    '.screen':
      'box-sizing: border-box, display: flex, flex-direction: column, align-items: stretch, gap, max-width, margin, padding, color, font-family',
    '.heading': 'margin, font-family, font-size, font-weight, line-height',
    '.who': 'margin, color, font-size, line-height',
    // `border` before `border-left-width`: the shorthand resets the longhand, so
    // this order is the thicker left edge and the other order is not.
    '.alert':
      'margin, padding, border, border-left-width, border-radius, background, color, font-size, line-height',
    '.alertLine': 'margin',
    '.alertLine + .alertLine': 'margin-top',
    '.waiting': 'margin, padding, color, font-size, line-height, text-align: center',
    '.truncated': 'margin, color, font-size, line-height',
  },
  'admin/StatTiles.module.css': {
    '.tiles': 'display: flex, flex-direction: column, gap, margin, padding',
    '.caption': 'margin, color, font-family, font-size, line-height',
    // The grid is on `.grid` and not on `.tiles` because a caption spanning the
    // tracks stops `auto-fit` collapsing any of them; the rule's own docblock
    // carries the measurement.
    '.grid': 'display: grid, grid-template-columns, gap',
    '.tile':
      'display: flex, flex-direction: column, gap, box-sizing: border-box, padding, border, border-radius, background, box-shadow',
    '.label':
      'color, font-family, font-size, font-weight, letter-spacing, line-height, text-transform: uppercase',
    '.figure':
      'color, font-family, font-size, font-variant-numeric: tabular-nums, font-weight, line-height',
  },
  'admin/TaskTable.module.css': {
    '.scroller': 'max-width, overflow-x: auto, border, border-radius',
    '.table':
      'width, min-width, border-collapse: collapse, background, font-family, font-size, line-height',
    '.head th':
      'padding, border-bottom, color, font-size, font-weight, letter-spacing, text-align: left, text-transform: uppercase, white-space: nowrap',
    '.row > td': 'padding, border-top, vertical-align: top',
    '.reason': 'min-width',
    '.assignee': 'font-family, white-space: nowrap',
    '.age': 'font-family, font-variant-numeric: tabular-nums, white-space: nowrap, text-align: right',
    '.action': 'white-space: nowrap',
    '.confirm': 'display: flex, flex-wrap: wrap, align-items: center, gap',
    '.prompt': 'flex-basis, margin, color, font-size, line-height',
    '.empty':
      'margin, padding, border, border-radius, background, color, font-family, font-size, text-align: center',
    '.note': 'margin, color, font-family, font-size, line-height',
  },
  'login/LoginPage.module.css': {
    '.form':
      'box-sizing: border-box, display: flex, flex-direction: column, gap, width, max-width, margin, padding, border, border-radius, background, box-shadow, font-family, color',
    '.heading': 'margin, font-family, font-size, font-weight, line-height',
    '.field': 'display: flex, flex-direction: column, gap, min-width, color, font-family, font-size',
    '.input':
      'min-height, box-sizing: border-box, padding, border, border-radius, background, color, font-family, font-size',
    '.error': 'margin, color, font-family, font-size',
    '.button':
      'align-self: start, min-height, min-width, padding, border, border-radius, background, color, font-family, font-size, font-weight, line-height, cursor: pointer, transition',
    '.button:hover:not(:disabled)': 'border-color',
    '.button:disabled': 'opacity, cursor: not-allowed',
  },
  'receipts/ReceiptsScreen.module.css': {
    '.screen':
      'box-sizing: border-box, display: flex, flex-direction: column, align-items: stretch, gap, max-width, margin, padding, color, font-family',
    '.heading': 'margin, font-family, font-size, font-weight, line-height',
    '.who': 'margin, color, font-size, line-height',
    '.scope': 'margin, color, font-size, line-height',
    '.alert':
      'margin, padding, border, border-left-width, border-radius, background, color, font-size, line-height',
    '.alertLine': 'margin',
    '.alertLine + .alertLine': 'margin-top',
    '.waiting': 'margin, padding, color, font-size, line-height, text-align: center',
    '.exportButton': 'align-self: flex-end',
    '.note': 'margin, align-self: flex-end, color, font-size, line-height',
    '.empty':
      'margin, padding, border, border-radius, background, color, font-size, text-align: center',
    '.scroller': 'max-width, overflow-x: auto, border, border-radius',
    '.table':
      'width, min-width, border-collapse: collapse, background, font-family, font-size, line-height',
    '.head th':
      'padding, border-bottom, color, font-size, font-weight, letter-spacing, text-align: left, text-transform: uppercase, white-space: nowrap',
    '.row > td': 'padding, border-top, vertical-align: top',
    '.date': 'white-space: nowrap',
    '.merchant': 'min-width',
    '.number': 'white-space: nowrap, text-align: right',
    '.currency': 'margin-right, color, font-family',
    '.status': 'white-space: nowrap',
    '.more': 'align-self: center',
  },
  'review/ConfidenceRail.module.css': {
    '.rail': 'border, border-radius, background, padding',
    '.heading': 'margin, font-family, font-size, font-weight, line-height',
    '.score': 'margin, font-size, line-height',
    '.band': 'display: flex, align-items: baseline, gap, margin, font-size, font-weight, line-height',
    '.bandIcon': 'flex: none, font-size, line-height',
    '.bandWord': 'letter-spacing, text-transform: uppercase',
    '.high': 'color',
    '.middle': 'color',
    '.low': 'color',
    '.note': 'margin, color, font-size',
    '.list': 'margin, padding, list-style: none',
    '.reason':
      'display: flex, align-items: baseline, justify-content: space-between, gap, padding, border-top, font-size, line-height',
    '.reason:first-child': 'border-top: none, padding-top',
    '.reasonText': 'min-width',
    '.penalty': 'flex: none, font-family, font-variant-numeric: tabular-nums, white-space: nowrap',
  },
  'review/FindingsPanel.module.css': {
    '.panel': 'border, border-radius, background, box-shadow, padding',
    '.heading': 'margin, font-family, font-size, font-weight, line-height',
    '.note': 'margin, color, font-size',
    '.empty': 'margin, color, font-size',
    '.list': 'margin, padding, list-style: none',
    '.finding': 'padding, border-top, font-size, line-height',
    '.finding:first-child': 'border-top: none, padding-top',
    '.disclosure': 'display: block',
    '.summary':
      'display: flex, flex-wrap: wrap, align-items: baseline, gap, list-style: none, cursor: pointer',
    '.summary::-webkit-details-marker': 'display: none',
    '.summary::after': 'flex: none, margin-left: auto, color, content',
    '.disclosure[open] > .summary::after': 'content',
    '.context':
      'margin, padding, max-width, overflow-x: auto, border-radius, background, color, font-family, font-size, line-height, white-space: pre-wrap',
    '.noContext': 'margin, color, font-size',
    '.ruleId': 'flex: none, font-family, font-size, font-weight',
    '.severity':
      'flex: none, font-style: normal, font-size, font-weight, letter-spacing, text-transform: uppercase',
    '.error': 'color',
    '.warn': 'color',
    '.info': 'color',
    '.resolved': 'flex: none, color, font-size',
  },
  'review/ImagePane.module.css': {
    '.pane': 'border, border-radius, background, overflow: hidden',
    '.toolbar': 'display: flex, flex-wrap: wrap, gap, padding, border-bottom, background',
    '.button':
      'min-height, min-width, padding, border, border-radius, background, color, font-family, font-size, font-weight, line-height, cursor: pointer, transition',
    '.button:hover': 'border-color',
    '.image': 'display: block, max-width, height: auto, margin, transform-origin',
    '.failure': 'display: flex, flex-direction: column, align-items: flex-start, gap, padding',
    '.alert': 'margin, color, font-size',
    '.loading': 'margin, padding, color, font-size, text-align: center',
  },
  'review/LineItemsTable.module.css': {
    '.scroller': 'max-width, overflow-x: auto, border, border-radius',
    '.table':
      'width, min-width, table-layout: fixed, border-collapse: collapse, background, font-family, font-size, line-height',
    '.head th':
      'box-sizing: border-box, padding, border-bottom, color, font-size, font-weight, letter-spacing, text-align: left, text-transform: uppercase',
    '.head th:nth-child(1)': 'width, text-align: right',
    '.head th:nth-child(2)': 'width',
    '.head th:nth-child(3)': 'width',
    '.head th:nth-child(4)': 'width, text-align: right',
    '.head th:nth-child(5)': 'width',
    '.head th:nth-child(6)': 'width, text-align: right',
    '.head th:nth-child(7)': 'width, text-align: right',
    '.row > td': 'padding, border-top, vertical-align: top',
    '.row:nth-child(even)': 'background',
    '.rowActive:nth-child(even), .rowActive': 'background',
    '.position': 'font-family, font-variant-numeric: tabular-nums, color, text-align: right',
    '.money': 'text-align: right',
    '.cell':
      'width, min-height, box-sizing: border-box, padding, border, border-radius, background, color, font-family, font-size',
    '.cell::placeholder': 'color, opacity',
    '.cell:placeholder-shown': 'border-left',
    '.error': 'margin, color, font-family, font-size',
  },
  'review/MoneyInput.module.css': {
    // `display: flex` and not `inline-flex` is the whole of the browser pass's
    // C1 width fix: in a `<td>` an inline-level label shrink-wraps to the
    // input's intrinsic `size="20"` width -- measured 246px against 92-119px
    // cells -- and the right-aligned em dash is pushed outside the clipped
    // scroller. The rule's own docblock carries the measurement.
    '.field': 'display: flex, flex-direction: column, min-width, gap, font-family, font-size, color',
    '.input':
      'box-sizing: border-box, font-family, font-variant-numeric: tabular-nums, text-align: right, min-height, padding, border, border-radius, background, color, font-size',
    '.input::placeholder': 'color, opacity',
    '.input:placeholder-shown': 'border-left',
    '.invalid': 'border-color',
    '.error': 'margin, color, font-family, font-size',
  },
  'review/ReceiptForm.module.css': {
    '.form':
      'display: grid, grid-template-columns, gap, align-items: start, border, border-radius, background, box-shadow, padding',
    '.form > h2': 'grid-column, margin, font-family, font-size, font-weight, line-height',
    '.fieldCell': 'display: flex, flex-direction: column, gap, min-width',
    '.field': 'display: flex, flex-direction: column, gap, min-width, color, font-family, font-size',
    '.input':
      'width, min-height, box-sizing: border-box, padding, border, border-radius, background, color, font-family, font-size',
    '.input::placeholder': 'color, opacity',
    '.input:placeholder-shown': 'border-left',
    '.error': 'margin, color, font-family, font-size',
    '.select':
      'width, min-height, box-sizing: border-box, padding, border, border-radius, background, color, font-family, font-size',
    '.check':
      'display: flex, align-items: center, gap, min-height, color, font-family, font-size, cursor: pointer',
    '.checkbox': 'flex: none, width, height, margin, accent-color, cursor: pointer',
  },
  'review/ReviewScreen.module.css': {
    '.screen':
      'box-sizing: border-box, display: grid, grid-template-columns, align-content: start, gap, max-width, margin, padding, font-family, color',
    '.screen > *': 'grid-column, min-width',
    '.screen > h1': 'grid-column, margin, font-family, font-size, font-weight, line-height',
    '.screen > div':
      'grid-column, grid-row, align-self: start, position: sticky, top, max-height, overflow: auto',
    '.notice':
      'box-sizing: border-box, display: flex, flex-direction: column, align-items: flex-start, gap, max-width, margin, padding, font-family, color',
    '.noticeFailed': 'justify-content: center, min-height, border, border-radius, background',
    '.message': 'margin, font-size, line-height',
    '.outcome': 'display: flex, flex-direction: column, gap',
    '.alert':
      'margin, padding, border-left, border-radius, background, color, font-size, font-weight, line-height',
    '.explanation': 'margin, color, font-size, line-height',
    '.terminal':
      'display: flex, flex-direction: column, align-items: flex-start, gap, padding, border, border-radius, background, box-shadow',
    '.terminalHeading': 'margin, font-size, font-weight, line-height',
    '.rewrites': 'margin, padding-left, font-size, line-height',
    '.rewrites code': 'font-family, font-size',
    '.action':
      'min-height, min-width, padding, border, border-radius, background, color, font-family, font-size, font-weight, line-height, cursor: pointer, transition',
    '.action:hover:not(:disabled)': 'border-color',
    '.action:disabled': 'opacity, cursor: not-allowed',
    '.primary': 'border-color: transparent, background, color',
    '.hint': 'margin, color, font-size, line-height',
    '@media (max-width: 1023px) .screen': 'grid-template-columns, padding',
    '@media (max-width: 1023px) .screen > *, .screen > h1, .screen > div':
      'grid-column, grid-row: auto, position: static, max-height: none',
  },
  'styles/tokens.css': {
    ':root':
      'color-scheme: light, --font-sans, --font-display, --font-mono, --text-xs, --text-sm, --text-base, --text-lg, --text-xl, --text-2xl, --text-3xl, --space-xs, --space-sm, --space-md, --space-lg, --space-xl, --space-2xl, --space-3xl, --space-4xl, --space-5xl, --radius-sm, --radius-md, --radius-lg, --shadow-sm, --shadow-md, --color-background, --color-surface, --color-surface-raised, --color-surface-active, --color-surface-sunken, --color-foreground, --color-muted-foreground, --color-border, --color-primary, --color-ring, --color-severity-error, --color-severity-warn, --color-severity-info, --color-positive, --color-null',
    ":root[data-theme='dark']":
      'color-scheme: dark, --color-background, --color-surface, --color-surface-raised, --color-surface-active, --color-surface-sunken, --color-foreground, --color-muted-foreground, --color-border, --color-primary, --color-ring, --color-severity-error, --color-severity-warn, --color-severity-info, --color-positive, --color-null',
    "@media (prefers-color-scheme: dark) :root:not([data-theme='light'])":
      'color-scheme: dark, --color-background, --color-surface, --color-surface-raised, --color-surface-active, --color-surface-sunken, --color-foreground, --color-muted-foreground, --color-border, --color-primary, --color-ring, --color-severity-error, --color-severity-warn, --color-severity-info, --color-positive, --color-null',
    body: 'margin, background, color, font-family, font-size, line-height',
    ':where(a, button, input, select, textarea):focus-visible': 'outline, outline-offset',
    '@media (prefers-reduced-motion: reduce) *, *::before, *::after': 'transition, animation',
  },
  'ui/Button.module.css': {
    '.button':
      'min-height, min-width, padding, border, border-radius, font-family, font-size, font-weight, line-height, cursor: pointer, transition',
    '.button:disabled': 'opacity, cursor: not-allowed',
    '.primary': 'background, color',
    '.secondary': 'background, color, border-color',
    '.danger': 'background, color',
    '.button:hover:not(:disabled)': 'border-color',
  },
  'ui/Chip.module.css': {
    '.chip':
      'display: inline-flex, align-items: center, gap, padding, border, border-radius, background, font-family, font-size, font-weight, line-height, white-space: nowrap',
    '.icon': 'display: inline-flex, flex: none, align-items: center',
    '.error': 'color',
    '.warn': 'color',
    '.info': 'color',
    '.positive': 'color',
    '.neutral': 'color',
  },
  'ui/Value.module.css': {
    '.numeric': 'font-family, font-variant-numeric: tabular-nums',
    '.text': 'font-family',
    // §4's three signals for the not-extracted mark. `value.test.tsx` also pins
    // these three by *value*, which is the one rule in the tree that gets that
    // treatment and is why it survived the review that found everything else
    // deletable.
    '.notExtracted': 'font-family, color, border-left, padding-left',
    // The same rule mirrored, for a cell whose contents are flush right. Added
    // 2026-08-20 after looking: at 1440 on `/app/receipts`, in Chromium, Firefox
    // and WebKit alike, a receipt carrying a currency but no total rendered
    // `PHP|—` -- the left-edge gutter landing between the currency code and the
    // mark, aligned with nothing, because a right-aligned span shrink-wraps away
    // from the edge the rule assumes. `value.test.tsx` pins this one by value
    // too, in both directions: the mirrored pair present, the left pair absent.
    '.notExtractedEnd': 'font-family, color, border-right, padding-right',
  },
  // Derived by running `censusFor` over the file, as the header above requires,
  // rather than transcribed by eye.
  'upload/UploadScreen.module.css': {
    '.screen':
      'box-sizing: border-box, display: flex, flex-direction: column, align-items: stretch, gap, max-width, margin, padding, color, font-family',
    '.heading': 'margin, font-family, font-size, font-weight, line-height',
    '.scope': 'margin, color, font-size, line-height',
    // `border` before `border-left-width`, for the reason `admin/AdminScreen`'s
    // `.alert` records: the shorthand resets the longhand, so this order is the
    // thicker left edge and the other order is not.
    '.alert':
      'margin, padding, border, border-left-width, border-radius, background, color, font-size, line-height',
    '.field':
      'display: flex, flex-direction: column, align-items: center, gap, box-sizing: border-box, padding, border, border-radius, background, box-shadow, cursor: pointer',
    '.label': 'color, font-size, font-weight, line-height',
    '.input': 'max-width, color, font-family, font-size, cursor: pointer',
    // The ring is on the card and not on the control: the `<label>` wraps its
    // input, so the click target is the whole box and the focus indicator has to
    // be the same box.
    '.field:focus-within': 'outline, outline-offset',
    '.limits': 'margin, color, font-size, line-height, text-align: center',
    '.sending': 'margin, color, font-size, line-height, text-align: center',
  },
  // The processing view. Two columns placed by class rather than by position --
  // `grid-column` on `.receipt` and `.steps` -- so there is no `>` selector here
  // for a wrapper to be added under.
  'upload/ProcessingView.module.css': {
    '.screen':
      'box-sizing: border-box, display: grid, grid-template-columns, align-content: start, gap, max-width, margin, padding, color, font-family',
    '.heading': 'grid-column, margin, font-family, font-size, font-weight, line-height',
    '.scope': 'grid-column, margin, color, font-size, line-height',
    '.receipt':
      'grid-column, box-sizing: border-box, display: flex, flex-direction: column, gap, min-width, padding, border, border-radius, background, box-shadow',
    '.steps': 'grid-column, display: flex, flex-direction: column, gap, min-width',
    '.paneHeading':
      'margin, color, font-size, font-weight, letter-spacing, line-height, text-transform: uppercase',
    '.fileName': 'margin, overflow-wrap: anywhere, font-size, font-weight, line-height',
    '.receiptId': 'margin, overflow-wrap: anywhere, color, font-family, font-size, line-height',
    '.alsoQueued': 'margin, overflow-wrap: anywhere, color, font-size, line-height',
    '.list': 'display: flex, flex-direction: column, gap, margin, padding, list-style: none',
    '.past': 'color, font-size, line-height',
    '.active':
      'display: flex, flex-direction: column, gap, box-sizing: border-box, padding, border, border-radius, background, box-shadow',
    '.stage': 'color, font-size, font-weight, line-height',
    '.details': 'display: flex, flex-direction: column, gap, margin, padding, list-style: none',
    '.detail': 'color, font-family, font-size, line-height',
    '.quiet': 'margin, color, font-size, line-height',
    '.outcome': 'margin, font-size, line-height',
    '.status': 'font-family, font-weight',
    '.next':
      'align-self: start, padding, border, border-radius, background, color, font-size, font-weight, line-height, text-decoration: none',
    '.next:focus-visible': 'outline, outline-offset',
    // Mirrored from `review/ReviewScreen.module.css`'s block at the same width.
    // The pair must agree: if one collapses to a single column and the other
    // does not, the receipt moves at the hand-over, which is the property the
    // two-column shape was chosen for. `.steps` resetting to column 1 is the
    // load-bearing half -- `grid-column: 2` in a one-column grid creates an
    // implicit second column rather than clamping.
    '@media (max-width: 1023px) .screen': 'grid-template-columns, padding',
    '@media (max-width: 1023px) .receipt, .steps': 'grid-column',
  },
}

describe('the census reads what is there, not what it hopes for', () => {
  it('parses declarations, keywords and at-rule nesting', () => {
    const [rule] = rulesIn('.x { display: flex; gap: var(--space-md) }')
    expect(rule.selector).toBe('.x')
    expect(censusOf(rule)).toBe('display: flex, gap')

    // An at-rule qualifies the rules inside it, so a copy hoisted into a media
    // query is a different census key and cannot answer for the top-level rule.
    const nested = rulesIn('@media (min-width: 40em) { .x { display: grid } }')
    expect(nested[0].selector).toBe('@media (min-width: 40em) .x')

    // ...and the rule after an at-rule is back at the top level.
    const after = rulesIn('@media print { .a { color: red } }\n.b { display: block }')
    expect(after.map((entry) => entry.selector)).toEqual(['@media print .a', '.b'])
  })

  it('is not fooled by a comment that contains a rule', () => {
    // Not hypothetical: `MoneyInput.module.css`'s docblock contains the literal
    // text `::before { content: '$' }`.
    const css = "/* ::before { content: '$' } */\n.real { display: flex }"
    expect(rulesIn(css).map((rule) => rule.selector)).toEqual(['.real'])
  })

  it('discards a statement at-rule instead of gluing it onto the next selector', () => {
    expect(rulesIn("@charset 'utf-8';\n.x { color: red }")[0].selector).toBe('.x')
  })

  it('separates a keyword from a quantity that merely starts with a word', () => {
    expect(KEYWORD.test('flex')).toBe(true)
    expect(KEYWORD.test('inline-flex')).toBe(true)
    expect(KEYWORD.test('border-box')).toBe(true)
    // A shorthand whose first word is a keyword is not a keyword value.
    expect(KEYWORD.test('none 1px solid')).toBe(false)
    expect(KEYWORD.test('1px solid var(--color-border)')).toBe(false)
    expect(KEYWORD.test('var(--space-md)')).toBe(false)
    expect(KEYWORD.test('#7C8CA2')).toBe(false)
    expect(KEYWORD.test('0.5')).toBe(false)
    expect(KEYWORD.test("'+'")).toBe(false)
  })

  it('refuses a stylesheet that declares one selector twice', () => {
    // Two rules for one selector would collapse to one census entry and hide a
    // whole rule.
    //
    // **This test does NOT exercise the guard, and this comment used to say it
    // did.** Corrected 2026-08-07: it said "proven on a synthetic file through
    // the same code path", but the call below is `rulesIn`, not `censusFor` --
    // and `censusFor` is where the duplicate check lives. Measured: replacing
    // that check's condition with `if (false)` leaves this test green. What is
    // asserted here is the weaker, true thing -- that `rulesIn` surfaces both
    // rules rather than merging them, which is the precondition the guard needs.
    // The guard itself is still reached by the `it.each` over the real files.
    const twice = rulesIn('.x { color: red }\n.x { display: block }')
    expect(twice).toHaveLength(2)
    expect(twice[0].selector).toBe(twice[1].selector)
  })

  it('is reading the real tree, not an empty one', () => {
    const files = stylesheets()
    expect(files.length, 'no stylesheets found -- the whole census is vacuous').toBe(22)
    let rules = 0
    let declarations = 0
    for (const file of files) {
      for (const rule of rulesIn(read(file))) {
        rules += 1
        declarations += rule.declarations.length
      }
    }
    // Floors, not equalities: adding a rule is not a failure here -- it is a
    // failure in the census below, which says which rule and where. These two
    // exist only to catch a parser that has stopped finding anything.
    //
    // The exact rule and declaration totals used to be written down beside
    // them and are not any more: they moved on every stylesheet edit while the
    // floors never did, so they were a maintenance cost with no guard attached
    // (ADR-0032 §3). The file count above stays an equality because a
    // stylesheet appearing or vanishing is precisely what it is watching for.
    expect(rules, 'the parser stopped finding rules').toBeGreaterThan(120)
    expect(declarations, 'the parser stopped finding declarations').toBeGreaterThan(600)
  })
})

describe('every declaration the app ships is accounted for', () => {
  it('guards every stylesheet in the tree, with none added or removed unseen', () => {
    expect(
      stylesheets(),
      'a stylesheet was added to or removed from src/ without a CENSUS entry. A ' +
        'new one arrives unguarded -- which is exactly how login/LoginPage.module.css ' +
        'shipped browser-default through a whole milestone.',
    ).toEqual(Object.keys(CENSUS).sort())
  })

  it.each(Object.keys(CENSUS))('%s declares exactly what the census records', (file) => {
    expect(
      censusFor(file),
      `${file}'s declarations no longer match the census. A rule emptied to {}, a ` +
        `declaration deleted, renamed or reordered, or a keyword value swapped -- ` +
        `all four land here. If the change is deliberate, transcribe it into ` +
        `CENSUS and say in the commit what a browser showed you, because nothing ` +
        `in the five gates can see what it looks like.`,
    ).toEqual(CENSUS[file])
    // **Rule order, which the assertion above cannot see.** `toEqual` compares
    // objects by key/value and ignores key order, so until 2026-08-24 the whole
    // census was blind to a rule being MOVED. Found by mutation in the
    // whole-branch review: hoisting `.current` above `.link` in
    // `Nav.module.css` reverses a cascade that file calls load-bearing -- the
    // current-page link loses its underline and its colour -- and the census
    // stayed green, as did `nav.test.tsx` and `value.test.tsx`.
    //
    // That is the same hazard the docblock above already names for
    // DECLARATIONS inside a rule ("a shorthand resets every longhand it
    // covers"), one level up: between rules, later wins at equal specificity.
    // The census recorded declaration order and sorted rule order away.
    expect(
      Object.keys(censusFor(file)),
      `${file}'s rules are the right rules in the wrong ORDER. At equal ` +
        `specificity the later rule wins, so moving one past another changes ` +
        `what paints without changing any declaration -- which the comparison ` +
        `above cannot see, because it compares objects and objects have no ` +
        `order. If the move is deliberate, reorder CENSUS to match and say in ` +
        `the commit what a browser showed you.`,
    ).toEqual(Object.keys(CENSUS[file]))
  })
})

// --------------------------------------------------------------------------- //
// The line-items table's column arithmetic (ISSUE-032). The census next door
// pins that a declaration is PRESENT; it cannot tell whether the numbers add up.
// --------------------------------------------------------------------------- //

/** `3rem`, `24%` or `12px` as pixels, against a table of `basis` px.
 *
 *  Returns `null` for anything else -- a `calc()`, a `var()`, a keyword -- so an
 *  unreadable width fails the test that calls this rather than silently
 *  contributing zero to a sum. */
function lengthPx(value: string, basis: number): number | null {
  const rem = /^([\d.]+)rem$/.exec(value)
  if (rem) return Number(rem[1]) * 16
  const percent = /^([\d.]+)%$/.exec(value)
  if (percent) return (Number(percent[1]) / 100) * basis
  const px = /^([\d.]+)px$/.exec(value)
  if (px) return Number(px[1])
  return null
}

/** The px value of a `--space-*` token, read from `tokens.css` rather than
 *  written down here, so the two cannot drift. */
function spaceToken(name: string): number {
  const match = new RegExp(`--${name}:\\s*([\\d.]+)px`).exec(read('styles/tokens.css'))
  if (!match) throw new Error(`tokens.css declares no --${name} in px`)
  return Number(match[1])
}

describe('the line items table leaves room for the columns its rules do not name', () => {
  /** ISSUE-032, as a property rather than as the instance that was found.
   *
   * Seven declared widths, eight rendered columns, and `.head th` was
   * content-box -- so the seven demanded `3rem + 85% + 7x16px = 758.4px` of a
   * 704px table and overflowed it by themselves. The eighth got nothing, and
   * under `table-layout: fixed` a zero-width cell does not grow: its 13px
   * checkbox painted over the column beside it at every width and in both
   * themes, and the em dash meaning "never extracted" was pushed outside the
   * clipped scroller.
   *
   * **Why this is arithmetic and not a count.** The obvious pin -- "every
   * column has a declared width" -- is wrong for this design: the eighth is
   * *meant* to take the remainder. What must hold is that there IS a remainder.
   * Reading `box-sizing` rather than assuming it is what makes this the pin
   * that would have caught the original defect: with the declaration removed
   * the padding term returns and the sum overflows again.
   *
   * So a ninth column, a widened Description, a lowered `min-width`, and
   * `box-sizing` going back to content-box all land here -- the ways the rule
   * list and the markup list fall out of step.
   *
   * Playwright is not one of the five gates (ADR-0029), which is why this is a
   * filesystem test. It cannot see what the columns look like, only that none
   * of them is impossible. */
  it('every column the header renders computes to a positive width at the floor', () => {
    const rules = rulesIn(read('review/LineItemsTable.module.css'))
    const declarationOf = (selector: string, property: string): string | undefined =>
      rules
        .find((rule) => rule.selector === selector)
        ?.declarations.find(([name]) => name === property)?.[1]

    const floorValue = declarationOf('.table', 'min-width')
    expect(floorValue, '.table declares no min-width, so there is no floor to check').toBeDefined()
    const floor = lengthPx(floorValue as string, 0)
    expect(floor, `.table's min-width (${floorValue}) is not a length this test reads`).not.toBeNull()

    // The header cells are the boxes `table-layout: fixed` measures, so their
    // padding is part of what each declared width demands -- unless the box
    // model already counts it. This term IS ISSUE-032.
    const padding =
      declarationOf('.head th', 'box-sizing') === 'border-box' ? 0 : 2 * spaceToken('space-md')

    const widths = rules
      .filter((rule) => /^\.head th:nth-child\(\d+\)$/.test(rule.selector))
      .map((rule) => rule.declarations.find(([name]) => name === 'width')?.[1])
      .filter((value): value is string => value !== undefined)

    const columns = (read('review/LineItemsTable.tsx').match(/<th>/g) ?? []).length
    expect(
      columns,
      'no <th> found in LineItemsTable.tsx -- the count this compares against is vacuous',
    ).toBeGreaterThan(0)
    expect(
      widths.length,
      'more nth-child width rules than the header renders columns',
    ).toBeLessThanOrEqual(columns)

    const demanded = widths.reduce((total, value) => {
      const px = lengthPx(value, floor as number)
      expect(px, `a column width this test cannot read: ${value}`).not.toBeNull()
      return total + (px as number) + padding
    }, 0)

    const remainder = (floor as number) - demanded
    const unnamed = columns - widths.length

    expect(
      remainder,
      `${widths.length} declared widths demand ${demanded.toFixed(1)}px of a ${floor}px ` +
        `table, leaving ${remainder.toFixed(1)}px for the ${unnamed} column(s) no rule ` +
        `names. Under table-layout: fixed those collapse to zero and their controls ` +
        `paint over the column beside them -- ISSUE-032.`,
    ).toBeGreaterThan(0)
  })
})

// --------------------------------------------------------------------------- //
// The other half: colours are quantities, so the census pins only their
// presence -- and a quantity is judged by what it does.
// --------------------------------------------------------------------------- //

/** The relative luminance of an `#RRGGBB` colour, WCAG 2.1 relative-luminance
 *  definition -- the same arithmetic `e2e/visual.spec.ts` runs in the page, so
 *  the two halves cannot disagree about what a ratio is. Cross-checked against
 *  the browser's own recorded numbers: this computes 4.76 for `#64748B` on
 *  `#FFFFFF` and 5.43 for `#7C8CA2` on `#0E1223`, and `measurements.json` from
 *  the browser pass records exactly those two. */
function luminance(hex: string): number {
  const value = Number.parseInt(hex.slice(1), 16)
  const channel = (byte: number): number => {
    const scaled = byte / 255
    return scaled <= 0.03928 ? scaled / 12.92 : Math.pow((scaled + 0.055) / 1.055, 2.4)
  }
  return (
    0.2126 * channel((value >> 16) & 255) +
    0.7152 * channel((value >> 8) & 255) +
    0.0722 * channel(value & 255)
  )
}

function contrastRatio(foreground: string, background: string): number {
  const first = luminance(foreground)
  const second = luminance(background)
  const light = Math.max(first, second)
  const dark = Math.min(first, second)
  return Math.round(((light + 0.05) / (dark + 0.05)) * 100) / 100
}

/** Design §6's body-text floor, and deliberately flat.
 *
 *  WCAG relaxes to 3:1 for large text and this does not take that discount: the
 *  sweep in `e2e/visual.spec.ts` already flags anything under 4.5 whatever its
 *  size, the tree's measured minimum is 4.76, and a token is not large or small
 *  -- the same `--color-null` paints a 14px table cell and a 24px em dash. */
const AA = 4.5

/** Every theme block in `tokens.css`, as declared-token maps.
 *
 *  Three of them: `:root` (light, the default), `:root[data-theme='dark']` (the
 *  explicit opt-in) and the `prefers-color-scheme` copy (the OS one).
 *  `tokens.test.ts` pins that the last two carry identical declarations; this
 *  file does not re-assert that, it simply checks all three, so a value fixed in
 *  one and not the other still fails here. */
function themeBlocks(): Map<string, Map<string, string>> {
  const blocks = new Map<string, Map<string, string>>()
  for (const rule of rulesIn(read('styles/tokens.css'))) {
    if (rule.declarations.some(([property]) => property.startsWith('--color-'))) {
      blocks.set(rule.selector, new Map(rule.declarations))
    }
  }
  return blocks
}

const LIGHT = ':root'

/** The colour a token resolves to in one theme: the block's own value, or the
 *  light block's when the theme does not override it. */
function colorOf(blocks: Map<string, Map<string, string>>, block: string, token: string): string {
  const value = blocks.get(block)?.get(token) ?? blocks.get(LIGHT)?.get(token)
  if (value === undefined) {
    throw new Error(`no value for ${token} in ${block} or ${LIGHT}`)
  }
  return value
}

/** `var(--color-x)` and nothing else, or `null`. A composite value
 *  (`1px solid var(--color-border)`, a gradient) is not a flat paint and is not
 *  a pair this check can reason about. */
function soleToken(value: string): string | null {
  const match = /^var\((--color-[\w-]+)\)$/.exec(value.trim())
  return match === null ? match : match[1]
}

/** The surfaces an inherited `color` is checked against: the page, a panel, and
 *  a raised panel.
 *
 *  **`--color-surface-raised` joined this list on 2026-08-24, because a browser
 *  found what its absence hid.** The Editorial refresh gave `FindingsPanel`'s
 *  `.panel` a raised background, which moved severity text onto a surface no
 *  check covered: `--color-severity-error` measured **4.39:1 on it in dark**,
 *  under design §6's floor, with all five gates green. The fix darkened dark
 *  `--color-surface-raised` to `#161925`; that pair is **4.65:1** now and the
 *  surface is inside the bound, so it cannot drift back unnoticed.
 *
 *  **`--color-surface-active` and `--color-surface-sunken` are still outside**,
 *  and that is a gap rather than a clean bound -- the same gap that hid the one
 *  above. Live tokens do not clear the floor on them, re-derived at HEAD with
 *  this file's own `contrastRatio`:
 *
 *    --color-severity-error on --color-surface-active   dark 3.89, light 4.44
 *    --color-severity-error on --color-surface-sunken   light 4.35
 *    --color-null           on --color-surface-active   dark 4.27, light 4.41
 *    --color-null           on --color-surface-sunken   light 4.32
 *
 *  Four rows, **six pairs** -- state both, because a row can carry a dark
 *  number and a light one and counting rows as pairs is how this list was
 *  miscounted once already. Every one of them predates the Editorial refresh;
 *  widening the bound to cover them is a source change, not a test change.
 *
 *  **Whether any pair is *reached* is a cascade question this file cannot
 *  answer.** One was: `SignOutControl.module.css`'s `.error` sits inside
 *  `.confirm`, which paints `--color-surface-raised`, so a failed sign-out in
 *  dark was the 4.39:1 above. **It now measures 4.65:1** -- resolved as a side
 *  effect of the fix rather than by anyone aiming at it, which is worth saying
 *  out loud so nobody re-files it.
 *
 *  This block replaced two stacked docblocks on 2026-08-24: the commit that
 *  added the second left the first in place, and the first went on asserting
 *  two surfaces, five under-floor pairs and unchanged dark digits -- all three
 *  falsified by that same commit. A fix wave leaving its own predecessor
 *  standing is this project's most-repeated defect, and it happened here inside
 *  the fix for a defect a browser had just found. */
const INHERITABLE_SURFACES = [
  '--color-background',
  '--color-surface',
  '--color-surface-raised',
] as const

describe('a colour token is readable on what it is painted on', () => {
  it('reads three theme blocks with hex values, or says so', () => {
    const blocks = themeBlocks()
    expect(
      [...blocks.keys()],
      'tokens.css no longer has exactly the three theme blocks this check walks',
    ).toEqual([
      LIGHT,
      ":root[data-theme='dark']",
      "@media (prefers-color-scheme: dark) :root:not([data-theme='light'])",
    ])
    // Every colour is a plain six-digit hex. Anything else -- `rgb()`,
    // `color-mix()`, a `var()` alias -- would make `luminance` return NaN, and
    // `NaN >= 4.5` is false, so the check would red for a reason its message did
    // not explain. This makes it explain itself instead.
    for (const [name, block] of blocks) {
      for (const [token, value] of block) {
        if (token.startsWith('--color-')) {
          expect(value, `${name}: ${token} is not a #RRGGBB colour, so no ratio can be computed`)
            .toMatch(/^#[0-9A-Fa-f]{6}$/)
        }
      }
    }
  })

  it('clears the floor for every colour painted on a background in the same rule', () => {
    // Derived, not listed: a rule that sets both `color` and `background` names
    // its own pair, so this needs no judgement about what sits on what. It is
    // what covers the inverted controls -- `--color-background` as *text*, on
    // `--color-primary` and on `--color-severity-error` -- which would fail
    // every check below and are correct.
    const blocks = themeBlocks()
    const pairs = new Map<string, string>()
    for (const file of stylesheets()) {
      for (const rule of rulesIn(read(file))) {
        const declarations = new Map(rule.declarations)
        const raw = declarations.get('background') ?? declarations.get('background-color')
        const foreground = declarations.has('color') ? soleToken(declarations.get('color')!) : null
        const background = raw === undefined ? null : soleToken(raw)
        if (foreground !== null && background !== null) {
          pairs.set(`${foreground} on ${background}`, `${file} ${rule.selector}`)
        }
      }
    }
    expect(pairs.size, 'no same-rule colour pairs found -- this check is vacuous').toBeGreaterThan(5)
    // Collected rather than asserted one at a time: a token used in several
    // places breaks several pairs at once, and the first failure alone would
    // read as a narrower defect than it is.
    const below: string[] = []
    for (const [pair, where] of pairs) {
      const [foreground, background] = pair.split(' on ')
      for (const block of blocks.keys()) {
        const ratio = contrastRatio(
          colorOf(blocks, block, foreground),
          colorOf(blocks, block, background),
        )
        if (ratio < AA) {
          below.push(`${pair} is ${ratio}:1 in ${block} (${where})`)
        }
      }
    }
    expect(below, `a colour is unreadable on the background its own rule paints`).toEqual([])
  })

  it('clears the floor for every colour a rule sets without a background of its own', () => {
    // The other half, and the one the dark `--color-null` lift lives in. A rule
    // that sets `color` and no background paints onto whatever encloses it, so
    // the token has to be readable on both general surfaces. `--color-null`
    // reaches this check through four rules -- `ui/Value.module.css`'s
    // `.notExtracted` and three `::placeholder` rules -- and reverting the dark
    // block to the `#64748B` that is correct on white puts it at 3.91:1 here.
    const blocks = themeBlocks()
    const tokens = new Map<string, string>()
    for (const file of stylesheets()) {
      for (const rule of rulesIn(read(file))) {
        const declarations = new Map(rule.declarations)
        if (declarations.has('background') || declarations.has('background-color')) {
          continue
        }
        const foreground = declarations.has('color') ? soleToken(declarations.get('color')!) : null
        if (foreground !== null && !tokens.has(foreground)) {
          tokens.set(foreground, `${file} ${rule.selector}`)
        }
      }
    }
    expect(tokens.size, 'no inherited colour tokens found -- this check is vacuous')
      .toBeGreaterThan(4)
    expect(
      [...tokens.keys()],
      'the not-extracted token stopped reaching this check, so §6 is unenforced on it',
    ).toContain('--color-null')
    const below: string[] = []
    for (const [token, where] of tokens) {
      for (const surface of INHERITABLE_SURFACES) {
        for (const block of blocks.keys()) {
          const ratio = contrastRatio(
            colorOf(blocks, block, token),
            colorOf(blocks, block, surface),
          )
          if (ratio < AA) {
            below.push(`${token} on ${surface} is ${ratio}:1 in ${block} (${where})`)
          }
        }
      }
    }
    expect(
      below,
      `a colour is unreadable on a surface it can be inherited onto -- design §6's ` +
        `${AA}:1 body-text floor. Each entry names the token, the surface, the theme ` +
        `block and one rule that paints it.`,
    ).toEqual([])
  })

  it('computes the ratio the browser computes', () => {
    // The anti-vacuity control for the arithmetic itself: if `luminance` were
    // wrong, every assertion above would be wrong in the same direction and all
    // of them would still pass. These four numbers come from the browser pass's
    // own `measurements.json`, not from this file.
    expect(contrastRatio('#64748B', '#FFFFFF')).toBe(4.76)
    expect(contrastRatio('#7C8CA2', '#0E1223')).toBe(5.43)
    expect(contrastRatio('#0F172A', '#FFFFFF')).toBe(17.85)
    expect(contrastRatio('#F8FAFC', '#0E1223')).toBe(17.77)
    // ...and the value the dark lift replaced, which is what these checks exist
    // to keep out: below the floor on the dark panel, fine on white.
    expect(contrastRatio('#64748B', '#0E1223')).toBe(3.91)
  })
})

describe('a rounded corner is declared where a browser can honour it', () => {
  /** ISSUE-010 item 4, as a property over the tree rather than three instances.
   *
   * `border-collapse: collapse` and `border-radius` on one rule is not a
   * near-miss: the corners render square in all three engines, so the radius
   * declares an intent the browser discards. Three `.table` rules did it --
   * admin, receipts and review -- which is why the issue called it a
   * repository-wide question and not one screen's.
   *
   * The fix is not to delete the radius. `--radius-lg` is a design token
   * (`tokens.css`) and seven other surfaces round with it -- StatTiles,
   * LoginPage, ConfidenceRail, FindingsPanel, ImagePane among them -- so
   * rounded surfaces are the system's norm and the tables were meant to be
   * rounded. The radius moves to `.scroller`, which already exists on all
   * three, already sets `overflow-x: auto`, and is therefore already a
   * clipping context. The border moves with it so it is not cut mid-corner.
   *
   * **Bound, stated because green here is not the same as seen.** This checks
   * that no rule declares the contradiction. It cannot check that the corners
   * look right; jsdom lays nothing out and this file reads text. What a
   * browser showed is in the commit message, per the census assertion's own
   * instruction. */
  it('never sets border-radius on the same rule that collapses its borders', () => {
    const offenders: string[] = []
    for (const file of stylesheets()) {
      for (const rule of rulesIn(read(file))) {
        const declared = new Map(rule.declarations)
        if (declared.get('border-collapse') === 'collapse' && declared.has('border-radius')) {
          offenders.push(`${file} ${rule.selector}`)
        }
      }
    }
    expect(
      offenders,
      'a rule sets border-radius and border-collapse: collapse together. The ' +
        'browser discards the radius, so the declaration states an intent that ' +
        'never renders. Put the radius on the scrolling wrapper, which clips.',
    ).toEqual([])
  })
})
