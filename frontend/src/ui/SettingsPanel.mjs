// Vite resolves .mjs before the checked-in .jsx runtime twin for extensionless
// imports. Route App.jsx through the additive media wrapper without duplicating
// the large legacy SettingsPanel implementation.
export { default } from './SettingsPanelWithMedia.tsx';
