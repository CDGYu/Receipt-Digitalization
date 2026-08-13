import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Button } from '../src/ui/Button'
import { Chip } from '../src/ui/Chip'
import { Value } from '../src/ui/Value'

/** All three `src/ui` primitives are pinned here rather than in a file each:
 *  Task 2's permitted file set names exactly one new test file, and splitting
 *  them would put two of the three outside it.
 *
 *  Nothing below asserts on a class name. Vitest's default is `css: false`, so a
 *  `.module.css` import is a proxy that answers for any key -- a class
 *  assertion would pass without any stylesheet existing at all, and would say
 *  nothing about what a reviewer sees. The assertions are on text content and
 *  accessible names, which are the parts that survive into a screen reader. */

afterEach(cleanup)

describe('Value — null is not zero, and neither is empty', () => {
  it('renders a null money value as an em dash, never a number', () => {
    render(<Value value={null} kind="money" />)
    const el = screen.getByLabelText('not extracted')
    expect(el.textContent).toBe('—')
    // The prime directive reaching the last inch: a null total rendered as
    // 0.00 would destroy the system's central safety property on the one
    // screen where a human decides.
    expect(el.textContent).not.toBe('0')
    expect(el.textContent).not.toBe('0.00')
    expect(el.textContent).not.toBe('')
  })

  it('renders an extracted zero as a real number, distinct from null', () => {
    render(<Value value="0.00" kind="money" />)
    expect(screen.getByText('0.00')).toBeTruthy()
    expect(screen.queryByLabelText('not extracted')).toBeNull()
  })

  it('gives null and zero different accessible names', () => {
    const { container: a } = render(<Value value={null} kind="money" />)
    const { container: b } = render(<Value value="0.00" kind="money" />)
    expect(a.textContent).not.toBe(b.textContent)
  })

  // A rule with an exception is a rule someone lands on the wrong side of. A
  // missing merchant name and a missing quantity are missing in the same way as
  // a missing total, and `Value` is the only place any of the three is decided,
  // so a `kind`-conditioned null branch would silently exempt two thirds of the
  // form. Reverted separately from the money row above.
  it.each(['money', 'text', 'count'] as const)(
    'applies the null rule to a %s value too, not to money alone',
    (kind) => {
      render(<Value value={null} kind={kind} />)
      expect(screen.getByLabelText('not extracted').textContent).toBe('—')
    },
  )

  // Every assertion above reaches the label through `getByLabelText`, which reads
  // the DOM attribute and never consults the role -- so all of them passed while
  // the span was a bare `role=generic`, for which ARIA 1.2 marks naming
  // PROHIBITED. The name was asserted and not delivered. `getByRole` resolves
  // through the accessibility tree instead, so this is the one assertion in the
  // file that fails if the name is not actually exposed.
  it('exposes the mark to the accessibility tree, not just as an attribute', () => {
    render(<Value value={null} kind="money" />)
    expect(screen.getByRole('img', { name: 'not extracted' }).textContent).toBe('—')
  })

  // §4's third state. `''` is not hypothetical here: `_coerce_text(None)` returns
  // `''`, so `null` and `''` land on the same column for `description_raw`
  // (LineItemsTable.tsx:117-121) and the database cannot tell "never recorded"
  // from "cleared" there either. An empty span is the exact failure the §4
  // headline names, so the empty string takes the mark.
  it('renders the empty string as the mark, not as nothing', () => {
    render(<Value value="" kind="text" />)
    expect(screen.getByRole('img', { name: 'not extracted' }).textContent).toBe('—')
  })

  // ...and the distinction it does NOT make, pinned so it is a decision rather
  // than an oversight: a cleared value and a never-extracted one are identical
  // here, because `Value` is handed a FieldMap and cannot know which is which.
  // §4 puts the "cleared" chip beside the label for that reason.
  it('does not distinguish a cleared value from one never extracted', () => {
    const { container: cleared } = render(<Value value="" kind="text" />)
    const { container: never } = render(<Value value={null} kind="text" />)
    expect(cleared.innerHTML).toBe(never.innerHTML)
  })
})

describe('Chip — the tone is never the only signal', () => {
  // "Never colour alone" is High severity in the accessibility contract (§6),
  // and red/green is the exact failure it names. The icon and the word are the
  // two signals that survive when the colour does not reach the reader, so each
  // is pinned on its own and reverted on its own.
  it('renders the icon it was given', () => {
    render(
      <Chip tone="error" icon={<svg data-testid="tone-icon" />}>
        Failed
      </Chip>,
    )
    expect(screen.getByTestId('tone-icon')).toBeTruthy()
  })

  it('renders its text', () => {
    render(
      <Chip tone="error" icon={<svg data-testid="tone-icon" />}>
        Failed
      </Chip>,
    )
    expect(screen.getByText('Failed')).toBeTruthy()
  })
})

// --------------------------------------------------------------------------- //
// The visual half of the rule, which no rendering test in this file can see.
//
// Vitest's default is `css: false`, so a `.module.css` import is a proxy that
// answers for ANY key. A class renamed on ONE side only -- which is exactly what
// this task did when it renamed `.null` to `.notExtracted` -- therefore ships
// unpainted with every gate green, taking `--color-null` and the hairline left
// border with it. Those are §4's scannability half, so losing them silently
// loses half the rule.
//
// **What "unpainted" is NOT is `class="undefined"`, and this file said it was in
// six places until 2026-08-13.** The substance was always right -- the class
// reaches no rule and the paint is silently gone -- but that spelling names
// something neither environment produces. Stated once, here, from measurement:
//
//   * Under this suite the proxy returns a scoped string built from whatever key
//     it is handed. Measured: `styles.fieldCellTYPO` is the string
//     `"_fieldCellTYPO_18fbc4"`, so the element renders
//     `class="_fieldCellTYPO_18fbc4"` -- a plausible-looking name that no
//     stylesheet declares.
//   * In a real build the object is the compiled stylesheet's exports and has no
//     such key at all, so the value is `undefined` -- and React omits a
//     `className` of `undefined` rather than stringifying it. Measured:
//     `<div className={undefined}>` renders with no `class` attribute at all.
//   * Only `String(undefined)` produces the literal `class="undefined"`.
//
// The other sites in this file now say "unpainted", which is the true and
// mechanism-free half, so there is one copy of the mechanism to keep right
// rather than six. As of 2026-08-13 the same wrong spelling also stands in
// `admin-screen.test.tsx`, `review-null-rule.test.tsx` (twice) and
// `theme-control.test.tsx`, which were outside the permitted set of the round
// that corrected it here.
//
// So: read both sides as text and check they agree, the way `tokens.test.ts`
// reads the stylesheet rather than trusting prose. Reading the *component* as
// well as the stylesheet is what makes this bidirectional -- a rename in the CSS
// alone leaves a reference with no declaration, and a rename in the TSX alone
// does the same, and both are the failure being pinned.
// --------------------------------------------------------------------------- //

/** `dirname(fileURLToPath(import.meta.url))` rather than
 *  `new URL(specifier, import.meta.url)`.
 *
 *  Measured, and the reason this test can live in a jsdom file at all: it is the
 *  `new URL(...)` *pattern* that Vite rewrites into a static-asset URL, which
 *  jsdom then resolves against the document base so `readFileSync` is handed an
 *  `http://` URL and dies with `TypeError: The URL must be of scheme file`.
 *  `import.meta.url` on its own is a `file://` URL under both environments --
 *  `tokens.test.ts:1-12` states exactly this, and it is the reason that file
 *  pins its environment to node while this one does not. (The older docblock on
 *  `no-float-in-money-path.test.ts` blames `import.meta.url` itself; that
 *  attribution is wrong, and this file running green under jsdom is the
 *  measurement.)
 *
 *  **And do not name the environment pragma in this file, even in prose.** The
 *  first version of this comment quoted it verbatim; Vitest matches that string
 *  anywhere in the source, so the whole file silently switched to the node
 *  environment and all eleven rendering tests died on
 *  `ReferenceError: document is not defined`. Prose answering for code, in a
 *  comment about prose answering for code. */
const SRC = join(dirname(fileURLToPath(import.meta.url)), '..', 'src')

/** Reading a path that no longer exists otherwise fails with a bare `ENOENT`,
 *  which does not say that a *guard* went blind or what to do about it. The
 *  guard reaches outside `src/ui` into `review/MoneyInput.*`, so a rename over
 *  there lands here. */
const read = (relative: string): string => {
  try {
    return readFileSync(join(SRC, relative), 'utf8')
  } catch (cause) {
    throw new Error(
      `the class guard cannot read src/${relative}. If that file moved or was ` +
        `renamed, update COMPONENTS -- this guard is not optional cover.`,
      { cause },
    )
  }
}

/** The class selectors a stylesheet declares.
 *
 *  Comments are stripped first, and that is not optional: `tokens.test.ts:19-27`
 *  records a review round where `indexOf` matched the *comment* above a rule and
 *  left the rule's deletion green. Every stylesheet here is heavily commented,
 *  and `Value.module.css`'s own comment names `.notExtracted`. Prose must not be
 *  allowed to answer for code.
 *
 *  The leading `[A-Za-z]` is what keeps `rgba(0,0,0,.05)`, `1.5` and `0.5rem`
 *  out of the set -- a CSS class cannot begin with a digit. */
function declaredClasses(css: string): Set<string> {
  const code = css.replace(/\/\*[\s\S]*?\*\//g, '')
  return new Set(Array.from(code.matchAll(/\.([A-Za-z][\w-]*)/g), (match) => match[1]))
}

/** The `styles.NAME` references a component makes.
 *
 *  Block comments are stripped for the same reason as above; this codebase
 *  documents in JSDoc, so that covers every docblock. A `//` line comment naming
 *  a `styles.x` that does not exist would produce a false failure here -- loud
 *  and one edit away from fixed, which is the right way round. Stripping `//`
 *  properly would need the TypeScript lexer, for the reasons
 *  `no-float-in-money-path.test.ts` spends forty lines on. */
function referencedClasses(tsx: string): Set<string> {
  const code = tsx.replace(/\/\*[\s\S]*?\*\//g, '')
  return new Set(Array.from(code.matchAll(/\bstyles\.([A-Za-z]\w*)/g), (match) => match[1]))
}

/** Whether the occurrence of `selector` at `at` is the *whole* selector rather
 *  than a fragment of a longer one -- both edges, per `declarationsIn`'s
 *  guarantee.
 *
 *  The leading edge walks back over whitespace and requires `}`, `,` or
 *  start-of-input: the end of the previous rule, the previous member of a comma
 *  list, and the top of the file. Anything else -- a class, a tag, `>`, `]` --
 *  means this occurrence is qualified by something, and a qualified selector does
 *  not match the element the component actually renders.
 *
 *  The trailing edge is its mirror: walk forward over whitespace and require `{`
 *  or `,`, so the selector *ends* where this occurrence ends. **Requiring merely
 *  that whitespace follow is not enough, and that was a live defect until
 *  2026-08-13.** `.form` and `.form > h2` are two different selectors, and the
 *  space after `.form` satisfied a bare `[\s{,]` test on its own -- so the second
 *  rule counted as an occurrence of the first and `declarationsIn` threw
 *  `2 top-level rules for .form` against a file that declares it exactly once.
 *  It went unseen because no stylesheet in `COMPONENTS` used a descendant or
 *  child combinator at all until `ReceiptForm.module.css` joined; it fired the
 *  moment that entry was added, which is how it was found. The fix is a
 *  tightening: every shape that passed before still passes, and one that never
 *  should have no longer does.
 *
 *  Those three are not everything that can *legally* precede a selector: a `;`
 *  can, after a statement at-rule such as `@import` or `@charset`. That is
 *  deliberately not accepted. It makes a stylesheet with a leading `@import`
 *  throw here rather than pass, which is loud and one edit from fixed, and is the
 *  ruling recorded in `declarationsIn`'s bound rather than a case to chase.
 *
 *  Provenance, stated honestly and narrowly, because the first version of this
 *  note overstated it: **no class selector in the tracked CSS files is
 *  qualified by another class, a tag or an attribute, and none is a descendant or
 *  child of one** -- verified by grep, and that is the shape the leading edge
 *  rejects. One of them now IS the left-hand side of a child combinator
 *  (`.form > h2`), which is the shape the trailing edge rejects. Neither is
 *  claimed from prose: `accepts every shape the real stylesheets actually use`
 *  runs `declarationsIn` over every declared class in every tracked file, so a
 *  stylesheet that breaks either edge fails rather than being trusted.
 *  Compound selectors as such certainly do exist here
 *  (`.button:hover:not(:disabled)`, `:root[data-theme='dark']`,
 *  `:where(...):focus-visible`), so "no compound selector anywhere" would have
 *  been simply false. Unlike the at-rule and pseudo-class shapes, then, this edge
 *  is closed on the strength of the property rather than of an observed pattern. */
function exactlyThisSelector(code: string, at: number, selector: string): boolean {
  if (!/[\s{,]/.test(code[at + selector.length] ?? '')) {
    return false
  }
  let forward = at + selector.length
  while (forward < code.length && /\s/.test(code[forward] ?? '')) {
    forward += 1
  }
  if (code[forward] !== '{' && code[forward] !== ',') {
    return false
  }
  let back = at - 1
  while (back >= 0 && /\s/.test(code[back] ?? '')) {
    back -= 1
  }
  return back < 0 || code[back] === '}' || code[back] === ','
}

/** The declarations of one rule, as (property, value) pairs.
 *
 *  **Substring checks on a rule body do not work, and this is the third time in
 *  this milestone that has been proved.** Task 1 had `--color-surface-raised`
 *  satisfying `toContain('--color-surface')`; round 1 of this task shipped
 *  `expect(body).toContain('var(--color-null)')`, which the *border* declaration
 *  satisfies -- so deleting `color: var(--color-null)` outright, the headline
 *  visual signal of §4, left all seventeen tests green. Measured before this fix
 *  landed, not argued.
 *
 *  Choosing a better needle (`'color: var(--color-null)'`) would have closed that
 *  instance and left the shape. Splitting the body into declarations closes it on
 *  the **value axis**: a property is looked up as a property and compared to a
 *  whole value, so no declaration can answer for another.
 *
 *  ## The guarantee, stated once and bounded
 *
 *  **This function returns the declarations of the unique top-level rule whose
 *  selector is *exactly* `selector`, and throws otherwise.** That is the whole
 *  claim. It is a property, not a list of defeated shapes.
 *
 *  Stating it that way is the actual fix here, and it took three rounds to
 *  arrive at. Round 1 anchored nothing and `border-left` answered for `color`.
 *  Round 2 anchored inside the body and `@media`, `:hover` and a longer class
 *  name answered for the rule. Round 3 anchored the selector's trailing edge and
 *  `.numeric.notExtracted` answered for it. Each round closed the shapes that had
 *  been found and then re-asserted that the whole class was closed; each was
 *  falsified by the next shape. **The recurring defect was the claim, not the
 *  code.** So the docblock now claims exactly what is enforced, and the shapes
 *  live in the tests as examples rather than here as a guarantee.
 *
 *  Exactness is enforced on four fronts, which is what "exactly, uniquely,
 *  top-level" decomposes into:
 *
 *    * a **leading** boundary -- walking back over whitespace, the previous
 *      non-space character must be `}` or `,` or start-of-input, so a qualifier
 *      in front (`.numeric.notExtracted`, `.numeric .notExtracted`,
 *      `.numeric > .notExtracted`, `span.notExtracted`, `[data-x].notExtracted`)
 *      is a different selector and not this one;
 *    * a **trailing** boundary (`[\s{,]`), so `.notExtractedInline` and
 *      `.notExtracted:hover` are not it either;
 *    * **brace depth 0**, so a copy nested in an at-rule is not it. The
 *      boundaries alone do not cover this -- `.notExtracted ` inside `@media`
 *      satisfies both perfectly well;
 *    * **uniqueness**, because two top-level rules for one selector leave
 *      nothing to say which paints the mark.
 *
 *  Absence **throws** rather than returning an empty map. `indexOf` returning -1
 *  fed `code.indexOf('{', -1)`, which clamps to 0 and silently read the *first
 *  rule in the file* -- against the real stylesheet that is `.numeric`, which
 *  carries `font-family: var(--font-mono)`, so the font assertion would have gone
 *  green against an unrelated rule.
 *
 *  What this is **not**: a CSS parser. The guarantee above is about locating a
 *  rule, and it says nothing about parsing one. Reading the body assumes rules do
 *  not nest inside a top-level rule and that values carry no braces or
 *  semicolons. That holds for the tracked stylesheets and is not claimed beyond
 *  them.
 *
 *  **And the property itself is bounded to stylesheets of the shape the tracked
 *  ones have: no functional selector lists and no statement at-rules.** Inside
 *  `:is(...)` or `:where(...)` a selector is read imprecisely, and a leading
 *  `@import` makes the lookup throw with a message that misdescribes the cause.
 *  Both are ruled parked rather than pursued -- the first is harmless (the rule
 *  still paints the mark) and the second is loud and safe -- and chasing them
 *  would be three more enumerated instances of the very defect this docblock was
 *  rewritten to stop committing.
 *
 *  First colon wins, which is right for these values -- none contains a colon,
 *  and `var(--x)` does not. */
function declarationsIn(css: string, selector: string): Map<string, string> {
  const code = css.replace(/\/\*[\s\S]*?\*\//g, '')
  const starts: number[] = []
  let depth = 0
  for (let i = 0; i < code.length; i += 1) {
    if (code[i] === '{') {
      depth += 1
    } else if (code[i] === '}') {
      depth -= 1
    } else if (depth === 0 && code.startsWith(selector, i) && exactlyThisSelector(code, i, selector)) {
      starts.push(i)
    }
  }
  if (starts.length !== 1) {
    throw new Error(
      starts.length === 0
        ? `no top-level rule whose selector is exactly ${selector}. It was ` +
          `renamed, or it gained a qualifier (${selector} is not ` +
          `.x${selector}), or it moved inside an at-rule -- and the element the ` +
          `component renders carries ${selector} alone, so none of those paint ` +
          `it. This guard is reading nothing and must not silently pass.`
        : `${starts.length} top-level rules for ${selector}; the guard cannot ` +
          `tell which one paints it. Fold them into one.`,
    )
  }
  const open = code.indexOf('{', starts[0])
  const pairs = new Map<string, string>()
  for (const part of code.slice(open + 1, code.indexOf('}', open)).split(';')) {
    const colon = part.indexOf(':')
    if (colon !== -1) {
      pairs.set(part.slice(0, colon).trim(), part.slice(colon + 1).trim())
    }
  }
  return pairs
}

/** The string-literal union assigned to `prop` in a component's source.
 *
 *  This is what makes the `computed` lists below more than documentation. Round
 *  1's docblock claimed they "mirror the union type verbatim, so a tone or
 *  variant added to the type without a rule to paint it fails here" -- and the
 *  re-reviewer disproved it by adding `'critical'` to Chip's union, seeing every
 *  gate stay green, and watching `styles[tone]` ship unpainted. The
 *  hand-maintained list caught a *deleted* rule and nothing else.
 *
 *  Deriving the same set from the component and requiring the two to agree makes
 *  the claim true: a new union member fails until it is both listed here and
 *  painted in the stylesheet.
 *
 *  A union reformatted one-member-per-line would not match this pattern at all.
 *  That fails loudly rather than vacuously -- the derived set is empty, and the
 *  equality assertion reports the mismatch instead of quietly checking nothing.
 *
 *  **Silent truncation is the harder failure, and it re-achieves the exact defect
 *  this helper exists to close.** The chain is greedy but stops at the first
 *  member it cannot chain, so if it stops precisely where the hand-maintained
 *  list ends, the guard is green while the extra tone ships unpainted -- G4 all
 *  over again with `derived.length === 5`. Three spellings do it:
 *  `| "critical"` (double quotes -- and quote style is unenforced, there is no
 *  formatter config in the tracked tree), `| LegacyTones` (a member that is a
 *  type alias, not a literal), and a `//` comment inside the union followed by
 *  `| 'critical'`.
 *
 *  So the match must consume the whole annotation: if the next thing after it is
 *  another `|`, the union continued and this parse is a lie.
 *
 *  **Line comments are stripped before the match, not merely skipped after it.**
 *  Round 3 did only the latter and left the leftmost-`exec` door open: a
 *  `// tone: 'error' | ... | 'neutral'` line *above* a union genuinely extended
 *  with `| 'critical'` wins the match, and the tail check then sees `\n  tone:`
 *  rather than `|` and stays quiet -- five stale members, agreeing with the
 *  hand-maintained list, green, with `.critical` shipping unpainted.
 *  G4 through the door round 3's own docblock called closed. Not live today (no
 *  `//` comment in `frontend/src` mentions `tone:` or `variant:`), and closed
 *  anyway, because round 3's stated reasoning already argued for it.
 *
 *  Note the direction, which is why this differs from `referencedClasses`. There,
 *  block-comments-only leaves a residue that causes a *false failure* -- loud,
 *  one edit from fixed. Here the identical gap causes a *false pass*. Same gap,
 *  opposite consequence, opposite call.
 *
 *  Stripping `//` over the whole file is safe for *this* helper, but not for the
 *  reason the first version of this note gave. It claimed "the pattern cannot
 *  span a newline", which is false -- `\s*` matches newlines, and the assertion
 *  that a comment inside a union is now parsed through depends on exactly that.
 *  The real reason is that **the strip preserves the newline**: `[^\n]*` stops
 *  before it, so no two lines are ever joined, and within a line a comment runs
 *  to the end, so there is no code after it to join to. Removal alone cannot
 *  manufacture a match that the code did not already contain. */
function unionMembers(source: string, prop: string): string[] {
  const code = source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '')
  const union = new RegExp(`\\b${prop}\\??:\\s*((?:'[\\w-]+'\\s*\\|\\s*)*'[\\w-]+')`).exec(code)
  if (union === null) {
    return []
  }
  const rest = code.slice(union.index + union[0].length)
  if (/^(?:\s|\/\/[^\n]*)*\|/.test(rest)) {
    throw new Error(
      `the ${prop} union continues past what this parse read, so the derived set ` +
        `is a truncation and would silently agree with a stale list. Extend ` +
        `unionMembers to cover the spelling that stopped it.`,
    )
  }
  return Array.from(union[1].matchAll(/'([\w-]+)'/g), (m) => m[1])
}

interface GuardedComponent {
  readonly name: string
  readonly tsx: string
  readonly css: string
  /** The prop whose string-literal union names classes reached as `styles[x]`,
   *  or `''` when the component reaches none that way. */
  readonly prop: string
  readonly computed: readonly string[]
}

/** `computed` holds the classes reached as `styles[union]`, which no regex over
 *  the component can see. `prop` is what lets the guard derive that same list
 *  from the source rather than trust it -- see `unionMembers`. */
const COMPONENTS: readonly GuardedComponent[] = [
  { name: 'Value', tsx: 'ui/Value.tsx', css: 'ui/Value.module.css', prop: '', computed: [] },
  {
    name: 'Button',
    tsx: 'ui/Button.tsx',
    css: 'ui/Button.module.css',
    prop: 'variant',
    computed: ['primary', 'secondary', 'danger'],
  },
  {
    name: 'Chip',
    tsx: 'ui/Chip.tsx',
    css: 'ui/Chip.module.css',
    prop: 'tone',
    computed: ['error', 'warn', 'info', 'positive', 'neutral'],
  },
  {
    name: 'MoneyInput',
    tsx: 'review/MoneyInput.tsx',
    css: 'review/MoneyInput.module.css',
    prop: '',
    computed: [],
  },
  // Added 2026-08-06, after the browser pass. The login page got its first
  // stylesheet in that round and arrived unguarded: the fix round could not add
  // itself here, because this file was outside its permitted set. Under
  // `css: false` a renamed class ships unpainted with all five gates green, and
  // the fix round proved exactly that by hand -- renaming `.form` made the card,
  // its border and its centring vanish silently. It is the first screen every
  // reviewer sees, so it is the worst one to leave to a hand check nobody will
  // repeat.
  {
    name: 'LoginPage',
    tsx: 'login/LoginPage.tsx',
    css: 'login/LoginPage.module.css',
    prop: '',
    computed: [],
  },
  // Added 2026-08-13, by controller ruling, for the same reason as LoginPage
  // above and found the same way. Task 1 of the I6/I8/I9 pass added `.fieldCell`
  // -- the whole of that task's deliverable -- and it was reachable by no guard
  // at all: `stylesheets.test.ts` audits what a stylesheet DECLARES and never
  // asks whether anything applies it. Measured before this entry existed:
  // renaming the reference to `styles.fieldCellTYPO` in `ReceiptForm.tsx` left
  // all 373 tests and `tsc -b` green, so every declaration in the `.fieldCell`
  // rule painted nothing and no gate said so.
  //
  // This entry covers every class the component declares, not just that one.
  // `.form` is the one with the most to lose -- it carries the grid itself.
  {
    name: 'ReceiptForm',
    tsx: 'review/ReceiptForm.tsx',
    css: 'review/ReceiptForm.module.css',
    prop: '',
    computed: [],
  },
]

describe('every class a component references exists in its stylesheet', () => {
  it('is reading real files, not empty ones', () => {
    // The whole guard is a silence check, so its silence has to mean something.
    for (const component of COMPONENTS) {
      expect(read(component.css).length, `${component.css} is empty`).toBeGreaterThan(100)
      expect(read(component.tsx).length, `${component.tsx} is empty`).toBeGreaterThan(100)
    }
  })

  it('extracts classes from both sides, and is not fooled by comments', () => {
    // Positive controls. A `declaredClasses` that returned everything, or a
    // `referencedClasses` that returned nothing, would make the guard below pass
    // for the wrong reason.
    expect(declaredClasses('.real { color: red }').has('real')).toBe(true)
    expect(declaredClasses('.real { color: red }').has('absent')).toBe(false)
    expect(declaredClasses('/* .ghost {} */ .real {}').has('ghost')).toBe(false)
    expect(declaredClasses('a { box-shadow: 0 1px 2px rgba(0,0,0,.05) }').has('05')).toBe(false)
    expect(referencedClasses('x = styles.real').has('real')).toBe(true)
    expect(referencedClasses('/** styles.ghost */ x = styles.real').has('ghost')).toBe(false)
  })

  it('finds every reference declared', () => {
    for (const component of COMPONENTS) {
      const declared = declaredClasses(read(component.css))
      const referenced = referencedClasses(read(component.tsx))

      // Anti-vacuity per component: an extraction that silently stopped matching
      // would make this component's row pass with an empty set.
      expect(referenced.size, `${component.tsx} references no styles.*`).toBeGreaterThan(0)
      expect(declared.size, `${component.css} declares no classes`).toBeGreaterThan(0)

      for (const name of [...referenced, ...component.computed]) {
        expect(
          declared.has(name),
          `${component.name}: ${component.tsx} uses styles.${name} but ` +
            `${component.css} declares no .${name} -- under css:false that ships ` +
            `unpainted with every gate green`,
        ).toBe(true)
      }
    }
  })

  // ------------------------------------------------------------------------ //
  // The ruling this test records, because the ledger it was parked in does not
  // survive the merge.
  //
  // Task 2's round 5 parked an item: the guard should gain the other direction,
  // `declared` subset of `referenced`, and it "would pass as-is, 18 declared
  // classes, all referenced today". **That form is wrong and the count had
  // rotted.** Measured at the time of writing: of the classes declared across
  // the components in `COMPONENTS`, the unreferenced ones are Button's `danger`,
  // `primary` and `secondary`, and Chip's `error`, `info`, `neutral`, `positive`
  // and `warn`. They are not orphans. `Button.tsx` applies `styles[variant]` and
  // `Chip.tsx` applies `styles[tone]`, and `referencedClasses` matches
  // `styles.NAME` only, so dynamic indexing is invisible to it by construction.
  // That is what the `computed` field on each entry above is for, and it is
  // already derived from the component's own union type by `unionMembers`.
  //
  // So the correct form is `declared` subset of (`referenced` union `computed`),
  // which holds. The "18" was true at e216af4 and rotted by six when
  // LoginPage.module.css was added.
  //
  // What it buys, and it is not symmetry for its own sake: the guard's other
  // direction cannot see a rule that nothing paints. A class renamed in the CSS
  // *and* in the TSX passes both directions; a class renamed in the CSS alone
  // fails the other direction; a class left behind in the CSS when its reference
  // is deleted fails only this one. `stylesheets.test.ts` audits declarations
  // without asking whether anything reaches them, so this is the only check in
  // the tree that says a rule in a guarded component is dead.
  //
  // The bound: it covers the components in COMPONENTS and nothing else.
  // `LineItemsTable.module.css`'s `.rowActive` is declared and referenced by
  // nothing today -- deliberately, per its own comment -- and would fail this if
  // that file were guarded here.
  // ------------------------------------------------------------------------ //
  it('declares no class that nothing reaches, so a rule cannot be left dead', () => {
    for (const component of COMPONENTS) {
      const declared = declaredClasses(read(component.css))
      const reached = new Set([
        ...referencedClasses(read(component.tsx)),
        ...component.computed,
      ])
      for (const name of declared) {
        expect(
          reached.has(name),
          `${component.name}: ${component.css} declares .${name} but ${component.tsx} ` +
            `neither writes styles.${name} nor reaches it through the guard's ` +
            `computed list -- so nothing paints with it and the rule is dead. If it ` +
            `is reached dynamically, add it to computed (and to the union the ` +
            `component indexes, which is what unionMembers checks it against).`,
        ).toBe(true)
      }
    }
  })

  it('still names the classes §4 depends on, so the mark keeps its colour and border', () => {
    // The three above are structural: they check the two sides agree. This one
    // checks *what* they agree on, so renaming `.notExtracted` consistently on
    // both sides still has to be a deliberate edit here.
    const value = declaredClasses(read('ui/Value.module.css'))
    expect(value.has('notExtracted')).toBe(true)
    expect(value.has('numeric')).toBe(true)
    expect(value.has('text')).toBe(true)

    // ...and the component still *applies* the mark's class. The guard's main
    // check is `referenced` subset of `declared`, and a subset check cannot see a
    // reference being DELETED: dropping `className={styles.notExtracted}` leaves
    // one fewer reference, which is still a subset, so the guard stays green --
    // and every rendering test stays green too, because they read textContent,
    // role and accessible name, none of which a class affects. Measured: the
    // whole suite passes with §4's paint entirely gone.
    //
    // This is the class §4's visual half depends on, so it gets the symmetric
    // assertion. Non-vacuous for the same reason as its `declaredClasses`
    // neighbour above -- it reads source text, not the `css: false` proxy.
    expect(
      referencedClasses(read('ui/Value.tsx')).has('notExtracted'),
      'Value.tsx no longer applies the not-extracted class; the mark has no paint',
    ).toBe(true)
  })

  it('separates declarations, so no one of them can answer for another', () => {
    // The positive control for `declarationsIn`, and specifically for the defect
    // it replaces: with ONLY the border present, `color` must come back
    // undefined. The substring version returned a hit here, which is exactly how
    // the mark's colour became deletable with every gate green.
    const bitten = declarationsIn('.x { border-left: 2px solid var(--t) }', '.x')
    expect(bitten.get('border-left')).toBe('2px solid var(--t)')
    expect(bitten.get('color')).toBeUndefined()

    const full = declarationsIn('.x { color: red; border-left: 2px solid red }', '.x')
    expect(full.get('color')).toBe('red')
    expect(full.get('border-left')).toBe('2px solid red')
    expect(full.get('padding')).toBeUndefined()
  })

  it('locates the rule by selector, not by substring', () => {
    // The three shapes that satisfied every §4 assertion while the real rule
    // carried none of them. Each declares the paint on a *different* selector
    // above the gutted base rule, so a helper that reads the first textual hit
    // reports the decoy's declarations.
    const gutted = '.notExtracted { padding-left: 4px }'
    const paint = 'color: var(--color-null)'

    for (const [label, decoy] of [
      ['a longer class name', `.notExtractedInline { ${paint} }`],
      ['an at-rule copy', `@media (prefers-contrast: more) { .notExtracted { ${paint} } }`],
      ['a pseudo-class', `.notExtracted:hover { ${paint} }`],
    ] as const) {
      const found = declarationsIn(`${decoy}\n${gutted}`, '.notExtracted')
      expect(found.get('padding-left'), `${label}: read the decoy, not the rule`).toBe('4px')
      expect(found.get('color'), `${label}: the decoy's paint answered for the rule`).toBeUndefined()
    }
  })

  it('reads the selector exactly, so a qualifier in front is a different rule', () => {
    // The leading edge. Round 3 anchored only the trailing one, so anything
    // *prefixed* to the selector still matched -- and unlike the hoist shapes,
    // these need no second rule: replacing `.notExtracted {` with
    // `.numeric.notExtracted {` leaves all three §4 declarations asserted while
    // the mark, which renders with `.notExtracted` alone, gets no paint at all.
    const paint = 'color: var(--color-null)'
    const gutted = '.notExtracted { padding-left: 4px }'

    for (const [label, qualified] of [
      ['a compound class', '.numeric.notExtracted'],
      ['a descendant', '.numeric .notExtracted'],
      ['a child combinator', '.numeric > .notExtracted'],
      ['a tag qualifier', 'span.notExtracted'],
      ['an attribute qualifier', '[data-x].notExtracted'],
    ] as const) {
      // Alone, a qualified selector is not this selector at all.
      expect(
        () => declarationsIn(`${qualified} { ${paint} }`, '.notExtracted'),
        `${label}: answered for the unqualified rule`,
      ).toThrow(/no top-level rule whose selector is exactly/)

      // ...and beside the real rule, it is the real one that is read.
      const found = declarationsIn(`${qualified} { ${paint} }\n${gutted}`, '.notExtracted')
      expect(found.get('padding-left'), `${label}: read the decoy`).toBe('4px')
      expect(found.get('color'), `${label}: the decoy's paint answered`).toBeUndefined()
    }
  })

  it('reads the selector exactly, so a combinator after it is a different rule', () => {
    // The trailing edge's other half, and the shape `ReceiptForm.module.css`
    // brought in when it joined COMPONENTS on 2026-08-13. `.form` and
    // `.form > h2` are two different selectors; the edge used to require only
    // that *some* whitespace follow the name, which `.form > h2` satisfies, so
    // the file's one `.form` rule read as two and the guard threw instead of
    // guarding. Not hypothetical -- it fired on the real file the moment the
    // entry was added.
    const paint = 'color: var(--color-null)'
    for (const [label, qualified] of [
      ['a child combinator', '.form > h2'],
      ['a descendant', '.form h2'],
    ] as const) {
      expect(
        () => declarationsIn(`${qualified} { ${paint} }`, '.form'),
        `${label}: answered for the unqualified rule`,
      ).toThrow(/no top-level rule whose selector is exactly/)
    }

    // ...and beside the real rule it is the real one that is read, exactly once,
    // which is the case the stylesheet actually presents.
    const both = '.form { display: grid }\n.form > h2 { grid-column: 1 / -1 }'
    expect(declarationsIn(both, '.form').get('display')).toBe('grid')
    expect(declarationsIn(both, '.form').get('grid-column')).toBeUndefined()
  })

  it('accepts every shape the real stylesheets actually use', () => {
    // The other half of the leading edge: it must not reject legitimate CSS. The
    // three things that can precede a complete top-level selector are the top of
    // the file, the previous rule's `}`, and a comma.
    expect(declarationsIn('.first { color: red }', '.first').get('color')).toBe('red')
    expect(declarationsIn('.a { color: red }\n.b { color: blue }', '.b').get('color')).toBe('blue')
    expect(declarationsIn('.a,\n.b { color: red }', '.b').get('color')).toBe('red')
    // And the real files, which is the case that actually matters.
    for (const component of COMPONENTS) {
      const css = read(component.css)
      for (const name of declaredClasses(css)) {
        expect(
          () => declarationsIn(css, `.${name}`),
          `${component.css}: .${name} is declared but not locatable`,
        ).not.toThrow()
      }
    }
  })

  it('throws rather than reading the wrong rule when the selector is not there', () => {
    // `indexOf` returned -1, and `indexOf('{', -1)` clamps to 0 -- so the helper
    // silently read the FIRST rule in the file. Against the real stylesheet that
    // is `.numeric`, which carries `font-family: var(--font-mono)`, so the font
    // assertion would have passed against an unrelated rule while the message
    // blamed the colour.
    expect(() => declarationsIn('.numeric { font-family: var(--font-mono) }', '.gone')).toThrow(
      /no top-level rule whose selector is exactly/,
    )
    // Two top-level rules for one selector leave nothing to say which paints it.
    expect(() => declarationsIn('.x { color: red }\n.x { color: blue }', '.x')).toThrow(
      /2 top-level rules/,
    )
  })

  it('rejects a truncated union instead of agreeing with a stale list', () => {
    // Each of these stops the greedy chain exactly at five members, which is the
    // length of Chip's hand-maintained list -- so without this check the guard is
    // green while the sixth tone ships unpainted. G4 re-achieved.
    const five = "tone: 'error' | 'warn' | 'info' | 'positive' | 'neutral'"
    expect(unionMembers(five, 'tone')).toEqual(['error', 'warn', 'info', 'positive', 'neutral'])

    for (const [label, tail] of [
      ['a double-quoted member', ' | "critical"'],
      ['a type alias member', ' | LegacyTones'],
    ] as const) {
      expect(() => unionMembers(five + tail, 'tone'), label).toThrow(/continues past/)
    }

    // A line comment *inside* the union was a third truncation spelling in round
    // 3, which skipped comments only in the tail check. Stripping them before the
    // match subsumes it: the union now parses in full rather than being rejected,
    // which is the better outcome -- six members derived, and the equality check
    // against the hand-maintained five is what reds.
    expect(unionMembers(`${five}\n  // and one more\n  | 'critical'`, 'tone')).toEqual([
      'error',
      'warn',
      'info',
      'positive',
      'neutral',
      'critical',
    ])
  })

  it('is not diverted by a line comment that looks like the union', () => {
    // The leftmost-`exec` door. A commented-out copy of the OLD union above the
    // real, extended one wins the match; the tail check then sees `tone:` rather
    // than `|` and stays quiet, so five stale members agree with the list and the
    // sixth tone ships unpainted. Stripping `//` before the match is what closes
    // it -- skipping comments only in the tail check does not.
    const decoyed =
      `  // ${"tone: 'error' | 'warn' | 'info' | 'positive' | 'neutral'"}\n` +
      `  tone: 'error' | 'warn' | 'info' | 'positive' | 'neutral' | 'critical'\n`
    // Round 3 derived the decoy's five stale members here, which matched the
    // hand-maintained list and went green. It now reads the real union, so
    // `critical` is in the derived set and the equality check reds.
    expect(unionMembers(decoyed, 'tone')).toContain('critical')
    expect(unionMembers(decoyed, 'tone')).toHaveLength(6)

    // ...and the same decoy above an unextended union still reads the real one
    // rather than the comment's invented members.
    const honest = `  // ${"tone: 'stale' | 'members'"}\n  tone: 'error' | 'warn'\n`
    expect(unionMembers(honest, 'tone')).toEqual(['error', 'warn'])
  })

  it('gives the not-extracted mark all three signals §4 names for it', () => {
    // Every one of these is compared as a whole value against a named property,
    // so each is falsified only by its own declaration changing. Reverted one at
    // a time, and each reds alone.
    const mark = declarationsIn(read('ui/Value.module.css'), '.notExtracted')
    expect(mark.get('color'), 'the mark lost its colour').toBe('var(--color-null)')
    expect(mark.get('border-left'), 'the mark lost the scannability border').toBe(
      '2px solid var(--color-null)',
    )
    // §4 names the monospaced family for the mark alongside the colour, and
    // round 1 asserted it nowhere at all.
    expect(mark.get('font-family'), 'the mark lost --font-mono').toBe('var(--font-mono)')
  })

  it('derives each computed list from its union, so a new tone cannot go unpainted', () => {
    // Round 1's docblock claimed the hand-maintained lists did this. They did
    // not: a union member added without a rule shipped unpainted with
    // every gate green. Deriving the set from the source is what makes the claim
    // true rather than narrowing it.
    const guarded = COMPONENTS.filter((entry) => entry.prop !== '')
    // The filter is an escape hatch: blanking `prop` on both entries would leave
    // this loop with zero iterations and no assertion executed, and the
    // anti-vacuity checks below are *inside* the loop, so they could not fire.
    expect(guarded.length, 'the derive-the-union loop has been emptied').toBe(2)
    for (const component of guarded) {
      const derived = unionMembers(read(component.tsx), component.prop)
      expect(
        derived.length,
        `${component.tsx}: could not read the ${component.prop} union -- if it was ` +
          `reformatted, unionMembers needs updating, because an empty set here ` +
          `would check nothing`,
      ).toBeGreaterThan(0)
      expect(
        [...derived].sort(),
        `${component.name}: the ${component.prop} union and the guard's computed ` +
          `list disagree -- a member added to one and not the other is unpainted`,
      ).toEqual([...component.computed].sort())
    }
  })
})

describe('Button', () => {
  // Re-measured in frontend/src on 2026-08-07, comments stripped: seventeen
  // buttons -- fifteen explicitly `type="button"`, one explicitly
  // `type="submit"` (LoginPage's, inside the app's only `<form>`), and `Button`'s
  // own element, which spells neither because it *is* the default. The earlier
  // "sixteen" omitted that last one while reading as a total.
  // The platform default is `submit`, so a primitive that did not
  // override it would post a half-keyed receipt the day anyone wraps the receipt
  // fields the way LoginPage already wraps its two.
  it('defaults to type="button" rather than the platform submit', () => {
    render(<Button variant="primary">Approve</Button>)
    expect(screen.getByRole('button', { name: 'Approve' }).getAttribute('type')).toBe('button')
  })

  it('forwards native button props', async () => {
    const onClick = vi.fn()
    render(
      <Button variant="danger" onClick={onClick}>
        Skip this receipt
      </Button>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Skip this receipt' }))
    expect(onClick).toHaveBeenCalledTimes(1)
  })
})
