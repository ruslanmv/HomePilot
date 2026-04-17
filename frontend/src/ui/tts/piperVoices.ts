/**
 * Piper voice catalog — curated from @mintplex-labs/piper-tts-web PATH_MAP.
 *
 * Ported from ruslanmv/3D-Avatar-Chatbot/src/tts/PiperWasmTTSProvider.js:22-105
 * (medium quality first, then low/high, female before male per language).
 *
 * Each voice id matches an ONNX model that the Piper WASM runtime fetches
 * on first use and caches in the browser's OPFS store. The ~20 MB download
 * happens once per voice per origin.
 *
 * Audio format returned by Piper: 16-bit PCM mono WAV at 22,050 Hz.
 */

export type PiperVoice = {
  id: string
  name: string
  /** BCP-47 locale tag, e.g. "en-US". */
  lang: string
  gender: 'female' | 'male'
  /** Quality tier. 'medium' is the production default; 'low' is faster but rougher; 'high' is slower and larger. */
  quality: 'low' | 'medium' | 'high'
}

export const DEFAULT_PIPER_VOICE_ID = 'en_US-hfc_female-medium'

export const PIPER_VOICES: readonly PiperVoice[] = Object.freeze([
  // ── English (US) ──
  { id: 'en_US-hfc_female-medium',   name: 'HFC Female',            lang: 'en-US', gender: 'female', quality: 'medium' },
  { id: 'en_US-lessac-medium',       name: 'Lessac',                lang: 'en-US', gender: 'female', quality: 'medium' },
  { id: 'en_US-kristin-medium',      name: 'Kristin',               lang: 'en-US', gender: 'female', quality: 'medium' },
  { id: 'en_US-libritts_r-medium',   name: 'LibriTTS-R',            lang: 'en-US', gender: 'female', quality: 'medium' },
  { id: 'en_US-amy-medium',          name: 'Amy',                   lang: 'en-US', gender: 'female', quality: 'medium' },
  { id: 'en_US-amy-low',             name: 'Amy (fast)',            lang: 'en-US', gender: 'female', quality: 'low'    },
  { id: 'en_US-kathleen-low',        name: 'Kathleen (fast)',       lang: 'en-US', gender: 'female', quality: 'low'    },
  { id: 'en_US-hfc_male-medium',     name: 'HFC Male',              lang: 'en-US', gender: 'male',   quality: 'medium' },
  { id: 'en_US-ryan-medium',         name: 'Ryan',                  lang: 'en-US', gender: 'male',   quality: 'medium' },
  { id: 'en_US-joe-medium',          name: 'Joe',                   lang: 'en-US', gender: 'male',   quality: 'medium' },
  { id: 'en_US-john-medium',         name: 'John',                  lang: 'en-US', gender: 'male',   quality: 'medium' },
  { id: 'en_US-bryce-medium',        name: 'Bryce',                 lang: 'en-US', gender: 'male',   quality: 'medium' },
  { id: 'en_US-norman-medium',       name: 'Norman',                lang: 'en-US', gender: 'male',   quality: 'medium' },
  { id: 'en_US-arctic-medium',       name: 'Arctic',                lang: 'en-US', gender: 'male',   quality: 'medium' },
  { id: 'en_US-danny-low',           name: 'Danny (fast)',          lang: 'en-US', gender: 'male',   quality: 'low'    },
  { id: 'en_US-ryan-low',            name: 'Ryan (fast)',           lang: 'en-US', gender: 'male',   quality: 'low'    },

  // ── English (UK) ──
  { id: 'en_GB-alba-medium',         name: 'Alba',                  lang: 'en-GB', gender: 'female', quality: 'medium' },
  { id: 'en_GB-cori-medium',         name: 'Cori',                  lang: 'en-GB', gender: 'female', quality: 'medium' },
  { id: 'en_GB-jenny_dioco-medium',  name: 'Jenny Dioco',           lang: 'en-GB', gender: 'female', quality: 'medium' },
  { id: 'en_GB-southern_english_female-low', name: 'Southern Female (fast)', lang: 'en-GB', gender: 'female', quality: 'low' },
  { id: 'en_GB-alan-medium',         name: 'Alan',                  lang: 'en-GB', gender: 'male',   quality: 'medium' },
  { id: 'en_GB-northern_english_male-medium', name: 'Northern Male', lang: 'en-GB', gender: 'male',  quality: 'medium' },
  { id: 'en_GB-aru-medium',          name: 'Aru',                   lang: 'en-GB', gender: 'male',   quality: 'medium' },

  // ── Español ──
  { id: 'es_ES-sharvard-medium',     name: 'SHarvard',              lang: 'es-ES', gender: 'female', quality: 'medium' },
  { id: 'es_ES-davefx-medium',       name: 'DaveFX',                lang: 'es-ES', gender: 'male',   quality: 'medium' },
  { id: 'es_ES-carlfm-x_low',        name: 'Carlfm (fast)',         lang: 'es-ES', gender: 'male',   quality: 'low'    },
  { id: 'es_MX-ald-medium',          name: 'Ald (Mexico)',          lang: 'es-ES', gender: 'male',   quality: 'medium' },
  { id: 'es_MX-claude-high',         name: 'Claude (Mexico, HQ)',   lang: 'es-ES', gender: 'male',   quality: 'high'   },

  // ── Français ──
  { id: 'fr_FR-siwis-medium',        name: 'Siwis',                 lang: 'fr-FR', gender: 'female', quality: 'medium' },
  { id: 'fr_FR-siwis-low',           name: 'Siwis (fast)',          lang: 'fr-FR', gender: 'female', quality: 'low'    },
  { id: 'fr_FR-tom-medium',          name: 'Tom',                   lang: 'fr-FR', gender: 'male',   quality: 'medium' },
  { id: 'fr_FR-upmc-medium',         name: 'UPMC',                  lang: 'fr-FR', gender: 'male',   quality: 'medium' },
  { id: 'fr_FR-gilles-low',          name: 'Gilles (fast)',         lang: 'fr-FR', gender: 'male',   quality: 'low'    },

  // ── Deutsch ──
  { id: 'de_DE-kerstin-low',         name: 'Kerstin',               lang: 'de-DE', gender: 'female', quality: 'low'    },
  { id: 'de_DE-eva_k-x_low',         name: 'Eva K (fast)',          lang: 'de-DE', gender: 'female', quality: 'low'    },
  { id: 'de_DE-thorsten-medium',     name: 'Thorsten',              lang: 'de-DE', gender: 'male',   quality: 'medium' },
  { id: 'de_DE-thorsten_emotional-medium', name: 'Thorsten Emotional', lang: 'de-DE', gender: 'male', quality: 'medium' },
  { id: 'de_DE-mls-medium',          name: 'MLS',                   lang: 'de-DE', gender: 'male',   quality: 'medium' },
  { id: 'de_DE-karlsson-low',        name: 'Karlsson (fast)',       lang: 'de-DE', gender: 'male',   quality: 'low'    },
  { id: 'de_DE-pavoque-low',         name: 'Pavoque (fast)',        lang: 'de-DE', gender: 'male',   quality: 'low'    },

  // ── Italiano ──
  { id: 'it_IT-paola-medium',        name: 'Paola',                 lang: 'it-IT', gender: 'female', quality: 'medium' },
  { id: 'it_IT-riccardo-x_low',      name: 'Riccardo (fast)',       lang: 'it-IT', gender: 'male',   quality: 'low'    },

  // ── Português (BR) ──
  { id: 'pt_BR-faber-medium',        name: 'Faber',                 lang: 'pt-BR', gender: 'male',   quality: 'medium' },
  { id: 'pt_BR-edresson-low',        name: 'Edresson (fast)',       lang: 'pt-BR', gender: 'male',   quality: 'low'    },
])
