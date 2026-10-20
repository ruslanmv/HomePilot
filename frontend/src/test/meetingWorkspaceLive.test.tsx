/**
 * The live meeting workspace: two lanes (Transcript, Ask), a transcript that reads like a
 * conversation and shows the line being spoken, a clock that ticks on its own, plain-language
 * problems instead of server codes, and nothing sitting on top of "End meeting".
 */
import React from 'react'
import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { MeetingWorkspace, friendlyMeetingError, groupTurns } from '../ui/meetingsense/MeetingWorkspace'
import { EMPTY_VIEW } from '../ui/meetingsense/meetingState'
import { DEFAULT_CAPTURE } from '../ui/meetingsense/CapturePopover'

const source = (over = {}) => ({
  requested: true, health: 'receiving', label: null, level: 0.05, error: null, lastSignalAt: null, ...over,
})

const STATUS = {
  meetingAudio: source(),
  microphone: source({ label: 'Microphone Array' }),
  screen: source({ requested: false, health: 'off', level: 0 }),
}

function renderWorkspace(view: Record<string, unknown>) {
  return render(
    <MeetingWorkspace
      view={{ ...EMPTY_VIEW, phase: 'live', meetingId: 'm1', ...view } as never}
      capture={DEFAULT_CAPTURE}
      captureStatus={STATUS as never}
      conversationId="conv"
      screenStream={null}
      record={null}
      pendingNotes={false}
      onEnd={vi.fn()}
      onMute={vi.fn()}
    />,
  )
}

beforeEach(() => {
  const shell = document.createElement('div')
  shell.className = 'hp-app-shell'
  shell.appendChild(document.createElement('main'))
  document.body.appendChild(shell)
  Element.prototype.scrollIntoView = vi.fn()
})

afterEach(() => {
  document.querySelectorAll('.hp-app-shell').forEach((node) => node.remove())
  vi.useRealTimers()
})

describe('live meeting workspace', () => {
  it('has two lanes and no Timeline', async () => {
    renderWorkspace({})
    expect(await screen.findByRole('tab', { name: /Transcript/ })).toBeTruthy()
    expect(screen.getByRole('tab', { name: /Ask/ })).toBeTruthy()
    expect(screen.queryByText(/Timeline/)).toBeNull()
  })

  it('says it is listening before the first words arrive', async () => {
    renderWorkspace({})
    expect((await screen.findByTestId('ms-workspace-listening')).textContent).toContain('Listening…')
    expect(screen.getByTestId('ms-workspace-state').textContent).toBe('Recording')
  })

  it('groups lines by speaker and shows the line still being spoken', async () => {
    renderWorkspace({
      segments: [
        { id: 'a', t0: 1000, t1: 3000, speaker: 'them', text: 'the launch moves to October' },
        { id: 'b', t0: 3200, t1: 5000, speaker: 'them', text: 'pricing is agreed' },
        { id: 'c', t0: 6000, t1: 8000, speaker: 'me', text: 'great, I will tell the team' },
      ],
      partial: { t0: 9000, speaker: 'them', text: 'one more thing about' },
    })
    const transcript = await screen.findByLabelText('Live transcript')
    expect(transcript.textContent).toContain('the launch moves to October')
    expect(transcript.textContent).toContain('great, I will tell the team')
    expect(screen.getByTestId('ms-workspace-partial').textContent).toContain('one more thing about')
    expect(screen.getByTestId('ms-transcript-count').textContent).toBe('3')
    // Each line keeps its anchor so a citation in Ask can jump to it.
    expect(transcript.querySelector('[data-segment-id="b"]')).not.toBeNull()
  })

  it('keeps its clock moving between server status frames', async () => {
    vi.useFakeTimers()
    renderWorkspace({ elapsedMs: 0 })
    expect(screen.getByTestId('ms-workspace-elapsed').textContent).toBe('00:00')
    await act(async () => { vi.advanceTimersByTime(3100) })
    expect(screen.getByTestId('ms-workspace-elapsed').textContent).toBe('00:03')
  })

  it('moves the chat header buttons out of the way while it is open', () => {
    const { unmount } = renderWorkspace({})
    expect(document.body.classList.contains('hp-meeting-open')).toBe(true)
    unmount()
    expect(document.body.classList.contains('hp-meeting-open')).toBe(false)
  })

  it('explains a restart in words, not server codes', async () => {
    renderWorkspace({ notice: 'Recording continues. What was said before the restart is saved as its own meeting.' })
    expect((await screen.findByTestId('ms-workspace-notice')).textContent).toContain('Recording continues')
  })

  it('never shows a raw server error', async () => {
    renderWorkspace({ error: 'session is idle, not live' })
    const alert = await screen.findByTestId('ms-workspace-error')
    expect(alert.textContent).not.toContain('session is idle')
    expect(alert.textContent).toContain('connection to HomePilot dropped')
  })
})

describe('helpers', () => {
  it('maps the codes people should never see', () => {
    expect(friendlyMeetingError('session is idle, not live')).toMatch(/connection to HomePilot dropped/)
    expect(friendlyMeetingError('that meeting is not resumable')).toMatch(/could not continue/)
    expect(friendlyMeetingError('the session socket closed')).toMatch(/Reconnecting/)
    expect(friendlyMeetingError('Microphone permission was denied')).toBe('Microphone permission was denied')
    expect(friendlyMeetingError(null)).toBeNull()
  })

  it('starts a new turn when the speaker changes or after a long pause', () => {
    const turns = groupTurns([
      { id: '1', t0: 0, t1: 1000, speaker: 'me', text: 'a' },
      { id: '2', t0: 1500, t1: 2000, speaker: 'me', text: 'b' },
      { id: '3', t0: 2500, t1: 3000, speaker: 'them', text: 'c' },
      { id: '4', t0: 60000, t1: 61000, speaker: 'them', text: 'd' },
    ] as never)
    expect(turns.map((t) => t.lines.map((l) => l.text).join(''))).toEqual(['ab', 'c', 'd'])
  })
})
