/**
 * usePersonaVoices — Per-persona voice configuration for Teams meetings.
 *
 * Stores a voiceURI + rate/pitch/volume per persona ID in localStorage.
 * Purely additive — does not touch the global SpeechService voiceConfig.
 *
 * Storage key: homepilot_persona_voice_map_v1
 */
import { useCallback, useEffect, useState } from 'react';
// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const LS_KEY = 'homepilot_persona_voice_map_v1';
// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function safeParse(raw, fallback) {
    try {
        return raw ? JSON.parse(raw) : fallback;
    }
    catch {
        return fallback;
    }
}
// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------
export function usePersonaVoices() {
    const [map, setMap] = useState(() => safeParse(localStorage.getItem(LS_KEY), {}));
    // Persist on change
    useEffect(() => {
        localStorage.setItem(LS_KEY, JSON.stringify(map));
    }, [map]);
    const setPersonaVoice = useCallback((personaId, cfg) => {
        setMap((m) => ({ ...m, [personaId]: cfg }));
    }, []);
    const clearPersonaVoice = useCallback((personaId) => {
        setMap((m) => {
            const copy = { ...m };
            delete copy[personaId];
            return copy;
        });
    }, []);
    const getPersonaVoice = useCallback((personaId) => map[personaId], [map]);
    return { map, setPersonaVoice, clearPersonaVoice, getPersonaVoice };
}
