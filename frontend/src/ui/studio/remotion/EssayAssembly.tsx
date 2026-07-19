import React from "react";
import {
  AbsoluteFill,
  Audio,
  Img,
  OffthreadVideo,
  Series,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { CTAScene } from "./CTAScene";
import { DiagramScene } from "./DiagramScene";
import { ProofScene } from "./ProofScene";
import { QuoteScene } from "./QuoteScene";
import {
  FONT_STACK_HEADING,
  MotionPalette,
  RUSLANMV_ESSAYS_PALETTE,
} from "./types";

/**
 * EssayAssembly - the master timeline (Batch 4): one composition, three
 * canvases. Diffusion scenes drop in as their rendered image/video
 * (regenerated natively per aspect, never cropped - see the aspect_plan
 * in promote-to-project); motion-graphic scenes nest the Batch 1
 * archetype compositions and reflow via safeMarginPct. The voiceover
 * audio track and the always-on caption track ride on top.
 */

export interface AssemblyScene {
  kind: "hero" | "diagram" | "quote" | "proof" | "cta" | "transition";
  rendererKind: "diffusion" | "motion_graphic" | null;
  title: string;
  narration: string;
  durationSec: number;
  imageUrl?: string;
  videoUrl?: string;
  links?: string[];
}

export interface CaptionCue {
  startSec: number;
  endSec: number;
  text: string;
}

export interface EssayAssemblyProps {
  scenes: AssemblyScene[];
  audioUrl?: string;
  captions?: CaptionCue[];
  safeMarginPct?: number;
  palette?: MotionPalette;
}

const MOTION_COMPONENTS = {
  diagram: DiagramScene,
  proof: ProofScene,
  quote: QuoteScene,
  cta: CTAScene,
} as const;

const CaptionTrack: React.FC<{
  captions: CaptionCue[];
  palette: MotionPalette;
  safeMarginPct: number;
}> = ({ captions, palette, safeMarginPct }) => {
  const frame = useCurrentFrame();
  const { fps, height, width } = useVideoConfig();
  const t = frame / fps;
  const active = captions.find((c) => t >= c.startSec && t < c.endSec);
  if (!active) return null;
  const scale = height / 1080;
  return (
    <div
      style={{
        position: "absolute",
        left: width * safeMarginPct,
        right: width * safeMarginPct,
        bottom: height * safeMarginPct,
        display: "flex",
        justifyContent: "center",
      }}
    >
      <span
        style={{
          fontFamily: FONT_STACK_HEADING,
          fontSize: 42 * scale,
          fontWeight: 600,
          lineHeight: 1.3,
          color: palette.textPrimary,
          background: "rgba(0, 0, 0, 0.72)",
          padding: `${10 * scale}px ${22 * scale}px`,
          borderRadius: 10 * scale,
          textAlign: "center",
        }}
      >
        {active.text}
      </span>
    </div>
  );
};

const DiffusionScene: React.FC<{ scene: AssemblyScene }> = ({ scene }) => (
  <AbsoluteFill style={{ backgroundColor: "#000" }}>
    {scene.videoUrl ? (
      <OffthreadVideo
        src={scene.videoUrl}
        style={{ width: "100%", height: "100%", objectFit: "cover" }}
        muted
      />
    ) : scene.imageUrl ? (
      <Img
        src={scene.imageUrl}
        style={{ width: "100%", height: "100%", objectFit: "cover" }}
      />
    ) : null}
  </AbsoluteFill>
);

export const EssayAssembly: React.FC<EssayAssemblyProps> = ({
  scenes,
  audioUrl,
  captions = [],
  safeMarginPct = 0.05,
  palette = RUSLANMV_ESSAYS_PALETTE,
}) => {
  const { fps } = useVideoConfig();

  return (
    <AbsoluteFill style={{ backgroundColor: palette.background }}>
      <Series>
        {scenes.map((scene, i) => {
          const frames = Math.max(1, Math.round(scene.durationSec * fps));
          const motionKind =
            scene.kind in MOTION_COMPONENTS
              ? (scene.kind as keyof typeof MOTION_COMPONENTS)
              : "quote";
          const Motion = MOTION_COMPONENTS[motionKind];
          return (
            <Series.Sequence key={i} durationInFrames={frames}>
              {scene.rendererKind === "motion_graphic" ? (
                <Motion
                  kind={motionKind}
                  title={scene.title}
                  narration={scene.narration}
                  links={scene.links}
                  safeMarginPct={safeMarginPct}
                  palette={palette}
                />
              ) : (
                <DiffusionScene scene={scene} />
              )}
            </Series.Sequence>
          );
        })}
      </Series>
      {audioUrl ? <Audio src={audioUrl} /> : null}
      {/* Captions always on - the ruslanmv-essays StyleKit's motion rule */}
      <CaptionTrack captions={captions} palette={palette} safeMarginPct={safeMarginPct} />
    </AbsoluteFill>
  );
};
