/**
 * AppErrorBoundary — the app never fails to an unexplained black screen.
 *
 * Without a boundary, any exception thrown while rendering unmounts the whole
 * React tree and leaves only the page background: on a phone that is a black
 * screen with nothing to tap. This shows what happened, offers Try again /
 * Reload / Copy details, and logs the failure with enough context to diagnose.
 */
import React from 'react'

type State = { error: Error | null; componentStack: string; copied: boolean }

export function describeFailure(error: Error, componentStack: string): string {
  return [
    `HomePilot UI error: ${error.name}: ${error.message}`,
    `When: ${new Date().toISOString()}`,
    `Where: ${typeof window !== 'undefined' ? window.location.pathname + window.location.hash : ''}`,
    `Viewport: ${typeof window !== 'undefined' ? `${window.innerWidth}x${window.innerHeight}` : ''}`,
    `Agent: ${typeof navigator !== 'undefined' ? navigator.userAgent : ''}`,
    '',
    (error.stack || '').split('\n').slice(0, 8).join('\n'),
    componentStack ? `\nComponents:${componentStack.split('\n').slice(0, 8).join('\n')}` : '',
  ].join('\n')
}

export class AppErrorBoundary extends React.Component<{ children: React.ReactNode; label?: string }, State> {
  state: State = { error: null, componentStack: '', copied: false }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    const componentStack = info?.componentStack || ''
    this.setState({ componentStack })
    // One structured line that is easy to find in browser and Space logs.
    console.error('[HomePilot] UI crashed', {
      area: this.props.label || 'app',
      name: error?.name,
      message: error?.message,
      path: typeof window !== 'undefined' ? window.location.pathname + window.location.hash : '',
      componentStack,
    })
  }

  private copy = async () => {
    const { error, componentStack } = this.state
    if (!error) return
    try {
      await navigator.clipboard.writeText(describeFailure(error, componentStack))
      this.setState({ copied: true })
    } catch {
      /* clipboard unavailable (e.g. insecure context) — the details stay on screen */
    }
  }

  render() {
    const { error, copied } = this.state
    if (!error) return this.props.children
    return (
      <div className="hp-status-screen" role="alert">
        <div className="hp-status-card">
          <div aria-hidden style={{ fontSize: 28 }}>⚠️</div>
          <h1>Something went wrong</h1>
          <p>
            HomePilot hit an unexpected error while showing this screen. Your conversations and settings are saved on
            the server. Try again, or reload the page.
          </p>
          <div className="hp-status-actions">
            <button type="button" className="hp-primary" onClick={() => this.setState({ error: null, componentStack: '', copied: false })}>
              Try again
            </button>
            <button type="button" onClick={() => window.location.reload()}>Reload</button>
            <button type="button" onClick={this.copy}>{copied ? 'Copied' : 'Copy details'}</button>
          </div>
          <details className="hp-accordion" style={{ marginTop: 16, textAlign: 'left', color: 'var(--hp-color-text-2)', fontSize: 12 }}>
            <summary style={{ cursor: 'pointer', minHeight: 32 }}>Technical details</summary>
            <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', marginTop: 8 }}>
              {`${error.name}: ${error.message}`}
            </pre>
          </details>
        </div>
      </div>
    )
  }
}

export default AppErrorBoundary
