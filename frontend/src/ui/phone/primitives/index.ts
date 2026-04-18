/**
 * Barrel — single import path for everything under ``phone/primitives/``.
 *
 * Callers import from ``'../phone/primitives'`` rather than picking
 * individual files so the paths don't need touching when a
 * primitive gets renamed or relocated inside the folder.
 *
 * Current contents:
 *
 *   useReducedMotion   OS motion-preference subscription
 *   useFocusTrap       keyboard-focus containment for dialogs
 *   ControlBtn         circular action button (mic, end, etc.)
 *   Waveform           rAF-driven audio-level bars
 *   Aura               seeded-hue persona identity chip
 *   AmbientAura        page-scale coloured backdrop glow
 */

export { useReducedMotion } from './useReducedMotion'
export { useFocusTrap } from './useFocusTrap'
export { default as ControlBtn } from './ControlBtn'
export type {
  ControlBtnProps,
  ControlBtnSize,
  ControlBtnTone,
} from './ControlBtn'
export { default as Waveform } from './Waveform'
export type { WaveformProps, WaveformMode } from './Waveform'
export { default as Aura } from './Aura'
export type { AuraProps, AuraMood } from './Aura'
export { default as AmbientAura } from './AmbientAura'
export type { AmbientAuraProps } from './AmbientAura'
