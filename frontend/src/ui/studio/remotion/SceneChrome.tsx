import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import {
  FONT_STACK_HEADING,
  MotionPalette,
  RUSLANMV_ESSAYS_PALETTE,
} from "./types";

/**
 * Shared frame for every archetype: StyleKit background, the accent
 * gradient bar, the section title, and the safe-content box all children
 * lay out inside. Layout is safe-margin-relative, never pixel-absolute,
 * so one composition reflows at 16:9 / 9:16 / 1:1 (CanvasSpec contract).
 */
export const SceneChrome: React.FC<{
  title: string;
  safeMarginPct?: number;
  palette?: MotionPalette;
  children: React.ReactNode;
}> = ({ title, safeMarginPct = 0.05, palette = RUSLANMV_ESSAYS_PALETTE, children }) => {
  const frame = useCurrentFrame();
  const { width, height, fps } = useVideoConfig();

  const marginX = width * safeMarginPct;
  const marginY = height * safeMarginPct;
  const scale = height / 1080;

  const barReveal = interpolate(frame, [0, fps * 0.6], [0, 1], {
    extrapolateRight: "clamp",
  });
  const titleOpacity = interpolate(frame, [fps * 0.2, fps * 0.9], [0, 1], {
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ backgroundColor: palette.background }}>
      <div
        style={{
          position: "absolute",
          left: marginX,
          top: marginY,
          right: marginX,
          bottom: marginY,
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div
          style={{
            height: 10 * scale,
            width: 220 * scale * barReveal,
            background: `linear-gradient(90deg, ${palette.accentStart}, ${palette.accentMid}, ${palette.accentEnd})`,
            borderRadius: 5 * scale,
          }}
        />
        <h1
          style={{
            fontFamily: FONT_STACK_HEADING,
            fontSize: 64 * scale,
            lineHeight: 1.2,
            color: palette.textPrimary,
            margin: 0,
            marginTop: 40 * scale,
            opacity: titleOpacity,
            fontWeight: 500,
          }}
        >
          {title}
        </h1>
        <div style={{ flex: 1, display: "flex", flexDirection: "column", marginTop: 30 * scale }}>
          {children}
        </div>
      </div>
    </AbsoluteFill>
  );
};
