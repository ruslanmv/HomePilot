/**
 * Unit tests for ``PhoneCallDivider``.
 *
 * Covers the core invariants from the product spec:
 *   - Renders as role="separator" (neutral event, not a message).
 *   - Duration formatting (seconds / minutes / minutes+seconds).
 *   - Time-of-day shown only when ``endedAt`` is provided.
 *   - No buttons, no cards, no left/right alignment — it is a
 *     timeline divider, nothing more.
 */
import React from 'react'
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import PhoneCallDivider from './PhoneCallDivider'

describe('PhoneCallDivider', () => {
  it('renders a separator role with the composed label', () => {
    render(<PhoneCallDivider durationSec={24} endedAt={1713456900000} />)
    const sep = screen.getByRole('separator')
    expect(sep).toBeTruthy()
    // Label must contain the duration token.
    expect(sep.getAttribute('aria-label') || '').toMatch(/24s/)
  })

  it('formats seconds under a minute as "Ns"', () => {
    render(<PhoneCallDivider durationSec={24} />)
    expect(screen.getByText(/24s/)).toBeTruthy()
  })

  it('formats exact minutes as "Nm"', () => {
    render(<PhoneCallDivider durationSec={180} />)
    expect(screen.getByText(/3m(?! )/)).toBeTruthy()
  })

  it('formats minutes+seconds as "Nm Ss"', () => {
    render(<PhoneCallDivider durationSec={192} />)
    expect(screen.getByText(/3m 12s/)).toBeTruthy()
  })

  it('omits the time-of-day segment when endedAt is missing', () => {
    render(<PhoneCallDivider durationSec={42} />)
    // Only one dot separator; no AM/PM string.
    const text = screen.getByText(/Phone call/).textContent || ''
    expect(text).not.toMatch(/AM|PM|:/)
  })

  it('renders no buttons (it is a divider, not a card)', () => {
    render(<PhoneCallDivider durationSec={42} endedAt={1713456900000} />)
    expect(screen.queryAllByRole('button').length).toBe(0)
  })

  it('clamps negative durations to 0s (defensive, not a real case)', () => {
    render(<PhoneCallDivider durationSec={-5} />)
    expect(screen.getByText(/0s/)).toBeTruthy()
  })
})
