/**
 * CreateSessionWizard — 3-step wizard for creating a team meeting session.
 *
 * Step 1: Name & Description
 * Step 2: Select Personas (drag-style multi-select from available list)
 * Step 3: Settings (turn mode, agenda)
 *
 * Simple, easy-to-use flow modeled after the Agent project wizard.
 */

import React, { useState, useCallback } from 'react'
import {
  X,
  ChevronLeft,
  ChevronRight,
  Users,
  Settings,
  FileText,
  Check,
  Zap,
  MessageSquare,
  Crown,
  Activity,
  Workflow,
  DollarSign,
} from 'lucide-react'
import type { PersonaSummary } from './types'
import { PersonaSelectorEnterprise } from './PersonaSelectorEnterprise'
import { TEAM_BUNDLES } from './teamBundles'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface CreateSessionWizardProps {
  personas: PersonaSummary[]
  backendUrl: string
  onCancel: () => void
  onCreate: (params: {
    name: string
    description: string
    participant_ids: string[]
    turn_mode: string
    agenda: string[]
    policy?: { engine?: string; crew?: { profile_id?: string; budget_limit_eur?: number } }
  }) => Promise<void>
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const TURN_MODES = [
  {
    value: 'reactive',
    label: 'Reactive (Recommended)',
    description: 'Only relevant personas speak — best for brainstorming and productivity',
    icon: <Activity size={16} />,
  },
  {
    value: 'round-robin',
    label: 'Round Robin',
    description: 'Each persona responds in order after you speak',
    icon: <Zap size={16} />,
  },
  {
    value: 'free-form',
    label: 'Free Form',
    description: 'Personas respond naturally as in a real conversation',
    icon: <MessageSquare size={16} />,
  },
  {
    value: 'moderated',
    label: 'Moderated',
    description: 'You choose which persona speaks next',
    icon: <Crown size={16} />,
  },
]

const ENGINE_OPTIONS = [
  {
    value: 'native' as const,
    label: 'Conversation',
    description: 'Free-form discussion with smart speaker selection',
    icon: <MessageSquare size={16} />,
  },
  {
    value: 'crew' as const,
    label: 'Task Workflow',
    description: 'Stage-based collaboration with structured output',
    icon: <Workflow size={16} />,
  },
]

const CREW_PROFILES = [
  { id: 'task_planner_v1', label: 'Task Planner', description: 'Plan, budget, and finalize tasks' },
  { id: 'brainstorm_v1', label: 'Brainstorm', description: 'Ideate, evaluate, and recommend' },
  { id: 'draft_and_edit_v1', label: 'Draft & Edit', description: 'Outline, draft, and refine content' },
]

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function CreateSessionWizard({
  personas,
  backendUrl,
  onCancel,
  onCreate,
}: CreateSessionWizardProps) {
  const [step, setStep] = useState(1)
  const totalSteps = 3

  // Step 1
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  // Step 2
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())

  // Step 3
  const [engine, setEngine] = useState<'native' | 'crew'>('native')
  const [crewProfileId, setCrewProfileId] = useState('task_planner_v1')
  const [budgetLimit, setBudgetLimit] = useState('')
  const [turnMode, setTurnMode] = useState('reactive')
  const [agendaText, setAgendaText] = useState('')

  const [creating, setCreating] = useState(false)

  const togglePersona = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const canProceed = step === 1 ? name.trim().length > 0
    : step === 2 ? selectedIds.size > 0
    : true

  const handleCreate = useCallback(async () => {
    if (creating) return
    setCreating(true)
    try {
      const agenda = agendaText
        .split('\n')
        .map((l) => l.trim())
        .filter(Boolean)
      const policy = engine === 'crew'
        ? {
            engine: 'crew' as const,
            crew: {
              profile_id: crewProfileId,
              ...(budgetLimit ? { budget_limit_eur: parseFloat(budgetLimit) } : {}),
            },
          }
        : { engine: 'native' as const }

      await onCreate({
        name: name.trim(),
        description: description.trim(),
        participant_ids: Array.from(selectedIds),
        turn_mode: turnMode,
        agenda,
        policy,
      })
    } catch (e) {
      console.error('Failed to create session:', e)
    } finally {
      setCreating(false)
    }
  }, [creating, name, description, selectedIds, turnMode, agendaText, engine, crewProfileId, budgetLimit, onCreate])

  return (
    <div className="h-full w-full bg-black text-white font-sans overflow-hidden flex flex-col min-h-0">

      {/* ═══════════════ HEADER ═══════════════ */}
      <div className="flex-shrink-0 flex items-center justify-between px-6 py-4 border-b border-white/[0.06]">
        <div className="flex items-center gap-3">
          <Users size={18} className="text-cyan-400" />
          <span className="text-sm font-semibold">New Team Session</span>
        </div>
        <button
          onClick={onCancel}
          className="p-2 rounded-lg hover:bg-white/5 text-white/40 hover:text-white/60 transition-colors"
        >
          <X size={16} />
        </button>
      </div>

      {/* ═══════════════ STEP INDICATOR ═══════════════ */}
      <div className="flex-shrink-0 px-6 py-3 flex items-center gap-2">
        {[
          { n: 1, label: 'Details', icon: <FileText size={12} /> },
          { n: 2, label: 'Personas', icon: <Users size={12} /> },
          { n: 3, label: 'Settings', icon: <Settings size={12} /> },
        ].map(({ n, label, icon }) => (
          <React.Fragment key={n}>
            {n > 1 && <div className={`flex-1 h-px ${step >= n ? 'bg-cyan-500/40' : 'bg-white/[0.06]'}`} />}
            <div
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                step === n
                  ? 'bg-cyan-500/15 text-cyan-300 border border-cyan-500/20'
                  : step > n
                    ? 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/20'
                    : 'bg-white/[0.03] text-white/30 border border-white/[0.06]'
              }`}
            >
              {step > n ? <Check size={12} /> : icon}
              {label}
            </div>
          </React.Fragment>
        ))}
      </div>

      {/* ═══════════════ STEP CONTENT ═══════════════ */}
      <div className="flex-1 min-h-0 overflow-y-auto px-6 py-4 scrollbar-hide">

        {/* Step 1: Details */}
        {step === 1 && (
          <div className="max-w-lg mx-auto space-y-5">
            <div>
              <h2 className="text-lg font-semibold text-white mb-1">Name your session</h2>
              <p className="text-xs text-white/35">Give your meeting room a name and optional description.</p>
            </div>

            <div className="space-y-3">
              <div>
                <label className="block text-xs text-white/50 mb-1.5">Session Name</label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g., Morning Standup, Strategy Review..."
                  className="w-full px-3.5 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-sm text-white placeholder:text-white/20 focus:outline-none focus:border-cyan-500/40 transition-colors"
                  autoFocus
                />
              </div>

              <div>
                <label className="block text-xs text-white/50 mb-1.5">Description (optional)</label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="What's this session about?"
                  rows={3}
                  className="w-full px-3.5 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-sm text-white placeholder:text-white/20 focus:outline-none focus:border-cyan-500/40 transition-colors resize-none"
                />
              </div>
            </div>
          </div>
        )}

        {/* Step 2: Select Personas (Enterprise) */}
        {step === 2 && (
          <div className="max-w-5xl mx-auto">
            <PersonaSelectorEnterprise
              personas={personas}
              backendUrl={backendUrl}
              selectedIds={selectedIds}
              onToggle={togglePersona}
              onSetSelected={setSelectedIds}
              bundles={TEAM_BUNDLES}
            />
          </div>
        )}

        {/* Step 3: Settings */}
        {step === 3 && (
          <div className="max-w-lg mx-auto space-y-5">
            <div>
              <h2 className="text-lg font-semibold text-white mb-1">Session settings</h2>
              <p className="text-xs text-white/35">Choose how the conversation flows and set an optional agenda.</p>
            </div>

            {/* Engine type */}
            <div>
              <label className="block text-xs text-white/50 mb-2">Session Type</label>
              <div className="flex gap-2">
                {ENGINE_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => setEngine(opt.value)}
                    className={`flex-1 flex items-center gap-3 p-3 rounded-xl border transition-all text-left ${
                      engine === opt.value
                        ? 'bg-cyan-500/[0.08] border-cyan-500/30'
                        : 'bg-white/[0.02] border-white/[0.06] hover:border-white/15'
                    }`}
                  >
                    <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
                      engine === opt.value ? 'bg-cyan-500/20 text-cyan-300' : 'bg-white/5 text-white/30'
                    }`}>
                      {opt.icon}
                    </div>
                    <div className="flex-1">
                      <div className="text-sm font-medium text-white">{opt.label}</div>
                      <div className="text-[10px] text-white/35">{opt.description}</div>
                    </div>
                    {engine === opt.value && (
                      <div className="w-5 h-5 rounded-full bg-cyan-500 flex items-center justify-center">
                        <Check size={12} className="text-white" />
                      </div>
                    )}
                  </button>
                ))}
              </div>
            </div>

            {/* Crew workflow settings (only when engine === 'crew') */}
            {engine === 'crew' && (
              <div className="space-y-3 rounded-xl border border-cyan-500/15 bg-cyan-500/[0.03] p-4">
                <div>
                  <label className="block text-xs text-white/50 mb-2">Workflow Profile</label>
                  <div className="space-y-2">
                    {CREW_PROFILES.map((profile) => (
                      <button
                        key={profile.id}
                        type="button"
                        onClick={() => setCrewProfileId(profile.id)}
                        className={`w-full flex items-center gap-3 p-2.5 rounded-lg border transition-all text-left ${
                          crewProfileId === profile.id
                            ? 'bg-cyan-500/[0.08] border-cyan-500/25'
                            : 'bg-white/[0.02] border-white/[0.06] hover:border-white/15'
                        }`}
                      >
                        <div className="flex-1">
                          <div className="text-sm font-medium text-white">{profile.label}</div>
                          <div className="text-[10px] text-white/35">{profile.description}</div>
                        </div>
                        {crewProfileId === profile.id && (
                          <div className="w-4 h-4 rounded-full bg-cyan-500 flex items-center justify-center">
                            <Check size={10} className="text-white" />
                          </div>
                        )}
                      </button>
                    ))}
                  </div>
                </div>
                <div>
                  <label className="block text-xs text-white/50 mb-1.5">Budget Limit (optional)</label>
                  <div className="flex items-center gap-2">
                    <DollarSign size={14} className="text-white/30" />
                    <input
                      type="number"
                      value={budgetLimit}
                      onChange={(e) => setBudgetLimit(e.target.value)}
                      placeholder="No limit"
                      min="0"
                      step="5"
                      className="flex-1 px-3 py-2 rounded-lg bg-white/[0.04] border border-white/[0.08] text-sm text-white placeholder:text-white/20 focus:outline-none focus:border-cyan-500/40 transition-colors"
                    />
                  </div>
                </div>
              </div>
            )}

            {/* Turn mode (only visible for native engine) */}
            {engine === 'native' && (
            <div>
              <label className="block text-xs text-white/50 mb-2">Conversation Style</label>
              <div className="space-y-2">
                {TURN_MODES.map((tm) => (
                  <button
                    key={tm.value}
                    type="button"
                    onClick={() => setTurnMode(tm.value)}
                    className={`w-full flex items-center gap-3 p-3 rounded-xl border transition-all text-left ${
                      turnMode === tm.value
                        ? 'bg-cyan-500/[0.08] border-cyan-500/30'
                        : 'bg-white/[0.02] border-white/[0.06] hover:border-white/15'
                    }`}
                  >
                    <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
                      turnMode === tm.value ? 'bg-cyan-500/20 text-cyan-300' : 'bg-white/5 text-white/30'
                    }`}>
                      {tm.icon}
                    </div>
                    <div className="flex-1">
                      <div className="text-sm font-medium text-white">{tm.label}</div>
                      <div className="text-[10px] text-white/35">{tm.description}</div>
                    </div>
                    {turnMode === tm.value && (
                      <div className="w-5 h-5 rounded-full bg-cyan-500 flex items-center justify-center">
                        <Check size={12} className="text-white" />
                      </div>
                    )}
                  </button>
                ))}
              </div>
            </div>
            )}

            {/* Agenda */}
            <div>
              <label className="block text-xs text-white/50 mb-1.5">Agenda (optional, one topic per line)</label>
              <textarea
                value={agendaText}
                onChange={(e) => setAgendaText(e.target.value)}
                placeholder={"Status updates\nBlockers\nAction items"}
                rows={4}
                className="w-full px-3.5 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-sm text-white placeholder:text-white/20 focus:outline-none focus:border-cyan-500/40 transition-colors resize-none"
              />
            </div>

            {/* Summary */}
            <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4 space-y-2">
              <div className="text-xs text-white/50 font-medium">Summary</div>
              <div className="text-sm text-white font-medium">{name || 'Untitled'}</div>
              <div className="flex items-center gap-3 text-[11px] text-white/40">
                <span className="flex items-center gap-1">
                  <Users size={10} />
                  {selectedIds.size} persona{selectedIds.size !== 1 ? 's' : ''} + You
                </span>
                <span className="flex items-center gap-1">
                  {ENGINE_OPTIONS.find((e) => e.value === engine)?.icon}
                  {ENGINE_OPTIONS.find((e) => e.value === engine)?.label}
                </span>
                {engine === 'native' && (
                  <span className="flex items-center gap-1">
                    {TURN_MODES.find((t) => t.value === turnMode)?.icon}
                    {TURN_MODES.find((t) => t.value === turnMode)?.label}
                  </span>
                )}
                {engine === 'crew' && (
                  <span className="flex items-center gap-1 text-cyan-300/50">
                    <Workflow size={10} />
                    {CREW_PROFILES.find((p) => p.id === crewProfileId)?.label}
                  </span>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ═══════════════ FOOTER ═══════════════ */}
      <div className="flex-shrink-0 px-6 py-4 border-t border-white/[0.06] flex items-center justify-between">
        <button
          onClick={step > 1 ? () => setStep((s) => s - 1) : onCancel}
          className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm text-white/50 hover:text-white/70 bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.06] transition-all"
        >
          <ChevronLeft size={14} />
          {step > 1 ? 'Back' : 'Cancel'}
        </button>

        <div className="text-xs text-white/20">
          Step {step} of {totalSteps}
        </div>

        <button
          onClick={step < totalSteps ? () => setStep((s) => s + 1) : handleCreate}
          disabled={!canProceed || creating}
          className={`flex items-center gap-1.5 px-5 py-2 rounded-xl text-sm font-semibold transition-all ${
            canProceed && !creating
              ? step < totalSteps
                ? 'bg-cyan-600 hover:bg-cyan-500 text-white border border-cyan-500/20'
                : 'bg-gradient-to-r from-cyan-600 to-blue-600 hover:brightness-110 text-white border border-cyan-500/20 shadow-lg shadow-cyan-500/10'
              : 'bg-white/[0.04] text-white/20 border border-white/[0.04] cursor-not-allowed'
          }`}
        >
          {creating ? (
            'Creating...'
          ) : step < totalSteps ? (
            <>Next <ChevronRight size={14} /></>
          ) : (
            <>Create Session <Check size={14} /></>
          )}
        </button>
      </div>

      <style>{`
        .scrollbar-hide::-webkit-scrollbar { display: none; }
        .scrollbar-hide { -ms-overflow-style: none; scrollbar-width: none; }
      `}</style>
    </div>
  )
}
