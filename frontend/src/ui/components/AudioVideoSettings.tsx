import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertCircle,
  Camera,
  CheckCircle2,
  Mic2,
  MonitorUp,
  Play,
  RefreshCw,
  ShieldCheck,
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

const SELECT_CLS =
  'w-full h-11 sm:h-10 bg-[#050505] border border-white/10 rounded-xl px-3 text-base sm:text-sm text-white ' +
  'outline-none focus:border-[#9b5cff]/60 focus:ring-2 focus:ring-[#9b5cff]/25 transition-colors [color-scheme:dark] pr-8 cursor-pointer';

const BUTTON_CLS =
  'h-10 px-3.5 rounded-xl border border-white/10 bg-white/5 hover:bg-white/10 text-xs text-white/80 ' +
  'hover:text-white font-semibold disabled:opacity-45 disabled:cursor-not-allowed transition-colors inline-flex items-center justify-center gap-2';

type TestState = 'idle' | 'running' | 'ok' | 'error';

type OutputMediaDevices = MediaDevices & {
  selectAudioOutput?: (options?: { deviceId?: string }) => Promise<MediaDeviceInfo>;
};

type SinkAudioContext = AudioContext & {
  setSinkId?: (sinkId: string) => Promise<void>;
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

function friendlyError(error: unknown): string {
  const err = error as { name?: string; message?: string } | null;
  if (err?.name === 'NotAllowedError' || err?.name === 'PermissionDeniedError') {
    return 'Permission was blocked. Allow camera/microphone access in your browser, then try again.';
  }
  if (err?.name === 'NotFoundError' || err?.name === 'DevicesNotFoundError') {
    return 'The selected device is no longer available. Choose another device or System default.';
  }
  if (err?.name === 'OverconstrainedError') {
    return 'The selected device cannot satisfy this configuration. Choose another device.';
  }
  if (err?.name === 'NotReadableError' || err?.name === 'TrackStartError') {
    return 'The device is busy in another app or could not be started.';
  }
  return err?.message || 'The media test could not start.';
}

export default function AudioVideoSettings() {
  const [preferences, setPreferences] = useState<MediaPreferences>(() => getMediaPreferences());
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [deviceError, setDeviceError] = useState<string | null>(null);
  const [previewState, setPreviewState] = useState<TestState>('idle');
  const [speakerState, setSpeakerState] = useState<TestState>('idle');
  const [screenState, setScreenState] = useState<TestState>('idle');
  const [previewMessage, setPreviewMessage] = useState<string | null>(null);
  const [speakerMessage, setSpeakerMessage] = useState<string | null>(null);
  const [screenMessage, setScreenMessage] = useState<string | null>(null);
  const [micLevel, setMicLevel] = useState(0);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
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

  const persist = useCallback((patch: Partial<MediaPreferences>) => {
    setPreferences((current) => {
      const next = setMediaPreferences({ ...current, ...patch });
      return next;
    });
    if (streamRef.current) {
      setPreviewMessage('Settings changed. Restart the camera & microphone test to verify the new source.');
    }
  }, []);

  const refreshDevices = useCallback(async () => {
    if (!navigator.mediaDevices?.enumerateDevices) return;
    try {
      setDeviceError(null);
      setDevices(await navigator.mediaDevices.enumerateDevices());
    } catch (error) {
      setDeviceError(friendlyError(error));
    }
  }, []);

  const stopPreview = useCallback(() => {
    if (animationRef.current) {
      cancelAnimationFrame(animationRef.current);
      animationRef.current = 0;
    }
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
      audioContextRef.current.close().catch(() => {});
    }
    audioContextRef.current = null;
    setMicLevel(0);
    setPreviewState('idle');
  }, []);

  useEffect(() => {
    if (!mediaSupported) return;
    void refreshDevices();
    const onDeviceChange = () => void refreshDevices();
    navigator.mediaDevices.addEventListener?.('devicechange', onDeviceChange);
    return () => {
      navigator.mediaDevices.removeEventListener?.('devicechange', onDeviceChange);
      stopPreview();
    };
  }, [mediaSupported, refreshDevices, stopPreview]);

  const startPreview = useCallback(async () => {
    if (!mediaSupported) return;
    stopPreview();
    setPreviewState('running');
    setPreviewMessage(null);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: buildVideoConstraints(preferences),
        audio: buildAudioConstraints(preferences),
      });
      streamRef.current = stream;

      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => undefined);
      }

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
          if (!streamRef.current || audioContextRef.current !== ctx) return;
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

      const videoSettings = stream.getVideoTracks()[0]?.getSettings();
      const audioSettings = stream.getAudioTracks()[0]?.getSettings();
      const parts = [
        videoSettings?.width && videoSettings?.height ? `${videoSettings.width}×${videoSettings.height}` : null,
        audioSettings?.sampleRate ? `${Math.round(audioSettings.sampleRate / 1000)} kHz mic` : 'microphone active',
      ].filter(Boolean);
      setPreviewMessage(`Live test is using the selected devices${parts.length ? ` (${parts.join(', ')})` : ''}.`);
      setPreviewState('ok');
      await refreshDevices();
    } catch (error) {
      stopPreview();
      setPreviewState('error');
      setPreviewMessage(friendlyError(error));
    }
  }, [mediaSupported, preferences, refreshDevices, stopPreview]);

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
      setSpeakerMessage(friendlyError(error));
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
      setSpeakerMessage(friendlyError(error));
    } finally {
      await ctx?.close().catch(() => undefined);
    }
  }, [preferences.speakerDeviceId]);

  const testScreenSharing = useCallback(async () => {
    if (!navigator.mediaDevices?.getDisplayMedia) {
      setScreenState('error');
      setScreenMessage('Screen sharing is not supported by this browser or device.');
      return;
    }
    setScreenState('running');
    setScreenMessage(null);
    let stream: MediaStream | null = null;
    try {
      stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
      const track = stream.getVideoTracks()[0];
      if (!track || track.readyState !== 'live') throw new Error('No screen-share video track was returned.');
      setScreenState('ok');
      setScreenMessage('Screen sharing permission and capture are working. The test share has been stopped.');
    } catch (error) {
      if ((error as { name?: string })?.name === 'NotAllowedError') {
        setScreenState('idle');
        setScreenMessage('Screen-share test cancelled.');
      } else {
        setScreenState('error');
        setScreenMessage(friendlyError(error));
      }
    } finally {
      stream?.getTracks().forEach((track) => track.stop());
    }
  }, []);

  const deviceLabel = (device: MediaDeviceInfo, index: number, fallback: string) => device.label || `${fallback} ${index + 1}`;
  const selectedSpeaker = speakers.find((speaker) => speaker.deviceId === preferences.speakerDeviceId);
  const selectAudioOutputSupported = !!(navigator.mediaDevices as OutputMediaDevices | undefined)?.selectAudioOutput;

  if (!mediaSupported || !secureEnough) {
    return (
      <Card
        title="Audio & Video"
        description="Choose and verify the devices HomePilot uses for live conversations."
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
      <Card
        title="Camera"
        description="Select the camera used for live video and verify the real capture before a conversation."
        icon={<Camera size={16} />}
      >
        <SettingRow label="Camera" description="Device labels appear after you grant media permission." stack>
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
              previewState === 'ok' ? 'opacity-100' : 'opacity-40',
            ].join(' ')}
          />
          {previewState !== 'ok' && (
            <div className="absolute inset-0 flex items-center justify-center text-center p-6">
              <div>
                <Camera size={24} className="mx-auto text-white/25 mb-2" />
                <div className="text-xs text-white/45">Start the device test to see your camera.</div>
              </div>
            </div>
          )}
        </div>
      </Card>

      <Card
        title="Microphone"
        description="HomePilot Voice uses this same microphone and the same processing settings below."
        icon={<Mic2 size={16} />}
      >
        <SettingRow label="Microphone" stack>
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

        <SettingRow label="Input level" description="Speak normally. The meter should move without staying pinned at 100%.">
          <div className="h-2.5 rounded-full bg-white/10 overflow-hidden border border-white/[0.06]" aria-label={`Microphone input level ${Math.round(micLevel * 100)}%`}>
            <div className="h-full bg-[#9b5cff] transition-[width] duration-75" style={{ width: `${Math.max(2, micLevel * 100)}%` }} />
          </div>
        </SettingRow>

        <div className="border-t border-white/[0.06] pt-4 space-y-4">
          <SettingRow label="Echo cancellation" description="Reduces sound from HomePilot or other speakers feeding back into your mic.">
            <Switch
              checked={preferences.echoCancellation}
              label="Echo cancellation"
              disabled={supportedConstraints.echoCancellation === false}
              onChange={(next) => persist({ echoCancellation: next })}
            />
          </SettingRow>
          <SettingRow label="Noise suppression" description="Reduces steady background noise such as fans and HVAC.">
            <Switch
              checked={preferences.noiseSuppression}
              label="Noise suppression"
              disabled={supportedConstraints.noiseSuppression === false}
              onChange={(next) => persist({ noiseSuppression: next })}
            />
          </SettingRow>
          <SettingRow label="Automatic gain control" description="Keeps speech at a useful level when your speaking distance changes.">
            <Switch
              checked={preferences.autoGainControl}
              label="Automatic gain control"
              disabled={supportedConstraints.autoGainControl === false}
              onChange={(next) => persist({ autoGainControl: next })}
            />
          </SettingRow>
        </div>

        <div className="flex flex-col sm:flex-row sm:items-center gap-3 pt-1">
          {previewState === 'ok' ? (
            <button type="button" className={BUTTON_CLS} onClick={stopPreview}><Square size={14} /> Stop camera &amp; mic test</button>
          ) : (
            <button type="button" className={BUTTON_CLS} onClick={() => void startPreview()} disabled={previewState === 'running'}>
              {previewState === 'running' ? <RefreshCw size={14} className="animate-spin" /> : <Play size={14} />}
              Test camera &amp; microphone
            </button>
          )}
          <TestBadge state={previewState} idleLabel="Not tested" okLabel="Live" />
        </div>
        {previewMessage ? <p className={previewState === 'error' ? 'text-xs text-red-300/80' : 'text-xs text-white/45'}>{previewMessage}</p> : null}
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

      <Card
        title="Troubleshooting"
        description="Verify the browser permissions and capture paths HomePilot depends on."
        icon={<ShieldCheck size={16} />}
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-xl bg-[#050505] border border-white/10 p-4 space-y-3">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-sm text-white/80"><Camera size={15} /> Camera &amp; microphone</div>
              <TestBadge state={previewState} idleLabel="Not tested" />
            </div>
            <p className="text-[11px] text-white/40 leading-relaxed">Checks real camera frames, microphone capture, the input meter, and your selected DSP constraints.</p>
            <button type="button" className={BUTTON_CLS + ' w-full'} onClick={() => void startPreview()} disabled={previewState === 'running'}>Run test</button>
          </div>
          <div className="rounded-xl bg-[#050505] border border-white/10 p-4 space-y-3">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-sm text-white/80"><MonitorUp size={15} /> Screen sharing</div>
              <TestBadge state={screenState} idleLabel="Not tested" />
            </div>
            <p className="text-[11px] text-white/40 leading-relaxed">Opens the browser's screen picker, verifies a live display track, then stops the test immediately.</p>
            <button type="button" className={BUTTON_CLS + ' w-full'} onClick={() => void testScreenSharing()} disabled={screenState === 'running'}>Run test</button>
          </div>
        </div>
        {screenMessage ? <p className={screenState === 'error' ? 'text-xs text-red-300/80' : 'text-xs text-white/45'}>{screenMessage}</p> : null}
        {deviceError ? <p className="text-xs text-red-300/80">Device discovery: {deviceError}</p> : null}
        <div className="rounded-xl border border-white/[0.07] bg-white/[0.025] px-3.5 py-3 text-[11px] text-white/40 leading-relaxed">
          Device choices and microphone processing are saved automatically on this browser. HomePilot Voice reads the same microphone source and processing preferences when it starts listening.
        </div>
      </Card>
    </div>
  );
}
