export type VADConfig = {
  threshold: number;        // 0..1
  minSpeechMs: number;      // e.g. 250
  silenceMs: number;        // e.g. 900
};

export function createVAD(onSpeechStart: () => void, onSpeechEnd: () => void, cfg: VADConfig) {
  let ctx: AudioContext | null = null;
  let analyser: AnalyserNode | null = null;
  let src: MediaStreamAudioSourceNode | null = null;
  let stream: MediaStream | null = null;
  let raf = 0;

  let speaking = false;
  let speechStartAt = 0;
  let lastAboveAt = 0;

  async function start() {
    ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
    analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;

    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    src = ctx.createMediaStreamSource(stream);
    src.connect(analyser);

    const data = new Uint8Array(analyser.frequencyBinCount);

    const tick = () => {
      if (!analyser) return;
      analyser.getByteTimeDomainData(data);

      // RMS 0..1
      let sum = 0;
      for (let i = 0; i < data.length; i++) {
        const v = (data[i] - 128) / 128;
        sum += v * v;
      }
      const rms = Math.sqrt(sum / data.length);

      const now = performance.now();
      if (rms >= cfg.threshold) {
        lastAboveAt = now;
        if (!speaking) {
          speaking = true;
          speechStartAt = now;
          onSpeechStart();
        }
      } else {
        if (speaking) {
          const speechDur = now - speechStartAt;
          const silenceDur = now - lastAboveAt;
          if (speechDur >= cfg.minSpeechMs && silenceDur >= cfg.silenceMs) {
            speaking = false;
            onSpeechEnd();
          }
        }
      }

      raf = requestAnimationFrame(tick);
    };

    raf = requestAnimationFrame(tick);
  }

  async function stop() {
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
    if (stream) stream.getTracks().forEach((t) => t.stop());
    stream = null;
    if (ctx) await ctx.close();
    ctx = null;
    analyser = null;
    src = null;
    speaking = false;
  }

  return { start, stop };
}
