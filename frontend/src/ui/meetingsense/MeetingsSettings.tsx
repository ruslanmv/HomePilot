/**
 * Settings → Meetings: the few choices that decide how a meeting is recorded.
 *
 * Everything applies immediately and is saved on this computer — there is no Save button,
 * the same as Audio & Video and Motion. Four groups, in the order a meeting meets them:
 *
 *   1. What to record by default (the Quick record switches, `library/quickRecord.ts`), and
 *      whether the audio is kept afterwards (`meetingPrefs.keepAudio`, unless the operator's
 *      MEETINGSENSE_RETENTION decides).
 *   2. Which microphone, and its clean-up — the *shared* media preference, so Meetings, calls
 *      and Settings → Audio & Video can never disagree about which microphone is "mine".
 *   3. The spoken language, which the transcriber otherwise guesses per sentence.
 *   4. Notes during the meeting, and the document written after it.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { HardDrive, Headphones, Mic, MonitorUp, Play, RefreshCw, Square, Volume2 } from 'lucide-react';
import { backendBase, requestHeaders } from './api';
import {
    buildAudioConstraints,
    getMediaPreferences,
    setMediaPreferences,
    subscribeMediaPreferences,
    type MediaPreferences,
} from '../media/mediaPreferences';
import { readQuickPrefs, writeQuickPrefs, type QuickRecordPrefs } from './library/quickRecord';
import { SUMMARY_LENGTHS, SUMMARY_STYLES } from './MeetingMinutes';
import {
    SPOKEN_LANGUAGES,
    readMeetingPrefs,
    subscribeMeetingPrefs,
    writeMeetingPrefs,
    type MeetingPrefs,
    type SummaryLength,
    type SummaryStyle,
} from './meetingPrefs';

const SELECT_CLS =
    'w-full h-10 rounded-xl border border-white/10 bg-[#050505] px-3 pr-8 text-sm text-white outline-none ' +
    'focus:border-[#9b5cff]/60 focus:ring-2 focus:ring-[#9b5cff]/25 [color-scheme:dark] cursor-pointer disabled:opacity-50';
const BUTTON_CLS =
    'inline-flex h-10 items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3.5 text-xs ' +
    'font-semibold text-white/80 transition-colors hover:bg-white/10 hover:text-white disabled:cursor-not-allowed disabled:opacity-45';
const MIC_TEST_MS = 5000;

/** Summary languages: the meeting's own, or one to translate into ("Write it in Italian"). */
const SUMMARY_LANGUAGES = [
    { id: '', label: 'Same as the meeting' },
    ...SPOKEN_LANGUAGES.filter((l) => l.id !== 'auto' && l.id !== 'multi').map((l) => ({ id: l.label, label: l.label })),
];

function Switch({ checked, label, onChange, disabled = false }: {
    checked: boolean; label: string; onChange: (next: boolean) => void; disabled?: boolean;
}) {
    return (
        <button
            type="button"
            role="switch"
            aria-checked={checked}
            aria-label={label}
            disabled={disabled}
            onClick={() => onChange(!checked)}
            className={[
                'relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors',
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-[#9b5cff]/75 disabled:cursor-not-allowed disabled:opacity-50',
                checked ? 'bg-[#9b5cff]' : 'bg-white/10',
            ].join(' ')}
        >
            <span className={['inline-block h-4 w-4 rounded-full bg-white transition-transform', checked ? 'translate-x-6' : 'translate-x-1'].join(' ')} />
        </button>
    );
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
    return (
        <section className="border-t border-white/[0.06] pt-5 first:border-t-0 first:pt-0">
            <h4 className="text-sm font-semibold text-white">{title}</h4>
            {hint ? <p className="mt-0.5 text-xs leading-relaxed text-white/50">{hint}</p> : null}
            <div className="mt-3 space-y-3">{children}</div>
        </section>
    );
}

function ToggleRow({ icon, label, note, checked, onChange, disabled }: {
    icon?: React.ReactNode; label: string; note?: string; checked: boolean; onChange: (next: boolean) => void;
    disabled?: boolean;
}) {
    return (
        <div className="flex items-center justify-between gap-4 rounded-xl border border-white/[0.06] bg-white/[0.02] px-3.5 py-3">
            <div className="flex min-w-0 items-start gap-3">
                {icon ? <span className="mt-0.5 text-white/55">{icon}</span> : null}
                <div className="min-w-0">
                    <div className="text-sm text-white/90">{label}</div>
                    {note ? <div className="mt-0.5 text-xs leading-snug text-white/50">{note}</div> : null}
                </div>
            </div>
            <Switch checked={checked} label={label} onChange={onChange} disabled={disabled} />
        </div>
    );
}

/**
 * The operator's `MEETINGSENSE_RETENTION`, when one is set — it decides for everyone, so the
 * switch shows it instead of the user's choice. `null` while unknown or when users choose.
 */
function useRetentionPolicy(): string | null {
    const [policy, setPolicy] = useState<string | null>(null);
    useEffect(() => {
        let cancelled = false;
        try {
            void fetch(`${backendBase()}/v1/meetingsense/status`, { headers: requestHeaders() })
                .then((r) => (r.ok ? r.json() : null))
                .then((body) => {
                    if (!cancelled && body) setPolicy(typeof body.retention_policy === 'string' ? body.retention_policy : null);
                })
                .catch(() => undefined);
        } catch {
            /* no fetch here: the user's own choice is what the switch shows */
        }
        return () => { cancelled = true; };
    }, []);
    return policy;
}

function Field({ label, htmlFor, children }: { label: string; htmlFor: string; children: React.ReactNode }) {
    return (
        <label htmlFor={htmlFor} className="block">
            <span className="mb-1.5 block text-xs font-medium text-white/70">{label}</span>
            {children}
        </label>
    );
}

/** Live microphone level while a short test runs, so "is it the right one?" has an answer. */
function useMicTest(preferences: MediaPreferences) {
    const [level, setLevel] = useState(0);
    const [running, setRunning] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const stopRef = useRef<() => void>(() => undefined);

    const stop = useCallback(() => {
        stopRef.current();
        stopRef.current = () => undefined;
        setRunning(false);
        setLevel(0);
    }, []);

    const start = useCallback(async () => {
        stop();
        setError(null);
        if (!navigator.mediaDevices?.getUserMedia) {
            setError('This browser cannot open a microphone.');
            return;
        }
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: buildAudioConstraints(preferences) });
            const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
            const ctx = new Ctx();
            const analyser = ctx.createAnalyser();
            analyser.fftSize = 1024;
            ctx.createMediaStreamSource(stream).connect(analyser);
            const buffer = new Float32Array(analyser.fftSize);
            let frame = 0;
            const tick = () => {
                analyser.getFloatTimeDomainData(buffer);
                let sum = 0;
                for (let i = 0; i < buffer.length; i += 1) sum += buffer[i] * buffer[i];
                setLevel(Math.min(1, Math.sqrt(sum / buffer.length) * 6));
                frame = window.requestAnimationFrame(tick);
            };
            frame = window.requestAnimationFrame(tick);
            const timer = window.setTimeout(() => stop(), MIC_TEST_MS);
            stopRef.current = () => {
                window.cancelAnimationFrame(frame);
                window.clearTimeout(timer);
                stream.getTracks().forEach((t) => t.stop());
                void ctx.close().catch(() => undefined);
            };
            setRunning(true);
        } catch (err) {
            const name = (err as { name?: string })?.name || '';
            setError(name === 'NotAllowedError'
                ? 'Microphone access is blocked for this site. Allow it in the browser’s address bar.'
                : name === 'OverconstrainedError' || name === 'NotFoundError'
                    ? 'That microphone is not connected any more. Pick another one.'
                    : 'The microphone could not be opened.');
        }
    }, [preferences, stop]);

    useEffect(() => stop, [stop]);
    return { level, running, error, start, stop };
}

export function MeetingsSettings() {
    const [quick, setQuick] = useState<QuickRecordPrefs>(() => readQuickPrefs());
    const [media, setMedia] = useState<MediaPreferences>(() => getMediaPreferences());
    const [prefs, setPrefs] = useState<MeetingPrefs>(() => readMeetingPrefs());
    const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
    const [labelsHidden, setLabelsHidden] = useState(false);
    const test = useMicTest(media);
    const policy = useRetentionPolicy();

    useEffect(() => subscribeMediaPreferences(setMedia), []);
    useEffect(() => subscribeMeetingPrefs(setPrefs), []);

    const refreshDevices = useCallback(async () => {
        if (!navigator.mediaDevices?.enumerateDevices) return;
        try {
            const all = await navigator.mediaDevices.enumerateDevices();
            const mics = all.filter((d) => d.kind === 'audioinput');
            setDevices(mics);
            setLabelsHidden(mics.length > 0 && mics.every((d) => !d.label));
        } catch {
            setDevices([]);
        }
    }, []);

    useEffect(() => {
        void refreshDevices();
        const md = navigator.mediaDevices;
        md?.addEventListener?.('devicechange', refreshDevices);
        return () => md?.removeEventListener?.('devicechange', refreshDevices);
    }, [refreshDevices]);

    // Device names are hidden until the site may use a microphone. Asking once, briefly, is
    // what turns "Microphone 1, Microphone 2" into names a person recognises.
    const revealNames = useCallback(async () => {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            stream.getTracks().forEach((t) => t.stop());
        } catch {
            /* refused: the generic names stay */
        }
        await refreshDevices();
    }, [refreshDevices]);

    const updateQuick = (patch: Partial<QuickRecordPrefs>) => {
        const next = { ...quick, ...patch };
        writeQuickPrefs(next);
        setQuick(next);
    };
    const updateMedia = (patch: Partial<MediaPreferences>) => setMedia(setMediaPreferences({ ...media, ...patch }));
    const updatePrefs = (patch: Partial<MeetingPrefs>) => setPrefs(writeMeetingPrefs(patch));

    const selectedMissing = !!media.microphoneDeviceId && devices.length > 0
        && !devices.some((d) => d.deviceId === media.microphoneDeviceId);

    return (
        <div className="space-y-6" data-testid="meetings-settings">
            <Section title="Record by default" hint="What a new meeting records. You can still change it for each meeting before it starts.">
                <ToggleRow icon={<Volume2 size={16} />} label="Call audio" note="The other people on the call — tab or system audio from the share picker." checked={quick.audio} onChange={(v) => updateQuick({ audio: v })} />
                <ToggleRow icon={<Mic size={16} />} label="My microphone" note="What you say." checked={quick.mic} onChange={(v) => updateQuick({ mic: v })} />
                <ToggleRow icon={<MonitorUp size={16} />} label="Screen" note="Key frames of shared slides, for the summary. Optional." checked={quick.screen} onChange={(v) => updateQuick({ screen: v })} />
            </Section>

            <Section title="Recording" hint="What is kept after the meeting, besides the transcript.">
                <ToggleRow
                    icon={<HardDrive size={16} />}
                    label="Keep the audio recording"
                    note={policy
                        ? `Set for everyone on this server (MEETINGSENSE_RETENTION=${policy}): ${policy === 'all' ? 'the audio is always kept.' : 'only the transcript is kept.'}`
                        : 'Saved on this computer with the transcript, so you can play a meeting back and download it from Meetings. Deleted when you delete the meeting. Off keeps only the transcript.'}
                    checked={policy ? policy === 'all' : prefs.keepAudio}
                    disabled={!!policy}
                    onChange={(v) => updatePrefs({ keepAudio: v })}
                />
            </Section>

            <Section title="Microphone" hint="Shared with Settings → Audio & Video, so calls and meetings use the same input.">
                <Field label="Input device" htmlFor="ms-settings-mic">
                    <div className="flex flex-wrap gap-2">
                        <select
                            id="ms-settings-mic"
                            className={`${SELECT_CLS} min-w-0 flex-1`}
                            value={media.microphoneDeviceId}
                            onChange={(e) => updateMedia({ microphoneDeviceId: e.target.value })}
                        >
                            <option value="">System default</option>
                            {devices.map((d, i) => (
                                <option key={d.deviceId || i} value={d.deviceId}>{d.label || `Microphone ${i + 1}`}</option>
                            ))}
                            {selectedMissing ? <option value={media.microphoneDeviceId}>Saved microphone (not connected)</option> : null}
                        </select>
                        <button type="button" className={BUTTON_CLS} onClick={() => void refreshDevices()} aria-label="Refresh the microphone list">
                            <RefreshCw size={14} />
                        </button>
                        {test.running ? (
                            <button type="button" className={BUTTON_CLS} onClick={test.stop}><Square size={14} /> Stop</button>
                        ) : (
                            <button type="button" className={BUTTON_CLS} onClick={() => void test.start()}><Play size={14} /> Test</button>
                        )}
                    </div>
                </Field>
                {labelsHidden ? (
                    <button type="button" className="text-xs text-[#b896ff] hover:text-white" onClick={() => void revealNames()}>
                        Show microphone names (asks for microphone access once)
                    </button>
                ) : null}
                {selectedMissing ? (
                    <p className="text-xs text-amber-200/80">The saved microphone is not connected. Meetings will use the system default until it is.</p>
                ) : null}
                <div aria-hidden={!test.running} className={test.running ? '' : 'opacity-40'}>
                    <div className="h-2 overflow-hidden rounded-full bg-white/[0.06]" role="meter" aria-label="Microphone level" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(test.level * 100)}>
                        <div className="h-full rounded-full bg-gradient-to-r from-cyan-400 to-[#9b5cff] transition-[width] duration-75" style={{ width: `${Math.round(test.level * 100)}%` }} />
                    </div>
                    <p className="mt-1 text-[11px] text-white/45">{test.running ? 'Speak now — the bar should move with your voice.' : 'Press Test and speak to check the level.'}</p>
                </div>
                {test.error ? <p className="text-xs text-rose-300">{test.error}</p> : null}
                <ToggleRow label="Echo cancellation" note="Keeps sound from your speakers out of the microphone. Leave on unless you use headphones and want the most natural sound." checked={media.echoCancellation} onChange={(v) => updateMedia({ echoCancellation: v })} />
                <ToggleRow label="Noise suppression" note="Filters steady background noise — fans, traffic, keyboards." checked={media.noiseSuppression} onChange={(v) => updateMedia({ noiseSuppression: v })} />
                <ToggleRow label="Automatic gain" note="Evens out your volume when you move away from the microphone." checked={media.autoGainControl} onChange={(v) => updateMedia({ autoGainControl: v })} />
                <div className="flex items-start gap-2.5 rounded-xl border border-cyan-400/15 bg-cyan-400/[0.05] px-3.5 py-3 text-xs leading-relaxed text-cyan-50/80">
                    <Headphones size={15} className="mt-0.5 shrink-0 text-cyan-300" />
                    <span>
                        <b className="font-semibold text-cyan-100">Headphones give the cleanest transcript.</b> Through laptop speakers the
                        call also reaches your microphone; HomePilot removes those repeated lines automatically, but it cannot
                        recover words two people said at the same time.
                    </span>
                </div>
            </Section>

            <Section title="Speech" hint="Transcribed on this computer.">
                <Field label="Spoken language" htmlFor="ms-settings-language">
                    <select id="ms-settings-language" className={SELECT_CLS} value={prefs.language} onChange={(e) => updatePrefs({ language: e.target.value })}>
                        {SPOKEN_LANGUAGES.map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}
                    </select>
                </Field>
                <p className="text-xs leading-relaxed text-white/50">
                    {prefs.language === 'auto'
                        ? 'The first few sentences decide the language, and the rest of the meeting is transcribed in it. Choose the language if you know it — short sentences are the hardest to guess.'
                        : prefs.language === 'multi'
                            ? 'Every sentence is detected on its own. Use this only for meetings that really switch languages: short sentences are sometimes guessed wrong.'
                            : 'Every sentence is transcribed in this language.'}
                </p>
            </Section>

            <Section title="Notes and summary">
                <ToggleRow
                    label="Live notes during the meeting"
                    note="A running recap, decisions and action items while people talk. Uses your chat model — turn it off on a slow computer; the summary is still written when the meeting ends."
                    checked={prefs.liveNotes}
                    onChange={(v) => updatePrefs({ liveNotes: v })}
                />
                <div className="grid gap-3 sm:grid-cols-3">
                    <Field label="Summary style" htmlFor="ms-settings-style">
                        <select id="ms-settings-style" className={SELECT_CLS} value={prefs.summaryStyle} onChange={(e) => updatePrefs({ summaryStyle: e.target.value as SummaryStyle })}>
                            {SUMMARY_STYLES.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
                        </select>
                    </Field>
                    <Field label="Length" htmlFor="ms-settings-length">
                        <select id="ms-settings-length" className={SELECT_CLS} value={prefs.summaryLength} onChange={(e) => updatePrefs({ summaryLength: e.target.value as SummaryLength })}>
                            {SUMMARY_LENGTHS.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
                        </select>
                    </Field>
                    <Field label="Summary language" htmlFor="ms-settings-summary-language">
                        <select id="ms-settings-summary-language" className={SELECT_CLS} value={prefs.summaryLanguage} onChange={(e) => updatePrefs({ summaryLanguage: e.target.value })}>
                            {SUMMARY_LANGUAGES.map((l) => <option key={l.id || 'same'} value={l.id}>{l.label}</option>)}
                        </select>
                    </Field>
                </div>
                <p className="text-xs text-white/50">{SUMMARY_STYLES.find((s) => s.id === prefs.summaryStyle)?.note}</p>
            </Section>
        </div>
    );
}

export default MeetingsSettings;
