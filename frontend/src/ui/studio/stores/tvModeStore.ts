import { create } from "zustand";
import { persist } from "zustand/middleware";

// Scene type matching the existing Scene interface
export interface TVScene {
  idx: number;
  narration: string;
  image_prompt: string;
  negative_prompt?: string;
  duration_s: number;
  tags: Record<string, string>;
  audio?: string | null;
  audio_url?: string | null;
  image?: string | null;
  image_url?: string | null; // Generated image URL
  status: "pending" | "generating" | "ready" | "error";
  imageStatus?: "pending" | "generating" | "ready" | "error"; // Track image separately (optional, defaults in enterTVMode)
}

export interface TVModeSettings {
  sceneDuration: number; // seconds, 0 = auto (use scene.duration_s)
  transitionDuration: number; // milliseconds
  autoHideDelay: number; // milliseconds
  narrationPosition: "bottom" | "top";
  narrationSize: "small" | "medium" | "large";
  showSceneNumber: boolean;
  pauseOnEnd: boolean;
}

interface TVModeState {
  // Mode State
  isActive: boolean;
  isFullscreen: boolean;

  // Session
  sessionId: string | null;
  storyTitle: string;

  // Playback State
  isPlaying: boolean;
  currentSceneIndex: number;
  scenes: TVScene[];

  // Prefetch State
  isPrefetching: boolean;
  prefetchError: string | null;
  maxScenes: number;

  // UI State
  controlsVisible: boolean;
  showSettings: boolean;
  showEndScreen: boolean;

  // Error handling
  playbackError: string | null;

  // Settings
  settings: TVModeSettings;
}

interface TVModeActions {
  // Mode control
  enterTVMode: (
    sessionId: string,
    storyTitle: string,
    scenes: TVScene[],
    startIndex?: number
  ) => void;
  exitTVMode: () => void;
  setFullscreen: (fullscreen: boolean) => void;

  // Playback control
  play: () => void;
  pause: () => void;
  togglePlay: () => void;

  // Navigation
  nextScene: () => void;
  prevScene: () => void;
  goToScene: (index: number) => void;

  // Scene management
  addScene: (scene: TVScene) => void;
  updateSceneStatus: (
    index: number,
    status: TVScene["status"],
    error?: string
  ) => void;
  updateSceneImage: (index: number, imageUrl: string) => void;
  setSceneImageStatus: (index: number, status: TVScene["imageStatus"]) => void;

  // Correct variants (use scene.idx, not array position)
  updateSceneImageByIdx: (sceneIdx: number, imageUrl: string) => void;
  setSceneImageStatusByIdx: (sceneIdx: number, status: TVScene["imageStatus"]) => void;

  // Prefetch state
  setPrefetching: (isPrefetching: boolean) => void;
  setPrefetchError: (error: string | null) => void;

  // UI control
  showControls: () => void;
  hideControls: () => void;
  setShowSettings: (show: boolean) => void;
  setShowEndScreen: (show: boolean) => void;
  setPlaybackError: (error: string | null) => void;

  // Settings
  updateSettings: (settings: Partial<TVModeSettings>) => void;
  resetSettings: () => void;
}

const DEFAULT_SETTINGS: TVModeSettings = {
  sceneDuration: 0, // 0 = auto (use scene.duration_s)
  transitionDuration: 800,
  autoHideDelay: 3000,
  narrationPosition: "bottom",
  narrationSize: "medium",
  showSceneNumber: true,
  pauseOnEnd: true,
};

const initialState: TVModeState = {
  isActive: false,
  isFullscreen: false,
  sessionId: null,
  storyTitle: "",
  isPlaying: false,
  currentSceneIndex: 0,
  scenes: [],
  isPrefetching: false,
  prefetchError: null,
  maxScenes: 24,
  controlsVisible: true,
  showSettings: false,
  showEndScreen: false,
  playbackError: null,
  settings: DEFAULT_SETTINGS,
};

type TVModeStore = TVModeState & TVModeActions;

export const useTVModeStore = create<TVModeStore>()(
  persist(
    (set, get) => ({
      ...initialState,

      // Mode control
      enterTVMode: (sessionId, storyTitle, scenes, startIndex = 0) => {
        // Convert scenes to TV scenes with proper status
        const tvScenes: TVScene[] = scenes.map((scene) => ({
          ...scene,
          status: "ready" as const,
          // Image is ready if we have image_url or image
          imageStatus: (scene.image_url || scene.image) ? "ready" as const : "pending" as const,
        }));

        set({
          isActive: true,
          sessionId,
          storyTitle,
          scenes: tvScenes,
          currentSceneIndex: startIndex,
          isPlaying: true,
          controlsVisible: true,
          showEndScreen: false,
          playbackError: null,
          prefetchError: null,
        });
      },

      exitTVMode: () => {
        set({
          isActive: false,
          isFullscreen: false,
          isPlaying: false,
          controlsVisible: true,
          showSettings: false,
          showEndScreen: false,
        });
      },

      setFullscreen: (fullscreen) => set({ isFullscreen: fullscreen }),

      // Playback control
      play: () => set({ isPlaying: true }),
      pause: () => set({ isPlaying: false }),
      togglePlay: () => set((state) => ({ isPlaying: !state.isPlaying })),

      // Navigation
      nextScene: () => {
        const { currentSceneIndex, scenes, settings } = get();
        if (currentSceneIndex < scenes.length - 1) {
          set({
            currentSceneIndex: currentSceneIndex + 1,
            showEndScreen: false,
          });
        } else if (settings.pauseOnEnd) {
          set({ isPlaying: false, showEndScreen: true });
        }
      },

      prevScene: () => {
        const { currentSceneIndex } = get();
        if (currentSceneIndex > 0) {
          set({
            currentSceneIndex: currentSceneIndex - 1,
            showEndScreen: false,
          });
        }
      },

      goToScene: (index) => {
        const { scenes } = get();
        if (index >= 0 && index < scenes.length) {
          set({
            currentSceneIndex: index,
            showEndScreen: false,
          });
        }
      },

      // Scene management
      addScene: (scene) => {
        set((state) => ({
          scenes: [...state.scenes, {
            ...scene,
            status: "ready" as const,
            // New scenes start with pending image status (image will be generated)
            imageStatus: (scene.image_url || scene.image) ? "ready" as const : "generating" as const,
          }],
        }));
      },

      updateSceneStatus: (index, status, error) => {
        set((state) => ({
          scenes: state.scenes.map((s, i) =>
            i === index ? { ...s, status } : s
          ),
          playbackError: error || state.playbackError,
        }));
      },

      updateSceneImage: (index, imageUrl) => {
        set((state) => ({
          scenes: state.scenes.map((s, i) =>
            i === index ? { ...s, image_url: imageUrl, imageStatus: "ready" as const } : s
          ),
        }));
      },

      setSceneImageStatus: (index, status) => {
        set((state) => ({
          scenes: state.scenes.map((s, i) =>
            i === index ? { ...s, imageStatus: status } : s
          ),
        }));
      },

      // Correct variants that use scene.idx instead of array position
      updateSceneImageByIdx: (sceneIdx, imageUrl) => {
        set((state) => ({
          scenes: state.scenes.map((s) =>
            s.idx === sceneIdx
              ? { ...s, image_url: imageUrl, imageStatus: "ready" as const }
              : s
          ),
        }));
      },

      setSceneImageStatusByIdx: (sceneIdx, status) => {
        set((state) => ({
          scenes: state.scenes.map((s) =>
            s.idx === sceneIdx ? { ...s, imageStatus: status } : s
          ),
        }));
      },

      // Prefetch state
      setPrefetching: (isPrefetching) => set({ isPrefetching }),
      setPrefetchError: (error) => set({ prefetchError: error }),

      // UI control
      showControls: () => set({ controlsVisible: true }),
      hideControls: () => set({ controlsVisible: false }),
      setShowSettings: (show) => set({ showSettings: show }),
      setShowEndScreen: (show) => set({ showEndScreen: show }),
      setPlaybackError: (error) => set({ playbackError: error }),

      // Settings
      updateSettings: (newSettings) =>
        set((state) => ({
          settings: { ...state.settings, ...newSettings },
        })),

      resetSettings: () => set({ settings: DEFAULT_SETTINGS }),
    }),
    {
      name: "tv-mode-storage",
      partialize: (state) => ({
        settings: state.settings,
      }),
    }
  )
);

// Selectors
export const selectCurrentScene = (state: TVModeStore) =>
  state.scenes[state.currentSceneIndex];

export const selectNextScene = (state: TVModeStore) =>
  state.scenes[state.currentSceneIndex + 1];

export const selectIsLastScene = (state: TVModeStore) =>
  state.currentSceneIndex >= state.scenes.length - 1;

export const selectCanPrefetch = (state: TVModeStore) =>
  state.currentSceneIndex < state.maxScenes - 1 &&
  !state.isPrefetching &&
  !state.scenes[state.currentSceneIndex + 1];

export const selectSceneDuration = (state: TVModeStore) => {
  const scene = selectCurrentScene(state);
  if (state.settings.sceneDuration > 0) {
    return state.settings.sceneDuration * 1000; // Convert to ms
  }
  return (scene?.duration_s || 8) * 1000; // Default 8 seconds
};

// Check if current scene has image ready
export const selectCurrentSceneImageReady = (state: TVModeStore) => {
  const scene = selectCurrentScene(state);
  if (!scene) return false;
  // Image is ready if we have a URL or imageStatus is "ready"
  const hasImage = Boolean(scene.image_url || scene.image);
  return hasImage || scene.imageStatus === "ready";
};

// Check if next scene is fully ready (narration + image)
export const selectNextSceneReady = (state: TVModeStore) => {
  const nextScene = selectNextScene(state);
  if (!nextScene) return false;
  // Scene text must be ready
  if (nextScene.status !== "ready") return false;
  // Image must be ready (has URL or imageStatus is "ready")
  const hasImage = Boolean(nextScene.image_url || nextScene.image);
  return hasImage || nextScene.imageStatus === "ready";
};

// Check if we're waiting for image to generate
export const selectIsWaitingForImage = (state: TVModeStore) => {
  const scene = selectCurrentScene(state);
  if (!scene) return false;
  // We're waiting if imageStatus is "generating" or "pending" AND no image URL
  const hasImage = Boolean(scene.image_url || scene.image);
  return !hasImage && (scene.imageStatus === "generating" || scene.imageStatus === "pending");
};
