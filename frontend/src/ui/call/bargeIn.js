/**
 * bargeIn.ts — VAD-tap hook that detects user speech-start while
 * the assistant's TTS is playing, so the client can interrupt the
 * persona the way a person would.
 *
 * Design (§ 5.4 of docs/analysis/voice-call-streaming-design.md):
 *
 *   - Reads the EMA-smoothed mic level that useVoiceController
 *     already exposes (audioLevelRef), sampled at rAF cadence.
 *   - Fires onBargeIn when the level stays above ``threshold`` for
 *     at least ``minSustainMs``. Sustain protects against a
 *     single spike (keyboard click, cough) cutting the persona off.
 *   - Only enabled when the overlay says it should be — i.e. the
 *     TTS is actually speaking AND the session negotiated streaming.
 *     Outside that window it's a pure no-op.
 *
 * The threshold here (default 0.08) is deliberately HIGHER than the
 * baseline VAD threshold (~0.035) that useVoiceController uses for
 * end-of-user-turn silence detection. Reason: during TTS playback a
 * fraction of the persona's own audio returns into the mic on most
 * laptops; a low threshold trips on that bleed and generates
 * phantom barge-ins. 0.08 is above typical TTS bleed but well below
 * normal voiced-speech peaks.
 */
import { useEffect, useRef } from 'react';
/**
 * Mount a VAD tap that fires ``onBargeIn`` when sustained speech is
 * detected during an active TTS phase. Cleanup on unmount.
 */
export function useBargeInDetector({ audioLevelRef, enabled, onBargeIn, threshold = 0.08, minSustainMs = 80, minRefractoryMs = 400, }) {
    // Latest callback in a ref so a change in ``onBargeIn`` identity
    // doesn't tear down the whole rAF loop.
    const onBargeInRef = useRef(onBargeIn);
    useEffect(() => {
        onBargeInRef.current = onBargeIn;
    }, [onBargeIn]);
    useEffect(() => {
        if (!enabled)
            return;
        let raf = 0;
        let aboveSince = null;
        let refractoryUntil = 0;
        const tick = () => {
            const now = performance.now();
            const level = audioLevelRef.current ?? 0;
            if (level >= threshold) {
                if (aboveSince === null)
                    aboveSince = now;
                else if (now >= refractoryUntil &&
                    now - aboveSince >= minSustainMs) {
                    refractoryUntil = now + minRefractoryMs;
                    aboveSince = null;
                    try {
                        onBargeInRef.current();
                    }
                    catch {
                        /* listener errors must not crash the rAF loop */
                    }
                }
            }
            else {
                aboveSince = null;
            }
            raf = requestAnimationFrame(tick);
        };
        raf = requestAnimationFrame(tick);
        return () => {
            cancelAnimationFrame(raf);
        };
    }, [enabled, audioLevelRef, threshold, minSustainMs, minRefractoryMs]);
}
// Exported for tests — pure detector without the React hook.
export function detectBargeIn(samples, opts) {
    const events = [];
    let aboveSince = null;
    let refractoryUntil = 0;
    for (const { tMs, level } of samples) {
        if (level >= opts.threshold) {
            if (aboveSince === null)
                aboveSince = tMs;
            else if (tMs >= refractoryUntil &&
                tMs - aboveSince >= opts.minSustainMs) {
                refractoryUntil = tMs + opts.minRefractoryMs;
                aboveSince = null;
                events.push(tMs);
            }
        }
        else {
            aboveSince = null;
        }
    }
    return events;
}
