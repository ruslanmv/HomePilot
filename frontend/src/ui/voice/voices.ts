/**
 * Voice Persona Definitions
 *
 * Defines available voice personas for the HomePilot Voice UI.
 * These map to browser SpeechSynthesis voices with custom rate/pitch settings.
 */

export type VoiceId = 'ara' | 'eve' | 'leo' | 'rex' | 'sal' | 'gork';

export interface VoiceDef {
  id: VoiceId;
  name: string;
  description: string;
  avatar: string;
  rate: number;
  pitch: number;
  ttsHints: string[];
}

export const VOICES: VoiceDef[] = [
  {
    id: 'ara',
    name: 'Ara',
    description: 'Upbeat Female',
    avatar: 'A',
    rate: 1.05,
    pitch: 1.1,
    ttsHints: ['Google US', 'en-US', 'Samantha', 'Karen'],
  },
  {
    id: 'eve',
    name: 'Eve',
    description: 'Soothing Female',
    avatar: 'E',
    rate: 1.0,
    pitch: 1.0,
    ttsHints: ['Google UK', 'en-GB', 'Serena', 'Moira'],
  },
  {
    id: 'leo',
    name: 'Leo',
    description: 'British Male',
    avatar: 'L',
    rate: 0.96,
    pitch: 0.95,
    ttsHints: ['en-GB', 'Male', 'Daniel', 'Oliver'],
  },
  {
    id: 'rex',
    name: 'Rex',
    description: 'Calm Male',
    avatar: 'R',
    rate: 0.98,
    pitch: 0.9,
    ttsHints: ['en-US', 'Male', 'Alex', 'Tom'],
  },
  {
    id: 'sal',
    name: 'Sal',
    description: 'Smooth Male',
    avatar: 'S',
    rate: 1.0,
    pitch: 1.0,
    ttsHints: ['en-US', 'Google US'],
  },
  {
    id: 'gork',
    name: 'Gork',
    description: 'Lazy Male',
    avatar: 'G',
    rate: 0.85,
    pitch: 0.85,
    ttsHints: ['en-US', 'Male'],
  },
];

/**
 * Find the best matching browser voice for a voice persona
 */
export function findBrowserVoice(
  voiceDef: VoiceDef,
  availableVoices: SpeechSynthesisVoice[]
): SpeechSynthesisVoice | null {
  if (availableVoices.length === 0) return null;

  // Try to match by hints
  for (const hint of voiceDef.ttsHints) {
    const match = availableVoices.find(
      (v) =>
        v.name.toLowerCase().includes(hint.toLowerCase()) ||
        v.lang.toLowerCase().includes(hint.toLowerCase())
    );
    if (match) return match;
  }

  // Fallback: any English voice
  const englishVoice = availableVoices.find((v) => v.lang.startsWith('en'));
  if (englishVoice) return englishVoice;

  // Last resort
  return availableVoices[0];
}

/**
 * Get default voice
 */
export function getDefaultVoice(): VoiceDef {
  return VOICES[0]; // Ara
}

/**
 * Find voice by ID
 */
export function getVoiceById(id: VoiceId): VoiceDef | undefined {
  return VOICES.find((v) => v.id === id);
}

// localStorage key
export const LS_VOICE_ID = 'homepilot_voice_id';
