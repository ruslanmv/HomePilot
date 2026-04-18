/**
 * Unit tests for ``Waveform``.
 *
 * Focuses on the structural guarantees — bar count, colour mapping
 * per mode, a11y defaults, reduced-motion behaviour. The per-frame
 * rAF loop is intentionally NOT driven here (would be flaky in
 * jsdom); the invariant we test is that rAF is/isn't scheduled
 * based on the reduced-motion flag.
 */
import React, { useRef } from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'
import Waveform from './Waveform'

describe('Waveform', () => {
  it('renders the default bar count (26)', () => {
    const { container } = render(<Waveform mode="listening" />)
    // The outer container holds ``bars`` child divs.
    const row = container.firstElementChild as HTMLElement
    expect(row.children.length).toBe(26)
  })

  it('renders a custom bar count', () => {
    const { container } = render(<Waveform mode="listening" bars={8} />)
    const row = container.firstElementChild as HTMLElement
    expect(row.children.length).toBe(8)
  })

  // jsdom normalizes CSS strings (strips trailing zeros from oklch,
  // inserts spaces in rgba), so exact-string comparison is brittle.
  // Assert on the distinguishing value component instead.
  it('paints listening + speaking with the rose accent (hue 340)', () => {
    const { container, rerender } = render(
      <Waveform mode="listening" bars={3} />,
    )
    const first = (
      container.firstElementChild as HTMLElement
    ).firstElementChild as HTMLElement
    expect(first.style.background).toMatch(/oklch.*340\)/)
    rerender(<Waveform mode="speaking" bars={3} />)
    expect(first.style.background).toMatch(/oklch.*340\)/)
  })

  it('paints muted bars with amber (hue 55)', () => {
    const { container } = render(<Waveform mode="muted" bars={3} />)
    const first = (
      container.firstElementChild as HTMLElement
    ).firstElementChild as HTMLElement
    expect(first.style.background).toMatch(/oklch.*55\)/)
  })

  it('paints idle bars with the faint surface tone', () => {
    const { container } = render(<Waveform mode="idle" bars={3} />)
    const first = (
      container.firstElementChild as HTMLElement
    ).firstElementChild as HTMLElement
    expect(first.style.background).toMatch(/rgba\(\s*245/)
  })

  it('is aria-hidden by default (decorative)', () => {
    const { container } = render(<Waveform mode="listening" />)
    const row = container.firstElementChild as HTMLElement
    expect(row.getAttribute('aria-hidden')).toBe('true')
  })

  it('drops aria-hidden when ariaHidden={false}', () => {
    const { container } = render(
      <Waveform mode="listening" ariaHidden={false} />,
    )
    const row = container.firstElementChild as HTMLElement
    expect(row.getAttribute('aria-hidden')).toBeNull()
  })

  it('does NOT schedule rAF when prefers-reduced-motion is set', () => {
    const mq = {
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }
    vi.stubGlobal(
      'matchMedia',
      vi.fn(() => mq),
    )
    const raf = vi.spyOn(globalThis, 'requestAnimationFrame')
    render(<Waveform mode="listening" />)
    expect(raf).not.toHaveBeenCalled()
    raf.mockRestore()
    vi.unstubAllGlobals()
  })

  it('accepts an intensity ref without throwing', () => {
    const Harness: React.FC = () => {
      const ref = useRef(0.3)
      return <Waveform mode="listening" intensityRef={ref} bars={3} />
    }
    const { container } = render(<Harness />)
    expect(container.firstElementChild?.children.length).toBe(3)
  })
})
