/**
 * Read-only microphone monitor for the Web Speech path.
 *
 * SpeechRecognition owns an opaque browser capture: it exposes words and lifecycle events,
 * but no MediaStream or audio samples. That does not mean Voice has to lose its input meter.
 * This helper opens the browser/default microphone separately and uses it only for RMS level
 * visualization. It never runs VAD, never records bytes and never decides turn boundaries.
 * The browser recognizer remains the only transcription source.
 */
import { microphoneDebug } from '../media/microphoneDebug';

export interface BrowserInputMeter {
  stop: (reason?: string) => void;
}

type WebkitAudioWindow = typeof window & {
  webkitAudioContext?: typeof AudioContext;
};

function audioContextCtor(): typeof AudioContext | null {
  if (typeof window === 'undefined') return null;
  return window.AudioContext || (window as WebkitAudioWindow).webkitAudioContext || null;
}

export function browserInputMeterAvailable(): boolean {
  return typeof navigator !== 'undefined'
    && Boolean(navigator.mediaDevices?.getUserMedia)
    && Boolean(audioContextCtor());
}

export async function startBrowserInputMeter(
  onLevel: (level: number) => void,
): Promise<BrowserInputMeter> {
  const Ctor = audioContextCtor();
  if (!Ctor || !navigator.mediaDevices?.getUserMedia) {
    throw new Error('Browser microphone level monitoring is unavailable.');
  }

  // Deliberately ask for the browser/system default input. Web Speech accepts no deviceId,
  // so measuring the user-selected HomePilot device here would recreate the misleading split
  // where the meter moves for a microphone the recognizer is not listening to.
  const stream = await navigator.mediaDevices.getUserMedia({ video: false, audio: true });
  const track = stream.getAudioTracks()[0];
  if (!track || track.readyState !== 'live') {
    stream.getTracks().forEach((candidate) => candidate.stop());
    throw new Error('No live default microphone track was returned for the input meter.');
  }

  let context: AudioContext | null = null;
  let timer: number | null = null;
  let stopped = false;

  try {
    context = new Ctor();
    if (context.state === 'suspended') {
      await context.resume().catch(() => undefined);
    }

    const analyser = context.createAnalyser();
    analyser.fftSize = 512;
    analyser.smoothingTimeConstant = 0.65;
    const source = context.createMediaStreamSource(stream);
    source.connect(analyser);
    const data = new Uint8Array(analyser.fftSize);

    const sample = () => {
      if (stopped) return;
      analyser.getByteTimeDomainData(data);
      let sum = 0;
      for (let i = 0; i < data.length; i += 1) {
        const value = (data[i] - 128) / 128;
        sum += value * value;
      }
      // Feed raw RMS-style 0..1 levels, matching the VAD controller contract. VoiceModeGrok
      // already applies the display gain/attack/release it needs; amplifying here too makes
      // normal speech pin the meter at 100% and destroys the visual dynamics.
      onLevel(Math.min(1, Math.sqrt(sum / data.length)));
    };

    sample();
    timer = window.setInterval(sample, 80);
    microphoneDebug('voice', 'browser_input_meter_started', {
      label: track.label || 'browser default microphone',
      deviceId: track.getSettings?.().deviceId || 'browser-default',
    });

    return {
      stop: (reason = 'stopped') => {
        if (stopped) return;
        stopped = true;
        if (timer !== null) window.clearInterval(timer);
        timer = null;
        try { (source as AudioNode).disconnect(); } catch { /* already disconnected */ }
        stream.getTracks().forEach((candidate) => candidate.stop());
        if (context && context.state !== 'closed') void context.close().catch(() => undefined);
        context = null;
        onLevel(0);
        microphoneDebug('voice', 'browser_input_meter_stopped', { reason });
      },
    };
  } catch (error) {
    if (timer !== null) window.clearInterval(timer);
    stream.getTracks().forEach((candidate) => candidate.stop());
    if (context && context.state !== 'closed') void context.close().catch(() => undefined);
    onLevel(0);
    throw error;
  }
}
