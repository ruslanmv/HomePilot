import React, { useEffect, useRef, useCallback } from "react";
import {
  useTVModeStore,
  selectCurrentScene,
  selectSceneDuration,
  selectIsLastScene,
  selectNextSceneReady,
  selectCurrentSceneImageReady,
  selectIsWaitingForImage,
  selectNextScene,
} from "../../stores/tvModeStore";
import type { TVScene } from "../../stores/tvModeStore";
import { TVModePlayer } from "./TVModePlayer";
import { TVModeControls } from "./TVModeControls";
import { TVModeSettings } from "./TVModeSettings";
import { TVModeEndScreen } from "./TVModeEndScreen";

interface TVModeContainerProps {
  onGenerateNext: () => Promise<any>;
  onEnsureImage?: (scene: TVScene) => void;
}

export const TVModeContainer: React.FC<TVModeContainerProps> = ({
  onGenerateNext,
  onEnsureImage,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const controlsTimerRef = useRef<number | null>(null);
  const sceneTimerRef = useRef<number | null>(null);
  const prefetchInFlightRef = useRef(false);

  const {
    isActive,
    isPlaying,
    currentSceneIndex,
    scenes,
    controlsVisible,
    showSettings,
    showEndScreen,
    isPrefetching,
    settings,
    exitTVMode,
    togglePlay,
    nextScene,
    prevScene,
    goToScene,
    showControls,
    hideControls,
    setShowSettings,
    addScene,
    setPrefetching,
    setPrefetchError,
    setFullscreen,
  } = useTVModeStore();

  const currentScene = useTVModeStore(selectCurrentScene);
  const nextSceneData = useTVModeStore(selectNextScene);
  const sceneDuration = useTVModeStore(selectSceneDuration);
  const isLastScene = useTVModeStore(selectIsLastScene);
  const nextSceneReady = useTVModeStore(selectNextSceneReady);
  const currentImageReady = useTVModeStore(selectCurrentSceneImageReady);
  const isWaitingForImage = useTVModeStore(selectIsWaitingForImage);

  // Enter fullscreen on mount
  useEffect(() => {
    if (isActive && containerRef.current) {
      const enterFullscreen = async () => {
        try {
          await containerRef.current?.requestFullscreen();
          setFullscreen(true);
        } catch (err) {
          console.warn("Could not enter fullscreen:", err);
        }
      };
      enterFullscreen();
    }

    return () => {
      if (document.fullscreenElement) {
        document.exitFullscreen().catch(() => {});
      }
    };
  }, [isActive, setFullscreen]);

  // Handle fullscreen change
  useEffect(() => {
    const handleFullscreenChange = () => {
      if (!document.fullscreenElement && isActive) {
        setFullscreen(false);
      }
    };

    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => {
      document.removeEventListener("fullscreenchange", handleFullscreenChange);
    };
  }, [isActive, setFullscreen]);

  // Auto-hide controls timer
  const resetControlsTimer = useCallback(() => {
    if (controlsTimerRef.current) {
      clearTimeout(controlsTimerRef.current);
    }
    showControls();

    if (isPlaying && !showSettings) {
      controlsTimerRef.current = window.setTimeout(() => {
        hideControls();
      }, settings.autoHideDelay);
    }
  }, [isPlaying, showSettings, settings.autoHideDelay, showControls, hideControls]);

  // Scene auto-advance timer - only advances when next scene is fully ready
  useEffect(() => {
    if (sceneTimerRef.current) {
      clearTimeout(sceneTimerRef.current);
      sceneTimerRef.current = null;
    }

    // Don't start timer if current scene's image isn't ready yet
    if (!currentImageReady && currentScene) {
      return;
    }

    if (isPlaying && currentScene && !showEndScreen) {
      sceneTimerRef.current = window.setTimeout(() => {
        if (isLastScene) {
          // Trigger prefetch for more scenes or show end screen
          if (scenes.length < 24 && !isPrefetching) {
            handlePrefetch();
          } else {
            nextScene(); // This will trigger end screen via the store
          }
        } else if (nextSceneReady) {
          // Only advance if next scene's image is ready
          nextScene();
        }
        // If next scene isn't ready, timer will be reset by the effect
        // and we'll wait for the image to be ready
      }, sceneDuration);
    }

    return () => {
      if (sceneTimerRef.current) {
        clearTimeout(sceneTimerRef.current);
      }
    };
  }, [isPlaying, currentSceneIndex, currentScene, sceneDuration, isLastScene, showEndScreen, nextSceneReady, currentImageReady]);

  // Trigger image generation for current scene if needed
  useEffect(() => {
    if (!currentScene || !onEnsureImage) return;

    const hasImage = Boolean(currentScene.image_url || currentScene.image);
    if (!hasImage && (currentScene.imageStatus === "pending" || currentScene.imageStatus === "generating")) {
      onEnsureImage(currentScene);
    }
  }, [currentScene?.idx, currentScene?.imageStatus, onEnsureImage]);

  // Trigger image generation for next scene (prefetch image while current scene plays)
  useEffect(() => {
    if (!nextSceneData || !onEnsureImage) return;

    const hasImage = Boolean(nextSceneData.image_url || nextSceneData.image);
    if (!hasImage && (nextSceneData.imageStatus === "pending" || nextSceneData.imageStatus === "generating")) {
      onEnsureImage(nextSceneData);
    }
  }, [nextSceneData?.idx, nextSceneData?.imageStatus, onEnsureImage]);

  // Prefetch next scene
  const handlePrefetch = useCallback(async () => {
    if (prefetchInFlightRef.current || isPrefetching || scenes.length >= 24) return;

    prefetchInFlightRef.current = true;
    setPrefetching(true);
    setPrefetchError(null);

    try {
      const newScene = await onGenerateNext();
      if (newScene) {
        addScene(newScene);
      }
    } catch (error: any) {
      setPrefetchError(error.message || "Failed to generate next scene");
    } finally {
      setPrefetching(false);
      prefetchInFlightRef.current = false;
    }
  }, [isPrefetching, scenes.length, onGenerateNext, addScene, setPrefetching, setPrefetchError]);

  // Trigger prefetch when playing and near end
  useEffect(() => {
    if (isPlaying && isLastScene && scenes.length < 24 && !isPrefetching) {
      handlePrefetch();
    }
  }, [isPlaying, isLastScene, scenes.length, isPrefetching, handlePrefetch]);

  // Keyboard controls
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't handle if settings panel is open and it's an input
      if (showSettings && e.target instanceof HTMLInputElement) return;

      switch (e.key) {
        case "Escape":
          if (showSettings) {
            setShowSettings(false);
          } else {
            exitTVMode();
          }
          break;
        case " ":
          e.preventDefault();
          togglePlay();
          resetControlsTimer();
          break;
        case "ArrowRight":
        case "l":
        case "L":
          nextScene();
          resetControlsTimer();
          break;
        case "ArrowLeft":
        case "j":
        case "J":
          prevScene();
          resetControlsTimer();
          break;
        case "f":
        case "F":
          if (document.fullscreenElement) {
            document.exitFullscreen();
          } else {
            containerRef.current?.requestFullscreen();
          }
          break;
        default:
          resetControlsTimer();
      }
    };

    if (isActive) {
      window.addEventListener("keydown", handleKeyDown);
    }

    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isActive, showSettings, exitTVMode, togglePlay, nextScene, prevScene, resetControlsTimer, setShowSettings]);

  // Mouse/touch handlers
  const handleMouseMove = useCallback(() => {
    resetControlsTimer();
  }, [resetControlsTimer]);

  const handleClick = useCallback((e: React.MouseEvent) => {
    // Don't toggle if clicking on controls
    if ((e.target as HTMLElement).closest(".tv-controls")) return;
    resetControlsTimer();
  }, [resetControlsTimer]);

  // Touch swipe handling
  const touchStartX = useRef(0);
  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    touchStartX.current = e.touches[0].clientX;
  }, []);

  const handleTouchEnd = useCallback((e: React.TouchEvent) => {
    const deltaX = e.changedTouches[0].clientX - touchStartX.current;
    const minSwipeDistance = 50;

    if (Math.abs(deltaX) > minSwipeDistance) {
      if (deltaX > 0) {
        prevScene();
      } else {
        nextScene();
      }
    }
    resetControlsTimer();
  }, [prevScene, nextScene, resetControlsTimer]);

  if (!isActive) return null;

  return (
    <div
      ref={containerRef}
      className="tv-mode-container"
      onMouseMove={handleMouseMove}
      onClick={handleClick}
      onTouchStart={handleTouchStart}
      onTouchEnd={handleTouchEnd}
    >
      <TVModePlayer
        scene={currentScene}
        isTransitioning={false}
        transitionDuration={settings.transitionDuration}
        isImageLoading={!currentImageReady || isWaitingForImage}
        isPrefetching={isPrefetching}
      />

      <TVModeControls
        visible={controlsVisible}
        isPlaying={isPlaying}
        currentIndex={currentSceneIndex}
        totalScenes={scenes.length}
        isPrefetching={isPrefetching}
        isWaitingForNextImage={!isLastScene && !nextSceneReady && isPlaying}
        onTogglePlay={togglePlay}
        onPrev={prevScene}
        onNext={() => {
          if (isLastScene && scenes.length < 24) {
            handlePrefetch();
          }
          nextScene();
        }}
        onExit={exitTVMode}
        onGoToScene={goToScene}
        onShowSettings={() => setShowSettings(true)}
      />

      {showSettings && (
        <TVModeSettings onClose={() => setShowSettings(false)} />
      )}

      {showEndScreen && (
        <TVModeEndScreen
          onRestart={() => goToScene(0)}
          onExit={exitTVMode}
          onContinue={scenes.length < 24 ? handlePrefetch : undefined}
        />
      )}

      <style>{`
        .tv-mode-container {
          position: fixed;
          inset: 0;
          background: #000;
          z-index: 9999;
          display: flex;
          flex-direction: column;
          user-select: none;
          overflow: hidden;
        }

        @media (prefers-reduced-motion: reduce) {
          .tv-mode-container * {
            animation: none !important;
            transition: none !important;
          }
        }
      `}</style>
    </div>
  );
};

export default TVModeContainer;
