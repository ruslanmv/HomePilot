/**
 * EditDropzone - Initial upload area for the Edit tab.
 *
 * Dual primary action pattern (industry best practice):
 *   [ Upload Image ]   [ Create Avatar ]
 *
 * - Upload Image: standard file upload (drag & drop + click)
 * - Create Avatar: navigates to Avatar Studio to generate a character
 *
 * The two buttons are equal hierarchy, with Create Avatar using a purple
 * gradient to signal "creative / identity-related" intent.
 */

import React, { useCallback, useState } from 'react'
import { Image as ImageIcon, Upload, Sparkles } from 'lucide-react'
import type { EditDropzoneProps } from './types'

export function EditDropzone({ onPickFile, disabled, onCreateAvatar }: EditDropzoneProps) {
  const [isDragging, setIsDragging] = useState(false)

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (!disabled) {
      setIsDragging(true)
    }
  }, [disabled])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
  }, [])

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      e.stopPropagation()
      setIsDragging(false)

      if (disabled) return

      const file = e.dataTransfer.files?.[0]
      if (file && file.type.startsWith('image/')) {
        onPickFile(file)
      }
    },
    [onPickFile, disabled]
  )

  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0]
      if (file) {
        onPickFile(file)
      }
      // Reset input to allow re-selecting the same file
      e.currentTarget.value = ''
    },
    [onPickFile]
  )

  return (
    <div
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className={[
        'rounded-2xl border bg-white/5 transition-all duration-200',
        'p-10 text-center shadow-2xl ring-1',
        isDragging
          ? 'border-blue-500/50 ring-blue-500/30 bg-blue-500/5'
          : 'border-white/10 ring-white/10',
        disabled ? 'opacity-50 cursor-not-allowed' : '',
      ].join(' ')}
    >
      {/* Icon */}
      <div
        className={[
          'mx-auto size-14 rounded-2xl bg-white/5 border border-white/10',
          'flex items-center justify-center transition-colors',
          isDragging ? 'bg-blue-500/10 border-blue-500/30' : '',
        ].join(' ')}
      >
        <ImageIcon size={24} className={isDragging ? 'text-blue-400' : 'text-white/80'} />
      </div>

      {/* Title */}
      <h2 className="mt-5 text-lg font-bold text-white">
        Start editing
      </h2>

      {/* Description */}
      <p className="mt-2 text-sm text-white/50 max-w-md mx-auto">
        Upload an existing image to edit, or create a new avatar character
        from scratch.
      </p>

      {/* Dual primary actions */}
      <div className="mt-6 flex items-center justify-center gap-3 flex-wrap">
        {/* Upload Image — primary action */}
        <label
          className={[
            'cursor-pointer inline-flex items-center gap-2',
            'px-5 py-2.5 rounded-xl bg-white/10 hover:bg-white/15',
            'border border-white/10 hover:border-white/20 transition-all',
            'text-sm font-semibold text-white',
            disabled ? 'pointer-events-none opacity-50' : '',
          ].join(' ')}
          aria-label="Upload an image to edit"
        >
          <Upload size={16} />
          <span>Upload Image</span>
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="hidden"
            onChange={handleFileChange}
            disabled={disabled}
          />
        </label>

        {/* Create Avatar — secondary creative action */}
        {onCreateAvatar && (
          <button
            type="button"
            onClick={onCreateAvatar}
            disabled={disabled}
            className={[
              'inline-flex items-center gap-2',
              'px-5 py-2.5 rounded-xl',
              'bg-gradient-to-r from-purple-600/80 to-pink-600/80',
              'hover:from-purple-500 hover:to-pink-500',
              'border border-purple-500/30 hover:border-purple-400/50',
              'text-sm font-semibold text-white',
              'shadow-lg shadow-purple-500/10 hover:shadow-purple-500/20',
              'transition-all',
              disabled ? 'pointer-events-none opacity-50' : '',
            ].join(' ')}
            aria-label="Create a reusable avatar character"
          >
            <Sparkles size={16} />
            <span>Create Avatar</span>
          </button>
        )}
      </div>

      {/* Subtext for Create Avatar */}
      {onCreateAvatar && (
        <p className="mt-3 text-[11px] text-white/30">
          Create a reusable character from photos
        </p>
      )}

      {/* Drag hint */}
      <p className="mt-4 text-xs text-white/30">
        Supports PNG, JPEG, and WebP — drag & drop or click Upload
      </p>
    </div>
  )
}

export default EditDropzone
