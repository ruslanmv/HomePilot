/**
 * Waveform — rAF-driven audio-level bars for the call surface.
 *
 * Extracted from the inline CallWaveform previously living in
 * CallOverlay.tsx. Self-contained: reads tokens only, takes a
 * simple ``mode`` enum rather than the overlay's richer CallState,
 * and reads a shared ``intensityRef`` (0..1) each frame so React
 * stays out of the per-frame path.
 *
 * Mode → colour mapping (token-driven):
 *
 *   listening  CALL.rose      primary accent; mic-open in a call
 *   speaking   CALL.rose      same; user reads bar colour as "live"
 *                              regardless of direction
 *   muted      CALL.amber     damped amplitude + warm warning tone
 *   idle       CALL.faint     flat-ish line when nothing is happening
 *
 * The colour split is intentional — speaking vs listening share the
 * accent so the user doesn't have to track two "active" colours
 * during a call. Muted is visually distinct so a glance tells the
 * user the mic is off.
 *
 * Reduced motion: the rAF loop never starts; bars render at an
 * initial level-agnostic height. The colour cue is preserved so the
 * user still sees the mode change.
 */
import React, { useEffect, useMemo, useRef } from 'react';
import { CALL } from '../tokens';
import { useReducedMotion } from './useReducedMotion';
function modeColor(mode) {
    switch (mode) {
        case 'speaking':
        case 'listening':
            return CALL.rose;
        case 'muted':
            return CALL.amber;
        case 'idle':
        default:
            return CALL.faint;
    }
}
const Waveform = ({ mode, intensityRef, bars = 26, height = 24, seed = 'homepilot', ariaHidden = true, }) => {
    const color = modeColor(mode);
    const containerRef = useRef(null);
    const reducedMotion = useReducedMotion();
    // ``active`` determines whether the rAF loop drives amplitude;
    // muted bars damp to near-flat; idle sits at the same damped
    // baseline but with a dimmer colour.
    const active = mode === 'listening' || mode === 'speaking';
    // Per-bar seed — stable across renders. Each bar gets its own
    // amplitude ceiling, phase offset, and natural oscillation rate
    // so the row never moves in lockstep.
    const barSeeds = useMemo(() => Array.from({ length: bars }, (_, i) => {
        const amp = 0.45 +
            Math.abs(Math.sin(i * 0.7 + seed.length) * 0.3 +
                Math.sin(i * 1.3 + seed.charCodeAt(0)) * 0.22);
        const phase = (((i * 83) % 1000) / 1000) * Math.PI * 2;
        const freq = 0.7 + ((i * 37) % 100) / 100;
        return { amp, phase, freq };
    }), [bars, seed]);
    useEffect(() => {
        // Reduced motion → bars render once at their initial opacity +
        // scale. No rAF loop starts, no per-frame DOM writes.
        if (reducedMotion)
            return;
        if (!containerRef.current)
            return;
        let raf = 0;
        const start = performance.now();
        const tick = () => {
            const t = (performance.now() - start) / 1000;
            const lvl = active ? intensityRef?.current ?? 0.18 : 0.04;
            const children = containerRef.current?.children;
            if (children) {
                for (let i = 0; i < children.length; i++) {
                    const s = barSeeds[i];
                    // Per-bar 0..1 oscillator layered over the global intensity.
                    const wave = 0.55 + 0.45 * Math.sin(t * s.freq * 4 + s.phase);
                    // Floor at 0.06 so idle bars are still a visible line,
                    // ceiling at 1 so loud bursts can't clip out of the card.
                    const scale = Math.max(0.06, Math.min(1, 0.08 + lvl * s.amp * wave * 1.4));
                    const el = children[i];
                    el.style.transform = `scaleY(${scale})`;
                    el.style.opacity = String(Math.min(1, 0.45 + lvl * 0.55));
                }
            }
            raf = requestAnimationFrame(tick);
        };
        raf = requestAnimationFrame(tick);
        return () => cancelAnimationFrame(raf);
    }, [barSeeds, active, intensityRef, reducedMotion]);
    return (<div ref={containerRef} aria-hidden={ariaHidden ? 'true' : undefined} style={{
            display: 'flex',
            gap: 3,
            alignItems: 'center',
            justifyContent: 'center',
            height,
        }}>
      {barSeeds.map((_, i) => (<div key={i} style={{
                width: 3,
                height: '100%',
                background: color,
                borderRadius: 2,
                transformOrigin: 'center',
                willChange: 'transform, opacity',
                opacity: 0.45,
            }}/>))}
    </div>);
};
export default Waveform;
