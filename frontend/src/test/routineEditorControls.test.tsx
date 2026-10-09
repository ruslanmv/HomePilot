/**
 * The routine form's three controls.
 *
 * All three exist to undo the same mistake: a creation form that spent its first screen on
 * things that were optional, duplicated, or unusable at scale.
 *
 * * **Templates** were a section of nine cards above the Name field, so an optional
 *   shortcut read as a required step. They are one dropdown now, and these tests hold it
 *   shut until asked.
 * * **The four action types** were a second card grid directly under the templates, and the
 *   two overlapped — picking "Morning news" and then "Today's news" is the same decision
 *   twice. They are suggestions under a single task field now.
 * * **Run with** was a native `<select>` over every persona and project on the install,
 *   which stops being usable somewhere around the twentieth entry. It is searchable now.
 */
import React from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import {
  TargetPicker,
  TaskField,
  TemplateMenu,
  parametersFor,
  taskKindLabel,
} from '../ui/routines/EditorControls'
import { ROUTINE_PRESETS } from '../ui/routines/presets'
import type { RoutineDraft, RoutineTarget } from '../ui/routines/types'
import type { RoutineTargetProject } from '../ui/routines/api'

const preset = (id: string) => {
  const found = ROUTINE_PRESETS.find((p) => p.id === id)
  if (!found) throw new Error(`no preset ${id}`)
  return found
}

describe('the template menu', () => {
  const renderMenu = (applied = null as ReturnType<typeof preset> | null) => {
    const onPick = vi.fn()
    const onClear = vi.fn()
    render(
      <TemplateMenu
        presets={ROUTINE_PRESETS}
        applied={applied}
        onPick={onPick}
        onClear={onClear}
      />,
    )
    return { onPick, onClear }
  }

  it('is one button, and shows no templates until asked', () => {
    // The whole point. As a section this was nine cards a person had to scan before
    // reaching the first field of the thing they actually came to create.
    renderMenu()
    expect(screen.getByTestId('routine-template-trigger')).toHaveTextContent('Start from a template')
    expect(screen.queryByTestId('routine-template-menu')).toBeNull()
    expect(screen.queryByTestId('routine-template-morning-news')).toBeNull()
  })

  it('opens grouped, with Popular first', () => {
    renderMenu()
    fireEvent.click(screen.getByTestId('routine-template-trigger'))

    const menu = screen.getByTestId('routine-template-menu')
    expect(menu).toHaveTextContent('Popular')
    expect(menu).toHaveTextContent('Work')
    expect(menu).toHaveTextContent('Personal')
    const text = menu.textContent || ''
    expect(text.indexOf('Popular')).toBeLessThan(text.indexOf('Work'))
  })

  it('filters on search', () => {
    renderMenu()
    fireEvent.click(screen.getByTestId('routine-template-trigger'))
    fireEvent.change(screen.getByTestId('routine-template-search'), { target: { value: 'story' } })

    expect(screen.getByTestId('routine-template-bedtime-story')).toBeTruthy()
    expect(screen.queryByTestId('routine-template-morning-news')).toBeNull()
  })

  it('searches the description too, not just the title', () => {
    // "headlines" appears only in Morning news's blurb — the word somebody would actually
    // type when they cannot remember what the template is called.
    renderMenu()
    fireEvent.click(screen.getByTestId('routine-template-trigger'))
    fireEvent.change(screen.getByTestId('routine-template-search'), { target: { value: 'headlines' } })
    expect(screen.getByTestId('routine-template-morning-news')).toBeTruthy()
  })

  it('says so rather than showing an empty menu', () => {
    renderMenu()
    fireEvent.click(screen.getByTestId('routine-template-trigger'))
    fireEvent.change(screen.getByTestId('routine-template-search'), { target: { value: 'zzzz' } })
    expect(screen.getByTestId('routine-template-empty')).toHaveTextContent('No template matches')
  })

  it('closes on choosing, and does not leave the list expanded', () => {
    const { onPick } = renderMenu()
    fireEvent.click(screen.getByTestId('routine-template-trigger'))
    fireEvent.click(screen.getByTestId('routine-template-sunday-reset'))

    expect(onPick).toHaveBeenCalledWith(expect.objectContaining({ id: 'sunday-reset' }))
    expect(screen.queryByTestId('routine-template-menu')).toBeNull()
  })

  it('names the applied template on the button instead of adding a card', () => {
    renderMenu(preset('morning-news'))
    expect(screen.getByTestId('routine-template-trigger')).toHaveTextContent('Template: Morning news')
  })

  it('offers a way back to a blank routine once one is applied', () => {
    const { onClear } = renderMenu(preset('morning-news'))
    fireEvent.click(screen.getByTestId('routine-template-trigger'))
    fireEvent.click(screen.getByTestId('routine-template-clear'))
    expect(onClear).toHaveBeenCalled()
  })

  it('closes on Escape', () => {
    renderMenu()
    fireEvent.click(screen.getByTestId('routine-template-trigger'))
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByTestId('routine-template-menu')).toBeNull()
  })
})

describe('the task field', () => {
  const renderTask = (action: RoutineDraft['action']) => {
    const onChangeKind = vi.fn()
    const onChangeText = vi.fn()
    const onChangeLocation = vi.fn()
    render(
      <TaskField
        action={action}
        onChangeKind={onChangeKind}
        onChangeText={onChangeText}
        onChangeLocation={onChangeLocation}
      />,
    )
    return { onChangeKind, onChangeText, onChangeLocation }
  }

  it('is a plain text field for a custom task', () => {
    renderTask({ type: 'assistant_prompt', parameters: { prompt: 'Check CI' } })
    expect(screen.getByTestId('routine-task-text')).toHaveValue('Check CI')
  })

  it('offers the four kinds as suggestions rather than cards', () => {
    renderTask({ type: 'assistant_prompt', parameters: { prompt: '' } })
    for (const id of ['assistant_prompt', 'daily_briefing', 'news_digest', 'reminder']) {
      expect(screen.getByTestId(`routine-task-kind-${id}`)).toBeTruthy()
    }
  })

  it('switches kind from a suggestion', () => {
    const { onChangeKind } = renderTask({ type: 'assistant_prompt', parameters: { prompt: '' } })
    fireEvent.click(screen.getByTestId('routine-task-kind-reminder'))
    expect(onChangeKind).toHaveBeenCalledWith('reminder')
  })

  it('binds to the reminder message when that is the kind', () => {
    const { onChangeText } = renderTask({ type: 'reminder', parameters: { message: 'Leave now' } })
    expect(screen.getByTestId('routine-task-text')).toHaveValue('Leave now')
    fireEvent.change(screen.getByTestId('routine-task-text'), { target: { value: 'Take pills' } })
    expect(onChangeText).toHaveBeenCalledWith('Take pills')
  })

  it('shows what will happen, not an empty box, for the fixed behaviours', () => {
    // `daily_briefing` and `news_digest` take no free text. A textarea here would silently
    // discard whatever was typed into it, which is worse than rendering none.
    renderTask({ type: 'daily_briefing', parameters: {} })
    expect(screen.queryByTestId('routine-task-text')).toBeNull()
    expect(screen.getByTestId('routine-task-fixed')).toHaveTextContent('overview of the day')
  })

  it('reveals the news location only for a news digest', () => {
    renderTask({ type: 'reminder', parameters: { message: '' } })
    expect(screen.queryByTestId('routine-news-location')).toBeNull()

    render(
      <TaskField
        action={{ type: 'news_digest', parameters: { location: 'Milan' } }}
        onChangeKind={vi.fn()}
        onChangeText={vi.fn()}
        onChangeLocation={vi.fn()}
      />,
    )
    expect(screen.getByTestId('routine-news-location')).toHaveValue('Milan')
  })

  it('resets parameters when the kind changes, so nothing stale survives', () => {
    expect(parametersFor('reminder')).toEqual({ message: '' })
    expect(parametersFor('assistant_prompt')).toEqual({ prompt: '' })
    expect(parametersFor('daily_briefing')).toEqual({})
    expect(parametersFor('news_digest')).toMatchObject({ location: '' })
  })

  it('names each kind once, for the field and the list badge alike', () => {
    // Two lists of names is how a badge ends up reading "Today's news" beside a field that
    // calls the same thing "News".
    expect(taskKindLabel('assistant_prompt')).toBe('Custom task')
    expect(taskKindLabel('news_digest')).toBe('News')
  })
})

describe('the target picker', () => {
  const PROJECTS: RoutineTargetProject[] = [
    { id: 'p1', name: 'Elena', project_type: 'persona' },
    { id: 'p2', name: 'Marcus Chen', project_type: 'persona' },
    { id: 'p3', name: 'Legal Document Reviewer', project_type: 'workspace' },
  ]

  const renderPicker = (target: RoutineTarget = { type: 'assistant' }, hint?: string) => {
    const onChange = vi.fn()
    render(
      <TargetPicker target={target} projects={PROJECTS} onChange={onChange} hint={hint} />,
    )
    return { onChange }
  }

  it('shows the current target and stays closed', () => {
    renderPicker()
    expect(screen.getByTestId('routine-target-trigger')).toHaveTextContent('HomePilot assistant')
    expect(screen.queryByTestId('routine-target-menu')).toBeNull()
  })

  it('groups the list into default, personas and projects', () => {
    renderPicker()
    fireEvent.click(screen.getByTestId('routine-target-trigger'))
    const menu = screen.getByTestId('routine-target-menu')
    expect(menu).toHaveTextContent('Default')
    expect(menu).toHaveTextContent('Personas')
    expect(menu).toHaveTextContent('Projects')
  })

  it('searches across personas and projects', () => {
    // The reason this is not a <select>: on an install with forty personas, typing is the
    // only way anyone finds the one they want.
    renderPicker()
    fireEvent.click(screen.getByTestId('routine-target-trigger'))
    fireEvent.change(screen.getByTestId('routine-target-search'), { target: { value: 'marcus' } })

    expect(screen.getByTestId('routine-target-persona-p2')).toBeTruthy()
    expect(screen.queryByTestId('routine-target-persona-p1')).toBeNull()
    expect(screen.queryByTestId('routine-target-assistant')).toBeNull()
  })

  it('picks a persona and closes', () => {
    const { onChange } = renderPicker()
    fireEvent.click(screen.getByTestId('routine-target-trigger'))
    fireEvent.click(screen.getByTestId('routine-target-persona-p1'))

    expect(onChange).toHaveBeenCalledWith({ type: 'persona', project_id: 'p1' })
    expect(screen.queryByTestId('routine-target-menu')).toBeNull()
  })

  it('shows the name of the chosen persona on the trigger', () => {
    renderPicker({ type: 'persona', project_id: 'p2' })
    expect(screen.getByTestId('routine-target-trigger')).toHaveTextContent('Marcus Chen')
  })

  it('carries the template’s advice as one line, not a panel', () => {
    renderPicker({ type: 'assistant' }, 'Stand-up prep works best with a project.')
    expect(screen.getByTestId('routine-target-hint')).toHaveTextContent('works best with a project')
  })

  it('says nothing when a search matches nothing', () => {
    renderPicker()
    fireEvent.click(screen.getByTestId('routine-target-trigger'))
    fireEvent.change(screen.getByTestId('routine-target-search'), { target: { value: 'zzzz' } })
    expect(screen.getByTestId('routine-target-empty')).toHaveTextContent('Nothing matches')
  })
})
