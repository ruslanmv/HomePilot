/**
 * MaskCanvas - Canvas overlay component for drawing inpainting masks.
 *
 * Features:
 * - Canvas overlay on top of the image
 * - Brush drawing with adjustable size and opacity
 * - Eraser mode
 * - Undo/Redo support
 * - Clear mask
 * - Export mask as data URL
 */

import React, { useCallback, useEffect, useRef, useState } from 'react'
import {
  Brush,
  Eraser,
  Undo2,
  Redo2,
  Trash2,
  Eye,
  EyeOff,
  Check,
  X,
} from 'lucide-react'

export interface MaskCanvasProps {
  /** URL of the image to draw mask on */
  imageUrl: string
  /** Callback when mask is saved - receives mask as data URL */
  onSaveMask: (maskDataUrl: string) => void
  /** Callback when mask drawing is cancelled */
  onCancel: () => void
  /** Optional initial mask data URL to load */
  initialMask?: string | null
}

type DrawMode = 'brush' | 'eraser'

interface HistoryEntry {
  imageData: ImageData
}

export function MaskCanvas({
  imageUrl,
  onSaveMask,
  onCancel,
  initialMask,
}: MaskCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  // Drawing state
  const [isDrawing, setIsDrawing] = useState(false)
  const [mode, setMode] = useState<DrawMode>('brush')
  const [brushSize, setBrushSize] = useState(30)
  const [brushOpacity, setBrushOpacity] = useState(1.0)
  const [showMask, setShowMask] = useState(true)

  // History for undo/redo
  const [history, setHistory] = useState<HistoryEntry[]>([])
  const [historyIndex, setHistoryIndex] = useState(-1)

  // Image dimensions
  const [imageDimensions, setImageDimensions] = useState({ width: 0, height: 0 })
  const [canvasScale, setCanvasScale] = useState(1)

  // Initialize canvas when image loads
  useEffect(() => {
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => {
      const canvas = canvasRef.current
      const container = containerRef.current
      if (!canvas || !container) return

      // Calculate scale to fit in container while maintaining aspect ratio
      const maxWidth = container.clientWidth - 32
      const maxHeight = container.clientHeight - 32
      const scale = Math.min(maxWidth / img.width, maxHeight / img.height, 1)

      const scaledWidth = Math.floor(img.width * scale)
      const scaledHeight = Math.floor(img.height * scale)

      // Set canvas to actual image dimensions for mask quality
      canvas.width = img.width
      canvas.height = img.height

      // Store dimensions and scale
      setImageDimensions({ width: img.width, height: img.height })
      setCanvasScale(scale)

      // Clear canvas with transparent background
      const ctx = canvas.getContext('2d')
      if (ctx) {
        ctx.clearRect(0, 0, canvas.width, canvas.height)

        // Load initial mask if provided
        if (initialMask) {
          const maskImg = new Image()
          maskImg.crossOrigin = 'anonymous'
          maskImg.onload = () => {
            ctx.drawImage(maskImg, 0, 0, canvas.width, canvas.height)
            saveToHistory()
          }
          maskImg.src = initialMask
        } else {
          saveToHistory()
        }
      }
    }
    img.src = imageUrl
  }, [imageUrl, initialMask])

  // Save current canvas state to history
  const saveToHistory = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height)

    setHistory((prev) => {
      // Remove any future history if we're not at the end
      const newHistory = prev.slice(0, historyIndex + 1)
      newHistory.push({ imageData })
      // Limit history to 50 entries
      if (newHistory.length > 50) newHistory.shift()
      return newHistory
    })
    setHistoryIndex((prev) => Math.min(prev + 1, 49))
  }, [historyIndex])

  // Undo
  const handleUndo = useCallback(() => {
    if (historyIndex <= 0) return

    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const newIndex = historyIndex - 1
    setHistoryIndex(newIndex)
    ctx.putImageData(history[newIndex].imageData, 0, 0)
  }, [history, historyIndex])

  // Redo
  const handleRedo = useCallback(() => {
    if (historyIndex >= history.length - 1) return

    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const newIndex = historyIndex + 1
    setHistoryIndex(newIndex)
    ctx.putImageData(history[newIndex].imageData, 0, 0)
  }, [history, historyIndex])

  // Clear mask
  const handleClear = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    ctx.clearRect(0, 0, canvas.width, canvas.height)
    saveToHistory()
  }, [saveToHistory])

  // Get canvas coordinates from mouse event
  const getCanvasCoords = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current
      if (!canvas) return { x: 0, y: 0 }

      const rect = canvas.getBoundingClientRect()
      const x = ((e.clientX - rect.left) / rect.width) * canvas.width
      const y = ((e.clientY - rect.top) / rect.height) * canvas.height

      return { x, y }
    },
    []
  )

  // Draw on canvas
  const draw = useCallback(
    (x: number, y: number) => {
      const canvas = canvasRef.current
      if (!canvas) return

      const ctx = canvas.getContext('2d')
      if (!ctx) return

      ctx.beginPath()
      ctx.arc(x, y, brushSize / 2 / canvasScale, 0, Math.PI * 2)

      if (mode === 'brush') {
        // Draw white mask (areas to inpaint)
        ctx.globalCompositeOperation = 'source-over'
        ctx.fillStyle = `rgba(255, 255, 255, ${brushOpacity})`
      } else {
        // Erase
        ctx.globalCompositeOperation = 'destination-out'
        ctx.fillStyle = 'rgba(0, 0, 0, 1)'
      }

      ctx.fill()
    },
    [mode, brushSize, brushOpacity, canvasScale]
  )

  // Mouse event handlers
  const handleMouseDown = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      setIsDrawing(true)
      const { x, y } = getCanvasCoords(e)
      draw(x, y)
    },
    [getCanvasCoords, draw]
  )

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      if (!isDrawing) return
      const { x, y } = getCanvasCoords(e)
      draw(x, y)
    },
    [isDrawing, getCanvasCoords, draw]
  )

  const handleMouseUp = useCallback(() => {
    if (isDrawing) {
      setIsDrawing(false)
      saveToHistory()
    }
  }, [isDrawing, saveToHistory])

  const handleMouseLeave = useCallback(() => {
    if (isDrawing) {
      setIsDrawing(false)
      saveToHistory()
    }
  }, [isDrawing, saveToHistory])

  // Save mask and call callback
  const handleSave = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    // Export as PNG data URL
    const maskDataUrl = canvas.toDataURL('image/png')
    onSaveMask(maskDataUrl)
  }, [onSaveMask])

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'z' && (e.ctrlKey || e.metaKey)) {
        if (e.shiftKey) {
          handleRedo()
        } else {
          handleUndo()
        }
        e.preventDefault()
      } else if (e.key === 'b') {
        setMode('brush')
      } else if (e.key === 'e') {
        setMode('eraser')
      } else if (e.key === 'Escape') {
        onCancel()
      } else if (e.key === 'Enter') {
        handleSave()
      } else if (e.key === '[') {
        setBrushSize((prev) => Math.max(5, prev - 5))
      } else if (e.key === ']') {
        setBrushSize((prev) => Math.min(200, prev + 5))
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [handleUndo, handleRedo, onCancel, handleSave])

  return (
    <div className="fixed inset-0 z-50 bg-black/90 flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-white/10 bg-black/50 backdrop-blur-xl">
        <div className="flex items-center gap-4">
          <h2 className="text-lg font-bold text-white">Draw Mask</h2>
          <span className="text-xs text-white/40">
            Paint the areas you want to edit (white = areas to change)
          </span>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={onCancel}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-white/70 hover:text-white transition-colors"
          >
            <X size={16} />
            Cancel
          </button>
          <button
            onClick={handleSave}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-purple-500 hover:bg-purple-400 text-white font-semibold transition-colors"
          >
            <Check size={16} />
            Apply Mask
          </button>
        </div>
      </div>

      {/* Main canvas area */}
      <div
        ref={containerRef}
        className="flex-1 flex items-center justify-center p-4 overflow-hidden"
      >
        <div className="relative">
          {/* Background image */}
          <img
            src={imageUrl}
            alt="Source"
            className="max-w-full max-h-[70vh] object-contain rounded-lg shadow-2xl"
            style={{
              width: imageDimensions.width * canvasScale || 'auto',
              height: imageDimensions.height * canvasScale || 'auto',
            }}
          />

          {/* Canvas overlay */}
          <canvas
            ref={canvasRef}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseLeave}
            className="absolute inset-0 cursor-crosshair"
            style={{
              width: imageDimensions.width * canvasScale || '100%',
              height: imageDimensions.height * canvasScale || '100%',
              opacity: showMask ? 0.6 : 0,
              pointerEvents: showMask ? 'auto' : 'none',
              mixBlendMode: 'screen',
            }}
          />

          {/* Brush cursor preview */}
          {showMask && (
            <div
              className="pointer-events-none absolute rounded-full border-2 border-white/50"
              style={{
                width: brushSize,
                height: brushSize,
                transform: 'translate(-50%, -50%)',
                left: '50%',
                top: '50%',
                display: 'none',
              }}
            />
          )}
        </div>
      </div>

      {/* Toolbar */}
      <div className="flex items-center justify-center gap-6 px-6 py-4 border-t border-white/10 bg-black/50 backdrop-blur-xl">
        {/* Mode buttons */}
        <div className="flex items-center gap-2 p-1 rounded-xl bg-white/5 border border-white/10">
          <button
            onClick={() => setMode('brush')}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
              mode === 'brush'
                ? 'bg-purple-500 text-white'
                : 'text-white/60 hover:text-white hover:bg-white/10'
            }`}
            title="Brush (B)"
          >
            <Brush size={18} />
            <span className="text-sm font-medium">Brush</span>
          </button>
          <button
            onClick={() => setMode('eraser')}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
              mode === 'eraser'
                ? 'bg-purple-500 text-white'
                : 'text-white/60 hover:text-white hover:bg-white/10'
            }`}
            title="Eraser (E)"
          >
            <Eraser size={18} />
            <span className="text-sm font-medium">Eraser</span>
          </button>
        </div>

        {/* Brush size */}
        <div className="flex items-center gap-3">
          <span className="text-xs text-white/40 uppercase tracking-wider font-semibold">
            Size
          </span>
          <input
            type="range"
            min={5}
            max={200}
            value={brushSize}
            onChange={(e) => setBrushSize(Number(e.target.value))}
            className="w-32 h-1.5 bg-white/10 rounded-full appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-purple-400 [&::-webkit-slider-thumb]:rounded-full"
          />
          <span className="text-sm text-white/60 w-8">{brushSize}</span>
        </div>

        {/* Brush opacity */}
        <div className="flex items-center gap-3">
          <span className="text-xs text-white/40 uppercase tracking-wider font-semibold">
            Opacity
          </span>
          <input
            type="range"
            min={0.1}
            max={1}
            step={0.1}
            value={brushOpacity}
            onChange={(e) => setBrushOpacity(Number(e.target.value))}
            className="w-24 h-1.5 bg-white/10 rounded-full appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-purple-400 [&::-webkit-slider-thumb]:rounded-full"
          />
          <span className="text-sm text-white/60 w-8">
            {Math.round(brushOpacity * 100)}%
          </span>
        </div>

        {/* Divider */}
        <div className="w-px h-8 bg-white/10" />

        {/* History buttons */}
        <div className="flex items-center gap-1">
          <button
            onClick={handleUndo}
            disabled={historyIndex <= 0}
            className="p-2 rounded-lg text-white/60 hover:text-white hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            title="Undo (Ctrl+Z)"
          >
            <Undo2 size={18} />
          </button>
          <button
            onClick={handleRedo}
            disabled={historyIndex >= history.length - 1}
            className="p-2 rounded-lg text-white/60 hover:text-white hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            title="Redo (Ctrl+Shift+Z)"
          >
            <Redo2 size={18} />
          </button>
        </div>

        {/* Clear button */}
        <button
          onClick={handleClear}
          className="flex items-center gap-2 px-3 py-2 rounded-lg text-white/60 hover:text-red-400 hover:bg-red-500/10 transition-colors"
          title="Clear mask"
        >
          <Trash2 size={18} />
          <span className="text-sm font-medium">Clear</span>
        </button>

        {/* Toggle visibility */}
        <button
          onClick={() => setShowMask(!showMask)}
          className="flex items-center gap-2 px-3 py-2 rounded-lg text-white/60 hover:text-white hover:bg-white/10 transition-colors"
          title="Toggle mask visibility"
        >
          {showMask ? <Eye size={18} /> : <EyeOff size={18} />}
          <span className="text-sm font-medium">{showMask ? 'Hide' : 'Show'}</span>
        </button>
      </div>

      {/* Keyboard shortcuts help */}
      <div className="absolute bottom-20 left-4 text-[10px] text-white/30 space-y-1">
        <div>
          <kbd className="px-1 py-0.5 bg-white/10 rounded">B</kbd> Brush
        </div>
        <div>
          <kbd className="px-1 py-0.5 bg-white/10 rounded">E</kbd> Eraser
        </div>
        <div>
          <kbd className="px-1 py-0.5 bg-white/10 rounded">[</kbd>{' '}
          <kbd className="px-1 py-0.5 bg-white/10 rounded">]</kbd> Brush size
        </div>
        <div>
          <kbd className="px-1 py-0.5 bg-white/10 rounded">Ctrl+Z</kbd> Undo
        </div>
        <div>
          <kbd className="px-1 py-0.5 bg-white/10 rounded">Enter</kbd> Apply
        </div>
        <div>
          <kbd className="px-1 py-0.5 bg-white/10 rounded">Esc</kbd> Cancel
        </div>
      </div>
    </div>
  )
}
