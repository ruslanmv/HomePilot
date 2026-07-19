import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { SceneChrome } from "./SceneChrome";
import {
  FONT_STACK_HEADING,
  MotionGraphicProps,
  RUSLANMV_ESSAYS_PALETTE,
  figures,
} from "./types";

/**
 * ProofScene - the exact figures from the narration ("42%", "3x") pop in
 * large, then the full sentence settles underneath. The numbers are pulled
 * verbatim from the text, never re-typed.
 */
export const ProofScene: React.FC<MotionGraphicProps> = (props) => {
  const palette = props.palette ?? RUSLANMV_ESSAYS_PALETTE;
  const frame = useCurrentFrame();
  const { fps, height } = useVideoConfig();
  const scale = height / 1080;

  const stats = figures(props.narration, 3);
  const bodyOpacity = interpolate(frame, [fps * 0.8, fps * 1.6], [0, 1], {
    extrapolateRight: "clamp",
  });

  return (
    <SceneChrome title={props.title} safeMarginPct={props.safeMarginPct} palette={palette}>
      <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center" }}>
        <div style={{ display: "flex", gap: 90 * scale, flexWrap: "wrap" }}>
          {stats.map((stat, i) => {
            const pop = spring({
              frame: frame - i * fps * 0.3,
              fps,
              config: { damping: 12, mass: 0.6 },
            });
            return (
              <div
                key={i}
                style={{
                  fontFamily: FONT_STACK_HEADING,
                  fontWeight: 700,
                  fontSize: 150 * scale,
                  color: palette.accentStart,
                  transform: `scale(${pop})`,
                  transformOrigin: "left bottom",
                }}
              >
                {stat}
              </div>
            );
          })}
        </div>
        <p
          style={{
            fontFamily: FONT_STACK_HEADING,
            fontSize: 44 * scale,
            lineHeight: 1.4,
            color: palette.textSecondary,
            maxWidth: "90%",
            opacity: bodyOpacity,
            marginTop: 40 * scale,
          }}
        >
          {props.narration}
        </p>
      </div>
    </SceneChrome>
  );
};
