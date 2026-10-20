/**
 * "Choose models" — which of a connection's models are offered in chat (level 1 of the
 * model shelf, see lib/modelShelf.ts).
 *
 * Built for long catalogs: a search field, the connection's base models and its assistants in
 * two groups with their own select-all, and one reset to the connection's own suggestion.
 * Changes apply as they are made; there is nothing to save.
 */
import React, { useId, useMemo, useState } from 'react'
import { Check, Search, Sparkles, X } from 'lucide-react'
import { isSuggested, setShown, shownModels, type ShelfModel, type ShelfSource } from '../lib/modelShelf'

const GROUPS: Array<{ kind: ShelfModel['kind']; title: string; hint: string }> = [
  { kind: 'model', title: 'Models', hint: 'Base models served by this connection.' },
  { kind: 'assistant', title: 'Assistants & workflows', hint: 'Presets built on a model, with their own instructions.' },
]

export interface ModelShelfPickerProps {
  source: ShelfSource
  onClose: () => void
  /** The default ("Suggested") rule; Multimodal passes one that asks the vision check. */
  suggest?: (m: ShelfModel) => boolean
  title?: string
  hint?: string
  /** A short status shown on each row (Multimodal: the vision check's verdict). */
  statusOf?: (m: ShelfModel) => string
  /** Called for each model the user adds, e.g. to check it straight away. */
  onAdded?: (m: ShelfModel) => void
}

export function ModelShelfPicker({
  source, onClose, suggest, title = 'Models offered in chat',
  hint = 'Each chat can pick one of these in its Chat settings.', statusOf, onAdded,
}: ModelShelfPickerProps) {
  const uid = useId()
  const [query, setQuery] = useState('')
  const shown = useMemo(() => new Set(shownModels(source, suggest).map((m) => m.id)), [source, suggest])
  const total = source.models.length

  const q = query.trim().toLowerCase()
  const matches = (m: ShelfModel) => !q || m.label.toLowerCase().includes(q) || m.id.toLowerCase().includes(q)

  const apply = (next: Set<string>) => {
    for (const m of source.models) if (next.has(m.id) && !shown.has(m.id)) onAdded?.(m)
    setShown(source.key, 'custom', source.models.filter((m) => next.has(m.id)).map((m) => m.id))
  }
  const toggle = (id: string) => {
    const next = new Set(shown)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    apply(next)
  }
  const setGroup = (models: ShelfModel[], on: boolean) => {
    const next = new Set(shown)
    for (const m of models) {
      if (on) next.add(m.id)
      else next.delete(m.id)
    }
    apply(next)
  }

  return (
    <section
      aria-labelledby={`${uid}-title`}
      className="mt-3 rounded-2xl border border-white/10 bg-black/40 p-3 sm:p-4"
      data-testid="model-shelf-picker"
    >
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <h3 id={`${uid}-title`} className="text-sm font-semibold text-white">{title}</h3>
          <p className="mt-0.5 text-xs text-white/50">
            {shown.size} of {total} shown. {hint}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close model choice"
          className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-white/10 bg-white/[0.03] text-white/60 hover:bg-white/[0.08] hover:text-white"
        >
          <X size={14} />
        </button>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <label className="relative min-w-0 flex-[1_1_14rem]">
          <span className="sr-only">Search models</span>
          <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-white/35" aria-hidden />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search models"
            className="h-9 w-full rounded-xl border border-white/10 bg-black/40 pl-9 pr-3 text-sm text-white outline-none placeholder:text-white/30 focus:border-cyan-400/50"
          />
        </label>
        <button
          type="button"
          onClick={() => setShown(source.key, 'suggested')}
          aria-pressed={source.mode === 'suggested'}
          className={[
            'inline-flex h-9 items-center gap-1.5 rounded-xl border px-3 text-xs font-semibold transition-colors',
            source.mode === 'suggested'
              ? 'border-cyan-400/40 bg-cyan-400/10 text-cyan-100'
              : 'border-white/10 bg-white/[0.03] text-white/70 hover:bg-white/[0.07] hover:text-white',
          ].join(' ')}
          title="Base models that are available and not hidden, as the connection describes them"
        >
          <Sparkles size={13} aria-hidden /> Suggested
        </button>
      </div>

      <div className="mt-3 max-h-72 space-y-4 overflow-y-auto pr-1">
        {GROUPS.map((group) => {
          const all = source.models.filter((m) => m.kind === group.kind)
          if (!all.length) return null
          const visible = all.filter(matches)
          const onCount = all.filter((m) => shown.has(m.id)).length
          return (
            <fieldset key={group.kind}>
              <legend className="flex w-full items-center justify-between gap-2 text-xs font-semibold text-white/70">
                <span>{group.title} <span className="font-normal text-white/40">· {onCount}/{all.length}</span></span>
                <span className="flex gap-2 font-normal">
                  <button type="button" className="text-cyan-300/90 hover:text-white" onClick={() => setGroup(all, true)}>All</button>
                  <button type="button" className="text-white/45 hover:text-white" onClick={() => setGroup(all, false)}>None</button>
                </span>
              </legend>
              <p className="mb-1.5 mt-0.5 text-[11px] text-white/35">{group.hint}</p>
              {visible.length === 0 ? (
                <p className="px-2 py-1.5 text-xs text-white/35">No match.</p>
              ) : (
                <ul className="space-y-0.5">
                  {visible.map((m) => {
                    const on = shown.has(m.id)
                    return (
                      <li key={m.id}>
                        <label className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 hover:bg-white/[0.04]">
                          <input
                            type="checkbox"
                            checked={on}
                            onChange={() => toggle(m.id)}
                            className="peer sr-only"
                          />
                          <span
                            aria-hidden
                            className={[
                              'grid h-4 w-4 shrink-0 place-items-center rounded border transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-cyan-400/60',
                              on ? 'border-cyan-400/70 bg-cyan-400/80 text-black' : 'border-white/20 bg-transparent',
                            ].join(' ')}
                          >
                            {on ? <Check size={11} strokeWidth={3} /> : null}
                          </span>
                          <span className="min-w-0 flex-1 truncate text-sm text-white/85" title={m.id}>{m.label}</span>
                          {statusOf ? (
                            <span className={[
                              'shrink-0 text-[10px]',
                              statusOf(m).startsWith('✓') ? 'text-emerald-300/90' : statusOf(m).startsWith('✗') ? 'text-rose-300/80' : 'text-white/40',
                            ].join(' ')}>{statusOf(m)}</span>
                          ) : isSuggested(m) && group.kind === 'model' ? null : m.available === false ? (
                            <span className="shrink-0 text-[10px] text-amber-200/70">unavailable</span>
                          ) : m.hidden ? (
                            <span className="shrink-0 text-[10px] text-white/35">hidden by gateway</span>
                          ) : null}
                        </label>
                      </li>
                    )
                  })}
                </ul>
              )}
            </fieldset>
          )
        })}
      </div>
    </section>
  )
}

export default ModelShelfPicker
