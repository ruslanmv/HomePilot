/**
 * SessionPanel — the project's Conversation Hub.
 *
 * Relationship-first UX: sessions are internal transport, users see
 * "Conversations".
 *
 * Layout, top to bottom:
 *  - the project's identity: its saved picture (or type icon), name, type,
 *    age, memories and description
 *  - Continue Conversation — the primary action, reopens the latest one
 *  - Talk by Voice / Chat by Text — reuse the active conversation
 *  - Fresh voice / text chat — explicitly start a new one (secondary)
 *  - Memories — the existing manager (forget one / forget all), opened in place
 *  - Conversation history — newest first, type · messages · last activity;
 *    micro-conversations (< 3 messages) hidden by default
 *  - No "session" language in user-facing copy
 */

import React, { useEffect, useState, useCallback, useMemo } from 'react'
import {
  Brain,
  CalendarDays,
  ChevronRight,
  Clock,
  Database,
  MessageCircle,
  Mic,
  Pin,
  Play,
  RotateCcw,
  Trash2,
} from 'lucide-react'
import { ProjectAvatar } from '../components/ProjectAvatar'
import { Collapsible } from '../motion'
import { projectTypeLabel, relationshipAge, shortDate, timeAgo } from '../projectIdentity'
import {
  PersonaSession,
  PersonaMemoryEntry,
  resolveSession,
  createSession,
  listSessions,
  endSession,
  getMemories,
  forgetMemory,
} from './sessionsApi'
import ConfirmForgetDialog from '../components/ConfirmForgetDialog'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SessionPanelProps {
  projectId: string
  projectName: string
  projectCreatedAt?: number
  /** The project's saved picture (projectAvatarUrl); its type icon is shown without one. */
  avatarUrl?: string | null
  /** Tried when avatarUrl fails to load (the face crop → the regular thumbnail). */
  avatarFallbackUrl?: string | null
  /** e.g. 'persona' — drives the type badge and the fallback icon. */
  projectType?: string
  /** Short project description, shown under the name. */
  description?: string
  /** Called when user wants to open a session — parent handles navigation */
  onOpenSession: (session: PersonaSession) => void
  /** Called when user wants to open voice mode with a specific session */
  onOpenVoiceSession: (session: PersonaSession) => void
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function SessionPanel({
  projectId,
  projectName,
  projectCreatedAt,
  avatarUrl,
  avatarFallbackUrl,
  projectType,
  description,
  onOpenSession,
  onOpenVoiceSession,
}: SessionPanelProps) {
  const [sessions, setSessions] = useState<PersonaSession[]>([])
  const [activeSession, setActiveSession] = useState<PersonaSession | null>(null)
  const [memoryCount, setMemoryCount] = useState(0)
  const [memories, setMemories] = useState<PersonaMemoryEntry[]>([])
  const [memoriesExpanded, setMemoriesExpanded] = useState(false)
  const [loading, setLoading] = useState(true)
  const [showMicro, setShowMicro] = useState(false)
  const [historyExpanded, setHistoryExpanded] = useState(false)

  // Confirmation dialog state
  const [confirmDialog, setConfirmDialog] = useState<{
    mode: 'single' | 'all'
    memory?: PersonaMemoryEntry
  } | null>(null)
  const [confirmLoading, setConfirmLoading] = useState(false)

  // Load sessions + memory count on mount
  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const [sessionList, memData] = await Promise.all([
        listSessions(projectId, 50),
        getMemories(projectId).catch(() => ({ memories: [], count: 0 })),
      ])
      setSessions(sessionList)
      setMemoryCount(memData.count)
      setMemories(memData.memories)

      // Find active session (first non-ended)
      const active = sessionList.find((s) => !s.ended_at) || null
      setActiveSession(active)
    } catch (err) {
      console.warn('[SessionPanel] Failed to load sessions:', err)
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    loadData()
  }, [loadData])

  // ── Handlers ──────────────────────────────────────────────────────────

  /** Continue the current conversation (reuse active session) */
  const handleContinue = useCallback(async () => {
    try {
      const session = await resolveSession(projectId, 'text')
      if (session.mode === 'voice') {
        onOpenVoiceSession(session)
      } else {
        onOpenSession(session)
      }
    } catch (err) {
      console.error('[SessionPanel] Failed to resolve session:', err)
    }
  }, [projectId, onOpenSession, onOpenVoiceSession])

  /** Talk by voice — reuses current conversation, just switches to voice UI */
  const handleTalkVoice = useCallback(async () => {
    try {
      const session = await resolveSession(projectId, 'voice')
      onOpenVoiceSession(session)
    } catch (err) {
      console.error('[SessionPanel] Failed to resolve voice session:', err)
    }
  }, [projectId, onOpenVoiceSession])

  /** Chat by text — reuses current conversation, opens text UI */
  const handleTalkText = useCallback(async () => {
    try {
      const session = await resolveSession(projectId, 'text')
      onOpenSession(session)
    } catch (err) {
      console.error('[SessionPanel] Failed to resolve text session:', err)
    }
  }, [projectId, onOpenSession])

  /** Start a truly fresh conversation (explicit user action) */
  const handleStartFresh = useCallback(
    async (mode: 'voice' | 'text') => {
      try {
        if (activeSession && !activeSession.ended_at) {
          await endSession(activeSession.id)
        }
        const session = await createSession(projectId, mode, undefined, true)
        mode === 'voice' ? onOpenVoiceSession(session) : onOpenSession(session)
      } catch (err) {
        console.error('[SessionPanel] Failed to start fresh conversation:', err)
      }
    },
    [projectId, activeSession, onOpenVoiceSession, onOpenSession]
  )

  // Memory deletion handlers
  const handleForgetSingle = useCallback(async (mem: PersonaMemoryEntry) => {
    setConfirmLoading(true)
    try {
      await forgetMemory(projectId, mem.category, mem.key)
      setMemories((prev) => prev.filter((m) => m.id !== mem.id))
      setMemoryCount((prev) => Math.max(0, prev - 1))
      setConfirmDialog(null)
    } catch (err) {
      console.error('[SessionPanel] Failed to forget memory:', err)
    } finally {
      setConfirmLoading(false)
    }
  }, [projectId])

  const handleForgetAll = useCallback(async () => {
    setConfirmLoading(true)
    try {
      await forgetMemory(projectId)
      setMemories([])
      setMemoryCount(0)
      setConfirmDialog(null)
      setMemoriesExpanded(false)
    } catch (err) {
      console.error('[SessionPanel] Failed to forget all memories:', err)
    } finally {
      setConfirmLoading(false)
    }
  }, [projectId])

  const handleOpenPast = useCallback(
    (session: PersonaSession) => {
      if (session.mode === 'voice') {
        onOpenVoiceSession(session)
      } else {
        onOpenSession(session)
      }
    },
    [onOpenSession, onOpenVoiceSession]
  )

  // ── Derived data ──────────────────────────────────────────────────────

  // Relationship age
  const ageLabel = relationshipAge(projectCreatedAt)

  // Filter real sessions (> 0 messages)
  const realSessions = useMemo(
    () => sessions.filter((s) => s.message_count > 0),
    [sessions]
  )
  const hasRealActiveSession = activeSession && activeSession.message_count > 0
  const isFirstTime = realSessions.length === 0

  // Split into meaningful (>= 3 msgs) and micro (< 3 msgs)
  const meaningfulSessions = useMemo(
    () => realSessions.filter((s) => s.message_count >= 3),
    [realSessions]
  )
  const microSessions = useMemo(
    () => realSessions.filter((s) => s.message_count > 0 && s.message_count < 3),
    [realSessions]
  )

  // ── Render ────────────────────────────────────────────────────────────

  const identity = (
    <HubIdentity
      name={projectName}
      avatarUrl={avatarUrl}
      avatarFallbackUrl={avatarFallbackUrl}
      projectType={projectType}
      description={description}
      ageLabel={ageLabel}
      memoryCount={memoryCount}
      subtitle={isFirstTime && !loading ? 'Ready to meet you' : undefined}
    />
  )

  if (loading) {
    return (
      <div className="flex flex-col gap-4" role="status" aria-label="Loading conversations">
        {identity}
        <span className="hp-skeleton h-[76px] rounded-2xl" />
        <div className="grid gap-3 sm:grid-cols-2">
          <span className="hp-skeleton h-16 rounded-2xl" />
          <span className="hp-skeleton h-16 rounded-2xl" />
        </div>
        <span className="hp-skeleton h-40 rounded-2xl" />
      </div>
    )
  }

  // ----- First-time welcome (brand new persona, no conversations yet) -----
  if (isFirstTime) {
    return (
      <div className="flex flex-col gap-4">
        {identity}
        <p className="text-sm text-white/60">Start your first conversation — pick voice or text.</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <HubAction kind="voice" title="Talk by Voice" subtitle={`Talk to ${projectName} out loud`} onClick={handleTalkVoice} />
          <HubAction kind="text" title="Chat by Text" subtitle={`Chat with ${projectName} via text`} onClick={handleTalkText} />
        </div>
      </div>
    )
  }

  // ----- Returning user (has real conversation history) -----
  const historyRows = showMicro ? realSessions : meaningfulSessions
  const visibleHistory = historyExpanded ? historyRows : historyRows.slice(0, HISTORY_PREVIEW)
  // Continue reopens the latest conversation, never a new one: the active one
  // when it has messages, otherwise the most recent conversation that does
  // (the active one can be empty, e.g. just opened by Voice).
  const latest = hasRealActiveSession ? activeSession! : realSessions[0] ?? null
  const continueLatest = () => (hasRealActiveSession ? handleContinue() : latest && handleOpenPast(latest))

  return (
    <div className="flex flex-col gap-4">
      {identity}

      {/* Continue Conversation — the primary action: reopens the latest conversation. */}
      {latest ? (
        <button
          type="button"
          onClick={continueLatest}
          className="group relative w-full overflow-hidden rounded-2xl border border-indigo-300/30 bg-gradient-to-r from-violet-600/90 via-indigo-600/85 to-blue-600/85 px-4 py-4 sm:px-5 text-left shadow-[0_10px_40px_-12px_rgba(99,102,241,0.6)] hover:brightness-110"
          aria-label={`Continue conversation: ${latest.mode === 'voice' ? 'voice' : 'text'}, ${plural(latest.message_count, 'message')}, ${timeAgo(latest.ended_at || latest.started_at)}`}
        >
          <span className="flex items-center gap-3 sm:gap-4">
            <span className="grid h-11 w-11 sm:h-12 sm:w-12 shrink-0 place-items-center rounded-xl bg-white/90 text-indigo-600 shadow-inner">
              <Play size={22} fill="currentColor" />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block whitespace-nowrap text-base font-semibold text-white sm:text-lg">Continue Conversation</span>
              <span className="block truncate text-sm text-white/80">
                {latest.mode === 'voice' ? 'Voice' : 'Text'} · {plural(latest.message_count, 'message')} · {timeAgo(latest.ended_at || latest.started_at)}
              </span>
            </span>
            <HubWave className="hidden sm:flex" />
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full border border-white/30 text-white group-hover:bg-white/10">
              <ChevronRight size={20} />
            </span>
          </span>
        </button>
      ) : null}

      {/* Resume by voice or by text — equally important. */}
      <div className="grid gap-3 sm:grid-cols-2">
        <HubAction kind="voice" title="Talk by Voice" subtitle="Continue via voice" onClick={handleTalkVoice} />
        <HubAction kind="text" title="Chat by Text" subtitle="Continue via text" onClick={handleTalkText} />
      </div>

      {/* Start fresh — secondary: ends the current conversation and opens a new one. */}
      <div className="grid gap-3 sm:grid-cols-2">
        <HubFresh title="Fresh voice chat" subtitle="Start a new voice conversation" onClick={() => handleStartFresh('voice')} />
        <HubFresh title="Fresh text chat" subtitle="Start a new text conversation" onClick={() => handleStartFresh('text')} />
      </div>

      {/* Memories — the existing manager (view, forget one, forget all) opens in place. */}
      <section className="rounded-2xl border border-white/10 bg-white/[0.03]">
        <div className="flex items-center gap-3 px-4 py-3">
          <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl border border-violet-400/25 bg-violet-500/15 text-violet-200">
            <Brain size={20} />
          </span>
          <div className="min-w-0 flex-1">
            <h3 className="text-base font-semibold text-white">Memories</h3>
            <p className="text-sm text-white/60">
              {memoryCount > 0
                ? <>{plural(memoryCount, 'memory', 'memories')} stored<span className="hidden sm:inline"> about your conversations</span></>
                : 'Nothing remembered yet'}
            </p>
          </div>
          {memoryCount > 0 ? (
            <button
              type="button"
              onClick={() => setMemoriesExpanded(!memoriesExpanded)}
              aria-expanded={memoriesExpanded}
              aria-controls="hp-hub-memories"
              className="inline-flex min-h-[44px] items-center gap-1.5 rounded-xl border border-white/15 bg-white/[0.04] px-3.5 text-sm font-medium text-white/90 hover:bg-white/10"
            >
              {memoriesExpanded ? 'Hide' : 'View All'}
              <ChevronRight size={16} className={`transition-transform ${memoriesExpanded ? 'rotate-90' : ''}`} />
            </button>
          ) : null}
        </div>
        {memoryCount > 0 ? (
          <Collapsible open={memoriesExpanded} id="hp-hub-memories">
            <div className="border-t border-white/10">
              <ul className="divide-y divide-white/5">
                {memories.map((mem) => (
                  <li key={mem.id} className="group/item flex items-start justify-between gap-3 px-4 py-2.5 hover:bg-white/[0.03]">
                    <div className="min-w-0 flex-1">
                      <div className="text-[13px] leading-relaxed text-white/85">{mem.value}</div>
                      <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-white/45">
                        <span>{mem.category}</span>
                        {mem.source_type === 'user_statement' ? (
                          <>
                            <span aria-hidden>·</span>
                            <Pin size={10} aria-label="You told me this" />
                          </>
                        ) : null}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => setConfirmDialog({ mode: 'single', memory: mem })}
                      className="hp-icon-btn mt-0.5 shrink-0 rounded-lg p-1.5 text-white/45 opacity-100 hover:bg-red-500/10 hover:text-red-400 sm:opacity-0 sm:group-hover/item:opacity-100 sm:focus-visible:opacity-100"
                      title="Forget this memory"
                      aria-label={`Forget: ${mem.value}`}
                    >
                      <Trash2 size={14} />
                    </button>
                  </li>
                ))}
              </ul>
              <div className="flex justify-end px-4 py-2">
                <button
                  type="button"
                  onClick={() => setConfirmDialog({ mode: 'all' })}
                  className="min-h-[36px] rounded-lg px-2 text-xs text-red-300/80 hover:text-red-300"
                >
                  Forget all
                </button>
              </div>
            </div>
          </Collapsible>
        ) : null}
      </section>

      {/* Conversation history — newest first: type, messages, last activity. */}
      {realSessions.length > 0 ? (
        <section className="rounded-2xl border border-white/10 bg-white/[0.03]">
          <div className="flex items-center gap-2 px-4 pt-3 pb-2">
            <Clock size={18} className="text-white/60" aria-hidden />
            <h3 className="flex-1 text-base font-semibold text-white">Conversation History</h3>
            {historyRows.length > HISTORY_PREVIEW ? (
              <button
                type="button"
                onClick={() => setHistoryExpanded((v) => !v)}
                aria-expanded={historyExpanded}
                className="inline-flex min-h-[44px] items-center gap-1 rounded-lg px-2 text-sm text-white/75 hover:text-white"
              >
                {historyExpanded ? 'Show less' : 'View All'}
                <ChevronRight size={16} className={`transition-transform ${historyExpanded ? 'rotate-90' : ''}`} />
              </button>
            ) : null}
          </div>
          <ul className="px-2 pb-2">
            {visibleHistory.map((session) => {
              const voice = session.mode === 'voice'
              const isActive = !session.ended_at
              return (
                <li key={session.id}>
                  <button
                    type="button"
                    onClick={() => handleOpenPast(session)}
                    className={`group flex w-full min-h-[48px] items-center gap-3 rounded-xl px-2 py-2 text-left hover:bg-white/[0.05] ${isActive ? 'bg-white/[0.04]' : ''}`}
                  >
                    <span className={`grid h-7 w-7 shrink-0 place-items-center rounded-md ${voice ? 'bg-blue-500/80 text-white' : 'bg-white/10 text-white/80'}`} aria-hidden>
                      {voice ? <Play size={13} fill="currentColor" /> : <MessageCircle size={14} />}
                    </span>
                    <span className="w-16 shrink-0 text-sm font-semibold text-white">{shortDate(session.started_at)}</span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm text-white/70 sm:truncate">
                        {voice ? 'Voice' : 'Text'} · {plural(session.message_count, 'message')} · {timeAgo(session.ended_at || session.started_at)}
                        {isActive ? ' · active' : ''}
                      </span>
                      {session.summary ? (
                        <span className="block truncate text-xs text-white/50">{session.summary}</span>
                      ) : null}
                    </span>
                    <ChevronRight size={16} className="shrink-0 text-white/40 group-hover:text-white/80" aria-hidden />
                  </button>
                </li>
              )
            })}
          </ul>
          {microSessions.length > 0 ? (
            <div className="border-t border-white/5 px-4 py-1.5 text-center">
              <button
                type="button"
                onClick={() => setShowMicro((v) => !v)}
                className="min-h-[36px] text-xs text-white/55 hover:text-white/80"
              >
                {showMicro ? 'Hide short conversations' : `Show short conversations (${microSessions.length})`}
              </button>
            </div>
          ) : null}
        </section>
      ) : null}

      {/* Confirmation Dialog */}
      {confirmDialog && (
        <ConfirmForgetDialog
          mode={confirmDialog.mode}
          personaName={projectName}
          memoryCount={memoryCount}
          memoryLabel={confirmDialog.memory?.value}
          memoryCategory={confirmDialog.memory?.category}
          loading={confirmLoading}
          onConfirm={() => {
            if (confirmDialog.mode === 'all') {
              handleForgetAll()
            } else if (confirmDialog.memory) {
              handleForgetSingle(confirmDialog.memory)
            }
          }}
          onCancel={() => { setConfirmDialog(null); setConfirmLoading(false) }}
        />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Pieces
// ---------------------------------------------------------------------------

const HISTORY_PREVIEW = 5

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`
}

/** Picture, name, type, age and memories — the project's identity at the top of the hub. */
function HubIdentity({
  name,
  avatarUrl,
  avatarFallbackUrl,
  projectType,
  description,
  ageLabel,
  memoryCount,
  subtitle,
}: {
  name: string
  avatarUrl?: string | null
  avatarFallbackUrl?: string | null
  projectType?: string
  description?: string
  ageLabel: string
  memoryCount: number
  subtitle?: string
}) {
  return (
    <header className="flex flex-col items-center gap-4 pt-2 text-center sm:flex-row sm:items-center sm:gap-6 sm:pr-10 sm:text-left">
      <ProjectAvatar url={avatarUrl} fallbackUrl={avatarFallbackUrl} name={name} projectType={projectType || 'persona'} size={112} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 sm:justify-start">
          <h2 className="min-w-0 break-words text-2xl font-semibold text-white sm:text-3xl">{name}</h2>
          <span className="rounded-full border border-pink-400/30 bg-pink-500/15 px-2.5 py-0.5 text-xs font-medium text-pink-200">
            {projectTypeLabel(projectType || 'persona')}
          </span>
        </div>
        {subtitle ? <p className="mt-1 text-sm text-violet-200/90">{subtitle}</p> : null}
        <p className="mt-2 flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-sm text-white/65 sm:justify-start">
          <span className="inline-flex items-center gap-1.5"><CalendarDays size={15} aria-hidden />{ageLabel}</span>
          {memoryCount > 0 ? (
            <>
              <span className="hidden h-4 w-px bg-white/15 sm:inline-block" aria-hidden />
              <span className="inline-flex items-center gap-1.5"><Database size={15} aria-hidden />{memoryCount === 1 ? '1 memory stored' : `${memoryCount} memories stored`}</span>
            </>
          ) : null}
        </p>
        {description ? <p className="mt-2 line-clamp-2 text-sm leading-relaxed text-white/60">{description}</p> : null}
      </div>
    </header>
  )
}

/** "Talk by Voice" / "Chat by Text" — resume the current conversation in that mode. */
function HubAction({ kind, title, subtitle, onClick }: { kind: 'voice' | 'text'; title: string; subtitle: string; onClick: () => void }) {
  const voice = kind === 'voice'
  return (
    <button
      type="button"
      onClick={onClick}
      className={`group flex w-full min-h-[64px] items-center gap-3 rounded-2xl border border-white/10 bg-white/[0.04] px-4 py-3 text-left hover:bg-white/[0.07] ${voice ? 'hover:border-violet-400/40' : 'hover:border-blue-400/40'}`}
    >
      <span className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl border ${voice ? 'border-violet-400/25 bg-violet-500/15 text-violet-200' : 'border-blue-400/25 bg-blue-500/15 text-blue-200'}`}>
        {voice ? <Mic size={20} /> : <MessageCircle size={20} />}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-base font-semibold text-white">{title}</span>
        <span className="block truncate text-sm text-white/60">{subtitle}</span>
      </span>
      <ChevronRight size={18} className="shrink-0 text-white/45 group-hover:text-white/80" aria-hidden />
    </button>
  )
}

/** "Fresh voice chat" / "Fresh text chat" — the secondary, start-over actions. */
function HubFresh({ title, subtitle, onClick }: { title: string; subtitle: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full min-h-[56px] items-center gap-3 rounded-2xl border border-white/[0.08] bg-transparent px-4 py-2.5 text-left hover:bg-white/[0.04]"
    >
      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full border border-white/10 bg-white/[0.04] text-violet-200">
        <RotateCcw size={16} />
      </span>
      <span className="min-w-0">
        <span className="block text-sm font-medium text-white/90">{title}</span>
        <span className="block truncate text-xs text-white/55">{subtitle}</span>
      </span>
    </button>
  )
}

/** Decorative bars inside the Continue button. */
function HubWave({ className = '' }: { className?: string }) {
  const bars = [6, 10, 16, 22, 14, 26, 18, 12, 20, 9, 14, 7, 5, 4]
  return (
    <span className={`items-center gap-[3px] pr-1 ${className}`} aria-hidden>
      {bars.map((h, i) => (
        <span key={i} className="w-[3px] rounded-full bg-white/50" style={{ height: h }} />
      ))}
    </span>
  )
}
