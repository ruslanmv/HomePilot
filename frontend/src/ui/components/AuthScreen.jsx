/**
 * Stale-shadow guard.
 *
 * The canonical AuthScreen implementation lives in AuthScreen.tsx. Vite is
 * configured (see frontend/vite.config.ts) to resolve `.tsx` before `.jsx`, and
 * tsconfig has `allowJs` off, so this `.jsx` file is neither bundled nor
 * type-checked. It used to hold a hand-transpiled copy that could silently go
 * stale and ship an old login UI. This re-export keeps a single source of truth.
 */
export { default } from './AuthScreen'
