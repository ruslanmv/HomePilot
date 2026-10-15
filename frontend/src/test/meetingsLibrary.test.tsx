/**
 * Meetings Library: honest status chips, readable summaries, the library grid, the details
 * panel that can be hidden and stays hidden, and a wizard that records nothing by itself.
 */
import React from 'react'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  isFallbackSummary,
  overviewSummary,
  plainText,
  statusChip,
} from '../ui/meetingsense/library/format'
import { MeetingsHome } from '../ui/meetingsense/library/MeetingsHome'
import { MeetingDetailPage } from '../ui/meetingsense/library/MeetingDetailPage'
import { StartMeetingWizard, summaryStyleFor } from '../ui/meetingsense/library/StartMeetingWizard'
import { resample } from '../ui/meetingsense/library/WaveformPlayer'
import type { LibraryItem } from '../ui/meetingsense/library/api'

const OUTLINE =
  "*No language model was reachable, so this is assembled from the meeting's own words rather than written.*\n\n" +
  '## The meeting in order\n\n**00:00:05–00:01:18** — A modular approach.'

function item(over: Partial<LibraryItem> = {}): LibraryItem {
  return {
    library_id: 'm1', meeting_id: 'm1', origin_type: 'import', origin_id: 'm1', title: 'Architecture Review',
    description: 'Discussed system architecture.', category: 'Project Meeting', started_at: 1772272800, ended_at: null,
    scheduled_for: null, duration_ms: 3_120_000, projects: [{ id: 'p1', name: 'HomePilot' }],
    source: { kind: 'upload', label: 'Upload' }, media_present: true, recording_state: 'present',
    transcript_state: 'ready', summary_state: 'ready', segments: 3, conversation_id: null, status: 'completed',
    live: false, warnings: [], ...over,
  }
}

type Route = (url: URL, init?: RequestInit) => unknown
let routes: Array<[RegExp, Route]> = []
const calls: Array<{ url: string; method: string; body?: any }> = []

function respond(pattern: RegExp, fn: Route) {
  routes.push([pattern, fn])
}

beforeEach(() => {
  routes = []
  calls.length = 0
  localStorage.clear()
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://hp.test')
    const method = (init?.method || 'GET').toUpperCase()
    let body: any
    try { body = init?.body && typeof init.body === 'string' ? JSON.parse(init.body) : undefined } catch { body = undefined }
    calls.push({ url: url.pathname + url.search, method, body })
    for (const [pattern, fn] of routes) {
      if (pattern.test(`${method} ${url.pathname}`)) {
        return new Response(JSON.stringify(fn(url, init)), { status: 200, headers: { 'content-type': 'application/json' } })
      }
    }
    return new Response(JSON.stringify({ detail: 'not mocked' }), { status: 404 })
  }))
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('status chips', () => {
  it('never calls an empty or silent recording transcribed', () => {
    expect(statusChip(item({ transcript_state: 'no_speech' })).label).toBe('No speech')
    expect(statusChip(item({ transcript_state: 'none', media_present: true })).label).toBe('Needs Transcript')
    expect(statusChip(item({ transcript_state: 'none', media_present: false, recording_state: 'awaiting' })).label).toBe('Awaiting recording')
    expect(statusChip(item({ transcript_state: 'needs_setup' })).label).toBe('Needs setup')
    expect(statusChip(item({ transcript_state: 'transcript_only' })).label).toBe('Transcript only')
    expect(statusChip(item({ live: true })).label).toBe('Recording')
  })
})

describe('summaries', () => {
  it('skips the no-model outline and falls back to notes or the description', () => {
    expect(isFallbackSummary({ text: OUTLINE })).toBe(true)
    expect(overviewSummary([{ text: OUTLINE }], 'Notes summary.', 'Description.')).toEqual({ text: 'Notes summary.', markdown: false })
    expect(overviewSummary([{ text: OUTLINE }], '', 'Description.')).toEqual({ text: 'Description.', markdown: false })
  })

  it('shows the written summary without its long outline', () => {
    const doc = { text: '## Summary\n\nWe chose **React Native**.\n\n## The meeting in order\n\n**00:00** — long outline' }
    const out = overviewSummary([{ text: OUTLINE }, doc], 'notes', 'desc')
    expect(out.markdown).toBe(true)
    expect(out.text).toContain('React Native')
    expect(out.text).not.toContain('meeting in order')
    expect(plainText(out.text)).toBe('Summary\n\nWe chose React Native.')
  })

  it('maps the chosen outputs to a summary style', () => {
    expect(summaryStyleFor(['transcript', 'minutes'])).toBe('minutes')
    expect(summaryStyleFor(['summary', 'actions'])).toBe('notes')
    expect(summaryStyleFor(['actions'])).toBe('actions')
  })
})

describe('waveform', () => {
  it('keeps the loudest peak of each bucket when there are more peaks than bars', () => {
    expect(resample([0.1, 0.9, 0.2, 0.3, 0.8, 0.1], 3)).toEqual([0.9, 0.3, 0.8])
    expect(resample([0.5, 0.4], 10)).toEqual([0.5, 0.4])
    expect(resample(Array.from({ length: 400 }, (_, i) => i / 400), 100)).toHaveLength(100)
  })
})

describe('Meetings home', () => {
  it('lists meetings as cards and asks the server for the chosen tab', async () => {
    respond(/GET \/v1\/meetingsense\/library$/, (url) => ({
      items: url.searchParams.get('tab') === 'imported'
        ? [item({ library_id: 'm2', meeting_id: 'm2', title: 'Imported meeting · Oct 10, 12:31', transcript_state: 'no_speech' })]
        : [item(), item({ library_id: 's1', meeting_id: 's1', title: 'Sprint Planning', origin_type: 'scheduled', transcript_state: 'none', media_present: false, recording_state: 'awaiting' })],
      next_cursor: null, total: 2, counts: {}, facets: { sources: [], projects: [] },
    }))
    respond(/GET \/v1\/meetingsense\/jobs/, () => ({ jobs: [], stt: { available: true } }))
    const onOpen = vi.fn()
    render(<MeetingsHome status={{ enabled: true }} onOpen={onOpen} />)

    const grid = await screen.findByTestId('meetings-grid')
    expect(within(grid).getByText('Architecture Review')).toBeTruthy()
    expect(within(grid).getByText('Awaiting recording')).toBeTruthy()
    // Icon-only on phones, so the header actions carry their names themselves.
    for (const name of ['New Meeting', 'Import Files', 'Folder Sync']) expect(screen.getByRole('button', { name })).toBeTruthy()

    fireEvent.click(screen.getByTestId('meetings-tab-imported'))
    await screen.findByText('Imported meeting · Oct 10, 12:31')
    expect(screen.getByText('No speech')).toBeTruthy()
    expect(calls.some((c) => c.url.includes('tab=imported'))).toBe(true)
    expect(localStorage.getItem('hp_meetings_tab')).toBe('imported')

    fireEvent.click(screen.getByTestId('meeting-card-m2'))
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ library_id: 'm2' }))
  })
})

describe('Meeting detail', () => {
  function detail(over: Record<string, unknown> = {}) {
    return {
      item: item(),
      segments: [
        { id: 'a', t0_ms: 5000, t1_ms: 9000, speaker: 'Jane Smith', text: "Let's start with the architecture proposal." },
        { id: 'b', t0_ms: 16000, t1_ms: 20000, speaker: 'Michael Lee', text: 'A modular approach works.' },
      ],
      notes: { version: 1, updated_at: 0, notes: { summary: 'Agreed on a modular architecture.', decisions: ['Adopt React Native.'], actions: [{ text: 'Write the design doc', owner: 'Sarah Park', due: 'Mar 7' }] } },
      summaries: [{ id: 's1', text: OUTLINE, degraded: 'extractive', created_at: 1772272900 }],
      assets: [], jobs: [], versions: [{ id: 'v1', origin: 'import', timing: 'imported', active: 1, segment_count: 2, provider: null, model: null, language: null, note: null, created_at: 0 }],
      ...over,
    }
  }

  it('shows the notes instead of the raw outline, and remembers a hidden panel', async () => {
    localStorage.setItem('hp_meeting_details_open', '1')
    respond(/GET \/v1\/meetingsense\/library\/item\/m1$/, () => detail())
    const { unmount } = render(<MeetingDetailPage libraryId="m1" onBack={() => undefined} />)

    await screen.findByRole('heading', { name: 'Architecture Review' })
    expect(screen.getAllByText('Agreed on a modular architecture.').length).toBeGreaterThan(0)
    expect(screen.queryByText(/No language model was reachable/)).toBeNull()
    expect(screen.getByText('Adopt React Native.')).toBeTruthy()

    const panel = screen.getByRole('complementary', { name: 'Meeting details' })
    expect(within(panel).getByText('Write the design doc')).toBeTruthy()

    const toggle = screen.getByTestId('details-toggle')
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    fireEvent.click(toggle)
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(screen.queryByRole('complementary', { name: 'Meeting details' })).toBeNull()
    expect(localStorage.getItem('hp_meeting_details_open')).toBe('0')
    unmount()

    render(<MeetingDetailPage libraryId="m1" onBack={() => undefined} />)
    await screen.findByRole('heading', { name: 'Architecture Review' })
    expect(screen.queryByRole('complementary', { name: 'Meeting details' })).toBeNull()
    expect(screen.getByTestId('details-toggle').textContent).toContain('Show details')
  })

  it('resizes the details panel from the keyboard within its limits', async () => {
    localStorage.setItem('hp_meeting_details_open', '1')
    respond(/GET \/v1\/meetingsense\/library\/item\/m1$/, () => detail())
    render(<MeetingDetailPage libraryId="m1" onBack={() => undefined} />)
    const handle = await screen.findByRole('separator', { name: 'Resize details' })
    expect(handle.getAttribute('aria-valuenow')).toBe('360')
    fireEvent.keyDown(handle, { key: 'ArrowLeft' })
    expect(handle.getAttribute('aria-valuenow')).toBe('380')
    for (let i = 0; i < 20; i += 1) fireEvent.keyDown(handle, { key: 'ArrowLeft' })
    expect(handle.getAttribute('aria-valuenow')).toBe('520')
    expect(localStorage.getItem('hp_meeting_details_width')).toBe('520')
  })

  it('renders a written summary as text, not markdown symbols', async () => {
    localStorage.setItem('hp_meeting_details_open', '1')
    respond(/GET \/v1\/meetingsense\/library\/item\/m1$/, () => detail({
      notes: null,
      summaries: [{ id: 's2', text: '## Decisions\n\n- Keep **Kubernetes**.', created_at: 1772272900 }],
    }))
    render(<MeetingDetailPage libraryId="m1" onBack={() => undefined} />)
    const strong = await screen.findByText('Kubernetes')
    expect(strong.tagName).toBe('STRONG')
    expect(screen.queryByText(/\*\*Kubernetes\*\*/)).toBeNull()
  })

  it('says plainly why a silent recording has no transcript', async () => {
    respond(/GET \/v1\/meetingsense\/library\/item\/m3$/, () => detail({
      item: item({ library_id: 'm3', meeting_id: 'm3', transcript_state: 'no_speech', summary_state: 'none',
        warnings: ['No speech detected — the recording is silent (loudest moment -70.3 dB).'] }),
      segments: [], notes: null, summaries: [], versions: [],
    }))
    render(<MeetingDetailPage libraryId="m3" onBack={() => undefined} />)
    expect(await screen.findByText('No speech was detected in the recording.')).toBeTruthy()
    expect(screen.getByText(/loudest moment -70.3 dB/)).toBeTruthy()
  })
})

describe('Start a meeting wizard', () => {
  it('needs a title, then schedules the meeting without recording anything', async () => {
    respond(/GET \/projects$/, () => ({ projects: [{ id: 'p1', name: 'HomePilot' }] }))
    respond(/POST \/v1\/meetingsense\/library\/meetings$/, () => ({ meeting_id: 'new1' }))
    const onCreated = vi.fn()
    render(<StartMeetingWizard onClose={() => undefined} onCreated={onCreated} />)

    fireEvent.click(screen.getByRole('button', { name: /Next: Recording source/ }))
    expect(screen.getByRole('alert').textContent).toContain('Give the meeting a title.')

    fireEvent.change(screen.getByPlaceholderText('Project planning meeting'), { target: { value: 'Q4 roadmap review' } })
    fireEvent.click(screen.getByText('Schedule for later'))
    fireEvent.click(screen.getByRole('button', { name: /Next: Recording source/ }))
    fireEvent.click(screen.getByRole('button', { name: /Next: Assistant/ }))
    fireEvent.click(screen.getByRole('button', { name: /Next: Summary/ }))
    fireEvent.click(screen.getByRole('button', { name: /Schedule meeting/ }))

    await waitFor(() => expect(onCreated).toHaveBeenCalled())
    const post = calls.find((c) => c.method === 'POST' && c.url.startsWith('/v1/meetingsense/library/meetings'))
    expect(post?.body?.title).toBe('Q4 roadmap review')
    expect(post?.body?.scheduled_for).toBeGreaterThan(Date.now() / 1000)
    expect(calls.some((c) => /\/ws|\/start/.test(c.url))).toBe(false)
  })
})
