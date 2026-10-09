/**
 * Motion system: preferences, the progressive reveal's pacing, the primitives'
 * accessible output, and the Back gesture closing layers in order.
 */
import React from 'react'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  AudioWaveform,
  Collapsible,
  DEFAULT_MOTION_PREFS,
  LoadingDots,
  MOTION_EVENT,
  ProgressBar,
  StatusText,
  StreamReveal,
  VoiceOrb,
  partialMarkdown,
  readMotionPrefs,
  revealDuration,
  revealStops,
  waveformWeights,
  writeMotionPrefs,
  MotionGallery,
} from '../ui/motion'
import { useBackToClose } from '../ui/lib/useBackToClose'

afterEach(() => {
  localStorage.clear()
  delete document.documentElement.dataset.hpMotion
  delete document.documentElement.dataset.hpReveal
  vi.useRealTimers()
})

describe('motion preferences', () => {
  it('default to the enterprise level with streamed answers, and ignore unknown values', () => {
    expect(readMotionPrefs()).toEqual(DEFAULT_MOTION_PREFS)
    localStorage.setItem('homepilot_motion', JSON.stringify({ level: 'wild', reveal: 'fade' }))
    expect(readMotionPrefs()).toEqual({ level: 'enterprise', reveal: 'fade' })
    localStorage.setItem('homepilot_motion', '{not json')
    expect(readMotionPrefs()).toEqual(DEFAULT_MOTION_PREFS)
  })

  it('are saved on this device, mirrored onto <html>, and announced', () => {
    const heard = vi.fn()
    window.addEventListener(MOTION_EVENT, heard)
    writeMotionPrefs({ level: 'minimal' })
    window.removeEventListener(MOTION_EVENT, heard)
    expect(readMotionPrefs()).toEqual({ level: 'minimal', reveal: 'stream' })
    expect(document.documentElement.dataset.hpMotion).toBe('minimal')
    expect(document.documentElement.dataset.hpReveal).toBe('stream')
    expect(heard).toHaveBeenCalledTimes(1)
  })
})

describe('progressive reveal', () => {
  it('stops only after whole words and always ends at the full text', () => {
    const text = 'Hello there,  world'
    const stops = revealStops(text)
    expect(stops).toEqual([6, 14, 19])
    expect(stops.map((i) => text.slice(0, i))).toEqual(['Hello ', 'Hello there,  ', 'Hello there,  world'])
    expect(revealStops('')).toEqual([0])
  })

  it('is paced by length but never slow', () => {
    expect(revealDuration(3)).toBe(450)
    expect(revealDuration(60)).toBe(840)
    expect(revealDuration(5000)).toBe(1600)
  })

  it('closes an unfinished code fence so a partial answer still renders as code', () => {
    const text = 'Run this:\n\n```bash\nls -la\n```\n\nDone.'
    expect(partialMarkdown(text, 'Run this:\n\n```bash\nls'.length)).toBe('Run this:\n\n```bash\nls\n```')
    expect(partialMarkdown(text, text.length)).toBe(text)
  })

  it('renders the final answer at once where motion cannot run (tests, reduced motion)', () => {
    render(<StreamReveal text="All of it" active render={(t) => <p>{t}</p>} />)
    expect(screen.getByText('All of it')).toBeInTheDocument()
  })
})

describe('motion primitives', () => {
  it('give every animation a readable, accessible equivalent', () => {
    render(
      <>
        <LoadingDots label="Waiting for a reply" />
        <ProgressBar value={0.42} label="Upload" />
        <ProgressBar label="Refreshing" />
        <StatusText text="Searching the web" />
        <VoiceOrb state="listening" level={2} />
        <AudioWaveform level={0.5} bars={9} />
      </>,
    )
    expect(screen.getByRole('img', { name: 'Waiting for a reply' })).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: 'Upload' })).toHaveAttribute('aria-valuenow', '42')
    expect(screen.getByRole('progressbar', { name: 'Refreshing' })).not.toHaveAttribute('aria-valuenow')
    expect(screen.getByRole('status')).toHaveTextContent('Searching the web')
    const orb = document.querySelector('.hp-orb') as HTMLElement
    expect(orb.style.getPropertyValue('--hp-level')).toBe('1.000') // clamped
    expect(document.querySelectorAll('.hp-wave > span')).toHaveLength(9)
  })

  it('announce a changed status once, with the new label', () => {
    const { rerender } = render(<StatusText text="Searching" />)
    rerender(<StatusText text="Reading 3 sources" />)
    expect(screen.getByRole('status')).toHaveTextContent('Reading 3 sources')
    expect(screen.getByRole('status')).not.toHaveTextContent('Searching')
  })

  it('hide collapsed content from everyone', () => {
    const { rerender } = render(<Collapsible open={false}><span>Details</span></Collapsible>)
    expect(document.querySelector('.hp-collapsible')).toHaveAttribute('aria-hidden', 'true')
    rerender(<Collapsible open><span>Details</span></Collapsible>)
    expect(document.querySelector('.hp-collapsible')).not.toHaveAttribute('aria-hidden')
  })

  it('shape the waveform like a voice: tallest in the middle', () => {
    const w = waveformWeights(7)
    expect(w[3]).toBeCloseTo(1)
    expect(w[0]).toBeCloseTo(w[6])
    expect(w[0]).toBeLessThan(w[3])
  })
})

describe('Settings → Motion', () => {
  it('lists all 22 animations and applies a choice immediately', () => {
    render(<MotionGallery />)
    const list = screen.getByRole('list', { name: 'Animations in HomePilot' })
    expect(list.textContent).toContain('Text shimmer')
    expect(list.textContent).toContain('Progress indicator')
    expect(list.querySelectorAll('[data-motion-demo]')).toHaveLength(22)
    fireEvent.click(screen.getByRole('radio', { name: /Off/ }))
    expect(readMotionPrefs().level).toBe('off')
    expect(screen.getByRole('radio', { name: /Off/ })).toHaveAttribute('aria-checked', 'true')
    fireEvent.click(screen.getByRole('radio', { name: /Instant/ }))
    expect(readMotionPrefs().reveal).toBe('instant')
  })
})

function Layer({ name, onClose }: { name: string; onClose: () => void }) {
  useBackToClose(true, onClose)
  return <div>{name}</div>
}

describe('Back gesture', () => {
  it('closes only the top layer, and gives its history entry back when closed another way', async () => {
    vi.useFakeTimers()
    const start = window.history.length
    const closeDrawer = vi.fn()
    const closeSettings = vi.fn()
    const { rerender } = render(<Layer name="drawer" onClose={closeDrawer} />)
    await act(async () => { vi.advanceTimersByTime(1) })
    rerender(<><Layer name="drawer" onClose={closeDrawer} /><Layer name="settings" onClose={closeSettings} /></>)
    await act(async () => { vi.advanceTimersByTime(1) })
    expect(window.history.length).toBe(start + 2)
    expect(window.history.state.hpLayer).toBe(2)

    // Back from settings: lands on the drawer's entry.
    await act(async () => {
      window.dispatchEvent(new PopStateEvent('popstate', { state: { hpLayer: 1 } }))
    })
    expect(closeSettings).toHaveBeenCalledTimes(1)
    expect(closeDrawer).not.toHaveBeenCalled()
  })
})

describe('StatusText under rapid changes', () => {
  it('never shows two labels when the status flips faster than it can animate', () => {
    const { rerender } = render(<StatusText text="Listening for voice..." working={false} />)
    for (let i = 0; i < 6; i++) {
      rerender(<StatusText text={i % 2 ? 'Listening for voice...' : 'Listening...'} working={false} />)
    }
    expect(document.querySelectorAll('.hp-status-swap__out')).toHaveLength(0)
    expect(screen.getByRole('status').textContent).toBe('Listening for voice...')
  })
})
