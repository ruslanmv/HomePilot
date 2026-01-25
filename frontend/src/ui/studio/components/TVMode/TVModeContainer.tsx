import React, { useEffect, useRef, useCallback, useState } from "react";
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
import { TVModeChapterTransition } from "./TVModeChapterTransition";
import { useTTSPlayback } from "../../hooks/useTTSPlayback";

interface ChapterData {
  sessionId: string;
  title: string;
  chapterNumber: number;
  scenes: TVScene[];
}

interface TVModeContainerProps {
  onGenerateNext: () => Promise<any>;
  onEnsureImage?: (scene: TVScene) => void;
  onContinueChapter?: () => Promise<ChapterData | null>;
  onSyncOutline?: () => Promise<void>;
}

export const TVModeContainer: React.FC<TVModeContainerProps> = ({
  onGenerateNext,
  onEnsureImage,
  onContinueChapter,
  onSyncOutline,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const controlsTimerRef = useRef<number | null>(null);
  const sceneTimerRef = useRef<number | null>(null);
  const prefetchInFlightRef = useRef(false);
  const [showChapterTransition, setShowChapterTransition] = useState(false);
  const [waitingForTTS, setWaitingForTTS] = useState(false);
  const [waitingForNextScene, setWaitingForNextScene] = useState(false);

  const {
    isActive,
    isPlaying,
    currentSceneIndex,
    scenes,
    controlsVisible,
    showSettings,
    showEndScreen,
    isPrefetching,
    isStoryComplete,
    isLoadingNextChapter,
    chapterNumber,
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
    setLoadingNextChapter,
    startNextChapter,
  } = useTVModeStore();

  const currentScene = useTVModeStore(selectCurrentScene);
  const nextSceneData = useTVModeStore(selectNextScene);
  const sceneDuration = useTVModeStore(selectSceneDuration);
  const isLastScene = useTVModeStore(selectIsLastScene);
  const nextSceneReady = useTVModeStore(selectNextSceneReady);
  const currentImageReady = useTVModeStore(selectCurrentSceneImageReady);
  const isWaitingForImage = useTVModeStore(selectIsWaitingForImage);

  // Callback when TTS finishes speaking a scene - advance when next scene is ready
  // TTS drives continuous narration, but waits for next scene (content + image) before advancing
  const handleSceneNarrationEnd = useCallback(() => {
    console.log("[TV Mode] TTS narration finished for current scene");
    setWaitingForTTS(false);

    if (isLastScene) {
      // On last scene - check if we should generate more or end
      if (scenes.length < 24 && !isPrefetching && !isStoryComplete && settings.autoGenerateScenes) {
        // More scenes can be generated - set waiting state, prefetch effect will handle generation
        console.log("[TV Mode] Last scene finished, waiting for new scene generation...");
        setWaitingForNextScene(true);
      } else if (!isStoryComplete && !isPrefetching) {
        nextScene(); // This will trigger end screen
      }
    } else if (nextSceneReady) {
      // Next scene is ready (content + image) - advance immediately
      console.log("[TV Mode] Next scene ready, advancing...");
      setWaitingForNextScene(false);
      nextScene();
    } else {
      // Next scene exists but not ready yet - wait for it
      console.log("[TV Mode] Waiting for next scene to be ready (image generating)...");
      setWaitingForNextScene(true);
    }
  }, [isLastScene, scenes.length, isPrefetching, isStoryComplete, nextSceneReady, nextScene, settings.autoGenerateScenes]);

  // TTS Playback Integration
  const {
    ttsEnabled,
    setTTSEnabled,
    isSpeaking,
    isPaused: ttsPaused,
    isSupported: ttsSupported,
    voices,
    voiceConfig,
    setVoiceConfig,
    stopSpeaking,
    pauseSpeaking,
    resumeSpeaking,
  } = useTTSPlayback({
    isActive,
    isPlaying,
    currentScene,
    currentSceneIndex,
    scenes,
    onSceneNarrationEnd: handleSceneNarrationEnd,
  });

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

  // Track when TTS starts speaking to set waitingForTTS
  useEffect(() => {
    if (ttsEnabled && isSpeaking && currentScene?.narration) {
      setWaitingForTTS(true);
    }
  }, [ttsEnabled, isSpeaking, currentScene?.narration]);

  // Reset waitingForTTS when scene changes, TTS disabled, or playback stops
  useEffect(() => {
    if (!ttsEnabled || !isPlaying) {
      setWaitingForTTS(false);
    }
  }, [ttsEnabled, isPlaying]);

  // Reset waitingForTTS when scene changes (new scene means new narration)
  useEffect(() => {
    setWaitingForTTS(false);
  }, [currentSceneIndex]);

  // Reset waitingForNextScene when scene changes
  useEffect(() => {
    setWaitingForNextScene(false);
  }, [currentSceneIndex]);

  // Advance to next scene when it becomes ready (while we're waiting for it)
  useEffect(() => {
    if (!waitingForNextScene || !isPlaying) return;

    if (nextSceneReady) {
      // Next scene is now ready - advance!
      console.log("[TV Mode] Next scene now ready, advancing...");
      setWaitingForNextScene(false);
      nextScene();
    }
  }, [waitingForNextScene, nextSceneReady, isPlaying, nextScene]);

  // Scene auto-advance timer - TTS drives the flow when enabled, timer only for non-TTS mode
  useEffect(() => {
    if (sceneTimerRef.current) {
      clearTimeout(sceneTimerRef.current);
      sceneTimerRef.current = null;
    }

    // Don't start timer if story is complete or chapter transition is showing
    if (isStoryComplete || showChapterTransition) {
      return;
    }

    // When TTS is enabled, let TTS drive scene advancement (via onSceneNarrationEnd callback)
    // TTS finishes speaking, then waits for next scene to be ready before advancing
    if (ttsEnabled && currentScene?.narration) {
      // TTS is controlling the flow - it will call onSceneNarrationEnd when done
      if (isSpeaking || waitingForTTS) {
        console.log("[TV Mode] TTS driving flow, narration in progress...");
        return;
      }
      // Waiting for next scene to be ready (image generating)
      if (waitingForNextScene) {
        console.log("[TV Mode] TTS finished, waiting for next scene to be ready...");
        return;
      }
      // TTS enabled but not speaking yet - let auto-speak effect handle it
      return;
    }

    // Non-TTS mode: use timer and wait for images
    // Don't start timer if current scene's image isn't ready yet (visual-first mode)
    if (!currentImageReady && currentScene) {
      return;
    }

    if (isPlaying && currentScene && !showEndScreen) {
      sceneTimerRef.current = window.setTimeout(() => {
        if (isLastScene) {
          // Only auto-generate if setting is enabled
          if (scenes.length < 24 && !isPrefetching && !isStoryComplete && settings.autoGenerateScenes) {
            // Trigger prefetch for more scenes
            handlePrefetch();
          } else if (!isStoryComplete && !isPrefetching) {
            // Only advance to end screen if not prefetching and story not complete
            nextScene(); // This will trigger end screen via the store
          }
          // If story is complete or prefetching, wait - chapter transition or prefetch will handle it
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
  // eslint-disable-next-line react-hooks/exhaustive-deps -- handlePrefetch and nextScene are stable callbacks
  }, [isPlaying, currentSceneIndex, currentScene, sceneDuration, isLastScene, showEndScreen, nextSceneReady, currentImageReady, isStoryComplete, showChapterTransition, isPrefetching, scenes.length, ttsEnabled, isSpeaking, waitingForTTS, waitingForNextScene, settings.autoGenerateScenes]);

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
    // Don't prefetch if story is already complete or at max scenes
    if (prefetchInFlightRef.current || isPrefetching || isStoryComplete || scenes.length >= 24) return;

    prefetchInFlightRef.current = true;
    setPrefetching(true);
    setPrefetchError(null);

    try {
      console.log("[TV Mode] Starting scene generation...");
      const newScene = await onGenerateNext();
      if (newScene) {
        addScene(newScene);
        console.log("[TV Mode] New scene generated successfully:", newScene.idx);

        // Sync outline after successful scene generation
        if (onSyncOutline) {
          try {
            await onSyncOutline();
            console.log("[TV Mode] Outline synced after scene generation");
          } catch (syncError) {
            console.warn("[TV Mode] Failed to sync outline:", syncError);
          }
        }
      }
      // If null returned, story is complete (handled by caller)
    } catch (error: any) {
      console.error("[TV Mode] Scene generation failed:", error);
      setPrefetchError(error.message || "Failed to generate next scene");
    } finally {
      setPrefetching(false);
      prefetchInFlightRef.current = false;
    }
  }, [isPrefetching, isStoryComplete, scenes.length, onGenerateNext, addScene, setPrefetching, setPrefetchError, onSyncOutline]);

  // Trigger prefetch when playing and near end (but not if story is complete or auto-generate is disabled)
  useEffect(() => {
    if (isPlaying && isLastScene && scenes.length < 24 && !isPrefetching && !isStoryComplete && settings.autoGenerateScenes) {
      handlePrefetch();
    }
  }, [isPlaying, isLastScene, scenes.length, isPrefetching, isStoryComplete, handlePrefetch, settings.autoGenerateScenes]);

  // Show chapter transition when story is complete (saga mode)
  useEffect(() => {
    if (!isStoryComplete || !settings.sagaMode || !onContinueChapter) {
      setShowChapterTransition(false);
      return;
    }

    // Only show transition when we're on the last scene
    if (!isLastScene) {
      setShowChapterTransition(false);
      return;
    }

    // Show the chapter transition screen with countdown
    setShowChapterTransition(true);
  }, [isStoryComplete, settings.sagaMode, isLastScene, onContinueChapter]);

  // Handle continuing to next chapter (called from transition screen)
  const handleContinueToNextChapter = useCallback(async () => {
    if (!onContinueChapter || isLoadingNextChapter) return;

    console.log(`[TV Mode] Chapter ${chapterNumber} complete, loading next chapter...`);
    setLoadingNextChapter(true);

    try {
      const chapterData = await onContinueChapter();
      if (chapterData) {
        setShowChapterTransition(false);
        startNextChapter(
          chapterData.sessionId,
          chapterData.title,
          chapterData.scenes,
          chapterData.chapterNumber
        );
        console.log(`[TV Mode] Started chapter ${chapterData.chapterNumber}: ${chapterData.title}`);
      } else {
        // No more chapters available
        setLoadingNextChapter(false);
        setShowChapterTransition(false);
      }
    } catch (error) {
      console.error('[TV Mode] Failed to continue to next chapter:', error);
      setLoadingNextChapter(false);
      setShowChapterTransition(false);
    }
  }, [onContinueChapter, isLoadingNextChapter, chapterNumber, setLoadingNextChapter, startNextChapter]);

  // Handle canceling the chapter transition
  const handleCancelChapterTransition = useCallback(() => {
    setShowChapterTransition(false);
    exitTVMode();
  }, [exitTVMode]);

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
        ttsEnabled={ttsEnabled}
        ttsSupported={ttsSupported}
        isSpeaking={isSpeaking}
        onToggleTTS={() => setTTSEnabled(!ttsEnabled)}
      />

      {showSettings && (
        <TVModeSettings
          onClose={() => setShowSettings(false)}
          ttsEnabled={ttsEnabled}
          setTTSEnabled={setTTSEnabled}
          ttsSupported={ttsSupported}
          voices={voices}
          voiceConfig={voiceConfig}
          setVoiceConfig={setVoiceConfig}
        />
      )}

      {/* Chapter Transition Screen (Saga Mode) */}
      {showChapterTransition && settings.sagaMode && onContinueChapter && (
        <TVModeChapterTransition
          onContinue={handleContinueToNextChapter}
          onCancel={handleCancelChapterTransition}
          nextChapterTitle={`Chapter ${chapterNumber + 1}`}
          countdown={5}
        />
      )}

      {/* End Screen (when not in saga mode or saga mode disabled) */}
      {showEndScreen && !showChapterTransition && (
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
