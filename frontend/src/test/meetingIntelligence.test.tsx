/**
 * Meeting intelligence on the detail page: the visual summary renders only what the analysis
 * holds and every timestamp seeks the recording; the insights panel is honest about its states
 * and disappears when the server has the feature off; the assistant shows its citations.
 */
import React from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { VisualSummary } from '../ui/meetingsense/library/meeting-summary/VisualSummary'
import { InsightsPanel } from '../ui/meetingsense/library/InsightsPanel'
import { AssistantDrawer } from '../ui/meetingsense/library/AssistantDrawer'
import { analysisToMarkdown, stampToMs, type MeetingAnalysis, type VisualSpec } from '../ui/meetingsense/library/intelligenceApi'

const analysis: MeetingAnalysis = {
  schema_version: 1, meeting_id: 'm1', language: 'en', created_at: 1_772_272_800,
  title: 'Fixing domain status detection', one_line: 'The team confirmed the Langfuse move.',
  topics: [{ id: 't1', label: 'Domain status', t0_ms: 0, t1_ms: 30_000, summary: 'Unknown status is misread.' }],
  decisions: [
    { id: 'd1', statement: 'Move prompt management to Langfuse', status: 'confirmed', evidence: [{ segment_id: 's4', t0_ms: 22_000, quote: 'move prompt management to Langfuse' }], confidence: 0.8 },
    { id: 'd2', statement: 'Add an MX lookup', status: 'proposed', evidence: [{ segment_id: 's3', t0_ms: 15_000, quote: 'second lookup' }], confidence: 0.6 },
  ],
  risks: [{ id: 'r1', title: 'Unknown status treated as unregistered', severity: 'high', detail: 'The agent skips the DNS check.', root_cause: 'No consecutive lookups', solutions: ['Chain the DNS and MX checks'], status: 'open', evidence: [{ segment_id: 's2', t0_ms: 6_000, quote: 'treats unknown' }] }],
  action_items: [{ id: 'a1', text: 'Inject fifty annotation tickets', owner: 'Ebony', due_text: 'by Friday', status: 'open', evidence: [{ segment_id: 's5', t0_ms: 30_000, quote: 'inject fifty' }], confidence: 0.8 }],
  open_questions: [{ id: 'q1', text: 'Who owns the definition of unknown status?', evidence: [{ segment_id: 's6', t0_ms: 38_000, quote: 'Who owns' }] }],
  conclusions: [{ id: 'c1', text: 'Consecutive lookups and Langfuse-managed prompts are the two fixes.', evidence: [{ segment_id: 's2', t0_ms: 6_000, quote: 'treats unknown' }] }],
  speakers: [{ label: 'Ebony', talk_ms: 20_000, share: 0.5, lines: 2 }],
  degraded: null, model: 'qwen', validator: { kept: 5, dropped: 1, repaired: 0, notes: [] },
}

const spec: VisualSpec = {
  schema_version: 1, analysis_id: 'an1', template: 'autopilot', blocks: [
    { type: 'header', title: analysis.title, text: analysis.one_line, items: [], columns: [], rows: [], meta: { degraded: null } },
    { type: 'kpi_row', items: [], columns: [], rows: [], meta: { kpis: [{ label: 'Decisions', value: 2 }, { label: 'Risks', value: 1 }] } },
    { type: 'risk_cards', title: 'Risks and problems', items: ['r1'], columns: [], rows: [], meta: {} },
    { type: 'decision_list', title: 'Decisions', items: ['d1', 'd2'], columns: [], rows: [], meta: {} },
    { type: 'comparison_table', title: 'Decision status at a glance', items: [], columns: ['Decision', 'Status', 'Said at'], rows: [['Move prompt management to Langfuse', 'Confirmed', '00:00:22']], meta: { status_column: 1, time_column: 2 } },
    { type: 'timeline', title: 'Action items', items: ['a1'], columns: [], rows: [], meta: {} },
    { type: 'section', title: 'Still open', items: ['q1'], columns: [], rows: [], tone: 'amber', meta: {} },
    { type: 'callout', title: 'Key conclusion', text: analysis.conclusions[0].text, items: ['c1'], columns: [], rows: [], meta: {} },
  ],
}

type Route = (url: URL, init?: RequestInit) => { status?: number; body: unknown }
let routes: Array<[RegExp, Route]> = []
const calls: Array<{ url: string; method: string; body?: any }> = []
function respond(pattern: RegExp, fn: Route) { routes.push([pattern, fn]) }

beforeEach(() => {
  routes = []
  calls.length = 0
  sessionStorage.clear()
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://hp.test')
    const method = (init?.method || 'GET').toUpperCase()
    let body: any
    try { body = init?.body && typeof init.body === 'string' ? JSON.parse(init.body) : undefined } catch { body = undefined }
    calls.push({ url: url.pathname, method, body })
    for (const [pattern, fn] of routes) {
      if (pattern.test(`${method} ${url.pathname}`)) {
        const out = fn(url, init)
        return new Response(JSON.stringify(out.body), { status: out.status || 200, headers: { 'content-type': 'application/json' } })
      }
    }
    return new Response(JSON.stringify({ detail: 'not found' }), { status: 404, headers: { 'content-type': 'application/json' } })
  }))
})
afterEach(() => { vi.unstubAllGlobals() })

describe('VisualSummary', () => {
  it('renders every block from the analysis and seeks from any timestamp', () => {
    const onSeek = vi.fn()
    render(<VisualSummary analysis={analysis} spec={spec} onSeek={onSeek} />)
    expect(screen.getByRole('heading', { name: 'Fixing domain status detection' })).toBeInTheDocument()
    expect(screen.getByText('Unknown status treated as unregistered')).toBeInTheDocument()
    expect(screen.getByText('High priority')).toBeInTheDocument()
    expect(screen.getByText('Root cause:').parentElement).toHaveTextContent('No consecutive lookups')
    expect(screen.getAllByText('Confirmed').length).toBeGreaterThanOrEqual(2) // list pill and table pill
    expect(screen.getByText('Proposed')).toBeInTheDocument()
    expect(screen.getByTestId('vs-timeline')).toHaveTextContent('Ebony')
    expect(screen.getByTestId('vs-callout')).toHaveTextContent('Consecutive lookups')
    // Any timestamp plays the recording from that line.
    fireEvent.click(screen.getAllByRole('button', { name: 'Play from 00:00:22' })[0])
    expect(onSeek).toHaveBeenCalledWith(22_000)
    fireEvent.click(screen.getByRole('button', { name: 'Play from 00:00:30' }))
    expect(onSeek).toHaveBeenCalledWith(30_000)
  })

  it('says plainly when the page is extractive, and never shows items the analysis lacks', () => {
    const degraded = { ...analysis, degraded: 'extractive', decisions: [] }
    const thin: VisualSpec = { ...spec, blocks: [{ ...spec.blocks[0], meta: { degraded: 'extractive' } }, spec.blocks[3]] }
    render(<VisualSummary analysis={degraded} spec={thin} />)
    expect(screen.getByText(/No language model answered/)).toBeInTheDocument()
    expect(screen.queryByText('Decisions')).not.toBeInTheDocument() // an empty list block renders nothing
  })

  it('exports the analysis as readable Markdown with timestamps', () => {
    const md = analysisToMarkdown(analysis)
    expect(md).toContain('# Fixing domain status detection')
    expect(md).toContain('**Confirmed:** Move prompt management to Langfuse _(00:00:22)_')
    expect(md).toContain('- [ ] Inject fifty annotation tickets — Ebony (by Friday)')
    expect(stampToMs('00:12:34')).toBe(754_000)
  })
})

describe('InsightsPanel', () => {
  it('renders nothing when the server has the feature off', async () => {
    const { container } = render(<InsightsPanel meetingId="m1" hasTranscript />)
    await waitFor(() => expect(calls.some((c) => c.url.endsWith('/analysis'))).toBe(true))
    await waitFor(() => expect(container).toBeEmptyDOMElement())
  })

  it('offers to generate, then shows progress once the job is queued', async () => {
    let state: 'none' | 'pending' = 'none'
    respond(/GET .*\/analysis$/, () => ({ body: state === 'none' ? { state } : { state, job: { stage: 'analysing', progress: 0.3, state: 'running' } } }))
    respond(/POST .*\/analysis$/, () => { state = 'pending'; return { status: 202, body: { job: { id: 'j1', state: 'queued' }, state: 'pending' } } })
    render(<InsightsPanel meetingId="m1" hasTranscript />)
    const cta = await screen.findByRole('button', { name: /Generate insights/ })
    expect(screen.getByTestId('insights-cta')).toHaveTextContent('one-page summary')
    fireEvent.click(cta)
    await screen.findByTestId('insights-progress')
    expect(screen.getByTestId('insights-progress')).toHaveTextContent('analysing')
    expect(calls.filter((c) => c.method === 'POST').length).toBe(1)
  })

  const readyBody = () => ({
    state: 'ready', id: 'an1', created_at: 1_772_272_800, model: 'qwen', degraded: null, versions: 1,
    analysis, visual: spec, report: analysis.validator,
    questions: [{ id: 'sq1', text: 'What was decided about prompt management?', kind: 'decisions' }, { id: 'sq2', text: 'Who owns the tickets?', kind: 'actions' }],
  })

  it('shows the compact card with counts, the verification line and clickable suggested questions when ready', async () => {
    respond(/GET .*\/analysis$/, () => ({ body: readyBody() }))
    const onAsk = vi.fn()
    const onOpenVisual = vi.fn()
    render(<InsightsPanel meetingId="m1" hasTranscript onAsk={onAsk} onOpenVisual={onOpenVisual} />)
    const card = await screen.findByTestId('insights-compact')
    expect(card).toHaveTextContent('Fixing domain status detection')
    expect(card).toHaveTextContent('2 decisions')
    expect(card).toHaveTextContent('1 risks')
    expect(screen.getByText(/5 items verified against the transcript · 1 dropped/)).toBeInTheDocument()
    expect(screen.getByText('Model · qwen')).toBeInTheDocument()
    expect(screen.queryByTestId('visual-summary')).not.toBeInTheDocument() // the full page lives in its tab
    fireEvent.click(screen.getByRole('button', { name: /Open visual summary/ }))
    expect(onOpenVisual).toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: /What was decided about prompt management/ }))
    expect(onAsk).toHaveBeenCalledWith('What was decided about prompt management?')
    expect(screen.getByRole('button', { name: /Regenerate/ })).toBeEnabled()
  })

  it('shows the whole visual page in place when there is no tab to open', async () => {
    respond(/GET .*\/analysis$/, () => ({ body: readyBody() }))
    render(<InsightsPanel meetingId="m1" hasTranscript />)
    await screen.findByTestId('visual-summary')
    expect(screen.queryByTestId('insights-compact')).not.toBeInTheDocument()
  })

  it('waits for a transcript before offering anything', async () => {
    respond(/GET .*\/analysis$/, () => ({ body: { state: 'no_transcript' } }))
    render(<InsightsPanel meetingId="m1" hasTranscript={false} />)
    expect(await screen.findByText(/written once there is a transcript/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Generate insights/ })).not.toBeInTheDocument()
  })
})

describe('AssistantDrawer', () => {
  it('answers with citations that seek the recording, and asks a seeded question on open', async () => {
    respond(/POST .*\/ask$/, (_u, init) => {
      const q = JSON.parse(String(init?.body)).text as string
      return { body: { text: `Answer to: ${q}`, cited: ['00:00:22', '00:00:30'], degraded: null } }
    })
    const onSeek = vi.fn()
    const onSeeded = vi.fn()
    render(<AssistantDrawer meetingId="m1" open onClose={() => undefined} seed="What was decided?" onSeeded={onSeeded} onSeek={onSeek} hasTranscript />)
    expect(await screen.findByText('Answer to: What was decided?')).toBeInTheDocument()
    expect(onSeeded).toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Play from 00:00:30' }))
    expect(onSeek).toHaveBeenCalledWith(30_000)
    // A typed follow-up goes through the same route and the history keeps both turns.
    fireEvent.change(screen.getByLabelText('Ask a question about this meeting'), { target: { value: 'And who owns it?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))
    expect(await screen.findByText('Answer to: And who owns it?')).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'POST').length).toBe(2)
    expect(JSON.parse(sessionStorage.getItem('hp_meeting_assistant:m1') || '[]')).toHaveLength(2)
  })

  it('says when an answer is quoted from the transcript because no model answered', async () => {
    respond(/POST .*\/ask$/, () => ({ body: { text: 'From the meeting transcript:\n[00:00:22] we agreed', cited: ['00:00:22'], degraded: 'extractive' } }))
    render(<AssistantDrawer meetingId="m2" open onClose={() => undefined} seed="Anything?" hasTranscript />)
    expect(await screen.findByText(/No language model answered — these are the transcript lines/)).toBeInTheDocument()
  })
})
