/**
 * Start a meeting.
 *
 * Opens on **Quick record** whenever live recording is possible: three switches (call audio,
 * microphone, optional screen), an optional title and one Start button — remembered, so the
 * next call is a single click. Consent is asked once per computer, the same remembered
 * consent the chat-box Start button uses.
 *
 * "More options" opens the full wizard, unchanged: four short steps — Setup, Recording,
 * Assistant, Summary. Every setting is MeetingSense's own (capture sources, assistant roles,
 * summary style and length, consent); the wizard only orders them. Back and Next keep
 * everything entered, and nothing records until "Start meeting" — with the consent line ticked.
 *
 * "Now" + HomePilot Live starts the existing live recorder (title and project included).
 * "Schedule for later" or an external recorder creates the meeting in the library, where its
 * recording arrives later by upload or folder sync.
 */
import React, { useMemo, useState } from 'react';
import {
    ArrowLeft, ArrowRight, AudioLines, CalendarClock, CalendarDays, Check, Clock3, FileText, Folder, HardDrive,
    Headphones, Info, Lightbulb, Mic, Mic2, MonitorUp, Radio, ShieldCheck, SlidersHorizontal, Sparkles, Users, X,
} from 'lucide-react';
import { ModalSheet } from '../../components/ModalSheet';
import { DEFAULT_CAPTURE, MODES, type CaptureOptions } from '../CapturePopover';
import { consentAcknowledged, withUserRetention } from '../ConsentSheet';
import { SUMMARY_LENGTHS } from '../MeetingMinutes';
import { consentSentences } from '../meetingState';
import { useMeetingControls } from '../MeetingSenseProvider';
import { LibraryError, libraryApi } from './api';
import {
    nothingSelected, readQuickPrefs, shareHint, writeQuickPrefs, type QuickRecordPrefs,
} from './quickRecord';

type When = 'now' | 'later';
type Plan = 'live' | 'external' | 'hybrid';

const STEPS = [
    { title: 'Setup', note: 'Basic information' },
    { title: 'Recording', note: 'Choose source' },
    { title: 'Assistant', note: 'Meeting support' },
    { title: 'Summary', note: 'Output preferences' },
];

const OUTPUTS = [
    { id: 'minutes', label: 'Meeting minutes' },
    { id: 'transcript', label: 'Full transcript' },
    { id: 'summary', label: 'Meeting summary' },
    { id: 'brief', label: 'Executive brief' },
    { id: 'actions', label: 'Action items' },
];

/** The document a meeting writes when it ends, from the outputs ticked (first match wins). */
export function summaryStyleFor(outputs: string[]): string {
    if (outputs.includes('minutes')) return 'minutes';
    if (outputs.includes('brief')) return 'brief';
    if (outputs.includes('summary')) return 'notes';
    if (outputs.includes('actions')) return 'actions';
    return 'minutes';
}

function localInputValue(ts: number): string {
    const d = new Date(ts);
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function StartMeetingWizard({ onClose, onCreated, canRecordLive = true }: {
    onClose: () => void; onCreated: (message: string) => void; canRecordLive?: boolean;
}) {
    const controls = useMeetingControls();
    const liveAvailable = canRecordLive && Boolean(controls?.status?.enabled) && !controls?.live;
    const [step, setStep] = useState(0);
    const [title, setTitle] = useState('');
    const [projects, setProjects] = useState<Array<{ id: string; name: string }>>([]);
    const [projectId, setProjectId] = useState('');
    const [showInProject, setShowInProject] = useState(true);
    const [when, setWhen] = useState<When>('now');
    const [at, setAt] = useState(() => localInputValue(Date.now() + 60 * 60 * 1000));
    const [plan, setPlan] = useState<Plan>(liveAvailable ? 'live' : 'external');
    const [capture, setCapture] = useState<CaptureOptions>(() => ({ ...DEFAULT_CAPTURE, ...(controls?.capture || {}) }));
    const [outputs, setOutputs] = useState<string[]>(['minutes', 'transcript', 'actions']);
    const [length, setLength] = useState(controls?.capture?.summaryLength || 'standard');
    const [consent, setConsent] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    // Quick record is the front door whenever a live recording can start right now.
    const [view, setView] = useState<'quick' | 'steps'>(liveAvailable ? 'quick' : 'steps');
    const [quick, setQuick] = useState<QuickRecordPrefs>(() => readQuickPrefs());
    const [consentKnown] = useState(() => consentAcknowledged());

    React.useEffect(() => { void libraryApi.projects().then(setProjects); }, []);

    const projectName = projects.find((p) => p.id === projectId)?.name;
    const startsLive = when === 'now' && (plan === 'live' || plan === 'hybrid');
    const privacy = useMemo(() => consentSentences({ ...withUserRetention(controls?.status as any), mode: capture.mode } as any),
        [controls?.status, capture.mode]);
    const keepsAudio = withUserRetention(controls?.status as any).retention === 'all';
    const local = !controls?.status?.stt?.remote;
    const scheduledTs = when === 'now' ? Date.now() : new Date(at).getTime();

    const stepValid = (i: number): string | null => {
        if (i === 0) {
            if (!title.trim()) return 'Give the meeting a title.';
            if (when === 'later' && !(scheduledTs > 0)) return 'Choose when the meeting is.';
        }
        if (i === 1 && startsLive && !liveAvailable) return 'Live recording is not available here — choose External Recorder.';
        return null;
    };

    const next = () => {
        const problem = stepValid(step);
        if (problem) { setError(problem); return; }
        setError(null);
        setStep((s) => Math.min(STEPS.length - 1, s + 1));
    };

    const finish = async () => {
        for (let i = 0; i < STEPS.length; i += 1) {
            const problem = stepValid(i);
            if (problem) { setError(problem); setStep(i); return; }
        }
        if (startsLive && !consent) { setError('Confirm that you may record this meeting.'); return; }
        setBusy(true);
        setError(null);
        const style = summaryStyleFor(outputs);
        try {
            if (startsLive && controls?.startWith) {
                const result = await controls.startWith(
                    { ...capture, summaryStyle: style, summaryLength: length },
                    { title: title.trim(), projectId: showInProject && projectId ? projectId : undefined },
                    true,
                );
                if (!result.ok) throw new Error(result.error || 'The meeting could not start.');
                onClose();
                return;
            }
            await libraryApi.createScheduled({
                title: title.trim(),
                project_id: showInProject && projectId ? projectId : '',
                scheduled_for: Math.round(scheduledTs / 1000),
                recording_plan: plan === 'live' ? 'later' : plan,
                category: projectId && showInProject ? 'Project Meeting' : 'Meeting',
                description: capture.context.trim() || undefined,
                outputs: {
                    selected: outputs, style, length, summary: outputs.some((o) => o !== 'transcript'),
                    actions: outputs.includes('actions'), assistant: capture.mode || 'note-taker',
                },
            });
            onCreated(when === 'later' ? `Scheduled "${title.trim()}". Its recording can be added by upload or folder sync.`
                : `Created "${title.trim()}". It is waiting for the external recording.`);
        } catch (e) {
            setError(e instanceof LibraryError || e instanceof Error ? e.message : 'The meeting could not be created.');
        } finally {
            setBusy(false);
        }
    };

    const startQuick = async () => {
        if (busy) return;
        if (nothingSelected(quick)) { setError('Choose at least one thing to record.'); return; }
        if (!consentKnown && !consent) { setError('Confirm that you may record this call.'); return; }
        if (!controls?.startWith) { setError('Live recording is not available here.'); return; }
        setBusy(true);
        setError(null);
        writeQuickPrefs(quick);
        try {
            const result = await controls.startWith(
                { ...capture, audio: quick.audio, mic: quick.mic, slides: quick.screen },
                // No title: the meeting is named from what was said (MEETINGS_AUTO_TITLE).
                title.trim() ? { title: title.trim() } : {},
                true,
            );
            if (!result.ok) throw new Error(result.error || 'The recording could not start.');
            onClose();
        } catch (e) {
            setError(e instanceof Error ? e.message : 'The recording could not start.');
        } finally {
            setBusy(false);
        }
    };

    const openFullWizard = () => {
        setCapture({ ...capture, audio: quick.audio, mic: quick.mic, slides: quick.screen });
        setPlan('live');
        setWhen('now');
        setError(null);
        setStep(0);
        setView('steps');
    };

    if (view === 'quick') {
        const startDisabled = busy || nothingSelected(quick) || (!consentKnown && !consent);
        return (
            <ModalSheet
                labelledBy="hp-quick-title"
                onRequestClose={() => { if (!busy) onClose(); }}
                className="hp-sheet--wide"
                header={(
                    <div className="flex items-start gap-4 border-b border-white/[0.06] px-5 py-5 sm:px-7">
                        <div className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl border border-violet-400/30 bg-violet-500/15 text-violet-200"><Mic size={22} /></div>
                        <div className="min-w-0 flex-1">
                            <h2 id="hp-quick-title" className="text-xl font-semibold sm:text-2xl">Record a call</h2>
                            <p className="mt-0.5 text-sm text-white/60">Slack, Zoom, Teams or any call. HomePilot transcribes it and writes the notes when you stop.</p>
                        </div>
                        {local ? (
                            <span className="hidden items-center gap-1.5 rounded-full border border-emerald-400/40 bg-emerald-500/10 px-3 py-1 text-[11px] font-semibold tracking-wide text-emerald-300 sm:inline-flex">
                                <HardDrive size={12} /> PROCESSED LOCALLY
                            </span>
                        ) : null}
                        <button type="button" onClick={onClose} aria-label="Close" className="grid h-10 w-10 shrink-0 place-items-center rounded-full border border-white/10 text-white/70 hover:bg-white/10"><X size={18} /></button>
                    </div>
                )}
                footer={(
                    <div className="flex flex-wrap items-center gap-3 border-t border-white/[0.06] px-5 py-3 sm:px-7">
                        <button type="button" onClick={onClose} className="h-11 rounded-xl border border-white/15 px-5 text-sm font-semibold hover:bg-white/10">Cancel</button>
                        <span className="min-w-0 flex-1 truncate text-sm text-rose-200" role="alert">{error}</span>
                        <button type="button" onClick={openFullWizard} data-testid="hp-quick-more"
                            className="inline-flex h-11 items-center gap-2 rounded-xl border border-white/15 px-4 text-sm font-semibold text-white/80 hover:bg-white/10"
                            title="Schedule, external recorder, project, assistant and summary">
                            <SlidersHorizontal size={15} /> More options
                        </button>
                        <button type="submit" form="hp-quick-form" disabled={startDisabled} autoFocus data-testid="hp-quick-start"
                            className="inline-flex h-11 items-center gap-2 rounded-xl bg-violet-600 px-5 text-sm font-semibold shadow-lg shadow-violet-900/40 hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-50">
                            <Radio size={15} /> {busy ? 'Starting…' : 'Start recording'}
                        </button>
                    </div>
                )}
            >
                <form id="hp-quick-form" className="space-y-5 px-5 py-5 sm:px-7"
                    onSubmit={(e) => { e.preventDefault(); void startQuick(); }}>
                    <fieldset>
                        <legend className="text-sm font-semibold text-white/85">Record</legend>
                        <div className="mt-2 grid gap-2 sm:grid-cols-3">
                            <QuickSwitch on={quick.audio} onToggle={() => setQuick({ ...quick, audio: !quick.audio })}
                                icon={<AudioLines size={16} />} title="Call audio" note="The other people on the call" testId="hp-quick-audio" />
                            <QuickSwitch on={quick.mic} onToggle={() => setQuick({ ...quick, mic: !quick.mic })}
                                icon={<Mic2 size={16} />} title="My microphone" note="What you say" testId="hp-quick-mic" />
                            <QuickSwitch on={quick.screen} onToggle={() => setQuick({ ...quick, screen: !quick.screen })}
                                icon={<MonitorUp size={16} />} title="Screen" note="Optional: slides and shared screens" testId="hp-quick-screen" />
                        </div>
                        <p className="mt-3 flex gap-2 text-xs leading-5 text-white/55" data-testid="hp-quick-hint">
                            <Info size={14} className="mt-0.5 shrink-0 text-sky-300" /> {shareHint(quick)}
                        </p>
                        {quick.audio && quick.mic ? (
                            <p className="mt-1.5 flex gap-2 text-xs leading-5 text-white/45" data-testid="hp-quick-headphones">
                                <Headphones size={14} className="mt-0.5 shrink-0 text-cyan-300" />
                                Headphones give the cleanest transcript: through speakers the call also reaches your microphone.
                            </p>
                        ) : null}
                    </fieldset>

                    <label className="block text-sm text-white/75">Title <span className="text-white/40">(optional)</span>
                        <input value={title} onChange={(e) => setTitle(e.target.value)} data-testid="hp-quick-title-input"
                            placeholder="Leave empty and HomePilot names it from the conversation"
                            className="mt-1.5 h-11 w-full rounded-xl border border-white/10 bg-white/[0.03] px-4 text-sm text-white placeholder-white/30 focus:border-violet-400/70 focus:outline-none" />
                    </label>

                    {consentKnown ? (
                        <div className="space-y-1.5">
                            <p className="flex items-center gap-2 text-xs text-white/50">
                                <ShieldCheck size={14} className="shrink-0 text-emerald-300" />
                                Tell everyone on the call that it is recorded.
                            </p>
                            <p className="flex items-center gap-2 text-xs text-white/45" data-testid="hp-quick-retention">
                                <HardDrive size={14} className="shrink-0 text-sky-300" />
                                {keepsAudio
                                    ? 'The audio is kept with the transcript, so you can play the call back from Meetings.'
                                    : 'Only the transcript is kept, not the audio.'}
                            </p>
                        </div>
                    ) : (
                        <div className="rounded-xl border border-white/10 bg-black/30 p-3">
                            <ul className="space-y-1 text-xs text-white/55">{privacy.map((line) => <li key={line}>• {line}</li>)}</ul>
                            <label className="mt-3 flex items-start gap-2 text-sm">
                                <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)}
                                    data-testid="hp-quick-consent" className="mt-0.5 accent-violet-500" />
                                <span>I have permission to record this call, and the people on it know. <span className="text-white/45">Asked once on this computer.</span></span>
                            </label>
                        </div>
                    )}
                </form>
            </ModalSheet>
        );
    }

    const last = step === STEPS.length - 1;
    const finishLabel = startsLive ? 'Start meeting' : (when === 'later' ? 'Schedule meeting' : 'Create meeting');

    return (
        <ModalSheet
            labelledBy="hp-wizard-title"
            onRequestClose={() => { if (!busy) onClose(); }}
            className="hp-sheet--xl"
            header={(
                <div className="border-b border-white/[0.06]">
                    <div className="flex items-start gap-4 px-5 pt-5 sm:px-7">
                        <div className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl border border-violet-400/30 bg-violet-500/15 text-violet-200 sm:h-14 sm:w-14"><Mic size={24} /></div>
                        <div className="min-w-0 flex-1">
                            <h2 id="hp-wizard-title" className="text-xl font-semibold sm:text-2xl">Start a meeting</h2>
                            <p className="mt-0.5 text-sm text-white/60">Set up your meeting and let HomePilot capture, sync and understand it.</p>
                        </div>
                        {local ? (
                            <span className="hidden items-center gap-1.5 rounded-full border border-emerald-400/40 bg-emerald-500/10 px-3 py-1 text-[11px] font-semibold tracking-wide text-emerald-300 sm:inline-flex">
                                <HardDrive size={12} /> PROCESSED LOCALLY
                            </span>
                        ) : null}
                        <button type="button" onClick={onClose} aria-label="Close" className="grid h-10 w-10 shrink-0 place-items-center rounded-full border border-white/10 text-white/70 hover:bg-white/10"><X size={18} /></button>
                    </div>
                    <ol className="flex gap-2 overflow-x-auto px-5 py-4 scrollbar-hide sm:px-7" aria-label="Steps">
                        {STEPS.map((s, i) => (
                            <li key={s.title} className="flex min-w-0 flex-1 items-center gap-2">
                                <button type="button" onClick={() => (i < step ? setStep(i) : undefined)} disabled={i > step}
                                    aria-current={i === step ? 'step' : undefined}
                                    className={`grid h-9 w-9 shrink-0 place-items-center rounded-full border text-sm font-semibold ${
                                        i === step ? 'border-violet-400 bg-violet-600 text-white shadow-[0_0_0_4px_rgba(139,92,246,0.2)]'
                                            : i < step ? 'border-violet-400/50 bg-violet-500/20 text-violet-100' : 'border-white/15 text-white/60'}`}>
                                    {i < step ? <Check size={15} /> : i + 1}
                                </button>
                                <span className="hidden min-w-0 sm:block">
                                    <span className={`block truncate text-sm font-semibold ${i === step ? 'text-white' : 'text-white/80'}`}>{s.title}</span>
                                    <span className={`block truncate text-xs ${i === step ? 'text-violet-300' : 'text-white/45'}`}>{s.note}</span>
                                </span>
                                {i < STEPS.length - 1 ? <span className="hidden h-px flex-1 bg-white/10 lg:block" aria-hidden /> : null}
                            </li>
                        ))}
                    </ol>
                </div>
            )}
            footer={(
                <div className="flex items-center gap-3 border-t border-white/[0.06] px-5 py-3 sm:px-7">
                    <button type="button" onClick={onClose} className="h-11 rounded-xl border border-white/15 px-5 text-sm font-semibold hover:bg-white/10">Cancel</button>
                    <span className="flex-1 truncate text-sm text-rose-200" role="alert">{error}</span>
                    {step > 0 ? (
                        <button type="button" onClick={() => { setError(null); setStep((s) => s - 1); }}
                            className="inline-flex h-11 items-center gap-2 rounded-xl border border-white/15 px-4 text-sm font-semibold hover:bg-white/10"><ArrowLeft size={15} /> Back</button>
                    ) : null}
                    {last ? (
                        <button type="button" onClick={() => void finish()} disabled={busy}
                            className="inline-flex h-11 items-center gap-2 rounded-xl bg-violet-600 px-5 text-sm font-semibold shadow-lg shadow-violet-900/40 hover:bg-violet-500 disabled:opacity-50">
                            {startsLive ? <Radio size={15} /> : <CalendarClock size={15} />} {busy ? 'Working…' : finishLabel}
                        </button>
                    ) : (
                        <button type="button" onClick={next}
                            className="inline-flex h-11 items-center gap-2 rounded-xl bg-violet-600 px-5 text-sm font-semibold shadow-lg shadow-violet-900/40 hover:bg-violet-500">
                            Next: {step === 0 ? 'Recording source' : step === 1 ? 'Assistant' : 'Summary'} <ArrowRight size={15} />
                        </button>
                    )}
                </div>
            )}
        >
            <div className="grid gap-4 px-5 py-5 sm:px-7 lg:grid-cols-[minmax(0,1fr)_340px]">
                <div className="min-w-0 rounded-2xl border border-white/10 bg-white/[0.02] p-5">
                    {step === 0 ? (
                        <section aria-labelledby="hp-wz-s1">
                            <SectionTitle id="hp-wz-s1" icon={<FileText size={18} />} title="Meeting details" note="Give your meeting a title and optionally link it to a project." />
                            <label className="mt-4 block text-sm text-white/75">Meeting title
                                <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Project planning meeting" autoFocus
                                    className="mt-1.5 h-12 w-full rounded-xl border border-white/10 bg-white/[0.03] px-4 text-base text-white placeholder-white/30 focus:border-violet-400/70 focus:outline-none" />
                            </label>
                            <div className="mt-4 grid gap-3 sm:grid-cols-[180px_minmax(0,1fr)] sm:items-start">
                                <span className="pt-2.5 text-sm text-white/75">Link to project (optional)</span>
                                <div>
                                    <select value={projectId} onChange={(e) => setProjectId(e.target.value)} aria-label="Project"
                                        className="h-12 w-full rounded-xl border border-white/10 bg-white/[0.03] px-3 text-sm text-white focus:border-violet-400/70 focus:outline-none">
                                        <option value="">No project</option>
                                        {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                                    </select>
                                    {projectId ? (
                                        <label className="mt-3 flex cursor-pointer items-start gap-3">
                                            <input type="checkbox" role="switch" checked={showInProject} onChange={(e) => setShowInProject(e.target.checked)}
                                                className="peer sr-only" />
                                            <span className="relative mt-0.5 h-6 w-11 shrink-0 rounded-full bg-white/15 transition-colors peer-checked:bg-violet-600 peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-violet-300 after:absolute after:left-0.5 after:top-0.5 after:h-5 after:w-5 after:rounded-full after:bg-white after:transition-transform peer-checked:after:translate-x-5" aria-hidden />
                                            <span className="text-sm text-white/85">Also show this meeting in the project
                                                <span className="block text-xs text-white/45">The meeting will appear in both the project and your Meetings library.</span></span>
                                        </label>
                                    ) : null}
                                </div>
                            </div>
                            <SectionTitle icon={<CalendarDays size={18} />} title="When is the meeting?" note="This helps HomePilot match recordings and organize your meetings." className="mt-6" />
                            <div className="mt-3 grid gap-3 sm:grid-cols-2">
                                <ChoiceCard selected={when === 'now'} onClick={() => setWhen('now')} icon={<CalendarDays size={18} />} title="Now" note="Start recording now" />
                                <ChoiceCard selected={when === 'later'} onClick={() => setWhen('later')} icon={<CalendarClock size={18} />} title="Schedule for later" note="Create the meeting and add audio later" />
                            </div>
                            {when === 'later' ? (
                                <label className="mt-3 block text-sm text-white/75">Date and time
                                    <input type="datetime-local" value={at} onChange={(e) => setAt(e.target.value)}
                                        className="mt-1.5 h-11 w-full rounded-xl border border-white/10 bg-white/[0.03] px-3 text-sm text-white [color-scheme:dark] focus:border-violet-400/70 focus:outline-none" />
                                </label>
                            ) : null}
                            <Tip>You can always add or change the project, title and other details later.</Tip>
                        </section>
                    ) : null}

                    {step === 1 ? (
                        <section aria-labelledby="hp-wz-s2">
                            <SectionTitle id="hp-wz-s2" icon={<AudioLines size={18} />} title="Recording source" note="How the audio of this meeting reaches HomePilot." />
                            <div className="mt-4 grid gap-3">
                                <ChoiceCard selected={plan === 'live'} onClick={() => setPlan('live')} disabled={!liveAvailable && when === 'now'}
                                    icon={<Mic2 size={18} />} title="HomePilot Live"
                                    note={liveAvailable || when === 'later' ? 'Use HomePilot’s microphone, meeting audio and optional screen capture.' : 'Not available: MeetingSense is off here, or a meeting is already recording.'} />
                                <ChoiceCard selected={plan === 'external'} onClick={() => setPlan('external')} icon={<HardDrive size={18} />} title="External Recorder"
                                    note="Insta360 or another recorder. HomePilot waits for the audio from Folder Sync or a later upload, and matches it by time." />
                                <ChoiceCard selected={plan === 'hybrid'} onClick={() => setPlan('hybrid')} disabled={!liveAvailable && when === 'now'} icon={<Radio size={18} />} title="Hybrid Recording"
                                    note="Record in HomePilot now and also bring in an external device’s file later (imported as its own recording)." />
                            </div>
                            {plan !== 'external' ? (
                                <fieldset className="mt-5">
                                    <legend className="text-sm font-semibold text-white/85">Capture</legend>
                                    <div className="mt-2 grid gap-2 sm:grid-cols-3">
                                        {([['audio', 'Meeting audio', AudioLines], ['mic', 'My microphone', Mic2], ['slides', 'Screen and slides', MonitorUp]] as const).map(([key, label, Icon]) => (
                                            <label key={key} className={`flex cursor-pointer items-center gap-2 rounded-xl border px-3 py-2.5 text-sm ${capture[key] ? 'border-violet-400/50 bg-violet-500/10' : 'border-white/10 bg-white/[0.02]'}`}>
                                                <input type="checkbox" checked={capture[key]} onChange={(e) => setCapture({ ...capture, [key]: e.target.checked })} className="accent-violet-500" />
                                                <Icon size={15} className="text-white/60" /> {label}
                                            </label>
                                        ))}
                                    </div>
                                </fieldset>
                            ) : (
                                <Tip>External recordings have no live transcript. When the audio arrives, HomePilot transcribes it on this computer and writes the outputs you choose.</Tip>
                            )}
                            {startsLive ? (
                                <div className="mt-5 rounded-xl border border-white/10 bg-black/30 p-3">
                                    <p className="flex items-center gap-2 text-sm font-semibold"><ShieldCheck size={15} className="text-emerald-300" /> Before you record</p>
                                    <ul className="mt-2 space-y-1 text-xs text-white/60">{privacy.map((line) => <li key={line}>• {line}</li>)}</ul>
                                    <label className="mt-3 flex items-start gap-2 text-sm">
                                        <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-0.5 accent-violet-500" />
                                        <span>I have permission to record this meeting, and the people in it know.</span>
                                    </label>
                                </div>
                            ) : null}
                        </section>
                    ) : null}

                    {step === 2 ? (
                        <section aria-labelledby="hp-wz-s3">
                            <SectionTitle id="hp-wz-s3" icon={<Sparkles size={18} />} title="Choose an assistant" note="What HomePilot does during the meeting." />
                            <div className="mt-4 grid gap-2 sm:grid-cols-2">
                                {MODES.map((m) => {
                                    const liveOnly = m.id !== null;
                                    const disabled = liveOnly && !startsLive;
                                    return (
                                        <ChoiceCard key={m.label} selected={capture.mode === m.id} disabled={disabled}
                                            onClick={() => setCapture({ ...capture, mode: m.id })} title={m.label}
                                            note={disabled ? 'Needs live recording — available when the meeting is recorded in HomePilot.' : m.note} />
                                    );
                                })}
                            </div>
                            {capture.mode === 'participant' || capture.mode === 'presenter' || capture.mode === 'coach' ? (
                                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                                    <label className="text-sm text-white/75">What people call you
                                        <input value={capture.myNames} onChange={(e) => setCapture({ ...capture, myNames: e.target.value })} placeholder="Ruslan, Rus"
                                            className="mt-1.5 h-10 w-full rounded-xl border border-white/10 bg-white/[0.03] px-3 text-sm focus:border-violet-400/70 focus:outline-none" />
                                    </label>
                                    <label className="text-sm text-white/75">Assistant name
                                        <input value={capture.assistantName} onChange={(e) => setCapture({ ...capture, assistantName: e.target.value })} placeholder="HomePilot"
                                            className="mt-1.5 h-10 w-full rounded-xl border border-white/10 bg-white/[0.03] px-3 text-sm focus:border-violet-400/70 focus:outline-none" />
                                    </label>
                                </div>
                            ) : null}
                            <label className="mt-4 block text-sm text-white/75">Meeting context <span className="text-white/40">(optional)</span>
                                <textarea value={capture.context} onChange={(e) => setCapture({ ...capture, context: e.target.value })} rows={4}
                                    placeholder="Agenda, goals, last week's minutes…"
                                    className="mt-1.5 w-full rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2 text-sm focus:border-violet-400/70 focus:outline-none" />
                            </label>
                        </section>
                    ) : null}

                    {step === 3 ? (
                        <section aria-labelledby="hp-wz-s4">
                            <SectionTitle id="hp-wz-s4" icon={<FileText size={18} />} title="Generate after the meeting" note={plan === 'external' ? 'Written once the recording has been transcribed.' : 'Written when the meeting ends.'} />
                            <div className="mt-4 grid gap-2 sm:grid-cols-2">
                                {OUTPUTS.map((o) => (
                                    <label key={o.id} className={`flex cursor-pointer items-center gap-2 rounded-xl border px-3 py-2.5 text-sm ${outputs.includes(o.id) ? 'border-violet-400/50 bg-violet-500/10' : 'border-white/10 bg-white/[0.02]'}`}>
                                        <input type="checkbox" checked={outputs.includes(o.id)} disabled={o.id === 'transcript'}
                                            onChange={(e) => setOutputs((cur) => e.target.checked ? [...cur, o.id] : cur.filter((x) => x !== o.id))}
                                            className="accent-violet-500" />
                                        {o.label}
                                    </label>
                                ))}
                            </div>
                            <p className="mt-5 text-sm font-semibold text-white/85">Summary length</p>
                            <div className="mt-2 inline-flex rounded-xl border border-white/10 bg-white/[0.02] p-1" role="radiogroup" aria-label="Summary length">
                                {SUMMARY_LENGTHS.map((l) => (
                                    <button key={l.id} type="button" role="radio" aria-checked={length === l.id} onClick={() => setLength(l.id)}
                                        className={`rounded-lg px-4 py-1.5 text-sm ${length === l.id ? 'bg-violet-600 font-semibold text-white' : 'text-white/70 hover:text-white'}`}>{l.label}</button>
                                ))}
                            </div>
                            <Tip>Summaries are written by your local model when it is available; the transcript is always kept.</Tip>
                        </section>
                    ) : null}
                </div>

                <aside className="rounded-2xl border border-white/10 bg-white/[0.02] p-5" aria-label="Meeting preview">
                    <h3 className="flex items-center gap-2 text-sm font-semibold"><CalendarDays size={16} className="text-violet-300" /> Meeting preview</h3>
                    <div className="mt-3 rounded-xl border border-white/10 bg-black/30 p-4">
                        <p className="text-lg font-semibold">{title.trim() || 'Untitled meeting'}</p>
                        <dl className="mt-3 space-y-2.5 text-sm text-white/75">
                            <PreviewRow icon={<Folder size={15} />} label="Project" value={projectName && showInProject ? projectName : 'None'} />
                            <PreviewRow icon={<CalendarDays size={15} />} label="Date" value={when === 'now' ? `Today, ${new Date().toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })}`
                                : new Date(scheduledTs).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })} />
                            <PreviewRow icon={<Clock3 size={15} />} label="Time" value={when === 'now' ? 'Now' : new Date(scheduledTs).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })} />
                            <PreviewRow icon={<Users size={15} />} label="Participants" value="Add later" />
                        </dl>
                        <div className="mt-4 rounded-xl border border-white/10 p-3 text-sm text-white/65">
                            {step === 0 ? 'You’ll choose the recording source in the next step.'
                                : plan === 'live' ? 'Recorded live in HomePilot.' : plan === 'external' ? 'Recording arrives from an external recorder.' : 'Recorded live, plus an external file later.'}
                            {step >= 2 ? <span className="mt-1 block text-xs text-white/45">Assistant: {MODES.find((m) => m.id === capture.mode)?.label || 'Note taker'}</span> : null}
                        </div>
                    </div>
                    {last ? (
                        <p className="mt-4 rounded-xl border border-violet-400/30 bg-violet-500/10 p-3 text-sm text-violet-100">
                            Ready to {startsLive ? 'start' : 'create'} the meeting.{' '}
                            {startsLive ? 'Nothing is recorded until you press Start meeting and allow capture.' : 'It appears in your Meetings library right away.'}
                        </p>
                    ) : null}
                </aside>
            </div>
        </ModalSheet>
    );
}

function SectionTitle({ id, icon, title, note, className = '' }: { id?: string; icon: React.ReactNode; title: string; note: string; className?: string }) {
    return (
        <div className={className}>
            <h3 id={id} className="flex items-center gap-2 text-lg font-semibold"><span className="text-violet-300">{icon}</span> {title}</h3>
            <p className="mt-0.5 pl-7 text-sm text-white/55">{note}</p>
        </div>
    );
}

function ChoiceCard({ selected, onClick, icon, title, note, disabled }: {
    selected: boolean; onClick: () => void; icon?: React.ReactNode; title: string; note: string; disabled?: boolean;
}) {
    return (
        <button type="button" onClick={onClick} disabled={disabled} aria-pressed={selected}
            className={`flex items-center gap-3 rounded-xl border p-3.5 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-45 ${
                selected ? 'border-violet-400 bg-violet-500/10 shadow-[0_0_0_1px_rgba(167,139,250,0.4)]' : 'border-white/10 bg-white/[0.02] hover:border-white/20'}`}>
            {icon ? <span className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl border ${selected ? 'border-violet-400/40 bg-violet-500/20 text-violet-100' : 'border-white/10 bg-white/[0.03] text-white/60'}`}>{icon}</span> : null}
            <span className="min-w-0">
                <span className="block font-semibold">{title}</span>
                <span className="block text-xs text-white/55">{note}</span>
            </span>
        </button>
    );
}

function QuickSwitch({ on, onToggle, icon, title, note, testId }: {
    on: boolean; onToggle: () => void; icon: React.ReactNode; title: string; note: string; testId: string;
}) {
    return (
        <button type="button" role="switch" aria-checked={on} onClick={onToggle} data-testid={testId}
            className={`flex items-center gap-3 rounded-xl border p-3 text-left transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-400/60 ${
                on ? 'border-violet-400/60 bg-violet-500/10' : 'border-white/10 bg-white/[0.02] hover:border-white/20'}`}>
            <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg border ${on ? 'border-violet-400/40 bg-violet-500/20 text-violet-100' : 'border-white/10 text-white/50'}`}>{icon}</span>
            <span className="min-w-0 flex-1">
                <span className={`block text-sm font-semibold ${on ? 'text-white' : 'text-white/60'}`}>{title}</span>
                <span className="block text-xs text-white/45">{note}</span>
            </span>
            <span aria-hidden className={`flex h-5 w-9 shrink-0 items-center rounded-full p-0.5 transition ${on ? 'justify-end bg-violet-500' : 'justify-start bg-white/15'}`}>
                <span className="h-4 w-4 rounded-full bg-white" />
            </span>
        </button>
    );
}

function PreviewRow({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
    return (
        <div className="flex items-center gap-3">
            <span className="text-violet-300">{icon}</span>
            <dt className="sr-only">{label}</dt>
            <dd>{label}: <span className="text-white">{value}</span></dd>
        </div>
    );
}

function Tip({ children }: { children: React.ReactNode }) {
    return (
        <p className="mt-5 flex gap-2 rounded-xl border border-white/10 bg-white/[0.02] px-3 py-2.5 text-sm text-white/60">
            <Lightbulb size={16} className="mt-0.5 shrink-0 text-sky-300" /> {children}
        </p>
    );
}

export default StartMeetingWizard;
