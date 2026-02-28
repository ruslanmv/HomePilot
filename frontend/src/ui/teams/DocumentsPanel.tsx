/**
 * DocumentsPanel — Shared documents tab for the meeting right rail.
 *
 * Features:
 *   - Upload files (txt/md/pdf)
 *   - Add URL links
 *   - List documents with type icons
 *   - Preview text files
 *   - Download files
 *   - Delete documents
 *
 * Additive — lives inside MeetingRightRail as a tab.
 */

import React, { useEffect, useMemo, useState, useRef } from 'react'
import {
  FileText,
  Link as LinkIcon,
  Upload,
  Trash2,
  Eye,
  Download,
  Plus,
  X,
} from 'lucide-react'
import type { TeamDocument } from './types'
import { useTeamsDocuments } from './useTeamsDocuments'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface DocumentsPanelProps {
  backendUrl: string
  apiKey?: string
  roomId: string
  initialDocuments?: TeamDocument[]
  onDocumentsChanged?: (docs: TeamDocument[]) => void
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function DocumentsPanel({
  backendUrl,
  apiKey,
  roomId,
  initialDocuments,
  onDocumentsChanged,
}: DocumentsPanelProps) {
  const docsApi = useTeamsDocuments(backendUrl, apiKey)

  const [docs, setDocs] = useState<TeamDocument[]>(initialDocuments || [])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [previewText, setPreviewText] = useState('')
  const [busy, setBusy] = useState(false)
  const [showUrlForm, setShowUrlForm] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const selected = useMemo(() => docs.find((d) => d.id === selectedId) || null, [docs, selectedId])

  // Lazy refresh on mount
  useEffect(() => {
    ;(async () => {
      try {
        const list = await docsApi.list(roomId)
        setDocs(list)
        onDocumentsChanged?.(list)
      } catch {
        // keep local state
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roomId])

  const iconFor = (d: TeamDocument) => {
    if (d.kind === 'url') return <LinkIcon size={12} className="text-blue-400/60" />
    const t = d.type
    if (t === 'pdf') return <FileText size={12} className="text-red-400/60" />
    if (t === 'md') return <FileText size={12} className="text-purple-400/60" />
    return <FileText size={12} className="text-white/35" />
  }

  const sizeLabel = (bytes?: number) => {
    if (typeof bytes !== 'number') return ''
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  async function handleUpload(file: File) {
    setBusy(true)
    try {
      const res = await docsApi.upload(roomId, file)
      const list = await docsApi.list(roomId)
      setDocs(list)
      onDocumentsChanged?.(list)
      setSelectedId(res.document.id)
    } catch (e) {
      console.error('Upload failed:', e)
    } finally {
      setBusy(false)
    }
  }

  async function handlePreview(docId: string) {
    setBusy(true)
    try {
      const text = await docsApi.preview(roomId, docId)
      setPreviewText(text)
      setSelectedId(docId)
    } catch (e) {
      console.error('Preview failed:', e)
      setPreviewText('[Failed to load preview]')
    } finally {
      setBusy(false)
    }
  }

  async function handleDelete(docId: string) {
    setBusy(true)
    try {
      await docsApi.deleteDoc(roomId, docId)
      const list = await docsApi.list(roomId)
      setDocs(list)
      onDocumentsChanged?.(list)
      if (selectedId === docId) {
        setSelectedId(null)
        setPreviewText('')
      }
    } catch (e) {
      console.error('Delete failed:', e)
    } finally {
      setBusy(false)
    }
  }

  async function handleDownload(doc: TeamDocument) {
    setBusy(true)
    try {
      await docsApi.download(roomId, doc)
    } catch (e) {
      console.error('Download failed:', e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="h-full flex flex-col">
      {/* Actions row */}
      <div className="flex items-center gap-1.5 mb-2">
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={busy}
          className="flex items-center gap-1 px-2 py-1.5 rounded-lg bg-white/[0.04] border border-white/[0.08] text-[10px] text-white/50 hover:bg-white/[0.06] hover:text-white/70 transition-colors"
        >
          <Upload size={11} />
          Upload
        </button>
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) handleUpload(f)
            e.currentTarget.value = ''
          }}
        />
        <button
          onClick={() => setShowUrlForm(!showUrlForm)}
          disabled={busy}
          className={`flex items-center gap-1 px-2 py-1.5 rounded-lg border text-[10px] transition-colors ${
            showUrlForm
              ? 'bg-cyan-500/10 border-cyan-500/20 text-cyan-300'
              : 'bg-white/[0.04] border-white/[0.08] text-white/50 hover:bg-white/[0.06] hover:text-white/70'
          }`}
        >
          <LinkIcon size={11} />
          Add Link
        </button>
      </div>

      {/* URL form */}
      {showUrlForm && (
        <AddUrlForm
          disabled={busy}
          onAdd={async (url, title) => {
            setBusy(true)
            try {
              await docsApi.addUrl(roomId, url, title)
              const list = await docsApi.list(roomId)
              setDocs(list)
              onDocumentsChanged?.(list)
              setShowUrlForm(false)
            } catch (e) {
              console.error('Add URL failed:', e)
            } finally {
              setBusy(false)
            }
          }}
          onCancel={() => setShowUrlForm(false)}
        />
      )}

      {/* Document list */}
      <div className="flex-1 min-h-0 overflow-y-auto space-y-1.5 scrollbar-hide">
        {docs.length === 0 && (
          <div className="text-center py-4">
            <FileText size={18} className="mx-auto text-white/10 mb-1.5" />
            <p className="text-[10px] text-white/20">No shared documents yet</p>
            <p className="text-[9px] text-white/12 mt-0.5">Upload a file or add a link</p>
          </div>
        )}
        {docs.map((d) => (
          <div
            key={d.id}
            className={`rounded-lg border p-2.5 transition-colors ${
              selectedId === d.id
                ? 'bg-cyan-500/[0.06] border-cyan-500/15'
                : 'bg-white/[0.02] border-white/[0.04] hover:border-white/[0.08]'
            }`}
          >
            <div className="flex items-start gap-2">
              <div className="mt-0.5 flex-shrink-0">{iconFor(d)}</div>
              <div className="flex-1 min-w-0">
                <div className="text-[10px] text-white/65 font-medium truncate">{d.name}</div>
                <div className="text-[9px] text-white/25 mt-0.5">
                  {d.kind === 'url' ? 'Link' : (d.type || 'file').toUpperCase()}
                  {d.size_bytes ? ` · ${sizeLabel(d.size_bytes)}` : ''}
                  {d.uploaded_by ? ` · ${d.uploaded_by}` : ''}
                </div>
              </div>
            </div>
            {/* Action buttons */}
            <div className="flex items-center gap-1 mt-1.5">
              <button
                disabled={busy}
                onClick={() => handlePreview(d.id)}
                className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] text-white/35 hover:text-white/60 hover:bg-white/[0.04] transition-colors"
              >
                <Eye size={9} /> Preview
              </button>
              {d.kind === 'file' && (
                <button
                  disabled={busy}
                  onClick={() => handleDownload(d)}
                  className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] text-white/35 hover:text-white/60 hover:bg-white/[0.04] transition-colors"
                >
                  <Download size={9} /> Download
                </button>
              )}
              <button
                disabled={busy}
                onClick={() => handleDelete(d.id)}
                className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] text-white/35 hover:text-red-300/70 hover:bg-red-500/[0.06] transition-colors ml-auto"
              >
                <Trash2 size={9} />
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* Preview pane */}
      {selected && previewText && (
        <div className="mt-2 rounded-lg border border-white/[0.06] bg-white/[0.02] p-2.5">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[9px] text-white/30 font-medium truncate">{selected.name}</span>
            <button
              onClick={() => { setSelectedId(null); setPreviewText('') }}
              className="p-0.5 rounded hover:bg-white/5 text-white/20 hover:text-white/40"
            >
              <X size={10} />
            </button>
          </div>
          <pre className="text-[10px] leading-relaxed text-white/55 whitespace-pre-wrap max-h-32 overflow-y-auto scrollbar-hide font-mono">
            {previewText}
          </pre>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sub-component: Add URL form
// ---------------------------------------------------------------------------

function AddUrlForm({
  disabled,
  onAdd,
  onCancel,
}: {
  disabled?: boolean
  onAdd: (url: string, title: string) => void
  onCancel: () => void
}) {
  const [url, setUrl] = useState('')
  const [title, setTitle] = useState('')

  return (
    <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-2.5 mb-2 space-y-1.5">
      <input
        disabled={disabled}
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Title (optional)"
        className="w-full px-2.5 py-1.5 rounded-lg bg-white/[0.04] border border-white/[0.06] text-[10px] text-white/70 placeholder:text-white/15 focus:outline-none focus:border-cyan-500/30"
      />
      <div className="flex items-center gap-1.5">
        <input
          disabled={disabled}
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://..."
          className="flex-1 px-2.5 py-1.5 rounded-lg bg-white/[0.04] border border-white/[0.06] text-[10px] text-white/70 placeholder:text-white/15 focus:outline-none focus:border-cyan-500/30"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && url.trim()) {
              onAdd(url.trim(), title.trim())
              setUrl('')
              setTitle('')
            }
          }}
        />
        <button
          disabled={disabled || !url.trim()}
          onClick={() => {
            if (!url.trim()) return
            onAdd(url.trim(), title.trim())
            setUrl('')
            setTitle('')
          }}
          className={`px-2.5 py-1.5 rounded-lg text-[10px] font-medium border transition-colors ${
            url.trim() && !disabled
              ? 'bg-cyan-600/80 hover:bg-cyan-500 border-cyan-500/30 text-white'
              : 'bg-white/[0.04] border-white/[0.06] text-white/15'
          }`}
        >
          <Plus size={11} />
        </button>
        <button
          onClick={onCancel}
          className="px-1.5 py-1.5 rounded-lg text-[10px] text-white/25 hover:text-white/45 hover:bg-white/[0.04] transition-colors"
        >
          <X size={11} />
        </button>
      </div>
    </div>
  )
}
