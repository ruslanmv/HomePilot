// @homepilot/ui — design tokens shared across web, desktop, and mobile.
//
// Tokens only (platform-safe values). Components stay per-app: web/desktop use
// these via Tailwind/CSS vars, mobile via NativeWind. A token changed here
// updates every app's look on next build — one source of truth for the brand.

export const tokens = {
  color: {
    bg: "#0b0f1a",
    surface: "#141a2a",
    primary: "#6366f1",
    primaryHover: "#4f46e5",
    success: "#10b981",
    danger: "#ef4444",
    text: "#e5e7eb",
    muted: "#9ca3af",
  },
  space: { xs: 4, sm: 8, md: 16, lg: 24, xl: 32 },
  radius: { sm: 6, md: 12, lg: 20, pill: 999 },
  font: {
    family: "Inter, system-ui, sans-serif",
    size: { sm: 13, md: 15, lg: 18, xl: 24 },
    weight: { regular: 400, medium: 500, bold: 700 },
  },
} as const;

export type Tokens = typeof tokens;
