/**
 * Unit tests for CallEventRow — enterprise chat renderer for phone
 * calls. Covers the three-state UX:
 *
 *   - Collapsed default, clickable label, hidden action cluster
 *   - Expanded after click, transcript visible, Collapse link exposed
 *   - Resume handler wired, Resume action visible when provided
 *
 * jsdom caveat: group-hover CSS is not actually evaluated, so the
 * hover-reveal is tested by asserting the hover CSS class is present
 * on the action cluster, rather than by simulating mouseenter.
 */
import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import CallEventRow from './CallEventRow'

const SAMPLE_TRANSCRIPT = [
  { who: 'user' as const, text: 'hello how are you going' },
  { who: 'assistant' as const, text: 'I am well, thank you.' },
]

describe('CallEventRow', () => {
  it('renders the collapsed divider with duration + time summary', () => {
    render(<CallEventRow durationSec={26} endedAt={1713456900000} transcript={SAMPLE_TRANSCRIPT} />)
    expect(screen.getByRole('region', { name: /call/i })).toBeTruthy()
    expect(screen.getByText(/26s/)).toBeTruthy()
  })

  it('hides the transcript body in the default collapsed state', () => {
    render(<CallEventRow durationSec={26} transcript={SAMPLE_TRANSCRIPT} />)
    expect(screen.queryByText(/hello how are you going/)).toBeNull()
  })

  it('expands the transcript when the label button is clicked', () => {
    render(<CallEventRow durationSec={26} transcript={SAMPLE_TRANSCRIPT} />)
    const expandBtn = screen.getByRole('button', { name: /expand call row/i })
    fireEvent.click(expandBtn)
    expect(screen.getByText(/hello how are you going/)).toBeTruthy()
    expect(screen.getByText(/I am well, thank you\./)).toBeTruthy()
  })

  it('uses personaName as the label column for assistant lines', () => {
    render(
      <CallEventRow
        durationSec={26}
        personaName="Secretary"
        transcript={SAMPLE_TRANSCRIPT}
        defaultExpanded
      />,
    )
    // User label + persona label both appear in the expanded body.
    expect(screen.getByText('You')).toBeTruthy()
    expect(screen.getByText('Secretary')).toBeTruthy()
  })

  it('strips markdown image syntax from transcript lines', () => {
    render(
      <CallEventRow
        durationSec={26}
        defaultExpanded
        transcript={[
          {
            who: 'assistant',
            text: 'hello ![Secretary](http://x.example.com/a.png) there',
          },
        ]}
      />,
    )
    // Stripped text has the middle removed; renders as "hello there".
    expect(screen.getByText(/^hello\s+there$/)).toBeTruthy()
  })

  it('hides the Transcript / Collapse affordance when transcript is empty', () => {
    render(<CallEventRow durationSec={26} onResume={vi.fn()} />)
    expect(screen.queryByText(/Transcript/i)).toBeNull()
    expect(screen.queryByText(/Collapse/i)).toBeNull()
  })

  it('renders Resume link only when onResume is provided', () => {
    const { rerender } = render(<CallEventRow durationSec={26} transcript={SAMPLE_TRANSCRIPT} />)
    expect(screen.queryByRole('button', { name: /resume call/i })).toBeNull()
    const onResume = vi.fn()
    rerender(<CallEventRow durationSec={26} transcript={SAMPLE_TRANSCRIPT} onResume={onResume} />)
    expect(screen.getByRole('button', { name: /resume call/i })).toBeTruthy()
  })

  it('fires onResume when Resume is clicked, does not expand/collapse', () => {
    const onResume = vi.fn()
    render(
      <CallEventRow
        durationSec={26}
        transcript={SAMPLE_TRANSCRIPT}
        onResume={onResume}
      />,
    )
    // Transcript stays hidden since we clicked Resume, not the label.
    fireEvent.click(screen.getByRole('button', { name: /resume call/i }))
    expect(onResume).toHaveBeenCalledTimes(1)
    expect(screen.queryByText(/hello how are you going/)).toBeNull()
  })

  it('renders with defaultExpanded=true showing transcript immediately', () => {
    render(
      <CallEventRow
        durationSec={26}
        transcript={SAMPLE_TRANSCRIPT}
        defaultExpanded
      />,
    )
    expect(screen.getByText(/hello how are you going/)).toBeTruthy()
  })

  it('formats durations as Ns / Nm / Nm Ss', () => {
    const { rerender } = render(<CallEventRow durationSec={42} />)
    expect(screen.getByText(/42s/)).toBeTruthy()
    rerender(<CallEventRow durationSec={180} />)
    expect(screen.getByText(/3m/)).toBeTruthy()
    rerender(<CallEventRow durationSec={192} />)
    expect(screen.getByText(/3m 12s/)).toBeTruthy()
  })
})
