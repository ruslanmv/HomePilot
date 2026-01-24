/**
 * Canonical route builders for Creator Studio.
 *
 * Why: Avoid hard-coded strings sprinkled across pages (especially now that
 * Studio routes are intentionally NOT prefixed with "/studio").
 *
 * Keep this file tiny and dependency-free so it can be imported anywhere.
 */

export type StudioTab =
  | "overview"
  | "bible"
  | "timeline"
  | "player"
  | "export"
  | "activity";

export const studioPaths = {
  home: () => "/",
  newProject: () => "/new",

  /** react-router pattern for <Route path="..."> */
  videoRootPattern: () => "/videos/:id/*",

  /** Root of a specific project */
  videoRoot: (id: string) => `/videos/${encodeURIComponent(id)}`,

  /** Specific tab route for a project */
  videoTab: (id: string, tab: StudioTab) => `${studioPaths.videoRoot(id)}/${tab}`,
};
