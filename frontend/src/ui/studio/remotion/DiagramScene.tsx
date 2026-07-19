import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { SceneChrome } from "./SceneChrome";
import {
  FONT_STACK_MONO,
  MotionGraphicProps,
  RUSLANMV_ESSAYS_PALETTE,
  sentences,
} from "./types";

/**
 * DiagramScene - the beat's sentences become nodes connected by arrows,
 * appearing one by one. Exact text, exact order; nothing is generated at
 * render time, so a label cannot be misspelled.
 */
export const DiagramScene: React.FC<MotionGraphicProps> = (props) => {
  const palette = props.palette ?? RUSLANMV_ESSAYS_PALETTE;
  const frame = useCurrentFrame();
  const { fps, height, width } = useVideoConfig();
  const scale = height / 1080;
  const vertical = height > width; // 9:16 stacks nodes top-to-bottom

  const nodes = sentences(props.narration, 3);
  const items = nodes.length > 0 ? nodes : [props.narration];

  return (
    <SceneChrome title={props.title} safeMarginPct={props.safeMarginPct} palette={palette}>
      <div
        style={{
          flex: 1,
          display: "flex",
          flexDirection: vertical ? "column" : "row",
          alignItems: "center",
          justifyContent: "center",
          gap: 24 * scale,
        }}
      >
        {items.map((node, i) => {
          const appear = spring({
            frame: frame - i * fps * 0.5,
            fps,
            config: { damping: 200 },
          });
          const arrowOpacity = interpolate(
            frame,
            [(i + 0.5) * fps * 0.5, (i + 1) * fps * 0.5],
            [0, 1],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
          );
          return (
            <React.Fragment key={i}>
              <div
                style={{
                  border: `${Math.max(2, 3 * scale)}px solid ${palette.accentMid}`,
                  borderRadius: 16 * scale,
                  padding: 24 * scale,
                  color: palette.textPrimary,
                  fontFamily: FONT_STACK_MONO,
                  fontSize: 30 * scale,
                  lineHeight: 1.35,
                  flex: 1,
                  maxWidth: vertical ? "100%" : `${100 / items.length}%`,
                  opacity: appear,
                  transform: `translateY(${(1 - appear) * 24 * scale}px)`,
                }}
              >
                {node}
              </div>
              {i < items.length - 1 && (
                <div
                  style={{
                    color: palette.accentMid,
                    fontSize: 44 * scale,
                    opacity: arrowOpacity,
                    transform: vertical ? "rotate(90deg)" : undefined,
                    flexShrink: 0,
                  }}
                >
                  →
                </div>
              )}
            </React.Fragment>
          );
        })}
      </div>
    </SceneChrome>
  );
};
