import { create, StateCreator } from "zustand";
import { persist, PersistOptions } from "zustand/middleware";
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
  // Connection (for API calls)
  backendUrl: string;
  apiKey: string;

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
  // Connection
  setConnection: (backendUrl: string, apiKey: string) => void;

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
  // Connection
  backendUrl: "",
  apiKey: "",

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

type StudioStore = StudioState & StudioActions;

export const useStudioStore = create<StudioStore>()(
  persist(
    (set: (partial: Partial<StudioStore> | ((state: StudioStore) => Partial<StudioStore>)) => void, get: () => StudioStore) => ({
      ...initialState,

      // Connection
      setConnection: (backendUrl: string, apiKey: string) => set({ backendUrl, apiKey }),

      // Content Rating
      setContentRating: (rating: ContentRating) => set({ contentRating: rating }),
      setMatureVerified: (verified: boolean) => set({ matureVerified: verified }),
      setMatureEnabled: (enabled: boolean) => set({ matureEnabled: enabled }),

      // Generation
      setCurrentPrompt: (prompt: string) => set({ currentPrompt: prompt }),
      setCurrentNegativePrompt: (prompt: string) =>
        set({ currentNegativePrompt: prompt }),
      setCurrentSettings: (settings: Partial<GenerationSettings>) =>
        set((state: StudioStore) => ({
          currentSettings: { ...state.currentSettings, ...settings },
        })),
      setSelectedPresetId: (presetId: string | null) => set({ selectedPresetId: presetId }),
      setSelectedModelId: (modelId: string) =>
        set((state: StudioStore) => ({
          selectedModelId: modelId,
          currentSettings: { ...state.currentSettings, model: modelId },
        })),
      setIsGenerating: (generating: boolean) => set({ isGenerating: generating }),
      setGenerationProgress: (progress: number) =>
        set({ generationProgress: progress }),

      applyPreset: (preset: Preset) =>
        set((state: StudioStore) => ({
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
      setPolicyResult: (result: PolicyResult | null) => set({ policyResult: result }),

      // Gallery
      addGeneratedImage: (image: GeneratedImage) =>
        set((state: StudioStore) => ({
          generatedImages: [image, ...state.generatedImages].slice(0, 200),
        })),
      removeGeneratedImage: (id: string) =>
        set((state: StudioStore) => ({
          generatedImages: state.generatedImages.filter((img: GeneratedImage) => img.id !== id),
          selectedImageId:
            state.selectedImageId === id ? null : state.selectedImageId,
        })),
      toggleFavorite: (id: string) =>
        set((state: StudioStore) => ({
          generatedImages: state.generatedImages.map((img: GeneratedImage) =>
            img.id === id ? { ...img, favorite: !img.favorite } : img
          ),
        })),
      setSelectedImageId: (id: string | null) => set({ selectedImageId: id }),
      clearGallery: () => set({ generatedImages: [], selectedImageId: null }),

      // UI State
      setSidebarCollapsed: (collapsed: boolean) => set({ sidebarCollapsed: collapsed }),
      setActiveTab: (tab: StudioState["activeTab"]) => set({ activeTab: tab }),
      setShowAdvancedSettings: (show: boolean) => set({ showAdvancedSettings: show }),

      // Reset
      reset: () => set(initialState),
    }),
    {
      name: "studio-storage",
      partialize: (state: StudioStore) => ({
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
export const selectContentRating = (state: StudioStore) => state.contentRating;
export const selectIsNsfwAllowed = (state: StudioStore) =>
  state.matureEnabled && state.contentRating === "mature" && state.matureVerified;
export const selectFavoriteImages = (state: StudioStore) =>
  state.generatedImages.filter((img: GeneratedImage) => img.favorite);
export const selectRecentImages = (state: StudioStore) =>
  state.generatedImages.slice(0, 20);

/**
 * Get the current studio configuration (backendUrl and apiKey).
 * Used by the API helpers to make authenticated requests.
 */
export function getStudioConfig() {
  const state = useStudioStore.getState();
  return { backendUrl: state.backendUrl, apiKey: state.apiKey };
}
