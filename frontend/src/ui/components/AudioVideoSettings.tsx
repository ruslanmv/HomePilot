import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertCircle,
  Camera,
  CheckCircle2,
  Mic2,
  Play,
  RefreshCw,
  Square,
  Volume2,
} from 'lucide-react';
import {
  buildAudioConstraints,
  buildVideoConstraints,
  getMediaPreferences,
  setMediaPreferences,
  type MediaPreferences,
} from '../media/mediaPreferences';
import { microphoneDebug, microphoneDebugError } from '../media/microphoneDebug';
import { describeMicrophoneRouting } from '../media/voiceSelfTest';

const SELECT_CLS =
  'w-full h-11 sm:h-10 bg-[#050505] border border-white/10 rounded-xl px-3 text-base sm:text-sm text-white ' +
  'outline-none focus:border-[#9b5cff]/60 focus:ring-2 focus:ring-[#9b5cff]/25 transition-colors [color-scheme:dark] pr-8 cursor-pointer';

const BUTTON_CLS =
  'h-10 px-3.5 rounded-xl border border-white/10 bg-white/5 hover:bg-white/10 text-xs text-white/80 ' +
  'hover:text-white font-semibold disabled:opacity-45 disabled:cursor-not-allowed transition-colors inline-flex items-center justify-center gap-2';

const MICROPHONE_TEST_MS = 5000;

type TestState = 'idle' | 'running' | 'ok' | 'error';

type OutputMediaDevices = MediaDevices & {
  selectAudioOutput?: (options?: { deviceId?: string }) => Promise<MediaDeviceInfo>;
};

type SinkAudioContext = AudioContext & {
  setSinkId?: (sinkId: string) => Promise<void>;
};

type SinkAudioElement = HTMLAudioElement & {
  setSinkId?: (sinkId: string) => Promise<void>;
};

type AudioTrackSettings = MediaTrackSettings & {
  echoCancellation?: boolean;
  noiseSuppression?: boolean;
  autoGainControl?: boolean;
};

function Switch({ checked, label, onChange, disabled = false }: {
  checked: boolean;
  label: string;
  onChange: (next: boolean) => void;
  disabled?: boolean;
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
        'relative inline-flex h-6 w-11 items-center rounded-full transition-colors shrink-0',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-[#9b5cff]/75',
        checked ? 'bg-[#9b5cff]' : 'bg-white/10',
        disabled ? 'opacity-40 cursor-not-allowed' : '',
      ].join(' ')}
    >
      <span
        className={[
          'inline-block h-4 w-4 transform rounded-full bg-white transition-transform',
          checked ? 'translate-x-6' : 'translate-x-1',
        ].join(' ')}
      />
    </button>
  );
}

function Card({ title, description, icon, children }: {
  title: string;
  description: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="bg-[#1b1c20] border border-white/[0.09] rounded-2xl p-5 sm:p-6">
      <div className="flex items-start gap-2.5 mb-4">
        <div className="text-[#9b5cff] mt-0.5 shrink-0">{icon}</div>
        <div>
          <h3 className="text-sm font-semibold text-white/95">{title}</h3>
          <p className="text-xs text-white/45 mt-0.5 leading-relaxed">{description}</p>
        </div>
      </div>
      <div className="space-y-4">{children}</div>
    </section>
  );
}

function SettingRow({ label, description, children, stack = false }: {
  label: string;
  description?: string;
  children: React.ReactNode;
  stack?: boolean;
}) {
  return (
    <div className={stack ? 'space-y-2' : 'flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between'}>
      <div className="min-w-0">
        <div className="text-sm text-white/85 font-medium">{label}</div>
        {description ? <p className="text-xs text-white/40 mt-0.5 leading-relaxed">{description}</p> : null}
      </div>
      <div className={stack ? '' : 'sm:w-72 sm:shrink-0'}>{children}</div>
    </div>
  );
}

function TestBadge({ state, idleLabel, runningLabel = 'Testing…', okLabel = 'Working', errorLabel = 'Needs attention' }: {
  state: TestState;
  idleLabel: string;
  runningLabel?: string;
  okLabel?: string;
  errorLabel?: string;
}) {
  const ok = state === 'ok';
  const error = state === 'error';
  const running = state === 'running';
  return (
    <span className={[
      'inline-flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-full border',
      ok ? 'bg-emerald-500/12 border-emerald-500/30 text-emerald-300' :
        error ? 'bg-red-500/10 border-red-500/25 text-red-300' :
          running ? 'bg-[#9b5cff]/10 border-[#9b5cff]/30 text-[#c8a7ff]' :
            'bg-white/5 border-white/10 text-white/45',
    ].join(' ')}>
      {ok ? <CheckCircle2 size={12} /> : error ? <AlertCircle size={12} /> : running ? <RefreshCw size={12} className="animate-spin" /> : null}
      {ok ? okLabel : error ? errorLabel : running ? runningLabel : idleLabel}
    </span>
  );
}

function friendlyError(error: unknown, subject = 'device'): string {
  const err = error as { name?: string; message?: string } | null;
  if (err?.name === 'NotAllowedError' || err?.name === 'PermissionDeniedError') {
    return `${subject} permission was blocked. Allow it in your browser, then try again.`;
  }
  if (err?.name === 'NotFoundError' || err?.name === 'DevicesNotFoundError') {
    return `The selected ${subject.toLowerCase()} is no longer available. Choose another device or System default.`;
  }
  if (err?.name === 'OverconstrainedError') {
    return `The selected ${subject.toLowerCase()} cannot satisfy this configuration. Choose another device.`;
  }
  if (err?.name === 'NotReadableError' || err?.name === 'TrackStartError') {
    return `The ${subject.toLowerCase()} is busy in another app or could not be started.`;
  }
  return err?.message || `The ${subject.toLowerCase()} test could not start.`;
}

export default function AudioVideoSettings() {
  const [preferences, setPreferences] = useState<MediaPreferences>(() => getMediaPreferences());
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [deviceError, setDeviceError] = useState<string | null>(null);
  const [cameraState, setCameraState] = useState<TestState>('idle');
  const [microphoneState, setMicrophoneState] = useState<TestState>('idle');
  const [speakerState, setSpeakerState] = useState<TestState>('idle');
  const [cameraMessage, setCameraMessage] = useState<string | null>(null);
  const [microphoneMessage, setMicrophoneMessage] = useState<string | null>(null);
  const [speakerMessage, setSpeakerMessage] = useState<string | null>(null);
  const [micLevel, setMicLevel] = useState(0);
  const [micSecondsLeft, setMicSecondsLeft] = useState(Math.ceil(MICROPHONE_TEST_MS / 1000));
  const [microphonePlaybackUrl, setMicrophonePlaybackUrl] = useState<string | null>(null);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const playbackRef = useRef<HTMLAudioElement | null>(null);
  const cameraStreamRef = useRef<MediaStream | null>(null);
  const microphoneStreamRef = useRef<MediaStream | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const microphoneChunksRef = useRef<Blob[]>([]);
  const microphoneDiscardRef = useRef(false);
  const microphoneStartedAtRef = useRef(0);
  const microphoneStopTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const microphoneCountdownRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const animationRef = useRef<number>(0);

  const mediaSupported = typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia;
  const secureEnough = typeof window === 'undefined' || window.isSecureContext || ['localhost', '127.0.0.1'].includes(window.location.hostname);
  const supportedConstraints = useMemo(() => {
    try {
      return navigator.mediaDevices?.getSupportedConstraints?.() ?? {};
    } catch {
      return {};
    }
  }, []);

  const cameras = devices.filter((device) => device.kind === 'videoinput');
  const microphones = devices.filter((device) => device.kind === 'audioinput');
  const speakers = devices.filter((device) => device.kind === 'audiooutput');

  // Recording and voice detection honour the selection below; browser speech
  // recognition cannot, because the Web Speech API accepts no deviceId. When
  // the two resolve to different microphones the meter moves while nothing is
  // transcribed, which is invisible without saying so here.
  const microphoneRouting = useMemo(
    () => describeMicrophoneRouting(devices, preferences.microphoneDeviceId),
    [devices, preferences.microphoneDeviceId],
  );

  const persist = useCallback((patch: Partial<MediaPreferences>) => {
    setPreferences((current) => setMediaPreferences({ ...current, ...patch }));

    if (cameraStreamRef.current && Object.prototype.hasOwnProperty.call(patch, 'cameraDeviceId')) {
      setCameraMessage('Camera changed. Restart the camera test to verify the new source.');
    }
    if (
      microphoneStreamRef.current &&
      ['microphoneDeviceId', 'echoCancellation', 'noiseSuppression', 'autoGainControl']
        .some((key) => Object.prototype.hasOwnProperty.call(patch, key))
    ) {
      setMicrophoneMessage('Microphone settings changed. Run the test again to verify them.');
    }
  }, []);

  const refreshDevices = useCallback(async () => {
    if (!navigator.mediaDevices?.enumerateDevices) return;
    try {
      setDeviceError(null);
      setDevices(await navigator.mediaDevices.enumerateDevices());
    } catch (error) {
      setDeviceError(friendlyError(error, 'Device discovery'));
    }
  }, []);

  const releaseCamera = useCallback(() => {
    cameraStreamRef.current?.getTracks().forEach((track) => track.stop());
    cameraStreamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
  }, []);

  const clearMicrophoneTimers = useCallback(() => {
    if (microphoneStopTimerRef.current) {
      clearTimeout(microphoneStopTimerRef.current);
      microphoneStopTimerRef.current = null;
    }
    if (microphoneCountdownRef.current) {
      clearInterval(microphoneCountdownRef.current);
      microphoneCountdownRef.current = null;
    }
  }, []);

  const releaseMicrophoneCapture = useCallback(() => {
    clearMicrophoneTimers();
    if (animationRef.current) {
      cancelAnimationFrame(animationRef.current);
      animationRef.current = 0;
    }
    microphoneStreamRef.current?.getTracks().forEach((track) => track.stop());
    microphoneStreamRef.current = null;
    if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
      audioContextRef.current.close().catch(() => {});
    }
    audioContextRef.current = null;
    setMicLevel(0);
  }, [clearMicrophoneTimers]);

  const cancelActiveMicrophoneTest = useCallback(() => {
    microphoneDiscardRef.current = true;
    const recorder = mediaRecorderRef.current;
    if (recorder && recorder.state !== 'inactive') {
      try { recorder.stop(); } catch { /* already stopping */ }
    }
    mediaRecorderRef.current = null;
    releaseMicrophoneCapture();
  }, [releaseMicrophoneCapture]);

  const stopCamera = useCallback(() => {
    releaseCamera();
    setCameraState('idle');
    setCameraMessage('Camera test stopped.');
  }, [releaseCamera]);

  useEffect(() => {
    if (!mediaSupported) return;
    void refreshDevices();
    const onDeviceChange = () => void refreshDevices();
    navigator.mediaDevices.addEventListener?.('devicechange', onDeviceChange);
    return () => {
      navigator.mediaDevices.removeEventListener?.('devicechange', onDeviceChange);
      releaseCamera();
      cancelActiveMicrophoneTest();
    };
  }, [mediaSupported, refreshDevices, releaseCamera, cancelActiveMicrophoneTest]);

  useEffect(() => () => {
    if (microphonePlaybackUrl) URL.revokeObjectURL(microphonePlaybackUrl);
  }, [microphonePlaybackUrl]);

  useEffect(() => {
    const audio = playbackRef.current as SinkAudioElement | null;
    if (!audio || !microphonePlaybackUrl || !preferences.speakerDeviceId || !audio.setSinkId) return;
    audio.setSinkId(preferences.speakerDeviceId).then(() => {
      microphoneDebug('settings', 'playback_output_routed', {
        speakerDeviceId: preferences.speakerDeviceId,
      });
    }).catch((error) => {
      microphoneDebugError('settings', 'playback_output_route_failed', error, {
        speakerDeviceId: preferences.speakerDeviceId,
      });
    });
  }, [microphonePlaybackUrl, preferences.speakerDeviceId]);

  const startCameraTest = useCallback(async () => {
    if (!mediaSupported) return;
    releaseCamera();
    setCameraState('running');
    setCameraMessage(null);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: buildVideoConstraints(preferences),
        audio: false,
      });
      const track = stream.getVideoTracks()[0];
      if (!track || track.readyState !== 'live') throw new Error('No live camera track was returned.');
      cameraStreamRef.current = stream;

      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => undefined);
      }

      const settings = track.getSettings();
      const size = settings.width && settings.height ? `${settings.width}×${settings.height}` : 'live video';
      setCameraState('ok');
      setCameraMessage(`Camera is live (${size}). This test did not open the microphone.`);
      await refreshDevices();
    } catch (error) {
      releaseCamera();
      setCameraState('error');
      setCameraMessage(friendlyError(error, 'Camera'));
    }
  }, [mediaSupported, preferences, refreshDevices, releaseCamera]);

  const finishMicrophoneTest = useCallback(() => {
    const recorder = mediaRecorderRef.current;
    if (!recorder || recorder.state === 'inactive') return;
    clearMicrophoneTimers();
    microphoneDebug('settings', 'recording_stop_requested', {
      elapsedMs: Math.max(0, Math.round(performance.now() - microphoneStartedAtRef.current)),
      recorderState: recorder.state,
    });
    try {
      recorder.stop();
    } catch (error) {
      microphoneDebugError('settings', 'recording_stop_failed', error);
      releaseMicrophoneCapture();
      setMicrophoneState('error');
      setMicrophoneMessage('The microphone recording could not be stopped cleanly. Run the test again.');
    }
  }, [clearMicrophoneTimers, releaseMicrophoneCapture]);

  const startMicrophoneTest = useCallback(async () => {
    if (!mediaSupported) return;
    if (typeof MediaRecorder === 'undefined') {
      setMicrophoneState('error');
      setMicrophoneMessage('This browser cannot record a microphone playback test because MediaRecorder is unavailable.');
      microphoneDebug('settings', 'test_unavailable_mediarecorder');
      return;
    }

    cancelActiveMicrophoneTest();
    microphoneDiscardRef.current = false;
    microphoneChunksRef.current = [];
    if (microphonePlaybackUrl) {
      URL.revokeObjectURL(microphonePlaybackUrl);
      setMicrophonePlaybackUrl(null);
    }
    setMicrophoneState('running');
    setMicrophoneMessage('Recording 5 seconds. Speak normally, then play it back below.');
    setMicSecondsLeft(Math.ceil(MICROPHONE_TEST_MS / 1000));

    const constraints = buildAudioConstraints(preferences);
    microphoneDebug('settings', 'test_button_click', {
      selectedDeviceId: preferences.microphoneDeviceId || 'system-default',
      durationMs: MICROPHONE_TEST_MS,
    });
    microphoneDebug('settings', 'capture_request', { constraints });

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: false, audio: constraints });
      const track = stream.getAudioTracks()[0];
      if (!track || track.readyState !== 'live') throw new Error('No live microphone track was returned.');
      microphoneStreamRef.current = stream;

      const settings = track.getSettings() as AudioTrackSettings;
      microphoneDebug('settings', 'capture_opened', {
        label: track.label || 'unlabelled microphone',
        readyState: track.readyState,
        enabled: track.enabled,
        muted: track.muted,
        deviceId: settings.deviceId || 'browser-default',
        sampleRate: settings.sampleRate,
        channelCount: settings.channelCount,
        echoCancellation: settings.echoCancellation,
        noiseSuppression: settings.noiseSuppression,
        autoGainControl: settings.autoGainControl,
      });
      track.addEventListener('mute', () => microphoneDebug('settings', 'track_muted', { label: track.label }));
      track.addEventListener('unmute', () => microphoneDebug('settings', 'track_unmuted', { label: track.label }));
      track.addEventListener('ended', () => microphoneDebug('settings', 'track_ended', { label: track.label }));

      const AudioContextCtor = window.AudioContext || (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (AudioContextCtor) {
        const ctx = new AudioContextCtor();
        audioContextRef.current = ctx;
        await ctx.resume().catch(() => undefined);
        const source = ctx.createMediaStreamSource(stream);
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 512;
        analyser.smoothingTimeConstant = 0.65;
        source.connect(analyser);
        const data = new Uint8Array(analyser.fftSize);

        const readLevel = () => {
          if (!microphoneStreamRef.current || audioContextRef.current !== ctx) return;
          analyser.getByteTimeDomainData(data);
          let sum = 0;
          for (let i = 0; i < data.length; i += 1) {
            const sample = (data[i] - 128) / 128;
            sum += sample * sample;
          }
          const rms = Math.sqrt(sum / data.length);
          setMicLevel(Math.min(1, rms * 4.5));
          animationRef.current = requestAnimationFrame(readLevel);
        };
        readLevel();
      }

      const recorder = new MediaRecorder(stream);
      mediaRecorderRef.current = recorder;
      microphoneStartedAtRef.current = performance.now();

      recorder.ondataavailable = (event) => {
        if (event.data?.size) microphoneChunksRef.current.push(event.data);
      };

      recorder.onerror = (event) => {
        const recorderError = (event as Event & { error?: DOMException }).error || new Error('MediaRecorder failed.');
        microphoneDebugError('settings', 'recorder_error', recorderError);
        microphoneDiscardRef.current = true;
        releaseMicrophoneCapture();
        setMicrophoneState('error');
        setMicrophoneMessage(friendlyError(recorderError, 'Microphone recording'));
      };

      recorder.onstop = () => {
        const elapsedMs = Math.max(0, Math.round(performance.now() - microphoneStartedAtRef.current));
        const discard = microphoneDiscardRef.current;
        const chunks = microphoneChunksRef.current;
        microphoneChunksRef.current = [];
        mediaRecorderRef.current = null;
        releaseMicrophoneCapture();

        if (discard) {
          microphoneDebug('settings', 'recording_discarded', { elapsedMs });
          return;
        }

        const mimeType = recorder.mimeType || chunks[0]?.type || 'audio/webm';
        const blob = new Blob(chunks, { type: mimeType });
        if (!blob.size) {
          microphoneDebug('settings', 'recording_empty', { elapsedMs, mimeType });
          setMicrophoneState('error');
          setMicrophoneMessage('The browser returned an empty microphone recording. Check the selected input and try again.');
          return;
        }

        const url = URL.createObjectURL(blob);
        setMicrophonePlaybackUrl(url);
        setMicrophoneState('ok');
        const seconds = Math.max(0.1, elapsedMs / 1000).toFixed(1);
        const sampleRate = settings.sampleRate ? `${Math.round(settings.sampleRate / 1000)} kHz` : 'live input';
        setMicrophoneMessage(
          `Recorded ${seconds}s from ${track.label || 'the selected microphone'} (${sampleRate}). Play it back to verify your voice is clear.`,
        );
        microphoneDebug('settings', 'recording_ready', {
          elapsedMs,
          bytes: blob.size,
          mimeType,
          label: track.label || 'unlabelled microphone',
          deviceId: settings.deviceId || 'browser-default',
        });
        void refreshDevices();
      };

      recorder.start(250);
      microphoneDebug('settings', 'recorder_started', {
        mimeType: recorder.mimeType || 'browser-selected',
        label: track.label || 'unlabelled microphone',
      });

      microphoneCountdownRef.current = setInterval(() => {
        const elapsed = performance.now() - microphoneStartedAtRef.current;
        setMicSecondsLeft(Math.max(0, Math.ceil((MICROPHONE_TEST_MS - elapsed) / 1000)));
      }, 200);
      microphoneStopTimerRef.current = setTimeout(() => {
        const active = mediaRecorderRef.current;
        if (active && active.state !== 'inactive') {
          microphoneDebug('settings', 'recording_auto_stop', { durationMs: MICROPHONE_TEST_MS });
          try { active.stop(); } catch { /* already stopping */ }
        }
      }, MICROPHONE_TEST_MS);
    } catch (error) {
      microphoneDebugError('settings', 'capture_start_failed', error, {
        selectedDeviceId: preferences.microphoneDeviceId || 'system-default',
      });
      cancelActiveMicrophoneTest();
      setMicrophoneState('error');
      setMicrophoneMessage(friendlyError(error, 'Microphone'));
    }
  }, [
    mediaSupported,
    preferences,
    refreshDevices,
    cancelActiveMicrophoneTest,
    releaseMicrophoneCapture,
    microphonePlaybackUrl,
  ]);

  const chooseSpeaker = useCallback(async () => {
    const outputDevices = navigator.mediaDevices as OutputMediaDevices;
    if (!outputDevices?.selectAudioOutput) {
      setSpeakerState('error');
      setSpeakerMessage('This browser does not support choosing an output device. HomePilot will use the system default speaker.');
      return;
    }
    try {
      const selected = await outputDevices.selectAudioOutput(
        preferences.speakerDeviceId ? { deviceId: preferences.speakerDeviceId } : undefined,
      );
      persist({ speakerDeviceId: selected.deviceId });
      setSpeakerState('idle');
      setSpeakerMessage(`Selected ${selected.label || 'speaker'}. Use Test speaker to verify it.`);
      await refreshDevices();
    } catch (error) {
      if ((error as { name?: string })?.name === 'NotAllowedError') return;
      setSpeakerState('error');
      setSpeakerMessage(friendlyError(error, 'Speaker'));
    }
  }, [persist, preferences.speakerDeviceId, refreshDevices]);

  const testSpeaker = useCallback(async () => {
    setSpeakerState('running');
    setSpeakerMessage(null);
    let ctx: SinkAudioContext | null = null;
    try {
      ctx = new AudioContext() as SinkAudioContext;
      if (preferences.speakerDeviceId) {
        if (!ctx.setSinkId) {
          throw new Error('This browser can test only the system default speaker. Output-device routing is not supported here.');
        }
        await ctx.setSinkId(preferences.speakerDeviceId);
      }
      await ctx.resume();
      const oscillator = ctx.createOscillator();
      const gain = ctx.createGain();
      oscillator.type = 'sine';
      oscillator.frequency.value = 523.25;
      gain.gain.setValueAtTime(0.0001, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.16, ctx.currentTime + 0.03);
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.5);
      oscillator.connect(gain);
      gain.connect(ctx.destination);
      oscillator.start();
      oscillator.stop(ctx.currentTime + 0.52);
      await new Promise((resolve) => setTimeout(resolve, 600));
      setSpeakerState('ok');
      setSpeakerMessage('Test tone played. If you heard it, speaker output is working.');
    } catch (error) {
      setSpeakerState('error');
      setSpeakerMessage(friendlyError(error, 'Speaker'));
    } finally {
      await ctx?.close().catch(() => undefined);
    }
  }, [preferences.speakerDeviceId]);

  const deviceLabel = (device: MediaDeviceInfo, index: number, fallback: string) => device.label || `${fallback} ${index + 1}`;
  const selectedSpeaker = speakers.find((speaker) => speaker.deviceId === preferences.speakerDeviceId);
  const selectAudioOutputSupported = typeof navigator !== 'undefined' && !!(navigator.mediaDevices as OutputMediaDevices | undefined)?.selectAudioOutput;

  if (!mediaSupported || !secureEnough) {
    return (
      <Card
        title="Audio & Video"
        description="Choose and verify the devices HomePilot uses for live conversations and meetings."
        icon={<Camera size={16} />}
      >
        <div className="rounded-xl border border-amber-500/25 bg-amber-500/10 p-4 text-xs text-amber-200/90 leading-relaxed">
          {!secureEnough
            ? 'Camera and microphone access requires HTTPS (localhost is allowed for development). Open HomePilot from a secure origin to configure devices.'
            : 'This browser does not expose the MediaDevices API required for camera and microphone testing.'}
        </div>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {deviceError ? (
        <div className="rounded-xl border border-red-500/20 bg-red-500/[0.07] px-3.5 py-3 text-xs text-red-300/80">
          Device discovery: {deviceError}
        </div>
      ) : null}

      <Card
        title="Camera"
        description="Select and test video independently. Testing the camera never opens your microphone."
        icon={<Camera size={16} />}
      >
        <SettingRow label="Camera" description="Device labels appear after you grant camera permission." stack>
          <div className="flex flex-col sm:flex-row gap-2">
            <select
              aria-label="Camera"
              className={SELECT_CLS}
              value={preferences.cameraDeviceId}
              onChange={(event) => persist({ cameraDeviceId: event.target.value })}
            >
              <option value="">System default</option>
              {cameras.map((camera, index) => (
                <option key={camera.deviceId} value={camera.deviceId}>{deviceLabel(camera, index, 'Camera')}</option>
              ))}
            </select>
            <button type="button" className={BUTTON_CLS + ' sm:shrink-0'} onClick={() => void refreshDevices()}>
              <RefreshCw size={14} /> Refresh
            </button>
          </div>
        </SettingRow>

        <SettingRow label="Mirror my preview" description="Mirrors only your local preview; it does not change the captured camera feed.">
          <Switch checked={preferences.mirrorCameraPreview} label="Mirror camera preview" onChange={(next) => persist({ mirrorCameraPreview: next })} />
        </SettingRow>

        <div className="relative overflow-hidden rounded-xl border border-white/10 bg-black aspect-video">
          <video
            ref={videoRef}
            autoPlay
            muted
            playsInline
            className={[
              'w-full h-full object-cover',
              preferences.mirrorCameraPreview ? '-scale-x-100' : '',
              cameraState === 'ok' ? 'opacity-100' : 'opacity-40',
            ].join(' ')}
          />
          {cameraState !== 'ok' && (
            <div className="absolute inset-0 flex items-center justify-center text-center p-6">
              <div>
                <Camera size={24} className="mx-auto text-white/25 mb-2" />
                <div className="text-xs text-white/45">Run the camera test to see your preview.</div>
              </div>
            </div>
          )}
        </div>

        <div className="flex flex-col sm:flex-row sm:items-center gap-3">
          {cameraState === 'ok' ? (
            <button type="button" className={BUTTON_CLS} onClick={stopCamera}><Square size={14} /> Stop camera test</button>
          ) : (
            <button type="button" className={BUTTON_CLS} onClick={() => void startCameraTest()} disabled={cameraState === 'running'}>
              {cameraState === 'running' ? <RefreshCw size={14} className="animate-spin" /> : <Play size={14} />}
              Test camera
            </button>
          )}
          <TestBadge state={cameraState} idleLabel="Not tested" okLabel="Live" />
        </div>
        {cameraMessage ? <p className={cameraState === 'error' ? 'text-xs text-red-300/80' : 'text-xs text-white/45'}>{cameraMessage}</p> : null}
      </Card>

      <Card
        title="Microphone"
        description="Record a short local sample and play it back. This verifies the selected input, real audio data, and the sound you actually captured."
        icon={<Mic2 size={16} />}
      >
        <SettingRow label="Microphone" description="The test opens only this audio input; it never starts the camera and never uploads the recording." stack>
          <select
            aria-label="Microphone"
            className={SELECT_CLS}
            value={preferences.microphoneDeviceId}
            onChange={(event) => persist({ microphoneDeviceId: event.target.value })}
          >
            <option value="">System default</option>
            {microphones.map((microphone, index) => (
              <option key={microphone.deviceId} value={microphone.deviceId}>{deviceLabel(microphone, index, 'Microphone')}</option>
            ))}
          </select>
        </SettingRow>

        {microphoneRouting.message ? (
          <div className="rounded-xl border border-amber-500/25 bg-amber-500/[0.07] px-3.5 py-3 text-[11px] leading-relaxed text-amber-200/90">
            <span className="font-semibold">Speech-to-text uses a different input. </span>
            {microphoneRouting.message}
          </div>
        ) : null}

        <SettingRow label="Input level" description="Speak normally while the 5-second recording is running. The meter should move without staying pinned at 100%.">
          <div className="h-2.5 rounded-full bg-white/10 overflow-hidden border border-white/[0.06]" aria-label={`Microphone input level ${Math.round(micLevel * 100)}%`}>
            <div className="h-full bg-[#9b5cff] transition-[width] duration-75" style={{ width: `${microphoneState === 'running' ? Math.max(2, micLevel * 100) : 0}%` }} />
          </div>
        </SettingRow>

        <div className="border-t border-white/[0.06] pt-4 space-y-4">
          <SettingRow label="Echo cancellation" description="Reduces sound from speakers feeding back into your microphone.">
            <Switch
              checked={preferences.echoCancellation}
              label="Echo cancellation"
              disabled={supportedConstraints.echoCancellation === false || microphoneState === 'running'}
              onChange={(next) => persist({ echoCancellation: next })}
            />
          </SettingRow>
          <SettingRow label="Noise suppression" description="Reduces steady background noise such as fans and HVAC.">
            <Switch
              checked={preferences.noiseSuppression}
              label="Noise suppression"
              disabled={supportedConstraints.noiseSuppression === false || microphoneState === 'running'}
              onChange={(next) => persist({ noiseSuppression: next })}
            />
          </SettingRow>
          <SettingRow label="Automatic gain control" description="Keeps speech at a useful level when your speaking distance changes.">
            <Switch
              checked={preferences.autoGainControl}
              label="Automatic gain control"
              disabled={supportedConstraints.autoGainControl === false || microphoneState === 'running'}
              onChange={(next) => persist({ autoGainControl: next })}
            />
          </SettingRow>
        </div>

        <div className="flex flex-col sm:flex-row sm:items-center gap-3 pt-1">
          {microphoneState === 'running' ? (
            <button type="button" className={BUTTON_CLS} onClick={finishMicrophoneTest}>
              <Square size={14} /> Stop & save recording
            </button>
          ) : (
            <button type="button" className={BUTTON_CLS} onClick={() => void startMicrophoneTest()}>
              <Mic2 size={14} /> {microphonePlaybackUrl ? 'Test microphone again' : 'Test microphone'}
            </button>
          )}
          <TestBadge
            state={microphoneState}
            idleLabel="Not tested"
            runningLabel={`Recording · ${micSecondsLeft}s`}
            okLabel="Recorded"
          />
        </div>
        {microphoneMessage ? <p className={microphoneState === 'error' ? 'text-xs text-red-300/80' : 'text-xs text-white/45'}>{microphoneMessage}</p> : null}

        {microphonePlaybackUrl ? (
          <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/[0.06] p-3.5 space-y-2.5">
            <div className="flex items-center gap-2 text-xs font-medium text-emerald-200">
              <CheckCircle2 size={14} /> Playback your microphone recording
            </div>
            <p className="text-[11px] leading-relaxed text-white/45">
              Press play and confirm that you can hear your own voice clearly. The sample stays only in this browser tab.
            </p>
            <audio
              ref={playbackRef}
              src={microphonePlaybackUrl}
              controls
              className="w-full h-10"
              onPlay={() => microphoneDebug('settings', 'playback_started', {
                speakerDeviceId: preferences.speakerDeviceId || 'system-default',
              })}
              onEnded={() => microphoneDebug('settings', 'playback_ended')}
              onError={(event) => microphoneDebug('settings', 'playback_error', {
                mediaErrorCode: (event.currentTarget as HTMLAudioElement).error?.code || null,
              })}
            />
          </div>
        ) : null}

        <div className="text-[10px] leading-relaxed text-white/30">
          Diagnostics: open DevTools and filter the console for <span className="font-mono text-white/45">HomePilot:Mic</span>. The trace records device/capture state, never audio bytes or transcript text.
        </div>
      </Card>

      <Card
        title="Speaker"
        description="Choose an output where supported, then play a short local test tone."
        icon={<Volume2 size={16} />}
      >
        <SettingRow label="Output device" description={selectAudioOutputSupported ? 'Your browser will ask which speaker or headset HomePilot may use.' : 'Output selection is not supported here; the system default will be used.'}>
          <div className="flex items-center gap-2">
            <div className="min-w-0 flex-1 h-10 px-3 rounded-xl bg-[#050505] border border-white/10 flex items-center text-xs text-white/70 truncate">
              {selectedSpeaker?.label || (preferences.speakerDeviceId ? 'Selected output' : 'System default')}
            </div>
            <button type="button" className={BUTTON_CLS + ' shrink-0'} onClick={() => void chooseSpeaker()} disabled={!selectAudioOutputSupported}>
              Choose…
            </button>
          </div>
        </SettingRow>
        <div className="flex flex-col sm:flex-row sm:items-center gap-3">
          <button type="button" className={BUTTON_CLS} onClick={() => void testSpeaker()} disabled={speakerState === 'running'}>
            {speakerState === 'running' ? <RefreshCw size={14} className="animate-spin" /> : <Play size={14} />}
            Test speaker
          </button>
          <TestBadge state={speakerState} idleLabel="Not tested" okLabel="Tone played" />
        </div>
        {speakerMessage ? <p className={speakerState === 'error' ? 'text-xs text-red-300/80' : 'text-xs text-white/45'}>{speakerMessage}</p> : null}
      </Card>
    </div>
  );
}
