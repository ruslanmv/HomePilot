/**
 * BottomSheet — mobile-first slide-up drawer used by the player.
 *
 * UX notes:
 *   - Anchored to the bottom; content scrolls independently of
 *     the page, capped at ~70vh so the video stage stays visible.
 *   - Backdrop click + ESC close the sheet (mirrors Modal).
 *   - Focus is not trapped — the player wants the input to keep
 *     focus when the sheet opens briefly for a quick tap. If you
 *     need a trap for a future long-form sheet, wrap it in a
 *     <FocusLock> without changing this primitive.
 *   - Styled against the same token palette as the editor
 *     (#1a1a1a surface, #3f3f3f borders, #3ea6ff accent).
 */

import React, { useEffect } from "react";
import { X } from "lucide-react";

export interface BottomSheetProps {
  open: boolean;
  onClose: () => void;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  children: React.ReactNode;
  /** Extra actions rendered in the header (right-aligned). */
  actions?: React.ReactNode;
  /** Max height as a CSS value; default `70vh`. */
  maxHeight?: string;
}

export function BottomSheet({
  open, onClose, title, subtitle, children, actions, maxHeight = "70vh",
}: BottomSheetProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[65] flex items-end justify-center"
      role="dialog"
      aria-modal="true"
      aria-label={typeof title === "string" ? title : "Sheet"}
    >
      <div
        className="absolute inset-0 bg-black/60"
        onClick={onClose}
        aria-hidden
      />
      <div
        className="relative w-full max-w-xl bg-[#1a1a1a] border-t border-[#3f3f3f] rounded-t-2xl shadow-2xl animate-sheet-up"
        style={{ maxHeight }}
      >
        <div className="flex items-start justify-between gap-3 px-5 pt-4 pb-3 border-b border-[#3f3f3f]">
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold text-[#f1f1f1] truncate">{title}</div>
            {subtitle && <div className="text-xs text-[#aaa] mt-0.5">{subtitle}</div>}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {actions}
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="w-8 h-8 rounded-full bg-white/5 hover:bg-white/10 flex items-center justify-center focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff]"
            >
              <X className="w-4 h-4" aria-hidden />
            </button>
          </div>
        </div>
        <div className="overflow-y-auto" style={{ maxHeight: `calc(${maxHeight} - 3.5rem)` }}>
          <div className="px-5 py-4">{children}</div>
        </div>
      </div>
    </div>
  );
}
