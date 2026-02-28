/**
 * PersonaSelectorEnterprise — Enterprise-grade persona selection for team wizard.
 *
 * Features:
 *   - Search: instant filter across name, description, persona_class
 *   - Role filter: All / Creative / Analyst / Ops / Engineering / Research / Product
 *   - Sort: A-Z, Recent (placeholder for now)
 *   - Bundle templates: Quick-apply team presets (Brainstorm, Incident, Standup)
 *   - Two-panel layout: Available (left/main) + Selected Tray (right)
 *   - Team coverage indicators: visual check for role coverage gaps
 *   - Scales to 5 or 100+ personas
 *
 * Designed to be a drop-in replacement for Step 2 of CreateSessionWizard.
 */

import React, { useMemo, useState, useCallback } from 'react'
import { Check, Plus, X, Search, SlidersHorizontal, Users } from 'lucide-react'
import type { PersonaSummary } from './types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function resolveAvatarUrl(persona: PersonaSummary, backendUrl: string): string | null {
  const thumb = persona.persona_appearance?.selected_thumb_filename
  const main = persona.persona_appearance?.selected_filename
  const file = thumb || main
  if (!file) return null
  if (file.startsWith('http')) return file
  return `${backendUrl}/files/${file}`
}

type RoleFilter = 'all' | 'secretary' | 'analyst' | 'creative' | 'engineer' | 'research' | 'product'

function inferRoleTag(p: PersonaSummary): RoleFilter {
  const txt = `${p.name ?? ''} ${p.description ?? ''} ${p.persona_agent?.persona_class ?? ''}`.toLowerCase()
  if (txt.includes('secret') || txt.includes('assistant') || txt.includes('calendar') || txt.includes('minutes')) return 'secretary'
  if (txt.includes('analyst') || txt.includes('data') || txt.includes('kpi') || txt.includes('metrics')) return 'analyst'
  if (txt.includes('creative') || txt.includes('design') || txt.includes('brand') || txt.includes('copy')) return 'creative'
  if (txt.includes('engineer') || txt.includes('devops') || txt.includes('api') || txt.includes('infra')) return 'engineer'
  if (txt.includes('research') || txt.includes('study') || txt.includes('evidence')) return 'research'
  if (txt.includes('product') || txt.includes('roadmap') || txt.includes('requirements')) return 'product'
  return 'all'
}

const ROLE_LABELS: Record<RoleFilter, string> = {
  all: 'All',
  creative: 'Creative',
  analyst: 'Analyst',
  secretary: 'Ops/Notes',
  engineer: 'Engineering',
  research: 'Research',
  product: 'Product',
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type PersonaBundle = {
  id: string
  name: string
  description: string
  match: (p: PersonaSummary) => boolean
  maxPick?: number
}

export interface PersonaSelectorEnterpriseProps {
  personas: PersonaSummary[]
  backendUrl: string
  selectedIds: Set<string>
  onToggle: (id: string) => void
  onSetSelected: (ids: Set<string>) => void
  bundles?: PersonaBundle[]
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function CoverageRow({ label, ok }: { label: string; ok: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <div className="text-white/40">{label}</div>
      <div className={ok ? 'text-emerald-300' : 'text-white/25'}>
        {ok ? '\u2713' : '\u2014'}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function PersonaSelectorEnterprise({
  personas,
  backendUrl,
  selectedIds,
  onToggle,
  onSetSelected,
  bundles = [],
}: PersonaSelectorEnterpriseProps) {
  const [query, setQuery] = useState('')
  const [role, setRole] = useState<RoleFilter>('all')
  const [sort, setSort] = useState<'az' | 'recent'>('az')

  const personaProjects = useMemo(
    () => personas.filter((p) => p.project_type === 'persona'),
    [personas],
  )

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    let items = personaProjects

    if (role !== 'all') {
      items = items.filter((p) => inferRoleTag(p) === role)
    }
    if (q) {
      items = items.filter((p) => {
        const hay = `${p.name ?? ''} ${p.description ?? ''} ${p.persona_agent?.persona_class ?? ''}`.toLowerCase()
        return hay.includes(q)
      })
    }

    if (sort === 'az') {
      items = [...items].sort((a, b) => (a.name ?? '').localeCompare(b.name ?? ''))
    }
    return items
  }, [personaProjects, query, role, sort])

  const selectedList = useMemo(() => {
    const map = new Map(personaProjects.map((p) => [p.id, p]))
    return Array.from(selectedIds)
      .map((id) => map.get(id))
      .filter(Boolean) as PersonaSummary[]
  }, [personaProjects, selectedIds])

  const coverage = useMemo(() => {
    const tags = new Set<RoleFilter>()
    for (const p of selectedList) tags.add(inferRoleTag(p))
    return {
      creative: tags.has('creative'),
      analyst: tags.has('analyst'),
      secretary: tags.has('secretary'),
      engineer: tags.has('engineer'),
      research: tags.has('research'),
      product: tags.has('product'),
    }
  }, [selectedList])

  const applyBundle = useCallback((bundleId: string) => {
    const b = bundles.find((x) => x.id === bundleId)
    if (!b) return
    const picks = personaProjects.filter(b.match)
    const limited = typeof b.maxPick === 'number' ? picks.slice(0, b.maxPick) : picks
    const next = new Set(selectedIds)
    for (const p of limited) next.add(p.id)
    onSetSelected(next)
  }, [bundles, personaProjects, selectedIds, onSetSelected])

  return (
    <div className="space-y-4">
      {/* Header */}
      <div>
        <h2 className="text-lg font-semibold text-white mb-1">Build your team</h2>
        <p className="text-xs text-white/35">
          Brainstorm works best with 3-6 personas. You are host by default.
          {selectedIds.size > 0 && (
            <span className="text-cyan-300 ml-1">{selectedIds.size} selected</span>
          )}
        </p>
      </div>

      {/* Controls row */}
      <div className="flex flex-col sm:flex-row gap-2">
        {/* Search */}
        <div className="flex-1 flex items-center gap-2 rounded-xl bg-white/[0.03] border border-white/[0.06] px-3 py-2 focus-within:border-cyan-500/30 transition-colors">
          <Search size={14} className="text-white/30 flex-shrink-0" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search personas..."
            className="flex-1 bg-transparent text-sm text-white placeholder:text-white/20 focus:outline-none"
          />
          {query && (
            <button
              onClick={() => setQuery('')}
              className="p-1 rounded-lg hover:bg-white/5 text-white/40 hover:text-white/70 transition-colors"
              type="button"
              aria-label="Clear search"
            >
              <X size={14} />
            </button>
          )}
        </div>

        {/* Filters */}
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-2 rounded-xl bg-white/[0.03] border border-white/[0.06] px-3 py-2">
            <SlidersHorizontal size={14} className="text-white/30" />
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as RoleFilter)}
              className="bg-transparent text-sm text-white/70 focus:outline-none cursor-pointer"
            >
              {(Object.keys(ROLE_LABELS) as RoleFilter[]).map((r) => (
                <option key={r} value={r}>Role: {ROLE_LABELS[r]}</option>
              ))}
            </select>
          </div>

          <div className="rounded-xl bg-white/[0.03] border border-white/[0.06] px-3 py-2">
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as 'az' | 'recent')}
              className="bg-transparent text-sm text-white/70 focus:outline-none cursor-pointer"
            >
              <option value="az">Sort: A-Z</option>
              <option value="recent">Sort: Recent</option>
            </select>
          </div>

          {bundles.length > 0 && (
            <div className="rounded-xl bg-white/[0.03] border border-white/[0.06] px-3 py-2">
              <select
                value=""
                onChange={(e) => {
                  if (e.target.value) applyBundle(e.target.value)
                }}
                className="bg-transparent text-sm text-white/70 focus:outline-none cursor-pointer"
              >
                <option value="">Bundles...</option>
                {bundles.map((b) => (
                  <option key={b.id} value={b.id}>{b.name}</option>
                ))}
              </select>
            </div>
          )}
        </div>
      </div>

      {/* Two-panel layout */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        {/* Available personas (left, 2/3 width) */}
        <div className="lg:col-span-2 rounded-2xl border border-white/[0.06] bg-white/[0.02] p-3">
          <div className="flex items-center justify-between mb-2">
            <div className="text-xs text-white/50 font-medium">Available Personas</div>
            <div className="text-[11px] text-white/25">{filtered.length} shown</div>
          </div>

          {filtered.length === 0 ? (
            <div className="text-center py-10 text-sm text-white/35">
              {personaProjects.length === 0
                ? 'No persona projects found. Create a Persona from the Project tab first.'
                : 'No personas match your search/filter.'}
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-[340px] overflow-y-auto scrollbar-thin">
              {filtered.map((p) => {
                const selected = selectedIds.has(p.id)
                const avatarUrl = resolveAvatarUrl(p, backendUrl)
                const roleTag = inferRoleTag(p)
                return (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => onToggle(p.id)}
                    className={`flex items-center gap-3 p-3 rounded-xl border transition-all duration-200 text-left ${
                      selected
                        ? 'bg-cyan-500/[0.08] border-cyan-500/30 shadow-lg shadow-cyan-500/5'
                        : 'bg-white/[0.02] border-white/[0.06] hover:border-white/15 hover:bg-white/[0.04]'
                    }`}
                  >
                    <div className="w-10 h-10 rounded-full border border-white/10 bg-white/5 flex-shrink-0 overflow-hidden">
                      {avatarUrl ? (
                        <img src={avatarUrl} alt={p.name} className="w-full h-full object-cover" />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center text-sm text-white/30 font-bold">
                          {(p.name || 'P').charAt(0).toUpperCase()}
                        </div>
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-white truncate">{p.name}</div>
                      <div className="text-[10px] text-white/35 truncate">
                        {p.persona_agent?.persona_class || p.description || 'Persona'}
                      </div>
                      {roleTag !== 'all' && (
                        <div className="mt-1 inline-flex text-[10px] px-2 py-0.5 rounded-full bg-white/[0.03] border border-white/[0.06] text-white/45">
                          {ROLE_LABELS[roleTag]}
                        </div>
                      )}
                    </div>
                    <div className={`w-7 h-7 rounded-xl border flex items-center justify-center transition-all duration-200 ${
                      selected
                        ? 'bg-cyan-500 border-cyan-400 text-white scale-110'
                        : 'border-white/10 bg-white/[0.03]'
                    }`}>
                      {selected ? <Check size={14} /> : <Plus size={14} className="text-white/20" />}
                    </div>
                  </button>
                )
              })}
            </div>
          )}
        </div>

        {/* Selected tray (right, 1/3 width) */}
        <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-3 flex flex-col">
          <div className="flex items-center justify-between mb-2">
            <div className="text-xs text-white/50 font-medium flex items-center gap-2">
              <Users size={14} className="text-white/35" /> Selected Team
            </div>
            <div className="text-[11px] text-white/25">{selectedList.length + 1} total</div>
          </div>

          {/* Always included: Human host */}
          <div className="flex items-center gap-2 p-2 rounded-xl bg-cyan-500/[0.06] border border-cyan-500/20 mb-2">
            <div className="text-xs font-medium text-white flex-1">You</div>
            <div className="text-[10px] px-2 py-0.5 rounded-full bg-cyan-500/15 text-cyan-300 border border-cyan-500/20">
              Host
            </div>
          </div>

          {/* Selected personas */}
          {selectedList.length === 0 ? (
            <div className="text-sm text-white/30 py-6 text-center flex-1 flex items-center justify-center">
              Pick 3-6 personas for best results.
            </div>
          ) : (
            <div className="space-y-1.5 flex-1 max-h-[220px] overflow-y-auto scrollbar-thin">
              {selectedList.map((p) => {
                const avatarUrl = resolveAvatarUrl(p, backendUrl)
                return (
                  <div key={p.id} className="flex items-center gap-2 p-2 rounded-xl border border-white/[0.06] bg-white/[0.02] group/item">
                    <div className="w-6 h-6 rounded-full border border-white/10 bg-white/5 flex-shrink-0 overflow-hidden">
                      {avatarUrl ? (
                        <img src={avatarUrl} alt={p.name} className="w-full h-full object-cover" />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center text-[8px] text-white/30 font-bold">
                          {(p.name || 'P').charAt(0).toUpperCase()}
                        </div>
                      )}
                    </div>
                    <div className="text-xs text-white font-medium truncate flex-1">{p.name}</div>
                    <button
                      type="button"
                      onClick={() => onToggle(p.id)}
                      className="text-[10px] px-2 py-1 rounded-lg bg-white/[0.03] border border-white/[0.06] text-white/40 hover:text-red-300 hover:bg-red-500/10 hover:border-red-500/20 transition-all duration-150 opacity-0 group-hover/item:opacity-100"
                    >
                      Remove
                    </button>
                  </div>
                )
              })}
            </div>
          )}

          {/* Coverage indicators */}
          <div className="mt-3 pt-3 border-t border-white/[0.06]">
            <div className="text-[11px] text-white/50 font-medium mb-2">Team Coverage</div>
            <div className="space-y-1 text-[11px]">
              <CoverageRow label="Creative" ok={coverage.creative} />
              <CoverageRow label="Analytics" ok={coverage.analyst} />
              <CoverageRow label="Ops/Notes" ok={coverage.secretary} />
              <CoverageRow label="Engineering" ok={coverage.engineer} />
              <CoverageRow label="Research" ok={coverage.research} />
              <CoverageRow label="Product" ok={coverage.product} />
            </div>
          </div>
        </div>
      </div>

      <style>{`
        .scrollbar-thin::-webkit-scrollbar { width: 4px; }
        .scrollbar-thin::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 4px; }
        .scrollbar-thin::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.15); }
        select option { background: #111; color: #ccc; }
      `}</style>
    </div>
  )
}
