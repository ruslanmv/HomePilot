export { ContentRatingBadge } from "./ContentRatingBadge";
export { StatusBadge } from "./StatusBadge";
export { PlatformBadge } from "./PlatformBadge";
export { PolicyBanner } from "./PolicyBanner";
export { MatureStoryWizard } from "./MatureStoryWizard";
export { RegenerationOptions } from "./RegenerationOptions";

// New components for image generation
export { ContentRatingToggle } from "./ContentRatingToggle";
export { AgeVerificationModal } from "./AgeVerificationModal";
export { PresetCard } from "./PresetCard";
export { ImageGenerator } from "./ImageGenerator";
export { PolicyBadge } from "./PolicyBadge";
export { ModelSelector } from "./ModelSelector";

// Types
export interface PolicyResult {
  allowed: boolean;
  reason: string;
  flags?: string[];
  explicit_allowed?: boolean;
}

export interface SamplerSettings {
  sampler: string;
  steps: number;
  cfg_scale: number;
  clip_skip: number;
}

export interface Preset {
  id: string;
  label: string;
  description: string;
  content_rating: "sfw" | "mature";
  requires_mature_mode: boolean;
  recommended_models: string[];
  sampler_settings: SamplerSettings;
  prompt_injection?: {
    positive_prefix: string;
    positive_suffix: string;
    negative: string;
  };
  safety_guidelines?: string[];
}

export interface Model {
  id: string;
  label: string;
  description: string;
  size_gb: number;
  resolution?: string;
  nsfw: boolean;
  recommended_nsfw?: boolean;
  anime?: boolean;
  downloaded?: boolean;
}

export interface GenerationSettings {
  model: string;
  width: number;
  height: number;
  steps: number;
  cfg: number;
  sampler: string;
  clipSkip: number;
  seed: number | "random";
}
