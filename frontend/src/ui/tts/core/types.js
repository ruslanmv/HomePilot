/**
 * TTS plugin registry — public types.
 *
 * A TtsProvider is a self-contained engine (Web Speech API, Piper WASM,
 * ElevenLabs, XTTS, …) that registers itself with the registry at import
 * time. The Settings panel reads ``getSettingsSchema()`` from the active
 * provider and renders its controls automatically, so adding a new engine
 * is one-file-and-done: no Settings edit, no call-site touch.
 *
 * This file intentionally declares only types — the registry itself and
 * its React glue live in ./registry and ./context respectively.
 */
export {};
