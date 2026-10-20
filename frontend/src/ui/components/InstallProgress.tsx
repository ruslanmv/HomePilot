/**
 * The downloading look, shared by every Install button on the Models page: the blue shimmer
 * and spinner the catalog rows always had, now with the real percentage, and a thin progress
 * bar with "2.7 GB of 6.5 GB · 5.8 MB/s" under the row. The shimmer keyframes live in Models.tsx.
 */
import React from 'react'
import { progressLabel, type InstallProgress } from '../lib/installProgress'

/** Goes inside a `relative overflow-hidden` button while it installs. */
export function DownloadingButtonContent({ progress, compact = false }: { progress: InstallProgress | null; compact?: boolean }) {
  const pct = progress?.state === 'running' && progress.percent !== null ? ` ${progress.percent}%` : ''
  return (
    <>
      <span
        className="absolute inset-0 bg-gradient-to-r from-blue-600 via-blue-500 to-blue-600 animate-shimmer"
        style={{ backgroundSize: '200% 100%', animation: 'shimmer 2s infinite linear' }}
        aria-hidden
      />
      <span className={`relative z-10 flex items-center ${compact ? 'gap-1.5' : 'gap-2.5'}`}>
        <svg className={`animate-spin ${compact ? 'h-3.5 w-3.5' : 'h-4 w-4'}`} xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" aria-hidden>
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
        </svg>
        <span>Downloading{pct || '...'}</span>
      </span>
    </>
  )
}

/** The bar and the one-line detail under a row that is installing. */
export function InstallProgressBar({ progress }: { progress: InstallProgress | null }) {
  const pct = progress?.percent
  const known = typeof pct === 'number'
  return (
    <div className="mt-2" role="status" aria-live="polite" data-testid="install-progress">
      <div
        className="h-1.5 overflow-hidden rounded-full bg-white/[0.08]"
        role="progressbar"
        aria-label="Download progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={known ? pct : undefined}
      >
        {known ? (
          <div className="h-full rounded-full bg-gradient-to-r from-blue-500 to-sky-400 transition-[width] duration-700" style={{ width: `${Math.max(2, pct as number)}%` }} />
        ) : (
          <div className="h-full w-1/3 rounded-full bg-gradient-to-r from-blue-600 via-blue-400 to-blue-600 animate-shimmer" style={{ backgroundSize: '200% 100%', animation: 'shimmer 1.6s infinite linear' }} />
        )}
      </div>
      <div className="mt-1 text-[11px] text-white/55">{progressLabel(progress)}</div>
    </div>
  )
}
