/**
 * MeetingRoom V2 — Enterprise-grade 3-column meeting layout.
 *
 * Architecture:
 *   ┌─────────────────────────────────────────────────────────┐
 *   │ HEADER (room name, live pill, orchestration state, toolbar)
 *   ├───────┬─────────────────────────────────┬───────────────┤
 *   │ LEFT  │ CENTER STAGE                    │ RIGHT RAIL    │
 *   │ RAIL  │   Meeting Table (oval, seats)   │ Agenda/Actions│
 *   │       │   Overflow Strip (paginated)    │ /Stats tabs   │
 *   │People │   Transcript (scrollable)       │               │
 *   │sidebar│                                 │               │
 *   ├───────┴─────────────────────────────────┴───────────────┤
 *   │ INPUT BAR (message + Call On + Run Turn)                │
 *   └─────────────────────────────────────────────────────────┘
 *
 * Features:
 *   - Seat paging: max 6 visible seats, overflow in gallery strip
 *   - HTML5 drag-and-drop: drag personas from rail/strip onto table
 *   - Pinned seats: double-click to pin, pinned seats stay stable
 *   - Active speaker auto-promotion to visible seat
 *   - Collapsible left/right rails (collapsed by default on <1280px)
 *   - Enterprise animation system (11+ keyframes from tailwind.config.js)
 *   - Visible orchestration: Live/Idle pill, "N want to speak", status labels
 *   - Message grouping: consecutive same-sender messages collapsed
 */
import React, { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { ArrowLeft, Send, User, Users, MessageSquare, Zap, Mic, MicOff, Hand, VolumeX, ListChecks, Play, Pause, Square, ChevronDown, Pin, X, Settings, Volume2, Gamepad2, Eye, Bot, } from 'lucide-react';
import { MeetingLeftRail } from './MeetingLeftRail';
import { MeetingRightRail } from './MeetingRightRail';
import { MeetingOverflowStrip } from './MeetingOverflowStrip';
import { PersonaProfilePanel } from './PersonaProfilePanel';
import { TeamsSettingsDrawer } from './TeamsSettingsDrawer';
import { MeetingVoiceSettings } from './MeetingVoiceSettings';
import { MeetingPlayMode } from './MeetingPlayMode';
import { usePersonaVoices } from './usePersonaVoices';
import { useMeetingTts } from './useMeetingTts';
import { BridgeStatusPanel } from './BridgeStatusPanel';
import { useBridge } from './useBridge';
// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const MAX_VISIBLE_SEATS = 6;
// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function resolveAvatarUrl(persona, backendUrl) {
    const file = persona.persona_appearance?.selected_thumb_filename || persona.persona_appearance?.selected_filename;
    if (!file)
        return null;
    if (file.startsWith('http'))
        return file;
    return `${backendUrl}/files/${file}`;
}
function formatTime(ts) {
    return new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}
/** Position participants in an oval layout */
function seatPositions(count) {
    const positions = [];
    for (let i = 0; i < count; i++) {
        const angle = (2 * Math.PI * i) / count - Math.PI / 2;
        positions.push({
            x: 50 + 42 * Math.cos(angle),
            y: 50 + 36 * Math.sin(angle),
        });
    }
    return positions;
}
const STATUS_LABEL = {
    speaking: 'Speaking',
    'wants-to-speak': 'Wants to speak',
    listening: 'Listening',
    muted: 'Muted',
};
/** Color + label for intent_type badges on seats. */
const INTENT_TYPE_STYLE = {
    idea: { bg: 'bg-purple-500/20 border-purple-500/30', text: 'text-purple-300', label: 'Idea' },
    risk: { bg: 'bg-red-500/20 border-red-500/30', text: 'text-red-300', label: 'Risk' },
    clarify: { bg: 'bg-blue-500/20 border-blue-500/30', text: 'text-blue-300', label: 'Clarify' },
    summary: { bg: 'bg-teal-500/20 border-teal-500/30', text: 'text-teal-300', label: 'Summary' },
    action: { bg: 'bg-orange-500/20 border-orange-500/30', text: 'text-orange-300', label: 'Action' },
};
/** Compute how many rounds remain on a hand raise, or null if no meta. */
function handRaiseTTL(meta, currentRound) {
    if (!meta)
        return null;
    return Math.max(0, meta.expires_round - currentRound);
}
// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------
function SpeakingEqualizer() {
    return (<span className="inline-flex items-end gap-[2px] h-[10px]">
      {[0, 200, 400, 150].map((delay, i) => (<span key={i} className="w-[2px] bg-emerald-300 rounded-full animate-eq-bar" style={{ animationDelay: `${delay}ms` }}/>))}
    </span>);
}
function ThinkingWaveform() {
    return (<span className="inline-flex items-center gap-[3px]">
      {[0, 1, 2, 3, 4].map((i) => (<span key={i} className="w-1.5 h-1.5 rounded-full bg-emerald-400/70 animate-think-wave" style={{ animationDelay: `${i * 120}ms` }}/>))}
    </span>);
}
// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export function MeetingRoom({ room, personas, backendUrl, runningTurn = false, onBack, onSendMessage, onAddParticipant, onRemoveParticipant, onCallOn, onToggleHandRaise, onToggleMute, onPreviewTurn, onRunTurnContinue, onUpdateAgenda, onUpdateTopic, onStartPlayMode, onStopPlayMode, onPausePlayMode, onResumePlayMode, onChangeTurnMode, onSavePolicy, onChangeEngine, }) {
    const [message, setMessage] = useState('');
    const [sending, setSending] = useState(false);
    const transcriptRef = useRef(null);
    // ── Initiative preview ──
    const [turnPreview, setTurnPreview] = useState(null);
    const [previewOpen, setPreviewOpen] = useState(false);
    // ── Panel state ──
    const [leftRailOpen, setLeftRailOpen] = useState(false);
    const [rightRailOpen, setRightRailOpen] = useState(false);
    const [callOnOpen, setCallOnOpen] = useState(false);
    const [profilePersonaId, setProfilePersonaId] = useState(null);
    const [settingsOpen, setSettingsOpen] = useState(false);
    const [voiceSettingsOpen, setVoiceSettingsOpen] = useState(false);
    // ── Per-persona voice + meeting TTS ──
    const { getPersonaVoice, setPersonaVoice, map: personaVoiceMap } = usePersonaVoices();
    const { meetingTtsEnabled, setMeetingTtsEnabled, speakingPersonaId, stopSpeaking, revealedIds } = useMeetingTts(room.messages || [], getPersonaVoice);
    // ── STT mic state (additive) ──
    const [sttActive, setSttActive] = useState(false);
    const [sttInterim, setSttInterim] = useState('');
    // ── Teams bridge state ──
    const bridge = useBridge({
        backendUrl,
        roomId: room.id,
        statusPollInterval: 10000,
    });
    // ── Seat paging state ──
    const [visibleSeatIds, setVisibleSeatIds] = useState([]);
    const [pinnedIds, setPinnedIds] = useState(new Set());
    const [overflowPage, setOverflowPage] = useState(0);
    // ── Drag-drop state ──
    const [dragOverTable, setDragOverTable] = useState(false);
    // ── Animation tracking ──
    const prevParticipantCount = useRef(room.participant_ids.length);
    const [newlyJoined, setNewlyJoined] = useState(new Set());
    const prevMsgCount = useRef(room.messages?.length || 0);
    const [newMsgIds, setNewMsgIds] = useState(new Set());
    const [swappedId, setSwappedId] = useState(null);
    // ── Derived data ──
    const personaMap = useMemo(() => new Map(personas.map((p) => [p.id, p])), [personas]);
    const participantPersonas = useMemo(() => room.participant_ids.map((id) => personaMap.get(id)).filter(Boolean), [room.participant_ids, personaMap]);
    // Auto-seed voice map from persona project data (persona_appearance.persona_voice).
    // Only runs once per persona — skips if user already has a manual override.
    useEffect(() => {
        for (const p of participantPersonas) {
            if (personaVoiceMap[p.id])
                continue;
            const pv = p.persona_appearance?.persona_voice;
            if (pv?.voiceURI) {
                setPersonaVoice(p.id, {
                    voiceURI: pv.voiceURI,
                    rate: pv.rate,
                    pitch: pv.pitch,
                    volume: pv.volume,
                });
            }
        }
    }, [participantPersonas, personaVoiceMap, setPersonaVoice]);
    const intents = room.intents || {};
    const handRaises = useMemo(() => new Set(room.hand_raises || []), [room.hand_raises]);
    const handRaiseMeta = room.hand_raise_meta || {};
    const mutedSet = useMemo(() => new Set(room.muted || []), [room.muted]);
    const currentRound = room.round || 0;
    // Last assistant speaker ID
    const lastSpeakerId = useMemo(() => {
        const assistants = (room.messages || []).filter((m) => m.role === 'assistant');
        return assistants.length > 0 ? assistants[assistants.length - 1].sender_id : undefined;
    }, [room.messages]);
    // ── Seat status (synced with TTS speaking state) ──
    const getSeatStatus = useCallback((personaId) => {
        if (mutedSet.has(personaId))
            return 'muted';
        // TTS is actively reading this persona's message — show speaking animation
        if (speakingPersonaId === personaId)
            return 'speaking';
        if (runningTurn && intents[personaId]?.wants_to_speak)
            return 'speaking';
        if (runningTurn && lastSpeakerId === personaId)
            return 'speaking';
        if (handRaises.has(personaId) || intents[personaId]?.wants_to_speak)
            return 'wants-to-speak';
        return 'listening';
    }, [intents, handRaises, mutedSet, runningTurn, lastSpeakerId, speakingPersonaId]);
    const seatClasses = (status) => {
        switch (status) {
            case 'speaking': return 'border-emerald-400 shadow-lg shadow-emerald-500/30 animate-speaking-ring';
            case 'wants-to-speak': return 'border-amber-400/60 shadow-md shadow-amber-500/15 animate-wants-pulse';
            case 'muted': return 'border-red-400/30 opacity-50 grayscale-[30%]';
            default: return 'border-white/15 hover:border-white/25 animate-seat-breathe';
        }
    };
    const seatNameClass = (status) => {
        switch (status) {
            case 'speaking': return 'text-emerald-300/90';
            case 'wants-to-speak': return 'text-amber-300/80';
            case 'muted': return 'text-red-300/50';
            default: return 'text-white/40';
        }
    };
    const statusLabelClass = (status) => {
        switch (status) {
            case 'speaking': return 'text-emerald-300/60';
            case 'wants-to-speak': return 'text-amber-300/50';
            case 'muted': return 'text-red-300/40';
            default: return 'text-white/20';
        }
    };
    // ── Orchestration summary for header ──
    const wantsToSpeakCount = useMemo(() => room.participant_ids.filter((id) => {
        if (mutedSet.has(id))
            return false;
        return handRaises.has(id) || intents[id]?.wants_to_speak;
    }).length, [room.participant_ids, intents, handRaises, mutedSet]);
    // ── Seat paging: compute visible vs overflow ──
    useEffect(() => {
        const allIds = room.participant_ids;
        if (allIds.length <= MAX_VISIBLE_SEATS) {
            setVisibleSeatIds(allIds);
            return;
        }
        // Keep pinned IDs in visible seats
        const pinned = allIds.filter((id) => pinnedIds.has(id));
        // Auto-promote active speaker
        const speaker = lastSpeakerId && allIds.includes(lastSpeakerId) && !pinnedIds.has(lastSpeakerId) ? lastSpeakerId : null;
        // Fill remaining visible slots
        const usedIds = new Set([...pinned, ...(speaker ? [speaker] : [])]);
        const remaining = allIds.filter((id) => !usedIds.has(id));
        const slotsLeft = MAX_VISIBLE_SEATS - usedIds.size;
        const visible = [...pinned, ...(speaker ? [speaker] : []), ...remaining.slice(0, Math.max(0, slotsLeft))];
        setVisibleSeatIds(visible.slice(0, MAX_VISIBLE_SEATS));
    }, [room.participant_ids, pinnedIds, lastSpeakerId]);
    const visiblePersonas = useMemo(() => visibleSeatIds.map((id) => personaMap.get(id)).filter(Boolean), [visibleSeatIds, personaMap]);
    const overflowPersonas = useMemo(() => {
        const visSet = new Set(visibleSeatIds);
        return participantPersonas.filter((p) => !visSet.has(p.id));
    }, [participantPersonas, visibleSeatIds]);
    const allSeats = useMemo(() => seatPositions(1 + visiblePersonas.length), [visiblePersonas.length]);
    // Scale avatar size inversely with participant count — bigger when fewer people
    const totalSeats = 1 + visiblePersonas.length;
    const avatarSize = totalSeats <= 2 ? 'w-44 h-44 lg:w-52 lg:h-52'
        : totalSeats <= 3 ? 'w-40 h-40 lg:w-48 lg:h-48'
            : totalSeats <= 4 ? 'w-36 h-36 lg:w-40 lg:h-40'
                : 'w-32 h-32 lg:w-36 lg:h-36';
    const hostAvatarSize = totalSeats <= 2 ? 'w-28 h-28 lg:w-32 lg:h-32'
        : totalSeats <= 3 ? 'w-24 h-24 lg:w-28 lg:h-28'
            : totalSeats <= 4 ? 'w-20 h-20 lg:w-24 lg:h-24'
                : 'w-18 h-18 lg:w-20 lg:h-20';
    const hostIconSize = totalSeats <= 3 ? 36 : 28;
    // ── Newly joined animation ──
    useEffect(() => {
        if (room.participant_ids.length > prevParticipantCount.current) {
            const prevIds = new Set(participantPersonas.slice(0, prevParticipantCount.current).map(p => p.id));
            const joined = room.participant_ids.filter(id => !prevIds.has(id));
            if (joined.length > 0) {
                setNewlyJoined(new Set(joined));
                const timer = setTimeout(() => setNewlyJoined(new Set()), 500);
                prevParticipantCount.current = room.participant_ids.length;
                return () => clearTimeout(timer);
            }
        }
        prevParticipantCount.current = room.participant_ids.length;
    }, [room.participant_ids, participantPersonas]);
    // ── New message animation ──
    useEffect(() => {
        const msgs = room.messages || [];
        if (msgs.length > prevMsgCount.current) {
            const newIds = msgs.slice(prevMsgCount.current).map(m => m.id);
            setNewMsgIds(new Set(newIds));
            const timer = setTimeout(() => setNewMsgIds(new Set()), 400);
            prevMsgCount.current = msgs.length;
            return () => clearTimeout(timer);
        }
        prevMsgCount.current = msgs.length;
    }, [room.messages]);
    // ── Auto-scroll transcript ──
    // Double scroll: immediate rAF for fast updates + delayed fallback
    // for long messages that need extra layout time.
    useEffect(() => {
        const el = transcriptRef.current;
        if (!el)
            return;
        const raf = requestAnimationFrame(() => {
            el.scrollTop = el.scrollHeight;
        });
        // Fallback for long messages that may still be laying out
        const timer = setTimeout(() => {
            el.scrollTop = el.scrollHeight;
        }, 150);
        return () => {
            cancelAnimationFrame(raf);
            clearTimeout(timer);
        };
    }, [room.messages?.length]);
    // ── Swap animation cleanup ──
    useEffect(() => {
        if (swappedId) {
            const t = setTimeout(() => setSwappedId(null), 400);
            return () => clearTimeout(t);
        }
    }, [swappedId]);
    // ── Handlers ──
    const handleSend = useCallback(async () => {
        const text = message.trim();
        if (!text || sending)
            return;
        setSending(true);
        setMessage('');
        try {
            await onSendMessage(text);
        }
        catch (e) {
            console.error('Failed to send:', e);
        }
        finally {
            setSending(false);
        }
    }, [message, sending, onSendMessage]);
    const handleKeyDown = useCallback((e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    }, [handleSend]);
    // ── Mic STT for Teams (additive) ──
    const startTeamsStt = useCallback(async () => {
        if (!window.SpeechService?.startSTT || sttActive)
            return;
        setSttActive(true);
        setSttInterim('');
        await window.SpeechService.startSTT({
            onInterim: (t) => setSttInterim(t),
            onResult: async (t) => {
                setSttInterim('');
                setSttActive(false);
                if (t.trim()) {
                    setSending(true);
                    setMessage('');
                    try {
                        await onSendMessage(t.trim());
                    }
                    catch (e) {
                        console.error('STT send error:', e);
                    }
                    finally {
                        setSending(false);
                    }
                }
            },
            onError: () => setSttActive(false),
            onEnd: () => setSttActive(false),
        });
    }, [sttActive, onSendMessage]);
    const stopTeamsStt = useCallback(() => {
        window.SpeechService?.stopSTT?.();
        setSttActive(false);
        setSttInterim('');
    }, []);
    const togglePin = useCallback((personaId) => {
        setPinnedIds((prev) => {
            const next = new Set(prev);
            if (next.has(personaId))
                next.delete(personaId);
            else
                next.add(personaId);
            return next;
        });
    }, []);
    /** Promote an overflow persona to a visible seat (swap with last non-pinned visible) */
    const promoteToSeat = useCallback((personaId) => {
        setVisibleSeatIds((prev) => {
            if (prev.includes(personaId))
                return prev;
            // Find last non-pinned seat to swap out
            const swapIdx = [...prev].reverse().findIndex((id) => !pinnedIds.has(id));
            if (swapIdx < 0)
                return prev;
            const realIdx = prev.length - 1 - swapIdx;
            const next = [...prev];
            next[realIdx] = personaId;
            setSwappedId(personaId);
            return next;
        });
    }, [pinnedIds]);
    // ── Drag & Drop ──
    const handleDragStartPersona = useCallback((e, personaId) => {
        e.dataTransfer.setData('text/plain', personaId);
        e.dataTransfer.effectAllowed = 'move';
    }, []);
    const handleTableDragOver = useCallback((e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        setDragOverTable(true);
    }, []);
    const handleTableDragLeave = useCallback(() => setDragOverTable(false), []);
    const handleTableDrop = useCallback((e) => {
        e.preventDefault();
        setDragOverTable(false);
        const personaId = e.dataTransfer.getData('text/plain');
        if (!personaId)
            return;
        // If not yet in meeting, add them
        if (!room.participant_ids.includes(personaId)) {
            onAddParticipant(personaId);
            return;
        }
        // If in overflow, promote to visible seat
        promoteToSeat(personaId);
    }, [room.participant_ids, onAddParticipant, promoteToSeat]);
    // ── Auto-fetch initiative preview when messages change ──
    useEffect(() => {
        if (!onPreviewTurn || runningTurn || room.participant_ids.length === 0)
            return;
        let cancelled = false;
        const fetchPreview = async () => {
            try {
                const preview = await onPreviewTurn();
                if (!cancelled)
                    setTurnPreview(preview);
            }
            catch { /* ignore */ }
        };
        fetchPreview();
        return () => { cancelled = true; };
    }, [onPreviewTurn, room.messages?.length, room.participant_ids.length, runningTurn]);
    // ── Message filtering: TTS reveal gating + facilitator filtering ──
    const allMessages = room.messages || [];
    const messages = allMessages.filter((msg) => {
        // Hide facilitator debug messages unless play mode has show_facilitator enabled
        if (msg.sender_id === 'facilitator') {
            return room.play_mode?.show_facilitator ?? false;
        }
        // Gate assistant messages behind TTS reveal queue
        if (msg.role === 'assistant' && meetingTtsEnabled && !revealedIds.has(msg.id)) {
            return false;
        }
        return true;
    })
        // Deduplicate: skip consecutive messages from the same sender with identical content
        .filter((msg, idx, arr) => {
        if (idx === 0)
            return true;
        const prev = arr[idx - 1];
        return !(prev.sender_id === msg.sender_id && prev.content === msg.content);
    });
    return (<div className="h-full w-full bg-black text-white font-sans overflow-hidden flex flex-col">

      {/* ═══════════════════════ HEADER ═══════════════════════ */}
      <div className="flex-shrink-0 flex items-center justify-between px-4 py-2.5 border-b border-white/[0.06] bg-black/50 backdrop-blur-sm relative z-30">
        {/* Left: back + room info */}
        <div className="flex items-center gap-3">
          <button onClick={onBack} className="p-1.5 rounded-lg hover:bg-white/5 text-white/40 hover:text-white/60 transition-colors">
            <ArrowLeft size={16}/>
          </button>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-semibold text-white">{room.name}</h2>
              {/* Live / Idle pill */}
              <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-semibold ${runningTurn
            ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/20'
            : 'bg-white/[0.04] text-white/25 border border-white/[0.06]'}`}>
                <span className={`w-1.5 h-1.5 rounded-full ${runningTurn ? 'bg-emerald-400 animate-glow-pulse' : 'bg-white/20'}`}/>
                {runningTurn ? 'Live' : 'Idle'}
              </span>
              {/* Play Mode consolidated status pill */}
              {room.play_mode?.enabled && (<span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[9px] font-semibold ${room.play_mode.paused_by_user
                ? 'bg-amber-500/15 text-amber-300 border border-amber-500/20'
                : 'bg-purple-500/15 text-purple-300 border border-purple-500/20'}`}>
                  <Gamepad2 size={9}/>
                  {room.play_mode.paused_by_user ? 'Paused' : 'Play'}
                  <span className="text-[8px] opacity-60">·</span>
                  <span className="text-[8px] opacity-60 font-mono">R{room.play_mode.round_count}/{room.play_mode.max_rounds || '∞'}</span>
                  {/* Next speaker from preview */}
                  {turnPreview?.selected_names?.[0] && !room.play_mode.paused_by_user && (<>
                      <span className="text-[8px] opacity-40">·</span>
                      <span className="text-[8px] opacity-70">Next: {turnPreview.selected_names[0]}</span>
                    </>)}
                  {/* Mini progress bar (hidden when infinite) */}
                  {(room.play_mode.max_rounds || 0) > 0 && (<span className="w-8 h-1 rounded-full bg-white/[0.08] overflow-hidden inline-flex">
                      <span className="h-full rounded-full bg-purple-400/50 transition-all duration-500" style={{ width: `${Math.min(100, ((room.play_mode.round_count || 0) / room.play_mode.max_rounds) * 100)}%` }}/>
                    </span>)}
                </span>)}
            </div>
            {room.topic && (<div className="text-[11px] text-cyan-300/40 mt-0.5 max-w-[320px] truncate" title={room.topic}>
                {room.topic}
              </div>)}
            <div className="text-[11px] text-white/35 flex items-center gap-2 mt-0.5">
              <span className="flex items-center gap-1">
                <Users size={10}/>
                {room.participant_ids.length + 1} participants
              </span>
              <span className="flex items-center gap-1">
                <Zap size={9}/>
                {room.turn_mode.replace('-', ' ')}
              </span>
              {wantsToSpeakCount > 0 && (<span className="flex items-center gap-1 text-amber-300/60">
                  <Hand size={9}/>
                  {wantsToSpeakCount} want{wantsToSpeakCount === 1 ? 's' : ''} to speak
                </span>)}
              {currentRound > 0 && (<span className="text-white/20">
                  R{currentRound}
                </span>)}
              {runningTurn && (<span className="flex items-center gap-1 text-emerald-300/50 animate-glow-pulse">
                  generating...
                </span>)}
            </div>
          </div>
        </div>

        {/* Center: Initiative bar (BG3-style next speakers preview) */}
        {turnPreview && turnPreview.candidates.length > 0 && !runningTurn && (<div className="flex items-center gap-1.5 px-2">
            <span className="text-[8px] text-white/20 font-medium uppercase tracking-wider mr-1">Next:</span>
            {turnPreview.candidates.slice(0, 4).map((c) => {
                const isSelected = turnPreview.selected.includes(c.persona_id);
                const persona = personaMap.get(c.persona_id);
                const avatarUrl = persona ? resolveAvatarUrl(persona, backendUrl) : null;
                return (<div key={c.persona_id} className={`flex items-center gap-1 px-1.5 py-1 rounded-full text-[9px] transition-all ${isSelected
                        ? 'bg-cyan-500/10 border border-cyan-500/20 text-cyan-300/70'
                        : 'bg-white/[0.02] border border-white/[0.04] text-white/30'}`} title={`${c.display_name}: ${(c.score * 100).toFixed(0)}% — ${c.reasons.join(', ')}`}>
                  <div className="w-4 h-4 rounded-full overflow-hidden flex-shrink-0">
                    {avatarUrl ? (<img src={avatarUrl} className="w-full h-full object-cover"/>) : (<div className="w-full h-full bg-white/5 flex items-center justify-center text-[7px] text-white/20">
                        {c.display_name[0]?.toUpperCase()}
                      </div>)}
                  </div>
                  <span className="max-w-[48px] truncate">{c.display_name.split(' ')[0]}</span>
                  {c.status === 'called_on' && <Mic size={7} className="text-cyan-400/60"/>}
                  {c.status === 'hand_raise' && <Hand size={7} className="text-amber-300/60"/>}
                  {isSelected && c.status === 'auto' && <span className="w-1 h-1 rounded-full bg-cyan-400/40"/>}
                </div>);
            })}
          </div>)}

        {/* Right: toolbar */}
        <div className="flex items-center gap-2">
          <button onClick={() => setLeftRailOpen(!leftRailOpen)} className={`flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-xs font-medium transition-all ${leftRailOpen
            ? 'bg-cyan-500/10 text-cyan-300 border border-cyan-500/20'
            : 'bg-white/[0.03] text-white/40 hover:text-white/60 border border-white/[0.06] hover:border-white/12'}`}>
            <Users size={14}/>
            People
          </button>
          <button onClick={() => setRightRailOpen(!rightRailOpen)} className={`flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-xs font-medium transition-all ${rightRailOpen
            ? 'bg-cyan-500/10 text-cyan-300 border border-cyan-500/20'
            : 'bg-white/[0.03] text-white/40 hover:text-white/60 border border-white/[0.06] hover:border-white/12'}`}>
            <ListChecks size={14}/>
            Agenda
          </button>
          <button onClick={() => setVoiceSettingsOpen(!voiceSettingsOpen)} className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-all ${voiceSettingsOpen
            ? 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/20'
            : meetingTtsEnabled
                ? 'bg-emerald-500/[0.06] text-emerald-300/60 border border-emerald-500/15 hover:border-emerald-500/25'
                : 'bg-white/[0.03] text-white/40 hover:text-white/60 border border-white/[0.06] hover:border-white/12'}`} title="Meeting voice settings">
            <Volume2 size={14}/>
            {meetingTtsEnabled && (<span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-glow-pulse"/>)}
          </button>
          {/* Play Mode button */}
          {onStartPlayMode && onStopPlayMode && onPausePlayMode && onResumePlayMode && (<MeetingPlayMode playMode={room.play_mode} participantCount={room.participant_ids.length} turnMode={room.turn_mode} onStart={onStartPlayMode} onStop={onStopPlayMode} onPause={onPausePlayMode} onResume={onResumePlayMode}/>)}
          <button onClick={() => setSettingsOpen(!settingsOpen)} className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-all ${settingsOpen
            ? 'bg-cyan-500/10 text-cyan-300 border border-cyan-500/20'
            : 'bg-white/[0.03] text-white/40 hover:text-white/60 border border-white/[0.06] hover:border-white/12'}`} title="Room settings">
            <Settings size={14}/>
          </button>
        </div>
      </div>

      {/* ═══════════════════════ 3-COLUMN BODY ═══════════════════════ */}
      <div className="flex-1 flex min-h-0">

        {/* ── LEFT RAIL ── */}
        {leftRailOpen && (<MeetingLeftRail expanded={leftRailOpen} onToggle={() => setLeftRailOpen(false)} personas={personas} participantIds={room.participant_ids} intents={intents} handRaises={handRaises} handRaiseMeta={handRaiseMeta} currentRound={currentRound} mutedSet={mutedSet} runningTurn={runningTurn} lastSpeakerId={lastSpeakerId} backendUrl={backendUrl} onAddParticipant={(id) => onAddParticipant(id)} onCallOn={onCallOn ? (id) => onCallOn(id) : undefined} onToggleMute={onToggleMute ? (id) => onToggleMute(id) : undefined} onRemoveParticipant={(id) => onRemoveParticipant(id)} onDragStartPersona={handleDragStartPersona} onOpenProfile={(id) => setProfilePersonaId(id)}/>)}

        {/* ── CENTER STAGE ── */}
        <div className="flex-1 flex flex-col min-w-0 min-h-0">

          {/* MEETING TABLE */}
          <div className={`relative flex-shrink-0 mx-4 my-2 transition-all duration-300 ${dragOverTable ? 'ring-2 ring-cyan-400/30 ring-inset rounded-2xl' : ''}`} style={{ height: 'clamp(340px, 48vh, 560px)' }} onDragOver={handleTableDragOver} onDragLeave={handleTableDragLeave} onDrop={handleTableDrop}>
            {/* Oval table with ambient glow when speaking */}
            <div className={`absolute inset-[12%] rounded-[50%] border transition-all duration-700 ${lastSpeakerId
            ? 'border-emerald-500/[0.06] bg-gradient-to-b from-emerald-500/[0.015] to-transparent'
            : 'border-white/[0.04] bg-white/[0.01]'}`}/>

            {/* Center label */}
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
              <div className="text-center">
                <div className="text-xs text-white/12 font-medium max-w-[160px] truncate">{room.name}</div>
                {dragOverTable && (<div className="text-[9px] text-cyan-300/50 mt-1 animate-glow-pulse">Drop to add</div>)}
              </div>
            </div>

            {/* Human seat (position 0) */}
            {allSeats.length > 0 && (<div className="absolute -translate-x-1/2 -translate-y-1/2" style={{ left: `${allSeats[0].x}%`, top: `${allSeats[0].y}%` }}>
                <div className="flex flex-col items-center gap-1">
                  <div className={`${hostAvatarSize} rounded-full bg-cyan-500/15 border-2 border-cyan-500/40 flex items-center justify-center shadow-lg shadow-cyan-500/10 transition-all duration-300`}>
                    <User size={hostIconSize} className="text-cyan-300"/>
                  </div>
                  <span className="text-sm text-cyan-300/60 font-semibold">You (Host)</span>
                  <span className="text-xs text-cyan-300/30">Speaking</span>
                </div>
              </div>)}

            {/* Persona seats (visible only, up to MAX_VISIBLE_SEATS) */}
            {visiblePersonas.map((p, i) => {
            const pos = allSeats[i + 1];
            if (!pos)
                return null;
            const avatarUrl = resolveAvatarUrl(p, backendUrl);
            const status = getSeatStatus(p.id);
            const intent = intents[p.id];
            const isMuted = mutedSet.has(p.id);
            const isNewlyJoined = newlyJoined.has(p.id);
            const isSwapped = swappedId === p.id;
            const isPinned = pinnedIds.has(p.id);
            const isNextSpeaker = room.play_mode?.enabled && !room.play_mode?.paused_by_user && turnPreview?.selected?.[0] === p.id;
            return (<div key={p.id} className={`absolute group ${isNewlyJoined ? 'animate-seat-enter' : isSwapped ? 'animate-seat-swap' : ''}`} style={{ left: `${pos.x}%`, top: `${pos.y}%`, transform: 'translate(-50%, -50%)' }}>
                  <div className="flex flex-col items-center gap-0.5 relative">
                    {/* Speaking glow */}
                    {status === 'speaking' && (<div className="absolute inset-0 -m-4 rounded-full bg-emerald-400/10 blur-xl animate-glow-pulse pointer-events-none"/>)}
                    {/* Next speaker glow (play mode only) */}
                    {isNextSpeaker && status !== 'speaking' && (<div className="absolute inset-0 -m-3 rounded-full bg-purple-400/10 blur-lg animate-glow-pulse pointer-events-none"/>)}

                    {/* Avatar */}
                    <div className={`${avatarSize} rounded-full border-2 overflow-hidden flex items-center justify-center transition-all duration-300 cursor-pointer ${isNextSpeaker && status !== 'speaking' ? 'border-purple-400/50 shadow-md shadow-purple-500/20' : seatClasses(status)}`} onClick={() => setProfilePersonaId(p.id)} onDoubleClick={() => togglePin(p.id)} title={`${p.name} — click for profile · double-click to ${isPinned ? 'unpin' : 'pin'}`}>
                      {avatarUrl ? (<img src={avatarUrl} alt={p.name} className="w-full h-full object-cover"/>) : (<div className="w-full h-full bg-white/5 flex items-center justify-center text-lg text-white/30 font-bold">
                          {p.name[0]?.toUpperCase()}
                        </div>)}
                    </div>

                    {/* Pin indicator */}
                    {isPinned && (<div className="absolute -top-1 -right-1 w-5 h-5 rounded-full bg-white/10 border border-white/20 flex items-center justify-center">
                        <Pin size={10} className="text-white/50"/>
                      </div>)}

                    {/* Name */}
                    <span className={`text-sm font-semibold truncate max-w-[120px] transition-colors duration-300 ${seatNameClass(status)}`}>
                      {p.name}
                    </span>

                    {/* Status text label with reason tooltip */}
                    <span className={`text-xs ${isNextSpeaker && status !== 'speaking' ? 'text-purple-300/70' : statusLabelClass(status)} cursor-default`} title={intent?.reason || ''}>
                      {isNextSpeaker && status !== 'speaking' ? 'Next up' : STATUS_LABEL[status]}
                    </span>

                    {/* Status badge + intent type */}
                    {status === 'wants-to-speak' && (() => {
                    const ttl = handRaiseTTL(handRaiseMeta[p.id], currentRound);
                    return (<div className="absolute -top-2 left-1/2 animate-badge-in">
                          <div className="px-1.5 py-0.5 rounded-md bg-amber-500/20 border border-amber-500/30 backdrop-blur-sm flex items-center gap-1" title={intent?.reason || ''}>
                            <Hand size={8} className="text-amber-300"/>
                            {ttl !== null && <span className="text-[9px] text-amber-300/70">{ttl}r</span>}
                          </div>
                        </div>);
                })()}
                    {status === 'muted' && (<div className="absolute -top-2 left-1/2 animate-badge-in">
                        <div className="px-1 py-0.5 rounded-md bg-red-500/20 border border-red-500/30 backdrop-blur-sm">
                          <VolumeX size={8} className="text-red-300"/>
                        </div>
                      </div>)}
                    {status === 'speaking' && (<div className="absolute -top-2 left-1/2 animate-badge-in">
                        <div className="px-1.5 py-0.5 rounded-md bg-emerald-500/20 border border-emerald-500/30 backdrop-blur-sm flex items-center gap-1">
                          <SpeakingEqualizer />
                        </div>
                      </div>)}

                    {/* Intent type pill (shown when not muted and intent exists) */}
                    {intent && status !== 'muted' && intent.intent_type && INTENT_TYPE_STYLE[intent.intent_type] && (<div className="animate-badge-in" title={`${intent.reason} (urgency: ${Math.round(intent.urgency * 100)}%)`}>
                        <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[9px] font-semibold border backdrop-blur-sm ${INTENT_TYPE_STYLE[intent.intent_type].bg} ${INTENT_TYPE_STYLE[intent.intent_type].text}`}>
                          {INTENT_TYPE_STYLE[intent.intent_type].label}
                        </span>
                      </div>)}

                    {/* Confidence bar */}
                    {intent && status !== 'muted' && (<div className="w-20 h-1 rounded-full bg-white/[0.06] overflow-hidden">
                        <div className={`h-full rounded-full animate-confidence-fill ${status === 'speaking' ? 'bg-emerald-400/60' : status === 'wants-to-speak' ? 'bg-amber-400/50' : 'bg-white/15'}`} style={{ '--confidence-width': `${Math.round(intent.confidence * 100)}%`, width: `${Math.round(intent.confidence * 100)}%` }}/>
                      </div>)}

                    {/* Moderation controls on hover */}
                    <div className="absolute -bottom-6 left-1/2 -translate-x-1/2 flex items-center gap-1 opacity-0 group-hover:opacity-100 translate-y-1 group-hover:translate-y-0 transition-all duration-200">
                      {onCallOn && (<button onClick={(e) => { e.stopPropagation(); onCallOn(p.id); }} className="w-6 h-6 rounded-full bg-cyan-500/20 hover:bg-cyan-500/40 border border-cyan-500/30 flex items-center justify-center transition-colors" title={`Call on ${p.name}`}>
                          <Mic size={10} className="text-cyan-300"/>
                        </button>)}
                      {onToggleMute && (<button onClick={(e) => { e.stopPropagation(); onToggleMute(p.id); }} className={`w-6 h-6 rounded-full border flex items-center justify-center transition-colors ${isMuted ? 'bg-red-500/20 hover:bg-red-500/40 border-red-500/30' : 'bg-white/5 hover:bg-white/10 border-white/10'}`} title={isMuted ? 'Unmute' : 'Mute'}>
                          <MicOff size={10} className={isMuted ? 'text-red-300' : 'text-white/30'}/>
                        </button>)}
                      <button onClick={(e) => { e.stopPropagation(); onRemoveParticipant(p.id); }} className="w-6 h-6 rounded-full bg-red-500/20 hover:bg-red-500/40 border border-red-500/30 flex items-center justify-center transition-colors" title="Remove">
                        <X size={10} className="text-red-300"/>
                      </button>
                    </div>
                  </div>
                </div>);
        })}
          </div>

          {/* OVERFLOW STRIP (paginated gallery for >6 participants) */}
          <MeetingOverflowStrip overflowPersonas={overflowPersonas} page={overflowPage} onPageChange={setOverflowPage} backendUrl={backendUrl} intents={intents} handRaises={handRaises} mutedSet={mutedSet} runningTurn={runningTurn} lastSpeakerId={lastSpeakerId} onDragStart={handleDragStartPersona} onPromote={promoteToSeat}/>

          {/* TRANSCRIPT */}
          <div className="flex-1 min-h-0 flex flex-col border-t border-white/[0.03]">
            <div className="px-4 py-2 flex-shrink-0">
              <span className="text-[13px] font-semibold text-white/30 uppercase tracking-wider">Transcript</span>
            </div>
            <div ref={transcriptRef} className="flex-1 overflow-y-auto px-4 pb-2 space-y-2.5 scrollbar-hide max-w-[900px] mx-auto w-full">

              {/* Empty state */}
              {messages.length === 0 && (<div className="text-center py-6 animate-msg-slide-in">
                  <MessageSquare size={20} className="mx-auto text-white/10 mb-2"/>
                  <p className="text-xs text-white/25">Start the conversation by typing a message below.</p>
                </div>)}

              {/* Messages with grouping */}
              {messages.map((msg, idx) => {
            const isHuman = msg.role === 'user' && msg.sender_id === 'human';
            const isFacilitator = msg.sender_id === 'facilitator' || msg.sender_id === 'system';
            const persona = personaMap.get(msg.sender_id);
            const avatarUrl = persona ? resolveAvatarUrl(persona, backendUrl) : null;
            const isNew = newMsgIds.has(msg.id);
            // Grouping: skip avatar+name if same sender as previous within 2 min
            const prevMsg = idx > 0 ? messages[idx - 1] : null;
            const isGrouped = prevMsg
                && prevMsg.sender_id === msg.sender_id
                && (msg.timestamp - prevMsg.timestamp) < 120;
            // Facilitator/system messages: render as subtle centered notices
            if (isFacilitator) {
                return (<div key={msg.id} className={`flex justify-center ${isNew ? 'animate-msg-slide-in' : ''}`}>
                      <div className="flex items-center gap-2 px-4 py-1.5 rounded-full bg-purple-500/[0.06] border border-purple-500/[0.08]">
                        <Bot size={12} className="text-purple-400/50"/>
                        <span className="text-[11px] text-purple-300/40 leading-relaxed">
                          {msg.content
                        .replace(/<think>[\s\S]*?<\/think>/g, '')
                        .replace(/<\/think>\s*/g, '')
                        .replace(/^\[.*?\]:\s*/, '')
                        .trim()}
                        </span>
                      </div>
                    </div>);
            }
            return (<div key={msg.id} className={`flex gap-3 ${isHuman ? 'flex-row-reverse' : ''} ${isNew ? (isHuman ? 'animate-msg-slide-in-right' : 'animate-msg-slide-in') : ''} ${isGrouped ? 'mt-0.5' : ''}`}>
                    {/* Avatar (or spacer if grouped) */}
                    {isGrouped ? (<div className="w-12 h-12 flex-shrink-0"/>) : (<div className={`w-12 h-12 rounded-full flex-shrink-0 overflow-hidden border transition-all duration-300 ${!isHuman && msg.sender_id && getSeatStatus(msg.sender_id) === 'speaking'
                        ? 'border-emerald-500/30 shadow-sm shadow-emerald-500/20'
                        : 'border-white/10'}`}>
                        {isHuman ? (<div className="w-full h-full bg-cyan-500/15 flex items-center justify-center">
                            <User size={16} className="text-cyan-300"/>
                          </div>) : avatarUrl ? (<img src={avatarUrl} alt={msg.sender_name} className="w-full h-full object-cover"/>) : (<div className="w-full h-full bg-white/5 flex items-center justify-center text-[10px] text-white/30 font-bold">
                            {msg.sender_name[0]?.toUpperCase()}
                          </div>)}
                      </div>)}

                    {/* Bubble */}
                    <div className={`${isHuman ? 'max-w-[480px] items-end' : 'max-w-[640px]'}`}>
                      {!isGrouped && (<div className="flex items-center gap-2 mb-0.5">
                          <span className={`text-xs font-medium ${isHuman ? 'text-cyan-300/60' : 'text-white/45'}`}>
                            {msg.sender_name}
                          </span>
                          <span className="text-[11px] text-white/20">{formatTime(msg.timestamp)}</span>
                        </div>)}
                      <div className={`px-3.5 py-2.5 rounded-2xl text-base leading-relaxed ${isHuman
                    ? 'bg-cyan-500/15 border border-cyan-500/20 text-white/90 rounded-tr-md'
                    : speakingPersonaId === msg.sender_id
                        ? 'bg-emerald-500/[0.06] border border-emerald-500/20 text-white/80 rounded-tl-md'
                        : 'bg-white/[0.04] border border-white/[0.06] text-white/80 rounded-tl-md'}`}>
                        {msg.content
                    .replace(/<think>[\s\S]*?<\/think>/g, '')
                    .replace(/<\/think>\s*/g, '')
                    .replace(/^\[.*?\]:\s*/, '')
                    .trim()}
                      </div>
                    </div>
                  </div>);
        })}

              {/* Thinking indicator */}
              {runningTurn && (<div className="flex gap-3 animate-msg-slide-in">
                  <div className="w-12 h-12 rounded-full flex-shrink-0 overflow-hidden border border-emerald-500/20 bg-emerald-500/10 flex items-center justify-center animate-speaking-ring">
                    <Users size={18} className="text-emerald-300"/>
                  </div>
                  <div>
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="text-[11px] font-medium text-emerald-300/60 animate-glow-pulse">Personas</span>
                    </div>
                    <div className="px-3.5 py-2.5 rounded-2xl rounded-tl-md bg-white/[0.04] border border-emerald-500/15 text-base text-white/50 flex items-center gap-3">
                      <ThinkingWaveform />
                      <span className="animate-glow-pulse">Thinking...</span>
                    </div>
                  </div>
                </div>)}
            </div>
          </div>
        </div>

        {/* ── RIGHT RAIL ── */}
        {rightRailOpen && (<div className="flex-shrink-0 w-64 flex flex-col overflow-hidden">
            {/* Bridge status panel — shown when Teams bridge is connected */}
            {bridge.status?.connected && (<div className="px-2 pt-2">
                <BridgeStatusPanel status={bridge.status} onDisconnect={() => bridge.disconnect()} onToggleVoice={(enabled) => bridge.toggleVoice(enabled)} onRefresh={() => bridge.fetchStatus()} loading={bridge.loading}/>
              </div>)}
            <MeetingRightRail room={room} personas={personas} backendUrl={backendUrl} onClose={() => setRightRailOpen(false)} onUpdateAgenda={onUpdateAgenda} onUpdateTopic={onUpdateTopic}/>
          </div>)}
      </div>

      {/* ═══════════════════════ INPUT BAR (Chat-style pill) ═══════════════════════ */}
      <div className="flex-shrink-0 px-4 py-3 border-t border-white/[0.04]">

        {/* Meeting action buttons row — switches between manual and play mode controls */}
        <div className="flex items-center justify-center gap-2 mb-2.5">

          {/* ── PLAY MODE ACTIVE: compact control strip ── */}
          {room.play_mode?.enabled ? (<>
              {/* Pause / Resume */}
              <button onClick={() => {
                if (room.play_mode?.paused_by_user)
                    onResumePlayMode?.();
                else
                    onPausePlayMode?.();
            }} className={`flex items-center gap-1.5 px-3.5 py-2 rounded-full text-xs font-medium transition-all ring-1 ${room.play_mode.paused_by_user
                ? 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30 hover:bg-emerald-500/25'
                : 'bg-amber-500/15 text-amber-300 ring-amber-500/30 hover:bg-amber-500/25'}`} title={room.play_mode.paused_by_user ? 'Resume' : 'Pause'}>
                {room.play_mode.paused_by_user ? <Play size={13}/> : <Pause size={13}/>}
                {room.play_mode.paused_by_user ? 'Resume' : 'Pause'}
              </button>

              {/* Stop */}
              <button onClick={() => onStopPlayMode?.()} className="flex items-center gap-1.5 px-3.5 py-2 rounded-full text-xs font-medium transition-all bg-red-500/10 text-red-300 ring-1 ring-red-500/20 hover:bg-red-500/20" title="End Play Mode">
                <Square size={13}/>
                End
              </button>

              {/* Observer indicator */}
              <span className="flex items-center gap-1.5 px-3 py-2 rounded-full text-xs text-purple-300/60 bg-purple-500/[0.06] ring-1 ring-purple-500/15">
                <Eye size={12}/>
                Observing
              </span>
            </>) : (<>
              {/* ── MANUAL MODE: Call On + Run Turn ── */}

              {/* Call On dropdown */}
              {onCallOn && participantPersonas.length > 0 && (<div className="relative">
                  <button onClick={() => setCallOnOpen(!callOnOpen)} className={`flex items-center gap-1.5 px-3.5 py-2 rounded-full text-xs font-medium transition-all ${callOnOpen
                    ? 'bg-cyan-500/15 text-cyan-300 ring-1 ring-cyan-500/30'
                    : 'bg-white/[0.04] text-white/45 hover:text-white/65 ring-1 ring-white/[0.08] hover:ring-white/15'}`}>
                    <Mic size={14}/>
                    Call On
                    <ChevronDown size={11}/>
                  </button>
                  {callOnOpen && (<div className="absolute bottom-full left-0 mb-1.5 w-52 py-1.5 rounded-xl bg-[#111] border border-white/[0.08] shadow-2xl z-50 animate-msg-slide-in">
                      {participantPersonas.filter((p) => !mutedSet.has(p.id)).map((p) => (<button key={p.id} onClick={() => { onCallOn(p.id); setCallOnOpen(false); }} className="w-full flex items-center gap-2.5 px-3 py-2 hover:bg-white/[0.04] transition-colors text-left">
                          <div className="w-10 h-10 rounded-full overflow-hidden bg-white/5 border border-white/10">
                            {resolveAvatarUrl(p, backendUrl) ? (<img src={resolveAvatarUrl(p, backendUrl)} alt={p.name} className="w-full h-full object-cover"/>) : (<div className="w-full h-full flex items-center justify-center text-[10px] text-white/30 font-bold">{p.name[0]?.toUpperCase()}</div>)}
                          </div>
                          <span className="text-xs text-white/60">{p.name}</span>
                        </button>))}
                    </div>)}
                </div>)}

              {/* Run Turn button with initiative preview */}
              <div className="relative">
                <div className="flex items-center">
                  <button onClick={async () => {
                if (onRunTurnContinue)
                    await onRunTurnContinue();
                else if (onCallOn && participantPersonas.length > 0)
                    await onCallOn(participantPersonas[0].id);
            }} disabled={runningTurn || sending} className={`flex items-center gap-1.5 px-3.5 py-2 rounded-l-full text-xs font-medium transition-all ${runningTurn
                ? 'bg-white/[0.02] text-white/10 cursor-default'
                : 'bg-white/[0.04] text-white/45 hover:text-white/65 ring-1 ring-white/[0.08] hover:ring-white/15'}`} title={turnPreview?.selected_names?.length
                ? `Run Turn → ${turnPreview.selected_names.join(', ')}`
                : 'Advance meeting by one step'}>
                    <Play size={13}/>
                    Run Turn
                    {turnPreview?.selected_names?.length ? (<span className="text-[10px] text-cyan-300/50 ml-0.5">
                        ({turnPreview.selected_names.slice(0, 2).join(', ')})
                      </span>) : null}
                  </button>
                  {/* Preview dropdown toggle */}
                  <button onClick={() => setPreviewOpen(!previewOpen)} disabled={runningTurn} className={`flex items-center px-1.5 py-2 rounded-r-full text-xs transition-all border-l border-white/[0.06] ${previewOpen
                ? 'bg-cyan-500/15 text-cyan-300'
                : runningTurn
                    ? 'bg-white/[0.02] text-white/10 cursor-default'
                    : 'bg-white/[0.04] text-white/45 hover:text-white/65 ring-1 ring-white/[0.08]'}`} title="Preview initiative order">
                    <ChevronDown size={11}/>
                  </button>
                </div>

                {/* Initiative preview dropdown */}
                {previewOpen && turnPreview && (<div className="absolute bottom-full left-0 mb-1.5 w-72 py-2 rounded-xl bg-[#111] border border-white/[0.08] shadow-2xl z-50 animate-msg-slide-in">
                    <div className="px-3 pb-2 border-b border-white/[0.04] mb-2">
                      <div className="text-[9px] font-semibold text-white/30 uppercase tracking-wider">Initiative Order</div>
                      <div className="text-[9px] text-white/20 mt-0.5">
                        Mode: {turnPreview.turn_mode?.replace('-', ' ')} · Round {turnPreview.round || 0}
                      </div>
                    </div>
                    {turnPreview.candidates.slice(0, 6).map((c, idx) => {
                    const isSelected = turnPreview.selected.includes(c.persona_id);
                    const persona = personaMap.get(c.persona_id);
                    const avatarUrl = persona ? resolveAvatarUrl(persona, backendUrl) : null;
                    return (<div key={c.persona_id} className={`flex items-center gap-2.5 px-3 py-1.5 transition-colors ${isSelected ? 'bg-cyan-500/[0.06]' : ''}`}>
                          {/* Rank */}
                          <span className={`text-[9px] w-3 text-right font-mono ${isSelected ? 'text-cyan-300/60' : 'text-white/15'}`}>
                            {idx + 1}
                          </span>
                          {/* Avatar */}
                          <div className="w-6 h-6 rounded-full overflow-hidden border border-white/10 flex-shrink-0">
                            {avatarUrl ? (<img src={avatarUrl} alt={c.display_name} className="w-full h-full object-cover"/>) : (<div className="w-full h-full bg-white/5 flex items-center justify-center text-[8px] text-white/25">
                                {c.display_name[0]?.toUpperCase()}
                              </div>)}
                          </div>
                          {/* Info */}
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-1.5">
                              <span className={`text-[10px] font-medium truncate ${isSelected ? 'text-cyan-300/80' : 'text-white/50'}`}>
                                {c.display_name}
                              </span>
                              {c.status === 'called_on' && (<span className="text-[8px] px-1 py-0.5 rounded-full bg-cyan-500/20 text-cyan-300 border border-cyan-500/30">called</span>)}
                              {c.status === 'hand_raise' && (<Hand size={8} className="text-amber-300/60"/>)}
                              {isSelected && c.status === 'auto' && (<span className="w-1 h-1 rounded-full bg-cyan-400/50"/>)}
                            </div>
                            <div className="text-[8px] text-white/20 truncate">
                              {c.reasons.slice(0, 3).join(' · ')}
                            </div>
                          </div>
                          {/* Score */}
                          <div className="flex items-center gap-1">
                            <div className="w-10 h-1 rounded-full bg-white/[0.04] overflow-hidden">
                              <div className={`h-full rounded-full ${isSelected ? 'bg-cyan-400/50' : 'bg-white/10'}`} style={{ width: `${Math.round(c.score * 100)}%` }}/>
                            </div>
                            <span className={`text-[8px] font-mono w-5 text-right ${isSelected ? 'text-cyan-300/50' : 'text-white/20'}`}>
                              {(c.score * 100).toFixed(0)}
                            </span>
                          </div>
                        </div>);
                })}
                    {turnPreview.selected.length > 0 && (<div className="px-3 pt-2 mt-1 border-t border-white/[0.04]">
                        <button onClick={() => {
                        setPreviewOpen(false);
                        if (onRunTurnContinue)
                            onRunTurnContinue();
                        else if (onCallOn && turnPreview.selected[0])
                            onCallOn(turnPreview.selected[0]);
                    }} className="w-full flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg bg-cyan-500/15 hover:bg-cyan-500/25 text-cyan-300/80 text-[10px] font-medium transition-all">
                          <Play size={10}/>
                          Run ({turnPreview.selected_names.join(', ')})
                        </button>
                      </div>)}
                  </div>)}
              </div>
            </>)}
        </div>

        {/* Chat-style pill input — matches HomePilot Chat QueryBar */}
        <div className="max-w-3xl mx-auto">
          <div className={[
            'relative w-full overflow-hidden',
            'bg-[#101010] shadow-sm shadow-black/20',
            'ring-1 ring-inset ring-white/15 hover:ring-white/20 focus-within:ring-white/25',
            'rounded-[10rem]',
            'transition-[background-color,box-shadow,border-color] duration-100 ease-in-out',
        ].join(' ')}>
            {/* Mic button (additive STT) */}
            <div className="absolute left-2.5 top-1/2 -translate-y-1/2 z-20">
              <button type="button" onClick={sttActive ? stopTeamsStt : startTeamsStt} className={`h-9 w-9 rounded-full grid place-items-center transition-all ${sttActive
            ? 'bg-red-500/20 text-red-300 ring-1 ring-red-500/40 animate-glow-pulse'
            : 'bg-white/[0.04] text-white/30 hover:text-white/50 hover:bg-white/[0.06]'}`} aria-label={sttActive ? 'Stop listening' : 'Speak into meeting'} title={sttActive ? 'Stop listening' : 'Speak into meeting (STT)'}>
                {sttActive ? <MicOff size={16}/> : <Mic size={16}/>}
              </button>
            </div>

            {/* Textarea */}
            <div className="ps-14 pe-16">
              <textarea value={message} onChange={(e) => setMessage(e.target.value)} onKeyDown={handleKeyDown} placeholder={sttInterim || (room.play_mode?.enabled ? 'Send a message to join the discussion — personas will respond to you...' : 'Type a message to the meeting...')} rows={1} className="w-full bg-transparent text-white placeholder:text-white/40 focus:outline-none resize-none min-h-[52px] py-3.5 px-1 max-h-[200px] overflow-y-auto text-[15px] leading-relaxed"/>
            </div>

            {/* Send button — white circle (matches Chat) */}
            <div className="absolute right-2.5 top-1/2 -translate-y-1/2 z-20">
              {message.trim() && !sending ? (<button type="button" onClick={handleSend} className="h-10 w-10 rounded-full bg-white text-black grid place-items-center hover:opacity-90 transition-opacity active:scale-95" aria-label="Send" title="Send message">
                  <Send size={18} strokeWidth={2.25}/>
                </button>) : (<div className="h-10 w-10 rounded-full bg-white/5 text-white/25 grid place-items-center">
                  <Send size={18}/>
                </div>)}
            </div>
          </div>
        </div>

        {/* Helper text */}
        <div className="text-[11px] text-white/20 mt-2 text-center">
          {room.play_mode?.enabled
            ? 'Sending a message joins you into the conversation · Personas will acknowledge and respond'
            : 'Enter to send · Mic to dictate · Drag personas onto the table · Double-click seat to pin'}
        </div>
      </div>

      {/* ═══════════════════════ PERSONA PROFILE PANEL ═══════════════════════ */}
      {profilePersonaId && personaMap.get(profilePersonaId) && (<PersonaProfilePanel persona={personaMap.get(profilePersonaId)} backendUrl={backendUrl} status={getSeatStatus(profilePersonaId)} onClose={() => setProfilePersonaId(null)}/>)}

      {/* Settings drawer */}
      <TeamsSettingsDrawer room={room} open={settingsOpen} onClose={() => setSettingsOpen(false)} onChangeTurnMode={onChangeTurnMode} onSave={onSavePolicy} onChangeEngine={onChangeEngine}/>

      {/* Voice settings drawer (additive) */}
      <MeetingVoiceSettings open={voiceSettingsOpen} onClose={() => setVoiceSettingsOpen(false)} participants={participantPersonas} backendUrl={backendUrl} meetingTtsEnabled={meetingTtsEnabled} onToggleTts={setMeetingTtsEnabled} getPersonaVoice={getPersonaVoice} setPersonaVoice={setPersonaVoice}/>

      <style>{`
        .scrollbar-hide::-webkit-scrollbar { display: none; }
        .scrollbar-hide { -ms-overflow-style: none; scrollbar-width: none; }
      `}</style>
    </div>);
}
