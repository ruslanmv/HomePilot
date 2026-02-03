/**
 * Voice Module Exports
 *
 * Provides a unified voice interaction system with:
 * - Adaptive Voice Activity Detection (VAD)
 * - Unified state machine controller
 * - Browser AEC/NS/AGC support
 * - True barge-in capability
 * - Grok-style UI components
 */

// VAD exports
export {
  createVAD,
  type VADConfig,
  type VADState,
  type VADCallbacks,
  type VADInstance,
} from './vad';

// Voice controller exports
export {
  useVoiceController,
  type VoiceState,
  type VoiceControllerConfig,
  type VoiceController,
} from './useVoiceController';

// Voice persona exports
export {
  VOICES,
  type VoiceDef,
  type VoiceId,
  getDefaultVoice,
  getVoiceById,
  findBrowserVoice,
  LS_VOICE_ID,
} from './voices';

// Personality exports
export {
  PERSONALITIES,
  type PersonalityDef,
  type PersonalityId,
  getDefaultPersonality,
  getPersonalityById,
  LS_PERSONALITY_ID,
} from './personalities';

// UI component exports
export { default as Starfield } from './Starfield';
export { default as SpeedSlider } from './SpeedSlider';
export { default as VoiceGrid } from './VoiceGrid';
export { default as PersonalityList } from './PersonalityList';
export { default as VoiceSettingsPanel } from './VoiceSettingsPanel';
export { default as SettingsModal } from './SettingsModal';
