/**
 * SessionPanel — Companion-Grade Conversation Management
 *
 * Relationship-first UX: sessions are internal transport, users see
 * "Conversations" grouped by day with micro-session hiding.
 *
 * Key UX principles:
 *  - "Talk by Voice" / "Chat by Text" reuse the active conversation
 *  - "Start Fresh" explicitly creates a new conversation (secondary action)
 *  - Past conversations grouped by day, collapsed beyond yesterday
 *  - Micro-sessions (< 3 messages) hidden by default
 *  - No "session" language in user-facing copy
 */
import React, { useEffect, useState, useCallback, useMemo } from 'react';
import { Trash2, ChevronDown, ChevronUp, Pin, RotateCcw } from 'lucide-react';
import { resolveSession, createSession, listSessions, endSession, getMemories, forgetMemory, } from './sessionsApi';
import ConfirmForgetDialog from '../components/ConfirmForgetDialog';
// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export default function SessionPanel({ projectId, projectName, projectCreatedAt, onOpenSession, onOpenVoiceSession, }) {
    const [sessions, setSessions] = useState([]);
    const [activeSession, setActiveSession] = useState(null);
    const [memoryCount, setMemoryCount] = useState(0);
    const [memories, setMemories] = useState([]);
    const [memoriesExpanded, setMemoriesExpanded] = useState(false);
    const [loading, setLoading] = useState(true);
    const [showMicro, setShowMicro] = useState(false);
    const [expandedDays, setExpandedDays] = useState(new Set());
    // Confirmation dialog state
    const [confirmDialog, setConfirmDialog] = useState(null);
    const [confirmLoading, setConfirmLoading] = useState(false);
    // Load sessions + memory count on mount
    const loadData = useCallback(async () => {
        setLoading(true);
        try {
            const [sessionList, memData] = await Promise.all([
                listSessions(projectId, 50),
                getMemories(projectId).catch(() => ({ memories: [], count: 0 })),
            ]);
            setSessions(sessionList);
            setMemoryCount(memData.count);
            setMemories(memData.memories);
            // Find active session (first non-ended)
            const active = sessionList.find((s) => !s.ended_at) || null;
            setActiveSession(active);
        }
        catch (err) {
            console.warn('[SessionPanel] Failed to load sessions:', err);
        }
        finally {
            setLoading(false);
        }
    }, [projectId]);
    useEffect(() => {
        loadData();
    }, [loadData]);
    // ── Handlers ──────────────────────────────────────────────────────────
    /** Continue the current conversation (reuse active session) */
    const handleContinue = useCallback(async () => {
        try {
            const session = await resolveSession(projectId, 'text');
            if (session.mode === 'voice') {
                onOpenVoiceSession(session);
            }
            else {
                onOpenSession(session);
            }
        }
        catch (err) {
            console.error('[SessionPanel] Failed to resolve session:', err);
        }
    }, [projectId, onOpenSession, onOpenVoiceSession]);
    /** Talk by voice — reuses current conversation, just switches to voice UI */
    const handleTalkVoice = useCallback(async () => {
        try {
            const session = await resolveSession(projectId, 'voice');
            onOpenVoiceSession(session);
        }
        catch (err) {
            console.error('[SessionPanel] Failed to resolve voice session:', err);
        }
    }, [projectId, onOpenVoiceSession]);
    /** Chat by text — reuses current conversation, opens text UI */
    const handleTalkText = useCallback(async () => {
        try {
            const session = await resolveSession(projectId, 'text');
            onOpenSession(session);
        }
        catch (err) {
            console.error('[SessionPanel] Failed to resolve text session:', err);
        }
    }, [projectId, onOpenSession]);
    /** Start a truly fresh conversation (explicit user action) */
    const handleStartFresh = useCallback(async (mode) => {
        try {
            if (activeSession && !activeSession.ended_at) {
                await endSession(activeSession.id);
            }
            const session = await createSession(projectId, mode, undefined, true);
            mode === 'voice' ? onOpenVoiceSession(session) : onOpenSession(session);
        }
        catch (err) {
            console.error('[SessionPanel] Failed to start fresh conversation:', err);
        }
    }, [projectId, activeSession, onOpenVoiceSession, onOpenSession]);
    // Memory deletion handlers
    const handleForgetSingle = useCallback(async (mem) => {
        setConfirmLoading(true);
        try {
            await forgetMemory(projectId, mem.category, mem.key);
            setMemories((prev) => prev.filter((m) => m.id !== mem.id));
            setMemoryCount((prev) => Math.max(0, prev - 1));
            setConfirmDialog(null);
        }
        catch (err) {
            console.error('[SessionPanel] Failed to forget memory:', err);
        }
        finally {
            setConfirmLoading(false);
        }
    }, [projectId]);
    const handleForgetAll = useCallback(async () => {
        setConfirmLoading(true);
        try {
            await forgetMemory(projectId);
            setMemories([]);
            setMemoryCount(0);
            setConfirmDialog(null);
            setMemoriesExpanded(false);
        }
        catch (err) {
            console.error('[SessionPanel] Failed to forget all memories:', err);
        }
        finally {
            setConfirmLoading(false);
        }
    }, [projectId]);
    const handleOpenPast = useCallback((session) => {
        if (session.mode === 'voice') {
            onOpenVoiceSession(session);
        }
        else {
            onOpenSession(session);
        }
    }, [onOpenSession, onOpenVoiceSession]);
    const toggleDay = useCallback((sortKey) => {
        setExpandedDays((prev) => {
            const next = new Set(prev);
            if (next.has(sortKey))
                next.delete(sortKey);
            else
                next.add(sortKey);
            return next;
        });
    }, []);
    // ── Derived data ──────────────────────────────────────────────────────
    // Relationship age
    const ageDays = projectCreatedAt
        ? Math.max(0, Math.floor((Date.now() / 1000 - projectCreatedAt) / 86400))
        : 0;
    const ageLabel = ageDays === 0
        ? 'Just created today'
        : ageDays === 1
            ? '1 day together'
            : `${ageDays} days together`;
    // Filter real sessions (> 0 messages)
    const realSessions = useMemo(() => sessions.filter((s) => s.message_count > 0), [sessions]);
    const hasRealActiveSession = activeSession && activeSession.message_count > 0;
    const isFirstTime = realSessions.length === 0;
    // Split into meaningful (>= 3 msgs) and micro (< 3 msgs)
    const meaningfulSessions = useMemo(() => realSessions.filter((s) => s.message_count >= 3), [realSessions]);
    const microSessions = useMemo(() => realSessions.filter((s) => s.message_count > 0 && s.message_count < 3), [realSessions]);
    // Group by day
    const dayGroups = useMemo(() => {
        const visible = showMicro ? realSessions : meaningfulSessions;
        const grouped = {};
        for (const s of visible) {
            const key = getDaySortKey(s.started_at);
            if (!grouped[key])
                grouped[key] = [];
            grouped[key].push(s);
        }
        const now = new Date();
        const todayKey = formatSortKey(now);
        const yesterday = new Date(now);
        yesterday.setDate(yesterday.getDate() - 1);
        const yesterdayKey = formatSortKey(yesterday);
        return Object.entries(grouped)
            .sort(([a], [b]) => b.localeCompare(a)) // newest first
            .map(([sortKey, sess]) => ({
            label: getDayLabel(sortKey, todayKey, yesterdayKey),
            sortKey,
            sessions: sess,
        }));
    }, [realSessions, meaningfulSessions, showMicro]);
    // Conversation history always starts collapsed — user toggles manually
    // (no auto-expand)
    // ── Render ────────────────────────────────────────────────────────────
    if (loading) {
        return (<div className="flex items-center justify-center p-8 text-gray-400">
        <div className="animate-pulse">Loading...</div>
      </div>);
    }
    // ----- First-time welcome (brand new persona, no conversations yet) -----
    if (isFirstTime) {
        return (<div className="flex flex-col gap-5 p-4 max-w-lg mx-auto">
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
          <button onClick={handleTalkVoice} className="w-full flex items-center gap-3 px-4 py-4 rounded-xl bg-gradient-to-r from-purple-600/30 to-pink-600/30 border border-purple-500/40 hover:border-purple-400/60 transition-all text-left">
            <span className="text-2xl">{'\uD83C\uDFA4'}</span>
            <div className="flex-1 min-w-0">
              <div className="text-white font-medium text-sm">Talk by Voice</div>
              <div className="text-gray-400 text-xs">Talk to {projectName} out loud</div>
            </div>
          </button>

          <button onClick={handleTalkText} className="w-full flex items-center gap-3 px-4 py-4 rounded-xl bg-gradient-to-r from-blue-600/30 to-purple-600/30 border border-blue-500/40 hover:border-blue-400/60 transition-all text-left">
            <span className="text-2xl">{'\uD83D\uDCAC'}</span>
            <div className="flex-1 min-w-0">
              <div className="text-white font-medium text-sm">Chat by Text</div>
              <div className="text-gray-400 text-xs">Chat with {projectName} via text</div>
            </div>
          </button>
        </div>
      </div>);
    }
    // ----- Returning user (has real conversation history) -----
    return (<div className="flex flex-col gap-4 p-4 max-w-lg mx-auto">
      {/* Header */}
      <div className="text-center mb-2">
        <h2 className="text-xl font-semibold text-white">{projectName}</h2>
        <p className="text-sm text-gray-400">{ageLabel}</p>
        {memoryCount > 0 && (<p className="text-xs text-gray-500 mt-1">
            {memoryCount} {memoryCount === 1 ? 'memory' : 'memories'} stored
          </p>)}
      </div>

      {/* Primary Actions */}
      <div className="flex flex-col gap-2">
        {/* Continue Conversation — glowing primary action */}
        {hasRealActiveSession && (<button onClick={handleContinue} className="w-full flex items-center gap-3 px-4 py-3 rounded-xl bg-gradient-to-r from-purple-600/30 to-blue-600/30 border border-purple-500/40 hover:border-purple-400/60 shadow-[0_0_15px_rgba(168,85,247,0.15)] hover:shadow-[0_0_20px_rgba(168,85,247,0.25)] transition-all text-left">
            <span className="text-2xl">
              {activeSession.mode === 'voice' ? '\u25B6\uFE0F' : '\u25B6\uFE0F'}
            </span>
            <div className="flex-1 min-w-0">
              <div className="text-white font-medium text-sm">Continue Conversation</div>
              <div className="text-gray-400 text-xs truncate">
                {activeSession.mode === 'voice' ? 'Voice' : 'Text'} &middot;{' '}
                {activeSession.message_count} msgs &middot;{' '}
                {formatTimeAgo(activeSession.started_at)}
              </div>
            </div>
          </button>)}

        {/* Talk by Voice */}
        <button onClick={handleTalkVoice} className="w-full flex items-center gap-3 px-4 py-3 rounded-xl bg-gray-800/60 border border-gray-700/50 hover:border-purple-500/40 transition-all text-left">
          <span className="text-2xl">{'\uD83C\uDFA4'}</span>
          <div className="flex-1 min-w-0">
            <div className="text-white font-medium text-sm">Talk by Voice</div>
            <div className="text-gray-400 text-xs">Continue via voice</div>
          </div>
        </button>

        {/* Chat by Text */}
        <button onClick={handleTalkText} className="w-full flex items-center gap-3 px-4 py-3 rounded-xl bg-gray-800/60 border border-gray-700/50 hover:border-blue-500/40 transition-all text-left">
          <span className="text-2xl">{'\uD83D\uDCAC'}</span>
          <div className="flex-1 min-w-0">
            <div className="text-white font-medium text-sm">Chat by Text</div>
            <div className="text-gray-400 text-xs">Continue via text</div>
          </div>
        </button>

        {/* Start Fresh — secondary action, subdued */}
        <div className="flex gap-2 mt-1">
          <button onClick={() => handleStartFresh('voice')} className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-gray-800/30 border border-gray-700/30 hover:border-gray-600/50 text-gray-500 hover:text-gray-300 transition-all text-xs">
            <RotateCcw size={12}/>
            Fresh voice chat
          </button>
          <button onClick={() => handleStartFresh('text')} className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-gray-800/30 border border-gray-700/30 hover:border-gray-600/50 text-gray-500 hover:text-gray-300 transition-all text-xs">
            <RotateCcw size={12}/>
            Fresh text chat
          </button>
        </div>
      </div>

      {/* Memories Section — expandable list with per-item delete + Forget All */}
      {memoryCount > 0 && (<div className="mt-2">
          <button type="button" onClick={() => setMemoriesExpanded(!memoriesExpanded)} className="w-full flex items-center justify-between px-1 mb-2 group">
            <h3 className="text-xs uppercase tracking-wider text-gray-500">
              Memories ({memoryCount})
            </h3>
            <div className="flex items-center gap-2">
              {memoriesExpanded && memoryCount > 0 && (<span role="button" onClick={(e) => {
                    e.stopPropagation();
                    setConfirmDialog({ mode: 'all' });
                }} className="text-[11px] text-red-400/60 hover:text-red-400 transition-colors cursor-pointer">
                  Forget All
                </span>)}
              {memoriesExpanded ? (<ChevronUp size={14} className="text-gray-500"/>) : (<ChevronDown size={14} className="text-gray-500"/>)}
            </div>
          </button>

          {memoriesExpanded && (<div className="rounded-xl border border-white/10 bg-white/[0.02] overflow-hidden divide-y divide-white/5">
              {memories.map((mem) => (<div key={mem.id} className="flex items-start justify-between gap-3 px-3 py-2.5 group/item hover:bg-white/[0.03] transition-colors">
                  <div className="min-w-0 flex-1">
                    <div className="text-[13px] text-white/80 leading-relaxed">
                      {mem.value}
                    </div>
                    <div className="flex items-center gap-1.5 mt-0.5">
                      <span className="text-[10px] text-white/30">{mem.category}</span>
                      {mem.source_type === 'user_statement' && (<>
                          <span className="text-[10px] text-white/15">&middot;</span>
                          <Pin size={9} className="text-white/25"/>
                        </>)}
                    </div>
                  </div>
                  <button type="button" onClick={() => setConfirmDialog({ mode: 'single', memory: mem })} className="p-1.5 rounded-lg opacity-0 group-hover/item:opacity-100 hover:bg-red-500/10 text-white/30 hover:text-red-400 transition-all shrink-0 mt-0.5" title="Forget this memory">
                    <Trash2 size={13}/>
                  </button>
                </div>))}
            </div>)}
        </div>)}

      {/* Conversation History — grouped by day */}
      {dayGroups.length > 0 && (<div className="mt-2">
          <h3 className="text-xs uppercase tracking-wider text-gray-500 mb-2 px-1">
            Conversation History
          </h3>
          <div className="flex flex-col gap-1">
            {dayGroups.map((group) => {
                const isExpanded = expandedDays.has(group.sortKey);
                return (<div key={group.sortKey}>
                  {/* Day header — clickable to toggle */}
                  <button onClick={() => toggleDay(group.sortKey)} className="w-full flex items-center justify-between px-3 py-1.5 rounded-lg hover:bg-gray-800/30 transition-colors">
                    <span className="text-xs font-medium text-gray-400">
                      {group.label}
                    </span>
                    <div className="flex items-center gap-2">
                      <span className="text-[11px] text-gray-600">
                        {group.sessions.length} {group.sessions.length === 1 ? 'chat' : 'chats'}
                      </span>
                      {isExpanded ? (<ChevronUp size={12} className="text-gray-600"/>) : (<ChevronDown size={12} className="text-gray-600"/>)}
                    </div>
                  </button>

                  {/* Expanded sessions */}
                  {isExpanded && (<div className="flex flex-col gap-0.5 ml-2 mt-0.5 mb-1">
                      {group.sessions.map((session) => (<button key={session.id} onClick={() => handleOpenPast(session)} className="w-full flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-gray-800/40 transition-all text-left group">
                          <span className="text-sm text-gray-500 group-hover:text-gray-300">
                            {session.mode === 'voice' ? '\uD83C\uDFA4' : '\uD83D\uDCAC'}
                          </span>
                          <div className="flex-1 min-w-0">
                            <div className="text-gray-300 text-sm truncate">
                              {session.summary ||
                                `${session.mode === 'voice' ? 'Voice' : 'Text'} chat`}
                            </div>
                            <div className="text-gray-500 text-xs">
                              {formatTime(session.started_at)} &middot;{' '}
                              {session.message_count} msgs
                              {session.ended_at ? '' : ' \u00B7 active'}
                            </div>
                          </div>
                        </button>))}
                    </div>)}
                </div>);
            })}
          </div>

          {/* Micro-session toggle */}
          {!showMicro && microSessions.length > 0 && (<button onClick={() => setShowMicro(true)} className="w-full mt-2 px-3 py-1.5 text-[11px] text-gray-600 hover:text-gray-400 transition-colors text-center">
              Show short conversations ({microSessions.length})
            </button>)}
          {showMicro && microSessions.length > 0 && (<button onClick={() => setShowMicro(false)} className="w-full mt-2 px-3 py-1.5 text-[11px] text-gray-600 hover:text-gray-400 transition-colors text-center">
              Hide short conversations
            </button>)}
        </div>)}

      {/* Confirmation Dialog */}
      {confirmDialog && (<ConfirmForgetDialog mode={confirmDialog.mode} personaName={projectName} memoryCount={memoryCount} memoryLabel={confirmDialog.memory?.value} memoryCategory={confirmDialog.memory?.category} loading={confirmLoading} onConfirm={() => {
                if (confirmDialog.mode === 'all') {
                    handleForgetAll();
                }
                else if (confirmDialog.memory) {
                    handleForgetSingle(confirmDialog.memory);
                }
            }} onCancel={() => { setConfirmDialog(null); setConfirmLoading(false); }}/>)}
    </div>);
}
// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function formatTimeAgo(dateStr) {
    try {
        const date = new Date(dateStr);
        const now = new Date();
        const diffMs = now.getTime() - date.getTime();
        const diffMin = Math.floor(diffMs / 60000);
        if (diffMin < 1)
            return 'just now';
        if (diffMin < 60)
            return `${diffMin}m ago`;
        const diffHr = Math.floor(diffMin / 60);
        if (diffHr < 24)
            return `${diffHr}h ago`;
        const diffDay = Math.floor(diffHr / 24);
        return `${diffDay}d ago`;
    }
    catch {
        return dateStr;
    }
}
function formatTime(dateStr) {
    try {
        const date = new Date(dateStr);
        return date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
    }
    catch {
        return dateStr;
    }
}
function formatSortKey(date) {
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, '0');
    const d = String(date.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
}
function getDaySortKey(dateStr) {
    try {
        return formatSortKey(new Date(dateStr));
    }
    catch {
        return '0000-00-00';
    }
}
function getDayLabel(sortKey, todayKey, yesterdayKey) {
    if (sortKey === todayKey)
        return 'Today';
    if (sortKey === yesterdayKey)
        return 'Yesterday';
    try {
        const [y, m, d] = sortKey.split('-').map(Number);
        const date = new Date(y, m - 1, d);
        const now = new Date();
        const diffDays = Math.floor((now.getTime() - date.getTime()) / 86400000);
        if (diffDays < 7) {
            return date.toLocaleDateString(undefined, { weekday: 'long' });
        }
        return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    }
    catch {
        return sortKey;
    }
}
