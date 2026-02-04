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

export type VADConfig = {
  // Detection thresholds
  baseThreshold: number;       // Base threshold above noise floor (0.02-0.05)
  hysteresisHigh: number;      // Multiplier for speech start (1.5-2.0)
  hysteresisLow: number;       // Multiplier for speech end (0.8-1.0)

  // Timing
  minSpeechMs: number;         // Min speech duration to trigger (150-300ms)
  silenceMs: number;           // Silence before speech end (600-1000ms)

  // Smoothing
  emaAlpha: number;            // EMA smoothing factor (0.1-0.3)
  noiseFloorDecay: number;     // Noise floor adaptation rate (0.995-0.999)
  noiseFloorMin: number;       // Minimum noise floor (0.001-0.01)
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

  // Audio context and nodes
  let ctx: AudioContext | null = null;
  let analyser: AnalyserNode | null = null;
  let src: MediaStreamAudioSourceNode | null = null;
  let stream: MediaStream | null = null;
  let raf = 0;

  // State tracking
  let state: VADState = 'idle';
  let running = false;
  let paused = false;

  // Level tracking with EMA smoothing
  let currentLevel = 0;
  let smoothedLevel = 0;
  let noiseFloor = cfg.noiseFloorMin;

  // Timing
  let speechStartAt = 0;
  let lastAboveAt = 0;
  let silenceStartAt = 0;

  // Calibration
  let calibrationSamples: number[] = [];
  let isCalibrating = true;
  const CALIBRATION_SAMPLES = 30; // ~500ms at 60fps

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
    // During calibration, collect samples
    if (isCalibrating) {
      calibrationSamples.push(level);
      if (calibrationSamples.length >= CALIBRATION_SAMPLES) {
        // Set initial noise floor as median of calibration samples
        calibrationSamples.sort((a, b) => a - b);
        const median = calibrationSamples[Math.floor(calibrationSamples.length / 2)];
        noiseFloor = Math.max(median * 1.2, cfg.noiseFloorMin);
        isCalibrating = false;
        console.log('[VAD] Calibration complete, noise floor:', noiseFloor.toFixed(4));
      }
      return;
    }

    // Adaptive noise floor: slowly decay toward current level when quiet
    if (level < noiseFloor * 2) {
      noiseFloor = Math.max(
        cfg.noiseFloorMin,
        noiseFloor * cfg.noiseFloorDecay + level * (1 - cfg.noiseFloorDecay)
      );
    }
  }

  function getAdaptiveThreshold(): number {
    // Threshold is noise floor + base threshold, with hysteresis
    const base = noiseFloor + cfg.baseThreshold;
    if (state === 'idle') {
      return base * cfg.hysteresisHigh; // Higher threshold to start speaking
    }
    return base * cfg.hysteresisLow; // Lower threshold to continue speaking
  }

  function tick() {
    if (!analyser || !running) return;

    // Skip processing if paused (but keep RAF running)
    if (paused) {
      raf = requestAnimationFrame(tick);
      return;
    }

    const data = new Uint8Array(analyser.frequencyBinCount);
    analyser.getByteTimeDomainData(data);

    // Calculate RMS level
    currentLevel = calculateRMS(data);

    // Apply EMA smoothing
    smoothedLevel = cfg.emaAlpha * currentLevel + (1 - cfg.emaAlpha) * smoothedLevel;

    // Update noise floor estimation
    updateNoiseFloor(smoothedLevel);

    const threshold = getAdaptiveThreshold();
    const now = performance.now();

    // Report level changes for visualization
    callbacks.onLevelChange?.(smoothedLevel, threshold, noiseFloor);

    // Skip detection during calibration
    if (isCalibrating) {
      raf = requestAnimationFrame(tick);
      return;
    }

    // State machine
    switch (state) {
      case 'idle':
        if (smoothedLevel >= threshold) {
          lastAboveAt = now;
          speechStartAt = now;
          setState('speech');
          callbacks.onSpeechStart();
        }
        break;

      case 'speech':
        if (smoothedLevel >= threshold * cfg.hysteresisLow) {
          lastAboveAt = now;
        } else {
          // Check if we've been silent long enough
          const silenceDur = now - lastAboveAt;
          const speechDur = now - speechStartAt;

          if (speechDur >= cfg.minSpeechMs && silenceDur >= cfg.silenceMs) {
            setState('idle');
            callbacks.onSpeechEnd();
          } else if (silenceDur > 100) {
            // Brief silence, might be between words
            silenceStartAt = lastAboveAt;
            setState('silence_pending');
          }
        }
        break;

      case 'silence_pending':
        if (smoothedLevel >= threshold * cfg.hysteresisLow) {
          // Speech resumed
          lastAboveAt = now;
          setState('speech');
        } else {
          const silenceDur = now - lastAboveAt;
          const speechDur = lastAboveAt - speechStartAt;

          if (speechDur >= cfg.minSpeechMs && silenceDur >= cfg.silenceMs) {
            setState('idle');
            callbacks.onSpeechEnd();
          }
        }
        break;
    }

    raf = requestAnimationFrame(tick);
  }

  async function start(): Promise<void> {
    if (running) return;

    try {
      // Create audio context
      ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
      analyser = ctx.createAnalyser();
      analyser.fftSize = 1024;
      analyser.smoothingTimeConstant = 0.3;

      // Request microphone with echo cancellation, noise suppression, and auto gain
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        }
      });

      // Guard: If stop() was called during async getUserMedia, abort gracefully
      // This handles React StrictMode double-mount race condition
      if (!ctx || ctx.state === 'closed') {
        console.log('[VAD] Context closed during startup, aborting');
        if (stream) {
          stream.getTracks().forEach(t => t.stop());
        }
        return;
      }

      src = ctx.createMediaStreamSource(stream);
      src.connect(analyser);

      // Reset state
      running = true;
      paused = false;
      state = 'idle';
      currentLevel = 0;
      smoothedLevel = 0;
      noiseFloor = cfg.noiseFloorMin;
      calibrationSamples = [];
      isCalibrating = true;

      console.log('[VAD] Started with AEC/NS/AGC enabled');

      // Start detection loop
      raf = requestAnimationFrame(tick);
    } catch (err) {
      console.error('[VAD] Failed to start:', err);
      throw err;
    }
  }

  function stop() {
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

    console.log('[VAD] Stopped');
  }

  function pause() {
    if (!running || paused) return;
    paused = true;
    console.log('[VAD] Paused');
  }

  function resume() {
    if (!running || !paused) return;
    paused = false;
    console.log('[VAD] Resumed');
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

