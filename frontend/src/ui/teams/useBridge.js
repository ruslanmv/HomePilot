/**
 * useBridge — React hook for Teams meeting bridge operations.
 *
 * Provides functions to:
 *   - Connect a room to a Teams meeting (paste join URL)
 *   - Disconnect
 *   - Poll bridge status
 *   - Toggle voice detection (STT)
 *   - Send persona messages to Teams chat
 */
import { useState, useCallback, useRef, useEffect } from 'react';
function headers(apiKey) {
    const h = { 'Content-Type': 'application/json' };
    if (apiKey)
        h['x-api-key'] = apiKey;
    return h;
}
export function useBridge({ backendUrl, apiKey, roomId, statusPollInterval = 0 }) {
    const [status, setStatus] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const pollRef = useRef(null);
    // ── Fetch status ─────────────────────────────────────────────────────
    const fetchStatus = useCallback(async (rid) => {
        const id = rid || roomId;
        if (!id)
            return null;
        try {
            const res = await fetch(`${backendUrl}/v1/teams/bridge/status/${id}`, {
                headers: headers(apiKey),
            });
            if (!res.ok)
                throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            setStatus(data);
            return data;
        }
        catch (e) {
            // Not connected is normal
            setStatus({ room_id: id, connected: false, status: 'not_connected' });
            return null;
        }
    }, [backendUrl, apiKey, roomId]);
    // ── Auto-poll status ─────────────────────────────────────────────────
    useEffect(() => {
        if (!roomId || !statusPollInterval)
            return;
        fetchStatus();
        pollRef.current = setInterval(() => fetchStatus(), statusPollInterval);
        return () => {
            if (pollRef.current)
                clearInterval(pollRef.current);
        };
    }, [roomId, statusPollInterval, fetchStatus]);
    // ── Connect ──────────────────────────────────────────────────────────
    const connect = useCallback(async (params) => {
        setLoading(true);
        setError(null);
        try {
            const res = await fetch(`${backendUrl}/v1/teams/bridge/connect`, {
                method: 'POST',
                headers: headers(apiKey),
                body: JSON.stringify(params),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
                throw new Error(err.detail || 'Failed to connect');
            }
            const data = await res.json();
            setStatus(data);
            return data;
        }
        catch (e) {
            setError(e.message);
            throw e;
        }
        finally {
            setLoading(false);
        }
    }, [backendUrl, apiKey]);
    // ── Disconnect ───────────────────────────────────────────────────────
    const disconnect = useCallback(async (rid) => {
        const id = rid || roomId;
        if (!id)
            return;
        setLoading(true);
        try {
            await fetch(`${backendUrl}/v1/teams/bridge/disconnect/${id}`, {
                method: 'POST',
                headers: headers(apiKey),
            });
            setStatus({ room_id: id, connected: false, status: 'disconnected' });
        }
        catch (e) {
            setError(e.message);
        }
        finally {
            setLoading(false);
        }
    }, [backendUrl, apiKey, roomId]);
    // ── Voice toggle ─────────────────────────────────────────────────────
    const toggleVoice = useCallback(async (enabled, rid) => {
        const id = rid || roomId;
        if (!id)
            return;
        try {
            const res = await fetch(`${backendUrl}/v1/teams/bridge/voice/${id}`, {
                method: 'POST',
                headers: headers(apiKey),
                body: JSON.stringify({ enabled }),
            });
            if (!res.ok)
                throw new Error('Failed to toggle voice');
            // Refresh status
            await fetchStatus(id);
        }
        catch (e) {
            setError(e.message);
        }
    }, [backendUrl, apiKey, roomId, fetchStatus]);
    // ── Send to Teams ────────────────────────────────────────────────────
    const sendToMeeting = useCallback(async (senderName, content, rid) => {
        const id = rid || roomId;
        if (!id)
            return;
        try {
            await fetch(`${backendUrl}/v1/teams/bridge/send/${id}`, {
                method: 'POST',
                headers: headers(apiKey),
                body: JSON.stringify({ sender_name: senderName, content }),
            });
        }
        catch (e) {
            setError(e.message);
        }
    }, [backendUrl, apiKey, roomId]);
    // ── Check MCP server availability ───────────────────────────────
    const checkMcpAvailable = useCallback(async (mcpBaseUrl = 'http://localhost:9106') => {
        try {
            const res = await fetch(`${backendUrl}/v1/teams/bridge/health?mcp_base_url=${encodeURIComponent(mcpBaseUrl)}`, { headers: headers(apiKey) });
            if (!res.ok)
                return false;
            const data = await res.json();
            return !!data.available;
        }
        catch {
            return false;
        }
    }, [backendUrl, apiKey]);
    return {
        status,
        loading,
        error,
        connect,
        disconnect,
        toggleVoice,
        sendToMeeting,
        fetchStatus,
        checkMcpAvailable,
    };
}
// ---------------------------------------------------------------------------
// Standalone hook: is the Teams MCP server available?
// ---------------------------------------------------------------------------
/**
 * Event name dispatched by the MCP server management panel after
 * install / uninstall so listeners can immediately re-check availability.
 */
export const MCP_SERVERS_CHANGED_EVENT = 'homepilot:mcp-servers-changed';
/**
 * useTeamsMcpAvailable — auto-detection for Teams MCP server.
 *
 * Probes the backend bridge health endpoint on mount.  If the server
 * is installed and healthy, `available` becomes true and the Teams tab
 * appears automatically — no manual toggle needed.
 *
 * Polling behaviour:
 *   - **Always:** checks once on mount and re-checks immediately when
 *     the MCP server panel dispatches `homepilot:mcp-servers-changed`.
 *   - **Only when `active` is true:** polls every 15 s so the Teams
 *     view stays up-to-date while the user is looking at it.
 *   - When the user switches away from the Teams tab, polling stops
 *     to avoid noisy background requests.
 */
export function useTeamsMcpAvailable(backendUrl, apiKey, active = false) {
    const [available, setAvailable] = useState(false);
    const [checking, setChecking] = useState(true);
    useEffect(() => {
        let cancelled = false;
        const check = async () => {
            try {
                const h = {};
                if (apiKey)
                    h['x-api-key'] = apiKey;
                const res = await fetch(`${backendUrl}/v1/teams/bridge/health`, { headers: h });
                if (!res.ok) {
                    if (!cancelled)
                        setAvailable(false);
                    return;
                }
                const data = await res.json();
                if (!cancelled)
                    setAvailable(!!data.available);
            }
            catch {
                if (!cancelled)
                    setAvailable(false);
            }
            finally {
                if (!cancelled)
                    setChecking(false);
            }
        };
        // Always check once on mount / dependency change
        check();
        // Only poll while the Teams tab is active
        let interval;
        if (active) {
            interval = setInterval(check, 15_000);
        }
        // Re-check immediately when the MCP server panel signals a change
        const onServersChanged = () => { check(); };
        window.addEventListener(MCP_SERVERS_CHANGED_EVENT, onServersChanged);
        return () => {
            cancelled = true;
            if (interval)
                clearInterval(interval);
            window.removeEventListener(MCP_SERVERS_CHANGED_EVENT, onServersChanged);
        };
    }, [backendUrl, apiKey, active]);
    return { available, checking };
}
