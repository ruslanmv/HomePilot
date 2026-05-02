/**
 * Aura — seeded-hue avatar primitive.
 *
 * The persona-identity chip at the centre of the call surface. Two
 * render paths:
 *
 *   1. No photo: seeded radial gradient with a soft top highlight.
 *      Hue is derived from ``seed`` via a cheap FNV-1a hash so two
 *      calls with the same persona show the same colour; different
 *      personas produce visibly distinct auras without any shared
 *      state.
 *
 *   2. ``photoUrl`` set: the <img> fills the inner disc, and the
 *      gradient becomes a low-opacity rim around it so the aura
 *      still reads as "belonging to" that persona even when
 *      dominated by the photo.
 *
 * The overlay's state-dependent decorations (CALL.state halo ring,
 * dialing pulse rings) are intentionally NOT in this primitive —
 * they couple to CallState and live in CallOverlay alongside
 * them. Aura is the stable identity chip; decorations sit on top.
 *
 * Reduced motion: the optional hue-drift animation is disabled;
 * gradient renders static.
 */
import React, { useMemo } from 'react';
import { useReducedMotion } from './useReducedMotion';
function hashHue(seed) {
    // FNV-1a, 32-bit. Cheap + deterministic; suitable for colour
    // derivation without actual crypto needs.
    let h = 2166136261;
    for (let i = 0; i < seed.length; i++) {
        h = ((h ^ seed.charCodeAt(i)) * 16777619) >>> 0;
    }
    return h % 360;
}
function moodOffset(mood) {
    switch (mood) {
        case 'warm':
            return 15;
        case 'alert':
            return -30;
        case 'calm':
        default:
            return 0;
    }
}
const Aura = ({ seed, size = 160, animated = true, mood, photoUrl, }) => {
    const reducedMotion = useReducedMotion();
    const motionOK = animated && !reducedMotion;
    const hue = useMemo(() => (hashHue(seed) + moodOffset(mood) + 360) % 360, [seed, mood]);
    const gradient = `radial-gradient(circle at 35% 30%,
    hsl(${hue} 70% 55%) 0%,
    hsl(${(hue + 40) % 360} 50% 28%) 65%,
    hsl(${(hue + 80) % 360} 40% 12%) 100%)`;
    // Keyframe name is used as a flag. The underlying @keyframes
    // block is injected once per page-load via ``ensureAuraKeyframes``
    // so a <style> tag isn't co-rendered with every Aura instance
    // (which inflated the DOM + tripped jsdom's style-parser in
    // tests). Injection is a no-op on the server + safe to call
    // repeatedly.
    React.useEffect(() => {
        if (motionOK)
            ensureAuraKeyframes();
    }, [motionOK]);
    return (<div role="img" aria-label="Persona avatar" style={{
            width: size,
            height: size,
            borderRadius: '50%',
            overflow: 'hidden',
            position: 'relative',
            background: photoUrl ? 'transparent' : gradient,
            boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.06), 0 0 0 1px rgba(255,255,255,0.04)',
            animationName: motionOK ? 'hp-aura-hue-drift' : undefined,
            animationDuration: motionOK ? '5s' : undefined,
            animationIterationCount: motionOK ? 'infinite' : undefined,
            animationTimingFunction: motionOK ? 'ease-in-out' : undefined,
        }}>
      {photoUrl ? (<img src={photoUrl} alt="" style={{
                width: '100%',
                height: '100%',
                objectFit: 'cover',
                display: 'block',
            }}/>) : (
        // Soft top highlight — gives the gradient fallback a
        // spherical feel without a full 3D light model.
        <div aria-hidden="true" style={{
                position: 'absolute',
                inset: 0,
                background: 'radial-gradient(circle at 40% 25%, rgba(255,255,255,0.35) 0%, transparent 45%)',
            }}/>)}
    </div>);
};
// One-shot keyframe injector. Guards on document presence (SSR)
// and on an already-injected flag so re-renders don't duplicate
// the style block.
function ensureAuraKeyframes() {
    if (typeof document === 'undefined')
        return;
    const flag = '__hp_aura_keyframes__';
    const w = window;
    if (w[flag])
        return;
    w[flag] = true;
    const style = document.createElement('style');
    style.setAttribute('data-hp-aura', '1');
    style.textContent = `
    @keyframes hp-aura-hue-drift {
      0%, 100% { filter: hue-rotate(0deg); }
      50%      { filter: hue-rotate(6deg); }
    }
  `;
    document.head.appendChild(style);
}
export default Aura;
