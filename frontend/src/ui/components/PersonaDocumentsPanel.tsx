/**
 * PersonaDocumentsPanel — manages documents attached to a persona for
 * Chat-with-Docs (RAG).
 *
 * Features:
 *   - Upload new documents (PDF/TXT/MD)
 *   - List attached docs with indexing status
 *   - Toggle mode: indexed / pinned / excluded
 *   - Detach (safe remove) documents
 */

import React, { useState, useEffect, useCallback, useRef } from 'react'
import {
  Upload,
  FileText,
  Loader2,
  BookOpen,
  Pin,
  EyeOff,
  Trash2,
  CheckCircle2,
  AlertCircle,
  Clock,
  RefreshCw,
} from 'lucide-react'
import type { PersonaDocument } from '../inventoryApi'
import {
  listPersonaDocuments,
  uploadProjectItem,
  attachPersonaDocument,
  setPersonaDocumentMode,
  deletePersonaDocumentPermanently,
} from '../inventoryApi'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Props = {
  projectId: string
  backendUrl: string
  apiKey?: string
  /** Called after documents are added or removed so parent can refresh counts */
  onChanged?: () => void
}

// ---------------------------------------------------------------------------
// Mode config
// ---------------------------------------------------------------------------

const MODE_CONFIG: Record<string, { label: string; icon: React.ElementType; color: string; desc: string }> = {
  indexed: { label: 'Indexed', icon: BookOpen, color: 'text-green-400', desc: 'Included in RAG retrieval' },
  pinned: { label: 'Pinned', icon: Pin, color: 'text-amber-400', desc: 'Always included (boosted)' },
  excluded: { label: 'Excluded', icon: EyeOff, color: 'text-red-400', desc: 'Excluded from retrieval' },
}

const STATUS_CONFIG: Record<string, { label: string; icon: React.ElementType; color: string }> = {
  ready: { label: 'Ready', icon: CheckCircle2, color: 'text-green-400' },
  indexing: { label: 'Indexing...', icon: Loader2, color: 'text-amber-400' },
  error: { label: 'Error', icon: AlertCircle, color: 'text-red-400' },
  not_indexed: { label: 'Not indexed', icon: Clock, color: 'text-white/30' },
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function PersonaDocumentsPanel({ projectId, backendUrl, apiKey, onChanged }: Props) {
  const [docs, setDocs] = useState<PersonaDocument[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [actionInProgress, setActionInProgress] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // -----------------------------------------------------------------------
  // Load documents
  // -----------------------------------------------------------------------
  const loadDocs = useCallback(async () => {
    try {
      const data = await listPersonaDocuments(backendUrl, projectId, { apiKey })
      setDocs(data.documents || [])
      setError(null)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [backendUrl, projectId, apiKey])

  useEffect(() => { loadDocs() }, [loadDocs])

  // -----------------------------------------------------------------------
  // Upload handler
  // -----------------------------------------------------------------------
  const handleUpload = useCallback(async (files: FileList | null) => {
    if (!files || files.length === 0) return
    setUploading(true)
    setError(null)

    for (const file of Array.from(files)) {
      try {
        // 1. Upload file as project item
        const result = await uploadProjectItem(backendUrl, projectId, file, {
          apiKey,
          category: 'file',
        })
        if (result.ok && result.item?.id) {
          // 2. Attach to persona with mode=indexed
          await attachPersonaDocument(backendUrl, projectId, result.item.id, 'indexed', { apiKey })
        }
      } catch (e: any) {
        setError(`Upload failed for ${file.name}: ${e.message}`)
      }
    }

    setUploading(false)
    loadDocs()
    onChanged?.()
  }, [backendUrl, projectId, apiKey, loadDocs, onChanged])

  // -----------------------------------------------------------------------
  // Mode change handler
  // -----------------------------------------------------------------------
  const handleModeChange = useCallback(async (itemId: string, newMode: string) => {
    setActionInProgress(itemId)
    try {
      await setPersonaDocumentMode(backendUrl, projectId, itemId, newMode, { apiKey })
      loadDocs()
    } catch (e: any) {
      setError(e.message)
    } finally {
      setActionInProgress(null)
    }
  }, [backendUrl, projectId, apiKey, loadDocs])

  // -----------------------------------------------------------------------
  // Delete handler — removes document from persona AND from storage
  // -----------------------------------------------------------------------
  const handleDelete = useCallback(async (doc: PersonaDocument) => {
    if (!confirm(`Delete "${doc.original_name || doc.name}"? This will remove the file from storage.`)) return
    setActionInProgress(doc.id)
    try {
      await deletePersonaDocumentPermanently(backendUrl, projectId, doc.id, { apiKey })
      loadDocs()
      onChanged?.()
    } catch (e: any) {
      setError(e.message)
    } finally {
      setActionInProgress(null)
    }
  }, [backendUrl, projectId, apiKey, loadDocs, onChanged])


  // -----------------------------------------------------------------------
  // Render: document row
  // -----------------------------------------------------------------------
  const renderDocRow = (doc: PersonaDocument) => {
    const props = doc.properties || {}
    const status = props.index_status || 'not_indexed'
    const statusCfg = STATUS_CONFIG[status] || STATUS_CONFIG.not_indexed
    const modeCfg = MODE_CONFIG[doc.mode] || MODE_CONFIG.indexed
    const StatusIcon = statusCfg.icon
    const isActive = actionInProgress === doc.id

    const ext = (doc.original_name || doc.name || '').split('.').pop()?.toUpperCase() || 'FILE'
    const sizeStr = doc.size_bytes > 1048576
      ? `${(doc.size_bytes / 1048576).toFixed(1)} MB`
      : doc.size_bytes > 0
        ? `${Math.round(doc.size_bytes / 1024)} KB`
        : ''

    return (
      <div
        key={doc.id}
        className={[
          'flex items-center gap-3 px-3 py-2.5 rounded-lg border transition-all',
          isActive ? 'opacity-40 pointer-events-none' : '',
          'bg-white/[0.03] border-white/10 hover:bg-white/[0.06] hover:border-white/15',
        ].join(' ')}
      >
        {/* File icon */}
        <div className="w-9 h-9 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center shrink-0">
          <FileText size={16} className="text-blue-400/70" />
        </div>

        {/* Name + meta */}
        <div className="flex-1 min-w-0">
          <div className="text-xs text-white font-medium truncate">
            {doc.original_name || doc.name}
          </div>
          <div className="flex items-center gap-2 mt-0.5">
            <span className="text-[9px] text-white/25 uppercase">{ext}</span>
            {sizeStr && <span className="text-[9px] text-white/25">{sizeStr}</span>}
            {/* Index status */}
            <span className={`text-[9px] flex items-center gap-0.5 ${statusCfg.color}`}>
              <StatusIcon size={9} className={status === 'indexing' ? 'animate-spin' : ''} />
              {statusCfg.label}
            </span>
            {props.chunk_count != null && props.chunk_count > 0 && (
              <span className="text-[9px] text-white/20">{props.chunk_count} chunks</span>
            )}
          </div>
        </div>

        {/* Mode selector */}
        <div className="flex items-center gap-1 shrink-0">
          {(['indexed', 'pinned', 'excluded'] as const).map((m) => {
            const cfg = MODE_CONFIG[m]
            const MIcon = cfg.icon
            const active = doc.mode === m
            return (
              <button
                key={m}
                title={`${cfg.label}: ${cfg.desc}`}
                onClick={() => { if (!active) handleModeChange(doc.id, m) }}
                className={[
                  'p-1 rounded transition-all',
                  active
                    ? `${cfg.color} bg-white/10`
                    : 'text-white/20 hover:text-white/40 hover:bg-white/5',
                ].join(' ')}
              >
                <MIcon size={12} />
              </button>
            )
          })}
        </div>

        {/* Delete button */}
        <button
          title="Remove document"
          onClick={() => handleDelete(doc)}
          className="p-1 rounded text-white/15 hover:text-red-400/70 hover:bg-red-500/10 transition-all shrink-0"
        >
          <Trash2 size={12} />
        </button>
      </div>
    )
  }

  // -----------------------------------------------------------------------
  // Main render
  // -----------------------------------------------------------------------
  return (
    <div className="space-y-3">
      {/* Header with upload button */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BookOpen size={14} className="text-blue-400/60" />
          <span className="text-xs text-white/60 font-medium">Knowledge Base</span>
          <span className="text-[10px] text-white/25">({docs.length} docs)</span>
        </div>
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
          className="flex items-center gap-1.5 px-2.5 py-1.5 text-[10px] font-medium rounded-lg bg-blue-500/15 text-blue-400 hover:bg-blue-500/25 border border-blue-500/20 transition-all disabled:opacity-40"
        >
          {uploading ? (
            <Loader2 size={11} className="animate-spin" />
          ) : (
            <Upload size={11} />
          )}
          Add Document
        </button>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".pdf,.txt,.md,.doc,.docx,.csv,.json,.yaml,.yml"
          className="hidden"
          onChange={(e) => handleUpload(e.target.files)}
        />
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/20 text-[10px] text-red-400">
          <AlertCircle size={12} />
          {error}
          <button onClick={() => setError(null)} className="ml-auto text-red-400/50 hover:text-red-400">dismiss</button>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-8">
          <Loader2 size={18} className="animate-spin text-white/20" />
        </div>
      )}

      {/* Document list */}
      {!loading && docs.length === 0 && (
        <div className="flex flex-col items-center justify-center py-8 gap-2 text-white/20">
          <FileText size={24} className="text-white/10" />
          <p className="text-[10px]">No documents attached to this persona.</p>
          <p className="text-[9px] text-white/15">Add PDFs, text, or markdown files to enable Chat-with-Docs.</p>
        </div>
      )}

      {!loading && docs.length > 0 && (
        <div className="space-y-1.5">
          {docs.map(renderDocRow)}
        </div>
      )}

      {/* Refresh */}
      {!loading && docs.length > 0 && (
        <div className="flex justify-center pt-1">
          <button
            onClick={loadDocs}
            className="flex items-center gap-1 text-[9px] text-white/20 hover:text-white/40 transition-colors"
          >
            <RefreshCw size={9} />
            Refresh
          </button>
        </div>
      )}
    </div>
  )
}
