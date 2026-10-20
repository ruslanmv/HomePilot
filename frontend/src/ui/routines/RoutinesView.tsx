import React, { useEffect, useMemo, useState } from 'react'
import {
  Bell,
  Bookmark,
  Bot,
  CalendarCheck,
  CalendarClock,
  CalendarDays,
  Check,
  CheckCircle2,
  Clock3,
  Folder,
  Globe2,
  History,
  MessageSquare,
  Newspaper,
  Pencil,
  Play,
  Plus,
  RotateCw,
  Sparkles,
  Trash2,
  UserRound,
  Users,
  X,
  Zap,
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
import { ModalSheet } from '../components/ModalSheet'
import {
  Button,
  Card,
  EmptyState,
  FIELD,
  FIELD_LABEL,
  IconButton,
  IconTile,
  InlineAlert,
  Page,
  PageHeader,
  SheetFooter,
  SheetHeader,
  SkeletonRows,
  StatTile,
  StatusBadge,
  Switch,
  type Tone,
} from '../ds'

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

/**
 * What a routine's badge says. Honest about the server: with scheduled execution off, an
 * enabled routine only runs when somebody presses Run now, and the badge says so rather
 * than "Active". Unknown (the capabilities call failed) claims neither.
 */
export function routineStatus(enabled: boolean, schedulerEnabled: boolean | null): { label: string; tone: Tone; title?: string } {
  if (!enabled) return { label: 'Paused', tone: 'slate', title: 'Paused: it does not run until you turn it back on.' }
  if (schedulerEnabled === false) {
    return { label: 'Manual only', tone: 'amber', title: 'Scheduled runs are off on this server. Run now still works.' }
  }
  if (schedulerEnabled === true) return { label: 'Active', tone: 'green', title: 'Runs at its scheduled time.' }
  return { label: 'Enabled', tone: 'green' }
}

export function runStatus(status: RoutineRun['status']): { label: string; tone: Tone; busy?: boolean } {
  if (status === 'success') return { label: 'Succeeded', tone: 'green' }
  if (status === 'failed') return { label: 'Failed', tone: 'red' }
  if (status === 'missed') return { label: 'Missed', tone: 'amber' }
  return { label: 'Running', tone: 'violet', busy: true }
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

  const isWeekdays = (days: number[]) => days.length === 5 && [1, 2, 3, 4, 5].every((d) => days.includes(d))

  return (
    <ModalSheet
      labelledBy="routine-editor-title"
      onRequestClose={onClose}
      className="hp-sheet--wide"
      header={(
        <SheetHeader
          id="routine-editor-title"
          icon={CalendarClock}
          title={initial ? 'Edit routine' : 'New routine'}
          subtitle="Choose when it happens and what HomePilot should prepare."
          onClose={onClose}
          closeLabel="Close routine editor"
          actions={
            /* Templates live in the header, as one button. As a section they were the first
               thing on the page and the largest, which made an optional shortcut read as a
               required step. Editing shows none of this: filling the form in one click is
               helpful on a blank form and destructive on a routine that has run for a month. */
            !initial ? (
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
            ) : null
          }
        />
      )}
      footer={(
        <SheetFooter>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" icon={Check} loading={saving} disabled={!valid} onClick={() => onSave(draft)}>
            {initial ? 'Save changes' : 'Create routine'}
          </Button>
        </SheetFooter>
      )}
    >
      <div className="space-y-6 px-5 py-5 sm:px-6">
        {/* One line, not a card: the template has already done its job by filling the
            fields below, and repeating it as a panel would put the weight straight back. */}
        {pickedPreset ? (
          <div className="text-xs text-white/45" data-testid="routine-template-applied">
            <span className="text-white/70">{pickedPreset.title}</span> template applied ·
            Everything below is editable.
          </div>
        ) : null}

        <section>
          <label htmlFor="routine-name" className={FIELD_LABEL}>Name</label>
          <input
            id="routine-name"
            value={draft.name}
            onChange={(e) => setDraft((prev) => ({ ...prev, name: e.target.value }))}
            className={`${FIELD} mt-2`}
            placeholder="Morning briefing"
            autoFocus
          />
        </section>

        {/* The four action types, as suggestions under one field rather than a second
            grid of cards. */}
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
            makes a native dropdown unusable. */}
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
          <div className={`${FIELD_LABEL} mb-3`}>When?</div>
          <div className="flex flex-wrap gap-2" role="group" aria-label="How often">
            {([
              ['daily', 'Every day'],
              ['weekdays', 'Weekdays'],
              ['custom', 'Custom days'],
            ] as const).map(([id, label]) => {
              const schedule = draft.schedule
              const active =
                id === 'daily'
                  ? schedule.type === 'daily'
                  : id === 'weekdays'
                    ? schedule.type === 'weekly' && isWeekdays(schedule.days)
                    : schedule.type === 'weekly' && !isWeekdays(schedule.days)
              return (
                <button
                  key={id}
                  type="button"
                  aria-pressed={active}
                  onClick={() => setCadence(id)}
                  className={[
                    'h-10 rounded-xl border px-4 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-hp-accent-fg/70',
                    active
                      ? 'border-violet-400/40 bg-hp-accent/20 font-semibold text-white'
                      : 'border-white/10 bg-white/[0.02] text-white/60 hover:bg-white/[0.05] hover:text-white',
                  ].join(' ')}
                >
                  {label}
                </button>
              )
            })}
          </div>

          {draft.schedule.type === 'weekly' ? (
            <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Routine days">
              {DAYS.map((day) => {
                const active = selectedDays.includes(day.id)
                return (
                  <button
                    key={day.id}
                    type="button"
                    aria-pressed={active}
                    aria-label={day.label}
                    onClick={() => toggleDay(day.id)}
                    title={day.label}
                    className={[
                      'h-10 w-10 rounded-full text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-hp-accent-fg/70',
                      active ? 'bg-hp-accent text-white' : 'bg-white/[0.05] text-white/55 hover:bg-white/10 hover:text-white',
                    ].join(' ')}
                  >
                    {day.short}
                  </button>
                )
              })}
            </div>
          ) : null}

          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <label>
              <span className="text-xs text-white/55">Time</span>
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
                className={`${FIELD} mt-1.5`}
              />
            </label>
            <label>
              <span className="text-xs text-white/55">Timezone</span>
              <input
                value={draft.timezone}
                onChange={(e) => setDraft((prev) => ({ ...prev, timezone: e.target.value }))}
                className={`${FIELD} mt-1.5`}
              />
            </label>
          </div>
        </section>

        <section>
          <div className={`${FIELD_LABEL} mb-3`}>Delivery</div>
          <div className="space-y-2">
            <div className="flex items-start gap-3 rounded-xl border border-violet-400/20 bg-hp-accent/[0.06] px-4 py-3">
              <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-hp-accent-fg" aria-hidden />
              <span>
                <span className="block text-sm text-white/85">Save as a conversation</span>
                <span className="mt-0.5 block text-xs text-white/50">
                  Always on. Every routine result is a native HomePilot conversation you can open and continue.
                </span>
              </span>
            </div>
            {([
              ['notification', 'Show a notification', 'Surface a non-disruptive notification when the run is ready.'],
              ['speak_if_active', 'Speak when a companion is active', 'Lets a voice/avatar client present it naturally.'],
              ['catch_up', 'Catch up after downtime', 'Run useful missed work when HomePilot starts again.'],
            ] as const).map(([key, title, description]) => (
              <div key={key} className="flex items-center justify-between gap-4 rounded-xl border border-white/10 bg-white/[0.02] px-4 py-3">
                <span className="min-w-0">
                  <span className="block text-sm text-white/85">{title}</span>
                  <span className="mt-0.5 block text-xs text-white/50">{description}</span>
                </span>
                <Switch
                  label={title}
                  checked={Boolean(draft.delivery[key])}
                  onChange={(next) =>
                    setDraft((prev) => ({
                      ...prev,
                      delivery: { ...prev.delivery, [key]: next, create_conversation: true },
                    }))
                  }
                />
              </div>
            ))}
          </div>
        </section>
      </div>
    </ModalSheet>
  )
}

/** The routine list's empty state: a calendar with a "+" and two quiet sparkles. */
function EmptyArt() {
  return (
    <div className="relative" aria-hidden>
      <span className="grid h-20 w-20 place-items-center rounded-2xl border border-violet-400/25 bg-hp-accent/15 text-hp-accent-fg">
        <CalendarDays size={38} strokeWidth={1.6} />
      </span>
      <span className="absolute -bottom-2 -right-2 grid h-9 w-9 place-items-center rounded-full bg-hp-accent text-white shadow-lg shadow-violet-950/60">
        <Plus size={18} />
      </span>
      <Sparkles size={13} className="absolute -left-6 top-7 text-violet-300/70" />
      <Sparkles size={15} className="absolute -right-8 -top-2 text-violet-300/70" />
    </div>
  )
}

function RoutineCard({
  routine,
  latest,
  targetName,
  schedulerEnabled,
  running,
  onToggle,
  onRun,
  onOpenLatest,
  onHistory,
  onEdit,
  onRemove,
}: {
  routine: Routine
  latest?: RoutineRun
  targetName: string
  schedulerEnabled: boolean | null
  running: boolean
  onToggle: () => void
  onRun: () => void
  onOpenLatest: () => void
  onHistory: () => void
  onEdit: () => void
  onRemove: () => void
}) {
  const [confirming, setConfirming] = useState(false)
  const ActionIcon = ACTION_ICONS[routine.action.type] || Sparkles
  const status = routineStatus(routine.enabled, schedulerEnabled)
  const TargetIcon = routine.target?.type === 'persona' ? UserRound : routine.target?.type === 'project' ? Folder : Bot
  const lastRun = latest ? runStatus(latest.status) : null

  return (
    <Card as="article" padded={false} className="p-4 transition-colors hover:border-white/20 sm:p-5" >
      <div className="flex items-start gap-4" data-testid="routine-card">
        <IconTile icon={ActionIcon} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-semibold text-white">{routine.name}</h2>
            <StatusBadge tone={status.tone} title={status.title}>{status.label}</StatusBadge>
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-white/55">
            <span className="inline-flex items-center gap-1.5"><Clock3 size={13} aria-hidden />{scheduleLabel(routine)}</span>
            <span>{actionLabel(routine.action.type)}</span>
            <span className="inline-flex items-center gap-1.5"><Globe2 size={13} aria-hidden />{routine.timezone}</span>
            <span className="inline-flex items-center gap-1.5 text-hp-accent-fg/90"><TargetIcon size={13} aria-hidden />{targetName}</span>
          </div>
          {latest && lastRun ? (
            <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-white/50">
              <span>Last run</span>
              <StatusBadge tone={lastRun.tone} busy={lastRun.busy}>{lastRun.label}</StatusBadge>
              <span>{new Date(latest.created_at).toLocaleString()}</span>
            </div>
          ) : null}
        </div>
        <Switch checked={routine.enabled} label={routine.enabled ? 'Pause routine' : 'Enable routine'} onChange={onToggle} />
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-1.5 border-t border-white/[0.06] pt-3">
        {confirming ? (
          <>
            <span className="mr-1 text-xs text-white/70">Remove “{routine.name}”? Its past runs stay in your conversations.</span>
            <Button size="sm" variant="secondary" icon={Trash2} className="text-rose-200 hover:text-rose-100" onClick={() => { setConfirming(false); onRemove() }}>
              Remove
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>Cancel</Button>
          </>
        ) : (
          <>
            <Button size="sm" variant="secondary" icon={Play} loading={running} onClick={onRun}>Run now</Button>
            {latest?.conversation_id ? (
              <Button size="sm" variant="ghost" icon={MessageSquare} onClick={onOpenLatest}>Open latest</Button>
            ) : null}
            <Button size="sm" variant="ghost" icon={History} onClick={onHistory}>History</Button>
            <Button size="sm" variant="ghost" icon={Pencil} onClick={onEdit}>Edit</Button>
            <Button size="sm" variant="danger" icon={Trash2} className="ml-auto" onClick={() => setConfirming(true)}>Remove</Button>
          </>
        )}
      </div>
    </Card>
  )
}

function HistorySheet({ routine, runs, onClose, onOpen }: {
  routine: Routine
  runs: RoutineRun[]
  onClose: () => void
  onOpen: (run: RoutineRun) => void
}) {
  const mine = runs.filter((run) => run.routine_id === routine.id)
  return (
    <ModalSheet
      labelledBy="routine-history-title"
      onRequestClose={onClose}
      className="hp-sheet--wide"
      header={<SheetHeader id="routine-history-title" icon={History} title={routine.name} subtitle="Run history" onClose={onClose} closeLabel="Close history" />}
    >
      <div className="space-y-2 px-5 py-5 sm:px-6">
        {mine.length === 0 ? (
          <div className="py-10 text-center text-sm text-white/50">No runs yet. Use Run now to try it.</div>
        ) : mine.map((run) => {
          const status = runStatus(run.status)
          return (
            <Card key={run.id} padded={false} className="p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge tone={status.tone} busy={status.busy}>{status.label}</StatusBadge>
                    <span className="text-xs text-white/50">{new Date(run.created_at).toLocaleString()}</span>
                  </div>
                  {run.result_preview ? <p className="mt-2 text-sm leading-6 text-white/65">{run.result_preview}</p> : null}
                  {run.error ? <p className="mt-2 text-sm leading-6 text-rose-200/80">{run.error}</p> : null}
                </div>
                {run.conversation_id ? (
                  <Button size="sm" variant="ghost" icon={MessageSquare} onClick={() => onOpen(run)}>Open</Button>
                ) : null}
              </div>
            </Card>
          )
        })}
      </div>
    </ModalSheet>
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
  const pausedCount = routines.length - enabledCount
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
  // null: unknown (the capabilities call failed) — then nothing claims either way.
  const schedulerEnabled = capabilities ? Boolean(capabilities.scheduler_enabled) : null

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

  const targetName = (routine: Routine) =>
    routine.target?.type === 'assistant'
      ? 'HomePilot'
      : targetNames.get(routine.target?.project_id || '') || (routine.target?.type === 'persona' ? 'Persona' : 'Project')

  return (
    <Page>
      <PageHeader
        eyebrow="Personal automation"
        eyebrowIcon={CalendarClock}
        title="Routines"
        description={(
          <>
            Define reusable moments for HomePilot — news, briefings, reminders and assistant prompts.
            The same routine definitions are available to optional companion clients such as the 3D Avatar.
          </>
        )}
        actions={<Button variant="primary" size="lg" icon={Plus} onClick={() => setCreating(true)}>New routine</Button>}
      />

      {/* Two up on a phone (the counts are short), three across from tablet width. */}
      <div className="mt-8 grid grid-cols-2 gap-3 sm:grid-cols-3">
        <StatTile
          icon={CalendarCheck}
          label="Active"
          value={enabledCount}
          caption={schedulerEnabled === false ? 'Enabled · run with Run now' : 'Routines running'}
        />
        <StatTile icon={Bookmark} label="Saved" value={routines.length} caption={pausedCount ? `${pausedCount} paused` : 'All routines you have saved'} />
        <StatTile icon={Users} label="Companion ready" value="Shared API contract" caption="Available for 3D Avatar" className="col-span-2 sm:col-span-1" />
      </div>

      {schedulerEnabled === true ? (
        <InlineAlert tone="success" title="Scheduled runs are on." className="mt-6">
          Enabled routines run at their local time, and Run now works any time.
        </InlineAlert>
      ) : schedulerEnabled === false ? (
        <InlineAlert tone="warning" icon={Zap} title="Run now is available." className="mt-6">
          Scheduled runs are turned off on this HomePilot server with{' '}
          <code className="rounded bg-white/[0.06] px-1.5 py-0.5 font-mono text-[12px] text-white/85">ROUTINES_EXECUTION_ENABLED=false</code>.
          Remove that setting, or set it to <code className="rounded bg-white/[0.06] px-1.5 py-0.5 font-mono text-[12px] text-white/85">true</code>,
          and restart HomePilot to run routines at their time.
        </InlineAlert>
      ) : !loading ? (
        <InlineAlert tone="info" className="mt-6">
          Could not check whether scheduled runs are on for this server. Run now always works.
        </InlineAlert>
      ) : null}

      {error ? (
        <InlineAlert
          tone="danger"
          className="mt-4"
          action={(
            <div className="flex items-center gap-1">
              <Button size="sm" variant="secondary" icon={RotateCw} onClick={() => void refresh()}>Try again</Button>
              <IconButton size="sm" label="Dismiss" icon={X} onClick={() => setError('')} />
            </div>
          )}
        >
          {error}
        </InlineAlert>
      ) : null}

      <main className="mt-6" aria-label="Your routines">
        {loading ? (
          <SkeletonRows count={3} label="Loading routines" />
        ) : routines.length === 0 ? (
          <EmptyState
            art={<EmptyArt />}
            title="No routines yet"
            action={<Button variant="primary" size="lg" icon={Plus} onClick={() => setCreating(true)}>Create your first routine</Button>}
          >
            Start with a morning news digest or daily briefing. You can pause or remove it at any time.
          </EmptyState>
        ) : (
          <div className="space-y-3">
            {routines.map((routine) => (
              <RoutineCard
                key={routine.id}
                routine={routine}
                latest={latestRuns.get(routine.id)}
                targetName={targetName(routine)}
                schedulerEnabled={schedulerEnabled}
                running={runningId === routine.id}
                onToggle={() => void toggle(routine)}
                onRun={() => void runNow(routine)}
                onOpenLatest={() => openRun(latestRuns.get(routine.id))}
                onHistory={() => setHistoryRoutine(routine)}
                onEdit={() => setEditing(routine)}
                onRemove={() => void remove(routine)}
              />
            ))}
          </div>
        )}
      </main>

      {historyRoutine ? (
        <HistorySheet routine={historyRoutine} runs={runs} onClose={() => setHistoryRoutine(null)} onOpen={openRun} />
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
    </Page>
  )
}
