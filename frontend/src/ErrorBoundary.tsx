import { Component } from 'react'
import type { ReactNode } from 'react'

/** The last stop for a render that throws.
 *
 * `main.tsx` had no boundary, and Task 3 is where the first components that can
 * actually throw arrive: `request` is an unchecked cast, so a `ReceiptDetail`
 * missing `findings` or `line_items` is a `TypeError` inside render rather than
 * a rejected promise anyone can catch.
 *
 * **What "no boundary" costs is measured, not assumed.** `tests/error-boundary
 * .test.tsx` renders the same throwing component with no boundary above it: the
 * render call itself throws and the container is left holding the empty string.
 * That is the blank page this exists to prevent, and deleting `<ErrorBoundary>`
 * from `main.tsx` turns `tests/app-root.test.tsx` red.
 *
 * **A boundary only catches render-phase errors** -- render, lifecycle and
 * constructor, per React's contract; a rejected promise or a throwing event
 * handler never reaches it. That last part is React's documented behaviour and
 * is *not* measured here; it is why `ImagePane` and `ReviewScreen` each handle
 * their own rejections rather than relying on this. This is the floor, not the
 * plan.
 *
 * The message is shown, not just logged: an internal reviewing tool where a
 * human can read the failure and quote it is worth more than a house sentence
 * that hides which field was missing. There is no `componentDidCatch` here on
 * purpose -- `getDerivedStateFromError` is what puts the failure on screen, and
 * a second hook whose only body was a `console.error` would be the swallowed
 * failure this project keeps banning.
 *
 * Reloading is the only recovery it can offer. Re-rendering the same children
 * would hit the same error, so the button does not pretend otherwise.
 */
interface ErrorBoundaryProps {
  readonly children: ReactNode
}

interface ErrorBoundaryState {
  readonly message: string | null
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { message: null }

  static getDerivedStateFromError(caught: unknown): ErrorBoundaryState {
    // `throw 'a string'` is legal and does happen; `String(caught)` keeps the
    // fallback readable instead of rendering "undefined" for it.
    return { message: caught instanceof Error ? caught.message : String(caught) }
  }

  render(): ReactNode {
    if (this.state.message === null) {
      return this.props.children
    }
    return (
      <main>
        <p role="alert">The review screen stopped working: {this.state.message}</p>
        <button type="button" onClick={() => window.location.reload()}>
          Reload the page
        </button>
      </main>
    )
  }
}
