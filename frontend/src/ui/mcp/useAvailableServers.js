/**
 * Hook for fetching MCP server availability and managing install/uninstall.
 *
 * Calls GET /v1/agentic/servers/available for the full server list,
 * POST /v1/agentic/servers/{id}/install and /uninstall for lifecycle.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
export function useAvailableServers({ backendUrl, apiKey }) {
    const [servers, setServers] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [actionLoading, setActionLoading] = useState({});
    const headers = useMemo(() => {
        const h = {};
        if (apiKey)
            h['x-api-key'] = apiKey;
        return h;
    }, [apiKey]);
    const fetchServers = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const res = await fetch(`${backendUrl}/v1/agentic/servers/available`, { headers });
            if (!res.ok)
                throw new Error(`HTTP ${res.status}`);
            const data = (await res.json());
            setServers(data);
        }
        catch (e) {
            setServers([]);
            setError(e?.message || 'Failed to load servers');
        }
        finally {
            setLoading(false);
        }
    }, [backendUrl, headers]);
    useEffect(() => {
        void fetchServers();
    }, [fetchServers]);
    const install = useCallback(async (serverId) => {
        setActionLoading((p) => ({ ...p, [serverId]: true }));
        try {
            const res = await fetch(`${backendUrl}/v1/agentic/servers/${serverId}/install`, {
                method: 'POST',
                headers: { ...headers, 'Content-Type': 'application/json' },
            });
            const data = await res.json();
            if (!res.ok)
                return { ok: false, error: data?.detail || `HTTP ${res.status}` };
            // Refresh the server list after install
            await fetchServers();
            return { ok: true, tools_discovered: data?.tools_discovered ?? 0 };
        }
        catch (e) {
            return { ok: false, error: e?.message || 'Install failed' };
        }
        finally {
            setActionLoading((p) => ({ ...p, [serverId]: false }));
        }
    }, [backendUrl, headers, fetchServers]);
    const uninstall = useCallback(async (serverId) => {
        setActionLoading((p) => ({ ...p, [serverId]: true }));
        try {
            const res = await fetch(`${backendUrl}/v1/agentic/servers/${serverId}/uninstall`, {
                method: 'POST',
                headers: { ...headers, 'Content-Type': 'application/json' },
            });
            const data = await res.json();
            if (!res.ok)
                return { ok: false, error: data?.detail || `HTTP ${res.status}` };
            await fetchServers();
            return { ok: true };
        }
        catch (e) {
            return { ok: false, error: e?.message || 'Uninstall failed' };
        }
        finally {
            setActionLoading((p) => ({ ...p, [serverId]: false }));
        }
    }, [backendUrl, headers, fetchServers]);
    /** Fetch uninstall preview for an external server (shows affected personas). */
    const previewUninstallExternal = useCallback(async (serverName) => {
        try {
            const res = await fetch(`${backendUrl}/v1/agentic/servers/external/${encodeURIComponent(serverName)}/uninstall-preview`, { headers });
            if (!res.ok)
                return null;
            return (await res.json());
        }
        catch {
            return null;
        }
    }, [backendUrl, headers]);
    /** Uninstall an external server (full lifecycle with dependency awareness). */
    const uninstallExternal = useCallback(async (serverName) => {
        setActionLoading((p) => ({ ...p, [serverName]: true }));
        try {
            const res = await fetch(`${backendUrl}/v1/agentic/servers/external/${encodeURIComponent(serverName)}/uninstall`, { method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' } });
            const data = await res.json();
            if (!res.ok)
                return { ok: false, error: data?.detail || `HTTP ${res.status}` };
            await fetchServers();
            return { ok: true, personas_affected: data?.personas_affected, tools_deactivated: data?.tools_deactivated };
        }
        catch (e) {
            return { ok: false, error: e?.message || 'Uninstall failed' };
        }
        finally {
            setActionLoading((p) => ({ ...p, [serverName]: false }));
        }
    }, [backendUrl, headers, fetchServers]);
    /** Reinstall a previously uninstalled external server (re-start + re-register tools). */
    const reinstallExternal = useCallback(async (serverName) => {
        setActionLoading((p) => ({ ...p, [serverName]: true }));
        try {
            const res = await fetch(`${backendUrl}/v1/agentic/servers/external/${encodeURIComponent(serverName)}/reinstall`, { method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' } });
            const data = await res.json();
            if (!res.ok)
                return { ok: false, error: data?.detail || `HTTP ${res.status}` };
            await fetchServers();
            return { ok: true, tools_discovered: data?.tools_discovered ?? 0 };
        }
        catch (e) {
            return { ok: false, error: e?.message || 'Reinstall failed' };
        }
        finally {
            setActionLoading((p) => ({ ...p, [serverName]: false }));
        }
    }, [backendUrl, headers, fetchServers]);
    /** Restart a stopped external server without reinstalling. */
    const restartExternal = useCallback(async (serverName) => {
        setActionLoading((p) => ({ ...p, [serverName]: true }));
        try {
            const res = await fetch(`${backendUrl}/v1/agentic/servers/external/${encodeURIComponent(serverName)}/restart`, { method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' } });
            const data = await res.json();
            if (!res.ok)
                return { ok: false, error: data?.detail || `HTTP ${res.status}` };
            await fetchServers();
            return { ok: true };
        }
        catch (e) {
            return { ok: false, error: e?.message || 'Restart failed' };
        }
        finally {
            setActionLoading((p) => ({ ...p, [serverName]: false }));
        }
    }, [backendUrl, headers, fetchServers]);
    /** Fetch config schema and current values for a server. */
    const getServerConfig = useCallback(async (serverId) => {
        try {
            const res = await fetch(`${backendUrl}/v1/agentic/servers/${encodeURIComponent(serverId)}/config`, { headers });
            if (!res.ok)
                return null;
            return await res.json();
        }
        catch {
            return null;
        }
    }, [backendUrl, headers]);
    /** Save config and restart server. */
    const saveServerConfig = useCallback(async (serverId, fields) => {
        try {
            const res = await fetch(`${backendUrl}/v1/agentic/servers/${encodeURIComponent(serverId)}/config`, {
                method: 'POST',
                headers: { ...headers, 'Content-Type': 'application/json' },
                body: JSON.stringify({ fields }),
            });
            const data = await res.json();
            if (!res.ok)
                return { ok: false, error: data?.detail || `HTTP ${res.status}` };
            await fetchServers();
            return { ok: true };
        }
        catch (e) {
            return { ok: false, error: e?.message || 'Save failed' };
        }
    }, [backendUrl, headers, fetchServers]);
    const counts = useMemo(() => {
        const core = servers.filter((s) => s.is_core);
        const optional = servers.filter((s) => !s.is_core && s.source_type !== 'external');
        const external = servers.filter((s) => s.source_type === 'external');
        const running = servers.filter((s) => s.healthy);
        const installed = optional.filter((s) => s.installed);
        const externalInstalled = external.filter((s) => s.installed);
        return {
            total: servers.length,
            core: core.length,
            optional: optional.length,
            external: external.length,
            externalInstalled: externalInstalled.length,
            running: running.length,
            installed: installed.length,
        };
    }, [servers]);
    return {
        servers,
        counts,
        loading,
        error,
        refresh: fetchServers,
        install,
        uninstall,
        uninstallExternal,
        reinstallExternal,
        restartExternal,
        previewUninstallExternal,
        getServerConfig,
        saveServerConfig,
        actionLoading,
    };
}
