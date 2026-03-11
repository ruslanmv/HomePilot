/**
 * AboutDialog — professional "About HomePilot" popup window.
 *
 * Displays version, author, and project links in a centered modal overlay.
 */
import React, { useEffect, useRef } from 'react'
import { X, ExternalLink, Github, Globe, Heart, Activity } from 'lucide-react'

interface AboutDialogProps {
  onClose: () => void
  onOpenSystemStatus?: () => void
}

export default function AboutDialog({ onClose, onOpenSystemStatus }: AboutDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null)

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  // Close on backdrop click
  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) onClose()
  }

  return (
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={handleBackdropClick}
      style={{ animation: 'aboutFadeIn 200ms ease-out' }}
    >
      <div
        ref={dialogRef}
        className="relative w-[420px] max-w-[92vw] bg-[#0c0c18] border border-white/10 rounded-3xl shadow-2xl overflow-hidden"
        style={{ animation: 'aboutSlideUp 250ms ease-out' }}
      >
        {/* Close button */}
        <button
          type="button"
          onClick={onClose}
          className="absolute top-4 right-4 z-10 h-8 w-8 rounded-full grid place-items-center text-white/40 hover:text-white hover:bg-white/10 transition-colors"
          aria-label="Close"
        >
          <X size={16} />
        </button>

        {/* Top gradient accent */}
        <div className="h-1.5 w-full bg-gradient-to-r from-purple-500 via-blue-500 to-cyan-400" />

        {/* Content */}
        <div className="flex flex-col items-center px-8 pt-8 pb-6">
          {/* Logo / Icon */}
          <div className="relative mb-5">
            <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-purple-600/30 to-blue-600/30 border border-white/10 grid place-items-center shadow-lg shadow-purple-500/10">
              <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="url(#aboutGrad)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <defs>
                  <linearGradient id="aboutGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stopColor="#a855f7" />
                    <stop offset="100%" stopColor="#06b6d4" />
                  </linearGradient>
                </defs>
                <path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z" />
                <polyline points="9 22 9 12 15 12 15 22" />
              </svg>
            </div>
            {/* Glow */}
            <div className="absolute -inset-3 bg-purple-500/8 rounded-3xl blur-xl -z-10" />
          </div>

          {/* Title */}
          <h1 className="text-2xl font-bold text-white tracking-tight mb-0.5">
            HomePilot
          </h1>

          {/* Version badge */}
          <div className="flex items-center gap-2 mb-4">
            <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-gradient-to-r from-purple-500/20 to-blue-500/20 text-purple-300 border border-purple-500/20">
              v3.0.0
            </span>
            <span className="text-xs text-white/30">Home Edition</span>
          </div>

          {/* Description */}
          <p className="text-[13px] text-white/50 text-center leading-relaxed max-w-[320px] mb-6">
            The self-hosted AI platform with persistent identities, studio-grade content creation, and agentic tool access — running entirely on your hardware.
          </p>

          {/* Divider */}
          <div className="w-full border-t border-white/5 mb-5" />

          {/* Info grid */}
          <div className="w-full grid grid-cols-2 gap-3 text-[12px] mb-6">
            <div className="bg-white/[0.03] rounded-xl px-3.5 py-2.5 border border-white/5">
              <div className="text-white/30 mb-0.5">Developer</div>
              <div className="text-white/80 font-medium">Ruslan Magana Vsevolodovna</div>
            </div>
            <div className="bg-white/[0.03] rounded-xl px-3.5 py-2.5 border border-white/5">
              <div className="text-white/30 mb-0.5">License</div>
              <div className="text-white/80 font-medium">Open Source</div>
            </div>
            <div className="bg-white/[0.03] rounded-xl px-3.5 py-2.5 border border-white/5">
              <div className="text-white/30 mb-0.5">Stack</div>
              <div className="text-white/80 font-medium">React + FastAPI</div>
            </div>
            <div className="bg-white/[0.03] rounded-xl px-3.5 py-2.5 border border-white/5">
              <div className="text-white/30 mb-0.5">Architecture</div>
              <div className="text-white/80 font-medium">160+ API Endpoints</div>
            </div>
          </div>

          {/* Links */}
          <div className="flex items-center gap-3 mb-5">
            <a
              href="https://github.com/ruslanmv/HomePilot"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-white/5 border border-white/8 text-white/70 hover:text-white hover:bg-white/10 transition-colors text-[12px] font-medium"
            >
              <Github size={14} />
              GitHub
              <ExternalLink size={10} className="text-white/30" />
            </a>
            <a
              href="https://ruslanmv.com/HomePilot/"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-white/5 border border-white/8 text-white/70 hover:text-white hover:bg-white/10 transition-colors text-[12px] font-medium"
            >
              <Globe size={14} />
              Website
              <ExternalLink size={10} className="text-white/30" />
            </a>
          </div>

          {/* Overview button */}
          {onOpenSystemStatus && (
            <button
              type="button"
              onClick={() => { onClose(); onOpenSystemStatus() }}
              className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-gradient-to-r from-emerald-500/10 to-cyan-500/10 border border-emerald-500/20 text-emerald-300 hover:text-white hover:border-emerald-400/30 transition-colors text-[12px] font-medium mb-5"
            >
              <Activity size={14} />
              Overview
            </button>
          )}

          {/* Footer */}
          <div className="flex items-center gap-1.5 text-[11px] text-white/25">
            <span>Made with</span>
            <Heart size={10} className="text-red-400/60" fill="currentColor" />
            <span>by Ruslan Magana Vsevolodovna</span>
          </div>
        </div>
      </div>

      {/* Keyframe animations */}
      <style>{`
        @keyframes aboutFadeIn {
          from { opacity: 0 }
          to { opacity: 1 }
        }
        @keyframes aboutSlideUp {
          from { opacity: 0; transform: translateY(16px) scale(0.97) }
          to { opacity: 1; transform: translateY(0) scale(1) }
        }
      `}</style>
    </div>
  )
}
