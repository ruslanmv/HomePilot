/**
 * Studio Module
 *
 * Complete frontend for the Studio content creation system.
 *
 * Features:
 * - Image generation with NSFW support
 * - Story/text generation with mature content
 * - Gallery management
 * - Content rating system (SFW/Mature)
 * - Generation presets
 *
 * Usage in your app router:
 *   import { StudioRoutes, StudioLayout } from "@/ui/studio";
 *   <Route path="/studio/*" element={<StudioRoutes />} />
 *   // Or use StudioLayout for the new generation UI
 *   <Route path="/studio/*" element={<StudioLayout />} />
 */

// Legacy exports
export { StudioRoutes } from "./StudioRoutes";
export { StudioShell } from "./StudioShell";
export { StudioLibraryRail } from "./StudioLibraryRail";

// Components
export * from "./components";

// Tabs (legacy)
export * from "./tabs";

// Pages (new)
export * from "./pages";

// Hooks
export * from "./hooks";

// Store
export { useStudioStore } from "./stores/studioStore";

// Styles
export { getTheme, themeToCSS, sfwTheme, matureTheme } from "./styles/themes";
