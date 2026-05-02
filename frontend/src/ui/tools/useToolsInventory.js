/**
 * Hook that wraps useAgenticCatalog and provides a unified capabilities view.
 *
 * Merges catalog.tools + catalog.a2a_agents into a single CapabilityItem[]
 * list with search, status, and type filtering.
 */
import { useMemo, useState } from 'react';
import { useAgenticCatalog } from '../../agentic/useAgenticCatalog';
import { deriveStatus } from './ToolStatusBadge';
export function useToolsInventory({ backendUrl, apiKey }) {
    const { catalog, loading, error, refresh } = useAgenticCatalog({
        backendUrl,
        apiKey,
        enabled: true,
    });
    const [search, setSearch] = useState('');
    const [statusFilter, setStatusFilter] = useState('all');
    const [typeFilter, setTypeFilter] = useState('all');
    /* Build unified list from both sources */
    const allItems = useMemo(() => {
        const toolItems = (catalog?.tools || [])
            .filter((t) => t.id && t.name)
            .map((t) => ({ kind: 'tool', data: t }));
        const a2aItems = (catalog?.a2a_agents || [])
            .filter((a) => a.id && a.name)
            .map((a) => ({ kind: 'a2a_agent', data: a }));
        return [...toolItems, ...a2aItems];
    }, [catalog?.tools, catalog?.a2a_agents]);
    /* Filtered list */
    const items = useMemo(() => {
        let filtered = allItems;
        // Type filter
        if (typeFilter !== 'all') {
            const kind = typeFilter === 'a2a' ? 'a2a_agent' : 'tool';
            filtered = filtered.filter((item) => item.kind === kind);
        }
        // Search filter
        if (search.trim()) {
            const q = search.toLowerCase();
            filtered = filtered.filter((item) => {
                const d = item.data;
                const searchable = `${d.name} ${d.description || ''} ${d.id} ${item.kind === 'a2a_agent' && 'endpoint_url' in d ? d.endpoint_url || '' : ''}`;
                return searchable.toLowerCase().includes(q);
            });
        }
        // Status filter
        if (statusFilter !== 'all') {
            filtered = filtered.filter((item) => deriveStatus(item.data.enabled) === statusFilter);
        }
        return filtered;
    }, [allItems, search, statusFilter, typeFilter]);
    /* Counts */
    const counts = useMemo(() => {
        const tools = (catalog?.tools || []);
        const a2a = (catalog?.a2a_agents || []);
        return {
            total: tools.length + a2a.length,
            tools: {
                total: tools.length,
                active: tools.filter((t) => t.enabled === true).length,
                inactive: tools.filter((t) => t.enabled === false).length,
            },
            a2a: {
                total: a2a.length,
                active: a2a.filter((a) => a.enabled === true).length,
                inactive: a2a.filter((a) => a.enabled === false).length,
            },
            active: tools.filter((t) => t.enabled === true).length + a2a.filter((a) => a.enabled === true).length,
            inactive: tools.filter((t) => t.enabled === false).length + a2a.filter((a) => a.enabled === false).length,
        };
    }, [catalog?.tools, catalog?.a2a_agents]);
    return {
        items,
        counts,
        loading,
        error,
        refresh,
        search,
        setSearch,
        statusFilter,
        setStatusFilter,
        typeFilter,
        setTypeFilter,
        forgeHealthy: catalog?.forge?.healthy ?? null,
    };
}
