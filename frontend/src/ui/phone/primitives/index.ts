/**
 * Barrel — single import path for everything under ``phone/primitives/``.
 *
 * Callers import from ``'../phone/primitives'`` rather than picking
 * individual files so the paths don't need touching when a
 * primitive gets renamed or relocated inside the folder.
 *
 * Current contents (grows as the remaining batches land —
 * Aura, AmbientAura, Waveform):
 *
 *   useReducedMotion   OS motion-preference subscription
 *   useFocusTrap       keyboard-focus containment for dialogs
 *   ControlBtn         circular action button (mic, end, etc.)
 */

export { useReducedMotion } from './useReducedMotion'
export { useFocusTrap } from './useFocusTrap'
export { default as ControlBtn } from './ControlBtn'
export type {
  ControlBtnProps,
  ControlBtnSize,
  ControlBtnTone,
} from './ControlBtn'
