/**
 * AmbientAura — page-scale blurred glow backdrop.
 *
 * Sits behind a call surface (CallScreen fullscreen, or the modal
 * centred in CallOverlay) and adds a soft coloured wash matched
 * to the persona. Complements ``Aura`` (identity chip at centre)
 * by echoing the same hue at page scale, so the screen "belongs
 * to" that persona without a single glance at the avatar.
 *
 * Render model: two radial-gradient layers with different hue +
 * offset, both blurred 80 px. The slight hue separation gives
 * depth without needing a full 3D lighting model; the double-
 * gradient is cheap because the browser composites both on a
 * single GPU layer once the parent has ``transform: translateZ(0)``
 * (handled by the fixed-position outer div implicitly).
 *
 * Animation: each layer's origin drifts independently over 25 s so
 * the glow breathes slowly. Reduced-motion → origins are static.
 *
 * Positioning: ``position: fixed; inset: 0; pointer-events: none;
 * z-index: -1``. It sits BEHIND everything, never catches clicks,
 * and is safe to render multiple times (last mount wins, earlier
 * instances are overlaid but invisible because they match).
 */
import React from 'react';
import { useReducedMotion } from './useReducedMotion';
const AmbientAura = ({ hue, intensity = 0.55, animated = true, }) => {
    const reducedMotion = useReducedMotion();
    const motionOK = animated && !reducedMotion;
    const h = ((hue % 360) + 360) % 360;
    const h2 = (h + 40) % 360;
    // One-shot keyframe injection — same pattern as Aura. Called
    // inline during render (with its own document guard) rather
    // than in a useEffect, so tests that render once see the
    // injection without having to flush effects.
    if (motionOK)
        ensureAmbientAuraKeyframes();
    const baseLayer = {
        position: 'absolute',
        inset: 0,
        filter: 'blur(80px)',
        pointerEvents: 'none',
        willChange: motionOK ? 'background-position' : undefined,
    };
    return (<div aria-hidden="true" style={{
            position: 'fixed',
            inset: 0,
            pointerEvents: 'none',
            zIndex: -1,
            overflow: 'hidden',
        }}>
      {/* Primary layer — driver hue, drifts along one path. */}
      <div style={{
            ...baseLayer,
            background: `radial-gradient(60% 50% at 30% 40%,
              oklch(0.45 0.22 ${h} / ${intensity}) 0%,
              transparent 60%)`,
            animationName: motionOK ? 'hp-ambient-drift-a' : undefined,
            animationDuration: motionOK ? '25s' : undefined,
            animationIterationCount: motionOK ? 'infinite' : undefined,
            animationTimingFunction: motionOK ? 'ease-in-out' : undefined,
        }}/>
      {/* Secondary layer — hue+40, 0.4× intensity, independent
            drift so the two never line up in the same sweep. */}
      <div style={{
            ...baseLayer,
            background: `radial-gradient(55% 45% at 70% 60%,
              oklch(0.45 0.22 ${h2} / ${intensity * 0.4}) 0%,
              transparent 60%)`,
            animationName: motionOK ? 'hp-ambient-drift-b' : undefined,
            animationDuration: motionOK ? '25s' : undefined,
            animationDelay: motionOK ? '-12s' : undefined,
            animationIterationCount: motionOK ? 'infinite' : undefined,
            animationTimingFunction: motionOK ? 'ease-in-out' : undefined,
        }}/>
    </div>);
};
function ensureAmbientAuraKeyframes() {
    if (typeof document === 'undefined')
        return;
    const flag = '__hp_ambient_aura_keyframes__';
    const w = window;
    if (w[flag])
        return;
    w[flag] = true;
    const style = document.createElement('style');
    style.setAttribute('data-hp-ambient-aura', '1');
    style.textContent = `
    @keyframes hp-ambient-drift-a {
      0%, 100% { transform: translate3d(0, 0, 0); }
      50%      { transform: translate3d(4%, 3%, 0); }
    }
    @keyframes hp-ambient-drift-b {
      0%, 100% { transform: translate3d(0, 0, 0); }
      50%      { transform: translate3d(-3%, 4%, 0); }
    }
  `;
    document.head.appendChild(style);
}
export default AmbientAura;
