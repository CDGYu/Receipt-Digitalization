import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { ConfidenceRail } from '../src/review/ConfidenceRail'
import { FindingsPanel } from '../src/review/FindingsPanel'
import { ImagePane } from '../src/review/ImagePane'
import { LineItemsTable } from '../src/review/LineItemsTable'
import { ReceiptForm } from '../src/review/ReceiptForm'
import type { FieldMap } from '../src/review/patch'
import type { Finding, LineItem, Money } from '../src/api/types'

// `globals: true` is deliberately absent from vite.config.ts, so
// `@testing-library/react` never installs its auto-cleanup hook and every render
// here has to be unmounted by this file.
afterEach(cleanup)

/** Design section 4's mark, byte for byte: U+2014 EM DASH, not a hyphen and not
 *  an en dash. Spelled once so a test cannot pass against a different glyph than
 *  the one the components render. */
const MARK = '—'

/** Everything a browser will let a reviewer type into, enumerated **from the
 *  DOM** rather than from a list anyone typed out.
 *
 * This is the shape the pin needs. Four consecutive fix rounds on this branch
 * were lost to hand-picked assertions (review standard 19: an enumerated defence
 * never converges), so the property below is stated once and quantified over
 * whatever is actually rendered -- a ninth text field is covered the day it is
 * added, and a second checkbox is excluded the same day, with no edit here.
 */
function controlsIn(container: HTMLElement): HTMLElement[] {
  return [...container.querySelectorAll<HTMLElement>('input, select, textarea')]
}

/** The input types that honour `placeholder` at all, per the HTML standard's
 *  "the placeholder attribute applies" table, plus `<textarea>`.
 *
 * The two exclusions design section 4 needs are *derived from the element*, not
 * matched by label: a `<select>` bound to a closed option list has no empty
 * state, and `<input type="checkbox">` has no third state
 * (`ReceiptForm.tsx:234-245` records both, and why). Neither honours
 * `placeholder`, so neither can carry the mark, and both fall out of this
 * predicate without being named.
 *
 * `type="number"` is in the standard's list and is kept here for the same
 * reason: this predicate describes HTML, not this app. ADR-0015 bans the number
 * input on money, and `tests/no-float-in-money-path.test.ts` is what enforces
 * that -- if one ever appeared, it would be caught there and *also* be required
 * to carry the mark here.
 */
const PLACEHOLDER_TYPES: ReadonlySet<string> = new Set([
  'text',
  'search',
  'url',
  'tel',
  'email',
  'password',
  'number',
])

function honoursPlaceholder(control: HTMLElement): boolean {
  if (control instanceof HTMLTextAreaElement) return true
  if (control instanceof HTMLInputElement) return PLACEHOLDER_TYPES.has(control.type)
  return false
}

/** What a control is, in words, so a failure names the defect instead of
 *  reporting `expected [ {} ] to equal []`.
 *
 * The wrapping label's own text nodes, not its `textContent`: a `<select>`'s
 * options are inside the label too, so the subtree reads
 * `Legibilitygoodfairpoorunreadable` (measured). */
function labelTextOf(control: HTMLElement): string | undefined {
  const label = control.closest('label')
  if (label === null) return undefined
  return [...label.childNodes]
    .filter((node) => node.nodeType === node.TEXT_NODE)
    .map((node) => node.textContent ?? '')
    .join('')
    .trim()
}

function describeControl(control: HTMLElement): string {
  const name =
    control.getAttribute('aria-label') ??
    labelTextOf(control) ??
    control.getAttribute('id') ??
    '(unnamed)'
  const kind =
    control instanceof HTMLInputElement ? `input[type=${control.type}]` : control.tagName.toLowerCase()
  return `${kind} ${name}`
}

/** Every control that honours `placeholder` but does not carry the mark. */
function unmarked(container: HTMLElement): string[] {
  return controlsIn(container)
    .filter(honoursPlaceholder)
    .filter((control) => control.getAttribute('placeholder') !== MARK)
    .map(describeControl)
}

/** The controls this pin deliberately does not cover, so the *reason* each was
 *  skipped is asserted rather than assumed. Without this, switching a text field
 *  to `type="date"` would drop it silently out of `honoursPlaceholder` and the
 *  universal assertion above would go on passing over a smaller set. */
function cannotCarryAMark(container: HTMLElement): string[] {
  return controlsIn(container)
    .filter((control) => !honoursPlaceholder(control))
    .map(describeControl)
}

const ITEMS: LineItem[] = [
  {
    position: 0,
    description_raw: 'DIESEL',
    sku: 'D-1',
    qty: '9.800' as Money,
    unit: 'L',
    unit_price: '102.04' as Money,
    line_total: '1000.00' as Money,
    is_template_row: null,
    modifiers: [],
    line_confidence: '0.900' as Money,
  },
  // Every correctable column null: the case the mark exists for.
  {
    position: 1,
    description_raw: '',
    sku: null,
    qty: null,
    unit: null,
    unit_price: null,
    line_total: null,
    is_template_row: null,
    modifiers: [],
    line_confidence: null,
  },
]

/** Deliberately empty. Every control renders `value ?? ''`, so an empty map is
 *  the all-null receipt -- the state in which a missing mark is the failure
 *  design section 4 names, and the state in which every box on screen is blank. */
const NOTHING_EXTRACTED: FieldMap = {}

describe("design section 4's input half, over every control that is rendered", () => {
  it('marks every text-entry control ReceiptForm renders, whatever it renders', () => {
    const { container } = render(
      <ReceiptForm fields={NOTHING_EXTRACTED} onChange={() => {}} />,
    )

    // Anti-vacuity: an enumeration that silently stopped matching would make
    // the assertion below pass over nothing at all.
    expect(controlsIn(container).filter(honoursPlaceholder).length).toBeGreaterThan(0)
    expect(unmarked(container)).toEqual([])
  })

  it('marks every text-entry control LineItemsTable renders, in every row', () => {
    const { container } = render(
      <LineItemsTable items={ITEMS} fields={NOTHING_EXTRACTED} onChange={() => {}} />,
    )

    expect(controlsIn(container).filter(honoursPlaceholder).length).toBeGreaterThan(0)
    expect(unmarked(container)).toEqual([])
  })

  it('skips a control only because HTML gives it no empty state to show one in', () => {
    // The measurement ADR-0027's dated correction records, asserted rather than
    // recited: `ReceiptForm` renders one control per key of `_RECEIPT_FIELDS`,
    // and exactly three of them -- the legibility `<select>` and the two
    // booleans -- cannot carry a placeholder. The two counts below therefore
    // move together, and the gap between them is the claim: it is three, and it
    // is three because of the list this test also asserts. Neither number is
    // recited from prose anywhere; both are read off the render.
    const { container } = render(
      <ReceiptForm fields={NOTHING_EXTRACTED} onChange={() => {}} />,
    )

    const all = controlsIn(container)
    const marked = all.filter(honoursPlaceholder)
    expect(all).toHaveLength(19)
    expect(marked).toHaveLength(all.length - 3)
    expect(marked).toHaveLength(16)
    expect(cannotCarryAMark(container).sort()).toEqual([
      'input[type=checkbox] Handwritten',
      'input[type=checkbox] Receipt is inconsistent',
      'select Legibility',
    ])
  })

  it('leaves nothing out of the line-item rows, and names the one control that cannot be marked', () => {
    // `position` is read-only and is a `<td>`, not a control, so it is not in
    // the count. Every other correctable column is.
    //
    // **The template-row checkbox cannot carry the mark, and that is a real
    // gap rather than an oversight.** A checkbox has no placeholder, so an
    // `is_template_row` of `null` renders identically to `false` -- design
    // section 4's `null` is not `0` is not empty, defeated by the control
    // type. It is listed here rather than excused, exactly as `Handwritten`
    // and `Receipt is inconsistent` are listed in the ReceiptForm pin above,
    // and ISSUE-006 records it. The pre-existing precedent is why this is not
    // a new class of defect: `meta.is_handwritten` has had the same shape
    // since the form was built.
    const { container } = render(
      <LineItemsTable items={ITEMS} fields={NOTHING_EXTRACTED} onChange={() => {}} />,
    )

    const all = controlsIn(container)
    expect(all).toHaveLength(ITEMS.length * 7)
    expect(all.filter(honoursPlaceholder)).toHaveLength(ITEMS.length * 6)
    expect(cannotCarryAMark(container).sort()).toEqual([
      'input[type=checkbox] Template row 0',
      'input[type=checkbox] Template row 1',
    ])
  })
})

describe("design section 5.1's autoComplete, over every money control that is rendered", () => {
  /** The money controls, found by what makes them money controls -- ADR-0015's
   *  `type="text" inputMode="decimal"` -- rather than by their labels. */
  function moneyControlsIn(container: HTMLElement): HTMLInputElement[] {
    return controlsIn(container)
      .filter((control): control is HTMLInputElement => control instanceof HTMLInputElement)
      .filter((control) => control.getAttribute('inputmode') === 'decimal')
  }

  it('turns autofill off on every money control ReceiptForm renders', () => {
    // A remembered `1000.00` offered under a total transcribed from a
    // photograph invites a reviewer to accept a number from another receipt.
    const { container } = render(
      <ReceiptForm fields={NOTHING_EXTRACTED} onChange={() => {}} />,
    )

    const money = moneyControlsIn(container)
    expect(money).toHaveLength(6)
    expect(money.filter((c) => c.getAttribute('autocomplete') !== 'off').map(describeControl)).toEqual(
      [],
    )
    // ...and none of them is the number input ADR-0015 bans, which is the other
    // half of why they are found by `inputMode` rather than by name.
    expect(money.filter((c) => c.type !== 'text').map(describeControl)).toEqual([])
  })

  it('turns autofill off on every money cell LineItemsTable renders', () => {
    const { container } = render(
      <LineItemsTable items={ITEMS} fields={NOTHING_EXTRACTED} onChange={() => {}} />,
    )

    const money = moneyControlsIn(container)
    expect(money).toHaveLength(ITEMS.length * 3)
    expect(money.filter((c) => c.getAttribute('autocomplete') !== 'off').map(describeControl)).toEqual(
      [],
    )
  })
})

describe("the confidence score goes through the primitive that owns section 4's rule", () => {
  it('announces a score that was never recorded, rather than drawing a glyph', () => {
    // `confidence-rail.test.tsx:58` asserts `getByText('—')`, which passes
    // whether or not `Value` is used: a bare `<p>{confidence ?? '—'}</p>` renders
    // the same text node. ADR-0027 names that line as the uncoordinated second
    // copy of half the rule -- same glyph, no accessible name, no `--color-null`,
    // no hairline border -- so a screen reader heard "em dash" or nothing.
    //
    // `role="img"` is what makes the name legal (a bare `<span>` is
    // `role=generic`, for which ARIA 1.2 marks naming prohibited) and querying
    // through the role is what makes this pin fail when the primitive is
    // bypassed. `getByLabelText` would not: it reads the DOM attribute without
    // ever consulting the role.
    render(<ConfidenceRail confidence={null} reasons={null} />)

    expect(screen.getByRole('img', { name: 'not extracted' })).toBeDefined()
  })

  it('does not paint the mark over a real score', () => {
    render(<ConfidenceRail confidence={'0.000' as Money} reasons={[]} />)

    expect(screen.queryByRole('img', { name: 'not extracted' })).toBeNull()
    expect(screen.getByText('0.000')).toBeDefined()
  })
})

// --------------------------------------------------------------------------- //
// Design section 5's three remaining components
// --------------------------------------------------------------------------- //

/** A stylesheet, read as text.
 *
 * Under Vitest's `css: false` a `.module.css` import is a proxy whose keys echo
 * back as strings, so a rendering test cannot tell `styles.scroller` from
 * `styles.scrolller` -- the misspelling ships as `class="undefined"` with every
 * gate green. Anything about the CSS itself therefore has to be read off the
 * file, exactly as `tests/value.test.tsx` reads the primitives'.
 *
 * `dirname(fileURLToPath(import.meta.url))` rather than
 * `new URL(specifier, import.meta.url)`: Vite rewrites that *pattern* into a
 * static-asset import, and for a `.module.css` specifier it does not merely
 * resolve wrongly -- it refuses outright with `?url is not supported with CSS
 * modules`, which is how the first draft of this file failed to collect a single
 * test. `tests/value.test.tsx:134-153` records the same measurement.
 */
const REVIEW_SRC = join(dirname(fileURLToPath(import.meta.url)), '..', 'src', 'review')

function readStylesheet(relative: string): string {
  try {
    return readFileSync(join(REVIEW_SRC, relative), 'utf8')
  } catch (cause) {
    throw new Error(
      `a guard in this file cannot read src/review/${relative}. If that file ` +
        `moved or was renamed, update this path -- the guard is not optional cover.`,
      { cause },
    )
  }
}

/** The declarations of the one top-level rule whose selector is exactly
 *  `selector`. Comments are stripped first, because these stylesheets document
 *  the rules they contain and prose must not answer for code. Throws rather than
 *  returning empty, so a renamed class is loud. */
function declarationsIn(css: string, selector: string): Map<string, string> {
  const source = css.replace(/\/\*[\s\S]*?\*\//g, '')
  const at = source.indexOf(`${selector} {`)
  if (at === -1) throw new Error(`no rule with the selector \`${selector}\``)
  const open = source.indexOf('{', at)
  const close = source.indexOf('}', open)
  if (close === -1) throw new Error(`unterminated block for \`${selector}\``)
  const found = new Map<string, string>()
  for (const [, name, value] of source.slice(open + 1, close).matchAll(/([\w-]+)\s*:\s*([^;]+);/g)) {
    found.set(name, value.trim())
  }
  return found
}

describe('every class these three components reference exists in its stylesheet', () => {
  // `tests/value.test.tsx` runs this guard over `Value`, `Button`, `Chip` and
  // `MoneyInput`, and it cannot be extended to cover the three components below
  // without editing it. So the same property is stated again here, for the
  // stylesheets §5.2/§5.3/§5.4 just grew: under `css: false` a `.module.css`
  // import is a proxy whose keys echo back, so `styles.scrolller` renders
  // `class="undefined"` and every rendering test in this file still passes.
  // Nothing here paints anything; a missing class is invisible to the DOM.
  const GUARDED = [
    { tsx: 'ConfidenceRail.tsx', css: 'ConfidenceRail.module.css' },
    { tsx: 'FindingsPanel.tsx', css: 'FindingsPanel.module.css' },
    { tsx: 'LineItemsTable.tsx', css: 'LineItemsTable.module.css' },
  ] as const

  /** Class selectors a stylesheet declares, comments stripped first -- these
   *  files document the rules they contain, and prose must not answer for
   *  code. */
  function declaredClasses(css: string): Set<string> {
    const source = css.replace(/\/\*[\s\S]*?\*\//g, '')
    return new Set(Array.from(source.matchAll(/\.([A-Za-z][\w-]*)/g), (m) => m[1]))
  }

  /** `styles.foo` references a component makes, comments stripped for the same
   *  reason: every one of these files names its own classes in prose. */
  function referencedClasses(tsx: string): Set<string> {
    const source = tsx.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1')
    return new Set(Array.from(source.matchAll(/\bstyles\.([A-Za-z][\w-]*)/g), (m) => m[1]))
  }

  it('extracts from both sides, and is not fooled by a comment', () => {
    // Positive controls: a `declaredClasses` returning everything, or a
    // `referencedClasses` returning nothing, makes the guard below vacuous.
    expect(declaredClasses('.real { color: red }').has('real')).toBe(true)
    expect(declaredClasses('/* .ghost {} */ .real {}').has('ghost')).toBe(false)
    expect(referencedClasses('x = styles.real').has('real')).toBe(true)
    expect(referencedClasses('/* styles.ghost */ x = styles.real').has('ghost')).toBe(false)
  })

  it('declares every class the three components reach', () => {
    for (const { tsx, css } of GUARDED) {
      const declared = declaredClasses(readStylesheet(css))
      const referenced = referencedClasses(readStylesheet(tsx))
      expect(referenced.size, `${tsx} references no styles.*`).toBeGreaterThan(0)
      const missing = [...referenced].filter((name) => !declared.has(name))
      expect(missing, `${tsx} reaches classes ${css} does not declare`).toEqual([])
    }
  })

  it('declares the three band tones, which no regex over the source can see', () => {
    // `ConfidenceRail` reaches these as `styles[band.tone]`, so the check above
    // is blind to them. Derived from the `Band['tone']` union in the source
    // rather than retyped, so a fourth tone is covered the day it is added and
    // a truncated parse is loud rather than silently agreeing with a stale list.
    const source = readStylesheet('ConfidenceRail.tsx')
    const union = source.match(/readonly tone:\s*([^\n]+)/)
    expect(union, 'the tone union is no longer declared the way this guard reads it').not.toBeNull()
    const tones = Array.from(union![1].matchAll(/'([\w-]+)'/g), (m) => m[1])
    expect(tones.length, 'the tone union parsed as empty').toBeGreaterThan(0)
    const declared = declaredClasses(readStylesheet('ConfidenceRail.module.css'))
    expect(tones.filter((tone) => !declared.has(tone))).toEqual([])
  })
})

describe('design section 5.2 -- the line items scroll rather than squeeze', () => {
  it('wraps the table in a scroller that is not a bare div', () => {
    // Not a `<div>`, and that is measured rather than stylistic:
    // `ReviewScreen.module.css` places the image pane with `.screen > div` and
    // says in its own comment that the pane is the ONLY direct `<div>` child of
    // the review `<main>`. `LineItemsTable` is a direct child of that `<main>`,
    // so a `<div>` root here silently steals the image pane's grid area -- a
    // layout break no rendering test can see. The invariant is pinned below.
    const { container } = render(
      <LineItemsTable items={ITEMS} fields={NOTHING_EXTRACTED} onChange={() => {}} />,
    )

    const table = container.querySelector('table')
    expect(table).not.toBeNull()
    const wrapper = table?.parentElement
    expect(wrapper?.tagName.toLowerCase()).toBe('section')
    expect(wrapper?.parentElement).toBe(container)

    // The table keeps its own element and therefore its implicit ARIA role.
    // `display: block; overflow-x: auto` on the `<table>` itself would scroll
    // too and would silently stop being a grid to a screen reader, while every
    // `getByRole('table')` query stayed green.
    expect(table?.tagName.toLowerCase()).toBe('table')
  })

  it('actually gives that wrapper a horizontal scroller', () => {
    const scroller = declarationsIn(readStylesheet('LineItemsTable.module.css'), '.scroller')
    expect(scroller.get('overflow-x')).toBe('auto')
    // The page body must never scroll horizontally instead, which needs the
    // wrapper to be allowed to be narrower than its content.
    expect(scroller.get('max-width')).toBe('100%')
  })
})

describe("the review screen's image slot stays the only direct <div>", () => {
  it('gives every other panel a root element that is not a div', () => {
    // `ReviewScreen.module.css` places the image pane **positionally**, with
    // `.screen > div { grid-column: 1; grid-row: 2 / span 4; position: sticky }`,
    // and states in its own comment that the pane is the ONLY direct `<div>`
    // child of the review `<main>`. Every panel below is a direct child of that
    // `<main>`, so the day one of them takes a `<div>` root it steals the
    // photograph's grid area -- silently, because a grid placement is invisible
    // to every rendering query in this suite. §5.2's scroll wrapper is where
    // that nearly happened: a `<div>` is the reflexive element for one.
    //
    // Quantified over the panels rather than asserted about the one that
    // changed, so the next component to gain a wrapper is covered without an
    // edit here. `ImagePane` is asserted from the other side in the same test:
    // the invariant is "exactly one", and a rule that matched *nothing* would
    // leave the pane unplaced just as silently.
    const panels = [
      ['FindingsPanel', <FindingsPanel key="f" findings={[]} />],
      ['ConfidenceRail', <ConfidenceRail key="c" confidence={null} reasons={null} />],
      ['ReceiptForm', <ReceiptForm key="r" fields={NOTHING_EXTRACTED} onChange={() => {}} />],
      [
        'LineItemsTable',
        <LineItemsTable key="l" items={ITEMS} fields={NOTHING_EXTRACTED} onChange={() => {}} />,
      ],
    ] as const

    const roots: string[] = []
    for (const [name, element] of panels) {
      const rendered = render(element)
      roots.push(`${name}: ${rendered.container.firstElementChild?.tagName.toLowerCase()}`)
      rendered.unmount()
    }
    expect(roots.filter((root) => root.endsWith(': div'))).toEqual([])
    // Anti-vacuity: an empty render would satisfy the filter above trivially.
    expect(roots).toHaveLength(panels.length)
    expect(roots.filter((root) => root.endsWith(': undefined'))).toEqual([])
  })

  it('keeps the image pane itself a div, because the rule has to match something', () => {
    const { container } = render(
      <ImagePane receiptId="a1" fetchUrl={() => new Promise<string>(() => {})} />,
    )

    expect(container.firstElementChild?.tagName.toLowerCase()).toBe('div')
  })
})

describe('design section 5.3 -- the confidence band is never colour alone', () => {
  const HIGH = '0.910' as Money
  const MIDDLE = '0.700' as Money
  const LOW = '0.120' as Money

  it('names the band in words, at every threshold', () => {
    // The word is the signal; the colour is a second, redundant one. A reader
    // who does not get colour -- greyscale print, a colour-blind reviewer, a
    // screen reader -- must get the same three-way distinction from the text.
    for (const [score, word] of [
      [HIGH, 'Auto-approve'],
      [MIDDLE, 'Review'],
      [LOW, 'Low'],
    ] as const) {
      const rendered = render(<ConfidenceRail confidence={score} reasons={[]} />)
      expect(rendered.getByText(word)).toBeDefined()
      rendered.unmount()
    }
  })

  it('gives the band an icon that announces as words, not as a glyph', () => {
    // The icon is a text glyph -- there is no icon set in this project and this
    // task may not add a dependency -- so it needs the same treatment
    // `ui/Value` gives the null mark: `role="img"` with a name, because a bare
    // `<span>` is `role=generic` and ARIA 1.2 prohibits naming one.
    render(<ConfidenceRail confidence={HIGH} reasons={[]} />)

    const icon = screen.getByRole('img', { name: /auto-approve/i })
    expect(icon.textContent?.trim().length).toBeGreaterThan(0)
  })

  it('draws no band at all for a score that was never recorded', () => {
    // A band is a judgement about a number. There is no number here, and
    // inventing "Low" for a receipt that was never scored is exactly the
    // null-reads-as-zero failure section 4 exists to prevent.
    render(<ConfidenceRail confidence={null} reasons={null} />)

    expect(screen.queryByText('Auto-approve')).toBeNull()
    expect(screen.queryByText('Review')).toBeNull()
    expect(screen.queryByText('Low')).toBeNull()
  })

  it('reads the thresholds off the string without arithmetic, at the boundary', () => {
    // 0.85 and 0.60 are the server's own cut-offs
    // (src/receipts/score/thresholds.py), and both are "at or above", so the
    // boundary value belongs to the higher band. Compared as decimal strings:
    // `Number('0.85')` is banned in this path (ADR-0001, and
    // tests/no-float-in-money-path.test.ts enforces it).
    for (const [score, word] of [
      ['0.850', 'Auto-approve'],
      ['0.849', 'Review'],
      ['0.600', 'Review'],
      ['0.599', 'Low'],
      ['1.000', 'Auto-approve'],
      ['0.000', 'Low'],
    ] as const) {
      const rendered = render(<ConfidenceRail confidence={score as Money} reasons={[]} />)
      expect(rendered.getByText(word), `${score} landed in the wrong band`).toBeDefined()
      rendered.unmount()
    }
  })
})

describe('design section 5.4 -- the findings are a disclosure list', () => {
  const FINDINGS: Finding[] = [
    {
      rule_id: 'R020',
      severity: 'error',
      message: 'subtotal + tax does not equal total',
      context: { expected: '97.43', actual: '96.00' },
      resolved_by_repair: false,
    },
    {
      rule_id: 'R101',
      severity: 'warn',
      message: 'merchant name is low confidence',
      context: null,
      resolved_by_repair: true,
    },
  ]

  it('collapses each finding to a summary a reviewer can open', () => {
    const { container } = render(<FindingsPanel findings={FINDINGS} />)

    const disclosures = [...container.querySelectorAll('details')]
    expect(disclosures).toHaveLength(FINDINGS.length)
    for (const disclosure of disclosures) {
      // Collapsed by default: a panel that opens every finding is the list it
      // replaced, one element heavier.
      expect(disclosure.open).toBe(false)
      expect(disclosure.querySelector('summary')).not.toBeNull()
    }
  })

  it('keeps the rule id, the severity word and the message in the collapsed row', () => {
    // What the reviewer scans without opening anything. `review-screen.test.tsx`
    // finds `R020` by text on the loaded screen, and it must go on finding it.
    const { container } = render(<FindingsPanel findings={FINDINGS} />)

    const summaries = [...container.querySelectorAll('summary')].map((s) => s.textContent ?? '')
    expect(summaries[0]).toContain('R020')
    expect(summaries[0]).toContain('error')
    expect(summaries[0]).toContain('subtotal + tax does not equal total')
    expect(summaries[1]).toContain('resolved by repair')
  })

  it('discloses the context payload, which nothing rendered before', () => {
    const { container } = render(<FindingsPanel findings={FINDINGS} />)

    const [withContext, withoutContext] = [...container.querySelectorAll('details')]
    expect(withContext.textContent).toContain('97.43')
    expect(withContext.textContent).toContain('96.00')
    // `context` is `unknown` and is `null` for most findings. A disclosure that
    // opens onto nothing is worse than none, so that row says so.
    expect(withoutContext.textContent).toMatch(/no further detail/i)
  })

  it('says so, once, when there is nothing to disclose', () => {
    const { container } = render(<FindingsPanel findings={[]} />)

    expect(container.querySelectorAll('details')).toHaveLength(0)
    expect(screen.getByText('No findings.')).toBeDefined()
  })
})
