/** Hook for Teams room CRUD operations */
import { useState, useEffect, useCallback } from 'react';
function headers(apiKey) {
    const h = { 'Content-Type': 'application/json' };
    if (apiKey)
        h['x-api-key'] = apiKey;
    return h;
}
/** Read LLM settings from localStorage (same keys as SettingsPanel / App.tsx). */
function readLLMSettings() {
    const provider = localStorage.getItem('homepilot_provider_chat') || undefined;
    const model = localStorage.getItem('homepilot_model_chat') || undefined;
    const base_url = localStorage.getItem('homepilot_base_url_chat') || undefined;
    const concRaw = localStorage.getItem('homepilot_teams_concurrent_calls');
    const max_concurrent = concRaw ? parseInt(concRaw, 10) : undefined;
    return { provider, model, base_url, max_concurrent };
}
export function useTeamsRooms({ backendUrl, apiKey }) {
    const [rooms, setRooms] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const fetchRooms = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const res = await fetch(`${backendUrl}/v1/teams/rooms`, {
                headers: headers(apiKey),
            });
            if (!res.ok)
                throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            setRooms(data);
        }
        catch (e) {
            setError(e.message || 'Failed to fetch rooms');
        }
        finally {
            setLoading(false);
        }
    }, [backendUrl, apiKey]);
    useEffect(() => {
        fetchRooms();
    }, [fetchRooms]);
    const createRoom = useCallback(async (params) => {
        const res = await fetch(`${backendUrl}/v1/teams/rooms`, {
            method: 'POST',
            headers: headers(apiKey),
            body: JSON.stringify(params),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
            throw new Error(err.detail || 'Failed to create room');
        }
        const room = await res.json();
        setRooms((prev) => [room, ...prev]);
        return room;
    }, [backendUrl, apiKey]);
    const deleteRoom = useCallback(async (roomId) => {
        const res = await fetch(`${backendUrl}/v1/teams/rooms/${roomId}`, {
            method: 'DELETE',
            headers: headers(apiKey),
        });
        if (!res.ok)
            throw new Error('Failed to delete room');
        setRooms((prev) => prev.filter((r) => r.id !== roomId));
    }, [backendUrl, apiKey]);
    /** Update room metadata (name, description, topic, agenda, etc.). */
    const updateRoom = useCallback(async (roomId, updates) => {
        const res = await fetch(`${backendUrl}/v1/teams/rooms/${roomId}`, {
            method: 'PUT',
            headers: headers(apiKey),
            body: JSON.stringify(updates),
        });
        if (!res.ok)
            throw new Error('Failed to update room');
        const room = await res.json();
        setRooms((prev) => prev.map((r) => (r.id === roomId ? room : r)));
        return room;
    }, [backendUrl, apiKey]);
    const addParticipant = useCallback(async (roomId, personaId) => {
        const res = await fetch(`${backendUrl}/v1/teams/rooms/${roomId}/participants`, {
            method: 'POST',
            headers: headers(apiKey),
            body: JSON.stringify({ persona_id: personaId }),
        });
        if (!res.ok)
            throw new Error('Failed to add participant');
        const room = await res.json();
        setRooms((prev) => prev.map((r) => (r.id === roomId ? room : r)));
        return room;
    }, [backendUrl, apiKey]);
    const removeParticipant = useCallback(async (roomId, personaId) => {
        const res = await fetch(`${backendUrl}/v1/teams/rooms/${roomId}/participants/${personaId}`, {
            method: 'DELETE',
            headers: headers(apiKey),
        });
        if (!res.ok)
            throw new Error('Failed to remove participant');
        const room = await res.json();
        setRooms((prev) => prev.map((r) => (r.id === roomId ? room : r)));
        return room;
    }, [backendUrl, apiKey]);
    const sendMessage = useCallback(async (roomId, content, senderName) => {
        const res = await fetch(`${backendUrl}/v1/teams/rooms/${roomId}/message`, {
            method: 'POST',
            headers: headers(apiKey),
            body: JSON.stringify({ content, sender_name: senderName || 'You' }),
        });
        if (!res.ok)
            throw new Error('Failed to send message');
        const room = await res.json();
        setRooms((prev) => prev.map((r) => (r.id === roomId ? room : r)));
        return room;
    }, [backendUrl, apiKey]);
    const getRoom = useCallback(async (roomId) => {
        const res = await fetch(`${backendUrl}/v1/teams/rooms/${roomId}`, {
            headers: headers(apiKey),
        });
        if (!res.ok)
            throw new Error('Room not found');
        return await res.json();
    }, [backendUrl, apiKey]);
    /** Trigger persona turns after a human message was sent (round-robin legacy). */
    const runTurn = useCallback(async (roomId, humanName) => {
        const llm = readLLMSettings();
        const res = await fetch(`${backendUrl}/v1/teams/rooms/${roomId}/run-turn`, {
            method: 'POST',
            headers: headers(apiKey),
            body: JSON.stringify({
                human_name: humanName || 'You',
                ...llm,
            }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
            throw new Error(err.detail || 'Failed to run turn');
        }
        const data = await res.json();
        const room = data.room;
        setRooms((prev) => prev.map((r) => (r.id === roomId ? room : r)));
        return room;
    }, [backendUrl, apiKey]);
    /** Reactive step: intent scoring + only relevant speakers respond. */
    const reactStep = useCallback(async (roomId) => {
        const llm = readLLMSettings();
        const res = await fetch(`${backendUrl}/v1/teams/rooms/${roomId}/react`, {
            method: 'POST',
            headers: headers(apiKey),
            body: JSON.stringify(llm),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
            throw new Error(err.detail || 'React step failed');
        }
        const data = await res.json();
        const room = data.room;
        setRooms((prev) => prev.map((r) => (r.id === roomId ? room : r)));
        return room;
    }, [backendUrl, apiKey]);
    /** Preview next turn (dry-run: who would speak, with scores + reasons). */
    const previewTurn = useCallback(async (roomId) => {
        const res = await fetch(`${backendUrl}/v1/teams/rooms/${roomId}/preview-turn`, {
            headers: headers(apiKey),
        });
        if (!res.ok)
            throw new Error('Failed to preview turn');
        return await res.json();
    }, [backendUrl, apiKey]);
    /** Call on a specific persona to speak next (moderated mode). */
    const callOn = useCallback(async (roomId, personaId) => {
        await fetch(`${backendUrl}/v1/teams/rooms/${roomId}/moderation/call-on`, {
            method: 'POST',
            headers: headers(apiKey),
            body: JSON.stringify({ persona_id: personaId }),
        });
    }, [backendUrl, apiKey]);
    /** Toggle hand-raise for a persona. */
    const toggleHandRaise = useCallback(async (roomId, personaId) => {
        await fetch(`${backendUrl}/v1/teams/rooms/${roomId}/hand-raise/${personaId}`, {
            method: 'POST',
            headers: headers(apiKey),
        });
    }, [backendUrl, apiKey]);
    // ── Play Mode API ────────────────────────────────────────────────────
    /** Start autonomous Play Mode for a room. */
    const startPlayMode = useCallback(async (roomId, opts = {}) => {
        const llm = readLLMSettings();
        const res = await fetch(`${backendUrl}/v1/teams/rooms/${roomId}/play-mode/start`, {
            method: 'POST',
            headers: headers(apiKey),
            body: JSON.stringify({ ...opts, ...llm }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
            throw new Error(err.detail || 'Failed to start play mode');
        }
        return await res.json();
    }, [backendUrl, apiKey]);
    /** Stop Play Mode. */
    const stopPlayMode = useCallback(async (roomId) => {
        const res = await fetch(`${backendUrl}/v1/teams/rooms/${roomId}/play-mode/stop`, {
            method: 'POST',
            headers: headers(apiKey),
        });
        if (!res.ok)
            throw new Error('Failed to stop play mode');
        return await res.json();
    }, [backendUrl, apiKey]);
    /** Pause Play Mode. */
    const pausePlayMode = useCallback(async (roomId) => {
        const res = await fetch(`${backendUrl}/v1/teams/rooms/${roomId}/play-mode/pause`, {
            method: 'POST',
            headers: headers(apiKey),
        });
        if (!res.ok)
            throw new Error('Failed to pause play mode');
        return await res.json();
    }, [backendUrl, apiKey]);
    /** Resume Play Mode. */
    const resumePlayMode = useCallback(async (roomId) => {
        const res = await fetch(`${backendUrl}/v1/teams/rooms/${roomId}/play-mode/resume`, {
            method: 'POST',
            headers: headers(apiKey),
        });
        if (!res.ok)
            throw new Error('Failed to resume play mode');
        return await res.json();
    }, [backendUrl, apiKey]);
    /** Get Play Mode status. */
    const getPlayStatus = useCallback(async (roomId) => {
        const res = await fetch(`${backendUrl}/v1/teams/rooms/${roomId}/play-mode/status`, {
            headers: headers(apiKey),
        });
        if (!res.ok)
            throw new Error('Failed to get play status');
        return await res.json();
    }, [backendUrl, apiKey]);
    /** Toggle mute for a persona (muted personas are skipped by orchestrator). */
    const toggleMute = useCallback(async (roomId, personaId) => {
        await fetch(`${backendUrl}/v1/teams/rooms/${roomId}/mute/${personaId}`, {
            method: 'POST',
            headers: headers(apiKey),
        });
    }, [backendUrl, apiKey]);
    return {
        rooms,
        loading,
        error,
        refresh: fetchRooms,
        createRoom,
        deleteRoom,
        updateRoom,
        addParticipant,
        removeParticipant,
        sendMessage,
        runTurn,
        reactStep,
        previewTurn,
        callOn,
        toggleHandRaise,
        toggleMute,
        getRoom,
        // Play Mode
        startPlayMode,
        stopPlayMode,
        pausePlayMode,
        resumePlayMode,
        getPlayStatus,
    };
}
