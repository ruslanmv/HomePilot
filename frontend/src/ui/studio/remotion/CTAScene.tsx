import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { SceneChrome } from "./SceneChrome";
import {
  FONT_STACK_HEADING,
  FONT_STACK_MONO,
  MotionGraphicProps,
  RUSLANMV_ESSAYS_PALETTE,
} from "./types";

/**
 * CTAScene - closing card: the final narration beat plus the essay's own
 * source links (EssaySource.source_links) sliding in one per beat.
 */
export const CTAScene: React.FC<MotionGraphicProps> = (props) => {
  const palette = props.palette ?? RUSLANMV_ESSAYS_PALETTE;
  const frame = useCurrentFrame();
  const { fps, height } = useVideoConfig();
  const scale = height / 1080;

  const links = (props.links ?? []).slice(0, 4);
  const bodyOpacity = interpolate(frame, [0, fps * 0.8], [0, 1], {
    extrapolateRight: "clamp",
  });

  return (
    <SceneChrome title={props.title} safeMarginPct={props.safeMarginPct} palette={palette}>
      <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center" }}>
        <p
          style={{
            fontFamily: FONT_STACK_HEADING,
            fontSize: 48 * scale,
            lineHeight: 1.4,
            color: palette.textPrimary,
            maxWidth: "90%",
            opacity: bodyOpacity,
            margin: 0,
          }}
        >
          {props.narration}
        </p>
        <div style={{ marginTop: 60 * scale, display: "flex", flexDirection: "column", gap: 22 * scale }}>
          {links.map((link, i) => {
            const slide = spring({
              frame: frame - fps * (0.8 + i * 0.35),
              fps,
              config: { damping: 200 },
            });
            return (
              <div
                key={i}
                style={{
                  fontFamily: FONT_STACK_MONO,
                  fontSize: 32 * scale,
                  color: palette.accentStart,
                  opacity: slide,
                  transform: `translateX(${(1 - slide) * -30 * scale}px)`,
                }}
              >
                {link}
              </div>
            );
          })}
        </div>
      </div>
    </SceneChrome>
  );
};
