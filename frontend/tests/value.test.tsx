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

const read = (relative: string): string => readFileSync(join(SRC, relative), 'utf8')

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

/** `computed` holds the classes reached as `styles[union]`, which no regex over
 *  the component can see. Each list mirrors that component's union type
 *  verbatim, so a tone or variant added to the type without a rule to paint it
 *  fails here. */
const COMPONENTS = [
  { name: 'Value', tsx: 'ui/Value.tsx', css: 'ui/Value.module.css', computed: [] },
  {
    name: 'Button',
    tsx: 'ui/Button.tsx',
    css: 'ui/Button.module.css',
    computed: ['primary', 'secondary', 'danger'],
  },
  {
    name: 'Chip',
    tsx: 'ui/Chip.tsx',
    css: 'ui/Chip.module.css',
    computed: ['error', 'warn', 'info', 'positive', 'neutral'],
  },
  {
    name: 'MoneyInput',
    tsx: 'review/MoneyInput.tsx',
    css: 'review/MoneyInput.module.css',
    computed: [],
  },
] as const

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

    // ...and that the mark's rule actually carries both signals §4 names.
    const css = read('ui/Value.module.css').replace(/\/\*[\s\S]*?\*\//g, '')
    const rule = css.slice(css.indexOf('.notExtracted'))
    const body = rule.slice(rule.indexOf('{'), rule.indexOf('}'))
    expect(body).toContain('var(--color-null)')
    expect(body).toContain('border-left')
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
