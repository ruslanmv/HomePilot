/**
 * Voice Module Exports
 *
 * Provides a unified voice interaction system with:
 * - Adaptive Voice Activity Detection (VAD)
 * - Unified state machine controller
 * - Browser AEC/NS/AGC support
 * - True barge-in capability
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
