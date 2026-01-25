/**
 * EditHistoryStrip - Horizontal strip of previous images in the session.
 *
 * Shows the image history allowing users to revert to or branch from
 * any previous state.
 */

import React from 'react'
import type { EditHistoryStripProps } from './types'

export function EditHistoryStrip({
  history,
  active,
  onSelect,
  disabled,
}: EditHistoryStripProps) {
  // Don't render if no history
  if (!history?.length) {
    return null
  }

  return (
    <div className="mt-4">
      {/* Section header */}
      <div className="text-[11px] uppercase tracking-wider text-white/40 font-semibold mb-2">
        History
      </div>

      {/* Horizontal scrollable strip */}
      <div className="flex gap-2 overflow-x-auto pb-2 scrollbar-thin scrollbar-thumb-white/10">
        {history.slice(0, 10).map((url, index) => {
          const isActive = active === url

          return (
            <button
              key={`${url}-${index}`}
              type="button"
              onClick={() => !disabled && onSelect(url)}
              disabled={disabled}
              className={[
                'shrink-0 rounded-xl overflow-hidden border transition-all duration-150',
                'focus:outline-none focus:ring-2 focus:ring-blue-500/50',
                isActive
                  ? 'border-white/40 ring-1 ring-white/20'
                  : 'border-white/10 hover:border-white/20',
                disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer',
              ].join(' ')}
              title={isActive ? 'Currently active' : 'Use as base image'}
              aria-label={isActive ? 'Currently active image' : 'Select this image as base'}
            >
              <img
                src={url}
                className="h-14 w-14 object-cover"
                alt={`History image ${index + 1}`}
                loading="lazy"
              />

              {/* Active indicator */}
              {isActive && (
                <div className="absolute inset-0 bg-blue-500/10 flex items-center justify-center">
                  <div className="w-2 h-2 rounded-full bg-blue-400" />
                </div>
              )}
            </button>
          )
        })}
      </div>

      {/* Hint text */}
      {history.length > 0 && (
        <p className="mt-2 text-[10px] text-white/30">
          Click to use as new base image
        </p>
      )}
    </div>
  )
}

export default EditHistoryStrip
