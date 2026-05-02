/**
 * PersonaImportExport — Phase 4 (Enterprise MCP Auto-Install)
 *
 * Enhanced modal for importing .hpersona packages with MCP server auto-install:
 *   Step 0: Upload (drag-drop or file picker)
 *   Step 1: Preview + dependency check
 *   Step 2: MCP Server Installation (if external servers needed)
 *   Step 3: Install complete
 *
 * When a shared persona requires an external MCP server (e.g. hp-news):
 *   1. Dependency checker detects the missing server
 *   2. User sees a confirmation prompt: "This persona needs mcp-news. Install it?"
 *   3. On "Yes": clones from git → installs deps → starts server → syncs to Forge
 *   4. Real-time progress bars show each installation phase
 *   5. Once all servers are ready, persona project is created
 *
 * Also provides an export button component for project cards.
 */
import React, { useState, useCallback, useRef, useEffect } from 'react';
import { X, Upload, Package, Check, AlertTriangle, Download, ChevronLeft, ChevronRight, Wrench, Server, Bot, Image as ImageIcon, Shield, Cpu, HelpCircle, GitBranch, Loader2, ExternalLink, CheckCircle, XCircle, SkipForward, RefreshCw, } from 'lucide-react';
import { previewPersonaPackage, importPersonaPackage, importPersonaAtomic, exportPersona, resolvePersonaDeps, installPersonaDeps, } from './personaPortability';
// ---------------------------------------------------------------------------
// Status icon helper
// ---------------------------------------------------------------------------
function StatusIcon({ status }) {
    if (status === 'available')
        return <div className="w-5 h-5 rounded-full bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center"><Check size={12} className="text-emerald-400"/></div>;
    if (status === 'installable')
        return <div className="w-5 h-5 rounded-full bg-blue-500/20 border border-blue-500/40 flex items-center justify-center"><Download size={10} className="text-blue-400"/></div>;
    if (status === 'downloadable')
        return <div className="w-5 h-5 rounded-full bg-amber-500/20 border border-amber-500/40 flex items-center justify-center"><ExternalLink size={10} className="text-amber-400"/></div>;
    if (status === 'missing')
        return <div className="w-5 h-5 rounded-full bg-red-500/20 border border-red-500/40 flex items-center justify-center"><X size={12} className="text-red-400"/></div>;
    if (status === 'degraded')
        return <div className="w-5 h-5 rounded-full bg-amber-500/20 border border-amber-500/40 flex items-center justify-center"><AlertTriangle size={10} className="text-amber-400"/></div>;
    return <div className="w-5 h-5 rounded-full bg-white/10 border border-white/20 flex items-center justify-center"><HelpCircle size={10} className="text-white/40"/></div>;
}
function DependencyRow({ item }) {
    return (<div className="flex items-center gap-3 py-2 px-3 rounded-lg bg-white/[0.03] border border-white/[0.06]">
      <StatusIcon status={item.status}/>
      <div className="flex-1 min-w-0">
        <div className="text-sm text-white font-medium truncate">{item.name}</div>
        <div className="text-xs text-white/40 truncate">{item.detail || item.description}</div>
      </div>
      {item.source_type === 'builtin' && (<span className="text-[10px] px-2 py-0.5 rounded-full bg-purple-500/15 text-purple-300 border border-purple-500/20 shrink-0">
          Built-in
        </span>)}
      {item.source_type === 'community_bundle' && (<span className={`text-[10px] px-2 py-0.5 rounded-full shrink-0 ${item.status === 'available'
                ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/20'
                : item.status === 'installable'
                    ? 'bg-blue-500/15 text-blue-300 border border-blue-500/20'
                    : 'bg-amber-500/15 text-amber-300 border border-amber-500/20'}`}>
          {item.status === 'available' ? 'Installed' : item.status === 'installable' ? 'Ready' : 'Download'}
        </span>)}
      {item.source_type === 'registry' && (<span className={`text-[10px] px-2 py-0.5 rounded-full shrink-0 ${item.status === 'available'
                ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/20'
                : 'bg-cyan-500/15 text-cyan-300 border border-cyan-500/20'}`}>
          {item.status === 'available' ? 'Installed' : 'Discover'}
        </span>)}
      {item.source_type === 'external' && (<span className={`text-[10px] px-2 py-0.5 rounded-full shrink-0 ${item.status === 'available'
                ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/20'
                : item.status === 'downloadable'
                    ? 'bg-amber-500/15 text-amber-300 border border-amber-500/20'
                    : 'bg-red-500/15 text-red-300 border border-red-500/20'}`}>
          {item.status === 'available' ? 'Installed' : item.status === 'downloadable' ? 'Auto-install' : 'Missing'}
        </span>)}
    </div>);
}
// ---------------------------------------------------------------------------
// MCP Server Install Status Card
// ---------------------------------------------------------------------------
const PHASE_LABELS = {
    analyzing: 'Analyzing',
    cloning: 'Cloning from Git',
    registering: 'Registering',
    starting: 'Starting Server',
    discovering: 'Discovering Tools',
    syncing: 'Syncing to Forge',
    complete: 'Complete',
    failed: 'Failed',
    skipped: 'Already Installed',
};
function McpInstallCard({ status, backendUrl, apiKey, }) {
    const isComplete = status.phase === 'complete' || status.phase === 'skipped';
    const isFailed = status.phase === 'failed';
    const isActive = !isComplete && !isFailed;
    return (<div className={`p-4 rounded-xl border transition-all ${isComplete
            ? 'bg-emerald-500/[0.04] border-emerald-500/20'
            : isFailed
                ? 'bg-red-500/[0.04] border-red-500/20'
                : 'bg-white/[0.04] border-white/[0.08]'}`}>
      {/* Header */}
      <div className="flex items-center gap-3 mb-2">
        <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${isComplete
            ? 'bg-emerald-500/15 border border-emerald-500/30'
            : isFailed
                ? 'bg-red-500/15 border border-red-500/30'
                : 'bg-purple-500/15 border border-purple-500/30'}`}>
          {isComplete ? <CheckCircle size={16} className="text-emerald-400"/>
            : isFailed ? <XCircle size={16} className="text-red-400"/>
                : <Loader2 size={16} className="text-purple-400 animate-spin"/>}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-white truncate">{status.server_name}</div>
          <div className="text-[11px] text-white/40">
            {PHASE_LABELS[status.phase] || status.phase}
            {status.port && ` \u2022 Port ${status.port}`}
          </div>
        </div>
        {status.source_type && (<span className="text-[10px] px-2 py-0.5 rounded-full bg-white/5 border border-white/10 text-white/40 shrink-0">
            {status.source_type}
          </span>)}
      </div>

      {/* Progress bar */}
      {isActive && (<div className="mb-2">
          <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
            <div className="h-full bg-gradient-to-r from-purple-500 to-cyan-400 rounded-full transition-all duration-500" style={{ width: `${status.progress_pct}%` }}/>
          </div>
        </div>)}

      {/* Status message */}
      <div className={`text-xs leading-relaxed ${isFailed ? 'text-red-300' : isComplete ? 'text-emerald-300/70' : 'text-white/50'}`}>
        {isFailed ? status.error : status.message}
      </div>

      {/* Git URL */}
      {status.git_url && (<div className="flex items-center gap-1.5 mt-1.5 text-[10px] text-white/25">
          <GitBranch size={10}/>
          <span className="truncate">{status.git_url}</span>
        </div>)}

      {/* Tools discovered */}
      {isComplete && status.tools_discovered > 0 && (<div className="flex items-center gap-3 mt-2 text-[11px] text-white/40">
          <span>{status.tools_discovered} tools discovered</span>
          <span>{status.tools_registered} registered in Forge</span>
          {status.elapsed_ms > 0 && <span>{(status.elapsed_ms / 1000).toFixed(1)}s</span>}
        </div>)}

      {/* Install logs — show for failed installs so user can debug */}
      {isFailed && backendUrl && (<InstallLogViewer backendUrl={backendUrl} apiKey={apiKey} serverName={status.server_name} active={false}/>)}
    </div>);
}
function InstallLogViewer({ backendUrl, apiKey, serverName, active, }) {
    const [logs, setLogs] = useState([]);
    const [expanded, setExpanded] = useState(false);
    const sinceRef = useRef(0);
    const scrollRef = useRef(null);
    useEffect(() => {
        let cancelled = false;
        const fetchLogs = async () => {
            try {
                const headers = {};
                if (apiKey)
                    headers['x-api-key'] = apiKey;
                const res = await fetch(`${backendUrl}/v1/agentic/servers/install-logs?server=${encodeURIComponent(serverName)}&since=${sinceRef.current}`, { headers });
                if (res.ok) {
                    const data = await res.json();
                    const newLogs = data.logs || [];
                    if (newLogs.length > 0) {
                        sinceRef.current += newLogs.length;
                        setLogs((prev) => [...prev, ...newLogs].slice(-100));
                        requestAnimationFrame(() => {
                            scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
                        });
                    }
                }
            }
            catch {
                // non-critical
            }
            // If active, keep polling; otherwise one-time fetch
            if (!cancelled && active) {
                setTimeout(fetchLogs, 1500);
            }
        };
        fetchLogs();
        return () => { cancelled = true; };
    }, [active, backendUrl, apiKey, serverName]);
    if (logs.length === 0 && !active)
        return null;
    const visibleLogs = expanded ? logs : logs.slice(-5);
    const levelColor = (level) => {
        if (level === 'error')
            return 'text-red-400';
        if (level === 'warning')
            return 'text-amber-400';
        if (level === 'debug')
            return 'text-white/20';
        return 'text-white/40';
    };
    return (<div className="mt-2">
      <button onClick={() => setExpanded(!expanded)} className="text-[10px] text-white/30 hover:text-white/50 transition-colors mb-1">
        {expanded ? 'Hide' : 'Show'} install logs ({logs.length} entries)
      </button>
      {(expanded || logs.length <= 5) && (<div ref={scrollRef} className="bg-black/30 border border-white/5 rounded-lg p-2 max-h-40 overflow-y-auto font-mono text-[10px] leading-relaxed custom-scrollbar">
          {visibleLogs.map((log, i) => (<div key={i} className={`flex gap-2 ${levelColor(log.level)}`}>
              <span className="text-white/15 shrink-0">{log.phase}</span>
              <span className="break-all">{log.message}</span>
            </div>))}
          {logs.length === 0 && active && (<div className="text-white/20 italic">Waiting for install logs...</div>)}
        </div>)}
    </div>);
}
// ---------------------------------------------------------------------------
// Step breadcrumb
// ---------------------------------------------------------------------------
function StepBreadcrumb({ step, totalSteps }) {
    const labels = totalSteps === 4
        ? ['Upload', 'Preview', 'MCP Servers', 'Install']
        : ['Upload', 'Preview', 'Install'];
    return (<div className="flex items-center gap-2">
      {labels.map((label, i) => (<React.Fragment key={label}>
          {i > 0 && <ChevronRight size={12} className="text-white/20"/>}
          <span className={`text-xs font-medium ${i === step ? 'text-purple-300' : i < step ? 'text-emerald-400' : 'text-white/30'}`}>
            {i < step ? '\u2713 ' : ''}{label}
          </span>
        </React.Fragment>))}
    </div>);
}
// ---------------------------------------------------------------------------
// Import Modal
// ---------------------------------------------------------------------------
export function PersonaImportModal({ onClose, onImported, backendUrl, apiKey, }) {
    const [step, setStep] = useState(0);
    const [file, setFile] = useState(null);
    const [isDragging, setIsDragging] = useState(false);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [preview, setPreview] = useState(null);
    const [importing, setImporting] = useState(false);
    const [importedProject, setImportedProject] = useState(null);
    const [memoryMode, setMemoryMode] = useState('adaptive');
    const fileInputRef = useRef(null);
    // MCP install state
    const [mcpPlan, setMcpPlan] = useState(null);
    const [mcpInstalling, setMcpInstalling] = useState(false);
    const [mcpResult, setMcpResult] = useState(null);
    const [forceReinstall, setForceReinstall] = useState(false);
    // Do we need MCP server installation? (installable, downloadable, or external missing)
    const needsMcpInstall = preview?.dependency_check?.mcp_servers?.some((s) => s.status === 'installable' || s.status === 'downloadable'
        || (s.status === 'missing' && s.source_type === 'external')) ?? false;
    // Alias for backwards compat in the component
    const hasMissingMcpServers = needsMcpInstall;
    // Are there MCP servers that are already installed? (user may want to reinstall)
    const hasAlreadyInstalledServers = preview?.dependency_check?.mcp_servers?.some((s) => s.status === 'available' && s.source_type === 'external') ?? false;
    // Total steps: 4 if MCP install needed, 3 otherwise
    const totalSteps = hasMissingMcpServers ? 4 : 3;
    // Map step numbers: 0=Upload, 1=Preview, 2=MCP (if needed), last=Complete
    const STEP_UPLOAD = 0;
    const STEP_PREVIEW = 1;
    const STEP_MCP = hasMissingMcpServers ? 2 : -1;
    const STEP_COMPLETE = hasMissingMcpServers ? 3 : 2;
    // --- Drag & drop ---
    const handleDragOver = useCallback((e) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragging(true);
    }, []);
    const handleDragLeave = useCallback((e) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragging(false);
    }, []);
    const handleDrop = useCallback((e) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragging(false);
        const f = e.dataTransfer.files?.[0];
        if (f)
            handleFileSelected(f);
    }, []);
    const handleFileChange = useCallback((e) => {
        const f = e.target.files?.[0];
        if (f)
            handleFileSelected(f);
    }, []);
    const handleFileSelected = async (f) => {
        setFile(f);
        setError(null);
        setLoading(true);
        try {
            const result = await previewPersonaPackage({ backendUrl, apiKey, file: f });
            setPreview(result);
            const mm = result.manifest?.memory_mode || result.persona_agent?.memory_mode || 'adaptive';
            setMemoryMode(mm === 'basic' ? 'basic' : 'adaptive');
            setStep(STEP_PREVIEW);
        }
        catch (err) {
            setError(err.message || 'Failed to parse package');
        }
        finally {
            setLoading(false);
        }
    };
    // Resolve MCP deps (check what needs install)
    const handleResolveDeps = async () => {
        if (!file)
            return;
        setError(null);
        setLoading(true);
        try {
            const plan = await resolvePersonaDeps({ backendUrl, apiKey, file });
            setMcpPlan(plan);
            setStep(STEP_MCP);
        }
        catch (err) {
            setError(err.message || 'Failed to check MCP dependencies');
        }
        finally {
            setLoading(false);
        }
    };
    // Install missing MCP servers
    const handleInstallMcp = async () => {
        if (!file)
            return;
        setMcpInstalling(true);
        setError(null);
        try {
            const result = await installPersonaDeps({ backendUrl, apiKey, file });
            setMcpResult(result);
            // After MCP install, proceed to import the persona
            if (result.all_satisfied) {
                await doImport();
            }
        }
        catch (err) {
            setError(err.message || 'MCP server installation failed');
        }
        finally {
            setMcpInstalling(false);
        }
    };
    // Import the persona project
    const doImport = async () => {
        if (!file)
            return;
        setImporting(true);
        setError(null);
        try {
            const result = await importPersonaPackage({ backendUrl, apiKey, file });
            setImportedProject(result.project);
            setStep(STEP_COMPLETE);
            try {
                const engineValue = memoryMode === 'basic' ? 'v1' : 'v2';
                localStorage.setItem('homepilot_memory_engine', engineValue);
            }
            catch { /* non-critical */ }
            onImported(result.project);
        }
        catch (err) {
            setError(err.message || 'Import failed');
        }
        finally {
            setImporting(false);
        }
    };
    // Atomic import: install MCP servers + create persona in one call
    const handleAtomicImport = async () => {
        if (!file)
            return;
        setImporting(true);
        setError(null);
        try {
            const result = await importPersonaAtomic({
                backendUrl, apiKey, file, autoInstallServers: true,
                forceReinstall,
            });
            setImportedProject(result.project);
            if (result.install_plan) {
                setMcpResult(result.install_plan);
            }
            setStep(STEP_COMPLETE);
            try {
                const engineValue = memoryMode === 'basic' ? 'v1' : 'v2';
                localStorage.setItem('homepilot_memory_engine', engineValue);
            }
            catch { /* non-critical */ }
            onImported(result.project);
        }
        catch (err) {
            setError(err.message || 'Atomic import failed');
        }
        finally {
            setImporting(false);
        }
    };
    const handleImport = async () => {
        if (needsMcpInstall) {
            // Use atomic import for one-click install
            await handleAtomicImport();
        }
        else {
            await doImport();
        }
    };
    // Extract preview data
    const agentLabel = preview?.persona_agent?.label || preview?.persona_agent?.id || 'Unknown';
    const agentRole = preview?.persona_agent?.role || '';
    const tone = preview?.persona_agent?.response_style?.tone || preview?.persona_agent?.tone || '';
    const contentRating = preview?.manifest?.content_rating || 'sfw';
    const schemaVer = preview?.manifest?.schema_version || 1;
    const pkgVer = preview?.manifest?.package_version || 1;
    const depCheck = preview?.dependency_check;
    const tools = preview?.persona_agent?.allowed_tools || [];
    const contents = preview?.manifest?.contents;
    return (<div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="w-full max-w-2xl bg-[#1a1a2e] rounded-2xl border border-white/10 shadow-2xl flex flex-col max-h-[90vh] overflow-hidden">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10">
          <div>
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <Package size={18} className="text-purple-400"/>
              Import Persona
            </h2>
            <div className="mt-1">
              <StepBreadcrumb step={step} totalSteps={totalSteps}/>
            </div>
          </div>
          <button onClick={onClose} className="p-2 text-white/50 hover:text-white hover:bg-white/10 rounded-lg transition-colors">
            <X size={20}/>
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 custom-scrollbar">

          {/* ── Step 0: Upload ── */}
          {step === STEP_UPLOAD && (<div className="space-y-4">
              <div onDragOver={handleDragOver} onDragLeave={handleDragLeave} onDrop={handleDrop} className={`flex flex-col items-center justify-center gap-4 p-10 rounded-2xl border-2 border-dashed transition-all ${isDragging
                ? 'border-purple-500/60 bg-purple-500/5 ring-2 ring-purple-500/20'
                : 'border-white/15 bg-white/[0.02] hover:border-white/25'}`}>
                <div className={`w-16 h-16 rounded-2xl flex items-center justify-center transition-all ${isDragging ? 'bg-purple-500/15 border border-purple-500/30' : 'bg-white/5 border border-white/10'}`}>
                  <Package size={28} className={isDragging ? 'text-purple-400' : 'text-white/60'}/>
                </div>

                <div className="text-center">
                  <h3 className="text-base font-semibold text-white mb-1">
                    {loading ? 'Analyzing package...' : 'Drop .hpersona file here'}
                  </h3>
                  <p className="text-sm text-white/40">
                    {loading ? 'Checking dependencies and validating contents' : 'or click to browse'}
                  </p>
                </div>

                {!loading && (<label className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-white/10 hover:bg-white/15 border border-white/10 transition-colors cursor-pointer text-sm text-white font-medium">
                    <Upload size={16}/>
                    Browse files
                    <input ref={fileInputRef} type="file" accept=".hpersona" className="hidden" onChange={handleFileChange}/>
                  </label>)}

                {loading && (<div className="flex items-center gap-2 text-sm text-purple-300">
                    <div className="w-4 h-4 border-2 border-purple-400 border-t-transparent rounded-full animate-spin"/>
                    Parsing package...
                  </div>)}
              </div>

              <div className="flex items-start gap-2 px-3 py-2.5 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                <Shield size={14} className="text-white/30 mt-0.5 shrink-0"/>
                <p className="text-xs text-white/40 leading-relaxed">
                  .hpersona files contain persona configurations, avatar images, and model references.
                  No executable code is included. Tool and server dependencies are checked before installation.
                </p>
              </div>
            </div>)}

          {/* ── Step 1: Preview ── */}
          {step === STEP_PREVIEW && preview && (<div className="space-y-5">

              {/* Persona card */}
              <div className="flex items-start gap-4 p-4 rounded-xl bg-white/[0.04] border border-white/[0.08]">
                <div className="w-16 h-16 rounded-xl overflow-hidden bg-gradient-to-br from-purple-500/20 to-pink-500/20 border border-white/10 flex items-center justify-center shrink-0">
                  {preview.avatar_preview_data_url ? (<img src={preview.avatar_preview_data_url} alt={agentLabel} className="block w-full h-full object-cover"/>) : preview.has_avatar ? (<ImageIcon size={24} className="text-pink-400"/>) : (<Bot size={24} className="text-purple-400"/>)}
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="text-lg font-semibold text-white">{agentLabel}</h3>
                  <div className="flex items-center gap-2 mt-1 flex-wrap">
                    {agentRole && <span className="text-xs text-white/50">{agentRole}</span>}
                    {tone && <span className="text-xs px-2 py-0.5 rounded-full bg-purple-500/15 text-purple-300 border border-purple-500/20">{tone}</span>}
                    {contentRating === 'nsfw' && (<span className="text-xs px-2 py-0.5 rounded-full bg-red-500/15 text-red-300 border border-red-500/20">NSFW</span>)}
                  </div>
                  <div className="flex items-center gap-3 mt-2 text-xs text-white/35">
                    {tools.length > 0 && <span>{tools.length} tools</span>}
                    {contents?.has_avatar && <span>Avatar included</span>}
                    {(contents?.outfit_count || 0) > 0 && <span>{contents.outfit_count} outfits</span>}
                    <span>v{pkgVer} / schema {schemaVer}</span>
                  </div>
                </div>
              </div>

              {/* Memory Mode */}
              <div className="flex items-center justify-between p-3 rounded-xl bg-white/[0.04] border border-white/[0.08]">
                <div>
                  <div className="text-xs font-semibold text-white/50 mb-0.5">Memory Mode</div>
                  <div className="text-[10px] text-white/30">
                    {memoryMode === 'adaptive'
                ? 'Learns over time, forgets irrelevant details.'
                : 'Only remembers what is explicitly saved.'}
                  </div>
                </div>
                <div className="flex gap-1.5">
                  {['adaptive', 'basic'].map((mode) => (<button key={mode} type="button" onClick={() => setMemoryMode(mode)} className={`text-[11px] px-3 py-1 rounded-full border transition-all ${memoryMode === mode
                    ? mode === 'adaptive'
                        ? 'bg-purple-500/15 border-purple-500/30 text-purple-300'
                        : 'bg-blue-500/15 border-blue-500/30 text-blue-300'
                    : 'bg-white/5 border-white/10 text-white/40 hover:bg-white/8'}`}>
                      {mode === 'adaptive' ? 'Adaptive' : 'Basic'}
                    </button>))}
                </div>
              </div>

              {/* System prompt preview */}
              {preview.persona_agent?.system_prompt && (<div>
                  <div className="text-xs font-semibold text-white/50 mb-2">System Prompt</div>
                  <div className="text-sm text-white/60 bg-white/[0.03] border border-white/[0.06] rounded-xl px-4 py-3 max-h-24 overflow-y-auto custom-scrollbar leading-relaxed">
                    {preview.persona_agent.system_prompt.slice(0, 300)}
                    {preview.persona_agent.system_prompt.length > 300 ? '...' : ''}
                  </div>
                </div>)}

              {/* Dependencies */}
              {depCheck && (<div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="text-xs font-semibold text-white/50">Dependencies</div>
                    <div className={`text-xs px-2.5 py-0.5 rounded-full font-medium ${depCheck.all_satisfied
                    ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/20'
                    : 'bg-amber-500/15 text-amber-300 border border-amber-500/20'}`}>
                      {depCheck.summary}
                    </div>
                  </div>

                  {/* Models */}
                  {depCheck.models.length > 0 && (<div>
                      <div className="flex items-center gap-2 mb-1.5">
                        <Cpu size={13} className="text-white/30"/>
                        <span className="text-xs text-white/40 font-medium">Image Models</span>
                      </div>
                      <div className="space-y-1.5">
                        {depCheck.models.map((m, i) => <DependencyRow key={i} item={m}/>)}
                      </div>
                    </div>)}

                  {/* Tools */}
                  {depCheck.tools.length > 0 && (<div>
                      <div className="flex items-center gap-2 mb-1.5">
                        <Wrench size={13} className="text-white/30"/>
                        <span className="text-xs text-white/40 font-medium">Tools ({depCheck.tools.length})</span>
                      </div>
                      <div className="space-y-1.5 max-h-32 overflow-y-auto custom-scrollbar">
                        {depCheck.tools.map((t, i) => <DependencyRow key={i} item={t}/>)}
                      </div>
                    </div>)}

                  {/* MCP Servers */}
                  {depCheck.mcp_servers.length > 0 && (<div>
                      <div className="flex items-center gap-2 mb-1.5">
                        <Server size={13} className="text-white/30"/>
                        <span className="text-xs text-white/40 font-medium">MCP Servers ({depCheck.mcp_servers.length})</span>
                      </div>
                      <div className="space-y-1.5">
                        {depCheck.mcp_servers.map((s, i) => <DependencyRow key={i} item={s}/>)}
                      </div>
                    </div>)}

                  {/* A2A Agents */}
                  {depCheck.a2a_agents.length > 0 && (<div>
                      <div className="flex items-center gap-2 mb-1.5">
                        <Bot size={13} className="text-white/30"/>
                        <span className="text-xs text-white/40 font-medium">A2A Agents ({depCheck.a2a_agents.length})</span>
                      </div>
                      <div className="space-y-1.5">
                        {depCheck.a2a_agents.map((a, i) => <DependencyRow key={i} item={a}/>)}
                      </div>
                    </div>)}

                  {/* No dependencies */}
                  {depCheck.models.length === 0 && depCheck.tools.length === 0 &&
                    depCheck.mcp_servers.length === 0 && depCheck.a2a_agents.length === 0 && (<div className="text-xs text-white/30 italic py-2">No external dependencies required</div>)}
                </div>)}

              {/* MCP Server Install Prompt */}
              {needsMcpInstall && (<div className="p-4 rounded-xl bg-blue-500/[0.06] border border-blue-500/20">
                  <div className="flex items-start gap-3">
                    <div className="w-10 h-10 rounded-xl bg-blue-500/15 border border-blue-500/30 flex items-center justify-center shrink-0">
                      <Server size={18} className="text-blue-400"/>
                    </div>
                    <div className="flex-1">
                      <h4 className="text-sm font-semibold text-blue-300 mb-1">
                        MCP Server Setup Required
                      </h4>
                      <p className="text-xs text-blue-200/60 leading-relaxed mb-2">
                        This persona requires MCP server(s) that will be automatically installed.
                        Click <strong>Install Persona + Server</strong> to set everything up in one step.
                      </p>
                      {depCheck?.mcp_servers
                    .filter(s => s.status === 'installable' || s.status === 'downloadable'
                    || (s.status === 'missing' && s.source_type === 'external'))
                    .map((s, i) => (<div key={i} className="flex items-center gap-2 text-xs mt-1">
                            {s.status === 'installable' ? (<>
                                <Download size={11} className="text-blue-400"/>
                                <span className="font-medium text-blue-300/80">{s.name}</span>
                                <span className="text-blue-300/40">Ready to install{s.port ? ` on port ${s.port}` : ''}</span>
                              </>) : (<>
                                <GitBranch size={11} className="text-amber-400"/>
                                <span className="font-medium text-amber-300/80">{s.name}</span>
                                {s.url && <span className="text-amber-300/40 truncate">({s.url})</span>}
                              </>)}
                          </div>))}
                    </div>
                  </div>
                </div>)}

              {/* Reinstall option — shown when servers are already installed */}
              {hasAlreadyInstalledServers && (<div className="p-4 rounded-xl bg-white/[0.03] border border-white/[0.08]">
                  <div className="flex items-start gap-3">
                    <div className="w-10 h-10 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center shrink-0">
                      <RefreshCw size={18} className="text-amber-400"/>
                    </div>
                    <div className="flex-1">
                      <h4 className="text-sm font-semibold text-white/80 mb-1">
                        MCP Server Already Installed
                      </h4>
                      <p className="text-xs text-white/40 leading-relaxed mb-3">
                        The required MCP server(s) are already running. Choose whether to reuse them or reinstall from scratch.
                      </p>
                      <div className="flex gap-2">
                        <button type="button" onClick={() => setForceReinstall(false)} className={`text-xs px-3 py-1.5 rounded-lg border transition-all ${!forceReinstall
                    ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-300'
                    : 'bg-white/5 border-white/10 text-white/40 hover:bg-white/8'}`}>
                          Reuse existing
                        </button>
                        <button type="button" onClick={() => setForceReinstall(true)} className={`text-xs px-3 py-1.5 rounded-lg border transition-all ${forceReinstall
                    ? 'bg-amber-500/15 border-amber-500/30 text-amber-300'
                    : 'bg-white/5 border-white/10 text-white/40 hover:bg-white/8'}`}>
                          Purge &amp; reinstall
                        </button>
                      </div>
                      {depCheck?.mcp_servers
                    .filter(s => s.status === 'available' && s.source_type === 'external')
                    .map((s, i) => (<div key={i} className="flex items-center gap-2 text-xs mt-2">
                            <CheckCircle size={11} className="text-emerald-400"/>
                            <span className="font-medium text-white/60">{s.name}</span>
                            <span className="text-white/30">running{s.port ? ` on port ${s.port}` : ''}</span>
                          </div>))}
                    </div>
                  </div>
                </div>)}
            </div>)}

          {/* ── Step 2: MCP Server Installation ── */}
          {step === STEP_MCP && (<div className="space-y-5">

              {/* Header */}
              <div className="text-center">
                <div className="w-14 h-14 mx-auto rounded-2xl bg-purple-500/15 border border-purple-500/30 flex items-center justify-center mb-3">
                  <Server size={24} className="text-purple-400"/>
                </div>
                <h3 className="text-lg font-semibold text-white mb-1">
                  MCP Server Installation
                </h3>
                <p className="text-sm text-white/50">
                  {mcpInstalling
                ? 'Installing required MCP servers...'
                : mcpResult
                    ? mcpResult.all_satisfied
                        ? 'All servers installed successfully!'
                        : 'Some servers could not be installed'
                    : `${mcpPlan?.servers_to_install.length || 0} server(s) need to be installed`}
                </p>
              </div>

              {/* Install confirmation (before install) */}
              {!mcpInstalling && !mcpResult && mcpPlan && (<div className="space-y-3">
                  {/* Already available */}
                  {mcpPlan.servers_already_available.length > 0 && (<div>
                      <div className="text-xs font-semibold text-emerald-300/70 mb-2">Available</div>
                      {mcpPlan.servers_already_available.map((s, i) => (<div key={i} className="flex items-center gap-2 py-1.5 px-3 text-xs text-white/50">
                          <CheckCircle size={14} className="text-emerald-400"/>
                          <span className="font-medium text-white/70">{s.name || 'unknown'}</span>
                          <span className="text-white/30">{s.description || ''}</span>
                        </div>))}
                    </div>)}

                  {/* To install */}
                  {mcpPlan.servers_to_install.length > 0 && (<div>
                      <div className="text-xs font-semibold text-amber-300/70 mb-2">Will be installed</div>
                      {mcpPlan.servers_to_install.map((s, i) => (<div key={i} className="p-3 rounded-xl bg-white/[0.03] border border-white/[0.06] mb-2">
                          <div className="flex items-center gap-2 mb-1">
                            <Server size={14} className="text-amber-400"/>
                            <span className="text-sm font-medium text-white">{s.name}</span>
                          </div>
                          <div className="text-xs text-white/40">{s.description}</div>
                          {s.git_url && (<div className="flex items-center gap-1.5 mt-1.5 text-[10px] text-white/25">
                              <GitBranch size={10}/>
                              <span className="truncate">{s.git_url}</span>
                            </div>)}
                          {s.tools_provided.length > 0 && (<div className="flex items-center gap-1.5 mt-1 text-[10px] text-white/25">
                              <Wrench size={10}/>
                              <span>{s.tools_provided.length} tools: {s.tools_provided.join(', ')}</span>
                            </div>)}
                        </div>))}
                    </div>)}

                  {/* Install button */}
                  <div className="flex justify-center pt-2">
                    <button onClick={handleInstallMcp} className="flex items-center gap-2 px-6 py-2.5 bg-purple-500 hover:bg-purple-600 text-white text-sm font-semibold rounded-full transition-colors">
                      <Download size={16}/>
                      Install {mcpPlan.servers_to_install.length} Server(s)
                    </button>
                  </div>
                </div>)}

              {/* Installing progress — live log viewer */}
              {mcpInstalling && (<div className="space-y-3">
                  <div className="flex items-center justify-center gap-2 text-sm text-purple-300">
                    <Loader2 size={16} className="animate-spin"/>
                    Installing MCP servers... This may take a moment.
                  </div>
                  {/* Live install logs for each server being installed */}
                  {mcpPlan?.servers_to_install?.map((srv, i) => (<div key={i} className="p-3 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                      <div className="flex items-center gap-2 mb-1">
                        <Server size={14} className="text-purple-400"/>
                        <span className="text-sm font-medium text-white">{srv.name}</span>
                        <Loader2 size={12} className="text-purple-400/60 animate-spin"/>
                      </div>
                      <InstallLogViewer backendUrl={backendUrl} apiKey={apiKey} serverName={srv.name} active={true}/>
                    </div>))}
                </div>)}

              {/* Install results */}
              {mcpResult && (<div className="space-y-3">
                  {mcpResult.install_statuses.map((s, i) => (<McpInstallCard key={i} status={s} backendUrl={backendUrl} apiKey={apiKey}/>))}

                  {/* Summary */}
                  <div className={`p-3 rounded-xl text-center text-sm font-medium ${mcpResult.all_satisfied
                    ? 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-300'
                    : 'bg-amber-500/10 border border-amber-500/20 text-amber-300'}`}>
                    {mcpResult.summary}
                  </div>
                </div>)}
            </div>)}

          {/* ── Step 3 (or 2): Complete ── */}
          {step === STEP_COMPLETE && importedProject && (<div className="flex flex-col items-center py-8 space-y-6">
              <div className="w-20 h-20 rounded-full bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center">
                <Check size={36} className="text-emerald-400"/>
              </div>

              <div className="text-center">
                <h3 className="text-xl font-semibold text-white mb-1">
                  {importedProject.name || 'Persona'} installed!
                </h3>
                <p className="text-sm text-white/50">
                  The persona project has been created and is ready to use.
                </p>
              </div>

              <div className="space-y-2 text-sm text-white/50 w-full max-w-sm">
                {preview?.has_avatar && (<div className="flex items-center gap-2">
                    <Check size={14} className="text-emerald-400"/>
                    Avatar committed to project storage
                  </div>)}
                {(preview?.manifest?.contents?.outfit_count || 0) > 0 && (<div className="flex items-center gap-2">
                    <Check size={14} className="text-emerald-400"/>
                    {preview.manifest.contents.outfit_count} outfits imported
                  </div>)}
                {(preview?.persona_agent?.allowed_tools?.length || 0) > 0 && (<div className="flex items-center gap-2">
                    <Check size={14} className="text-emerald-400"/>
                    {preview.persona_agent.allowed_tools.length} tools configured
                  </div>)}
                {mcpResult && mcpResult.install_statuses.length > 0 && (<div className="flex items-center gap-2">
                    <Check size={14} className="text-emerald-400"/>
                    {mcpResult.install_statuses.filter(s => s.phase === 'complete' || s.phase === 'skipped').length} MCP server(s) installed and synced
                  </div>)}
                {(preview?.dependency_check?.mcp_servers?.length || 0) > 0 && !mcpResult && (<div className="flex items-center gap-2">
                    <Check size={14} className="text-emerald-400"/>
                    {preview.dependency_check.mcp_servers.length} MCP server(s) referenced
                  </div>)}
                <div className="flex items-center gap-2">
                  <Check size={14} className="text-emerald-400"/>
                  Memory: {memoryMode === 'adaptive' ? 'Adaptive Memory' : 'Basic Memory'}
                </div>
              </div>
            </div>)}

          {/* Error display */}
          {error && (<div className="mt-4 text-sm text-red-400 bg-red-500/10 border border-red-500/20 rounded-xl px-4 py-3">
              {error}
            </div>)}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-white/10 bg-[#1a1a2e] flex justify-between items-center">
          {step === STEP_UPLOAD && (<>
              <div />
              <button onClick={onClose} className="px-4 py-2 text-sm font-medium text-white/50 hover:text-white transition-colors">
                Cancel
              </button>
            </>)}

          {step === STEP_PREVIEW && (<>
              <button onClick={() => { setStep(STEP_UPLOAD); setFile(null); setPreview(null); setError(null); }} className="flex items-center gap-1 px-4 py-2 text-sm font-medium text-white/50 hover:text-white transition-colors">
                <ChevronLeft size={16}/>
                Back
              </button>
              <button onClick={handleImport} disabled={importing || loading} className="flex items-center gap-2 px-6 py-2.5 bg-purple-500 hover:bg-purple-600 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-semibold rounded-full transition-colors">
                {importing || loading ? (<>
                    <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"/>
                    {needsMcpInstall ? 'Installing servers & persona...' : 'Installing...'}
                  </>) : needsMcpInstall ? (<>
                    <Server size={16}/>
                    Install Persona + Server
                  </>) : (<>
                    <Download size={16}/>
                    Install Persona
                  </>)}
              </button>
            </>)}

          {step === STEP_MCP && (<>
              <button onClick={() => { setStep(STEP_PREVIEW); setMcpPlan(null); setMcpResult(null); setError(null); }} disabled={mcpInstalling} className="flex items-center gap-1 px-4 py-2 text-sm font-medium text-white/50 hover:text-white transition-colors disabled:opacity-30">
                <ChevronLeft size={16}/>
                Back
              </button>
              {mcpResult?.all_satisfied && !importedProject && (<button onClick={doImport} disabled={importing} className="flex items-center gap-2 px-6 py-2.5 bg-emerald-500 hover:bg-emerald-600 disabled:opacity-40 text-white text-sm font-semibold rounded-full transition-colors">
                  {importing ? (<>
                      <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"/>
                      Creating persona...
                    </>) : (<>
                      <Check size={16}/>
                      Create Persona Project
                    </>)}
                </button>)}
              {mcpResult && !mcpResult.all_satisfied && (<button onClick={doImport} disabled={importing} className="flex items-center gap-2 px-6 py-2.5 bg-amber-500 hover:bg-amber-600 disabled:opacity-40 text-white text-sm font-semibold rounded-full transition-colors">
                  <SkipForward size={16}/>
                  Install Anyway (limited tools)
                </button>)}
            </>)}

          {step === STEP_COMPLETE && (<>
              <div />
              <button onClick={onClose} className="px-6 py-2.5 bg-purple-500 hover:bg-purple-600 text-white text-sm font-semibold rounded-full transition-colors">
                Done
              </button>
            </>)}
        </div>
      </div>
    </div>);
}
// ---------------------------------------------------------------------------
// Export button (inline, for project cards)
// ---------------------------------------------------------------------------
export function PersonaExportButton({ projectId, backendUrl, apiKey, className, }) {
    const [exporting, setExporting] = useState(false);
    const handleExport = async (e) => {
        e.stopPropagation();
        if (exporting)
            return;
        setExporting(true);
        try {
            await exportPersona({ backendUrl, apiKey, projectId });
        }
        catch (err) {
            alert(`Export failed: ${err.message}`);
        }
        finally {
            setExporting(false);
        }
    };
    return (<button onClick={handleExport} disabled={exporting} className={className || 'p-1.5 bg-purple-500/20 hover:bg-purple-500/40 rounded-lg text-purple-400 hover:text-purple-300 transition-colors disabled:opacity-40'} title="Export persona (.hpersona)">
      {exporting ? (<div className="w-3.5 h-3.5 border-2 border-purple-400 border-t-transparent rounded-full animate-spin"/>) : (<Upload size={14}/>)}
    </button>);
}
