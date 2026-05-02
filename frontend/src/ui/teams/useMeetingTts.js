/**
 * useMeetingTts — Auto-speak persona messages in Teams meetings.
 *
 * Features:
 *   - One-at-a-time playback: messages are revealed + spoken sequentially
 *   - Reveal queue: new assistant messages are held back until TTS is ready
 *   - Non-assistant messages (human, system) are always revealed immediately
 *   - When TTS is disabled, all messages are revealed immediately
 *   - Strips <think> blocks and markdown noise before speaking
 *   - Queue overflow protection: if > 3 messages queue up, flush old ones
 */
import { useEffect, useRef, useCallback, useState } from 'react';
// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const LS_TTS_KEY = 'homepilot_teams_tts_enabled';
const MAX_QUEUE = 3; // flush old messages if queue grows beyond this
// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function cleanForSpeech(text) {
    return text
        .replace(/<think>[\s\S]*?<\/think>/g, '')
        .replace(/```[\s\S]*?```/g, '')
        .replace(/^\[.*?\]:\s*/gm, '')
        .replace(/[*_~`#>]/g, '')
        .replace(/\n{2,}/g, '\n')
        .trim();
}
// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------
export function useMeetingTts(messages, getPersonaVoice) {
    // ── Toggle state (persisted) ──
    const [enabled, setEnabled] = useState(() => {
        return localStorage.getItem(LS_TTS_KEY) !== 'false';
    });
    useEffect(() => {
        localStorage.setItem(LS_TTS_KEY, String(enabled));
    }, [enabled]);
    // ── Revealed message IDs — controls what's visible in transcript ──
    const [revealedIds, setRevealedIds] = useState(() => new Set(messages.map((m) => m.id)));
    // ── Tracking refs ──
    const processedRef = useRef(new Set(messages.map((m) => m.id)));
    const initialisedRef = useRef(false);
    const queueRef = useRef([]);
    const isProcessingRef = useRef(false);
    // ── Speaking state for UI indicator ──
    const [speakingPersonaId, setSpeakingPersonaId] = useState(null);
    // ── Queue processor: reveal + speak messages one at a time ──
    const processQueue = useCallback(async () => {
        if (isProcessingRef.current)
            return;
        isProcessingRef.current = true;
        while (queueRef.current.length > 0) {
            // Overflow protection: if queue is too long, flush old messages
            if (queueRef.current.length > MAX_QUEUE) {
                const overflow = queueRef.current.splice(0, queueRef.current.length - 1);
                setRevealedIds((prev) => {
                    const next = new Set(prev);
                    for (const m of overflow)
                        next.add(m.id);
                    return next;
                });
            }
            const msg = queueRef.current.shift();
            if (!msg)
                break;
            // Reveal the message in the transcript
            setRevealedIds((prev) => new Set(prev).add(msg.id));
            // Speak it
            const text = cleanForSpeech(msg.content);
            if (text && window.SpeechService?.speakWithConfig) {
                const cfg = getPersonaVoice(msg.sender_id);
                setSpeakingPersonaId(msg.sender_id);
                try {
                    await window.SpeechService.speakWithConfig(text, cfg || {}, {});
                }
                catch {
                    // speech interrupted or unavailable — continue
                }
                setSpeakingPersonaId(null);
            }
        }
        isProcessingRef.current = false;
    }, [getPersonaVoice]);
    // ── Detect new messages and route them ──
    useEffect(() => {
        // First render: mark all existing messages as processed + revealed
        if (!initialisedRef.current) {
            for (const m of messages) {
                processedRef.current.add(m.id);
            }
            setRevealedIds(new Set(messages.map((m) => m.id)));
            initialisedRef.current = true;
            return;
        }
        let hasNewQueued = false;
        for (const msg of messages) {
            if (processedRef.current.has(msg.id))
                continue;
            processedRef.current.add(msg.id);
            // Non-assistant messages (human, system, facilitator): reveal immediately, don't speak
            if (msg.role !== 'assistant') {
                setRevealedIds((prev) => new Set(prev).add(msg.id));
                continue;
            }
            // TTS disabled: reveal immediately without speaking
            if (!enabled || !window.SpeechService?.speakWithConfig) {
                setRevealedIds((prev) => new Set(prev).add(msg.id));
                continue;
            }
            // TTS enabled: queue for sequential reveal + speak
            queueRef.current.push(msg);
            hasNewQueued = true;
        }
        if (hasNewQueued) {
            processQueue();
        }
    }, [messages, enabled, processQueue]);
    // ── Stop speaking ──
    const stop = useCallback(() => {
        // Flush remaining queue — reveal all immediately
        if (queueRef.current.length > 0) {
            setRevealedIds((prev) => {
                const next = new Set(prev);
                for (const m of queueRef.current)
                    next.add(m.id);
                return next;
            });
            queueRef.current = [];
        }
        window.SpeechService?.stopSpeaking?.();
        setSpeakingPersonaId(null);
    }, []);
    return {
        meetingTtsEnabled: enabled,
        setMeetingTtsEnabled: setEnabled,
        speakingPersonaId,
        stopSpeaking: stop,
        /** Set of message IDs that should be visible in the transcript. */
        revealedIds,
    };
}
