import React, { useEffect } from 'react';
import { X } from 'lucide-react';
export default function PersonaHubDrawer({ open, title, subtitle, metaRight, onClose, children, }) {
    // ESC to close
    useEffect(() => {
        if (!open)
            return;
        const onKeyDown = (e) => {
            if (e.key === 'Escape')
                onClose();
        };
        window.addEventListener('keydown', onKeyDown);
        return () => window.removeEventListener('keydown', onKeyDown);
    }, [open, onClose]);
    // Lock background scroll
    useEffect(() => {
        if (!open)
            return;
        const prev = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        return () => {
            document.body.style.overflow = prev;
        };
    }, [open]);
    if (!open)
        return null;
    return (<div className="fixed inset-0 z-50">
      {/* Overlay (click to close) */}
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onMouseDown={onClose} aria-hidden/>

      {/* Drawer — centered */}
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
        <div className="w-full max-w-md max-h-[90vh] bg-gray-950 border border-white/10 rounded-2xl shadow-2xl flex flex-col pointer-events-auto" onMouseDown={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
          {/* Sticky header */}
          <div className="sticky top-0 z-10 bg-gray-950/95 backdrop-blur border-b border-white/10">
            <div className="px-4 py-3 flex items-center gap-3">
              <div className="min-w-0 flex-1">
                <div className="text-white font-semibold truncate">{title}</div>
                {subtitle && <div className="text-xs text-gray-400 truncate">{subtitle}</div>}
              </div>

              {metaRight && <div className="shrink-0">{metaRight}</div>}

              <button onClick={onClose} className="shrink-0 p-2 rounded-lg text-gray-400 hover:text-white hover:bg-white/10 transition" aria-label="Close" title="Close">
                <X size={18}/>
              </button>
            </div>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto px-4 py-4">
            {children}
          </div>

          {/* Bottom safe area */}
          <div className="h-4"/>
        </div>
      </div>
    </div>);
}
