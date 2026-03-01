/**
 * MeetingRightRail — Tabbed side panel: Agenda | Actions | Stats.
 *
 * - Agenda:  checkable items from room.agenda[] + manual add
 * - Actions: auto-extracted action items from transcript
 * - Stats:   meeting duration, message count, per-persona speaking distribution
 *
 * Collapsible — when collapsed, hidden entirely.
 */

import React, { useState, useMemo, useCallback } from 'react'
import {
  X,
  ListChecks,
  Zap,
  BarChart3,
  Clock,
  MessageSquare,
  Users,
  CheckCircle2,
  Circle,
  FileText,
  Plus,
  Pencil,
  Trash2,
  Check,
  Target,
} from 'lucide-react'
import type { MeetingRoom, PersonaSummary, MeetingMessage, IntentSnapshot } from './types'
import { DocumentsPanel } from './DocumentsPanel'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface MeetingRightRailProps {
  room: MeetingRoom
  personas: PersonaSummary[]
  backendUrl: string
  apiKey?: string
  onClose: () => void
  onUpdateAgenda?: (agenda: string[]) => Promise<void>
  onUpdateTopic?: (topic: string) => Promise<void>
}

// ---------------------------------------------------------------------------
// Action-item extraction heuristic
// ---------------------------------------------------------------------------

const ACTION_PATTERNS = [
  /\bshould\b/i,
  /\bneed\s+to\b/i,
  /\bassign\b/i,
  /\btodo\b/i,
  /\baction\s*item\b/i,
  /\blet'?s\b/i,
  /\bwe\s+will\b/i,
  /\bfollow[- ]up\b/i,
  /\bplease\b/i,
  /\bmake\s+sure\b/i,
]

function extractActions(messages: MeetingMessage[]): Array<{ sender: string; text: string; ts: number }> {
  const actions: Array<{ sender: string; text: string; ts: number }> = []
  for (const msg of messages) {
    if (msg.role !== 'assistant') continue
    const sentences = msg.content.split(/[.!?\n]+/).filter((s) => s.trim().length > 10)
    for (const sentence of sentences) {
      if (ACTION_PATTERNS.some((p) => p.test(sentence))) {
        actions.push({ sender: msg.sender_name, text: sentence.trim(), ts: msg.timestamp })
      }
    }
  }
  return actions.slice(-12) // cap at 12 most recent
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDuration(startTs: number): string {
  const secs = Math.floor(Date.now() / 1000 - startTs)
  if (secs < 60) return `${secs}s`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ${secs % 60}s`
  return `${Math.floor(secs / 3600)}h ${Math.floor((secs % 3600) / 60)}m`
}

type Tab = 'agenda' | 'documents' | 'actions' | 'stats'

const TABS: Array<{ id: Tab; label: string; icon: React.ReactNode }> = [
  { id: 'agenda', label: 'Agenda', icon: <ListChecks size={12} /> },
  { id: 'documents', label: 'Docs', icon: <FileText size={12} /> },
  { id: 'actions', label: 'Actions', icon: <Zap size={12} /> },
  { id: 'stats', label: 'Stats', icon: <BarChart3 size={12} /> },
]

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function MeetingRightRail({ room, personas, backendUrl, apiKey, onClose, onUpdateAgenda, onUpdateTopic }: MeetingRightRailProps) {
  const [activeTab, setActiveTab] = useState<Tab>('agenda')
  const [checkedAgenda, setCheckedAgenda] = useState<Set<number>>(new Set())

  // ── Agenda editing state ──
  const [editingIdx, setEditingIdx] = useState<number | null>(null)
  const [editText, setEditText] = useState('')
  const [addingNew, setAddingNew] = useState(false)
  const [newItemText, setNewItemText] = useState('')
  // ── Topic editing state ──
  const [editingTopic, setEditingTopic] = useState(false)
  const [topicText, setTopicText] = useState(room.topic || '')

  const messages = room.messages || []
  const personaMap = useMemo(() => new Map(personas.map((p) => [p.id, p])), [personas])

  const actions = useMemo(() => extractActions(messages), [messages])

  // Per-persona message counts for stats
  const speakerCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const msg of messages) {
      counts[msg.sender_name] = (counts[msg.sender_name] || 0) + 1
    }
    return Object.entries(counts).sort(([, a], [, b]) => b - a)
  }, [messages])

  const maxCount = speakerCounts.length > 0 ? speakerCounts[0][1] : 1

  const toggleAgenda = (idx: number) => {
    setCheckedAgenda((prev) => {
      const next = new Set(prev)
      if (next.has(idx)) next.delete(idx)
      else next.add(idx)
      return next
    })
  }

  return (
    <div className="flex-shrink-0 w-64 border-l border-white/[0.04] bg-white/[0.01] flex flex-col animate-rail-slide-right overflow-hidden">
      {/* Tabs */}
      <div className="flex items-center border-b border-white/[0.04]">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex-1 flex items-center justify-center gap-1 py-2.5 text-xs font-medium transition-colors relative ${
              activeTab === tab.id
                ? 'text-cyan-300'
                : 'text-white/30 hover:text-white/50'
            }`}
          >
            {tab.icon}
            {tab.label}
            {activeTab === tab.id && (
              <span className="absolute bottom-0 left-1/4 right-1/4 h-[1.5px] bg-cyan-400/60 rounded-full animate-tab-underline" />
            )}
          </button>
        ))}
        <button
          onClick={onClose}
          className="p-1.5 mx-1 rounded hover:bg-white/5 text-white/20 hover:text-white/40 transition-colors"
          title="Close panel"
        >
          <X size={12} />
        </button>
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto scrollbar-hide px-3 py-3">
        {/* ═══ AGENDA ═══ */}
        {activeTab === 'agenda' && (
          <div className="space-y-3">
            {/* ── Main Topic ── */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <Target size={10} className="text-cyan-400/60" />
                  <span className="text-[9px] font-semibold text-white/30 uppercase tracking-wider">Main Topic</span>
                </div>
                {onUpdateTopic && !editingTopic && (
                  <button
                    onClick={() => { setEditingTopic(true); setTopicText(room.topic || '') }}
                    className="p-0.5 rounded hover:bg-white/5 text-white/20 hover:text-white/40 transition-colors"
                    title="Edit topic"
                  >
                    <Pencil size={10} />
                  </button>
                )}
              </div>
              {editingTopic && onUpdateTopic ? (
                <div className="flex items-center gap-1.5">
                  <input
                    type="text"
                    value={topicText}
                    onChange={(e) => setTopicText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        onUpdateTopic(topicText.trim())
                        setEditingTopic(false)
                      }
                      if (e.key === 'Escape') setEditingTopic(false)
                    }}
                    autoFocus
                    placeholder="What is this discussion about?"
                    className="flex-1 bg-white/[0.04] border border-white/10 rounded-lg px-2.5 py-1.5 text-xs text-white/70 placeholder:text-white/20 focus:outline-none focus:border-cyan-500/30"
                  />
                  <button
                    onClick={() => { onUpdateTopic(topicText.trim()); setEditingTopic(false) }}
                    className="p-1 rounded hover:bg-cyan-500/10 text-cyan-400/60 hover:text-cyan-300 transition-colors"
                  >
                    <Check size={12} />
                  </button>
                </div>
              ) : (
                <div
                  className={`px-2.5 py-2 rounded-lg text-xs leading-relaxed ${
                    room.topic
                      ? 'bg-cyan-500/[0.04] border border-cyan-500/10 text-white/55'
                      : 'bg-white/[0.02] border border-white/[0.04] text-white/20 italic'
                  }`}
                  onClick={onUpdateTopic ? () => { setEditingTopic(true); setTopicText(room.topic || '') } : undefined}
                  style={onUpdateTopic ? { cursor: 'pointer' } : undefined}
                >
                  {room.topic || 'No topic set — click to add'}
                </div>
              )}
            </div>

            {/* ── Divider ── */}
            <div className="border-t border-white/[0.04]" />

            {/* ── Agenda Items ── */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="text-[9px] font-semibold text-white/30 uppercase tracking-wider">Agenda Items</span>
                {onUpdateAgenda && (
                  <button
                    onClick={() => { setAddingNew(true); setNewItemText('') }}
                    className="p-0.5 rounded hover:bg-white/5 text-white/20 hover:text-white/40 transition-colors"
                    title="Add agenda item"
                  >
                    <Plus size={12} />
                  </button>
                )}
              </div>

              {/* Add new item input */}
              {addingNew && onUpdateAgenda && (
                <div className="flex items-center gap-1.5 animate-msg-slide-in">
                  <input
                    type="text"
                    value={newItemText}
                    onChange={(e) => setNewItemText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && newItemText.trim()) {
                        onUpdateAgenda([...(room.agenda || []), newItemText.trim()])
                        setNewItemText('')
                        setAddingNew(false)
                      }
                      if (e.key === 'Escape') setAddingNew(false)
                    }}
                    autoFocus
                    placeholder="New agenda item..."
                    className="flex-1 bg-white/[0.04] border border-white/10 rounded-lg px-2.5 py-1.5 text-xs text-white/70 placeholder:text-white/20 focus:outline-none focus:border-cyan-500/30"
                  />
                  <button
                    onClick={() => {
                      if (newItemText.trim()) {
                        onUpdateAgenda([...(room.agenda || []), newItemText.trim()])
                        setNewItemText('')
                        setAddingNew(false)
                      }
                    }}
                    className="p-1 rounded hover:bg-cyan-500/10 text-cyan-400/60 hover:text-cyan-300 transition-colors"
                  >
                    <Check size={12} />
                  </button>
                </div>
              )}

              {(!room.agenda || room.agenda.length === 0) && !addingNew ? (
                <div className="text-center py-4">
                  <ListChecks size={18} className="mx-auto text-white/10 mb-1.5" />
                  <p className="text-[10px] text-white/20">No agenda items</p>
                  {onUpdateAgenda && (
                    <button
                      onClick={() => { setAddingNew(true); setNewItemText('') }}
                      className="mt-2 text-[10px] text-cyan-400/50 hover:text-cyan-300/70 transition-colors"
                    >
                      + Add first item
                    </button>
                  )}
                </div>
              ) : (
                (room.agenda || []).map((item, i) => {
                  const done = checkedAgenda.has(i)
                  const isEditing = editingIdx === i

                  if (isEditing && onUpdateAgenda) {
                    return (
                      <div key={i} className="flex items-center gap-1.5 animate-msg-slide-in">
                        <input
                          type="text"
                          value={editText}
                          onChange={(e) => setEditText(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' && editText.trim()) {
                              const updated = [...(room.agenda || [])]
                              updated[i] = editText.trim()
                              onUpdateAgenda(updated)
                              setEditingIdx(null)
                            }
                            if (e.key === 'Escape') setEditingIdx(null)
                          }}
                          autoFocus
                          className="flex-1 bg-white/[0.04] border border-white/10 rounded-lg px-2.5 py-1.5 text-xs text-white/70 focus:outline-none focus:border-cyan-500/30"
                        />
                        <button
                          onClick={() => {
                            if (editText.trim()) {
                              const updated = [...(room.agenda || [])]
                              updated[i] = editText.trim()
                              onUpdateAgenda(updated)
                              setEditingIdx(null)
                            }
                          }}
                          className="p-1 rounded hover:bg-cyan-500/10 text-cyan-400/60 hover:text-cyan-300 transition-colors"
                        >
                          <Check size={12} />
                        </button>
                      </div>
                    )
                  }

                  return (
                    <div
                      key={i}
                      className={`group w-full flex items-start gap-2 px-2.5 py-2 rounded-lg text-left transition-all ${
                        done
                          ? 'bg-emerald-500/[0.04] border border-emerald-500/10'
                          : 'bg-white/[0.02] border border-white/[0.04] hover:border-white/[0.08]'
                      }`}
                    >
                      <button onClick={() => toggleAgenda(i)} className="flex-shrink-0 mt-0.5">
                        {done ? (
                          <CheckCircle2 size={13} className="text-emerald-400/70 animate-agenda-check" />
                        ) : (
                          <Circle size={13} className="text-white/15" />
                        )}
                      </button>
                      <span className={`flex-1 text-xs leading-relaxed ${done ? 'text-white/30 line-through' : 'text-white/55'}`}>
                        {item}
                      </span>
                      {/* Edit/Remove controls */}
                      {onUpdateAgenda && (
                        <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button
                            onClick={() => { setEditingIdx(i); setEditText(item) }}
                            className="p-0.5 rounded hover:bg-white/5 text-white/15 hover:text-white/40 transition-colors"
                            title="Edit"
                          >
                            <Pencil size={10} />
                          </button>
                          <button
                            onClick={() => {
                              const updated = (room.agenda || []).filter((_, idx) => idx !== i)
                              onUpdateAgenda(updated)
                            }}
                            className="p-0.5 rounded hover:bg-red-500/10 text-white/15 hover:text-red-300/60 transition-colors"
                            title="Remove"
                          >
                            <Trash2 size={10} />
                          </button>
                        </div>
                      )}
                    </div>
                  )
                })
              )}
              {room.agenda && room.agenda.length > 0 && (
                <div className="text-[9px] text-white/15 text-center mt-2">
                  {checkedAgenda.size}/{room.agenda.length} completed
                </div>
              )}
            </div>
          </div>
        )}

        {/* ═══ DOCUMENTS ═══ */}
        {activeTab === 'documents' && (
          <DocumentsPanel
            backendUrl={backendUrl}
            apiKey={apiKey}
            roomId={room.id}
            initialDocuments={room.documents || []}
          />
        )}

        {/* ═══ ACTIONS ═══ */}
        {activeTab === 'actions' && (
          <div className="space-y-2">
            {actions.length === 0 ? (
              <div className="text-center py-6">
                <Zap size={20} className="mx-auto text-white/10 mb-2" />
                <p className="text-xs text-white/20">No action items yet</p>
                <p className="text-[10px] text-white/12 mt-1">Action items are auto-extracted from the conversation</p>
              </div>
            ) : (
              actions.map((action, i) => (
                <div
                  key={i}
                  className="px-2.5 py-2 rounded-lg bg-white/[0.02] border border-white/[0.04]"
                >
                  <div className="flex items-center gap-1.5 mb-1">
                    <span className="w-1 h-1 rounded-full bg-cyan-400/50" />
                    <span className="text-[9px] text-cyan-300/50 font-medium">{action.sender}</span>
                  </div>
                  <p className="text-[10px] text-white/45 leading-relaxed">{action.text}</p>
                </div>
              ))
            )}
          </div>
        )}

        {/* ═══ STATS ═══ */}
        {activeTab === 'stats' && (
          <div className="space-y-4">
            {/* Quick metrics */}
            <div className="grid grid-cols-2 gap-2">
              <div className="px-2.5 py-2 rounded-lg bg-white/[0.02] border border-white/[0.04]">
                <div className="flex items-center gap-1 mb-1">
                  <Clock size={9} className="text-white/20" />
                  <span className="text-[9px] text-white/25">Duration</span>
                </div>
                <span className="text-[12px] text-white/60 font-medium">{formatDuration(room.created_at)}</span>
              </div>
              <div className="px-2.5 py-2 rounded-lg bg-white/[0.02] border border-white/[0.04]">
                <div className="flex items-center gap-1 mb-1">
                  <MessageSquare size={9} className="text-white/20" />
                  <span className="text-[9px] text-white/25">Messages</span>
                </div>
                <span className="text-[12px] text-white/60 font-medium">{messages.length}</span>
              </div>
              <div className="px-2.5 py-2 rounded-lg bg-white/[0.02] border border-white/[0.04]">
                <div className="flex items-center gap-1 mb-1">
                  <Users size={9} className="text-white/20" />
                  <span className="text-[9px] text-white/25">Participants</span>
                </div>
                <span className="text-[12px] text-white/60 font-medium">{room.participant_ids.length + 1}</span>
              </div>
              <div className="px-2.5 py-2 rounded-lg bg-white/[0.02] border border-white/[0.04]">
                <div className="flex items-center gap-1 mb-1">
                  <Zap size={9} className="text-white/20" />
                  <span className="text-[9px] text-white/25">Actions</span>
                </div>
                <span className="text-[12px] text-white/60 font-medium">{actions.length}</span>
              </div>
            </div>

            {/* Speaking distribution with dominance indicators */}
            <div>
              <div className="text-[9px] font-semibold text-white/30 uppercase tracking-wider mb-2">
                Speaking Distribution
              </div>
              <div className="space-y-1.5">
                {speakerCounts.map(([name, count]) => {
                  const ratio = messages.length > 0 ? count / messages.filter(m => m.role === 'assistant').length : 0
                  const isDominant = ratio > 0.4 && messages.filter(m => m.role === 'assistant').length >= 3
                  return (
                    <div key={name} className="flex items-center gap-2">
                      <span className={`text-[10px] w-16 truncate text-right ${isDominant ? 'text-amber-300/60' : 'text-white/40'}`}>
                        {name}
                      </span>
                      <div className="flex-1 h-1.5 rounded-full bg-white/[0.04] overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all duration-500 ${isDominant ? 'bg-amber-400/50' : 'bg-cyan-400/40'}`}
                          style={{ width: `${Math.round((count / maxCount) * 100)}%` }}
                        />
                      </div>
                      <span className="text-[9px] text-white/25 w-4 text-right">{count}</span>
                      {isDominant && (
                        <span className="text-[8px] text-amber-400/60" title="Dominance suppression active (>40% of messages)">!</span>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>

            {/* Orchestration Policy */}
            {room.policy && (
              <div>
                <div className="text-[9px] font-semibold text-white/30 uppercase tracking-wider mb-2">
                  Policy
                </div>
                <div className="space-y-1">
                  {[
                    { label: 'Engine', value: room.policy.engine === 'crew' ? 'Task Workflow' : (room.policy.engine || 'Native') },
                    ...(room.policy.engine === 'crew' && room.policy.crew?.profile_id
                      ? [{ label: 'Profile', value: room.policy.crew.profile_id.replace(/_/g, ' ') }]
                      : []),
                    ...(room.policy.engine === 'crew' && room.policy.crew?.budget_limit_eur
                      ? [{ label: 'Budget', value: `${room.policy.crew.budget_limit_eur} EUR` }]
                      : []),
                    { label: 'Speak threshold', value: room.policy.speak_threshold },
                    { label: 'Hand-raise threshold', value: room.policy.hand_raise_threshold },
                    { label: 'Hand-raise TTL', value: room.policy.hand_raise_ttl_rounds ? `${room.policy.hand_raise_ttl_rounds} rounds` : undefined },
                    { label: 'Max speakers/event', value: room.policy.max_speakers_per_event },
                    { label: 'Max rounds/event', value: room.policy.max_rounds_per_event },
                    { label: 'Cooldown', value: room.policy.cooldown_turns ? `${room.policy.cooldown_turns} turn(s)` : undefined },
                  ].filter(item => item.value !== undefined).map((item) => (
                    <div key={item.label} className="flex items-center justify-between px-2 py-1 rounded bg-white/[0.02]">
                      <span className="text-[9px] text-white/25">{item.label}</span>
                      <span className="text-[9px] text-white/45 font-mono">{item.value}</span>
                    </div>
                  ))}
                </div>
                {room.round !== undefined && room.round > 0 && (
                  <div className="mt-2 text-center text-[9px] text-white/20">
                    Round {room.round}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
