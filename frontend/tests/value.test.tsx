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
 *  `.module.css` import is a proxy whose keys echo back as strings -- a class
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
// Vitest's default is `css: false`, so `styles.anything` echoes its own key back
// as a string. A class renamed on ONE side only -- which is exactly what this
// task did when it renamed `.null` to `.notExtracted` -- produces
// `class="undefined"` and ships with every gate green, taking `--color-null` and
// the hairline left border with it. Those are §4's scannability half, so losing
// them silently loses half the rule.
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
 *  instance and left the shape. Splitting the body into declarations closes the
 *  class: a property is looked up as a property and compared to a whole value,
 *  so no declaration can answer for another and no assertion here can be
 *  satisfied by a longer string that happens to contain it.
 *
 *  First colon wins, which is right for these values -- none contains a colon,
 *  and `var(--x)` does not. */
function declarationsIn(css: string, selector: string): Map<string, string> {
  const code = css.replace(/\/\*[\s\S]*?\*\//g, '')
  const open = code.indexOf('{', code.indexOf(selector))
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
 *  gate stay green, and watching `styles[tone]` ship `class="undefined"`. The
 *  hand-maintained list caught a *deleted* rule and nothing else.
 *
 *  Deriving the same set from the component and requiring the two to agree makes
 *  the claim true: a new union member fails until it is both listed here and
 *  painted in the stylesheet.
 *
 *  A union reformatted one-member-per-line would not match this pattern. That
 *  fails loudly rather than vacuously -- the derived set is empty, and the
 *  equality assertion reports the mismatch instead of quietly checking nothing. */
function unionMembers(source: string, prop: string): string[] {
  const code = source.replace(/\/\*[\s\S]*?\*\//g, '')
  const union = new RegExp(`\\b${prop}\\??:\\s*((?:'[\\w-]+'\\s*\\|\\s*)*'[\\w-]+')`).exec(code)
  return union === null ? [] : Array.from(union[1].matchAll(/'([\w-]+)'/g), (m) => m[1])
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
            `as class="undefined" with every gate green`,
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
    // not: a union member added without a rule shipped class="undefined" with
    // every gate green. Deriving the set from the source is what makes the claim
    // true rather than narrowing it.
    for (const component of COMPONENTS.filter((entry) => entry.prop !== '')) {
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
  // Measured in src/: sixteen buttons, fifteen explicitly `type="button"` and
  // one explicitly `type="submit"` -- LoginPage's, inside the app's only
  // `<form>`. The platform default is `submit`, so a primitive that did not
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
