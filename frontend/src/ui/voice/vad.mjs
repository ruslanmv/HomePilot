// The repository still contains a legacy generated vad.js next to vad.ts.
// Vite resolves .mjs before .js for extensionless imports, so this tiny bridge
// keeps the TypeScript implementation as the single runtime source of truth.
export { createVAD } from './vad.ts';
