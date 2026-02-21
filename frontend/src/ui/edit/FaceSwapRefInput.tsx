/**
 * FaceSwapRefInput — inline reference image picker for Face Swap.
 *
 * Additive component — rendered below the Face Swap button in IdentityTools
 * when user clicks Face Swap and no reference is yet set.
 *
 * Compact inline variant — upload zone + URL input.
 * Same pattern as AvatarStudio reference upload.
 */

import React, { useState, useCallback, useRef } from 'react'
import { Upload, X, Loader2, Check } from 'lucide-react'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface FaceSwapRefInputProps {
  backendUrl: string
  apiKey?: string
  onReferenceReady: (url: string) => void
  onCancel: () => void
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function FaceSwapRefInput({
  backendUrl,
  apiKey,
  onReferenceReady,
  onCancel,
}: FaceSwapRefInputProps) {
  const [uploading, setUploading] = useState(false)
  const [preview, setPreview] = useState<string | null>(null)
  const [urlInput, setUrlInput] = useState('')
  const [error, setError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleFileUpload = useCallback(
    async (file: File) => {
      setUploading(true)
      setError(null)

      // Show local preview immediately
      const localPreview = URL.createObjectURL(file)
      setPreview(localPreview)

      // Upload to backend
      const formData = new FormData()
      formData.append('file', file)
      const base = (backendUrl || '').replace(/\/+$/, '')
      const headers: Record<string, string> = {}
      if (apiKey) headers['x-api-key'] = apiKey

      try {
        const res = await fetch(`${base}/upload`, {
          method: 'POST',
          headers,
          body: formData,
        })
        if (res.ok) {
          const data = await res.json()
          const uploadedUrl = data.url || data.file_url || ''
          if (uploadedUrl) {
            onReferenceReady(uploadedUrl)
          } else {
            setError('Upload succeeded but no URL returned')
          }
        } else {
          setError(`Upload failed: ${res.status}`)
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Upload failed')
      } finally {
        setUploading(false)
      }
    },
    [backendUrl, apiKey, onReferenceReady],
  )

  const handleUrlSubmit = useCallback(() => {
    const trimmed = urlInput.trim()
    if (trimmed) {
      onReferenceReady(trimmed)
    }
  }, [urlInput, onReferenceReady])

  return (
    <div className="mt-2 p-3 rounded-xl bg-cyan-500/5 border border-cyan-500/20 space-y-2.5 animate-fadeIn">
      <div className="flex items-center justify-between">
        <div className="text-[11px] text-cyan-300/60 font-medium">
          Upload the face to swap onto this image
        </div>
        <button
          onClick={onCancel}
          className="p-1 rounded-md text-white/30 hover:text-white/60 hover:bg-white/5 transition-colors"
        >
          <X size={14} />
        </button>
      </div>

      <div className="flex items-center gap-2">
        {/* Upload button */}
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
          className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-xs font-medium transition-all ${
            uploading
              ? 'border-cyan-500/30 bg-cyan-500/10 text-cyan-300'
              : 'border-white/10 bg-white/5 text-white/60 hover:bg-cyan-500/10 hover:border-cyan-500/30 hover:text-cyan-200'
          }`}
        >
          {uploading ? (
            <Loader2 size={14} className="animate-spin" />
          ) : preview ? (
            <Check size={14} className="text-green-400" />
          ) : (
            <Upload size={14} />
          )}
          {uploading ? 'Uploading...' : 'Upload face'}
        </button>

        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) handleFileUpload(file)
            e.target.value = ''
          }}
        />

        {/* Preview thumbnail */}
        {preview && !uploading && (
          <div className="w-9 h-9 rounded-lg overflow-hidden border border-white/10 flex-shrink-0">
            <img src={preview} alt="Face preview" className="w-full h-full object-cover" />
          </div>
        )}

        {/* URL input */}
        {!preview && !uploading && (
          <div className="flex-1 flex items-center gap-1.5">
            <span className="text-[10px] text-white/20">or</span>
            <input
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              placeholder="Paste image URL..."
              className="flex-1 px-2 py-1.5 rounded-lg bg-white/5 border border-white/10 text-white text-[11px] placeholder:text-white/20 focus:outline-none focus:border-cyan-500/50 transition-all"
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleUrlSubmit()
              }}
            />
            {urlInput.trim() && (
              <button
                onClick={handleUrlSubmit}
                className="px-2 py-1.5 rounded-lg bg-cyan-500/20 text-cyan-300 text-[11px] font-medium hover:bg-cyan-500/30 transition-colors"
              >
                Use
              </button>
            )}
          </div>
        )}
      </div>

      {error && (
        <div className="text-[10px] text-red-400">{error}</div>
      )}
    </div>
  )
}
