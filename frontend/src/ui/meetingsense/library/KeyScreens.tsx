/**
 * Key screens — the slides and shared screens captured during a meeting.
 *
 * Built from the meeting's own keyframes (``detail.keyframes``: ``t_ms``, ``url``, ``caption``),
 * never placeholders. Each opens full size in a viewer that steps through the rest with the
 * arrow keys and closes on Escape, returning focus to the screen that opened it.
 */
import React, { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, ImageOff, X } from 'lucide-react';
import { backendBase } from '../api';
import { clock } from './format';

export interface KeyScreen {
    id?: string;
    t_ms?: number;
    url?: string;
    caption?: string | null;
}

const PREVIEW_COUNT = 2;

/** A stored screen URL as the browser can load it: relative ones live on the backend. */
export function screenSrc(url?: string): string {
    const value = (url || '').trim();
    if (!value || /^(https?:|data:|blob:)/i.test(value)) return value;
    const base = backendBase();
    return value.startsWith('/') && base ? `${base}${value}` : value;
}

export function usableScreens(rows: unknown): KeyScreen[] {
    return (Array.isArray(rows) ? rows : [])
        .filter((r): r is KeyScreen => !!r && typeof r === 'object' && typeof (r as KeyScreen).url === 'string' && !!(r as KeyScreen).url)
        .sort((a, b) => (a.t_ms ?? 0) - (b.t_ms ?? 0));
}

/** Lets a card header open the viewer ("View all") without owning its state. */
export interface KeyScreensHandle {
    openViewer: (index?: number) => void;
}

export const KeyScreens = forwardRef<KeyScreensHandle, { screens: KeyScreen[]; onSeek?: (ms: number) => void }>(function KeyScreens({ screens, onSeek }, ref) {
    const [all, setAll] = useState(false);
    const [open, setOpen] = useState<number | null>(null);
    const openers = useRef<Array<HTMLButtonElement | null>>([]);
    const returnTo = useRef<HTMLElement | null>(null);
    useImperativeHandle(ref, () => ({
        openViewer: (index = 0) => {
            if (!screens.length) return;
            returnTo.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
            setOpen(Math.max(0, Math.min(index, screens.length - 1)));
        },
    }), [screens.length]);

    if (!screens.length) {
        return (
            <p className="flex items-center gap-2 text-sm text-white/55">
                <ImageOff size={15} className="text-white/35" aria-hidden /> No screens were captured in this meeting.
            </p>
        );
    }
    const shown = all ? screens : screens.slice(0, PREVIEW_COUNT);
    return (
        <>
            <ul className={all ? 'grid grid-cols-2 gap-3 sm:grid-cols-3' : 'space-y-3'} data-testid="key-screens">
                {shown.map((screen, index) => (
                    <li key={screen.id || `${screen.url}-${index}`} className={all ? '' : 'flex items-center gap-3'}>
                        <button
                            type="button"
                            ref={(el) => { openers.current[index] = el; }}
                            onClick={() => { returnTo.current = null; setOpen(index); }}
                            aria-label={`Open ${screen.caption || `meeting screen ${index + 1}`} full size`}
                            className={`group relative shrink-0 overflow-hidden rounded-xl border border-white/10 bg-black focus-visible:outline focus-visible:outline-2 focus-visible:outline-violet-400 ${all ? 'block w-full' : 'w-40 sm:w-48'}`}
                        >
                            <img src={screenSrc(screen.url)} alt="" loading="lazy" className="aspect-video w-full object-cover transition group-hover:opacity-90" />
                            {typeof screen.t_ms === 'number' ? (
                                <span className="absolute bottom-1.5 left-1.5 rounded-md bg-black/75 px-1.5 py-0.5 font-mono text-[11px] text-white/90">{clock(screen.t_ms)}</span>
                            ) : null}
                        </button>
                        {all ? null : (
                            <div className="min-w-0">
                                <p className="text-sm font-medium text-white/90">Meeting screen {index + 1}</p>
                                {screen.caption ? <p className="mt-0.5 line-clamp-2 text-xs text-white/55">{screen.caption}</p> : null}
                                {onSeek && typeof screen.t_ms === 'number' ? (
                                    <button type="button" onClick={() => onSeek(screen.t_ms!)} className="mt-1 text-xs text-violet-300 hover:text-violet-200">
                                        Play from {clock(screen.t_ms)}
                                    </button>
                                ) : null}
                            </div>
                        )}
                    </li>
                ))}
            </ul>
            {screens.length > PREVIEW_COUNT ? (
                <button type="button" onClick={() => setAll((v) => !v)} className="mt-3 text-sm text-violet-300 hover:text-violet-200">
                    {all ? 'Show fewer' : `Show all ${screens.length} screens`}
                </button>
            ) : null}
            {open !== null ? (
                <ScreenViewer
                    // Every screen, not only the ones shown: the arrows step through the meeting.
                    screens={screens}
                    index={open}
                    onIndex={setOpen}
                    onClose={() => {
                        const at = open;
                        const back = returnTo.current;
                        setOpen(null);
                        // Focus goes back to whatever opened the viewer: a thumbnail or "View all".
                        window.requestAnimationFrame(() => (back && back.isConnected ? back : openers.current[at])?.focus());
                    }}
                />
            ) : null}
        </>
    );
});

function ScreenViewer({ screens, index, onIndex, onClose }: {
    screens: KeyScreen[]; index: number; onIndex: (i: number) => void; onClose: () => void;
}) {
    const screen = screens[index];
    const closeRef = useRef<HTMLButtonElement>(null);
    const step = useCallback((d: number) => onIndex((index + d + screens.length) % screens.length), [index, onIndex, screens.length]);

    useEffect(() => {
        closeRef.current?.focus();
        const onKey = (e: KeyboardEvent) => {
            if (e.key === 'Escape') onClose();
            else if (e.key === 'ArrowRight' && screens.length > 1) step(1);
            else if (e.key === 'ArrowLeft' && screens.length > 1) step(-1);
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [onClose, step, screens.length]);

    if (!screen) return null;
    return (
        <div className="fixed inset-0 z-[80] flex flex-col bg-black/90 p-4 sm:p-8" role="dialog" aria-modal="true"
            aria-label={`Meeting screen ${index + 1} of ${screens.length}`} onClick={onClose}>
            <div className="flex items-center gap-3 text-sm text-white/75" onClick={(e) => e.stopPropagation()}>
                <span>Meeting screen {index + 1} of {screens.length}</span>
                {typeof screen.t_ms === 'number' ? <span className="font-mono text-white/50">{clock(screen.t_ms)}</span> : null}
                <button ref={closeRef} type="button" onClick={onClose} aria-label="Close"
                    className="ml-auto grid h-10 w-10 place-items-center rounded-full border border-white/15 hover:bg-white/10">
                    <X size={18} />
                </button>
            </div>
            <div className="relative mt-3 flex min-h-0 flex-1 items-center justify-center" onClick={(e) => e.stopPropagation()}>
                {screens.length > 1 ? (
                    <button type="button" onClick={() => step(-1)} aria-label="Previous screen"
                        className="absolute left-0 grid h-11 w-11 place-items-center rounded-full border border-white/15 bg-black/60 hover:bg-white/10">
                        <ChevronLeft size={20} />
                    </button>
                ) : null}
                <img src={screenSrc(screen.url)} alt={screen.caption || `Meeting screen ${index + 1}`} className="max-h-full max-w-full rounded-lg object-contain" />
                {screens.length > 1 ? (
                    <button type="button" onClick={() => step(1)} aria-label="Next screen"
                        className="absolute right-0 grid h-11 w-11 place-items-center rounded-full border border-white/15 bg-black/60 hover:bg-white/10">
                        <ChevronRight size={20} />
                    </button>
                ) : null}
            </div>
            {screen.caption ? <p className="mt-3 text-center text-sm text-white/70" onClick={(e) => e.stopPropagation()}>{screen.caption}</p> : null}
        </div>
    );
}
