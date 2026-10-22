/**
 * The Expert stream, read event by event: tokens to the active step or the answer, tool
 * chips that start and finish, numbered sources, the verdict, the final answer, and a Deep
 * research job's plan.
 */
import { describe, expect, it } from 'vitest'

import {
  applyDeepDone,
  applyExpertEvent,
  initialExpertState,
  parseExpertSse,
  sourcesAsWeb,
  traceHasWork,
  type ExpertEvent,
  type ExpertStreamState,
} from '../ui/lib/expertStream'
import { deepGateFrom, deepOptionState, UNKNOWN_GATE } from '../ui/lib/expertCapabilities'
import { isTrivialPrompt } from '../ui/lib/promptHeuristics'
import { COMPACTED_NOTE } from '../ui/lib/expertStream'

function run(events: ExpertEvent[], mode?: string): ExpertStreamState {
  return events.reduce((s, ev) => applyExpertEvent(s, ev), initialExpertState(mode))
}

describe('the SSE parser', () => {
  it('reads named events, plain tokens with escaped newlines, keep-alives and [DONE]', () => {
    const wire =
      'event: meta\ndata: {"thinking_mode":"think","model":"qwen3:32b","notices":[]}\n\n' +
      'event: step\ndata: {"step":"analyze","label":"🔍 Analyzing problem…","role":"work"}\n\n' +
      'data: line one\\nline two\n\n' +
      ': keep-alive\n\n' +
      'event: tool\ndata: {"phase":"start","id":"c1","name":"hp_web_search","label":"Searching the web for “x”"}\n\n' +
      'data: [DONE]\n\n' +
      'event: step\ndata: {"step":"incompl'
    const { events, rest } = parseExpertSse(wire)
    expect(events.map((e) => e.type)).toEqual(['meta', 'step', 'token', 'tool', 'end'])
    expect((events[2] as any).text).toBe('line one\nline two')
    expect(rest.startsWith('event: step')).toBe(true)              // the partial block waits
    expect(parseExpertSse('event: bogus\ndata: {"a":1}\n\n').events).toEqual([])
    expect(parseExpertSse('event: sources\ndata: not json\n\n').events).toEqual([])
  })
})

describe('the reducer', () => {
  it('routes tokens to the active step, then to the answer after final_answer', () => {
    const s = run([
      { type: 'meta', data: { thinking_mode: 'think', model: 'm' } },
      { type: 'step', step: 'analyze', label: 'Analyzing', role: 'work' },
      { type: 'token', text: 'thinking…' },
      { type: 'step_end', step: 'analyze' },
      { type: 'step', step: 'solve', label: 'Solving', role: 'answer' },
      { type: 'token', text: 'draft' },
      { type: 'step_end', step: 'solve' },
      { type: 'final_answer' },
      { type: 'token', text: 'The answer.' },
      { type: 'done', data: { content: 'The answer.', sources: [], notices: ['note'] } },
    ])
    expect(s.trace.steps.map((x) => [x.step, x.status, x.content])).toEqual([
      ['analyze', 'done', 'thinking…'], ['solve', 'done', 'draft'],
    ])
    expect(s.text).toBe('The answer.')
    expect(s.done).toBe(true)
    expect(s.trace.notices).toEqual(['note'])
    expect(s.trace.model).toBe('m')
  })

  it('reads sequence ids, the project, the effort and the verdict detail', () => {
    const { events } = parseExpertSse('id: 7\nevent: status\ndata: {"status":"writing"}\n\nid: 8\ndata: tok\n\n')
    expect(events.map((e) => e.seq)).toEqual([7, 8])
    const s = run([
      { type: 'meta', data: { thinking_mode: 'heavy', effort: { level: 'direct', reason: 'a short message needs no verification' }, project: { id: 'p1', name: 'Launch' } } },
      { type: 'token', text: 'Hello!' },
      { type: 'verdict', verdict: 'needs_review', note: 'doubts', detail: { issues: [{ severity: 'high', text: 'date?' }], method: 'model review', limitations: 'none' } },
      { type: 'done', data: { content: 'Hello!' }, seq: 9 },
    ])
    expect(s.text).toBe('Hello!')                                                  // direct: tokens are the answer
    expect(s.trace.effort).toEqual({ level: 'direct', reason: 'a short message needs no verification' })
    expect(s.trace.project).toEqual({ id: 'p1', name: 'Launch' })
    expect(s.trace.verdict).toEqual({ verdict: 'needs_review', note: 'doubts', issues: [{ severity: 'high', text: 'date?' }], method: 'model review', limitations: 'none' })
    expect(s.lastSeq).toBe(9)
  })

  it('keeps the elapsed time from done and notes a summarized earlier context', () => {
    const s = run([
      { type: 'meta', data: { thinking_mode: 'fast', compacted: true } },
      { type: 'token', text: 'ok' },
      { type: 'done', data: { content: 'ok', latency_ms: 3812 } },
    ])
    expect(s.trace.elapsed_s).toBe(3.8)
    expect(s.trace.notices).toEqual([COMPACTED_NOTE])
  })

  it('in fast mode tokens are the answer, a reset clears the preamble, chips and sources accumulate', () => {
    const s = run([
      { type: 'meta', data: { thinking_mode: 'fast' } },
      { type: 'token', text: 'Let me check.' },
      { type: 'reset' },
      { type: 'tool', phase: 'start', id: 'c1', name: 'hp_web_search', label: 'Searching the web for “HomePilot”' },
      { type: 'tool', phase: 'end', id: 'c1', name: 'hp_web_search', label: 'Searching the web for “HomePilot”', ok: true, summary: '3 results', elapsed_ms: 900 },
      { type: 'sources', sources: [{ n: 1, title: 'HomePilot', url: 'https://github.com/ruslanmv/HomePilot', domain: 'github.com' }] },
      { type: 'token', text: 'HomePilot is on GitHub [1].' },
      { type: 'done', data: { content: 'HomePilot is on GitHub [1].' } },
    ])
    expect(s.text).toBe('HomePilot is on GitHub [1].')
    expect(s.trace.tools).toEqual([expect.objectContaining({ id: 'c1', status: 'done', summary: '3 results', elapsed_ms: 900 })])
    expect(s.trace.sources[0].n).toBe(1)
    expect(sourcesAsWeb(s.trace)).toEqual({ status: 'ok', query: 'HomePilot', sources: s.trace.sources })
    expect(sourcesAsWeb(initialExpertState().trace)).toBeNull()
  })

  it('keeps the verdict and marks a failed tool', () => {
    const s = run([
      { type: 'meta', data: { thinking_mode: 'heavy' } },
      { type: 'step', step: 'research', label: 'Researching', role: 'work' },
      { type: 'tool', phase: 'start', id: 'c1', name: 'hp_web_search', label: 'Searching the web' },
      { type: 'tool', phase: 'end', id: 'c1', name: 'hp_web_search', label: 'Searching the web', ok: false, summary: 'timeout' },
      { type: 'verdict', verdict: 'corrected', note: 'The validator found issues and corrected the answer.' },
      { type: 'error', error: 'boom' },
    ])
    expect(s.trace.tools[0]).toMatchObject({ status: 'failed', step: 'research' })
    expect(s.trace.verdict).toEqual({ verdict: 'corrected', note: 'The validator found issues and corrected the answer.' })
    expect(s.error).toBe('boom')
  })

  it('follows a Deep research job: plan, items, report', () => {
    let s = run([
      { type: 'status', status: 'planning' },
      { type: 'plan', items: [{ id: 'q1', title: 'What is X?', status: 'pending' }, { id: 'q2', title: 'Who makes X?', status: 'pending' }] },
      { type: 'status', status: 'researching' },
      { type: 'item', id: 'q1', status: 'running' },
      { type: 'tool', phase: 'start', id: 't1', name: 'hp_web_search', label: 'Searching the web for “X”' },
      { type: 'tool', phase: 'end', id: 't1', name: 'hp_web_search', label: 'Searching the web for “X”', ok: true },
      { type: 'item', id: 'q1', status: 'done', summary: 'X is… [1]', sources: [1] },
      { type: 'item', id: 'q2', status: 'skipped' },
      { type: 'status', status: 'writing' },
      { type: 'token', text: '# Report' },
    ], 'deep')
    expect(s.text).toBe('# Report')                                   // writing → tokens are the report
    expect(s.trace.plan!.map((p) => p.status)).toEqual(['done', 'skipped'])
    s = applyDeepDone(s, { report: '# Report\nX is… [1]', sources: [{ n: 1, title: 'X', url: 'https://x.test' }], plan: s.trace.plan, elapsed_s: 42.5, notices: [] })
    expect(s.done && s.text.startsWith('# Report')).toBe(true)
    expect(s.trace.status).toBe('done')
    expect(s.trace.elapsed_s).toBe(42.5)
  })
})

describe('the trivial-prompt check behind the Deep research hint', () => {
  it('catches greetings and a few words, not real questions', () => {
    for (const t of ['hello', 'Hi!', 'thanks', 'ok', 'how are you', 'test', 'summarize this']) expect(isTrivialPrompt(t)).toBe(true)
    for (const t of ['What changed in HomePilot this week?', 'compare gemma4 and qwen3 for coding', 'why?']) {
      expect(isTrivialPrompt(t)).toBe(false)
    }
  })
})

describe('the Deep research gate', () => {
  it('is unknown until measured, disabled with the reason, enabled with the model', () => {
    expect(deepOptionState(UNKNOWN_GATE).disabled).toBe(true)
    expect(deepGateFrom(null)).toBe(UNKNOWN_GATE)
    const low = deepGateFrom({ deep_research: { enabled: false, reason: 'Deep research needs a high-end model; the strongest here is llama3.2:3b (3.2B parameters).', model: null } } as any)
    expect(deepOptionState(low)).toEqual({ disabled: true, description: expect.stringContaining('llama3.2:3b') })
    const high = deepGateFrom({ deep_research: { enabled: true, reason: 'ok', model: 'internal-gpt-oss-120b' } } as any)
    // Enabled: the menu's plain caption; the model is the chat's own and is not repeated.
    expect(deepOptionState(high)).toEqual({ disabled: false, description: 'Plan, research and synthesize a report.' })
  })
})

describe('waiting for a busy provider', () => {
  it('shows the wait while it lasts and clears it on the next event', () => {
    let s = initialExpertState('fast')
    s = applyExpertEvent(s, { type: 'wait', text: 'The model provider is busy; retrying in 8 s…', retry_in: 8 })
    expect(s.trace.waiting).toBe('The model provider is busy; retrying in 8 s…')
    expect(traceHasWork(s.trace)).toBe(false)                    // the skeleton stays, with the line
    s = applyExpertEvent(s, { type: 'token', text: 'Hello' })
    expect(s.trace.waiting).toBeNull()
    expect(s.text).toBe('Hello')
    const parsed = parseExpertSse('event: wait\ndata: {"text": "Waiting in line for the model provider…", "retry_in": 3}\n\n')
    expect(parsed.events[0]).toEqual({ type: 'wait', text: 'Waiting in line for the model provider…', retry_in: 3 })
  })
})

describe('compacting a long conversation', () => {
  it('shows the compaction until the turn starts, then keeps only the note', () => {
    let s = initialExpertState('fast')
    const parsed = parseExpertSse('event: compacting\ndata: {"turns": 8, "text": "Compacting the conversation: summarizing 8 earlier messages…"}\n\n')
    s = applyExpertEvent(s, parsed.events[0])
    expect(s.trace.compacting).toBe('Compacting the conversation: summarizing 8 earlier messages…')
    expect(traceHasWork(s.trace)).toBe(false)
    s = applyExpertEvent(s, { type: 'meta', data: { thinking_mode: 'fast', compacted: true } })
    expect(s.trace.compacting).toBeNull()
    expect(s.trace.notices).toContain(COMPACTED_NOTE)
  })
})
