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
