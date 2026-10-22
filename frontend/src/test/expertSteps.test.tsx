/**
 * The card above an Expert answer: the running stage while it works (named once), a quiet
 * summary once done (collapsed, with the verdict), the stages, chips, verdict detail and
 * notices when opened, and the Deep research plan with each item's state.
 */
import React from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ExpertSteps, hasLimitations, stageCopy, stripParts, stripTitle } from '../ui/components/ExpertSteps'
import type { ExpertTrace } from '../ui/lib/expertStream'

const base: ExpertTrace = { mode: 'heavy', model: 'openwebui/internal-gemma4-31b', steps: [], tools: [], sources: [], notices: [], verdict: null }

describe('stripParts', () => {
  it('names the running stage once while pending, then summarizes', () => {
    const running: ExpertTrace = { ...base, mode: 'think', steps: [
      { step: 'analyze', label: '🔍 Analyzing problem…', role: 'work', status: 'done', content: '' },
      { step: 'plan', label: '📋 Building plan…', role: 'work', status: 'running', content: '' },
      { step: 'solve', label: '⚡ Solving…', role: 'answer', status: 'running', content: '' },
    ] }
    expect(stripParts(running, true, false)).toEqual({ title: 'Planning the approach', sub: 'Expert · step 2 of 3' })
    expect(stripParts(running, true, true).title).toBe('Expert · working')         // open: the list shows the stage
    const done: ExpertTrace = { ...running, elapsed_s: 3.8, steps: running.steps.map((s) => ({ ...s, status: 'done' as const })) }
    expect(stripParts(done)).toEqual({ title: 'Reasoning completed', sub: 'Expert · 3 steps' })
    const heavy: ExpertTrace = { ...done, mode: 'heavy', verdict: { verdict: 'validated', note: 'ok' } }
    expect(stripTitle(heavy)).toBe('Validated response')
    expect(stripTitle({ ...heavy, verdict: { verdict: 'needs_review', note: '' } })).toBe('Needs review')
    expect(stripParts({ ...base, tools: [{ id: 'c1', name: 'hp_web_search', label: 'Searching the web for “x”', status: 'running' }] }, true).title)
      .toBe('Searching the web for “x”')
    expect(stripParts({ ...base, tools: [{ id: 'c1', name: 'hp_web_search', label: 'Searching the web', status: 'done' }] }).title)
      .toBe('Used 1 tool')
    const deep: ExpertTrace = { ...base, mode: 'deep', status: 'researching', plan: [
      { id: 'q1', title: 'A', status: 'done' }, { id: 'q2', title: 'B', status: 'running' }, { id: 'q3', title: 'C', status: 'pending' },
    ] }
    expect(stripParts(deep, true).title).toBe('Researching · 1 of 3 questions')
    expect(stripParts({ ...deep, status: 'done', elapsed_s: 26.5 })).toEqual({ title: 'Research complete', sub: 'Deep research · 1 of 3 questions' })
    expect(stageCopy({ step: 'custom', label: '🧪 Testing things…' })).toEqual({ doing: 'Testing things…', done: 'Testing things', detail: '' })
  })
})

describe('ExpertSteps', () => {
  it('renders nothing when there is nothing to show', () => {
    const { container } = render(<ExpertSteps trace={base} />)
    expect(container.innerHTML).toBe('')
  })

  it('while pending shows the running tool as the title and a single live indicator', () => {
    render(<ExpertSteps trace={{
      ...base,
      steps: [{ step: 'research', label: '🔬 Researching deeply…', role: 'work', status: 'running', content: 'notes' }],
      tools: [{ id: 'c1', name: 'hp_web_search', label: 'Searching the web for “X”', status: 'running' }],
    }} pending defaultOpen={false} />)
    expect(screen.getByTestId('expert-title').textContent).toBe('Searching the web for “X”')
    expect(screen.getByText('Live')).toBeTruthy()
    expect(screen.queryByText('Investigating')).toBeNull()                     // not repeated under the head
  })

  it('keeps the validator’s raw JSON out of the card once its verdict is shown, and hides "Not verified: none"', () => {
    render(<ExpertSteps defaultOpen showReasoning trace={{
      ...base, elapsed_s: 4,
      steps: [
        { step: 'reasoning', label: 'Reasoning', role: 'work', status: 'done', content: 'Mexico City is the capital.' },
        { step: 'validation', label: 'Validating', role: 'work', status: 'done', content: '{"verdict": "validated"}' },
      ],
      verdict: { verdict: 'validated', note: 'The validator confirmed the answer.', method: 'model review', limitations: 'none' },
    }} />)
    const reasoning = screen.getAllByTestId('expert-reasoning').map((n) => n.textContent)
    expect(reasoning).toEqual(['Mexico City is the capital.'])
    expect(screen.queryByText(/Not verified/)).toBeNull()
    expect(hasLimitations('no source for the date')).toBe(true)
    expect(hasLimitations('None.')).toBe(false)
  })

  it('shows a stage’s reasoning inline only when asked; otherwise it sits behind "Show output"', () => {
    const trace: ExpertTrace = { ...base, mode: 'think', steps: [
      { step: 'analyze', label: 'Analyzing', role: 'work', status: 'running', content: 'The question asks for X.' },
    ] }
    const first = render(<ExpertSteps trace={trace} pending showReasoning />)
    expect(screen.getByTestId('expert-reasoning').textContent).toBe('The question asks for X.')
    expect(screen.queryByText('Show output')).toBeNull()
    first.unmount()
    render(<ExpertSteps trace={trace} pending />)
    expect(screen.queryByTestId('expert-reasoning')).toBeNull()
    expect(screen.getByText('Show output')).toBeTruthy()
  })

  it('collapses to a summary with the verdict once done, and opens into detail', () => {
    render(<ExpertSteps trace={{
      ...base, elapsed_s: 12.1,
      steps: [
        { step: 'research', label: 'Researching', role: 'work', status: 'done', content: 'r' },
        { step: 'synthesis', label: 'Synthesizing', role: 'answer', status: 'done', content: 's' },
      ],
      tools: [{ id: 'c1', name: 'hp_web_search', label: 'Searching the web', status: 'done', summary: '3 results' }],
      verdict: { verdict: 'needs_review', note: 'The validator raised doubts it could not resolve; read the answer with care.',
        issues: [{ severity: 'high', text: 'The date may be wrong' }], method: 'model review', limitations: 'no source for the date' },
      notices: ['Heavy used qwen3:32b, the strongest model on this connection, instead of deepseek-r1:latest.'],
      project: { id: 'p1', name: 'Launch' },
    }} />)
    const toggle = screen.getByRole('button', { expanded: false })
    expect(screen.getByTestId('expert-title').textContent).toBe('Needs review')
    expect(toggle.textContent).toContain('12.1s')
    expect(toggle.textContent).toContain('internal-gemma4-31b')              // the provider prefix is dropped
    expect(toggle.textContent).not.toContain('openwebui/')
    expect(screen.queryByTestId('expert-notices')).toBeNull()
    fireEvent.click(toggle)
    expect(screen.getByTestId('expert-project').textContent).toContain('Using project Launch')
    expect(screen.getByText('Investigated')).toBeTruthy()
    expect(screen.getByText('Drafted the answer')).toBeTruthy()
    expect(screen.getByTestId('expert-verdict-detail').textContent).toContain('The date may be wrong')
    expect(screen.getByTestId('expert-verdict-detail').textContent).toContain('Not verified: no source for the date')
    expect(screen.getByTestId('expert-notices').textContent).toContain('strongest model')
    expect(screen.getByText('3 results', { exact: false })).toBeTruthy()
    expect(screen.getByText('Show output')).toBeTruthy()                       // a work stage's output stays behind a disclosure
  })

  it('shows a Deep research plan with each item state', () => {
    render(<ExpertSteps trace={{
      ...base, mode: 'deep', status: 'researching',
      plan: [
        { id: 'q1', title: 'What is X?', status: 'done', summary: 'X is… [1]' },
        { id: 'q2', title: 'Who makes X?', status: 'running' },
        { id: 'q3', title: 'Price?', status: 'skipped' },
      ],
    }} pending />)
    expect(screen.getByTestId('expert-title').textContent).toBe('Deep research · 1 of 3 questions')
    const plan = screen.getByTestId('expert-plan')
    expect(plan.textContent).toContain('X is… [1]')
    expect(plan.querySelector('.line-through')?.textContent).toBe('Price?')
  })
})
