import React from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { StudioHome } from "./pages/StudioHome";
import { StudioNewWizard } from "./pages/StudioNewWizard";
import { StudioWorkspace } from "./pages/StudioWorkspace";

/**
 * Studio routing configuration.
 *
 * Routes:
 * - /studio         → Library home
 * - /studio/new     → New project wizard
 * - /studio/videos/:id/* → Video workspace with tabs
 */
export function StudioRoutes() {
  return (
    <Routes>
      <Route path="/" element={<StudioHome />} />
      <Route path="/new" element={<StudioNewWizard />} />
      <Route path="/videos/:id/*" element={<StudioWorkspace />} />
      <Route path="*" element={<Navigate to="/studio" replace />} />
    </Routes>
  );
}
