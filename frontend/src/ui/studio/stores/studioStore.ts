import { create } from "zustand";
import { persist } from "zustand/middleware";
import type {
  Preset,
  Model,
  GenerationSettings,
  PolicyResult,
} from "../components";

// Types
type ContentRating = "sfw" | "mature";

interface GeneratedImage {
  id: string;
  url: string;
  prompt: string;
  negativePrompt: string;
  settings: GenerationSettings;
  contentRating: ContentRating;
  presetId?: string;
  modelId: string;
  timestamp: number;
  favorite: boolean;
}

interface StudioState {
  // Content Rating
  contentRating: ContentRating;
  matureVerified: boolean;
  matureEnabled: boolean;

  // Generation
  currentPrompt: string;
  currentNegativePrompt: string;
  currentSettings: GenerationSettings;
  selectedPresetId: string | null;
  selectedModelId: string;
  isGenerating: boolean;
  generationProgress: number;

  // Policy
  policyResult: PolicyResult | null;

  // Gallery
  generatedImages: GeneratedImage[];
  selectedImageId: string | null;

  // UI State
  sidebarCollapsed: boolean;
  activeTab: "generate" | "gallery" | "story" | "settings";
  showAdvancedSettings: boolean;
}

interface StudioActions {
  // Content Rating
  setContentRating: (rating: ContentRating) => void;
  setMatureVerified: (verified: boolean) => void;
  setMatureEnabled: (enabled: boolean) => void;

  // Generation
  setCurrentPrompt: (prompt: string) => void;
  setCurrentNegativePrompt: (prompt: string) => void;
  setCurrentSettings: (settings: Partial<GenerationSettings>) => void;
  setSelectedPresetId: (presetId: string | null) => void;
  setSelectedModelId: (modelId: string) => void;
  setIsGenerating: (generating: boolean) => void;
  setGenerationProgress: (progress: number) => void;
  applyPreset: (preset: Preset) => void;

  // Policy
  setPolicyResult: (result: PolicyResult | null) => void;

  // Gallery
  addGeneratedImage: (image: GeneratedImage) => void;
  removeGeneratedImage: (id: string) => void;
  toggleFavorite: (id: string) => void;
  setSelectedImageId: (id: string | null) => void;
  clearGallery: () => void;

  // UI State
  setSidebarCollapsed: (collapsed: boolean) => void;
  setActiveTab: (tab: StudioState["activeTab"]) => void;
  setShowAdvancedSettings: (show: boolean) => void;

  // Reset
  reset: () => void;
}

const DEFAULT_SETTINGS: GenerationSettings = {
  model: "abyssOrangeMix3_aom3a1b.safetensors",
  width: 512,
  height: 768,
  steps: 25,
  cfg: 6.0,
  sampler: "dpm++_2m_karras",
  clipSkip: 2,
  seed: "random",
};

const initialState: StudioState = {
  // Content Rating
  contentRating: "sfw",
  matureVerified: false,
  matureEnabled: false,

  // Generation
  currentPrompt: "",
  currentNegativePrompt:
    "lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry",
  currentSettings: DEFAULT_SETTINGS,
  selectedPresetId: null,
  selectedModelId: DEFAULT_SETTINGS.model,
  isGenerating: false,
  generationProgress: 0,

  // Policy
  policyResult: null,

  // Gallery
  generatedImages: [],
  selectedImageId: null,

  // UI State
  sidebarCollapsed: false,
  activeTab: "generate",
  showAdvancedSettings: false,
};

export const useStudioStore = create<StudioState & StudioActions>()(
  persist(
    (set, get) => ({
      ...initialState,

      // Content Rating
      setContentRating: (rating) => set({ contentRating: rating }),
      setMatureVerified: (verified) => set({ matureVerified: verified }),
      setMatureEnabled: (enabled) => set({ matureEnabled: enabled }),

      // Generation
      setCurrentPrompt: (prompt) => set({ currentPrompt: prompt }),
      setCurrentNegativePrompt: (prompt) =>
        set({ currentNegativePrompt: prompt }),
      setCurrentSettings: (settings) =>
        set((state) => ({
          currentSettings: { ...state.currentSettings, ...settings },
        })),
      setSelectedPresetId: (presetId) => set({ selectedPresetId: presetId }),
      setSelectedModelId: (modelId) =>
        set((state) => ({
          selectedModelId: modelId,
          currentSettings: { ...state.currentSettings, model: modelId },
        })),
      setIsGenerating: (generating) => set({ isGenerating: generating }),
      setGenerationProgress: (progress) =>
        set({ generationProgress: progress }),

      applyPreset: (preset) =>
        set((state) => ({
          selectedPresetId: preset.id,
          currentSettings: {
            ...state.currentSettings,
            steps: preset.sampler_settings.steps,
            cfg: preset.sampler_settings.cfg_scale,
            sampler: preset.sampler_settings.sampler,
            clipSkip: preset.sampler_settings.clip_skip,
            model: preset.recommended_models[0] || state.currentSettings.model,
          },
          currentNegativePrompt:
            preset.prompt_injection?.negative || state.currentNegativePrompt,
          selectedModelId:
            preset.recommended_models[0] || state.selectedModelId,
        })),

      // Policy
      setPolicyResult: (result) => set({ policyResult: result }),

      // Gallery
      addGeneratedImage: (image) =>
        set((state) => ({
          generatedImages: [image, ...state.generatedImages].slice(0, 200),
        })),
      removeGeneratedImage: (id) =>
        set((state) => ({
          generatedImages: state.generatedImages.filter((img) => img.id !== id),
          selectedImageId:
            state.selectedImageId === id ? null : state.selectedImageId,
        })),
      toggleFavorite: (id) =>
        set((state) => ({
          generatedImages: state.generatedImages.map((img) =>
            img.id === id ? { ...img, favorite: !img.favorite } : img
          ),
        })),
      setSelectedImageId: (id) => set({ selectedImageId: id }),
      clearGallery: () => set({ generatedImages: [], selectedImageId: null }),

      // UI State
      setSidebarCollapsed: (collapsed) => set({ sidebarCollapsed: collapsed }),
      setActiveTab: (tab) => set({ activeTab: tab }),
      setShowAdvancedSettings: (show) => set({ showAdvancedSettings: show }),

      // Reset
      reset: () => set(initialState),
    }),
    {
      name: "studio-storage",
      partialize: (state) => ({
        contentRating: state.contentRating,
        matureVerified: state.matureVerified,
        generatedImages: state.generatedImages,
        sidebarCollapsed: state.sidebarCollapsed,
        currentSettings: state.currentSettings,
        selectedModelId: state.selectedModelId,
      }),
    }
  )
);

// Selectors
export const selectContentRating = (state: StudioState) => state.contentRating;
export const selectIsNsfwAllowed = (state: StudioState) =>
  state.matureEnabled && state.contentRating === "mature" && state.matureVerified;
export const selectFavoriteImages = (state: StudioState) =>
  state.generatedImages.filter((img) => img.favorite);
export const selectRecentImages = (state: StudioState) =>
  state.generatedImages.slice(0, 20);
