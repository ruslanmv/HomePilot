/**
 * Optional marketplace search panel.
 *
 * Queries the HomePilot backend `/v1/marketplace/search` endpoint which
 * proxies to Matrix Hub.  If the marketplace is not available, shows a
 * friendly "coming soon" placeholder.
 *
 * The backend marketplace module is feature-flagged via MARKETPLACE_ENABLED.
 */
import React, { useState, useCallback, useEffect, useRef } from 'react';
import { Search, Download, Globe, AlertCircle } from 'lucide-react';
export function MarketplaceSearch({ backendUrl, apiKey, onInstalled }) {
    const [query, setQuery] = useState('');
    const [results, setResults] = useState([]);
    const [searching, setSearching] = useState(false);
    const [available, setAvailable] = useState(null);
    const [error, setError] = useState(null);
    const [installing, setInstalling] = useState(null);
    const debounceRef = useRef();
    const headers = useCallback(() => {
        const h = {};
        if (apiKey)
            h['x-api-key'] = apiKey;
        return h;
    }, [apiKey]);
    // Check marketplace availability on mount
    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const res = await fetch(`${backendUrl}/v1/marketplace/status`, { headers: headers() });
                if (!cancelled) {
                    setAvailable(res.ok);
                }
            }
            catch {
                if (!cancelled)
                    setAvailable(false);
            }
        })();
        return () => { cancelled = true; };
    }, [backendUrl, headers]);
    const doSearch = useCallback(async (q) => {
        if (!q.trim()) {
            setResults([]);
            return;
        }
        setSearching(true);
        setError(null);
        try {
            const res = await fetch(`${backendUrl}/v1/marketplace/search?q=${encodeURIComponent(q)}&type=mcp_server&limit=10`, { headers: headers() });
            if (!res.ok)
                throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            setResults(data.results || []);
        }
        catch (e) {
            setError(e?.message || 'Search failed');
            setResults([]);
        }
        finally {
            setSearching(false);
        }
    }, [backendUrl, headers]);
    // Debounced search
    const handleSearchChange = (value) => {
        setQuery(value);
        clearTimeout(debounceRef.current);
        debounceRef.current = setTimeout(() => doSearch(value), 350);
    };
    const handleInstall = async (item) => {
        if (!item.install_url)
            return;
        setInstalling(item.id);
        try {
            const res = await fetch(`${backendUrl}/v1/marketplace/install`, {
                method: 'POST',
                headers: { ...headers(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ entity_id: item.id }),
            });
            if (!res.ok) {
                const data = await res.json().catch(() => ({}));
                throw new Error(data.detail || `HTTP ${res.status}`);
            }
            onInstalled();
        }
        catch (e) {
            setError(e?.message || 'Install failed');
        }
        finally {
            setInstalling(null);
        }
    };
    // Marketplace not available
    if (available === false) {
        return (<div className="rounded-2xl border border-white/10 bg-white/5 p-6">
        <div className="flex items-center gap-3 mb-3">
          <Globe size={20} className="text-purple-400"/>
          <h3 className="text-sm font-semibold text-white">MCP Marketplace</h3>
          <span className="text-xs px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 font-medium">
            Coming Soon
          </span>
        </div>
        <p className="text-sm text-white/50">
          The Matrix Hub marketplace will allow you to discover and install MCP servers from a shared directory.
          This feature is currently in development.
        </p>
      </div>);
    }
    // Marketplace available — show search UI
    return (<div className="rounded-2xl border border-white/10 bg-white/5 p-6 space-y-4">
      <div className="flex items-center gap-3 mb-1">
        <Globe size={20} className="text-purple-400"/>
        <h3 className="text-sm font-semibold text-white">Find MCP Servers</h3>
      </div>

      {/* Search input */}
      <div className="relative">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30"/>
        <input type="text" value={query} onChange={(e) => handleSearchChange(e.target.value)} placeholder="Search Matrix Hub for MCP servers..." className="w-full bg-white/5 border border-white/10 rounded-xl pl-10 pr-4 py-2.5 text-sm text-white placeholder-white/30 focus:outline-none focus:border-purple-500/50 transition-colors"/>
      </div>

      {/* Results */}
      {searching && (<div className="flex items-center gap-2 text-white/40 text-sm py-4">
          <div className="w-4 h-4 border-2 border-white/20 border-t-purple-400 rounded-full animate-spin"/>
          Searching...
        </div>)}

      {error && (<div className="flex items-center gap-2 text-red-400 text-sm">
          <AlertCircle size={14}/>
          {error}
        </div>)}

      {!searching && results.length > 0 && (<div className="space-y-2 max-h-80 overflow-y-auto">
          {results.map((item) => (<div key={item.id} className="flex items-center justify-between p-4 rounded-xl bg-white/5 border border-white/10 hover:border-white/20 transition-colors">
              <div className="min-w-0 flex-1 mr-4">
                <h4 className="text-sm font-medium text-white truncate">{item.name}</h4>
                <p className="text-xs text-white/40 truncate">{item.description}</p>
                {item.author && (<p className="text-xs text-white/30 mt-1">by {item.author}</p>)}
              </div>
              <button onClick={() => handleInstall(item)} disabled={installing === item.id || !item.install_url} className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-purple-500/20 hover:bg-purple-500/30 text-purple-300 rounded-lg transition-colors disabled:opacity-50">
                {installing === item.id ? (<div className="w-3 h-3 border-2 border-purple-300/30 border-t-purple-300 rounded-full animate-spin"/>) : (<Download size={12}/>)}
                Install
              </button>
            </div>))}
        </div>)}

      {!searching && query && results.length === 0 && !error && (<p className="text-sm text-white/40 py-4 text-center">No servers found for &quot;{query}&quot;</p>)}
    </div>);
}
