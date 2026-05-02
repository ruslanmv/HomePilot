import { create } from "zustand";
import { persist } from "zustand/middleware";
const DEFAULT_SETTINGS = {
    sceneDuration: 0, // 0 = auto (use scene.duration_s)
    transitionDuration: 800,
    autoHideDelay: 3000,
    narrationPosition: "bottom",
    narrationSize: "medium",
    showSceneNumber: true,
    pauseOnEnd: true,
    sagaMode: true, // Auto-continue to next chapter by default
    autoGenerateScenes: true, // Auto-generate new scenes when on last scene by default
};
const initialState = {
    isActive: false,
    isFullscreen: false,
    sessionId: null,
    storyTitle: "",
    sagaId: null,
    chapterNumber: 1,
    isLoadingNextChapter: false,
    isPlaying: false,
    currentSceneIndex: 0,
    scenes: [],
    isPrefetching: false,
    prefetchError: null,
    maxScenes: 24,
    isStoryComplete: false,
    controlsVisible: true,
    showSettings: false,
    showEndScreen: false,
    playbackError: null,
    settings: DEFAULT_SETTINGS,
};
export const useTVModeStore = create()(persist((set, get) => ({
    ...initialState,
    // Mode control
    enterTVMode: (sessionId, storyTitle, scenes, startIndex = 0) => {
        // Convert scenes to TV scenes with proper status
        const tvScenes = scenes.map((scene) => ({
            ...scene,
            status: "ready",
            // Image is ready if we have image_url or image
            imageStatus: (scene.image_url || scene.image) ? "ready" : "pending",
        }));
        set({
            isActive: true,
            sessionId,
            storyTitle,
            sagaId: sessionId, // First chapter becomes the saga root
            chapterNumber: 1,
            isLoadingNextChapter: false,
            scenes: tvScenes,
            currentSceneIndex: startIndex,
            isPlaying: true,
            controlsVisible: true,
            showEndScreen: false,
            playbackError: null,
            prefetchError: null,
            isStoryComplete: false, // Reset when entering new story
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
        }
        else if (settings.pauseOnEnd) {
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
                    status: "ready",
                    // New scenes start with pending image status (image will be generated)
                    imageStatus: (scene.image_url || scene.image) ? "ready" : "generating",
                }],
        }));
    },
    updateSceneStatus: (index, status, error) => {
        set((state) => ({
            scenes: state.scenes.map((s, i) => i === index ? { ...s, status } : s),
            playbackError: error || state.playbackError,
        }));
    },
    updateSceneImage: (index, imageUrl) => {
        set((state) => ({
            scenes: state.scenes.map((s, i) => i === index ? { ...s, image_url: imageUrl, imageStatus: "ready" } : s),
        }));
    },
    setSceneImageStatus: (index, status) => {
        set((state) => ({
            scenes: state.scenes.map((s, i) => i === index ? { ...s, imageStatus: status } : s),
        }));
    },
    // Correct variants that use scene.idx instead of array position
    updateSceneImageByIdx: (sceneIdx, imageUrl) => {
        set((state) => ({
            scenes: state.scenes.map((s) => s.idx === sceneIdx
                ? { ...s, image_url: imageUrl, imageStatus: "ready" }
                : s),
        }));
    },
    setSceneImageStatusByIdx: (sceneIdx, status) => {
        set((state) => ({
            scenes: state.scenes.map((s) => s.idx === sceneIdx ? { ...s, imageStatus: status } : s),
        }));
    },
    // Prefetch state
    setPrefetching: (isPrefetching) => set({ isPrefetching }),
    setPrefetchError: (error) => set({ prefetchError: error }),
    setStoryComplete: (complete) => set({ isStoryComplete: complete }),
    // Saga mode (chapter continuation)
    setLoadingNextChapter: (loading) => set({ isLoadingNextChapter: loading }),
    startNextChapter: (sessionId, title, scenes, chapterNumber) => {
        // Convert scenes to TV scenes with proper status
        const tvScenes = scenes.map((scene) => ({
            ...scene,
            status: "ready",
            imageStatus: (scene.image_url || scene.image) ? "ready" : "pending",
        }));
        set({
            sessionId,
            storyTitle: title,
            chapterNumber,
            isLoadingNextChapter: false,
            scenes: tvScenes,
            currentSceneIndex: 0,
            isPlaying: true,
            isStoryComplete: false,
            prefetchError: null,
            showEndScreen: false,
        });
    },
    // UI control
    showControls: () => set({ controlsVisible: true }),
    hideControls: () => set({ controlsVisible: false }),
    setShowSettings: (show) => set({ showSettings: show }),
    setShowEndScreen: (show) => set({ showEndScreen: show }),
    setPlaybackError: (error) => set({ playbackError: error }),
    // Settings
    updateSettings: (newSettings) => set((state) => ({
        settings: { ...state.settings, ...newSettings },
    })),
    resetSettings: () => set({ settings: DEFAULT_SETTINGS }),
}), {
    name: "tv-mode-storage",
    partialize: (state) => ({
        settings: state.settings,
    }),
}));
// Selectors
export const selectCurrentScene = (state) => state.scenes[state.currentSceneIndex];
export const selectNextScene = (state) => state.scenes[state.currentSceneIndex + 1];
export const selectIsLastScene = (state) => state.currentSceneIndex >= state.scenes.length - 1;
export const selectCanPrefetch = (state) => state.currentSceneIndex < state.maxScenes - 1 &&
    !state.isPrefetching &&
    !state.scenes[state.currentSceneIndex + 1];
export const selectSceneDuration = (state) => {
    const scene = selectCurrentScene(state);
    if (state.settings.sceneDuration > 0) {
        return state.settings.sceneDuration * 1000; // Convert to ms
    }
    return (scene?.duration_s || 8) * 1000; // Default 8 seconds
};
// Check if current scene has image ready
export const selectCurrentSceneImageReady = (state) => {
    const scene = selectCurrentScene(state);
    if (!scene)
        return false;
    // Image is ready if we have a URL or imageStatus is "ready"
    const hasImage = Boolean(scene.image_url || scene.image);
    return hasImage || scene.imageStatus === "ready";
};
// Check if next scene is fully ready (narration + image)
export const selectNextSceneReady = (state) => {
    const nextScene = selectNextScene(state);
    if (!nextScene)
        return false;
    // Scene text must be ready
    if (nextScene.status !== "ready")
        return false;
    // Image must be ready (has URL or imageStatus is "ready")
    const hasImage = Boolean(nextScene.image_url || nextScene.image);
    return hasImage || nextScene.imageStatus === "ready";
};
// Check if we're waiting for image to generate
export const selectIsWaitingForImage = (state) => {
    const scene = selectCurrentScene(state);
    if (!scene)
        return false;
    // We're waiting if imageStatus is "generating" or "pending" AND no image URL
    const hasImage = Boolean(scene.image_url || scene.image);
    return !hasImage && (scene.imageStatus === "generating" || scene.imageStatus === "pending");
};
