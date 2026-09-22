import React, { useEffect, useMemo, useState } from 'react'
import {
  Bell,
  CalendarClock,
  Check,
  Clock3,
  Loader2,
  Newspaper,
  Pencil,
  Plus,
  Sparkles,
  Trash2,
  X,
  type LucideIcon,
} from 'lucide-react'

import { createRoutine, deleteRoutine, listRoutines, updateRoutine } from './api'
import type { Routine, RoutineActionType, RoutineDraft } from './types'

const DAYS = [
  { id: 1, short: 'M', label: 'Monday' },
  { id: 2, short: 'T', label: 'Tuesday' },
  { id: 3, short: 'W', label: 'Wednesday' },
  { id: 4, short: 'T', label: 'Thursday' },
  { id: 5, short: 'F', label: 'Friday' },
  { id: 6, short: 'S', label: 'Saturday' },
  { id: 7, short: 'S', label: 'Sunday' },
]

const ACTIONS: Array<{
  id: RoutineActionType
  title: string
  description: string
  icon: LucideIcon
}> = [
  {
    id: 'news_digest',
    title: 'Today’s news',
    description: 'Prepare a concise local + broader news digest.',
    icon: Newspaper,
  },
  {
    id: 'daily_briefing',
    title: 'Daily briefing',
    description: 'A warm overview of the day, priorities, reminders and context.',
    icon: Sparkles,
  },
  {
    id: 'reminder',
    title: 'Reminder',
    description: 'Surface a short message at the chosen time.',
    icon: Bell,
  },
  {
    id: 'assistant_prompt',
    title: 'Assistant prompt',
    description: 'Keep a reusable informational prompt on a schedule.',
    icon: CalendarClock,
  },
]

function browserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  } catch {
    return 'UTC'
  }
}

function defaultDraft(): RoutineDraft {
  return {
    name: 'Morning news',
    enabled: true,
    timezone: browserTimezone(),
    schedule: { type: 'daily', time: '08:00' },
    action: {
      type: 'news_digest',
      parameters: {
        scope: ['local', 'national', 'world'],
        max_items: 6,
      },
    },
    delivery: {
      in_app: true,
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
  return ACTIONS.find((action) => action.id === type)?.title || type
}

function RoutineEditor({
  initial,
  onClose,
  onSave,
  saving,
}: {
  initial?: Routine
  onClose: () => void
  onSave: (draft: RoutineDraft) => void
  saving: boolean
}) {
  const [draft, setDraft] = useState<RoutineDraft>(() => {
    if (!initial) return defaultDraft()
    return {
      name: initial.name,
      enabled: initial.enabled,
      timezone: initial.timezone,
      schedule: initial.schedule,
      action: initial.action,
      delivery: initial.delivery,
    }
  })

  const selectedDays = draft.schedule.type === 'weekly' ? draft.schedule.days : []

  const setAction = (type: RoutineActionType) => {
    const parameters =
      type === 'news_digest'
        ? { scope: ['local', 'national', 'world'], max_items: 6 }
        : type === 'reminder'
          ? { message: '' }
          : type === 'assistant_prompt'
            ? { prompt: '' }
            : {}
    setDraft((prev) => ({ ...prev, action: { type, parameters } }))
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
    (draft.action.type !== 'assistant_prompt' || prompt.trim().length > 0)

  return (
    <div className="fixed inset-0 z-[90] bg-black/65 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-3xl border border-white/10 bg-[#121212] shadow-2xl">
        <div className="sticky top-0 z-10 flex items-center justify-between px-6 py-5 border-b border-white/[0.06] bg-[#121212]/95 backdrop-blur">
          <div>
            <div className="text-lg font-semibold text-white">
              {initial ? 'Edit routine' : 'New routine'}
            </div>
            <div className="text-sm text-white/45 mt-1">Choose when it happens and what HomePilot should prepare.</div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="h-9 w-9 rounded-xl grid place-items-center text-white/45 hover:text-white hover:bg-white/[0.06]"
            aria-label="Close routine editor"
          >
            <X size={18} />
          </button>
        </div>

        <div className="p-6 space-y-7">
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

          <section>
            <div className="text-xs font-semibold uppercase tracking-wider text-white/40 mb-3">What should HomePilot do?</div>
            <div className="grid gap-2 sm:grid-cols-2">
              {ACTIONS.map((action) => {
                const Icon = action.icon
                const selected = draft.action.type === action.id
                return (
                  <button
                    key={action.id}
                    type="button"
                    onClick={() => setAction(action.id)}
                    className={[
                      'rounded-2xl border p-4 text-left transition-colors',
                      selected
                        ? 'border-cyan-400/40 bg-cyan-400/[0.08]'
                        : 'border-white/[0.08] bg-white/[0.02] hover:bg-white/[0.05]',
                    ].join(' ')}
                  >
                    <div className="flex items-start gap-3">
                      <div className={[
                        'h-9 w-9 rounded-xl grid place-items-center shrink-0',
                        selected ? 'bg-cyan-400/10 text-cyan-300' : 'bg-white/[0.05] text-white/55',
                      ].join(' ')}>
                        <Icon size={18} />
                      </div>
                      <div>
                        <div className="text-sm font-semibold text-white/90">{action.title}</div>
                        <div className="text-xs leading-5 text-white/40 mt-1">{action.description}</div>
                      </div>
                    </div>
                  </button>
                )
              })}
            </div>

            {draft.action.type === 'reminder' ? (
              <textarea
                value={message}
                onChange={(e) =>
                  setDraft((prev) => ({
                    ...prev,
                    action: { ...prev.action, parameters: { ...prev.action.parameters, message: e.target.value } },
                  }))
                }
                className="mt-3 min-h-24 w-full rounded-2xl border border-white/10 bg-black/20 px-4 py-3 text-sm text-white outline-none focus:border-white/25"
                placeholder="What should HomePilot remind you about?"
              />
            ) : null}

            {draft.action.type === 'assistant_prompt' ? (
              <textarea
                value={prompt}
                onChange={(e) =>
                  setDraft((prev) => ({
                    ...prev,
                    action: { ...prev.action, parameters: { ...prev.action.parameters, prompt: e.target.value } },
                  }))
                }
                className="mt-3 min-h-24 w-full rounded-2xl border border-white/10 bg-black/20 px-4 py-3 text-sm text-white outline-none focus:border-white/25"
                placeholder="For example: Summarize my priorities for today."
              />
            ) : null}
          </section>

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
              {[
                ['in_app', 'Show inside HomePilot', 'Keep the result available in the app.'],
                ['speak_if_active', 'Speak when a companion is active', 'Lets a voice/avatar client present it naturally.'],
                ['catch_up', 'Catch up after downtime', 'Keep the routine relevant if HomePilot was offline at the scheduled time.'],
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
                          delivery: { ...prev.delivery, [key]: e.target.checked },
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
}: {
  backendUrl: string
  apiKey?: string
}) {
  const [routines, setRoutines] = useState<Routine[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState<Routine | null>(null)
  const [creating, setCreating] = useState(false)

  const enabledCount = useMemo(() => routines.filter((routine) => routine.enabled).length, [routines])

  const refresh = async () => {
    setLoading(true)
    setError('')
    try {
      setRoutines(await listRoutines(backendUrl, apiKey))
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

        <div className="mt-7 rounded-2xl border border-amber-300/15 bg-amber-300/[0.035] px-4 py-3 text-xs leading-5 text-white/50">
          This first Routines release stores and manages definitions only. Automatic background execution is intentionally a separate capability,
          so enabling this tab cannot change existing HomePilot behavior or trigger actions unexpectedly.
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
                const ActionIcon = ACTIONS.find((action) => action.id === routine.action.type)?.icon || Sparkles
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

                        <div className="mt-4 flex items-center gap-2">
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

      {(creating || editing) ? (
        <RoutineEditor
          initial={editing || undefined}
          onClose={() => { setCreating(false); setEditing(null) }}
          onSave={(draft) => void save(draft)}
          saving={saving}
        />
      ) : null}
    </div>
  )
}
