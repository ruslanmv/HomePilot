/**
 * EditDropzone - Initial upload area for the Edit tab.
 *
 * Single primary action: upload an image to start editing.
 * Avatar creation has moved to the dedicated Avatar tab.
 */

import React, { useCallback, useState } from 'react'
import { Image as ImageIcon, Upload } from 'lucide-react'
import type { EditDropzoneProps } from './types'

export function EditDropzone({ onPickFile, disabled }: EditDropzoneProps) {
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
        Upload an image to start editing with AI-powered tools.
      </p>

      {/* Upload action */}
      <div className="mt-6 flex items-center justify-center gap-3 flex-wrap">
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
      </div>

      {/* Drag hint */}
      <p className="mt-4 text-xs text-white/30">
        Supports PNG, JPEG, and WebP — drag & drop or click Upload
      </p>
    </div>
  )
}

export default EditDropzone
