/**
 * Props contract for the motion-graphic compositions.
 *
 * This mirrors backend/app/studio/motion_graphics.py :: MotionGraphicSpec -
 * the backend renders a deterministic PNG still from the same data; these
 * compositions render the animated version. Keep the two in sync.
 */

export type MotionSceneKind = "diagram" | "proof" | "quote" | "cta";

/** StyleKit palette subset used by every composition (ruslanmv-essays defaults). */
export interface MotionPalette {
  background: string;
  textPrimary: string;
  textSecondary: string;
  accentStart: string;
  accentMid: string;
  accentEnd: string;
}

export const RUSLANMV_ESSAYS_PALETTE: MotionPalette = {
  background: "#0a0a0a",
  textPrimary: "#ffffff",
  textSecondary: "#94a3b8",
  accentStart: "#00d4ff",
  accentMid: "#0f62fe",
  accentEnd: "#8a3ffc",
};

export interface MotionGraphicProps {
  kind: MotionSceneKind;
  /** Section title shown in the shared header. */
  title: string;
  /** The scene's narration - the essay's own words, verbatim. */
  narration: string;
  /** Links for the CTA card (EssaySource.source_links). */
  links?: string[];
  /**
   * Safe-content margin as a fraction of each canvas dimension
   * (CanvasSpec.safe_margin_pct). Every composition lays out inside this
   * box so the same scene reflows at 16:9, 9:16, and 1:1.
   */
  safeMarginPct?: number;
  palette?: MotionPalette;
}

export const FONT_STACK_HEADING =
  '"IBM Plex Sans", "Helvetica Neue", Arial, sans-serif';
export const FONT_STACK_MONO =
  '"IBM Plex Mono", "SFMono-Regular", Menlo, monospace';

/** Split narration into sentences (same rule as the backend segmenter). */
export function sentences(text: string, limit: number): string[] {
  return text
    .split(/(?<=[.!?])\s+/)
    .map((s) => s.trim())
    .filter(Boolean)
    .slice(0, limit);
}

/** Exact figures ("42%", "3x", "128") pulled from narration for ProofScene. */
export function figures(text: string, limit: number): string[] {
  const m = text.match(/\d+(?:\.\d+)?\s*%|\b\d+(?:\.\d+)?x\b|\b\d+(?:\.\d+)?\b/g);
  return (m ?? []).slice(0, limit);
}
