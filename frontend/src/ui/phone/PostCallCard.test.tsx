/**
 * Unit tests for PostCallCard.
 *
 * Anchored to the variant × missed matrix in § 3 of the handoff.
 * Each test names the invariant it protects.
 */
import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import PostCallCard, { postCallCardInternals } from './PostCallCard'

const { formatDuration } = postCallCardInternals

describe('formatDuration', () => {
  it('renders seconds under a minute', () => {
    expect(formatDuration(5)).toBe('5s')
    expect(formatDuration(59)).toBe('59s')
  })
  it('rounds to whole minutes when exact', () => {
    expect(formatDuration(60)).toBe('1 min')
    expect(formatDuration(720)).toBe('12 min')
  })
  it('renders minutes + residual seconds', () => {
    expect(formatDuration(64)).toBe('1 min 4s')
  })
})

describe('PostCallCard — expand variant (default)', () => {
  it('renders duration + persona name', () => {
    render(<PostCallCard durationSec={42} personaName="Vesper" />)
    expect(screen.getByText(/Call with Vesper/i)).toBeInTheDocument()
    expect(screen.getByText(/42s/)).toBeInTheDocument()
  })

  it('hides the transcript button when no transcript is supplied', () => {
    render(<PostCallCard durationSec={42} personaName="Vesper" />)
    expect(screen.queryByRole('button', { name: /view transcript/i })).not.toBeInTheDocument()
  })

  it('shows the transcript button when a transcript is supplied', () => {
    render(
      <PostCallCard
        durationSec={42}
        personaName="Vesper"
        transcript={[{ who: 'user', text: 'hello' }]}
      />,
    )
    expect(screen.getByRole('button', { name: /view transcript/i })).toBeInTheDocument()
  })

  it('expands the transcript inline (NOT a modal) when clicked', () => {
    render(
      <PostCallCard
        durationSec={42}
        personaName="Vesper"
        transcript={[
          { who: 'user', text: 'hello' },
          { who: 'assistant', text: 'hey there' },
        ]}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /view transcript/i }))
    expect(screen.getByText('hey there')).toBeInTheDocument()
    // The only role=dialog in the tree would be a modal; assert none.
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('collapses the transcript on a second click', () => {
    render(
      <PostCallCard
        durationSec={42}
        personaName="Vesper"
        transcript={[{ who: 'assistant', text: 'hey there' }]}
      />,
    )
    const btn = screen.getByRole('button', { name: /view transcript/i })
    fireEvent.click(btn)
    expect(screen.getByText('hey there')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /collapse transcript/i }))
    expect(screen.queryByText('hey there')).not.toBeInTheDocument()
  })

  it('fires onResume when Resume call is clicked', () => {
    const onResume = vi.fn()
    render(
      <PostCallCard durationSec={42} personaName="Vesper" onResume={onResume} />,
    )
    fireEvent.click(screen.getByRole('button', { name: /resume call/i }))
    expect(onResume).toHaveBeenCalledTimes(1)
  })
})

describe('PostCallCard — highlights variant', () => {
  it('shows the summary line and a "Full transcript" button when handler supplied', () => {
    const onOpen = vi.fn()
    render(
      <PostCallCard
        durationSec={600}
        personaName="Vesper"
        variant="highlights"
        summary="You talked about Lisbon and made plans for Friday."
        onOpenFullTranscript={onOpen}
      />,
    )
    expect(screen.getByText(/Vesper remembers/i)).toBeInTheDocument()
    expect(
      screen.getByText(/You talked about Lisbon and made plans for Friday/i),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /open full transcript/i }))
    expect(onOpen).toHaveBeenCalledTimes(1)
  })

  it('omits the "Full transcript" button when no handler is supplied', () => {
    render(
      <PostCallCard
        durationSec={600}
        personaName="Vesper"
        variant="highlights"
        summary="…"
      />,
    )
    expect(
      screen.queryByRole('button', { name: /open full transcript/i }),
    ).not.toBeInTheDocument()
  })
})

describe('PostCallCard — missed variant', () => {
  it('swaps Resume → Call back and omits secondary CTA', () => {
    const onCallBack = vi.fn()
    render(
      <PostCallCard
        durationSec={0}
        personaName="Vesper"
        missed
        onCallBack={onCallBack}
      />,
    )
    expect(screen.getByText(/Missed call/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /call back/i }))
    expect(onCallBack).toHaveBeenCalledTimes(1)
    // No secondary button at all in the missed variant.
    expect(screen.queryByRole('button', { name: /view transcript/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /full transcript/i })).not.toBeInTheDocument()
  })

  it('falls back to onResume when onCallBack is omitted', () => {
    const onResume = vi.fn()
    render(
      <PostCallCard durationSec={0} personaName="Vesper" missed onResume={onResume} />,
    )
    fireEvent.click(screen.getByRole('button', { name: /call back/i }))
    expect(onResume).toHaveBeenCalledTimes(1)
  })
})
