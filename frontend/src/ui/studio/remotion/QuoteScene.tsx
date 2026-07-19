import React from "react";
import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { SceneChrome } from "./SceneChrome";
import {
  FONT_STACK_HEADING,
  MotionGraphicProps,
  RUSLANMV_ESSAYS_PALETTE,
} from "./types";

/**
 * QuoteScene - a thesis line fades up word by word. The words are the
 * essay's own (is_thesis_line beats from the segmenter), rendered exactly.
 * Also serves as the title-card fallback for hero/transition stills.
 */
export const QuoteScene: React.FC<MotionGraphicProps> = (props) => {
  const palette = props.palette ?? RUSLANMV_ESSAYS_PALETTE;
  const frame = useCurrentFrame();
  const { fps, height } = useVideoConfig();
  const scale = height / 1080;

  const words = props.narration.split(/\s+/).filter(Boolean);
  const perWord = (fps * 1.6) / Math.max(1, words.length);

  return (
    <SceneChrome title={props.title} safeMarginPct={props.safeMarginPct} palette={palette}>
      <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center" }}>
        <div
          style={{
            fontFamily: FONT_STACK_HEADING,
            fontSize: 120 * scale,
            lineHeight: 0.8,
            color: palette.accentEnd,
            fontWeight: 700,
          }}
        >
          “
        </div>
        <blockquote
          style={{
            fontFamily: FONT_STACK_HEADING,
            fontSize: 58 * scale,
            lineHeight: 1.45,
            color: palette.textPrimary,
            margin: 0,
            marginLeft: 60 * scale,
            maxWidth: "88%",
            fontWeight: 500,
          }}
        >
          {words.map((word, i) => (
            <span
              key={i}
              style={{
                opacity: interpolate(frame, [i * perWord, i * perWord + fps * 0.4], [0, 1], {
                  extrapolateLeft: "clamp",
                  extrapolateRight: "clamp",
                }),
              }}
            >
              {word}{" "}
            </span>
          ))}
        </blockquote>
      </div>
    </SceneChrome>
  );
};
