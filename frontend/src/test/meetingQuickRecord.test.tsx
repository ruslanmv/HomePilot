/**
 * Quick record: recording a Slack / Zoom / Teams call is one click once consent has been
 * given on this computer, and the full wizard is still one click away ("More options").
 */
import React from 'react'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { CONSENT_STORAGE_KEY } from '../ui/meetingsense/ConsentSheet'
import { DEFAULT_CAPTURE } from '../ui/meetingsense/CapturePopover'
import { MeetingSenseContext, type MeetingControls } from '../ui/meetingsense/MeetingSenseProvider'
import { StartMeetingWizard } from '../ui/meetingsense/library/StartMeetingWizard'
import {
  QUICK_RECORD_KEY,
  readQuickPrefs,
  shareHint,
  writeQuickPrefs,
} from '../ui/meetingsense/library/quickRecord'

vi.mock('../ui/meetingsense/library/api', () => ({
  LibraryError: class LibraryError extends Error {},
  libraryApi: { projects: vi.fn(async () => []), createScheduled: vi.fn(async () => ({})) },
}))

function controls(overrides: Partial<MeetingControls> = {}): MeetingControls {
  return {
    live: false,
    starting: false,
    error: null,
    status: { enabled: true, stt: { remote: false } } as any,
    conversationId: null,
    begin: vi.fn(),
    end: vi.fn(),
    phase: 'idle' as any,
    phaseText: '',
    elapsedMs: 0,
    micMuted: false,
    mute: vi.fn(),
    undo: vi.fn(),
    undoSecondsLeft: null,
    capture: { ...DEFAULT_CAPTURE },
    setCapture: vi.fn(),
    startWith: vi.fn(async () => ({ ok: true })),
    ...overrides,
  }
}

function renderWizard(ctl: MeetingControls, onClose = vi.fn()) {
  render(
    <MeetingSenseContext.Provider value={ctl}>
      <StartMeetingWizard onClose={onClose} onCreated={() => undefined} />
    </MeetingSenseContext.Provider>,
  )
  return onClose
}

beforeEach(() => localStorage.clear())
afterEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
})

describe('Quick record', () => {
  it('opens on quick record and asks for consent the first time only', async () => {
    const ctl = controls()
    const onClose = renderWizard(ctl)

    expect(screen.getByRole('heading', { name: 'Record a call' })).toBeTruthy()
    const start = screen.getByTestId('hp-quick-start') as HTMLButtonElement
    expect(start.disabled).toBe(true)

    fireEvent.click(screen.getByTestId('hp-quick-consent'))
    expect(start.disabled).toBe(false)
    await act(async () => { fireEvent.click(start) })

    expect(ctl.startWith).toHaveBeenCalledTimes(1)
    const [capture, meta, acknowledge] = (ctl.startWith as any).mock.calls[0]
    expect(capture).toMatchObject({ audio: true, mic: true, slides: false })
    expect(meta).toEqual({})
    expect(acknowledge).toBe(true)
    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })

  it('is a single click once consent is remembered, and remembers the switches', async () => {
    localStorage.setItem(CONSENT_STORAGE_KEY, 'true')
    const ctl = controls()
    renderWizard(ctl)

    expect(screen.queryByTestId('hp-quick-consent')).toBeNull()
    fireEvent.click(screen.getByTestId('hp-quick-screen'))
    fireEvent.change(screen.getByTestId('hp-quick-title-input'), { target: { value: 'Standup' } })
    await act(async () => { fireEvent.click(screen.getByTestId('hp-quick-start')) })

    const [capture, meta] = (ctl.startWith as any).mock.calls[0]
    expect(capture).toMatchObject({ audio: true, mic: true, slides: true })
    expect(meta).toEqual({ title: 'Standup' })
    expect(readQuickPrefs()).toEqual({ audio: true, mic: true, screen: true })
  })

  it('shows the start error and stays open', async () => {
    localStorage.setItem(CONSENT_STORAGE_KEY, 'true')
    const ctl = controls({ startWith: vi.fn(async () => ({ ok: false, error: 'Share was cancelled.' })) })
    const onClose = renderWizard(ctl)
    await act(async () => { fireEvent.click(screen.getByTestId('hp-quick-start')) })
    expect(screen.getByRole('alert').textContent).toContain('Share was cancelled.')
    expect(onClose).not.toHaveBeenCalled()
  })

  it('keeps the full wizard one click away, carrying the switches', () => {
    localStorage.setItem(CONSENT_STORAGE_KEY, 'true')
    writeQuickPrefs({ audio: true, mic: false, screen: false })
    renderWizard(controls())

    fireEvent.click(screen.getByTestId('hp-quick-more'))
    expect(screen.getByRole('heading', { name: 'Start a meeting' })).toBeTruthy()
    expect(screen.getByRole('button', { name: /Next: Recording source/ })).toBeTruthy()
  })

  it('opens straight on the full wizard when live recording is not possible', () => {
    renderWizard(controls({ live: true }))
    expect(screen.queryByRole('heading', { name: 'Record a call' })).toBeNull()
    expect(screen.getByRole('heading', { name: 'Start a meeting' })).toBeTruthy()
  })

  it('cannot start with nothing selected', () => {
    localStorage.setItem(CONSENT_STORAGE_KEY, 'true')
    writeQuickPrefs({ audio: false, mic: false, screen: false })
    renderWizard(controls())
    expect((screen.getByTestId('hp-quick-start') as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByTestId('hp-quick-hint').textContent).toContain('Choose at least one thing to record.')
  })
})

describe('quickRecord helpers', () => {
  it('defaults to call audio and microphone, screen off', () => {
    expect(readQuickPrefs()).toEqual({ audio: true, mic: true, screen: false })
  })

  it('survives corrupt storage', () => {
    localStorage.setItem(QUICK_RECORD_KEY, '{not json')
    expect(readQuickPrefs()).toEqual({ audio: true, mic: true, screen: false })
  })

  it('tells people what the share picker will ask', () => {
    expect(shareHint({ audio: true, mic: true, screen: false })).toContain('Share system audio')
    expect(shareHint({ audio: false, mic: false, screen: true })).toContain('which screen or window')
    expect(shareHint({ audio: false, mic: true, screen: false })).toContain('Only your microphone')
  })
})
