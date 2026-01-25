/**
 * EditTab - Main component for the Edit mode workspace.
 *
 * REDESIGNED:
 * - Implements "Grok-like" Cyber-Noir aesthetic (True Black backgrounds)
 * - Centralized Canvas for immersive editing
 * - Floating "Conversational" Input Bar at the bottom
 * - Right-side "Studio" controls panel
 * - Horizontal Filmstrip for version history
 */

import React, { useCallback, useEffect, useRef, useState } from 'react'
import {
  Sparkles,
  Trash2,
  Upload,
  Loader2,
  Wand2,
  AlertCircle,
  Settings2,
  Download,
  History,
  ChevronRight,
  Maximize2,
  X
} from 'lucide-react'

import { EditDropzone } from './EditDropzone'
import {
  uploadToEditSession,
  sendEditMessage,
  selectActiveImage,
  clearEditSession,
  getEditSession,
  extractImages,
} from './editApi'
import type { EditTabProps } from './types'

// --- Sub-components for the new UI ---

const SliderControl = ({ label, value, defaultValue }: { label: string, value: string, defaultValue: number }) => (
  <div className="space-y-2 py-2">
    <div className="flex justify-between text-xs">
      <span className="text-white/60 font-medium">{label}</span>
      <span className="text-white/40">{value}</span>
    </div>
    <div className="relative h-1 w-full bg-white/10 rounded-full overflow-hidden">
      <div className="absolute h-full bg-white/40" style={{ width: `${defaultValue}%` }} />
    </div>
  </div>
)

export function EditTab({
  backendUrl,
  apiKey,
  conversationId,
  onOpenLightbox,
  provider,
  providerBaseUrl,
  providerModel,
}: EditTabProps) {
  // Refs
  const fileInputRef = useRef<HTMLInputElement>(null)
  const resultsEndRef = useRef<HTMLDivElement>(null)

  // State
  const [active, setActive] = useState<string | null>(null)
  const [history, setHistory] = useState<string[]>([])
  const [results, setResults] = useState<string[]>([])
  const [prompt, setPrompt] = useState('')
  const [lastPrompt, setLastPrompt] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [initialized, setInitialized] = useState(false)
  const [showSettings, setShowSettings] = useState(true)

  const hasImage = Boolean(active)

  // Load existing session on mount
  useEffect(() => {
    let cancelled = false
    const loadSession = async () => {
      try {
        const session = await getEditSession({ backendUrl, apiKey, conversationId })
        if (!cancelled) {
          setActive(session.active_image_url ?? null)
          setHistory(session.history ?? [])
          setInitialized(true)
        }
      } catch {
        if (!cancelled) setInitialized(true)
      }
    }
    loadSession()
    return () => { cancelled = true }
  }, [backendUrl, apiKey, conversationId])

  // Scroll to new results
  useEffect(() => {
    if (results.length > 0) {
      resultsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [results])

  // Handlers
  const handlePickFile = useCallback(async (file: File) => {
    setError(null); setBusy(true); setResults([]);
    try {
      const data = await uploadToEditSession({ backendUrl, apiKey, conversationId, file })
      setActive(data.active_image_url ?? null)
      setHistory(Array.isArray(data.history) ? data.history : [])
    } catch (e) { setError(e instanceof Error ? e.message : 'Upload failed') }
    finally { setBusy(false) }
  }, [backendUrl, apiKey, conversationId])

  const runEdit = useCallback(async (text: string) => {
    const trimmed = text.trim(); if (!trimmed) return
    setError(null); setBusy(true); setLastPrompt(trimmed); setResults([]) // Clear previous results on new run
    try {
      const out = await sendEditMessage({
        backendUrl, apiKey, conversationId, message: trimmed,
        provider, provider_base_url: providerBaseUrl, model: providerModel,
      })
      const imgs = extractImages(out.raw)
      setResults(imgs)
      // Optimistically add to history if we have results
      if (imgs.length) {
        setHistory((prev) => Array.from(new Set([...imgs, ...prev])).slice(0, 15))
      }
    } catch (e) { setError(e instanceof Error ? e.message : 'Edit failed') }
    finally { setBusy(false) }
  }, [backendUrl, apiKey, conversationId, provider, providerBaseUrl, providerModel])

  const handleUse = useCallback(async (url: string) => {
    setError(null); setBusy(true);
    try {
      const state = await selectActiveImage({ backendUrl, apiKey, conversationId, image_url: url })
      setActive(state.active_image_url ?? url)
      setHistory(state.history ?? [])
      setResults([]) // Clear results once used
    } catch (e) { setError(e instanceof Error ? e.message : 'Failed to set active image') }
    finally { setBusy(false) }
  }, [backendUrl, apiKey, conversationId])

  const handleReset = useCallback(async () => {
    setError(null); setBusy(true);
    try {
      await clearEditSession({ backendUrl, apiKey, conversationId })
      setActive(null); setHistory([]); setResults([]); setPrompt(''); setLastPrompt('');
    } catch (e) { setError(e instanceof Error ? e.message : 'Failed to reset') }
    finally { setBusy(false) }
  }, [backendUrl, apiKey, conversationId])

  const handleSubmit = useCallback((e?: React.FormEvent) => {
    e?.preventDefault()
    if (prompt.trim()) { runEdit(prompt); setPrompt('') }
  }, [prompt, runEdit])

  // Render Loading Screen
  if (!initialized) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-black">
        <div className="flex flex-col items-center gap-4 text-white/50">
          <Loader2 size={32} className="animate-spin text-white" />
          <span className="text-sm font-mono tracking-wider">INITIALIZING STUDIO...</span>
        </div>
      </div>
    )
  }

  return (
    <div className="relative flex h-full w-full bg-black text-white overflow-hidden font-sans">

      {/* --- Main Workspace (Canvas) --- */}
      <div className="flex-1 flex flex-col relative z-0">

        {/* Top Bar (Transparent) */}
        <div className="absolute top-0 left-0 right-0 p-6 flex items-start justify-between z-20 pointer-events-none">
          <div className="pointer-events-auto flex items-center gap-3">
             <div className="h-8 w-8 rounded-full bg-white/10 flex items-center justify-center backdrop-blur-md">
                <Sparkles size={16} className="text-white" />
             </div>
             <div>
                <h1 className="text-sm font-bold tracking-wide">EDIT STUDIO</h1>
                <p className="text-[10px] text-white/40 font-mono uppercase tracking-wider">
                  {hasImage ? 'Session Active' : 'No Image Loaded'}
                </p>
             </div>
          </div>

          <div className="pointer-events-auto flex gap-2">
             <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) handlePickFile(file)
                e.currentTarget.value = ''
              }}
            />
            {hasImage && (
              <>
                <button
                  onClick={() => fileInputRef.current?.click()}
                  className="p-2 rounded-lg bg-black/40 hover:bg-white/10 border border-white/10 text-white/70 hover:text-white transition-colors backdrop-blur-md"
                  title="Upload New"
                >
                  <Upload size={18} />
                </button>
                <button
                  onClick={handleReset}
                  className="p-2 rounded-lg bg-black/40 hover:bg-red-500/20 border border-white/10 text-white/70 hover:text-red-400 transition-colors backdrop-blur-md"
                  title="Reset Session"
                >
                  <Trash2 size={18} />
                </button>
                <button
                  onClick={() => setShowSettings(!showSettings)}
                  className={`p-2 rounded-lg border border-white/10 transition-colors backdrop-blur-md ${showSettings ? 'bg-white text-black' : 'bg-black/40 text-white/70 hover:text-white'}`}
                  title="Toggle Settings"
                >
                  <Settings2 size={18} />
                </button>
              </>
            )}
          </div>
        </div>

        {/* Canvas Area */}
        <div className="flex-1 relative flex items-center justify-center bg-[radial-gradient(circle_at_center,_var(--tw-gradient-stops))] from-white/5 to-black">
          {!hasImage ? (
            <div className="w-full max-w-xl px-6 relative z-10">
               <EditDropzone onPickFile={handlePickFile} disabled={busy} />
            </div>
          ) : (
            <div className="relative w-full h-full p-8 flex items-center justify-center">
               {/* The Active Image */}
               <div className="relative group max-w-full max-h-full shadow-2xl">
                  <img
                    src={active!}
                    alt="Active Canvas"
                    className="max-w-full max-h-[75vh] object-contain rounded-sm shadow-[0_0_50px_rgba(0,0,0,0.5)] border border-white/5"
                  />
                  {/* Hover Actions for Canvas */}
                  <div className="absolute bottom-4 right-4 flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity duration-200">
                    <button
                      onClick={() => active && onOpenLightbox(active)}
                      className="p-2 bg-black/80 text-white rounded-md hover:bg-white hover:text-black transition-colors"
                    >
                      <Maximize2 size={16} />
                    </button>
                    <a
                      href={active!}
                      download="edited-image.png"
                      className="p-2 bg-black/80 text-white rounded-md hover:bg-white hover:text-black transition-colors"
                    >
                      <Download size={16} />
                    </a>
                  </div>

                  {/* Processing Overlay */}
                  {busy && (
                    <div className="absolute inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center rounded-sm">
                      <div className="flex flex-col items-center gap-3">
                        <Loader2 size={32} className="animate-spin text-white" />
                        <span className="text-xs font-mono uppercase tracking-widest text-white/70">Processing Edit...</span>
                      </div>
                    </div>
                  )}
               </div>
            </div>
          )}
        </div>

        {/* Bottom Floating Bar (Input + History) */}
        {hasImage && (
          <div className="absolute bottom-0 left-0 right-0 z-20 flex flex-col items-center pb-6 px-4 bg-gradient-to-t from-black via-black/80 to-transparent pt-20">

            {/* Error Toast */}
            {error && (
              <div className="mb-4 flex items-center gap-3 px-4 py-3 bg-red-950/80 border border-red-500/30 rounded-lg backdrop-blur-xl animate-in fade-in slide-in-from-bottom-5">
                <AlertCircle size={16} className="text-red-400" />
                <span className="text-sm text-red-100">{error}</span>
                <button onClick={() => setError(null)} className="ml-2 text-red-400 hover:text-white"><X size={14}/></button>
              </div>
            )}

            {/* Input Bar (Grok Style) */}
            <div className="w-full max-w-3xl relative mb-8">
              <form onSubmit={handleSubmit} className="relative group">
                <div className="absolute inset-0 bg-white/5 rounded-2xl blur-xl group-hover:bg-white/10 transition-colors" />
                <div className="relative flex items-center bg-[#0A0A0A] border border-white/10 rounded-2xl shadow-2xl focus-within:border-white/30 transition-colors overflow-hidden">
                   <div className="pl-4 text-white/40">
                      <Wand2 size={20} />
                   </div>
                   <input
                      value={prompt}
                      onChange={(e) => setPrompt(e.target.value)}
                      placeholder={busy ? "Processing..." : "Describe changes naturally (e.g. 'Make the lighting cyberpunk', 'Add rain')..."}
                      className="flex-1 bg-transparent border-none text-white px-4 py-4 focus:ring-0 placeholder:text-white/30 text-base outline-none"
                      disabled={busy}
                   />
                   <div className="pr-3">
                      <button
                        type="submit"
                        disabled={!prompt.trim() || busy}
                        className="py-2 px-5 rounded-xl bg-white text-black hover:bg-gray-200 disabled:bg-white/10 disabled:text-white/30 disabled:cursor-not-allowed transition-all font-medium text-sm"
                      >
                        Generate
                      </button>
                   </div>
                </div>
              </form>
            </div>

            {/* Filmstrip (History/Results) */}
            <div className="w-full max-w-5xl flex gap-3 overflow-x-auto pb-4 px-2 pt-2 snap-x scrollbar-hide">
               {/* Current Results */}
               {results.map((url, idx) => (
                  <div key={`res-${idx}`} className="snap-center shrink-0 relative group w-24 h-24 rounded-lg overflow-hidden border-2 border-blue-500/50 cursor-pointer shadow-[0_0_20px_rgba(59,130,246,0.3)]">
                     <img src={url} className="w-full h-full object-cover" alt="Result" />
                     <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity flex flex-col items-center justify-center gap-1">
                        <button onClick={() => handleUse(url)} className="text-[10px] font-bold bg-white text-black px-2 py-1 rounded hover:scale-105 transition-transform">
                           USE THIS
                        </button>
                        <button onClick={() => onOpenLightbox(url)} className="text-white/70 hover:text-white"><Maximize2 size={12}/></button>
                     </div>
                  </div>
               ))}

               {/* Divider */}
               {results.length > 0 && history.length > 0 && (
                  <div className="w-px h-16 bg-white/10 shrink-0 self-center mx-2" />
               )}

               {/* History Items */}
               {history.map((url, idx) => (
                  <div key={`hist-${idx}`} className={`snap-center shrink-0 relative group w-20 h-20 rounded-lg overflow-hidden border border-white/10 cursor-pointer hover:border-white/40 transition-colors ${active === url ? 'ring-1 ring-white' : ''}`}>
                     <img src={url} className="w-full h-full object-cover opacity-60 group-hover:opacity-100 transition-opacity" alt="History" />
                     <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 flex items-center justify-center">
                        <button onClick={() => handleUse(url)} className="p-1.5 bg-white/10 rounded-full hover:bg-white hover:text-black backdrop-blur-md transition-colors">
                           <History size={12} />
                        </button>
                     </div>
                  </div>
               ))}
               <div ref={resultsEndRef} />
            </div>
          </div>
        )}
      </div>

      {/* --- Right Settings Panel (Collapsible) --- */}
      {hasImage && (
        <div className={`border-l border-white/10 bg-[#050505] transition-all duration-300 ease-in-out flex flex-col ${showSettings ? 'w-80 translate-x-0' : 'w-0 translate-x-full opacity-0 overflow-hidden'}`}>
           <div className="p-5 border-b border-white/10 flex items-center justify-between">
              <h3 className="font-bold text-sm tracking-wide flex items-center gap-2">
                <Settings2 size={16} />
                PARAMETERS
              </h3>
              <button onClick={() => setShowSettings(false)} className="text-white/40 hover:text-white">
                <ChevronRight size={18} />
              </button>
           </div>

           <div className="flex-1 overflow-y-auto p-5 space-y-8">
              {/* Mock Controls based on 'Imagine' tab style */}
              <div className="space-y-4">
                 <div className="flex items-center justify-between text-xs uppercase tracking-wider text-white/40 font-semibold">
                    Edit Strength
                 </div>
                 <SliderControl label="Guidance Scale" value="7.5" defaultValue={60} />
                 <SliderControl label="Denoising Strength" value="0.65" defaultValue={65} />
              </div>

              <div className="space-y-4">
                 <div className="flex items-center justify-between text-xs uppercase tracking-wider text-white/40 font-semibold">
                    Style Locks
                 </div>
                 <div className="space-y-2">
                    {['Face Detailer', 'Color Match', 'Structure Lock'].map(opt => (
                       <div key={opt} className="flex items-center justify-between p-3 rounded-lg bg-white/5 border border-white/5 hover:border-white/20 cursor-pointer transition-colors group">
                          <span className="text-sm text-white/80">{opt}</span>
                          <div className="w-8 h-4 rounded-full bg-white/10 relative">
                             <div className="absolute right-0.5 top-0.5 w-3 h-3 rounded-full bg-white/20 group-hover:bg-white/50" />
                          </div>
                       </div>
                    ))}
                 </div>
              </div>

              <div className="p-4 rounded-xl bg-blue-900/10 border border-blue-500/20 text-xs text-blue-200/70 leading-relaxed">
                 <span className="font-bold text-blue-400 block mb-1">PRO TIP</span>
                 Select specific areas in the "Brush" mode (coming soon) for targeted in-painting results.
              </div>
           </div>
        </div>
      )}
    </div>
  )
}

export default EditTab
