/**
 * Settings → Voice Assistant → "Speech Recognition".
 *
 * HomePilot has two transcription paths with genuinely different trade-offs, and a third
 * that belongs to MeetingSense and is not interchangeable with either. This card is where
 * that stops being an implementation detail.
 *
 * **Why a choice rather than a detection.** Preferring the local engine whenever it reported
 * itself available broke chat speech-to-text on a machine whose CUDA runtime was present but
 * incomplete: the provider answered "available" and then failed every single turn, while the
 * browser path would have worked fine. Availability is not suitability, and only the person
 * using it can weigh privacy against latency against setup.
 *
 * **Why the browser is the default.** It is what HomePilot behaved like before on-device
 * transcription existed, and it needs nothing installed. A default that works everywhere
 * beats a better default that works on some machines.
 *
 * **Why meetings are read-only here.** MeetingSense streams two channels of continuous audio
 * over its own socket and needs speaker labels; the browser recognizer can do none of that.
 * There is exactly one engine, so this reports it instead of pretending to offer a choice.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Check, Cpu, Globe, Mic2, Wand2 } from 'lucide-react';
import { resolveBackendUrl } from '../lib/backendUrl';
import { microphoneDebug } from '../media/microphoneDebug';
import { getSttCapability, type SttCapability } from '../media/sttService';
import {
  describeSttResolution,
  getSttPreferences,
  resolveSttEngine,
  setSttPreferences,
  subscribeSttPreferences,
  type SttEnginePreference,
} from '../media/sttPreferences';

interface Option {
  id: SttEnginePreference;
  label: string;
  icon: typeof Globe;
  summary: string;
  /** The honest trade-off. Every option has one; hiding it makes the choice meaningless. */
  goods: readonly string[];
  bads: readonly string[];
}

const OPTIONS: readonly Option[] = [
  {
    id: 'web-speech',
    label: 'Browser',
    icon: Globe,
    summary: 'Your browser’s built-in speech recognition. Nothing to install.',
    goods: ['Shows words as you speak', 'No setup, no CPU cost'],
    bads: [
      'Records your system default input, not the microphone selected in Audio & Video',
      'Chrome sends audio to a Google service, so it needs the internet',
      'Not available in Firefox or Safari',
    ],
  },
  {
    id: 'homepilot',
    label: 'On this computer',
    icon: Cpu,
    summary: 'HomePilot transcribes with its own speech model.',
    goods: [
      'Records the microphone you selected in Audio & Video',
      'Audio never leaves this computer; works offline',
      'Works in any browser that can record',
    ],
    bads: [
      'Needs a speech model installed on the server',
      'No live words — the text arrives when you finish the turn',
      'Uses CPU or GPU for every turn',
    ],
  },
  {
    id: 'auto',
    label: 'Automatic',
    icon: Wand2,
    summary: 'On this computer when a speech model is installed, the browser otherwise.',
    goods: ['Never leaves you without voice input'],
    bads: ['Which engine runs — and whether audio leaves the machine — can change'],
  },
];

const CARD =
  'rounded-2xl border border-white/[0.08] bg-white/[0.025] p-4';

export default function SpeechRecognitionSettings(): JSX.Element {
  const [preference, setPreference] = useState<SttEnginePreference>(
    () => getSttPreferences().chat,
  );
  const [capability, setCapability] = useState<SttCapability | null>(null);
  const [meeting, setMeeting] = useState<{ provider: string | null; available: boolean } | null>(
    null,
  );

  const webSpeechSupported = useMemo(
    () => typeof window !== 'undefined'
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      && (!!(window as any).SpeechRecognition || !!(window as any).webkitSpeechRecognition),
    [],
  );
  const mediaRecorderSupported = typeof MediaRecorder !== 'undefined'
    && Boolean(navigator.mediaDevices?.getUserMedia);

  useEffect(() => subscribeSttPreferences((next) => setPreference(next.chat)), []);

  useEffect(() => {
    let cancelled = false;
    void getSttCapability().then((value) => { if (!cancelled) setCapability(value); });
    return () => { cancelled = true; };
  }, []);

  // MeetingSense answers separately, and its provider is chosen by a different rule — local
  // first, never crossing to a remote endpoint on its own. Reported, never offered.
  useEffect(() => {
    let cancelled = false;
    fetch(`${resolveBackendUrl().replace(/\/+$/, '')}/v1/meetingsense/status`, {
      headers: { Accept: 'application/json' },
    })
      .then((response) => (response.ok ? response.json() : null))
      .then((body) => {
        if (cancelled || !body) return;
        setMeeting({
          provider: body?.stt?.provider ?? null,
          available: Boolean(body?.stt?.available),
        });
      })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, []);

  const resolution = useMemo(
    () => resolveSttEngine(preference, {
      backendAvailable: Boolean(capability?.available),
      mediaRecorderSupported,
      webSpeechSupported,
    }),
    [preference, capability, mediaRecorderSupported, webSpeechSupported],
  );

  const choose = useCallback((next: SttEnginePreference) => {
    setSttPreferences({ ...getSttPreferences(), chat: next });
    setPreference(next);
    microphoneDebug('settings', 'stt_preference_changed', { scenario: 'chat', preference: next });
  }, []);

  return (
    <div className="space-y-4" data-testid="speech-recognition-settings">
      <div>
        <div className="text-[11px] uppercase tracking-wider text-white/40 mb-1 font-semibold">
          Chat and Voice
        </div>
        <p className="text-[11px] leading-relaxed text-white/40">
          Which engine turns your speech into text in the chat composer and the Voice tab.
          Meetings are separate — see below.
        </p>
      </div>

      <div className="grid gap-2.5 sm:grid-cols-3" role="radiogroup" aria-label="Speech recognition engine">
        {OPTIONS.map((option) => {
          const selected = preference === option.id;
          const Icon = option.icon;
          return (
            <button
              key={option.id}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => choose(option.id)}
              data-testid={`stt-engine-${option.id}`}
              className={[
                'text-left rounded-xl border p-3 transition focus:outline-none',
                'focus-visible:ring-2 focus-visible:ring-[#9b5cff]/60',
                selected
                  ? 'border-[#9b5cff]/40 bg-[#9b5cff]/[0.08]'
                  : 'border-white/[0.08] bg-white/[0.02] hover:border-white/20',
              ].join(' ')}
            >
              <div className="flex items-center gap-2">
                <Icon size={14} className={selected ? 'text-[#c8a7ff]' : 'text-white/45'} />
                <span className={selected ? 'text-xs font-semibold text-white' : 'text-xs font-medium text-white/70'}>
                  {option.label}
                </span>
                {selected ? <Check size={13} className="ml-auto text-[#c8a7ff]" /> : null}
              </div>
              <p className="mt-1.5 text-[10px] leading-relaxed text-white/45">{option.summary}</p>
            </button>
          );
        })}
      </div>

      {/* The trade-off for whatever is selected, spelled out. A choice presented without its
          cost is not a choice the user can actually make. */}
      {OPTIONS.filter((option) => option.id === preference).map((option) => (
        <div key={option.id} className="grid gap-2 sm:grid-cols-2">
          <ul className="space-y-1">
            {option.goods.map((good) => (
              <li key={good} className="flex gap-1.5 text-[10px] leading-relaxed text-emerald-200/70">
                <span aria-hidden="true">+</span><span>{good}</span>
              </li>
            ))}
          </ul>
          <ul className="space-y-1">
            {option.bads.map((bad) => (
              <li key={bad} className="flex gap-1.5 text-[10px] leading-relaxed text-amber-200/70">
                <span aria-hidden="true">−</span><span>{bad}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}

      {/* What will actually run, which is not always what was picked. */}
      <div
        className={[
          CARD,
          resolution.fellBack || !resolution.usable ? 'border-amber-500/25 bg-amber-500/[0.06]' : '',
        ].join(' ')}
        data-testid="stt-resolution"
        role="status"
      >
        <div className="flex gap-2.5">
          <span className="mt-0.5 shrink-0 text-white/45">
            {resolution.fellBack || !resolution.usable
              ? <AlertTriangle size={14} className="text-amber-300/80" />
              : <Mic2 size={14} />}
          </span>
          <div className="min-w-0">
            <div className="text-[11px] font-medium text-white/85">
              {resolution.fellBack ? 'Not the engine you chose' : 'In use now'}
            </div>
            <p className="mt-0.5 text-[10px] leading-relaxed text-white/50">
              {describeSttResolution(resolution, capability?.provider ?? null)}
            </p>
            {capability && !capability.available && capability.hint ? (
              <p className="mt-1 text-[10px] leading-relaxed text-white/35">{capability.hint}</p>
            ) : null}
            {capability?.remote ? (
              <p className="mt-1 text-[10px] leading-relaxed text-amber-200/70">
                This server is configured with a remote speech service, so recordings leave this
                computer.
              </p>
            ) : null}
          </div>
        </div>
      </div>

      {/* Meetings: reported, not offered. */}
      <div className={CARD} data-testid="stt-meetings">
        <div className="text-[11px] uppercase tracking-wider text-white/40 mb-1 font-semibold">
          Meetings
        </div>
        <p className="text-[10px] leading-relaxed text-white/50">
          {meeting === null
            ? 'Checking what meetings transcribe with…'
            : meeting.available
              ? `Meetings are transcribed by ${meeting.provider || 'a local speech model'}, on this computer.`
              : 'Meetings cannot be transcribed yet: no speech model is installed on this server.'}
        </p>
        <p className="mt-1.5 text-[10px] leading-relaxed text-white/35">
          This is not a setting. A meeting records two channels of continuous audio and needs
          speaker labels, which the browser’s recognizer cannot do — so there is one
          engine rather than a choice. Meetings also never send audio to a remote service on
          their own, even when one is configured for chat.
        </p>
      </div>
    </div>
  );
}
