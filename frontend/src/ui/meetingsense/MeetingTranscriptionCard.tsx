/**
 * Settings → Voice Assistant → Meeting transcription (batch MS32, wave W12).
 *
 * The home the server's setup hint always needed.
 *
 * MS5 wrote that hint deliberately: a disabled control must say *what to set*, and
 * `/v1/meetingsense/status` returns the exact variable because the server is the only thing
 * that knows which provider is missing. That was right — and MS29 then printed it under the
 * composer on every chat screen, where the audience is somebody typing a message, not
 * somebody configuring a server.
 *
 * So the hint keeps its precision and moves to the surface where precision is what people
 * came for. Environment-variable names are fine here and nowhere else in the product's chat
 * UI: opening Settings is already the act of asking a configuration question.
 *
 * Renders nothing when the server has MeetingSense off, and nothing while the probe is in
 * flight — an optional feature does not get to add a loading row to somebody's Settings.
 */
import React, { useEffect, useState } from 'react';
import type { MeetingSenseStatus } from './entryPoint';

export interface MeetingTranscriptionCardProps {
    /** Injected in tests; defaults to the same relative probe `App` uses. */
    load?: () => Promise<MeetingSenseStatus | null>;
}

async function probe(): Promise<MeetingSenseStatus | null> {
    try {
        const res = await fetch('/v1/meetingsense/status');
        return res.ok ? ((await res.json()) as MeetingSenseStatus) : null;
    } catch {
        return null;
    }
}

export function MeetingTranscriptionCard({ load }: MeetingTranscriptionCardProps) {
    const [status, setStatus] = useState<MeetingSenseStatus | null>(null);

    useEffect(() => {
        let cancelled = false;
        void (async () => {
            const body = await (load || probe)();
            if (!cancelled) setStatus(body);
        })();
        return () => {
            cancelled = true;
        };
    }, [load]);

    if (!status?.enabled) return null;

    const stt = status.stt || {};
    const ready = stt.available !== false;
    const provider = stt.provider || null;

    return (
        <div
            data-testid="ms-settings-transcription"
            className="flex flex-col gap-1.5 border-t border-white/[0.06] pt-4"
        >
            <div className="flex items-center justify-between gap-3">
                <div className="text-[13px] text-white/80">Meeting transcription</div>
                <span
                    data-testid="ms-settings-state"
                    className={[
                        'px-2 py-0.5 rounded-full text-[11px] border',
                        ready
                            ? 'bg-emerald-500/10 border-emerald-500/25 text-emerald-200'
                            : 'bg-amber-500/10 border-amber-500/25 text-amber-200',
                    ].join(' ')}
                >
                    {ready ? 'Ready' : 'Not configured'}
                </span>
            </div>

            <div className="text-[11px] text-white/40 leading-relaxed">
                {ready
                    ? `Speech from meetings is transcribed${provider ? ` by ${provider}` : ''}${
                          stt.device ? ` on ${stt.device}` : ''
                      }.`
                    : 'Meetings record audio, but nothing is transcribed until a speech provider is available.'}
            </div>

            {!ready && stt.hint ? (
                // Verbatim from the server. Paraphrasing it here would be a second, staler
                // copy of the one answer that knows which provider is actually missing.
                <div
                    data-testid="ms-settings-hint"
                    className="mt-0.5 px-2.5 py-2 rounded-lg bg-white/[0.03] border border-white/[0.06] text-[11px] text-white/50 font-mono leading-relaxed break-words"
                >
                    {stt.hint}
                </div>
            ) : null}
        </div>
    );
}

export default MeetingTranscriptionCard;
