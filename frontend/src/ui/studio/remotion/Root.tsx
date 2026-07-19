import React from "react";
import { Composition } from "remotion";
import { CTAScene } from "./CTAScene";
import { DiagramScene } from "./DiagramScene";
import { EssayAssembly, EssayAssemblyProps } from "./EssayAssembly";
import { ProofScene } from "./ProofScene";
import { QuoteScene } from "./QuoteScene";
import { MotionGraphicProps } from "./types";

const FPS = 30;
const DEFAULT_DURATION_SEC = 5;

/**
 * One master composition per archetype, registered at the three target
 * canvases. The composition code is identical across canvases - layout is
 * safe-margin-relative (CanvasSpec.safe_margin_pct), which is what makes
 * the multi-aspect reflow close to free.
 *
 * Render one scene:
 *   npx remotion render Diagram-youtube_16_9 out/scene.mp4 \
 *     --props='{"kind":"diagram","title":"...","narration":"..."}'
 */
// Composition IDs may not contain underscores (Remotion allows a-z, 0-9,
// and hyphens only), so canvas ids here are the hyphenated form of the
// backend PlatformPreset values.
const CANVASES = [
  { id: "youtube-16-9", width: 1920, height: 1080, safeMarginPct: 0.05 },
  { id: "shorts-9-16", width: 1080, height: 1920, safeMarginPct: 0.06 },
  { id: "social-1-1", width: 1080, height: 1080, safeMarginPct: 0.06 },
] as const;

const ARCHETYPES = [
  { name: "Diagram", component: DiagramScene, kind: "diagram" },
  { name: "Proof", component: ProofScene, kind: "proof" },
  { name: "Quote", component: QuoteScene, kind: "quote" },
  { name: "CTA", component: CTAScene, kind: "cta" },
] as const;

const DEFAULT_ASSEMBLY_PROPS: EssayAssemblyProps = {
  scenes: [
    {
      kind: "quote",
      rendererKind: "motion_graphic",
      title: "Essay Assembly",
      narration: "Pass the promoted project's scenes as props to render the full timeline.",
      durationSec: 5,
    },
  ],
  captions: [],
};

export const RemotionRoot: React.FC = () => {
  return (
    <>
      {/* Master timeline: scenes + voiceover + always-on captions.
          Duration follows the scene list via calculateMetadata. */}
      {CANVASES.map((canvas) => (
        <Composition
          key={`Assembly-${canvas.id}`}
          id={`Assembly-${canvas.id}`}
          component={EssayAssembly as React.FC<Record<string, unknown> & EssayAssemblyProps>}
          durationInFrames={FPS * DEFAULT_DURATION_SEC}
          fps={FPS}
          width={canvas.width}
          height={canvas.height}
          defaultProps={{ ...DEFAULT_ASSEMBLY_PROPS, safeMarginPct: canvas.safeMarginPct }}
          calculateMetadata={({ props }) => ({
            durationInFrames: Math.max(
              FPS,
              Math.round(
                (props.scenes ?? []).reduce(
                  (sum: number, s: { durationSec: number }) => sum + (s.durationSec || 0),
                  0
                ) * FPS
              )
            ),
          })}
        />
      ))}
      {ARCHETYPES.map(({ name, component, kind }) =>
        CANVASES.map((canvas) => (
          <Composition
            key={`${name}-${canvas.id}`}
            id={`${name}-${canvas.id}`}
            component={component as React.FC<Record<string, unknown> & MotionGraphicProps>}
            durationInFrames={FPS * DEFAULT_DURATION_SEC}
            fps={FPS}
            width={canvas.width}
            height={canvas.height}
            defaultProps={{
              kind,
              title: "Section Title",
              narration:
                "The essay's own sentences render here, verbatim. Nothing is sampled between the text and the pixels.",
              links: ["ruslanmv.com"],
              safeMarginPct: canvas.safeMarginPct,
            }}
          />
        ))
      )}
    </>
  );
};
