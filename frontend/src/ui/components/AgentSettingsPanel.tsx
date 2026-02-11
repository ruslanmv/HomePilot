import React, { useState, useEffect, useCallback } from 'react'
import {
  X,
  Settings,
  Bot,
  Zap,
  Shield,
  Wrench,
  Users,
  Server,
  ChevronDown,
  ChevronUp,
  Check,
  Circle,
  Loader2,
  FileText,
  Trash2,
} from 'lucide-react'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type AgentProjectData = {
  id: string
  name: string
  description?: string
  instructions?: string
  project_type?: string
  files?: Array<{ name: string; size?: string; chunks?: number }>
  agentic?: {
    goal?: string
    capabilities?: string[]
    tool_ids?: string[]
    a2a_agent_ids?: string[]
    tool_details?: Array<{ id: string; name: string; description?: string }>
    agent_details?: Array<{ id: string; name: string; description?: string }>
    tool_source?: string
    ask_before_acting?: boolean
    execution_profile?: 'fast' | 'balanced' | 'quality'
  }
}

type CatalogItem = { id: string; name: string; description?: string; enabled?: boolean }
type CatalogServer = { id: string; name: string; description?: string; enabled?: boolean; tool_ids?: string[] }

type Props = {
  project: AgentProjectData
  backendUrl: string
  apiKey?: string
  onClose: () => void
  onSaved: (updated: AgentProjectData) => void
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PROFILE_OPTIONS: Array<{
  value: 'fast' | 'balanced' | 'quality'
  label: string
  hint: string
}> = [
  { value: 'fast', label: 'Fast', hint: 'Low latency, fewer tool calls' },
  { value: 'balanced', label: 'Balanced', hint: 'Good mix of speed and depth' },
  { value: 'quality', label: 'Quality', hint: 'Thorough, multi-step reasoning' },
]

const BUILTIN_CAPABILITIES: Array<{ id: string; label: string }> = [
  { id: 'generate_images', label: 'Generate images' },
  { id: 'generate_videos', label: 'Generate short videos' },
  { id: 'analyze_documents', label: 'Analyze documents' },
  { id: 'automate_external', label: 'Automate external services' },
]

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function SectionHeader({ icon: Icon, title, badge }: {
  icon: React.ElementType
  title: string
  badge?: string | number
}) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <Icon size={14} className="text-white/50" />
      <span className="text-xs font-semibold text-white/60 uppercase tracking-wider">{title}</span>
      {badge !== undefined && (
        <span className="ml-auto text-[10px] px-1.5 py-0.5 rounded-full bg-white/10 text-white/50 font-medium">
          {badge}
        </span>
      )}
    </div>
  )
}

function Toggle({ checked, onChange, label }: {
  checked: boolean
  onChange: (v: boolean) => void
  label: string
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className="flex items-center justify-between w-full group"
    >
      <span className="text-sm text-white/80 group-hover:text-white transition-colors">{label}</span>
      <div
        className={[
          'relative w-10 h-5 rounded-full transition-colors',
          checked ? 'bg-purple-500' : 'bg-white/15',
        ].join(' ')}
      >
        <div
          className={[
            'absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform',
            checked ? 'translate-x-5' : 'translate-x-0.5',
          ].join(' ')}
        />
      </div>
    </button>
  )
}

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span className={`inline-block w-1.5 h-1.5 rounded-full ${ok ? 'bg-green-400' : 'bg-white/20'}`} />
  )
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function AgentSettingsPanel({ project, backendUrl, apiKey, onClose, onSaved }: Props) {
  const ag = project.agentic || {}

  // --- Editable state ---
  const [name, setName] = useState(project.name || '')
  const [description, setDescription] = useState(project.description || '')
  const [instructions, setInstructions] = useState(project.instructions || '')
  const [goal, setGoal] = useState(ag.goal || '')
  const [capabilities, setCapabilities] = useState<string[]>(ag.capabilities || [])
  const [profile, setProfile] = useState<'fast' | 'balanced' | 'quality'>(ag.execution_profile || 'fast')
  const [askFirst, setAskFirst] = useState(ag.ask_before_acting !== false)
  const [toolIds, setToolIds] = useState<string[]>(ag.tool_ids || [])
  const [agentIds, setAgentIds] = useState<string[]>(ag.a2a_agent_ids || [])
  const [toolSource, setToolSource] = useState(ag.tool_source || 'all')

  // --- Catalog data ---
  const [catalogTools, setCatalogTools] = useState<CatalogItem[]>([])
  const [catalogAgents, setCatalogAgents] = useState<CatalogItem[]>([])
  const [catalogServers, setCatalogServers] = useState<CatalogServer[]>([])
  const [catalogLoading, setCatalogLoading] = useState(true)

  // --- Documents ---
  const [documents, setDocuments] = useState<Array<{ name: string; size?: string; chunks?: number }>>(project.files || [])

  // --- UI state ---
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [showTools, setShowTools] = useState(false)
  const [showAgents, setShowAgents] = useState(false)

  // Track dirtiness
  useEffect(() => { setDirty(true) }, [name, description, instructions, goal, capabilities, profile, askFirst, toolIds, agentIds, toolSource])
  // Reset dirty on initial load
  useEffect(() => { setDirty(false) }, [])

  // --- Fetch catalog ---
  useEffect(() => {
    const headers: Record<string, string> = {}
    if (apiKey) headers['x-api-key'] = apiKey

    fetch(`${backendUrl}/v1/agentic/catalog`, { headers })
      .then((r) => r.ok ? r.json() : null)
      .then((data) => {
        if (data) {
          setCatalogServers(
            Array.isArray(data.servers)
              ? data.servers.map((s: any) => ({
                  id: String(s.id || s.name),
                  name: String(s.name || s.id),
                  description: s.description,
                  enabled: s.enabled !== false,
                  tool_ids: Array.isArray(s.tool_ids)
                    ? s.tool_ids
                    : (Array.isArray(s.associated_tools) ? s.associated_tools : []),
                }))
              : []
          )
          setCatalogTools(
            Array.isArray(data.tools)
              ? data.tools.map((t: any) => ({ id: t.id || t.name, name: t.name, description: t.description, enabled: t.enabled !== false }))
              : []
          )
          setCatalogAgents(
            Array.isArray(data.a2a_agents)
              ? data.a2a_agents.map((a: any) => ({ id: a.id || a.name, name: a.name, description: a.description, enabled: a.enabled !== false }))
              : []
          )
        }
      })
      .catch(() => {})
      .finally(() => setCatalogLoading(false))
  }, [backendUrl, apiKey])

  // --- Derived: effective access policy (matches wizard + backend enforcement) ---
  const enabledCatalogTools = catalogTools.filter((t) => t.enabled !== false)

  const serverToolCount = (() => {
    if (!toolSource.startsWith('server:')) return 0
    const sid = toolSource.replace('server:', '')
    const s = catalogServers.find((x) => x.id === sid)
    return s?.tool_ids?.length || 0
  })()

  const effectiveToolCount = (() => {
    if (toolSource === 'none') return 0
    if (toolSource === 'all') return enabledCatalogTools.length
    if (toolSource.startsWith('server:')) return serverToolCount
    return 0
  })()

  const visibleTools = (() => {
    if (toolSource === 'none') return []
    if (toolSource === 'all') return enabledCatalogTools
    if (toolSource.startsWith('server:')) {
      const sid = toolSource.replace('server:', '')
      const s = catalogServers.find((x) => x.id === sid)
      if (!s?.tool_ids?.length) return []
      const ids = new Set(s.tool_ids)
      return enabledCatalogTools.filter((t) => ids.has(t.id))
    }
    return []
  })()

  // --- Save ---
  const handleSave = useCallback(async () => {
    setSaving(true)
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (apiKey) headers['x-api-key'] = apiKey

      // Build lookup from previously saved details so we can fall back if catalog is empty/stale
      const prevToolDetails: Record<string, { name: string; description?: string }> = {}
      for (const d of (ag.tool_details || [])) {
        if (d && typeof d === 'object' && d.id) prevToolDetails[d.id] = d
      }
      const prevAgentDetails: Record<string, { name: string; description?: string }> = {}
      for (const d of (ag.agent_details || [])) {
        if (d && typeof d === 'object' && d.id) prevAgentDetails[d.id] = d
      }

      // Resolve human-readable names for tools & agents (catalog → previous save → fallback)
      const toolDetails = toolIds.map((tid) => {
        const t = catalogTools.find((x) => x.id === tid)
        const prev = prevToolDetails[tid]
        return {
          id: tid,
          name: t?.name || prev?.name || tid,
          description: t?.description || prev?.description || '',
        }
      })
      const agentDetailsList = agentIds.map((aid) => {
        const a = catalogAgents.find((x) => x.id === aid)
        const prev = prevAgentDetails[aid]
        return {
          id: aid,
          name: a?.name || prev?.name || aid,
          description: a?.description || prev?.description || '',
        }
      })

      const body = {
        name,
        description,
        instructions,
        project_type: 'agent',
        agentic: {
          goal,
          capabilities,
          tool_ids: toolIds,
          a2a_agent_ids: agentIds,
          tool_details: toolDetails,
          agent_details: agentDetailsList,
          tool_source: toolSource,
          ask_before_acting: askFirst,
          execution_profile: profile,
        },
      }

      const res = await fetch(`${backendUrl}/projects/${project.id}`, {
        method: 'PUT',
        headers,
        body: JSON.stringify(body),
      })

      if (res.ok) {
        const data = await res.json()
        setDirty(false)
        onSaved(data.project)
      } else {
        alert('Failed to save project settings')
      }
    } catch {
      alert('Failed to save project settings')
    } finally {
      setSaving(false)
    }
  }, [name, description, instructions, goal, capabilities, profile, askFirst, toolIds, agentIds, toolSource, backendUrl, apiKey, project.id, onSaved, catalogTools, catalogAgents, ag.tool_details, ag.agent_details])

  // --- Document delete ---
  const handleDeleteDoc = async (docName: string) => {
    if (!confirm(`Delete document "${docName}"?`)) return
    try {
      const headers: Record<string, string> = {}
      if (apiKey) headers['x-api-key'] = apiKey
      const res = await fetch(`${backendUrl}/projects/${project.id}/documents/${encodeURIComponent(docName)}`, { method: 'DELETE', headers })
      if (res.ok) setDocuments((prev) => prev.filter((d) => d.name !== docName))
    } catch { /* silent */ }
  }

  const toggleCap = (id: string) => {
    setCapabilities((prev) => prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id])
  }
  const toggleTool = (id: string) => {
    setToolIds((prev) => prev.includes(id) ? prev.filter((t) => t !== id) : [...prev, id])
  }
  const toggleAgent = (id: string) => {
    setAgentIds((prev) => prev.includes(id) ? prev.filter((a) => a !== id) : [...prev, id])
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
      <div
        className="w-full max-w-2xl bg-[#1a1a2e] rounded-2xl border border-white/10 shadow-2xl flex flex-col max-h-[90vh] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* ── Header ── */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-amber-500/20 border border-amber-500/30 flex items-center justify-center">
              <Bot size={16} className="text-amber-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white">Agent Settings</h2>
              <p className="text-xs text-white/40">Configure behavior, tools, and connections</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-white/50 hover:text-white hover:bg-white/10 rounded-lg transition-colors"
          >
            <X size={20} />
          </button>
        </div>

        {/* ── Content ── */}
        <div className="flex-1 overflow-y-auto p-6 space-y-8 custom-scrollbar">

          {/* ─── Section: Identity ─── */}
          <section>
            <SectionHeader icon={Bot} title="Identity" />
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-white/60 mb-1.5">Project Name</label>
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm text-white placeholder-white/30 focus:outline-none focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/30 transition-all"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-white/60 mb-1.5">Description</label>
                <input
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="What does this agent do?"
                  className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm text-white placeholder-white/30 focus:outline-none focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/30 transition-all"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-white/60 mb-1.5">Agent Goal</label>
                <textarea
                  value={goal}
                  onChange={(e) => setGoal(e.target.value)}
                  placeholder="e.g. Help me plan my week and make decisions"
                  rows={2}
                  className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm text-white placeholder-white/30 focus:outline-none focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/30 transition-all resize-none"
                />
              </div>
            </div>
          </section>

          {/* ─── Section: Behavior ─── */}
          <section>
            <SectionHeader icon={Zap} title="Behavior" />
            <div className="space-y-5">
              {/* Execution profile */}
              <div>
                <label className="block text-xs font-medium text-white/60 mb-2">Execution Profile</label>
                <div className="grid grid-cols-3 gap-2">
                  {PROFILE_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => setProfile(opt.value)}
                      className={[
                        'relative px-3 py-3 rounded-xl border text-left transition-all',
                        profile === opt.value
                          ? 'bg-purple-500/15 border-purple-500/40 ring-1 ring-purple-500/20'
                          : 'bg-white/5 border-white/10 hover:bg-white/8 hover:border-white/15',
                      ].join(' ')}
                    >
                      <div className="text-sm font-medium text-white">{opt.label}</div>
                      <div className="text-[11px] text-white/40 mt-0.5 leading-tight">{opt.hint}</div>
                      {profile === opt.value && (
                        <div className="absolute top-2 right-2">
                          <Check size={12} className="text-purple-400" />
                        </div>
                      )}
                    </button>
                  ))}
                </div>
              </div>

              {/* Toggle */}
              <div className="px-1">
                <Toggle
                  checked={askFirst}
                  onChange={setAskFirst}
                  label="Ask before executing actions"
                />
                <p className="text-[11px] text-white/35 mt-1 ml-0.5">
                  When enabled, the agent will confirm before running tools or taking actions.
                </p>
              </div>
            </div>
          </section>

          {/* ─── Section: Capabilities ─── */}
          <section>
            <SectionHeader icon={Shield} title="Capabilities" badge={capabilities.length} />
            <div className="grid grid-cols-2 gap-2">
              {BUILTIN_CAPABILITIES.map((cap) => {
                const active = capabilities.includes(cap.id)
                return (
                  <button
                    key={cap.id}
                    type="button"
                    onClick={() => toggleCap(cap.id)}
                    className={[
                      'flex items-center gap-2.5 px-3 py-2.5 rounded-xl border text-left transition-all',
                      active
                        ? 'bg-purple-500/15 border-purple-500/30'
                        : 'bg-white/5 border-white/10 hover:bg-white/8',
                    ].join(' ')}
                  >
                    <div className={[
                      'w-4 h-4 rounded border flex items-center justify-center shrink-0 transition-colors',
                      active ? 'bg-purple-500 border-purple-500' : 'border-white/20',
                    ].join(' ')}>
                      {active && <Check size={10} className="text-white" />}
                    </div>
                    <span className={`text-sm ${active ? 'text-white' : 'text-white/60'}`}>{cap.label}</span>
                  </button>
                )
              })}
            </div>
          </section>

          {/* ─── Section: Connected Tools ─── */}
          <section>
            <SectionHeader icon={Wrench} title="Connected Tools" badge={effectiveToolCount} />
            {catalogLoading ? (
              <div className="flex items-center gap-2 text-xs text-white/40 py-3">
                <Loader2 size={12} className="animate-spin" /> Loading catalog...
              </div>
            ) : catalogTools.length === 0 ? (
              <div className="text-xs text-white/35 py-3 px-1">
                No tools registered in Context Forge. Start the MCP servers and run the seed script.
              </div>
            ) : (
              <div>
                <button
                  type="button"
                  onClick={() => setShowTools(!showTools)}
                  className="flex items-center gap-2 text-xs text-white/50 hover:text-white/80 transition-colors mb-2"
                >
                  {showTools ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                  {showTools ? 'Collapse' : `Browse ${effectiveToolCount} in bundle (${toolIds.length} pinned)`}
                </button>

                {showTools && (
                  <div className="space-y-1 max-h-48 overflow-y-auto custom-scrollbar">
                    {visibleTools.map((tool) => {
                      const bound = toolIds.includes(tool.id)
                      return (
                        <button
                          key={tool.id}
                          type="button"
                          onClick={() => toggleTool(tool.id)}
                          className={[
                            'w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition-all',
                            bound
                              ? 'bg-purple-500/10 border border-purple-500/20'
                              : 'hover:bg-white/5 border border-transparent',
                          ].join(' ')}
                        >
                          <StatusDot ok={tool.enabled !== false} />
                          <div className="flex-1 min-w-0">
                            <div className="text-xs font-medium text-white truncate">{tool.name}</div>
                            {tool.description && (
                              <div className="text-[10px] text-white/35 truncate">{tool.description}</div>
                            )}
                          </div>
                          <div className={[
                            'w-4 h-4 rounded border flex items-center justify-center shrink-0',
                            bound ? 'bg-purple-500 border-purple-500' : 'border-white/20',
                          ].join(' ')}>
                            {bound && <Check size={10} className="text-white" />}
                          </div>
                        </button>
                      )
                    })}
                  </div>
                )}

                <p className="text-[11px] text-white/35 mt-2 px-1">
                  The tool bundle sets the runtime permission boundary. Checkmarks above are optional pinned tools
                  (UI hint) and do not expand access beyond the selected bundle.
                </p>

                <div className="flex items-center gap-3 mt-2 pt-2 border-t border-white/5">
                  <label className="text-xs text-white/50">Tool bundle:</label>
                  <select
                    value={toolSource}
                    onChange={(e) => setToolSource(e.target.value)}
                    className="bg-white/5 border border-white/10 rounded-lg px-2 py-1 text-xs text-white focus:outline-none focus:border-purple-500/50"
                  >
                    <option value="all">All enabled tools</option>
                    {catalogServers.map((s) => (
                      <option key={s.id} value={`server:${s.id}`}>
                        Virtual server: {s.name}
                      </option>
                    ))}
                    <option value="none">No tools</option>
                  </select>
                </div>
              </div>
            )}
          </section>

          {/* ─── Section: Connected Agents ─── */}
          <section>
            <SectionHeader icon={Users} title="Connected Agents" badge={agentIds.length} />
            {catalogLoading ? (
              <div className="flex items-center gap-2 text-xs text-white/40 py-3">
                <Loader2 size={12} className="animate-spin" /> Loading...
              </div>
            ) : catalogAgents.length === 0 ? (
              <div className="text-xs text-white/35 py-3 px-1">
                No A2A agents registered.
              </div>
            ) : (
              <div>
                <button
                  type="button"
                  onClick={() => setShowAgents(!showAgents)}
                  className="flex items-center gap-2 text-xs text-white/50 hover:text-white/80 transition-colors mb-2"
                >
                  {showAgents ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                  {showAgents ? 'Collapse' : `Browse ${catalogAgents.length} available (${agentIds.length} connected)`}
                </button>

                {showAgents && (
                  <div className="space-y-1 max-h-36 overflow-y-auto custom-scrollbar">
                    {catalogAgents.map((agent) => {
                      const bound = agentIds.includes(agent.id)
                      return (
                        <button
                          key={agent.id}
                          type="button"
                          onClick={() => toggleAgent(agent.id)}
                          className={[
                            'w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition-all',
                            bound
                              ? 'bg-purple-500/10 border border-purple-500/20'
                              : 'hover:bg-white/5 border border-transparent',
                          ].join(' ')}
                        >
                          <StatusDot ok={agent.enabled !== false} />
                          <div className="flex-1 min-w-0">
                            <div className="text-xs font-medium text-white truncate">{agent.name}</div>
                            {agent.description && (
                              <div className="text-[10px] text-white/35 truncate">{agent.description}</div>
                            )}
                          </div>
                          <div className={[
                            'w-4 h-4 rounded border flex items-center justify-center shrink-0',
                            bound ? 'bg-purple-500 border-purple-500' : 'border-white/20',
                          ].join(' ')}>
                            {bound && <Check size={10} className="text-white" />}
                          </div>
                        </button>
                      )
                    })}
                  </div>
                )}
              </div>
            )}
          </section>

          {/* ─── Section: Effective Access Summary ─── */}
          <section>
            <SectionHeader icon={Server} title="Effective Access" />
            <div className="rounded-xl bg-white/[0.03] border border-white/10 p-4 space-y-2">
              <div className="flex items-center justify-between text-xs">
                <span className="text-white/50">Tool bundle</span>
                <span className="text-white/80 font-medium">
                  {toolSource === 'all'
                    ? `All enabled tools (${effectiveToolCount})`
                    : toolSource === 'none'
                    ? 'No tools'
                    : (() => {
                        const sid = toolSource.replace('server:', '')
                        const s = catalogServers.find((x) => x.id === sid)
                        return s ? `${s.name} (${effectiveToolCount})` : toolSource
                      })()}
                </span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-white/50">Connected agents</span>
                <span className="text-white/80 font-medium">
                  {agentIds.length === 0
                    ? 'None'
                    : agentIds
                        .map((id) => catalogAgents.find((a) => a.id === id)?.name || id)
                        .join(', ')}
                </span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-white/50">Pinned tools</span>
                <span className="text-white/80 font-medium">{toolIds.length}</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-white/50">Execution</span>
                <span className="text-white/80 font-medium">{profile} / {askFirst ? 'Ask first' : 'Auto-execute'}</span>
              </div>
            </div>
          </section>

          {/* ─── Section: Instructions ─── */}
          <section>
            <SectionHeader icon={Settings} title="Custom Instructions" />
            <textarea
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              placeholder="How should this agent behave? E.g., Always be concise, prefer bullet points..."
              rows={4}
              className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm text-white placeholder-white/30 focus:outline-none focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/30 transition-all resize-none"
            />
          </section>

          {/* ─── Section: Documents ─── */}
          <section>
            <SectionHeader icon={FileText} title="Knowledge Base" badge={documents.length} />
            {documents.length === 0 ? (
              <div className="text-xs text-white/35 py-3 px-1">
                No documents uploaded. Upload files when creating or using the project.
              </div>
            ) : (
              <div className="space-y-1">
                {documents.map((doc, i) => (
                  <div key={i} className="flex items-center justify-between px-3 py-2 rounded-lg bg-white/5 border border-white/10 group">
                    <div className="flex items-center gap-2.5 min-w-0">
                      <FileText size={14} className="text-purple-400 shrink-0" />
                      <div className="min-w-0">
                        <div className="text-xs text-white truncate">{doc.name}</div>
                        <div className="text-[10px] text-white/30">
                          {doc.size || ''}{doc.chunks ? ` \u00b7 ${doc.chunks} chunks` : ''}
                        </div>
                      </div>
                    </div>
                    <button
                      onClick={() => handleDeleteDoc(doc.name)}
                      className="p-1 text-white/30 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all rounded hover:bg-red-500/10"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>

        {/* ── Footer ── */}
        <div className="px-6 py-4 border-t border-white/10 bg-[#1a1a2e] flex items-center justify-between">
          <div className="text-[11px] text-white/30">
            {dirty ? 'Unsaved changes' : 'All changes saved'}
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-white/50 hover:text-white transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saving || !dirty}
              className={[
                'px-5 py-2 text-sm font-semibold rounded-full transition-all',
                dirty
                  ? 'bg-purple-500 hover:bg-purple-600 text-white'
                  : 'bg-white/10 text-white/30 cursor-not-allowed',
              ].join(' ')}
            >
              {saving ? (
                <span className="flex items-center gap-2">
                  <Loader2 size={14} className="animate-spin" /> Saving...
                </span>
              ) : 'Save Changes'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
