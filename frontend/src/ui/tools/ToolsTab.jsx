import React, { useState } from 'react';
import { Search, RefreshCw, Filter } from 'lucide-react';
import { useToolsInventory } from './useToolsInventory';
import { ToolsGrid } from './ToolsGrid';
import { ToolsEmptyState } from './ToolsEmptyState';
import { ToolDetailDrawer } from './ToolDetailDrawer';
const TYPE_BUTTONS = [
    { value: 'all', label: 'All' },
    { value: 'tool', label: 'Tools' },
    { value: 'a2a', label: 'A2A Agents' },
];
export function ToolsTab({ backendUrl, apiKey, onGoToMcpServers }) {
    const { items, counts, loading, error, refresh, search, setSearch, statusFilter, setStatusFilter, typeFilter, setTypeFilter, forgeHealthy, } = useToolsInventory({ backendUrl, apiKey });
    const [selectedItem, setSelectedItem] = useState(null);
    const [refreshing, setRefreshing] = useState(false);
    const handleRefresh = async () => {
        setRefreshing(true);
        try {
            await refresh();
        }
        finally {
            setRefreshing(false);
        }
    };
    const hasItems = !loading && !error && items.length > 0;
    const showEmpty = !loading && !error && items.length === 0 && !search && statusFilter === 'all' && typeFilter === 'all';
    return (<div className="space-y-4">
      {/* Stats bar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4 flex-wrap">
          {/* Total capabilities */}
          <div className="flex items-center gap-2">
            <span className="text-sm text-white/50">Total</span>
            <span className="text-sm font-semibold text-white">{counts.total}</span>
          </div>
          <div className="w-px h-4 bg-white/10"/>

          {/* Tools count */}
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-blue-400"/>
            <span className="text-sm text-white/50">Tools</span>
            <span className="text-sm font-semibold text-blue-300">{counts.tools.total}</span>
          </div>

          {/* A2A count */}
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-violet-400"/>
            <span className="text-sm text-white/50">A2A</span>
            <span className="text-sm font-semibold text-violet-300">{counts.a2a.total}</span>
          </div>

          <div className="w-px h-4 bg-white/10"/>

          {/* Active / Inactive */}
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"/>
            <span className="text-sm text-white/50">Active</span>
            <span className="text-sm font-semibold text-emerald-300">{counts.active}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-yellow-400"/>
            <span className="text-sm text-white/50">Inactive</span>
            <span className="text-sm font-semibold text-yellow-300">{counts.inactive}</span>
          </div>

          {/* Forge status */}
          {forgeHealthy !== null && (<>
              <div className="w-px h-4 bg-white/10"/>
              <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${forgeHealthy
                ? 'bg-emerald-500/20 text-emerald-300'
                : 'bg-red-500/20 text-red-300'}`}>
                Forge {forgeHealthy ? 'Online' : 'Offline'}
              </span>
            </>)}
        </div>

        <button onClick={handleRefresh} disabled={refreshing} className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium text-white/60 hover:text-white bg-white/5 hover:bg-white/10 rounded-lg transition-colors disabled:opacity-50">
          <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''}/>
          Refresh
        </button>
      </div>

      {/* Search + filter bar */}
      {(counts.total > 0 || search || statusFilter !== 'all' || typeFilter !== 'all') && (<div className="flex items-center gap-3">
          <div className="flex-1 relative">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30"/>
            <input type="text" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search by name, description, or ID..." className="w-full bg-white/5 border border-white/10 rounded-xl pl-10 pr-4 py-2.5 text-sm text-white placeholder-white/30 focus:outline-none focus:border-purple-500/50 transition-colors"/>
          </div>

          {/* Type filter */}
          <div className="flex items-center gap-1 bg-white/5 border border-white/10 rounded-xl p-1">
            {TYPE_BUTTONS.map((t) => (<button key={t.value} onClick={() => setTypeFilter(t.value)} className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${typeFilter === t.value
                    ? 'bg-white/10 text-white'
                    : 'text-white/40 hover:text-white/60'}`}>
                {t.label}
              </button>))}
          </div>

          {/* Status filter */}
          <div className="flex items-center gap-1 bg-white/5 border border-white/10 rounded-xl p-1">
            {['all', 'active', 'inactive'].map((s) => (<button key={s} onClick={() => setStatusFilter(s)} className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors capitalize ${statusFilter === s
                    ? 'bg-white/10 text-white'
                    : 'text-white/40 hover:text-white/60'}`}>
                {s}
              </button>))}
          </div>
        </div>)}

      {/* Content */}
      {loading && <ToolsEmptyState loading/>}
      {error && <ToolsEmptyState error={error}/>}
      {showEmpty && <ToolsEmptyState onGoToMcpServers={onGoToMcpServers}/>}

      {!loading && !error && items.length === 0 && (search || statusFilter !== 'all' || typeFilter !== 'all') && !showEmpty && (<div className="flex flex-col items-center justify-center h-40 text-white/40">
          <Filter size={32} className="mb-3 opacity-30"/>
          <p className="text-sm">No capabilities match your search or filters.</p>
        </div>)}

      {hasItems && (<ToolsGrid items={items} onSelect={setSelectedItem}/>)}

      {/* Detail drawer */}
      {selectedItem && (<ToolDetailDrawer item={selectedItem} onClose={() => setSelectedItem(null)}/>)}
    </div>);
}
