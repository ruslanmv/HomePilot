/**
 * Adaptive Voice Activity Detection (VAD)
 *
 * Industry-standard implementation with:
 * - Noise floor estimation with exponential decay
 * - Hysteresis to prevent state flicker
 * - EMA smoothing for stable readings
 * - Browser AEC/NS/AGC for echo cancellation
 * - Never stops during TTS (barge-in capable)
 */

import {
  buildAudioConstraints,
  getMediaPreferences,
  isDeviceSelectionError,
} from '../media/mediaPreferences';
import { microphoneDebug, microphoneDebugError } from '../media/microphoneDebug';

export type VADConfig = {
  baseThreshold: number;
  hysteresisHigh: number;
  hysteresisLow: number;
  minSpeechMs: number;
  silenceMs: number;
  emaAlpha: number;
  noiseFloorDecay: number;
  noiseFloorMin: number;
};

export type VADState = 'idle' | 'speech' | 'silence_pending';

export type VADCallbacks = {
  onSpeechStart: () => void;
  onSpeechEnd: () => void;
  onStateChange?: (state: VADState) => void;
  onLevelChange?: (level: number, threshold: number, noiseFloor: number) => void;
};

export interface VADInstance {
  start: () => Promise<void>;
  stop: () => void;
  pause: () => void;
  resume: () => void;
  getState: () => VADState;
  isRunning: () => boolean;
  isPaused: () => boolean;
  getCurrentLevel: () => number;
  getNoiseFloor: () => number;
  getThreshold: () => number;
}

const DEFAULT_CONFIG: VADConfig = {
  baseThreshold: 0.035,
  hysteresisHigh: 1.8,
  hysteresisLow: 0.9,
  minSpeechMs: 200,
  silenceMs: 800,
  emaAlpha: 0.2,
  noiseFloorDecay: 0.997,
  noiseFloorMin: 0.005,
};

export function createVAD(
  onSpeechStart: () => void,
  onSpeechEnd: () => void,
  config?: Partial<VADConfig>
): VADInstance {
  const cfg: VADConfig = { ...DEFAULT_CONFIG, ...config };
  const callbacks: VADCallbacks = { onSpeechStart, onSpeechEnd };

  let ctx: AudioContext | null = null;
  let analyser: AnalyserNode | null = null;
  let src: MediaStreamAudioSourceNode | null = null;
  let stream: MediaStream | null = null;
  let raf = 0;
  let startInFlight: Promise<void> | null = null;

  let state: VADState = 'idle';
  let running = false;
  let paused = false;

  let currentLevel = 0;
  let smoothedLevel = 0;
  let noiseFloor = cfg.noiseFloorMin;

  let speechStartAt = 0;
  let lastAboveAt = 0;
  let silenceStartAt = 0;

  let calibrationSamples: number[] = [];
  let isCalibrating = true;
  const CALIBRATION_SAMPLES = 30;

  function setState(newState: VADState) {
    if (state !== newState) {
      state = newState;
      callbacks.onStateChange?.(newState);
    }
  }

  function calculateRMS(data: Uint8Array): number {
    let sum = 0;
    for (let i = 0; i < data.length; i++) {
      const v = (data[i] - 128) / 128;
      sum += v * v;
    }
    return Math.sqrt(sum / data.length);
  }

  function updateNoiseFloor(level: number) {
    if (isCalibrating) {
      calibrationSamples.push(level);
      if (calibrationSamples.length >= CALIBRATION_SAMPLES) {
        calibrationSamples.sort((a, b) => a - b);
        const median = calibrationSamples[Math.floor(calibrationSamples.length / 2)];
        noiseFloor = Math.max(median * 1.2, cfg.noiseFloorMin);
        isCalibrating = false;
        microphoneDebug('vad', 'calibration_complete', {
          noiseFloor: Number(noiseFloor.toFixed(5)),
          threshold: Number(getAdaptiveThreshold().toFixed(5)),
        });
      }
      return;
    }

    if (level < noiseFloor * 2) {
      noiseFloor = Math.max(
        cfg.noiseFloorMin,
        noiseFloor * cfg.noiseFloorDecay + level * (1 - cfg.noiseFloorDecay)
      );
    }
  }

  function getAdaptiveThreshold(): number {
    const base = noiseFloor + cfg.baseThreshold;
    if (state === 'idle') return base * cfg.hysteresisHigh;
    return base * cfg.hysteresisLow;
  }

  function tick() {
    if (!analyser || !running) return;

    if (paused) {
      raf = requestAnimationFrame(tick);
      return;
    }

    const data = new Uint8Array(analyser.frequencyBinCount);
    analyser.getByteTimeDomainData(data);
    currentLevel = calculateRMS(data);
    smoothedLevel = cfg.emaAlpha * currentLevel + (1 - cfg.emaAlpha) * smoothedLevel;
    updateNoiseFloor(smoothedLevel);

    const threshold = getAdaptiveThreshold();
    const now = performance.now();
    callbacks.onLevelChange?.(smoothedLevel, threshold, noiseFloor);

    if (isCalibrating) {
      raf = requestAnimationFrame(tick);
      return;
    }

    switch (state) {
      case 'idle':
        if (smoothedLevel >= threshold) {
          lastAboveAt = now;
          speechStartAt = now;
          setState('speech');
          microphoneDebug('vad', 'speech_detected', {
            level: Number(smoothedLevel.toFixed(5)),
            threshold: Number(threshold.toFixed(5)),
            noiseFloor: Number(noiseFloor.toFixed(5)),
          });
          callbacks.onSpeechStart();
        }
        break;

      case 'speech':
        if (smoothedLevel >= threshold * cfg.hysteresisLow) {
          lastAboveAt = now;
        } else {
          const silenceDur = now - lastAboveAt;
          const speechDur = now - speechStartAt;

          if (speechDur >= cfg.minSpeechMs && silenceDur >= cfg.silenceMs) {
            setState('idle');
            microphoneDebug('vad', 'speech_ended', {
              speechMs: Math.round(speechDur),
              silenceMs: Math.round(silenceDur),
              level: Number(smoothedLevel.toFixed(5)),
            });
            callbacks.onSpeechEnd();
          } else if (silenceDur > 100) {
            silenceStartAt = lastAboveAt;
            setState('silence_pending');
          }
        }
        break;

      case 'silence_pending':
        if (smoothedLevel >= threshold * cfg.hysteresisLow) {
          lastAboveAt = now;
          setState('speech');
        } else {
          const silenceDur = now - lastAboveAt;
          const speechDur = lastAboveAt - speechStartAt;

          if (speechDur >= cfg.minSpeechMs && silenceDur >= cfg.silenceMs) {
            setState('idle');
            microphoneDebug('vad', 'speech_ended', {
              speechMs: Math.round(speechDur),
              silenceMs: Math.round(silenceDur),
              level: Number(smoothedLevel.toFixed(5)),
            });
            callbacks.onSpeechEnd();
          }
        }
        break;
    }

    raf = requestAnimationFrame(tick);
  }

  async function start(): Promise<void> {
    if (running) {
      microphoneDebug('vad', 'start_skipped_already_running');
      return;
    }
    if (startInFlight) {
      microphoneDebug('vad', 'start_joined_inflight');
      return startInFlight;
    }

    const run = async (): Promise<void> => {
      const mediaPreferences = getMediaPreferences();
      const requestedConstraints = buildAudioConstraints(mediaPreferences);
      microphoneDebug('vad', 'capture_request', {
        selectedDeviceId: mediaPreferences.microphoneDeviceId || 'system-default',
        constraints: requestedConstraints,
      });

      try {
        ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
        analyser = ctx.createAnalyser();
        analyser.fftSize = 1024;
        analyser.smoothingTimeConstant = 0.3;

        try {
          stream = await navigator.mediaDevices.getUserMedia({ audio: requestedConstraints });
        } catch (err) {
          if (!mediaPreferences.microphoneDeviceId || !isDeviceSelectionError(err)) throw err;
          microphoneDebugError('vad', 'selected_device_unavailable_fallback_default', err, {
            selectedDeviceId: mediaPreferences.microphoneDeviceId,
          });
          stream = await navigator.mediaDevices.getUserMedia({
            audio: buildAudioConstraints(mediaPreferences, { ignoreDeviceId: true }),
          });
        }

        if (!ctx || ctx.state === 'closed') {
          microphoneDebug('vad', 'capture_aborted_context_closed');
          if (stream) {
            stream.getTracks().forEach(t => t.stop());
            stream = null;
          }
          return;
        }

        const track = stream.getAudioTracks()[0];
        if (!track) throw new Error('No microphone audio track was returned.');
        const trackSettings = track.getSettings();

        microphoneDebug('vad', 'capture_opened', {
          label: track.label || 'unlabelled microphone',
          readyState: track.readyState,
          enabled: track.enabled,
          muted: track.muted,
          deviceId: trackSettings.deviceId || 'browser-default',
          sampleRate: trackSettings.sampleRate,
          channelCount: trackSettings.channelCount,
          echoCancellation: trackSettings.echoCancellation,
          noiseSuppression: trackSettings.noiseSuppression,
          autoGainControl: trackSettings.autoGainControl,
        });

        track.addEventListener('mute', () => microphoneDebug('vad', 'track_muted', {
          label: track.label || 'unlabelled microphone',
          readyState: track.readyState,
        }));
        track.addEventListener('unmute', () => microphoneDebug('vad', 'track_unmuted', {
          label: track.label || 'unlabelled microphone',
          readyState: track.readyState,
        }));
        track.addEventListener('ended', () => microphoneDebug('vad', 'track_ended', {
          label: track.label || 'unlabelled microphone',
          readyState: track.readyState,
        }));

        src = ctx.createMediaStreamSource(stream);
        src.connect(analyser);

        running = true;
        paused = false;
        state = 'idle';
        currentLevel = 0;
        smoothedLevel = 0;
        noiseFloor = cfg.noiseFloorMin;
        calibrationSamples = [];
        isCalibrating = true;

        raf = requestAnimationFrame(tick);
      } catch (err) {
        microphoneDebugError('vad', 'capture_start_failed', err, {
          selectedDeviceId: mediaPreferences.microphoneDeviceId || 'system-default',
        });
        throw err;
      }
    };

    startInFlight = run();
    try {
      await startInFlight;
    } finally {
      startInFlight = null;
    }
  }

  function stop() {
    const track = stream?.getAudioTracks()[0];
    microphoneDebug('vad', 'capture_stop', {
      running,
      label: track?.label || null,
      readyState: track?.readyState || null,
    });

    running = false;
    paused = false;

    if (raf) {
      cancelAnimationFrame(raf);
      raf = 0;
    }

    if (stream) {
      stream.getTracks().forEach(t => t.stop());
      stream = null;
    }

    if (ctx && ctx.state !== 'closed') {
      ctx.close().catch(() => {});
    }

    ctx = null;
    analyser = null;
    src = null;
    state = 'idle';
  }

  function pause() {
    if (!running || paused) return;
    paused = true;
    microphoneDebug('vad', 'detection_paused');
  }

  function resume() {
    if (!running || !paused) return;
    paused = false;
    microphoneDebug('vad', 'detection_resumed');
  }

  return {
    start,
    stop,
    pause,
    resume,
    getState: () => state,
    isRunning: () => running,
    isPaused: () => paused,
    getCurrentLevel: () => smoothedLevel,
    getNoiseFloor: () => noiseFloor,
    getThreshold: () => getAdaptiveThreshold(),
  };
}
