/**
 * HomePilot's design system: one visual language for every page. See ./README.md for the
 * tokens, the components and how each page moves onto them.
 */
export { Button, IconButton, buttonClass, type ButtonProps, type ButtonSize, type ButtonVariant } from './Button'
export {
  CARD,
  Card,
  EmptyState,
  IconTile,
  InlineAlert,
  Page,
  PageHeader,
  SkeletonRows,
  StatTile,
  StatusBadge,
  Switch,
  TONE_CLASSES,
  type AlertTone,
  type Tone,
} from './Surface'
export { SheetFooter, SheetHeader } from './Sheet'

/** Shared form-field classes, for inputs and selects that are not yet a component. */
export const FIELD =
  'w-full h-11 rounded-xl border border-white/10 bg-white/[0.03] px-4 text-sm text-white placeholder-white/30 ' +
  'outline-none transition-colors focus:border-violet-400/70 focus:ring-2 focus:ring-hp-accent/25 [color-scheme:dark]'

/** The small uppercase label above a group of fields. */
export const FIELD_LABEL = 'text-[11px] font-semibold uppercase tracking-[0.12em] text-white/45'
