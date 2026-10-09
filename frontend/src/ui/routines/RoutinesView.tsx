import React, { useEffect, useMemo, useState } from 'react'
import {
  Bell,
  Bot,
  CalendarClock,
  Check,
  CheckCircle2,
  Clock3,
  Folder,
  History,
  AlertCircle,
  Loader2,
  Newspaper,
  Pencil,
  Play,
  Plus,
  Sparkles,
  Trash2,
  UserRound,
  X,
  type LucideIcon,
} from 'lucide-react'

import {
  createRoutine,
  deleteRoutine,
  getRoutineCapabilities,
  listRoutines,
  listRoutineRuns,
  listRoutineTargetProjects,
  runRoutineNow,
  updateRoutine,
  type RoutineCapabilities,
  type RoutineTargetProject,
} from './api'
import type { Routine, RoutineActionType, RoutineDraft, RoutineRun } from './types'
import { applyPreset, availablePresets, type RoutinePreset } from './presets'
import { TargetPicker, TaskField, TemplateMenu, parametersFor, taskKindLabel } from './EditorControls'

const DAYS = [
  { id: 1, short: 'M', label: 'Monday' },
  { id: 2, short: 'T', label: 'Tuesday' },
  { id: 3, short: 'W', label: 'Wednesday' },
  { id: 4, short: 'T', label: 'Thursday' },
  { id: 5, short: 'F', label: 'Friday' },
  { id: 6, short: 'S', label: 'Saturday' },
  { id: 7, short: 'S', label: 'Sunday' },
]

/**
 * Icons for the routine list.
 *
 * Labels are **not** here: they come from `taskKindLabel`, which the editor's suggestion
 * row also uses. Two lists of names for the same four things is how a badge ends up
 * reading "Today's news" next to a field that calls it "News".
 */
const ACTION_ICONS: Record<RoutineActionType, LucideIcon> = {
  news_digest: Newspaper,
  daily_briefing: Sparkles,
  reminder: Bell,
  assistant_prompt: CalendarClock,
}

function browserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  } catch {
    return 'UTC'
  }
}

/**
 * A blank routine, and blank is the point.
 *
 * This used to open pre-filled as a news digest called "Morning news" — a template in all
 * but name, sitting where the empty form should be. With templates now one button away,
 * the form's job is to be empty and get out of the way: an unnamed custom task the user
 * types into, or the shape a template drops in.
 */
function defaultDraft(): RoutineDraft {
  return {
    name: '',
    enabled: true,
    timezone: browserTimezone(),
    schedule: { type: 'daily', time: '08:00' },
    target: { type: 'assistant' },
    action: {
      type: 'assistant_prompt',
      parameters: { prompt: '' },
    },
    delivery: {
      in_app: true,
      notification: true,
      create_conversation: true,
      speak_if_active: true,
      catch_up: true,
    },
  }
}

function scheduleLabel(routine: Pick<RoutineDraft, 'schedule' | 'timezone'>): string {
  const schedule = routine.schedule
  if (schedule.type === 'once') {
    return schedule.at ? `Once · ${new Date(schedule.at).toLocaleString()}` : 'Once'
  }
  const time = schedule.time || '08:00'
  if (schedule.type === 'daily') return `Every day · ${time}`
  const days = schedule.days || []
  const weekdays = [1, 2, 3, 4, 5]
  const isWeekdays = weekdays.every((d) => days.includes(d)) && days.length === weekdays.length
  const dayText = isWeekdays
    ? 'Weekdays'
    : DAYS.filter((d) => days.includes(d.id)).map((d) => d.label.slice(0, 3)).join(', ') || 'Selected days'
  return `${dayText} · ${time}`
}

function actionLabel(type: RoutineActionType): string {
  return taskKindLabel(type)
}

function RoutineEditor({
  initial,
  targets,
  presets,
  onClose,
  onSave,
  saving,
}: {
  initial?: Routine
  targets: RoutineTargetProject[]
  presets: RoutinePreset[]
  onClose: () => void
  onSave: (draft: RoutineDraft) => void
  saving: boolean
}) {
  const [pickedPreset, setPickedPreset] = useState<RoutinePreset | null>(null)
  const [draft, setDraft] = useState<RoutineDraft>(() => {
    if (!initial) return defaultDraft()
    return {
      name: initial.name,
      enabled: initial.enabled,
      timezone: initial.timezone,
      schedule: initial.schedule,
      target: initial.target || { type: 'assistant' },
      action: initial.action,
      delivery: {
        in_app: initial.delivery.in_app ?? true,
        notification: initial.delivery.notification ?? true,
        create_conversation: initial.delivery.create_conversation ?? true,
        speak_if_active: initial.delivery.speak_if_active ?? true,
        catch_up: initial.delivery.catch_up ?? true,
      },
    }
  })

  const selectedDays = draft.schedule.type === 'weekly' ? draft.schedule.days : []

  // Switching kind resets the parameters, so a reminder message never lingers on a news
  // digest. `parametersFor` is shared with the control that renders the choice, because
  // two copies of "what fields does this kind have" is how one of them goes stale.
  const setAction = (type: RoutineActionType) => {
    setDraft((prev) => ({ ...prev, action: { type, parameters: parametersFor(type) } }))
  }

  const setCadence = (cadence: 'daily' | 'weekdays' | 'custom') => {
    setDraft((prev) => {
      const time = prev.schedule.type === 'once' ? '08:00' : prev.schedule.time || '08:00'
      if (cadence === 'daily') return { ...prev, schedule: { type: 'daily', time } }
      if (cadence === 'weekdays') {
        return { ...prev, schedule: { type: 'weekly', time, days: [1, 2, 3, 4, 5] } }
      }
      return { ...prev, schedule: { type: 'weekly', time, days: [1] } }
    })
  }

  const toggleDay = (day: number) => {
    if (draft.schedule.type !== 'weekly') return
    const current = draft.schedule.days || []
    const next = current.includes(day) ? current.filter((d) => d !== day) : [...current, day].sort()
    if (!next.length) return
    setDraft((prev) =>
      prev.schedule.type === 'weekly'
        ? { ...prev, schedule: { ...prev.schedule, days: next } }
        : prev,
    )
  }

  const message = String(draft.action.parameters.message || '')
  const prompt = String(draft.action.parameters.prompt || '')

  const valid =
    draft.name.trim().length > 0 &&
    (draft.schedule.type !== 'weekly' || draft.schedule.days.length > 0) &&
    (draft.action.type !== 'reminder' || message.trim().length > 0) &&
    (draft.action.type !== 'assistant_prompt' || prompt.trim().length > 0) &&
    (draft.target.type === 'assistant' || Boolean(draft.target.project_id))

  return (
    <div className="fixed inset-0 z-[90] bg-black/65 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-3xl border border-white/10 bg-[#121212] shadow-2xl">
        <div className="sticky top-0 z-10 flex items-center justify-between px-6 py-5 border-b border-white/[0.06] bg-[#121212]/95 backdrop-blur">
          <div className="min-w-0">
            <div className="text-lg font-semibold text-white">
              {initial ? 'Edit routine' : 'New routine'}
            </div>
            <div className="text-sm text-white/45 mt-1">Choose when it happens and what HomePilot should prepare.</div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {/* Templates live in the header, as one button.
                As a section they were the first thing on the page and the largest — nine
                cards to scan before reaching the Name field, which makes an optional
                shortcut read as a required step. Editing shows none of this: filling the
                form in one click is helpful on a blank form and destructive on a routine
                that has been running for a month. */}
            {!initial ? (
              <TemplateMenu
                presets={presets}
                applied={pickedPreset}
                onPick={(preset) => {
                  setPickedPreset(preset)
                  setDraft((prev) => applyPreset(preset, prev))
                }}
                onClear={() => {
                  setPickedPreset(null)
                  setDraft(defaultDraft())
                }}
              />
            ) : null}
            <button
              type="button"
              onClick={onClose}
              className="h-9 w-9 rounded-xl grid place-items-center text-white/45 hover:text-white hover:bg-white/[0.06]"
              aria-label="Close routine editor"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        <div className="p-6 space-y-6">
          {/* One line, not a card: the template has already done its job by filling the
              fields below, and repeating it as a panel would put the weight straight back. */}
          {pickedPreset ? (
            <div className="text-[11px] text-white/35" data-testid="routine-template-applied">
              <span className="text-white/55">{pickedPreset.title}</span> template applied ·
              Everything below is editable.
            </div>
          ) : null}

          <section>
            <label className="text-xs font-semibold uppercase tracking-wider text-white/40">Name</label>
            <input
              value={draft.name}
              onChange={(e) => setDraft((prev) => ({ ...prev, name: e.target.value }))}
              className="mt-2 w-full rounded-2xl border border-white/10 bg-black/20 px-4 py-3 text-sm text-white outline-none focus:border-white/25"
              placeholder="Morning briefing"
              autoFocus
            />
          </section>

          {/* The four action types, as suggestions under one field rather than a second
              grid of cards. They used to be four large targets directly under nine template
              cards, and the two sets overlapped: "Morning news" then "Today's news" is the
              same decision twice, and reads as the form not having listened. */}
          <TaskField
            action={draft.action}
            onChangeKind={setAction}
            onChangeText={(value) =>
              setDraft((prev) => ({
                ...prev,
                action: {
                  ...prev.action,
                  parameters: {
                    ...prev.action.parameters,
                    [prev.action.type === 'reminder' ? 'message' : 'prompt']: value,
                  },
                },
              }))
            }
            onChangeLocation={(value) =>
              setDraft((prev) => ({
                ...prev,
                action: { ...prev.action, parameters: { ...prev.action.parameters, location: value } },
              }))
            }
          />


          {/* A searchable picker rather than a <select>: an install with forty personas
              makes a native dropdown unusable, and this list is the user's whole project
              space. The template's preference appears as one line under it — advice,
              because a template cannot know anybody's project ids. */}
          <TargetPicker
            target={draft.target}
            projects={targets}
            onChange={(next) => setDraft((prev) => ({ ...prev, target: next }))}
            hint={
              pickedPreset
              && pickedPreset.targetHint !== 'assistant'
              && draft.target.type === 'assistant'
                ? `${pickedPreset.title} works best with ${
                  pickedPreset.targetHint === 'persona' ? 'a persona' : 'a project'
                }, so it can draw on that context.`
                : null
            }
          />

          <section>
            <div className="text-xs font-semibold uppercase tracking-wider text-white/40 mb-3">When?</div>
            <div className="flex flex-wrap gap-2">
              {[
                ['daily', 'Every day'],
                ['weekdays', 'Weekdays'],
                ['custom', 'Custom days'],
              ].map(([id, label]) => {
                const schedule = draft.schedule
                const active =
                  id === 'daily'
                    ? schedule.type === 'daily'
                    : id === 'weekdays'
                      ? schedule.type === 'weekly' && schedule.days.length === 5 && [1, 2, 3, 4, 5].every((d) => schedule.days.includes(d))
                      : schedule.type === 'weekly' && !(schedule.days.length === 5 && [1, 2, 3, 4, 5].every((d) => schedule.days.includes(d)))
                return (
                  <button
                    key={id}
                    type="button"
                    onClick={() => setCadence(id as 'daily' | 'weekdays' | 'custom')}
                    className={[
                      'rounded-xl border px-3.5 py-2 text-sm transition-colors',
                      active
                        ? 'border-white/20 bg-white/10 text-white'
                        : 'border-white/[0.07] text-white/50 hover:bg-white/[0.05] hover:text-white/75',
                    ].join(' ')}
                  >
                    {label}
                  </button>
                )
              })}
            </div>

            {draft.schedule.type === 'weekly' ? (
              <div className="flex gap-2 mt-3" aria-label="Routine days">
                {DAYS.map((day) => {
                  const active = selectedDays.includes(day.id)
                  return (
                    <button
                      key={day.id}
                      type="button"
                      onClick={() => toggleDay(day.id)}
                      title={day.label}
                      className={[
                        'h-9 w-9 rounded-full text-xs font-semibold transition-colors',
                        active ? 'bg-white text-black' : 'bg-white/[0.05] text-white/45 hover:bg-white/10',
                      ].join(' ')}
                    >
                      {day.short}
                    </button>
                  )
                })}
              </div>
            ) : null}

            <div className="grid gap-3 sm:grid-cols-2 mt-4">
              <label>
                <span className="text-xs text-white/40">Time</span>
                <input
                  type="time"
                  value={draft.schedule.type === 'once' ? '08:00' : draft.schedule.time}
                  onChange={(e) =>
                    setDraft((prev) =>
                      prev.schedule.type === 'once'
                        ? prev
                        : { ...prev, schedule: { ...prev.schedule, time: e.target.value } },
                    )
                  }
                  className="mt-1.5 w-full rounded-xl border border-white/10 bg-black/20 px-3 py-2.5 text-sm text-white outline-none focus:border-white/25"
                />
              </label>
              <label>
                <span className="text-xs text-white/40">Timezone</span>
                <input
                  value={draft.timezone}
                  onChange={(e) => setDraft((prev) => ({ ...prev, timezone: e.target.value }))}
                  className="mt-1.5 w-full rounded-xl border border-white/10 bg-black/20 px-3 py-2.5 text-sm text-white outline-none focus:border-white/25"
                />
              </label>
            </div>
          </section>

          <section>
            <div className="text-xs font-semibold uppercase tracking-wider text-white/40 mb-3">Delivery</div>
            <div className="space-y-2">
              <div className="flex items-start gap-3 rounded-2xl border border-emerald-300/10 bg-emerald-300/[0.025] px-4 py-3">
                <CheckCircle2 size={15} className="mt-0.5 shrink-0 text-emerald-300/70" />
                <span>
                  <span className="block text-sm text-white/80">Save as a conversation</span>
                  <span className="block text-xs text-white/40 mt-0.5">
                    Always on. Every routine result is a native HomePilot conversation you can open and continue.
                  </span>
                </span>
              </div>
              {[
                ['notification', 'Show a notification', 'Surface a non-disruptive notification when the run is ready.'],
                ['speak_if_active', 'Speak when a companion is active', 'Lets a voice/avatar client present it naturally.'],
                ['catch_up', 'Catch up after downtime', 'Run useful missed work when HomePilot starts again.'],
              ].map(([key, title, description]) => {
                const checked = Boolean(draft.delivery[key as keyof RoutineDraft['delivery']])
                return (
                  <label key={key} className="flex items-start gap-3 rounded-2xl border border-white/[0.07] px-4 py-3 cursor-pointer hover:bg-white/[0.025]">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(e) =>
                        setDraft((prev) => ({
                          ...prev,
                          delivery: { ...prev.delivery, [key]: e.target.checked, create_conversation: true },
                        }))
                      }
                      className="mt-0.5"
                    />
                    <span>
                      <span className="block text-sm text-white/80">{title}</span>
                      <span className="block text-xs text-white/40 mt-0.5">{description}</span>
                    </span>
                  </label>
                )
              })}
            </div>
          </section>
        </div>

        <div className="sticky bottom-0 flex items-center justify-end gap-2 px-6 py-4 border-t border-white/[0.06] bg-[#121212]/95 backdrop-blur">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl px-4 py-2.5 text-sm text-white/55 hover:text-white hover:bg-white/[0.05]"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={!valid || saving}
            onClick={() => onSave(draft)}
            className="inline-flex items-center gap-2 rounded-xl bg-white px-4 py-2.5 text-sm font-semibold text-black disabled:opacity-40"
          >
            {saving ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}
            {initial ? 'Save changes' : 'Create routine'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default function RoutinesView({
  backendUrl,
  apiKey,
  onOpenConversation,
}: {
  backendUrl: string
  apiKey?: string
  onOpenConversation?: (run: RoutineRun) => void
}) {
  const [routines, setRoutines] = useState<Routine[]>([])
  const [targets, setTargets] = useState<RoutineTargetProject[]>([])
  const [runs, setRuns] = useState<RoutineRun[]>([])
  const [capabilities, setCapabilities] = useState<RoutineCapabilities | null>(null)
  const [runningId, setRunningId] = useState<string | null>(null)
  const [historyRoutine, setHistoryRoutine] = useState<Routine | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState<Routine | null>(null)
  const [creating, setCreating] = useState(false)

  const enabledCount = useMemo(() => routines.filter((routine) => routine.enabled).length, [routines])
  const targetNames = useMemo(
    () => new Map(targets.map((target) => [target.id, target.name])),
    [targets],
  )
  const latestRuns = useMemo(() => {
    const map = new Map<string, RoutineRun>()
    for (const run of runs) {
      if (!map.has(run.routine_id)) map.set(run.routine_id, run)
    }
    return map
  }, [runs])

  const refresh = async () => {
    setLoading(true)
    setError('')
    try {
      const [routineRows, targetRows, runRows, capabilityInfo] = await Promise.all([
        listRoutines(backendUrl, apiKey),
        listRoutineTargetProjects(backendUrl, apiKey).catch(() => []),
        listRoutineRuns(backendUrl, undefined, apiKey, 100).catch(() => []),
        getRoutineCapabilities(backendUrl, apiKey).catch(() => null),
      ])
      setRoutines(routineRows)
      setTargets(targetRows)
      setRuns(runRows)
      setCapabilities(capabilityInfo)
    } catch (err: any) {
      setError(err?.message || 'Could not load routines.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void refresh()
  }, [backendUrl, apiKey])

  const save = async (draft: RoutineDraft) => {
    setSaving(true)
    setError('')
    try {
      if (editing) {
        const updated = await updateRoutine(backendUrl, editing.id, draft, apiKey)
        setRoutines((items) => items.map((item) => item.id === updated.id ? updated : item))
      } else {
        const created = await createRoutine(backendUrl, draft, apiKey)
        setRoutines((items) => [created, ...items])
      }
      setEditing(null)
      setCreating(false)
    } catch (err: any) {
      setError(err?.message || 'Could not save routine.')
    } finally {
      setSaving(false)
    }
  }

  const toggle = async (routine: Routine) => {
    const before = routine.enabled
    setRoutines((items) => items.map((item) => item.id === routine.id ? { ...item, enabled: !before } : item))
    try {
      const updated = await updateRoutine(backendUrl, routine.id, { enabled: !before }, apiKey)
      setRoutines((items) => items.map((item) => item.id === updated.id ? updated : item))
    } catch (err: any) {
      setRoutines((items) => items.map((item) => item.id === routine.id ? { ...item, enabled: before } : item))
      setError(err?.message || 'Could not update routine.')
    }
  }

  const remove = async (routine: Routine) => {
    const snapshot = routines
    setRoutines((items) => items.filter((item) => item.id !== routine.id))
    try {
      await deleteRoutine(backendUrl, routine.id, apiKey)
    } catch (err: any) {
      setRoutines(snapshot)
      setError(err?.message || 'Could not remove routine.')
    }
  }

  const runNow = async (routine: Routine) => {
    setRunningId(routine.id)
    setError('')
    try {
      const run = await runRoutineNow(backendUrl, routine.id, apiKey)
      setRuns((items) => [run, ...items.filter((item) => item.id !== run.id)])
      if (run.status === 'failed') {
        setError(run.error || 'Routine execution failed.')
      }
    } catch (err: any) {
      setError(err?.message || 'Could not run routine.')
    } finally {
      setRunningId(null)
    }
  }

  const openRun = (run?: RoutineRun) => {
    if (!run?.conversation_id) {
      setError('This run does not have a conversation to open.')
      return
    }
    onOpenConversation?.(run)
  }

  return (
    <div className="h-full overflow-y-auto bg-[#0d0d0d] text-white">
      <div className="mx-auto max-w-6xl px-5 py-8 sm:px-8 sm:py-10">
        <header className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="flex items-center gap-2.5 text-white/40 text-sm">
              <CalendarClock size={17} />
              Personal automation
            </div>
            <h1 className="text-3xl font-semibold tracking-tight mt-2">Routines</h1>
            <p className="text-sm leading-6 text-white/45 mt-2 max-w-2xl">
              Define reusable moments for HomePilot — news, briefings, reminders and assistant prompts.
              The same routine definitions are available to optional companion clients such as the 3D Avatar.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setCreating(true)}
            className="inline-flex items-center justify-center gap-2 rounded-xl bg-white px-4 py-2.5 text-sm font-semibold text-black hover:bg-white/90"
          >
            <Plus size={16} />
            New routine
          </button>
        </header>

        <div className="grid gap-3 sm:grid-cols-3 mt-8">
          <div className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-4">
            <div className="text-xs uppercase tracking-wider text-white/35">Active</div>
            <div className="text-2xl font-semibold mt-1">{enabledCount}</div>
          </div>
          <div className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-4">
            <div className="text-xs uppercase tracking-wider text-white/35">Saved</div>
            <div className="text-2xl font-semibold mt-1">{routines.length}</div>
          </div>
          <div className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-4">
            <div className="text-xs uppercase tracking-wider text-white/35">Companion ready</div>
            <div className="text-sm font-medium text-white/80 mt-2">Shared API contract</div>
          </div>
        </div>

        <div className={[
          'mt-7 rounded-2xl border px-4 py-3 text-xs leading-5',
          capabilities?.scheduler_enabled
            ? 'border-emerald-300/15 bg-emerald-300/[0.035] text-white/55'
            : 'border-amber-300/15 bg-amber-300/[0.035] text-white/50',
        ].join(' ')}>
          {capabilities?.scheduler_enabled ? (
            <>
              Automatic scheduling is active. Enabled routines run at their configured local time, and you can also use <strong className="text-white/70">Run now</strong>.
            </>
          ) : (
            <>
              <strong className="text-white/65">Run now is available.</strong> Automatic time-based execution is disabled on this HomePilot server.
              Set <code className="mx-1 text-white/65">ROUTINES_EXECUTION_ENABLED=true</code> and restart HomePilot to activate scheduled runs.
            </>
          )}
        </div>

        {error ? (
          <div className="mt-5 rounded-2xl border border-red-400/20 bg-red-400/[0.06] px-4 py-3 text-sm text-red-100/80">
            {error}
          </div>
        ) : null}

        <main className="mt-7">
          {loading ? (
            <div className="py-20 flex items-center justify-center gap-2 text-white/40">
              <Loader2 size={17} className="animate-spin" />
              Loading routines…
            </div>
          ) : routines.length === 0 ? (
            <div className="rounded-3xl border border-dashed border-white/10 px-6 py-16 text-center">
              <div className="mx-auto h-12 w-12 rounded-2xl bg-white/[0.05] grid place-items-center text-white/50">
                <CalendarClock size={22} />
              </div>
              <div className="text-base font-semibold text-white/85 mt-4">No routines yet</div>
              <p className="text-sm text-white/40 mt-2 max-w-md mx-auto">
                Start with a morning news digest or daily briefing. You can pause or remove it at any time.
              </p>
              <button
                type="button"
                onClick={() => setCreating(true)}
                className="mt-5 inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.05] px-4 py-2.5 text-sm text-white/80 hover:bg-white/[0.08]"
              >
                <Plus size={15} />
                Create your first routine
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              {routines.map((routine) => {
                const ActionIcon = ACTION_ICONS[routine.action.type] || Sparkles
                return (
                  <article key={routine.id} className="rounded-2xl border border-white/[0.075] bg-white/[0.025] p-4 sm:p-5">
                    <div className="flex items-start gap-4">
                      <div className="h-11 w-11 rounded-2xl bg-white/[0.055] grid place-items-center text-white/60 shrink-0">
                        <ActionIcon size={20} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div>
                            <h2 className="font-semibold text-white/90">{routine.name}</h2>
                            <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-white/40">
                              <span className="inline-flex items-center gap-1.5">
                                <Clock3 size={13} />
                                {scheduleLabel(routine)}
                              </span>
                              <span>{actionLabel(routine.action.type)}</span>
                              <span>{routine.timezone}</span>
                              <span className="inline-flex items-center gap-1.5 text-violet-200/65">
                                {routine.target?.type === 'persona' ? <UserRound size={13} /> : routine.target?.type === 'project' ? <Folder size={13} /> : <Bot size={13} />}
                                {routine.target?.type === 'assistant'
                                  ? 'HomePilot'
                                  : targetNames.get(routine.target?.project_id || '') || (routine.target?.type === 'persona' ? 'Persona' : 'Project')}
                              </span>
                            </div>
                          </div>
                          <button
                            type="button"
                            role="switch"
                            aria-checked={routine.enabled}
                            onClick={() => void toggle(routine)}
                            className={[
                              'relative h-7 w-12 rounded-full transition-colors',
                              routine.enabled ? 'bg-emerald-400/80' : 'bg-white/10',
                            ].join(' ')}
                            title={routine.enabled ? 'Pause routine' : 'Enable routine'}
                          >
                            <span className={[
                              'absolute top-1 h-5 w-5 rounded-full bg-white shadow transition-transform',
                              routine.enabled ? 'translate-x-6' : 'translate-x-1',
                            ].join(' ')} />
                          </button>
                        </div>

                        {(() => {
                          const latest = latestRuns.get(routine.id)
                          if (!latest) return null
                          return (
                            <div className="mt-3 flex items-center gap-2 text-xs text-white/40">
                              {latest.status === 'success' ? <CheckCircle2 size={13} className="text-emerald-300/70" /> : latest.status === 'failed' ? <AlertCircle size={13} className="text-red-300/70" /> : <Clock3 size={13} />}
                              <span>
                                Last run: {latest.status} · {new Date(latest.created_at).toLocaleString()}
                              </span>
                            </div>
                          )
                        })()}

                        <div className="mt-4 flex flex-wrap items-center gap-2">
                          <button
                            type="button"
                            onClick={() => void runNow(routine)}
                            disabled={runningId === routine.id}
                            className="inline-flex items-center gap-1.5 rounded-lg border border-white/[0.08] bg-white/[0.035] px-2.5 py-1.5 text-xs text-white/65 hover:bg-white/[0.07] disabled:opacity-40"
                          >
                            {runningId === routine.id ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
                            Run now
                          </button>
                          {latestRuns.get(routine.id)?.conversation_id ? (
                            <button
                              type="button"
                              onClick={() => openRun(latestRuns.get(routine.id))}
                              className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs text-cyan-200/70 hover:bg-cyan-300/[0.06] hover:text-cyan-100"
                            >
                              Open latest
                            </button>
                          ) : null}
                          <button
                            type="button"
                            onClick={() => setHistoryRoutine(routine)}
                            className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs text-white/45 hover:bg-white/[0.05] hover:text-white/75"
                          >
                            <History size={13} />
                            History
                          </button>
                          <button
                            type="button"
                            onClick={() => setEditing(routine)}
                            className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs text-white/50 hover:bg-white/[0.05] hover:text-white/80"
                          >
                            <Pencil size={13} />
                            Edit
                          </button>
                          <button
                            type="button"
                            onClick={() => void remove(routine)}
                            className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs text-white/35 hover:bg-red-400/[0.06] hover:text-red-200/75"
                          >
                            <Trash2 size={13} />
                            Remove
                          </button>
                        </div>
                      </div>
                    </div>
                  </article>
                )
              })}
            </div>
          )}
        </main>
      </div>

      {historyRoutine ? (
        <div className="fixed inset-0 z-[85] bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-2xl max-h-[80vh] overflow-y-auto rounded-3xl border border-white/10 bg-[#121212] shadow-2xl">
            <div className="sticky top-0 flex items-center justify-between border-b border-white/[0.06] bg-[#121212]/95 px-6 py-5">
              <div>
                <div className="text-lg font-semibold">{historyRoutine.name}</div>
                <div className="text-xs text-white/40 mt-1">Execution history</div>
              </div>
              <button type="button" onClick={() => setHistoryRoutine(null)} className="h-9 w-9 rounded-xl grid place-items-center text-white/45 hover:bg-white/[0.06] hover:text-white">
                <X size={17} />
              </button>
            </div>
            <div className="p-4 space-y-2">
              {runs.filter((run) => run.routine_id === historyRoutine.id).length === 0 ? (
                <div className="py-10 text-center text-sm text-white/35">No runs yet.</div>
              ) : runs.filter((run) => run.routine_id === historyRoutine.id).map((run) => (
                <div key={run.id} className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2 text-sm text-white/75">
                        {run.status === 'success' ? <CheckCircle2 size={14} className="text-emerald-300" /> : run.status === 'failed' ? <AlertCircle size={14} className="text-red-300" /> : <Clock3 size={14} />}
                        <span className="capitalize">{run.status}</span>
                      </div>
                      <div className="mt-1 text-xs text-white/35">{new Date(run.created_at).toLocaleString()}</div>
                      {run.result_preview ? <p className="mt-2 text-xs leading-5 text-white/50">{run.result_preview}</p> : null}
                      {run.error ? <p className="mt-2 text-xs leading-5 text-red-200/60">{run.error}</p> : null}
                    </div>
                    {run.conversation_id ? (
                      <button type="button" onClick={() => openRun(run)} className="rounded-lg px-2.5 py-1.5 text-xs text-cyan-200/70 hover:bg-cyan-300/[0.06]">
                        Open
                      </button>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : null}

      {(creating || editing) ? (
        <RoutineEditor
          initial={editing || undefined}
          targets={targets}
          /* Gated on what the server says it can run, so a template can never offer an
             action this build does not implement. With no capability payload yet, all of
             them show — they are all built on actions HomePilot ships with. */
          presets={availablePresets(capabilities?.actions)}
          onClose={() => { setCreating(false); setEditing(null) }}
          onSave={(draft) => void save(draft)}
          saving={saving}
        />
      ) : null}
    </div>
  )
}
