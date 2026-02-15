/**
 * PersonaImportExport — Phase 3 v2
 *
 * Beautiful modal for importing .hpersona packages:
 *   Step 1: Upload (drag-drop or file picker)
 *   Step 2: Preview + dependency check
 *   Step 3: Install complete
 *
 * Also provides an export button component for project cards.
 */
import React, { useState, useCallback, useRef } from 'react'
import {
  X,
  Upload,
  Package,
  Check,
  AlertTriangle,
  Download,
  ChevronLeft,
  ChevronRight,
  MessageSquare,
  Mic,
  Wrench,
  Server,
  Bot,
  Image as ImageIcon,
  FileText,
  Shield,
  Cpu,
  HelpCircle,
} from 'lucide-react'

import type { PersonaPreview, DependencyItem } from './personaPortability'
import { previewPersonaPackage, importPersonaPackage, exportPersona } from './personaPortability'

// ---------------------------------------------------------------------------
// Status icon helper
// ---------------------------------------------------------------------------

function StatusIcon({ status }: { status: string }) {
  if (status === 'available')
    return <div className="w-5 h-5 rounded-full bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center"><Check size={12} className="text-emerald-400" /></div>
  if (status === 'missing')
    return <div className="w-5 h-5 rounded-full bg-red-500/20 border border-red-500/40 flex items-center justify-center"><X size={12} className="text-red-400" /></div>
  if (status === 'degraded')
    return <div className="w-5 h-5 rounded-full bg-amber-500/20 border border-amber-500/40 flex items-center justify-center"><AlertTriangle size={10} className="text-amber-400" /></div>
  return <div className="w-5 h-5 rounded-full bg-white/10 border border-white/20 flex items-center justify-center"><HelpCircle size={10} className="text-white/40" /></div>
}

function DependencyRow({ item }: { item: DependencyItem }) {
  return (
    <div className="flex items-center gap-3 py-2 px-3 rounded-lg bg-white/[0.03] border border-white/[0.06]">
      <StatusIcon status={item.status} />
      <div className="flex-1 min-w-0">
        <div className="text-sm text-white font-medium truncate">{item.name}</div>
        <div className="text-xs text-white/40 truncate">{item.detail || item.description}</div>
      </div>
      {item.source_type === 'builtin' && (
        <span className="text-[10px] px-2 py-0.5 rounded-full bg-purple-500/15 text-purple-300 border border-purple-500/20 shrink-0">
          Built-in
        </span>
      )}
      {item.source_type === 'external' && (
        <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-300 border border-amber-500/20 shrink-0">
          External
        </span>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Step breadcrumb
// ---------------------------------------------------------------------------

const STEP_LABELS = ['Upload', 'Preview', 'Install']

function StepBreadcrumb({ step }: { step: number }) {
  return (
    <div className="flex items-center gap-2">
      {STEP_LABELS.map((label, i) => (
        <React.Fragment key={label}>
          {i > 0 && <ChevronRight size={12} className="text-white/20" />}
          <span className={`text-xs font-medium ${
            i === step ? 'text-purple-300' : i < step ? 'text-emerald-400' : 'text-white/30'
          }`}>
            {i < step ? '\u2713 ' : ''}{label}
          </span>
        </React.Fragment>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Import Modal
// ---------------------------------------------------------------------------

export function PersonaImportModal({
  onClose,
  onImported,
  backendUrl,
  apiKey,
}: {
  onClose: () => void
  onImported: (project: Record<string, any>) => void
  backendUrl: string
  apiKey?: string
}) {
  const [step, setStep] = useState(0)
  const [file, setFile] = useState<File | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [preview, setPreview] = useState<PersonaPreview | null>(null)
  const [importing, setImporting] = useState(false)
  const [importedProject, setImportedProject] = useState<Record<string, any> | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // --- Drag & drop ---
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
    const f = e.dataTransfer.files?.[0]
    if (f) handleFileSelected(f)
  }, [])

  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (f) handleFileSelected(f)
  }, [])

  const handleFileSelected = async (f: File) => {
    setFile(f)
    setError(null)
    setLoading(true)

    try {
      const result = await previewPersonaPackage({ backendUrl, apiKey, file: f })
      setPreview(result)
      setStep(1)
    } catch (err: any) {
      setError(err.message || 'Failed to parse package')
    } finally {
      setLoading(false)
    }
  }

  const handleImport = async () => {
    if (!file) return
    setImporting(true)
    setError(null)

    try {
      const result = await importPersonaPackage({ backendUrl, apiKey, file })
      setImportedProject(result.project)
      setStep(2)
      onImported(result.project)
    } catch (err: any) {
      setError(err.message || 'Import failed')
    } finally {
      setImporting(false)
    }
  }

  // Extract preview data
  const agentLabel = preview?.persona_agent?.label || preview?.persona_agent?.id || 'Unknown'
  const agentRole = preview?.persona_agent?.role || ''
  const tone = preview?.persona_agent?.response_style?.tone || preview?.persona_agent?.tone || ''
  const category = preview?.persona_agent?.category || 'general'
  const contentRating = preview?.manifest?.content_rating || 'sfw'
  const schemaVer = preview?.manifest?.schema_version || 1
  const pkgVer = preview?.manifest?.package_version || 1
  const depCheck = preview?.dependency_check
  const tools = preview?.persona_agent?.allowed_tools || []
  const contents = preview?.manifest?.contents

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="w-full max-w-2xl bg-[#1a1a2e] rounded-2xl border border-white/10 shadow-2xl flex flex-col max-h-[90vh] overflow-hidden">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10">
          <div>
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <Package size={18} className="text-purple-400" />
              Import Persona
            </h2>
            <div className="mt-1">
              <StepBreadcrumb step={step} />
            </div>
          </div>
          <button onClick={onClose} className="p-2 text-white/50 hover:text-white hover:bg-white/10 rounded-lg transition-colors">
            <X size={20} />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 custom-scrollbar">

          {/* ── Step 0: Upload ── */}
          {step === 0 && (
            <div className="space-y-4">
              <div
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                className={`flex flex-col items-center justify-center gap-4 p-10 rounded-2xl border-2 border-dashed transition-all ${
                  isDragging
                    ? 'border-purple-500/60 bg-purple-500/5 ring-2 ring-purple-500/20'
                    : 'border-white/15 bg-white/[0.02] hover:border-white/25'
                }`}
              >
                <div className={`w-16 h-16 rounded-2xl flex items-center justify-center transition-all ${
                  isDragging ? 'bg-purple-500/15 border border-purple-500/30' : 'bg-white/5 border border-white/10'
                }`}>
                  <Package size={28} className={isDragging ? 'text-purple-400' : 'text-white/60'} />
                </div>

                <div className="text-center">
                  <h3 className="text-base font-semibold text-white mb-1">
                    {loading ? 'Analyzing package...' : 'Drop .hpersona file here'}
                  </h3>
                  <p className="text-sm text-white/40">
                    {loading ? 'Checking dependencies and validating contents' : 'or click to browse'}
                  </p>
                </div>

                {!loading && (
                  <label className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-white/10 hover:bg-white/15 border border-white/10 transition-colors cursor-pointer text-sm text-white font-medium">
                    <Upload size={16} />
                    Browse files
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept=".hpersona"
                      className="hidden"
                      onChange={handleFileChange}
                    />
                  </label>
                )}

                {loading && (
                  <div className="flex items-center gap-2 text-sm text-purple-300">
                    <div className="w-4 h-4 border-2 border-purple-400 border-t-transparent rounded-full animate-spin" />
                    Parsing package...
                  </div>
                )}
              </div>

              <div className="flex items-start gap-2 px-3 py-2.5 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                <Shield size={14} className="text-white/30 mt-0.5 shrink-0" />
                <p className="text-xs text-white/40 leading-relaxed">
                  .hpersona files contain persona configurations, avatar images, and model references.
                  No executable code is included. Tool and server dependencies are checked before installation.
                </p>
              </div>
            </div>
          )}

          {/* ── Step 1: Preview ── */}
          {step === 1 && preview && (
            <div className="space-y-5">

              {/* Persona card */}
              <div className="flex items-start gap-4 p-4 rounded-xl bg-white/[0.04] border border-white/[0.08]">
                <div className="w-16 h-16 rounded-xl overflow-hidden bg-gradient-to-br from-purple-500/20 to-pink-500/20 border border-white/10 flex items-center justify-center shrink-0">
                  {preview.avatar_preview_data_url ? (
                    <img
                      src={preview.avatar_preview_data_url}
                      alt={agentLabel}
                      className="block w-full h-full object-cover"
                    />
                  ) : preview.has_avatar ? (
                    <ImageIcon size={24} className="text-pink-400" />
                  ) : (
                    <Bot size={24} className="text-purple-400" />
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="text-lg font-semibold text-white">{agentLabel}</h3>
                  <div className="flex items-center gap-2 mt-1 flex-wrap">
                    {agentRole && <span className="text-xs text-white/50">{agentRole}</span>}
                    {tone && <span className="text-xs px-2 py-0.5 rounded-full bg-purple-500/15 text-purple-300 border border-purple-500/20">{tone}</span>}
                    {contentRating === 'nsfw' && (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-red-500/15 text-red-300 border border-red-500/20">NSFW</span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 mt-2 text-xs text-white/35">
                    {tools.length > 0 && <span>{tools.length} tools</span>}
                    {contents?.has_avatar && <span>Avatar included</span>}
                    {(contents?.outfit_count || 0) > 0 && <span>{contents!.outfit_count} outfits</span>}
                    <span>v{pkgVer} / schema {schemaVer}</span>
                  </div>
                </div>
              </div>

              {/* System prompt preview */}
              {preview.persona_agent?.system_prompt && (
                <div>
                  <div className="text-xs font-semibold text-white/50 mb-2">System Prompt</div>
                  <div className="text-sm text-white/60 bg-white/[0.03] border border-white/[0.06] rounded-xl px-4 py-3 max-h-24 overflow-y-auto custom-scrollbar leading-relaxed">
                    {preview.persona_agent.system_prompt.slice(0, 300)}
                    {preview.persona_agent.system_prompt.length > 300 ? '...' : ''}
                  </div>
                </div>
              )}

              {/* Dependencies */}
              {depCheck && (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="text-xs font-semibold text-white/50">Dependencies</div>
                    <div className={`text-xs px-2.5 py-0.5 rounded-full font-medium ${
                      depCheck.all_satisfied
                        ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/20'
                        : 'bg-amber-500/15 text-amber-300 border border-amber-500/20'
                    }`}>
                      {depCheck.summary}
                    </div>
                  </div>

                  {/* Models */}
                  {depCheck.models.length > 0 && (
                    <div>
                      <div className="flex items-center gap-2 mb-1.5">
                        <Cpu size={13} className="text-white/30" />
                        <span className="text-xs text-white/40 font-medium">Image Models</span>
                      </div>
                      <div className="space-y-1.5">
                        {depCheck.models.map((m, i) => <DependencyRow key={i} item={m} />)}
                      </div>
                    </div>
                  )}

                  {/* Tools */}
                  {depCheck.tools.length > 0 && (
                    <div>
                      <div className="flex items-center gap-2 mb-1.5">
                        <Wrench size={13} className="text-white/30" />
                        <span className="text-xs text-white/40 font-medium">Tools ({depCheck.tools.length})</span>
                      </div>
                      <div className="space-y-1.5 max-h-32 overflow-y-auto custom-scrollbar">
                        {depCheck.tools.map((t, i) => <DependencyRow key={i} item={t} />)}
                      </div>
                    </div>
                  )}

                  {/* MCP Servers */}
                  {depCheck.mcp_servers.length > 0 && (
                    <div>
                      <div className="flex items-center gap-2 mb-1.5">
                        <Server size={13} className="text-white/30" />
                        <span className="text-xs text-white/40 font-medium">MCP Servers ({depCheck.mcp_servers.length})</span>
                      </div>
                      <div className="space-y-1.5">
                        {depCheck.mcp_servers.map((s, i) => <DependencyRow key={i} item={s} />)}
                      </div>
                    </div>
                  )}

                  {/* A2A Agents */}
                  {depCheck.a2a_agents.length > 0 && (
                    <div>
                      <div className="flex items-center gap-2 mb-1.5">
                        <Bot size={13} className="text-white/30" />
                        <span className="text-xs text-white/40 font-medium">A2A Agents ({depCheck.a2a_agents.length})</span>
                      </div>
                      <div className="space-y-1.5">
                        {depCheck.a2a_agents.map((a, i) => <DependencyRow key={i} item={a} />)}
                      </div>
                    </div>
                  )}

                  {/* No dependencies */}
                  {depCheck.models.length === 0 && depCheck.tools.length === 0 &&
                   depCheck.mcp_servers.length === 0 && depCheck.a2a_agents.length === 0 && (
                    <div className="text-xs text-white/30 italic py-2">No external dependencies required</div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* ── Step 2: Complete ── */}
          {step === 2 && importedProject && (
            <div className="flex flex-col items-center py-8 space-y-6">
              <div className="w-20 h-20 rounded-full bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center">
                <Check size={36} className="text-emerald-400" />
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
                {preview?.has_avatar && (
                  <div className="flex items-center gap-2">
                    <Check size={14} className="text-emerald-400" />
                    Avatar committed to project storage
                  </div>
                )}
                {(preview?.manifest?.contents?.outfit_count || 0) > 0 && (
                  <div className="flex items-center gap-2">
                    <Check size={14} className="text-emerald-400" />
                    {preview!.manifest.contents!.outfit_count} outfits imported
                  </div>
                )}
                {(preview?.persona_agent?.allowed_tools?.length || 0) > 0 && (
                  <div className="flex items-center gap-2">
                    <Check size={14} className="text-emerald-400" />
                    {preview!.persona_agent.allowed_tools.length} tools configured
                  </div>
                )}
                {(preview?.dependency_check?.mcp_servers?.length || 0) > 0 && (
                  <div className="flex items-center gap-2">
                    <Check size={14} className="text-emerald-400" />
                    {preview!.dependency_check.mcp_servers.length} MCP server(s) referenced
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Error display */}
          {error && (
            <div className="mt-4 text-sm text-red-400 bg-red-500/10 border border-red-500/20 rounded-xl px-4 py-3">
              {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-white/10 bg-[#1a1a2e] flex justify-between items-center">
          {step === 0 && (
            <>
              <div />
              <button onClick={onClose} className="px-4 py-2 text-sm font-medium text-white/50 hover:text-white transition-colors">
                Cancel
              </button>
            </>
          )}

          {step === 1 && (
            <>
              <button
                onClick={() => { setStep(0); setFile(null); setPreview(null); setError(null) }}
                className="flex items-center gap-1 px-4 py-2 text-sm font-medium text-white/50 hover:text-white transition-colors"
              >
                <ChevronLeft size={16} />
                Back
              </button>
              <button
                onClick={handleImport}
                disabled={importing}
                className="flex items-center gap-2 px-6 py-2.5 bg-purple-500 hover:bg-purple-600 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-semibold rounded-full transition-colors"
              >
                {importing ? (
                  <>
                    <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                    Installing...
                  </>
                ) : (
                  <>
                    <Download size={16} />
                    Install Persona
                  </>
                )}
              </button>
            </>
          )}

          {step === 2 && (
            <>
              <div />
              <button
                onClick={onClose}
                className="px-6 py-2.5 bg-purple-500 hover:bg-purple-600 text-white text-sm font-semibold rounded-full transition-colors"
              >
                Done
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Export button (inline, for project cards)
// ---------------------------------------------------------------------------

export function PersonaExportButton({
  projectId,
  backendUrl,
  apiKey,
  className,
}: {
  projectId: string
  backendUrl: string
  apiKey?: string
  className?: string
}) {
  const [exporting, setExporting] = useState(false)

  const handleExport = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (exporting) return
    setExporting(true)
    try {
      await exportPersona({ backendUrl, apiKey, projectId })
    } catch (err: any) {
      alert(`Export failed: ${err.message}`)
    } finally {
      setExporting(false)
    }
  }

  return (
    <button
      onClick={handleExport}
      disabled={exporting}
      className={className || 'p-1.5 bg-purple-500/20 hover:bg-purple-500/40 rounded-lg text-purple-400 hover:text-purple-300 transition-colors disabled:opacity-40'}
      title="Export persona (.hpersona)"
    >
      {exporting ? (
        <div className="w-3.5 h-3.5 border-2 border-purple-400 border-t-transparent rounded-full animate-spin" />
      ) : (
        <Upload size={14} />
      )}
    </button>
  )
}
