/**
 * TTS plugin system — public entry point.
 *
 * Importing this module (once, from the app root) has two side effects:
 *
 *   1. Registers every bundled provider (web-speech-api, piper-wasm).
 *   2. Makes all public types + the ``useActiveTts()`` React hook
 *      available as named exports.
 *
 * Feature modules that want to call TTS should import from here, not
 * from the individual provider files — that way the registration side
 * effect happens even when tree-shakers would otherwise drop the
 * provider imports.
 */
// Side-effect imports: each provider self-registers on first import.
import './providers/webSpeech/provider';
import './providers/piper/provider';
// Side-effect import: wraps window.SpeechService (the legacy in-app TTS
// path at App.tsx:4012) so picking Piper from Settings actually plays
// Piper audio. No-op when engine=web-speech-api so default users are
// unaffected.
import './shimSpeechService';
export { list as listTtsProviders, get as getTtsProvider, getActive as getActiveTtsProvider, getActiveId as getActiveTtsEngineId, setActive as setActiveTtsEngine, onActiveChange as onActiveTtsEngineChange, readSettings as readTtsProviderSettings, writeSettings as writeTtsProviderSettings, } from './core/registry';
export { TtsEngineProvider, useActiveTts } from './core/context';
