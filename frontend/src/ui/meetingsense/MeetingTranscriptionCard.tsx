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

/** What `/v1/meetingsense/status` reports under `stt.local_speech` (LS3/LS7). */
export interface LocalSpeechStatus {
    available?: boolean;
    local?: boolean;
    device?: string | null;
    warm?: boolean;
    label?: string;
    modes?: string[];
    pack?: {
        pack?: string | null;
        label?: string | null;
        reason?: string;
        size_mb?: number;
        license?: string | null;
    } | null;
    benchmark?: { rtf?: number; device?: string; keeps_up?: boolean } | null;
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
    // LS3/LS7. The pinned pack and the measured profile, when the server is new enough to report
    // them. An older server simply does not send the key and the card behaves as it did.
    const local = (stt.local_speech as LocalSpeechStatus | undefined) || null;

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

            {!ready ? (
                <LocalSpeechSetup local={local} />
            ) : null}

            {!ready && stt.hint ? (
                // LS4. Demoted behind Advanced. The hint is precise and it names environment
                // variables, which is right for somebody debugging a server and wrong as the
                // first thing a person reads when they want to record a meeting. Precision does
                // not stop being useful when it stops being the headline; a `<details>` is
                // closed by default, keyboard reachable, and never in the normal path.
                //
                // Still gated on `!ready`, which MS32 decided and this batch does not reopen:
                // `hint` is advice, not a fault, and a device note beside a working provider is
                // not a setup problem even when it is folded away.
                <details data-testid="ms-settings-advanced" className="mt-1">
                    <summary className="cursor-pointer text-[11px] text-white/35 hover:text-white/55 select-none">
                        Advanced
                    </summary>
                    <div
                        data-testid="ms-settings-hint"
                        className="mt-1.5 px-2.5 py-2 rounded-lg bg-white/[0.03] border border-white/[0.06] text-[11px] text-white/50 font-mono leading-relaxed break-words"
                    >
                        {stt.hint}
                    </div>
                </details>
            ) : null}
        </div>
    );
}

/**
 * The install moment (LS4).
 *
 * Settings stops teaching environment variables. What somebody wants here is one sentence about
 * what they get, one about where the audio goes, and a button — and the download size has to come
 * from the pack manifest the server reports, never a figure typed in here: CTranslate2 conversion
 * and quantisation change the installed footprint, so a hard-coded number is wrong the first time
 * the pack is rebuilt.
 *
 * No progress bar is invented. The server reports `reason` — not installed, incomplete, corrupt,
 * unverified — and each of those is a different sentence with a different next step. A single
 * spinner over all four would be the same shrug this whole series has been removing.
 */
function LocalSpeechSetup({ local }: { local: LocalSpeechStatus | null }) {
    const reason = local?.pack?.reason || (local ? 'not-installed' : '');
    const size = local?.pack?.size_mb;
    const label = local?.pack?.label;

    const copy: Record<string, { title: string; body: string; action: string }> = {
        'not-installed': {
            title: 'Local transcription needs to be installed.',
            body: 'Private transcription runs entirely on this computer after installation.',
            action: 'Install Local Transcription',
        },
        incomplete: {
            title: 'The last install did not finish.',
            body: 'Some of the model files are missing. Installing again picks up where it stopped.',
            action: 'Finish Installing',
        },
        corrupt: {
            title: 'The installed model does not match its checksum.',
            body: 'That usually means an interrupted download. Installing again replaces it.',
            action: 'Reinstall',
        },
    };
    const shown = copy[reason] || copy['not-installed'];

    return (
        <div data-testid="ms-settings-install" className="mt-1 flex flex-col gap-2">
            <div className="text-[12px] text-white/70">{shown.title}</div>
            <div className="text-[11px] text-white/40 leading-relaxed">{shown.body}</div>
            <button
                type="button"
                data-testid="ms-settings-install-btn"
                className="self-start px-3 py-1.5 rounded-lg text-[12px] bg-cyan-500/15 border border-cyan-400/30 text-cyan-100 hover:bg-cyan-500/25"
            >
                {shown.action}
                {size ? (
                    // From the manifest, via the server. Never a number written down here.
                    <span data-testid="ms-settings-install-size" className="ml-1.5 text-white/40 tabular-nums">
                        {size >= 1024 ? `${(size / 1024).toFixed(1)} GB` : `${size} MB`}
                    </span>
                ) : null}
            </button>
            <div className="text-[11px] text-white/35">
                No account or cloud speech service required.
                {label ? ` Installs ${label}.` : ''}
            </div>
        </div>
    );
}

export default MeetingTranscriptionCard;
