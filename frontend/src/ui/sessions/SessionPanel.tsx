/**
 * SessionPanel — Companion-Grade Session Management for Persona Projects
 *
 * Displays session history and provides controls to:
 *  - Continue the last session (in its original mode: voice or text)
 *  - Start a new voice session
 *  - Start a new text session
 *  - Browse past sessions
 *
 * This is the "home" view for a persona project — the entry point
 * for long-term companion interaction.
 *
 * Additive: this is a new component, does not modify any existing UI.
 */

import React, { useEffect, useState, useCallback } from 'react'
import {
  PersonaSession,
  resolveSession,
  createSession,
  listSessions,
  endSession,
  getMemories,
} from './sessionsApi'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SessionPanelProps {
  projectId: string
  projectName: string
  projectCreatedAt?: number
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
  onOpenSession,
  onOpenVoiceSession,
}: SessionPanelProps) {
  const [sessions, setSessions] = useState<PersonaSession[]>([])
  const [activeSession, setActiveSession] = useState<PersonaSession | null>(null)
  const [memoryCount, setMemoryCount] = useState(0)
  const [loading, setLoading] = useState(true)

  // Load sessions + memory count on mount
  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const [sessionList, memData] = await Promise.all([
        listSessions(projectId, 20),
        getMemories(projectId).catch(() => ({ memories: [], count: 0 })),
      ])
      setSessions(sessionList)
      setMemoryCount(memData.count)

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

  // Handlers
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

  const handleNewVoice = useCallback(async () => {
    try {
      // End current active session if any
      if (activeSession && !activeSession.ended_at) {
        await endSession(activeSession.id)
      }
      const session = await createSession(projectId, 'voice')
      onOpenVoiceSession(session)
    } catch (err) {
      console.error('[SessionPanel] Failed to create voice session:', err)
    }
  }, [projectId, activeSession, onOpenVoiceSession])

  const handleNewText = useCallback(async () => {
    try {
      // End current active session if any
      if (activeSession && !activeSession.ended_at) {
        await endSession(activeSession.id)
      }
      const session = await createSession(projectId, 'text')
      onOpenSession(session)
    } catch (err) {
      console.error('[SessionPanel] Failed to create text session:', err)
    }
  }, [projectId, activeSession, onOpenSession])

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

  // Compute relationship age
  const ageDays = projectCreatedAt
    ? Math.max(0, Math.floor((Date.now() / 1000 - projectCreatedAt) / 86400))
    : 0
  const ageLabel =
    ageDays === 0
      ? 'Just created today'
      : ageDays === 1
      ? '1 day together'
      : `${ageDays} days together`

  // Determine first-time state: no real conversations have happened yet.
  // A session with 0 messages is just a system placeholder, not a real session.
  const realSessions = sessions.filter((s) => s.message_count > 0)
  const hasRealActiveSession = activeSession && activeSession.message_count > 0
  const isFirstTime = realSessions.length === 0

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8 text-gray-400">
        <div className="animate-pulse">Loading sessions...</div>
      </div>
    )
  }

  // ----- First-time welcome (brand new persona, no conversations yet) -----
  if (isFirstTime) {
    return (
      <div className="flex flex-col gap-5 p-4 max-w-lg mx-auto">
        {/* Welcome header */}
        <div className="text-center mb-1">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-gradient-to-br from-purple-500/20 to-pink-500/20 border border-purple-500/30 mb-3">
            <span className="text-3xl">{'\u2728'}</span>
          </div>
          <h2 className="text-xl font-semibold text-white">{projectName}</h2>
          <p className="text-sm text-purple-300/80 mt-1">Ready to meet you</p>
        </div>

        {/* First-time prompt */}
        <p className="text-center text-gray-400 text-sm leading-relaxed px-4">
          Start your first conversation — pick voice or text below.
        </p>

        {/* Primary action buttons */}
        <div className="flex flex-col gap-2">
          <button
            onClick={handleNewVoice}
            className="w-full flex items-center gap-3 px-4 py-4 rounded-xl bg-gradient-to-r from-purple-600/30 to-pink-600/30 border border-purple-500/40 hover:border-purple-400/60 transition-all text-left"
          >
            <span className="text-2xl">{'\uD83C\uDFA4'}</span>
            <div className="flex-1 min-w-0">
              <div className="text-white font-medium text-sm">Start Voice Session</div>
              <div className="text-gray-400 text-xs">Talk to {projectName} out loud</div>
            </div>
          </button>

          <button
            onClick={handleNewText}
            className="w-full flex items-center gap-3 px-4 py-4 rounded-xl bg-gradient-to-r from-blue-600/30 to-purple-600/30 border border-blue-500/40 hover:border-blue-400/60 transition-all text-left"
          >
            <span className="text-2xl">{'\uD83D\uDCAC'}</span>
            <div className="flex-1 min-w-0">
              <div className="text-white font-medium text-sm">Start Text Session</div>
              <div className="text-gray-400 text-xs">Chat with {projectName} via text</div>
            </div>
          </button>
        </div>
      </div>
    )
  }

  // ----- Returning user (has real conversation history) -----
  return (
    <div className="flex flex-col gap-4 p-4 max-w-lg mx-auto">
      {/* Header */}
      <div className="text-center mb-2">
        <h2 className="text-xl font-semibold text-white">{projectName}</h2>
        <p className="text-sm text-gray-400">{ageLabel}</p>
        {memoryCount > 0 && (
          <p className="text-xs text-gray-500 mt-1">
            {memoryCount} {memoryCount === 1 ? 'memory' : 'memories'} stored
          </p>
        )}
      </div>

      {/* Action Buttons */}
      <div className="flex flex-col gap-2">
        {/* Continue Last Session — only when there are real messages to continue */}
        {hasRealActiveSession && (
          <button
            onClick={handleContinue}
            className="w-full flex items-center gap-3 px-4 py-3 rounded-xl bg-gradient-to-r from-purple-600/30 to-blue-600/30 border border-purple-500/40 hover:border-purple-400/60 transition-all text-left"
          >
            <span className="text-2xl">
              {activeSession.mode === 'voice' ? '\u25B6\uFE0F' : '\u25B6\uFE0F'}
            </span>
            <div className="flex-1 min-w-0">
              <div className="text-white font-medium text-sm">Continue Last Session</div>
              <div className="text-gray-400 text-xs truncate">
                {activeSession.mode === 'voice' ? 'Voice' : 'Text'} ·{' '}
                {activeSession.message_count} msgs ·{' '}
                {formatTimeAgo(activeSession.started_at)}
              </div>
            </div>
          </button>
        )}

        {/* New Voice Session */}
        <button
          onClick={handleNewVoice}
          className="w-full flex items-center gap-3 px-4 py-3 rounded-xl bg-gray-800/60 border border-gray-700/50 hover:border-purple-500/40 transition-all text-left"
        >
          <span className="text-2xl">{'\uD83C\uDFA4'}</span>
          <div className="flex-1 min-w-0">
            <div className="text-white font-medium text-sm">New Voice Session</div>
            <div className="text-gray-400 text-xs">Start a fresh voice conversation</div>
          </div>
        </button>

        {/* New Text Session */}
        <button
          onClick={handleNewText}
          className="w-full flex items-center gap-3 px-4 py-3 rounded-xl bg-gray-800/60 border border-gray-700/50 hover:border-blue-500/40 transition-all text-left"
        >
          <span className="text-2xl">{'\uD83D\uDCAC'}</span>
          <div className="flex-1 min-w-0">
            <div className="text-white font-medium text-sm">New Text Session</div>
            <div className="text-gray-400 text-xs">Start a fresh text conversation</div>
          </div>
        </button>
      </div>

      {/* Past Sessions — only show sessions that have actual messages */}
      {realSessions.length > 0 && (
        <div className="mt-2">
          <h3 className="text-xs uppercase tracking-wider text-gray-500 mb-2 px-1">
            Past Sessions
          </h3>
          <div className="flex flex-col gap-1">
            {realSessions.map((session) => (
              <button
                key={session.id}
                onClick={() => handleOpenPast(session)}
                className="w-full flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-gray-800/40 transition-all text-left group"
              >
                <span className="text-sm text-gray-500 group-hover:text-gray-300">
                  {session.mode === 'voice' ? '\uD83C\uDFA4' : '\uD83D\uDCAC'}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-gray-300 text-sm truncate">
                    {session.summary || `${session.mode} session`}
                  </div>
                  <div className="text-gray-500 text-xs">
                    {formatDate(session.started_at)} · {session.message_count} msgs
                    {session.ended_at ? '' : ' · active'}
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatTimeAgo(dateStr: string): string {
  try {
    const date = new Date(dateStr)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMin = Math.floor(diffMs / 60000)

    if (diffMin < 1) return 'just now'
    if (diffMin < 60) return `${diffMin}m ago`
    const diffHr = Math.floor(diffMin / 60)
    if (diffHr < 24) return `${diffHr}h ago`
    const diffDay = Math.floor(diffHr / 24)
    return `${diffDay}d ago`
  } catch {
    return dateStr
  }
}

function formatDate(dateStr: string): string {
  try {
    const date = new Date(dateStr)
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  } catch {
    return dateStr
  }
}
