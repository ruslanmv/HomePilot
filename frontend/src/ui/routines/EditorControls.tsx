/**
 * The three controls the routine form is built from.
 *
 * They live here rather than in `RoutinesView` because each one is a small interaction with
 * its own state — an open/closed menu, a search string — and inlining three of those into a
 * component that already renders a list, a detail pane and a modal makes the form's actual
 * shape impossible to see.
 *
 * ── What these replace, and why ──────────────────────────────────────────────────────────
 *
 * The first version of this form asked the same question twice. Nine template cards at the
 * top ("Morning news", "Start my day", "Daily reminder") and then four action cards below
 * ("Today's news", "Daily briefing", "Reminder", "Assistant task") — thirteen large targets
 * to read before reaching the Name field, and two of them meaning almost the same thing. A
 * person choosing "Morning news" from the first group then had to choose "Today's news"
 * from the second, which reads as the form not having listened.
 *
 * So the hierarchy is now: **a template is a shortcut that fills the form; the routine is
 * the thing being created.** Templates collapse into one dropdown in the header, and the
 * four action types stop being a card grid — they become suggestions under a single task
 * field, which is what they always were.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Bot, Check, ChevronDown, Folder, Search, UserRound, type LucideIcon } from 'lucide-react'

import type { RoutineActionType, RoutineDraft, RoutineTarget } from './types'
import type { RoutinePreset } from './presets'
import type { RoutineTargetProject } from './api'

/** Close on outside click and on Escape — the two ways anyone expects to dismiss a menu. */
function useDismiss(open: boolean, close: () => void) {
  const ref = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    if (!open) return undefined
    const onDown = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) close()
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close()
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, close])
  return ref
}

function matches(haystack: string, needle: string): boolean {
  return haystack.toLowerCase().includes(needle.trim().toLowerCase())
}

// ── templates ───────────────────────────────────────────────────────────────

/**
 * Templates, as one button.
 *
 * Deliberately not a section. A template is optional, and a form that spends its first
 * screen on optional shortcuts makes them look compulsory — people scan all of them before
 * realising they could have typed a name and moved on.
 */
export function TemplateMenu({
  presets,
  applied,
  onPick,
  onClear,
}: {
  presets: RoutinePreset[]
  applied: RoutinePreset | null
  onPick: (preset: RoutinePreset) => void
  onClear: () => void
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const ref = useDismiss(open, () => setOpen(false))

  const groups = useMemo(() => {
    const found = presets.filter(
      (preset) => !query.trim() || matches(preset.title, query) || matches(preset.blurb, query),
    )
    const order: RoutinePreset['group'][] = ['Popular', 'Work', 'Personal']
    return order
      .map((name) => ({ name, items: found.filter((preset) => preset.group === name) }))
      .filter((group) => group.items.length > 0)
  }, [presets, query])

  if (!presets.length) return null

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => { setOpen((v) => !v); setQuery('') }}
        aria-expanded={open}
        aria-haspopup="menu"
        data-testid="routine-template-trigger"
        className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-xs font-medium text-white/70 hover:bg-white/[0.08] hover:text-white"
      >
        {applied ? `Template: ${applied.title}` : 'Start from a template'}
        <ChevronDown size={14} />
      </button>

      {open ? (
        <div
          role="menu"
          data-testid="routine-template-menu"
          className="absolute right-0 z-20 mt-2 w-80 overflow-hidden rounded-2xl border border-white/10 bg-[#171717] shadow-2xl"
        >
          <div className="flex items-center gap-2 border-b border-white/[0.07] px-3 py-2.5">
            <Search size={14} className="text-white/30" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search templates…"
              data-testid="routine-template-search"
              autoFocus
              className="w-full bg-transparent text-xs text-white outline-none placeholder:text-white/30"
            />
          </div>

          {/* Capped and scrollable rather than paged: ten items is not enough to be worth a
              "view all", and a menu that grows to the height of the catalog is the same
              mistake as the card grid, one layer down. */}
          <div className="max-h-72 overflow-y-auto py-1">
            {groups.length === 0 ? (
              <div className="px-4 py-6 text-center text-xs text-white/35" data-testid="routine-template-empty">
                No template matches “{query.trim()}”.
              </div>
            ) : null}
            {groups.map((group) => (
              <div key={group.name}>
                <div className="px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-white/30">
                  {group.name}
                </div>
                {group.items.map((preset) => {
                  const Icon = preset.icon
                  return (
                    <button
                      key={preset.id}
                      type="button"
                      role="menuitem"
                      onClick={() => { onPick(preset); setOpen(false) }}
                      data-testid={`routine-template-${preset.id}`}
                      className="flex w-full items-start gap-3 px-3 py-2 text-left hover:bg-white/[0.06]"
                    >
                      <Icon size={15} className="mt-0.5 shrink-0 text-white/45" />
                      <span className="min-w-0">
                        <span className="block text-xs font-medium text-white/85">{preset.title}</span>
                        <span className="block text-[11px] leading-4 text-white/35">{preset.blurb}</span>
                      </span>
                      {applied?.id === preset.id ? (
                        <Check size={14} className="ml-auto mt-0.5 shrink-0 text-cyan-300" />
                      ) : null}
                    </button>
                  )
                })}
              </div>
            ))}
          </div>

          {applied ? (
            <button
              type="button"
              onClick={() => { onClear(); setOpen(false) }}
              data-testid="routine-template-clear"
              className="w-full border-t border-white/[0.07] px-3 py-2.5 text-left text-[11px] text-white/45 hover:bg-white/[0.06] hover:text-white/70"
            >
              Start from a blank routine instead
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

// ── the task ────────────────────────────────────────────────────────────────

/**
 * The four things a routine can be, as suggestions rather than a card grid.
 *
 * `news_digest` and `daily_briefing` are fixed behaviours that take no free text, so for
 * those the field shows what will happen instead of an input nothing is bound to. Rendering
 * a textarea that silently discards what you type would be worse than rendering none.
 */
const TASK_KINDS: Array<{
  id: RoutineActionType
  label: string
  /** What the field binds to, or `null` when the behaviour takes no text. */
  field: 'prompt' | 'message' | null
  placeholder?: string
  fixed?: string
}> = [
  {
    id: 'assistant_prompt',
    label: 'Custom task',
    field: 'prompt',
    placeholder:
      'For example: check this project’s notes and summarise what changed yesterday.',
  },
  {
    id: 'daily_briefing',
    label: 'Daily briefing',
    field: null,
    fixed: 'Prepare a warm overview of the day: priorities, reminders and useful context.',
  },
  { id: 'news_digest', label: 'News', field: null, fixed: 'Prepare a concise local and world news digest.' },
  {
    id: 'reminder',
    label: 'Reminder',
    field: 'message',
    placeholder: 'What should HomePilot bring to your attention?',
  },
]

export function TaskField({
  action,
  onChangeKind,
  onChangeText,
  onChangeLocation,
}: {
  action: RoutineDraft['action']
  onChangeKind: (type: RoutineActionType) => void
  onChangeText: (value: string) => void
  onChangeLocation: (value: string) => void
}) {
  const kind = TASK_KINDS.find((entry) => entry.id === action.type) || TASK_KINDS[0]
  const value = String(
    (kind.field === 'message' ? action.parameters.message : action.parameters.prompt) ?? '',
  )

  return (
    <section data-testid="routine-task">
      <div className="text-xs font-semibold uppercase tracking-wider text-white/40 mb-2">
        What should HomePilot do?
      </div>

      {kind.field ? (
        <textarea
          value={value}
          onChange={(event) => onChangeText(event.target.value)}
          placeholder={kind.placeholder}
          data-testid="routine-task-text"
          className="min-h-24 w-full rounded-2xl border border-white/10 bg-black/20 px-4 py-3 text-sm leading-6 text-white outline-none focus:border-white/25"
        />
      ) : (
        <div
          data-testid="routine-task-fixed"
          className="rounded-2xl border border-white/[0.08] bg-white/[0.02] px-4 py-3 text-sm leading-6 text-white/65"
        >
          {kind.fixed}
        </div>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-x-1 gap-y-1 text-[11px] text-white/35">
        <span className="mr-1">Suggestions:</span>
        {TASK_KINDS.map((entry, index) => (
          <React.Fragment key={entry.id}>
            {index ? <span className="text-white/15">·</span> : null}
            <button
              type="button"
              onClick={() => onChangeKind(entry.id)}
              data-testid={`routine-task-kind-${entry.id}`}
              aria-pressed={entry.id === action.type}
              className={[
                'rounded-md px-1.5 py-0.5 transition-colors',
                entry.id === action.type
                  ? 'bg-cyan-400/10 text-cyan-200'
                  : 'hover:bg-white/[0.06] hover:text-white/70',
              ].join(' ')}
            >
              {entry.label}
            </button>
          </React.Fragment>
        ))}
      </div>

      {action.type === 'news_digest' ? (
        <label className="mt-3 block">
          <span className="text-xs text-white/40">
            News location <span className="text-white/25">(optional)</span>
          </span>
          <input
            value={String(action.parameters.location || '')}
            onChange={(event) => onChangeLocation(event.target.value)}
            data-testid="routine-news-location"
            placeholder="For example: Milan, Lombardy"
            className="mt-1.5 w-full rounded-2xl border border-white/10 bg-black/20 px-4 py-3 text-sm text-white outline-none focus:border-white/25"
          />
        </label>
      ) : null}
    </section>
  )
}

/** What to call a routine kind. The one place — the list's badge reads this too. */
export function taskKindLabel(type: RoutineActionType): string {
  return TASK_KINDS.find((entry) => entry.id === type)?.label || type
}

/** The parameters a kind starts with, so switching never leaves a stale field behind. */
export function parametersFor(type: RoutineActionType): Record<string, unknown> {
  if (type === 'news_digest') return { scope: ['local', 'national', 'world'], max_items: 6, location: '' }
  if (type === 'reminder') return { message: '' }
  if (type === 'assistant_prompt') return { prompt: '' }
  return {}
}

// ── where it runs ───────────────────────────────────────────────────────────

/**
 * A searchable picker, because an install with forty personas makes a `<select>` useless.
 *
 * Search plus a capped, scrolling list rather than a "most recent" shortlist: the API gives
 * no recency, and inventing an order that looks like recency but is really insertion order
 * is worse than an honest alphabetical list you can type into.
 */
export function TargetPicker({
  target,
  projects,
  onChange,
  hint,
}: {
  target: RoutineTarget
  projects: RoutineTargetProject[]
  onChange: (next: RoutineTarget) => void
  hint?: string | null
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const ref = useDismiss(open, () => setOpen(false))

  const personas = projects.filter((project) => project.project_type === 'persona')
  const others = projects.filter((project) => project.project_type !== 'persona')

  const current = target.type === 'assistant'
    ? null
    : projects.find((project) => project.id === target.project_id) || null
  const label = target.type === 'assistant'
    ? 'HomePilot assistant'
    : current?.name || 'Unknown target'
  const Icon: LucideIcon = target.type === 'persona' ? UserRound : target.type === 'project' ? Folder : Bot

  const filter = (rows: RoutineTargetProject[]) =>
    rows.filter((project) => !query.trim() || matches(project.name, query))

  const pick = (next: RoutineTarget) => {
    onChange(next)
    setOpen(false)
  }

  const row = (
    key: string,
    name: string,
    active: boolean,
    icon: LucideIcon,
    onClick: () => void,
    testId: string,
  ) => {
    const RowIcon = icon
    return (
      <button
        key={key}
        type="button"
        role="option"
        aria-selected={active}
        onClick={onClick}
        data-testid={testId}
        className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-xs text-white/80 hover:bg-white/[0.06]"
      >
        <RowIcon size={14} className="shrink-0 text-white/40" />
        <span className="min-w-0 flex-1 truncate">{name}</span>
        {active ? <Check size={14} className="shrink-0 text-cyan-300" /> : null}
      </button>
    )
  }

  const personaRows = filter(personas)
  const projectRows = filter(others)
  const assistantShown = !query.trim() || matches('HomePilot assistant', query)

  return (
    <section>
      <div className="text-xs font-semibold uppercase tracking-wider text-white/40 mb-2">Run with</div>
      <div className="relative" ref={ref}>
        <button
          type="button"
          onClick={() => { setOpen((v) => !v); setQuery('') }}
          aria-expanded={open}
          aria-haspopup="listbox"
          data-testid="routine-target-trigger"
          className="flex w-full items-center gap-2.5 rounded-2xl border border-white/10 bg-black/20 px-4 py-3 text-sm text-white hover:border-white/20"
        >
          <Icon size={16} className="shrink-0 text-violet-200/80" />
          <span className="min-w-0 flex-1 truncate text-left">{label}</span>
          <ChevronDown size={15} className="shrink-0 text-white/35" />
        </button>

        {open ? (
          <div
            role="listbox"
            data-testid="routine-target-menu"
            className="absolute left-0 right-0 z-20 mt-2 overflow-hidden rounded-2xl border border-white/10 bg-[#171717] shadow-2xl"
          >
            <div className="flex items-center gap-2 border-b border-white/[0.07] px-3 py-2.5">
              <Search size={14} className="text-white/30" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search assistants, personas or projects…"
                data-testid="routine-target-search"
                autoFocus
                className="w-full bg-transparent text-xs text-white outline-none placeholder:text-white/30"
              />
            </div>
            <div className="max-h-72 overflow-y-auto py-1">
              {assistantShown ? (
                <>
                  <div className="px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-white/30">
                    Default
                  </div>
                  {row(
                    'assistant',
                    'HomePilot assistant',
                    target.type === 'assistant',
                    Bot,
                    () => pick({ type: 'assistant' }),
                    'routine-target-assistant',
                  )}
                </>
              ) : null}
              {personaRows.length ? (
                <>
                  <div className="px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-white/30">
                    Personas
                  </div>
                  {personaRows.map((project) => row(
                    project.id,
                    project.name,
                    target.type === 'persona' && target.project_id === project.id,
                    UserRound,
                    () => pick({ type: 'persona', project_id: project.id }),
                    `routine-target-persona-${project.id}`,
                  ))}
                </>
              ) : null}
              {projectRows.length ? (
                <>
                  <div className="px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-white/30">
                    Projects
                  </div>
                  {projectRows.map((project) => row(
                    project.id,
                    project.name,
                    target.type === 'project' && target.project_id === project.id,
                    Folder,
                    () => pick({ type: 'project', project_id: project.id }),
                    `routine-target-project-${project.id}`,
                  ))}
                </>
              ) : null}
              {!assistantShown && !personaRows.length && !projectRows.length ? (
                <div className="px-4 py-6 text-center text-xs text-white/35" data-testid="routine-target-empty">
                  Nothing matches “{query.trim()}”.
                </div>
              ) : null}
            </div>
          </div>
        ) : null}
      </div>

      {hint ? (
        <p className="mt-2 text-[11px] leading-5 text-amber-100/60" role="status" data-testid="routine-target-hint">
          {hint}
        </p>
      ) : null}
    </section>
  )
}
