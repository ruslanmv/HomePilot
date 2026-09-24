/**
 * Ready-made routines.
 *
 * The picker's job is to answer the hardest question on a blank routine form — *what
 * should HomePilot do?* — with a worked example rather than a placeholder. Two properties
 * make that safe to ship, and both are easy to lose in an edit six months from now:
 *
 * 1. **Nothing in the picker can fail on a fresh install.** Every preset uses an action
 *    HomePilot ships with. A template whose first row errors because a connector is
 *    missing teaches people that templates do not work.
 * 2. **Every task is written as a task**, imperative and addressed to the assistant. A
 *    first-person template would be the fabricated-user-turn bug all over again — this
 *    time typed in by the product and copied into every routine made from it.
 *
 * The rest is ordinary: picking fills the form, and it fills only the parts a preset is
 * entitled to decide.
 */
import React from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import {
  ROUTINE_PRESETS,
  applyPreset,
  availablePresets,
} from '../ui/routines/presets'
import type { RoutineDraft } from '../ui/routines/types'

const BASE: RoutineDraft = {
  name: 'Morning news',
  enabled: true,
  timezone: 'Europe/Rome',
  schedule: { type: 'daily', time: '08:00' },
  target: { type: 'persona', project_id: 'p-1' },
  action: { type: 'news_digest', parameters: {} },
  delivery: {
    in_app: true,
    notification: true,
    create_conversation: true,
    speak_if_active: false,
    catch_up: true,
  },
}

const byId = (id: string) => {
  const preset = ROUTINE_PRESETS.find((p) => p.id === id)
  if (!preset) throw new Error(`no preset ${id}`)
  return preset
}

describe('the preset catalog', () => {
  it('ships ten routines', () => {
    expect(ROUTINE_PRESETS).toHaveLength(10)
  })

  it('gives every preset a stable, unique id', () => {
    const ids = ROUTINE_PRESETS.map((p) => p.id)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('only uses actions HomePilot ships with', () => {
    // The whole reason the Gmail triage and calendar look-ahead are absent: a picker whose
    // first row needs credentials is a picker people stop opening.
    const shipped = new Set(['news_digest', 'daily_briefing', 'reminder', 'assistant_prompt'])
    for (const preset of ROUTINE_PRESETS) {
      expect(shipped.has(preset.draft.action.type)).toBe(true)
    }
  })

  it('never phrases a task in the user’s voice', () => {
    /*
     * The routine executor stores a routine's opening turn as `system` precisely because it
     * is not the user talking. A template that opens "Give me my briefing" puts the old
     * fabricated first-person phrasing back into every routine created from it — and unlike
     * the original bug, this one would be copied by hand and survive the fix.
     */
    const firstPerson = /^\s*(give me|tell me|show me|what('s| is) my|prepare my|read me)\b/i
    for (const preset of ROUTINE_PRESETS) {
      const text = String(
        preset.draft.action.parameters.prompt
        ?? preset.draft.action.parameters.message
        ?? '',
      )
      if (!text) continue
      expect(text, `${preset.id} reads as the user speaking`).not.toMatch(firstPerson)
    }
  })

  it('tells the model what to do when there is nothing to report', () => {
    // Left unsaid, a small local model fills the silence. A stand-up that invents progress
    // is worse than one that says the notes were empty.
    for (const id of ['standup-prep', 'sunday-reset', 'field-watch']) {
      const text = String(byId(id).draft.action.parameters.prompt || '')
      expect(text.toLowerCase(), id).toMatch(/nothing recorded|say so|say that|instead of/)
    }
  })

  it('schedules weekday routines on weekdays and Sunday reset on Sunday', () => {
    // `isoweekday` numbering — Monday 1, Sunday 7. Off-by-one here silently runs a
    // "weekday" routine on Sunday, which nobody notices until the weekend.
    const standup = byId('standup-prep').draft.schedule
    expect(standup.type === 'weekly' && standup.days).toEqual([1, 2, 3, 4, 5])
    const sunday = byId('sunday-reset').draft.schedule
    expect(sunday.type === 'weekly' && sunday.days).toEqual([7])
  })

  it('points work and family presets at the context they need', () => {
    expect(byId('standup-prep').targetHint).toBe('project')
    expect(byId('sunday-reset').targetHint).toBe('project')
    expect(byId('bedtime-story').targetHint).toBe('persona')
    expect(byId('language-practice').targetHint).toBe('persona')
    expect(byId('morning-news').targetHint).toBe('assistant')
  })
})

describe('applying a preset', () => {
  it('fills in the name, schedule and task', () => {
    const draft = applyPreset(byId('bedtime-story'), BASE)
    expect(draft.name).toBe('Bedtime story')
    expect(draft.schedule).toEqual({ type: 'daily', time: '19:45' })
    expect(draft.action.type).toBe('assistant_prompt')
    expect(String(draft.action.parameters.prompt)).toContain('bedtime story')
  })

  it('leaves the settings a preset has no business deciding', () => {
    // Timezone and delivery come from the form, not the template. A preset that reset
    // "speak if active" would quietly undo a choice made two fields above it.
    const draft = applyPreset(byId('morning-news'), BASE)
    expect(draft.timezone).toBe('Europe/Rome')
    expect(draft.delivery).toEqual(BASE.delivery)
    expect(draft.enabled).toBe(true)
  })

  it('never sets the target, because it cannot know the project ids', () => {
    const draft = applyPreset(byId('standup-prep'), BASE)
    expect(draft.target).toEqual(BASE.target)
  })

  it('copies parameters rather than sharing them with the catalog', () => {
    // Two routines made from one template must not end up editing the same object — and
    // worse, writing the first user's prompt into the shipped preset for the next one.
    const draft = applyPreset(byId('field-watch'), BASE)
    draft.action.parameters.prompt = 'mutated'
    expect(String(byId('field-watch').draft.action.parameters.prompt)).not.toBe('mutated')
  })
})

describe('gating on what the server can run', () => {
  it('shows everything when the server has not said yet', () => {
    expect(availablePresets(undefined)).toHaveLength(ROUTINE_PRESETS.length)
    expect(availablePresets([])).toHaveLength(ROUTINE_PRESETS.length)
  })

  it('hides a preset whose action this build does not implement', () => {
    const shown = availablePresets(['assistant_prompt', 'reminder'])
    expect(shown.map((p) => p.id)).not.toContain('morning-news')
    expect(shown.map((p) => p.id)).toContain('bedtime-story')
  })
})

/*
 * The picker itself. Rendered through the real editor would need the whole Routines view
 * and its fetches; these drive the two behaviours that are actually the picker's own.
 */
function Picker({ onPicked }: { onPicked: (draft: RoutineDraft) => void }) {
  const [draft, setDraft] = React.useState<RoutineDraft>(BASE)
  return (
    <div>
      {availablePresets(undefined).map((preset) => (
        <button
          key={preset.id}
          type="button"
          data-testid={`routine-preset-${preset.id}`}
          onClick={() => {
            const next = applyPreset(preset, draft)
            setDraft(next)
            onPicked(next)
          }}
        >
          {preset.title}
        </button>
      ))}
      <output data-testid="draft-name">{draft.name}</output>
    </div>
  )
}

describe('picking one in the form', () => {
  it('replaces the draft the form is editing', () => {
    const picked: RoutineDraft[] = []
    render(<Picker onPicked={(d) => picked.push(d)} />)

    fireEvent.click(screen.getByTestId('routine-preset-sunday-reset'))

    expect(screen.getByTestId('draft-name')).toHaveTextContent('Sunday reset')
    expect(picked.at(-1)?.action.type).toBe('assistant_prompt')
  })

  it('lets a second choice replace the first cleanly', () => {
    render(<Picker onPicked={() => {}} />)
    fireEvent.click(screen.getByTestId('routine-preset-sunday-reset'))
    fireEvent.click(screen.getByTestId('routine-preset-morning-news'))

    expect(screen.getByTestId('draft-name')).toHaveTextContent('Morning news')
  })
})
