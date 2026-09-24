/**
 * Ready-made routines.
 *
 * A blank routine form asks four questions at once — what, when, where, and what to say —
 * and the hardest of them is the last. "What should HomePilot do?" is a writing task, and
 * a good answer looks nothing like the one-line placeholder most people type. So the tab
 * opens with worked examples rather than an empty box.
 *
 * ── Two rules shape the list ─────────────────────────────────────────────────────────────
 *
 * **Nothing here can fail on a fresh install.** Every preset uses a capability HomePilot
 * ships with: the model itself, hp-news, or the default web search. The obvious candidates
 * that need credentials — the Gmail triage and calendar look-ahead the Secretary workflows
 * already implement — are deliberately absent. A template picker whose first row errors
 * because a connector is missing teaches people that templates do not work, and they stop
 * opening it.
 *
 * **Every task is written as a task.** Imperative, addressed to the assistant, never in the
 * user's voice — the same rule the executor enforces when it stores a routine's opening
 * turn as `system`. A first-person template ("Give me my briefing") would be the fabricated
 * user turn all over again, this time typed in by the product itself and copied by every
 * routine somebody creates from it.
 *
 * Each task text also says what to do when there is nothing to report. Left unsaid, a small
 * local model fills the silence, and a briefing that invents a meeting is worse than one
 * that says the calendar was empty.
 */
import {
  Bell,
  BookOpen,
  Briefcase,
  CalendarCheck,
  Dumbbell,
  GraduationCap,
  Moon,
  Newspaper,
  Radar,
  Sunrise,
  type LucideIcon,
} from 'lucide-react'

import type { RoutineActionType, RoutineDraft } from './types'

/** Where a preset wants to run. We cannot know the user's project ids, so this is a hint
 *  the form surfaces rather than a value it sets. */
export type PresetTargetHint = 'assistant' | 'persona' | 'project'

export type RoutinePreset = {
  id: string
  title: string
  /** One line, in the picker. Says what it is for, not what it does mechanically. */
  blurb: string
  icon: LucideIcon
  group: 'Your day' | 'Work' | 'Wellbeing' | 'Home'
  targetHint: PresetTargetHint
  /** The parts of a draft a preset decides. Everything else keeps the form's defaults. */
  draft: Pick<RoutineDraft, 'name' | 'schedule' | 'action'>
}

const WEEKDAYS = [1, 2, 3, 4, 5]

/** Sunday, in `isoweekday` terms — the numbering the scheduler uses. */
const SUNDAY = 7

export const ROUTINE_PRESETS: RoutinePreset[] = [
  {
    id: 'morning-news',
    title: 'Morning news',
    blurb: 'Today’s local and world headlines, before you are properly awake.',
    icon: Newspaper,
    group: 'Your day',
    targetHint: 'assistant',
    draft: {
      name: 'Morning news',
      schedule: { type: 'daily', time: '07:00' },
      action: {
        type: 'news_digest',
        parameters: { scope: ['local', 'national', 'world'], max_items: 6, location: '' },
      },
    },
  },
  {
    id: 'start-my-day',
    title: 'Start my day',
    blurb: 'A warm overview of the day ahead, on working mornings.',
    icon: Sunrise,
    group: 'Your day',
    targetHint: 'assistant',
    draft: {
      name: 'Start my day',
      schedule: { type: 'weekly', time: '08:00', days: WEEKDAYS },
      action: { type: 'daily_briefing', parameters: {} },
    },
  },
  {
    id: 'evening-wind-down',
    title: 'Evening wind-down',
    blurb: 'Close the day: what matters tomorrow, and what to let go of.',
    icon: Moon,
    group: 'Your day',
    targetHint: 'assistant',
    draft: {
      name: 'Evening wind-down',
      schedule: { type: 'daily', time: '21:30' },
      action: {
        type: 'assistant_prompt',
        parameters: {
          prompt:
            'Write a short, calm end-of-day note. Name the three things most worth doing '
            + 'tomorrow and one thing worth letting go of. Keep it under 120 words. Do not '
            + 'invent events or commitments you have no record of.',
        },
      },
    },
  },
  {
    id: 'standup-prep',
    title: 'Stand-up prep',
    blurb: 'Your update drafted before the meeting, from the project’s own notes.',
    icon: Briefcase,
    group: 'Work',
    targetHint: 'project',
    draft: {
      name: 'Stand-up prep',
      schedule: { type: 'weekly', time: '08:45', days: WEEKDAYS },
      action: {
        type: 'assistant_prompt',
        parameters: {
          prompt:
            'Using this project’s notes and files, draft my stand-up: what moved yesterday, '
            + 'what I am on today, and anything blocked. Three bullets each, no filler. Where '
            + 'the notes say nothing, write "nothing recorded" rather than guessing.',
        },
      },
    },
  },
  {
    id: 'sunday-reset',
    title: 'Sunday reset',
    blurb: 'Weekly review and next week’s three priorities, before Monday.',
    icon: CalendarCheck,
    group: 'Work',
    targetHint: 'project',
    draft: {
      name: 'Sunday reset',
      schedule: { type: 'weekly', time: '18:00', days: [SUNDAY] },
      action: {
        type: 'assistant_prompt',
        parameters: {
          prompt:
            'Review this project’s notes from the past seven days and write a short weekly '
            + 'review: what actually got done, what slipped and why, and the three priorities '
            + 'for the coming week. If a week produced little, say so plainly instead of '
            + 'padding it.',
        },
      },
    },
  },
  {
    id: 'field-watch',
    title: 'Field watch',
    blurb: 'What moved in your field today — five items, newest first, with sources.',
    icon: Radar,
    group: 'Work',
    targetHint: 'assistant',
    draft: {
      name: 'Field watch',
      schedule: { type: 'weekly', time: '17:00', days: WEEKDAYS },
      action: {
        type: 'assistant_prompt',
        parameters: {
          prompt:
            'Search the web for notable developments in [replace with your field] from the '
            + 'last 24 hours. At most five, newest first, one line each with a source link. '
            + 'Skip press releases, rumours, and reposts of the same story. If nothing '
            + 'significant happened, say that rather than filling the list.',
        },
      },
    },
  },
  {
    id: 'habit-reminder',
    title: 'Daily reminder',
    blurb: 'Medication, stretches, the bins — the thing you keep forgetting.',
    icon: Bell,
    group: 'Wellbeing',
    targetHint: 'assistant',
    draft: {
      name: 'Daily reminder',
      schedule: { type: 'daily', time: '09:00' },
      action: { type: 'reminder', parameters: { message: '' } },
    },
  },
  {
    id: 'move-of-the-day',
    title: 'Move of the day',
    blurb: 'One fifteen-minute workout, no equipment, different every day.',
    icon: Dumbbell,
    group: 'Wellbeing',
    targetHint: 'assistant',
    draft: {
      name: 'Move of the day',
      schedule: { type: 'daily', time: '12:30' },
      action: {
        type: 'assistant_prompt',
        parameters: {
          prompt:
            'Suggest one 15-minute workout I can do at home with no equipment. Vary it from '
            + 'day to day and name the muscle groups it works: two lines of warm-up, five '
            + 'exercises with reps or timings, one line of cool-down.',
        },
      },
    },
  },
  {
    id: 'bedtime-story',
    title: 'Bedtime story',
    blurb: 'A fresh story every night, ready when it is time to read one.',
    icon: BookOpen,
    group: 'Home',
    targetHint: 'persona',
    draft: {
      name: 'Bedtime story',
      schedule: { type: 'daily', time: '19:45' },
      action: {
        type: 'assistant_prompt',
        parameters: {
          prompt:
            'Write tonight’s original bedtime story for a 6-year-old: about 300 words, a '
            + 'named animal hero, a gentle ending, and a different setting from yesterday. '
            + 'Nothing frightening, and no cliffhanger.',
        },
      },
    },
  },
  {
    id: 'language-practice',
    title: 'Language practice',
    blurb: 'A short daily lesson you answer in the chat it arrives in.',
    icon: GraduationCap,
    group: 'Home',
    targetHint: 'persona',
    draft: {
      name: 'Language practice',
      schedule: { type: 'daily', time: '08:15' },
      action: {
        type: 'assistant_prompt',
        parameters: {
          prompt:
            'Set today’s Spanish practice at B1 level: five useful phrases with '
            + 'pronunciation hints, then three short sentences for me to translate. Do not '
            + 'give the answers until I ask — wait for my reply in this conversation.',
        },
      },
    },
  },
]

/**
 * Build a full draft from a preset.
 *
 * `base` is the form's own blank draft, so timezone, delivery and the enabled flag keep
 * coming from one place: a preset decides *what and when*, never how a routine is delivered.
 * Overlaying rather than replacing is what stops a preset silently resetting a preference
 * the user set two fields above it.
 *
 * The target is deliberately **not** set. A preset cannot know the user's project ids, so
 * `targetHint` is advice the form displays next to the picker, and the user chooses.
 */
export function applyPreset(preset: RoutinePreset, base: RoutineDraft): RoutineDraft {
  return {
    ...base,
    name: preset.draft.name,
    schedule: preset.draft.schedule,
    action: {
      type: preset.draft.action.type,
      parameters: { ...preset.draft.action.parameters },
    },
  }
}

/** The presets this server can actually run, given the action types it reports. */
export function availablePresets(actions: readonly string[] | undefined): RoutinePreset[] {
  if (!actions || !actions.length) return ROUTINE_PRESETS
  const supported = new Set(actions)
  return ROUTINE_PRESETS.filter((preset) =>
    supported.has(preset.draft.action.type as RoutineActionType),
  )
}
