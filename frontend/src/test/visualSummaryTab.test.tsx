/**
 * The Visual Summary tab: the Executive Brief renders only what the server verified, numbers
 * the sections that have content and hides the rest, shows decision status exactly as
 * verified, and every stamp leads back to the transcript. The toolbar re-writes, exports and
 * presents the same brief without inventing anything.
 */
import React from 'react'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ExecutiveBriefView } from '../ui/meetingsense/library/meeting-summary/ExecutiveBrief'
import { VisualSummaryTab } from '../ui/meetingsense/library/VisualSummaryTab'
import { slidesFor } from '../ui/meetingsense/library/PresentMode'
import { printBrief, safeFilename } from '../ui/meetingsense/library/briefExport'
import type { ExecutiveBrief, MeetingAnalysis, VisualSpec } from '../ui/meetingsense/library/intelligenceApi'
import type { LibraryItem } from '../ui/meetingsense/library/api'

const analysis: MeetingAnalysis = {
  schema_version: 1, meeting_id: 'm1', language: 'en', created_at: 1_772_272_800,
  title: 'Agent debugging sync', one_line: 'The team confirmed the Langfuse move.',
  topics: [],
  decisions: [
    { id: 'd1', statement: 'Move prompt management to Langfuse', status: 'confirmed', evidence: [{ segment_id: 's4', t0_ms: 22_000, quote: 'move prompt management to Langfuse' }], confidence: 0.8 },
    { id: 'd2', statement: 'Add an MX record lookup before deciding', status: 'proposed', evidence: [{ segment_id: 's3', t0_ms: 15_000, quote: 'second lookup' }], confidence: 0.6 },
  ],
  risks: [
    { id: 'r1', title: 'Unknown status treated as unregistered', severity: 'high', detail: 'The agent skips the DNS check.', root_cause: 'No consecutive lookups', solutions: [], status: 'open', evidence: [{ segment_id: 's2', t0_ms: 6_000, quote: 'treats unknown' }] },
    { id: 'r2', title: 'MX lookup tool missing in the test environment', severity: 'medium', detail: 'The MX record tool is unavailable.', root_cause: '', solutions: [], status: 'open', evidence: [{ segment_id: 's7', t0_ms: 44_000, quote: 'missing MX record tool' }] },
  ],
  action_items: [
    { id: 'a1', text: 'Inject fifty annotation tickets', owner: 'Ebony', due_text: 'by Friday', status: 'open', evidence: [{ segment_id: 's5', t0_ms: 30_000, quote: 'inject fifty' }], confidence: 0.8 },
    { id: 'a2', text: 'Ask the business systems team for access', owner: 'Vasi', due_text: 'next week', status: 'open', evidence: [{ segment_id: 's8', t0_ms: 52_000, quote: 'business systems team' }], confidence: 0.7 },
  ],
  open_questions: [{ id: 'q1', text: 'Who owns the definition of unknown status?', evidence: [{ segment_id: 's6', t0_ms: 38_000, quote: 'Who owns' }] }],
  conclusions: [{ id: 'c1', text: 'Consecutive lookups and Langfuse-managed prompts are the two fixes.', evidence: [{ segment_id: 's2', t0_ms: 6_000, quote: 'treats unknown' }] }],
  speakers: [], degraded: null, model: 'qwen', validator: { kept: 7, dropped: 0, repaired: 0, notes: [] },
}

const brief: ExecutiveBrief = {
  eyebrow: 'Technical meeting · Executive brief',
  title: 'Domain status fixes and Langfuse prompt management',
  intro: 'The team traced agent failures to unknown domain status handling.',
  risks: [{ item: 'r1', title: 'Ambiguous domain status handling', summary: 'Unknown statuses are treated as unregistered.', note: 'No consecutive lookups', severity: 'high', polished: true }],
  blockers: [{ item: 'r2', title: 'MX lookup tool missing in the test environment', summary: 'The MX record tool is unavailable.', note: '', severity: 'medium', polished: false }],
  decisions: [
    { item: 'd1', option: 'Langfuse prompt management', status: 'confirmed', status_label: 'Selected', impact: 'Prompt changes without a redeploy.', polished: true },
    { item: 'd2', option: 'Add an MX record lookup before deciding', status: 'proposed', status_label: 'Proposed', impact: '', polished: false },
  ],
  actions: [
    { item: 'a1', bucket: 'This week', label: 'This week', text: 'Inject fifty annotation tickets', owner: 'Ebony', polished: false },
    { item: 'a2', bucket: 'Next steps', label: 'Next steps', text: 'Ask the business systems team for access', owner: 'Vasi', polished: false },
  ],
  open_questions: ['q1'],
  takeaway: 'Chain the DNS and MX checks and move prompt management to Langfuse.', takeaway_items: ['r1', 'd1'],
  source_count: 7, polished: true, notes: ['d2: proposal kept in its own words.'],
}
const spec: VisualSpec = { schema_version: 1, analysis_id: 'an1', template: 'executive_brief', blocks: [], brief }
const item = {
  title: 'Agent debugging sync', started_at: 1_772_272_800, scheduled_for: null, duration_ms: 1_500_000,
  projects: [{ id: 'p1', name: 'Agents' }], source: { kind: 'import', label: 'Imported' },
} as unknown as LibraryItem

type Route = (url: URL, init?: RequestInit) => { status?: number; body: unknown }
let routes: Array<[RegExp, Route]> = []
const calls: Array<{ url: string; method: string }> = []
function respond(pattern: RegExp, fn: Route) { routes.push([pattern, fn]) }

beforeEach(() => {
  routes = []
  calls.length = 0
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://hp.test')
    const method = (init?.method || 'GET').toUpperCase()
    calls.push({ url: url.pathname, method })
    for (const [pattern, fn] of routes) {
      if (pattern.test(`${method} ${url.pathname}`)) {
        const out = fn(url, init)
        return new Response(JSON.stringify(out.body), { status: out.status || 200, headers: { 'content-type': 'application/json' } })
      }
    }
    return new Response(JSON.stringify({ detail: 'not found' }), { status: 404, headers: { 'content-type': 'application/json' } })
  }))
})
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

const readyBody = () => ({
  state: 'ready', id: 'an1', created_at: 1_772_272_800, model: 'qwen', degraded: null, versions: 1,
  analysis, visual: spec, report: analysis.validator,
  questions: [{ id: 'sq1', text: 'What was decided about prompt management?', kind: 'decisions' }],
})

describe('ExecutiveBriefView', () => {
  it('numbers the sections that have content, derives pills from verified status, and leads to the source', () => {
    const onEvidence = vi.fn()
    render(<ExecutiveBriefView analysis={analysis} brief={brief} onEvidence={onEvidence} meta={{ date: '2 Mar 2026', duration: '25 min' }} />)
    expect(screen.getByRole('heading', { name: 'Domain status fixes and Langfuse prompt management' })).toBeInTheDocument()
    expect(screen.getByText('01 / Core risks & blockers')).toBeInTheDocument()
    expect(screen.getByText('02 / Decision comparison')).toBeInTheDocument()
    expect(screen.getByText('03 / Next actions')).toBeInTheDocument()
    expect(screen.getByText('04 / Still open')).toBeInTheDocument()
    expect(screen.getByTestId('brief-card-r1')).toHaveTextContent('HIGH PRIORITY')
    expect(screen.getByTestId('brief-card-r2')).toHaveTextContent('BLOCKER')
    // Status pills come from the verified status, never from the wording.
    expect(screen.getByTestId('brief-row-d1')).toHaveTextContent('Selected')
    expect(screen.getByTestId('brief-row-d2')).toHaveTextContent('Proposed')
    expect(screen.getByTestId('brief-timeline')).toHaveTextContent('This week')
    expect(screen.getByTestId('brief-timeline')).toHaveTextContent('Next steps')
    expect(screen.getByTestId('brief-takeaway')).toHaveTextContent('Chain the DNS and MX checks')
    expect(screen.getByText(/Grounded in 7 transcript moments/)).toBeInTheDocument()
    expect(screen.getByText(/2 Mar 2026 · 25 min/)).toBeInTheDocument()
    // d1 is cited twice (its row and the takeaway); either stamp opens the same line.
    fireEvent.click(screen.getAllByRole('button', { name: 'View source at 00:00:22' })[0])
    expect(onEvidence).toHaveBeenCalledWith(22_000, 'd1')
  })

  it('hides empty sections and renumbers the rest, and never invents a blocker or a question', () => {
    const thin: ExecutiveBrief = { ...brief, risks: [], blockers: [], open_questions: [], actions: [brief.actions[0]] }
    render(<ExecutiveBriefView analysis={analysis} brief={thin} />)
    expect(screen.queryByText(/Core risks/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Still open/)).not.toBeInTheDocument()
    expect(screen.getByText('01 / Decision comparison')).toBeInTheDocument()
    expect(screen.getByText('02 / Next actions')).toBeInTheDocument()
    // Without a handler, stamps are plain text: nothing to click, nothing broken.
    expect(screen.queryByRole('button', { name: /View source/ })).not.toBeInTheDocument()
    expect(screen.getAllByText('00:00:22').length).toBeGreaterThan(0) // the decision row and the takeaway both cite d1
  })

  it('presents only the sections that exist as slides', () => {
    expect(slidesFor(brief)).toEqual([['header'], ['risks'], ['decisions'], ['actions'], ['questions'], ['takeaway', 'footer']])
    expect(slidesFor({ ...brief, actions: [], open_questions: [], takeaway: '' })).toEqual([['header'], ['risks'], ['decisions']])
  })
})

describe('VisualSummaryTab', () => {
  it('offers to generate when nothing exists yet, and queues the analysis', async () => {
    let state = 'none'
    respond(/GET .*\/analysis$/, () => ({ body: state === 'none' ? { state } : { state, job: { stage: 'writing the brief', progress: 0.6, state: 'running' } } }))
    respond(/POST .*\/analysis$/, () => { state = 'pending'; return { status: 202, body: { job: { id: 'j1', state: 'queued' }, state: 'pending' } } })
    render(<VisualSummaryTab meetingId="m1" item={item} hasTranscript />)
    fireEvent.click(await screen.findByRole('button', { name: /Generate visual summary/ }))
    await screen.findByTestId('visual-progress')
    expect(screen.getByTestId('visual-progress')).toHaveTextContent('writing the brief')
    expect(calls.filter((c) => c.method === 'POST').map((c) => c.url)).toEqual(['/v1/meetingsense/library/item/m1/analysis'])
  })

  it('renders the brief, rewrites it on request without re-analysing, and leads from the footer to the first source', async () => {
    respond(/GET .*\/analysis$/, () => ({ body: readyBody() }))
    respond(/POST .*\/visual$/, () => ({ status: 202, body: { job: { id: 'j2', state: 'queued' }, state: 'pending' } }))
    const onEvidence = vi.fn()
    const onAsk = vi.fn()
    render(<VisualSummaryTab meetingId="m1" item={item} hasTranscript onEvidence={onEvidence} onAsk={onAsk} />)
    await screen.findByTestId('executive-brief')
    expect(screen.getByTestId('visual-footer')).toHaveTextContent('Grounded in 7 referenced transcript moments')
    expect(screen.getByText(/AI-written wording · verified · qwen/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /View source evidence/ }))
    expect(onEvidence).toHaveBeenCalledWith(6_000, 'r1')
    fireEvent.click(screen.getByRole('button', { name: 'View source at 00:00:44' }))
    expect(onEvidence).toHaveBeenCalledWith(44_000, 'r2')
    fireEvent.click(screen.getByRole('button', { name: /What was decided about prompt management/ }))
    expect(onAsk).toHaveBeenCalledWith('What was decided about prompt management?')
    fireEvent.click(screen.getByRole('button', { name: /Rewrite brief/ }))
    await waitFor(() => expect(calls.filter((c) => c.method === 'POST').map((c) => c.url)).toEqual(['/v1/meetingsense/library/item/m1/visual']))
    // The validation notes are there for whoever wants them, folded away by default.
    fireEvent.click(screen.getByRole('button', { name: /What was checked/ }))
    expect(screen.getByText('d2: proposal kept in its own words.')).toBeInTheDocument()
  })

  it('presents the same brief as slides, moves with the keyboard, and leaves on Escape', async () => {
    respond(/GET .*\/analysis$/, () => ({ body: readyBody() }))
    render(<VisualSummaryTab meetingId="m1" item={item} hasTranscript />)
    await screen.findByTestId('executive-brief')
    fireEvent.click(screen.getByRole('button', { name: /Present/ }))
    const stage = screen.getByTestId('present-mode')
    expect(screen.getByTestId('present-counter')).toHaveTextContent('1 / 6')
    expect(stage).toHaveTextContent('Domain status fixes and Langfuse prompt management')
    fireEvent.keyDown(document, { key: 'ArrowRight' })
    expect(screen.getByTestId('present-counter')).toHaveTextContent('2 / 6')
    expect(stage).toHaveTextContent('Core risks & blockers')
    fireEvent.keyDown(document, { key: 'End' })
    expect(screen.getByTestId('present-counter')).toHaveTextContent('6 / 6')
    expect(stage).toHaveTextContent('Core takeaway')
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByTestId('present-mode')).not.toBeInTheDocument()
  })

  it('says when the feature is off, and waits for a transcript', async () => {
    const { unmount } = render(<VisualSummaryTab meetingId="m1" item={item} hasTranscript />)
    expect(await screen.findByText(/turned off on this server/)).toBeInTheDocument()
    unmount()
    respond(/GET .*\/analysis$/, () => ({ body: { state: 'no_transcript' } }))
    render(<VisualSummaryTab meetingId="m2" item={item} hasTranscript={false} />)
    expect(await screen.findByText(/written once there is a transcript/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Generate visual summary/ })).not.toBeInTheDocument()
  })
})

describe('exports', () => {
  it('prints a clone of the report on its own and cleans up afterwards', () => {
    vi.useFakeTimers()
    const print = vi.fn()
    vi.stubGlobal('print', print)
    const report = document.createElement('div')
    report.innerHTML = '<article class="hp-brief">Brief</article>'
    document.body.appendChild(report)
    printBrief(report)
    act(() => { vi.advanceTimersByTime(60) })
    expect(print).toHaveBeenCalledTimes(1)
    expect(document.getElementById('hp-print-root')).toHaveTextContent('Brief')
    expect(document.body.classList.contains('hp-print-brief')).toBe(true)
    act(() => { vi.advanceTimersByTime(1600) })
    expect(document.getElementById('hp-print-root')).toBeNull()
    expect(document.body.classList.contains('hp-print-brief')).toBe(false)
    report.remove()
  })

  it('names files after the meeting, safely', () => {
    expect(safeFilename('Agent sync: Q3 / review!', 'visual-summary')).toBe('agent-sync-q3-review-visual-summary')
    expect(safeFilename('', 'visual-summary')).toBe('meeting-visual-summary')
  })
})
