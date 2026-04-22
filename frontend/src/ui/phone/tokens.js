/**
 * phone/tokens.ts — design tokens for the call surface.
 *
 * Ported from ``Phone Call UI.html``'s CALL constant. Single source
 * of truth for colours + fonts used by PostCallCard, CallScreen,
 * Aura, and every other component under ``ui/phone/``.
 *
 * Values stay in JS strings so they can also be consumed by
 * inline-style props (gradients, box-shadows) where Tailwind arbitrary
 * values would be verbose. Tailwind colour tokens live in
 * ``tailwind.config.js`` — extend them from this file.
 */
export const CALL = {
    // Typography stack — UI + editorial. Both fall back cleanly to
    // system families so offline / FOUT states stay legible.
    font: '"Geist", "Inter", -apple-system, system-ui, sans-serif',
    display: '"Instrument Serif", "Cormorant Garamond", Georgia, serif',
    // Surfaces — two-step dark gradient for the main call background
    // and a set of soft white alphas for on-surface primitives.
    bg0: '#08060c',
    bg1: '#0e0a16',
    ink: '#f5ecff',
    dim: 'rgba(245,236,255,0.55)',
    faint: 'rgba(245,236,255,0.28)',
    line: 'rgba(245,236,255,0.08)',
    // Primary accent — the brand rose. Uses oklch() so the hue carries
    // evenly into the softened variant (roseSoft) without the
    // "muddy middle" you get with HSL or RGB interpolation.
    rose: 'oklch(0.70 0.19 340)',
    roseSoft: 'oklch(0.62 0.16 340 / 0.5)',
    // Secondary accents.
    amber: 'oklch(0.80 0.15 55)', // muted / warning (used by muted state)
    danger: 'oklch(0.64 0.22 25)', // end-call red + missed-call tint
    good: 'oklch(0.72 0.15 155)', // accept green
};
/** Post-call card layout dimensions. Kept as a separate object so
 *  the component file doesn't accumulate magic numbers. */
export const POST_CALL = {
    cardWidth: 320,
    cardRadius: 16,
    rowPadding: '12px 14px',
    ctaHeight: 32,
    ctaRadius: 10,
    avatarSize: 30,
};
/** Class helper so components using the tokens can still pass the
 *  right ``font-family`` inline without importing the whole record. */
export const callFontFamily = {
    ui: CALL.font,
    display: CALL.display,
};
