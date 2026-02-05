/**
 * Model Configuration & Preset Logic for Frontend
 *
 * Mirrors backend/app/model_config.py to ensure UI shows correct values
 * based on model architecture (SD1.5 vs SDXL vs Flux).
 *
 * This prevents the "two heads" issue by enforcing safe resolutions
 * for SD1.5 models (max 768px) while allowing SDXL/Flux native 1024px+.
 */

export type Architecture = "sd15" | "sdxl" | "flux_schnell" | "flux_dev";
export type PresetName = "low" | "med" | "high" | "ultra";
export type AspectRatio = "1:1" | "4:3" | "3:4" | "16:9" | "9:16";

export interface Dimensions {
  width: number;
  height: number;
}

export interface StepCfg {
  steps: number;
  cfg: number;
}

export interface ModelSettings {
  width: number;
  height: number;
  steps: number;
  cfg: number;
  architecture: Architecture;
}

// =============================================================================
// 1. MODEL ARCHITECTURE MAPPING
// =============================================================================

export const MODEL_ARCHITECTURES: Record<string, Architecture> = {
  // --- SDXL Models (Native 1024x1024) ---
  "sd_xl_base_1.0.safetensors": "sdxl",
  "ponyDiffusionV6XL_v6.safetensors": "sdxl",

  // --- Flux Models (Native 1024+, Special Steps / CFG behavior) ---
  "flux1-schnell.safetensors": "flux_schnell",
  "flux1-dev.safetensors": "flux_dev",

  // --- SD 1.5 Models (Native 512x512) ---
  "dreamshaper_8.safetensors": "sd15",
  "epicrealism_pureEvolution.safetensors": "sd15",
  "abyssOrangeMix3_aom3a1b.safetensors": "sd15",
  "sd15.safetensors": "sd15",
  "realisticVisionV51.safetensors": "sd15",
  "deliberate_v3.safetensors": "sd15",
  "cyberrealistic_v42.safetensors": "sd15",
  "absolutereality_v181.safetensors": "sd15",
  "aZovyaRPGArtist_v5.safetensors": "sd15",
  "unstableDiffusion.safetensors": "sd15",
  "majicmixRealistic_v7.safetensors": "sd15",
  "bbmix_v4.safetensors": "sd15",
  "realisian_v50.safetensors": "sd15",
  "counterfeit_v30.safetensors": "sd15",
  "anything_v5PrtRE.safetensors": "sd15",
};

// =============================================================================
// 2. RESOLUTION LOOKUP TABLES
// =============================================================================

// SD 1.5: Strict limits to prevent "Two Heads" (keep dimensions conservative)
export const SD15_RESOLUTIONS: Record<AspectRatio, Dimensions> = {
  "1:1":  { width: 512, height: 512 },
  "4:3":  { width: 680, height: 512 },
  "3:4":  { width: 512, height: 680 },
  "16:9": { width: 768, height: 432 },
  "9:16": { width: 432, height: 768 },
};

// SDXL / Flux: High Resolution Native (Base 1024)
export const SDXL_RESOLUTIONS: Record<AspectRatio, Dimensions> = {
  "1:1":  { width: 1024, height: 1024 },
  "4:3":  { width: 1152, height: 896 },
  "3:4":  { width: 896, height: 1152 },
  "16:9": { width: 1216, height: 832 },
  "9:16": { width: 832, height: 1216 },
};

// =============================================================================
// 3. GENERATION PRESETS (Steps & CFG)
// =============================================================================

export const PRESETS: Record<Architecture, Record<PresetName, StepCfg>> = {
  // Standard SD 1.5 (DreamShaper, Realistic Vision, etc.)
  sd15: {
    low:   { steps: 20, cfg: 7.0 },
    med:   { steps: 25, cfg: 7.0 },
    high:  { steps: 35, cfg: 8.0 },
    ultra: { steps: 50, cfg: 8.5 },
  },

  // Standard SDXL (Base, Pony)
  sdxl: {
    low:   { steps: 25, cfg: 5.0 },
    med:   { steps: 30, cfg: 5.5 },
    high:  { steps: 45, cfg: 6.0 },
    ultra: { steps: 60, cfg: 6.5 },
  },

  // Flux SCHNELL (Must be fast; optimized for very low step counts)
  flux_schnell: {
    low:   { steps: 4, cfg: 1.0 },
    med:   { steps: 4, cfg: 1.0 },
    high:  { steps: 6, cfg: 1.0 },
    ultra: { steps: 8, cfg: 1.0 },
  },

  // Flux DEV (High quality; likes lower CFG)
  flux_dev: {
    low:   { steps: 20, cfg: 3.5 },
    med:   { steps: 25, cfg: 3.5 },
    high:  { steps: 40, cfg: 4.0 },
    ultra: { steps: 50, cfg: 4.0 },
  },
};

// =============================================================================
// 4. HELPER FUNCTIONS
// =============================================================================

const DEFAULT_ARCH: Architecture = "sd15";
const DEFAULT_ASPECT: AspectRatio = "1:1";
const DEFAULT_PRESET: PresetName = "med";

/**
 * Detect architecture from model filename using heuristics.
 */
export function detectArchitecture(modelFilename: string): Architecture {
  if (!modelFilename) return DEFAULT_ARCH;

  // Check known models first
  if (MODEL_ARCHITECTURES[modelFilename]) {
    return MODEL_ARCHITECTURES[modelFilename];
  }

  const lower = modelFilename.toLowerCase();

  // Flux detection
  if (lower.includes("flux")) {
    if (lower.includes("schnell")) return "flux_schnell";
    return "flux_dev";
  }

  // SDXL detection
  if (lower.includes("sdxl") || lower.includes("_xl") || lower.includes("-xl") || lower.includes("xl_") || lower.includes("pony")) {
    return "sdxl";
  }

  // Default to SD1.5 (safest for preventing duplication)
  return "sd15";
}

/**
 * Get resolution table based on architecture.
 */
export function getResolutionTable(arch: Architecture): Record<AspectRatio, Dimensions> {
  if (arch === "sdxl" || arch === "flux_schnell" || arch === "flux_dev") {
    return SDXL_RESOLUTIONS;
  }
  return SD15_RESOLUTIONS;
}

/**
 * Normalize aspect ratio to valid value.
 */
export function normalizeAspectRatio(aspectRatio: string): AspectRatio {
  const valid: AspectRatio[] = ["1:1", "4:3", "3:4", "16:9", "9:16"];
  return valid.includes(aspectRatio as AspectRatio) ? (aspectRatio as AspectRatio) : DEFAULT_ASPECT;
}

/**
 * Normalize preset to valid value.
 */
export function normalizePreset(preset: string): PresetName {
  const valid: PresetName[] = ["low", "med", "high", "ultra"];
  return valid.includes(preset as PresetName) ? (preset as PresetName) : DEFAULT_PRESET;
}

/**
 * Get model settings based on model filename, aspect ratio, and preset.
 * This is the main function to call when you need to know what settings to use.
 */
export function getModelSettings(
  modelFilename: string,
  aspectRatio: string = "1:1",
  preset: string = "med"
): ModelSettings {
  const arch = detectArchitecture(modelFilename);
  const ar = normalizeAspectRatio(aspectRatio);
  const pr = normalizePreset(preset);

  const resTable = getResolutionTable(arch);
  const dimensions = resTable[ar] || resTable[DEFAULT_ASPECT];

  const presetTable = PRESETS[arch];
  const stepCfg = presetTable[pr] || presetTable[DEFAULT_PRESET];

  return {
    width: dimensions.width,
    height: dimensions.height,
    steps: stepCfg.steps,
    cfg: stepCfg.cfg,
    architecture: arch,
  };
}

/**
 * Get human-readable description for a preset + model combination.
 */
export function getPresetDescription(modelFilename: string, preset: PresetName): string {
  const settings = getModelSettings(modelFilename, "1:1", preset);
  const archLabel = {
    sd15: "SD 1.5",
    sdxl: "SDXL",
    flux_schnell: "Flux Schnell",
    flux_dev: "Flux Dev",
  }[settings.architecture];

  return `${archLabel}: ${settings.width}×${settings.height}, ${settings.steps} steps, CFG ${settings.cfg}`;
}

/**
 * Get architecture display name.
 */
export function getArchitectureLabel(arch: Architecture): string {
  return {
    sd15: "SD 1.5",
    sdxl: "SDXL",
    flux_schnell: "Flux Schnell",
    flux_dev: "Flux Dev",
  }[arch];
}
