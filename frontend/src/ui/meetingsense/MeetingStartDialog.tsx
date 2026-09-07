/**
 * Premium meeting preflight (additive UX layer).
 *
 * This component deliberately does not know how a meeting is recorded. It only edits the
 * existing CaptureOptions object and hands the final choice back to MeetingSenseProvider.
 * The provider remains the single place that starts capture, enforces the server flag and
 * handles consent persistence.
 */
import React, { useCallback, useEffect, useMemo, useRef } from 'react';
import {
    AudioLines,
    Check,
    Cloud,
    HardDrive,
    Mic2,
    MonitorUp,
    ShieldCheck,
    Sparkles,
    X,
} from 'lucide-react';
import { MODES, type CaptureOptions } from './CapturePopover';
import type { ConsentStatus } from './ConsentSheet';
import { consentSentences } from './meetingState';

export interface MeetingStartDialogProps {
    status: ConsentStatus | null;
    capture: CaptureOptions;
    onCaptureChange: (next: CaptureOptions) => void;
    onAccept: (rememberChoice: boolean) => void;
    onCancel: () => void;
}

type CaptureKey = 'audio' | 'mic' | 'slides';

const captureItems: Array<{
    key: CaptureKey;
    label: string;
    detail: string;
    icon: React.ComponentType<{ size?: number; strokeWidth?: number }>;
}> = [
    { key: 'audio', label: 'Meeting audio', detail: 'Hear the people in the call', icon: AudioLines },
    { key: 'mic', label: 'My microphone', detail: 'Include what you say', icon: Mic2 },
    { key: 'slides', label: 'Screen & slides', detail: 'Capture useful key frames', icon: MonitorUp },
];

export function MeetingStartDialog({
    status,
    capture,
    onCaptureChange,
    onAccept,
    onCancel,
}: MeetingStartDialogProps) {
    const dialog = useRef<HTMLDivElement | null>(null);
    const remember = useRef<HTMLInputElement | null>(null);

    const privacyLines = useMemo(
        () => consentSentences({ ...(status || {}), mode: capture.mode }),
        [status, capture.mode],
    );
    const selectedMode = MODES.find((mode) => mode.id === capture.mode) ?? MODES[0];
    const remote = Boolean(status?.stt?.remote);

    const onKeyDown = useCallback(
        (event: React.KeyboardEvent) => {
            if (event.key === 'Escape') {
                event.preventDefault();
                onCancel();
                return;
            }
            if (event.key !== 'Tab') return;

            const focusable = dialog.current?.querySelectorAll<HTMLElement>(
                'button:not(:disabled), input:not(:disabled), select:not(:disabled), [href], [tabindex]:not([tabindex="-1"])',
            );
            if (!focusable || !focusable.length) return;
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        },
        [onCancel],
    );

    useEffect(() => {
        const previouslyFocused = document.activeElement as HTMLElement | null;
        const previousOverflow = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        dialog.current?.focus();
        return () => {
            document.body.style.overflow = previousOverflow;
            previouslyFocused?.focus?.();
        };
    }, []);

    const toggleCapture = (key: CaptureKey) => {
        onCaptureChange({ ...capture, [key]: !capture[key] });
    };

    return (
        <div
            className="fixed inset-0 z-[100] flex items-end justify-center bg-black/70 p-0 backdrop-blur-sm sm:items-center sm:p-6"
            aria-hidden="false"
        >
            <div
                ref={dialog}
                role="dialog"
                aria-modal="true"
                aria-labelledby="ms-consent-title"
                aria-describedby="ms-start-description"
                tabIndex={-1}
                onKeyDown={onKeyDown}
                data-testid="ms-consent"
                className="relative flex max-h-[min(820px,calc(100dvh-24px))] w-full max-w-2xl flex-col overflow-hidden rounded-t-[28px] border border-white/10 bg-[#101014] shadow-[0_30px_100px_-30px_rgba(0,0,0,0.95)] outline-none sm:rounded-[28px]"
            >
                <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/25 to-transparent" />

                <div className="flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-contain">
                    <header className="relative border-b border-white/[0.07] px-5 pb-5 pt-5 sm:px-7 sm:pb-6 sm:pt-6">
                        <button
                            type="button"
                            onClick={onCancel}
                            aria-label="Close meeting setup"
                            className="absolute right-4 top-4 inline-flex h-9 w-9 items-center justify-center rounded-full border border-white/10 bg-white/[0.03] text-white/50 transition hover:bg-white/[0.08] hover:text-white focus:outline-none focus:ring-2 focus:ring-violet-400/60 sm:right-5 sm:top-5"
                        >
                            <X size={17} />
                        </button>

                        <div className="flex items-start gap-4 pr-12">
                            <div className="mt-0.5 inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-violet-400/20 bg-violet-400/10 text-violet-200 shadow-inner shadow-white/[0.04]">
                                <Mic2 size={20} strokeWidth={1.8} />
                            </div>
                            <div className="min-w-0">
                                <div className="mb-2 flex flex-wrap items-center gap-2">
                                    <h2 id="ms-consent-title" className="text-xl font-semibold tracking-[-0.02em] text-white sm:text-[22px]">
                                        Start a meeting
                                    </h2>
                                    <span
                                        className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-1 text-[10px] font-medium uppercase tracking-[0.08em] ${
                                            remote
                                                ? 'border-amber-300/20 bg-amber-300/[0.08] text-amber-200/90'
                                                : 'border-emerald-300/20 bg-emerald-300/[0.08] text-emerald-200/90'
                                        }`}
                                    >
                                        {remote ? <Cloud size={11} /> : <HardDrive size={11} />}
                                        {remote ? 'Remote speech' : 'Processed locally'}
                                    </span>
                                </div>
                                <p id="ms-start-description" className="max-w-xl text-[13px] leading-5 text-white/45">
                                    Choose what HomePilot can hear and see. Nothing is captured until you press Start meeting.
                                </p>
                            </div>
                        </div>
                    </header>

                    <div className="space-y-6 px-5 py-5 sm:px-7 sm:py-6">
                        <section aria-labelledby="ms-capture-heading">
                            <div className="mb-3 flex items-center justify-between gap-3">
                                <div>
                                    <h3 id="ms-capture-heading" className="text-sm font-medium text-white/90">Capture</h3>
                                    <p className="mt-0.5 text-[11px] text-white/35">Notes stay on; choose the sources for this meeting.</p>
                                </div>
                                <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.035] px-2.5 py-1 text-[10px] font-medium text-white/45">
                                    <Check size={11} /> Notes on
                                </span>
                            </div>

                            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
                                {captureItems.map((item) => {
                                    const Icon = item.icon;
                                    const active = capture[item.key];
                                    return (
                                        <button
                                            key={item.key}
                                            type="button"
                                            role="switch"
                                            aria-checked={active}
                                            onClick={() => toggleCapture(item.key)}
                                            data-testid={`ms-start-${item.key}`}
                                            className={`group flex min-h-[86px] items-start gap-3 rounded-2xl border p-3.5 text-left transition focus:outline-none focus:ring-2 focus:ring-violet-400/60 ${
                                                active
                                                    ? 'border-violet-300/25 bg-violet-400/[0.08] shadow-inner shadow-violet-200/[0.03]'
                                                    : 'border-white/[0.08] bg-white/[0.02] hover:border-white/15 hover:bg-white/[0.04]'
                                            }`}
                                        >
                                            <span className={`mt-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-xl border ${active ? 'border-violet-300/20 bg-violet-300/10 text-violet-200' : 'border-white/10 bg-white/[0.03] text-white/35'}`}>
                                                <Icon size={15} strokeWidth={1.8} />
                                            </span>
                                            <span className="min-w-0 flex-1">
                                                <span className={`block text-xs font-medium ${active ? 'text-white' : 'text-white/55'}`}>{item.label}</span>
                                                <span className="mt-1 block text-[10px] leading-4 text-white/30">{item.detail}</span>
                                            </span>
                                            <span
                                                aria-hidden="true"
                                                className={`mt-1 flex h-4 w-7 shrink-0 items-center rounded-full p-0.5 transition ${active ? 'justify-end bg-violet-400' : 'justify-start bg-white/15'}`}
                                            >
                                                <span className="h-3 w-3 rounded-full bg-white shadow-sm" />
                                            </span>
                                        </button>
                                    );
                                })}
                            </div>

                            {!capture.audio && !capture.mic ? (
                                <p className="mt-2.5 rounded-xl border border-amber-300/15 bg-amber-300/[0.06] px-3 py-2 text-[11px] leading-4 text-amber-100/70" role="status">
                                    No audio source is selected. The meeting can still capture screen context, but the transcript may be empty.
                                </p>
                            ) : null}
                        </section>

                        <section aria-labelledby="ms-role-heading">
                            <div className="mb-3 flex items-center gap-2">
                                <Sparkles size={14} className="text-violet-200/80" />
                                <h3 id="ms-role-heading" className="text-sm font-medium text-white/90">Assistant role</h3>
                            </div>
                            <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Assistant role">
                                {MODES.map((mode) => {
                                    const selected = capture.mode === mode.id;
                                    return (
                                        <button
                                            type="button"
                                            key={mode.label}
                                            role="radio"
                                            aria-checked={selected}
                                            onClick={() => onCaptureChange({ ...capture, mode: mode.id })}
                                            data-testid={`ms-start-mode-${mode.id ?? 'note-taker'}`}
                                            className={`rounded-xl border px-3 py-2 text-xs transition focus:outline-none focus:ring-2 focus:ring-violet-400/60 ${
                                                selected
                                                    ? 'border-violet-300/30 bg-violet-400/10 text-violet-100'
                                                    : 'border-white/[0.08] bg-white/[0.02] text-white/45 hover:border-white/15 hover:text-white/75'
                                            }`}
                                        >
                                            {mode.label}
                                        </button>
                                    );
                                })}
                            </div>
                            <p className="mt-2.5 text-[11px] leading-4 text-white/35">
                                <span className="font-medium text-white/55">{selectedMode.label}:</span> {selectedMode.note}
                            </p>
                        </section>

                        <section
                            aria-labelledby="ms-privacy-heading"
                            className="rounded-2xl border border-white/[0.08] bg-white/[0.025] p-4"
                        >
                            <div className="flex gap-3">
                                <span className="mt-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-xl border border-emerald-300/15 bg-emerald-300/[0.06] text-emerald-200/80">
                                    <ShieldCheck size={16} strokeWidth={1.8} />
                                </span>
                                <div className="min-w-0 flex-1">
                                    <h3 id="ms-privacy-heading" className="text-xs font-medium text-white/85">Privacy before recording</h3>
                                    <ul className="mt-2.5 space-y-2 text-[11px] leading-[1.55] text-white/42">
                                        {privacyLines.map((line) => (
                                            <li key={line} className="flex gap-2">
                                                <span aria-hidden="true" className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-white/25" />
                                                <span>{line}</span>
                                            </li>
                                        ))}
                                    </ul>
                                </div>
                            </div>
                        </section>

                        <label className="flex cursor-pointer items-start gap-3 rounded-xl px-1 py-0.5 text-xs text-white/50">
                            <input
                                type="checkbox"
                                ref={remember}
                                data-testid="ms-consent-remember"
                                className="mt-0.5 h-4 w-4 rounded border-white/20 bg-white/[0.04] accent-violet-500"
                            />
                            <span>
                                <span className="block font-medium text-white/65">Skip this preflight next time on this computer</span>
                                <span className="mt-0.5 block text-[10px] leading-4 text-white/30">The live recording indicator and participant reminder still stay visible.</span>
                            </span>
                        </label>
                    </div>
                </div>

                <footer className="flex shrink-0 items-center justify-end gap-2 border-t border-white/[0.07] bg-black/10 px-5 py-4 sm:px-7">
                    <button
                        type="button"
                        onClick={onCancel}
                        data-testid="ms-consent-cancel"
                        className="inline-flex h-10 items-center justify-center rounded-xl border border-white/10 bg-white/[0.025] px-4 text-xs font-medium text-white/60 transition hover:bg-white/[0.06] hover:text-white focus:outline-none focus:ring-2 focus:ring-white/20"
                    >
                        Cancel
                    </button>
                    <button
                        type="button"
                        onClick={() => onAccept(Boolean(remember.current?.checked))}
                        data-testid="ms-consent-accept"
                        className="inline-flex h-10 items-center justify-center gap-2 rounded-xl bg-white px-[18px] text-xs font-semibold text-black shadow-[0_8px_28px_-10px_rgba(255,255,255,0.45)] transition hover:bg-white/90 focus:outline-none focus:ring-2 focus:ring-violet-300 focus:ring-offset-2 focus:ring-offset-[#101014]"
                    >
                        <Mic2 size={14} strokeWidth={2} />
                        Start meeting
                    </button>
                </footer>
            </div>
        </div>
    );
}

export default MeetingStartDialog;
