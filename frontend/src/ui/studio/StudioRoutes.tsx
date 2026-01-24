import React from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { StudioHome } from "./pages/StudioHome";
import { StudioNewWizard } from "./pages/StudioNewWizard";
import { StudioWorkspace } from "./pages/StudioWorkspace";
import { studioPaths } from "./lib/studioPaths";

/**
 * Studio routing configuration.
 *
 * Routes:
 * - /               → Library home
 * - /new            → New project wizard
 * - /videos/:id/*   → Video workspace with tabs
 *
 * NOTE: These routes are intentionally NOT prefixed with "/studio" so
 * CreatorStudioHost can mount StudioRoutes inside a MemoryRouter cleanly.
 *
 * COMPAT: We still accept legacy "/studio/*" paths and redirect.
 */
export function StudioRoutes() {
  return (
    <Routes>
      {/* Legacy redirects (old links/bookmarks) */}
      <Route path="/studio" element={<Navigate to={studioPaths.home()} replace />} />
      <Route path="/studio/new" element={<Navigate to={studioPaths.newProject()} replace />} />
      <Route path="/studio/videos/:id/*" element={<Navigate to={studioPaths.home()} replace />} />
      <Route path="/studio/*" element={<Navigate to={studioPaths.home()} replace />} />

      {/* Canonical routes */}
      <Route path={studioPaths.home()} element={<StudioHome />} />
      <Route path={studioPaths.newProject()} element={<StudioNewWizard />} />
      <Route path={studioPaths.videoRootPattern()} element={<StudioWorkspace />} />

      {/* Catch-all */}
      <Route path="*" element={<Navigate to={studioPaths.home()} replace />} />
    </Routes>
  );
}
