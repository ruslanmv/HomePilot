import React, { useState, useEffect, useRef } from "react";
import { useTVModeStore } from "../../stores/tvModeStore";
import type { TVScene } from "./types";
import { resolveFileUrl } from '../../../resolveFileUrl';

interface TVModePlayerProps {
  scene: TVScene | undefined;
  isTransitioning: boolean;
  transitionDuration: number;
  isImageLoading?: boolean;
  isPrefetching?: boolean;
}

export const TVModePlayer: React.FC<TVModePlayerProps> = ({
  scene,
  isTransitioning,
  transitionDuration,
  isImageLoading = false,
  isPrefetching = false,
}) => {
  const { settings, storyTitle, currentSceneIndex, chapterNumber, isLoadingNextChapter } = useTVModeStore();
  const [imageLoaded, setImageLoaded] = useState(false);
  const [displayedScene, setDisplayedScene] = useState(scene);
  const [isAnimating, setIsAnimating] = useState(false);
  const prevSceneRef = useRef<TVScene | undefined>(undefined);

  // Handle scene transitions
  useEffect(() => {
    // Skip animation on initial render (when there's no previous scene)
    if (prevSceneRef.current === undefined && scene) {
      prevSceneRef.current = scene;
      setDisplayedScene(scene);
      setIsAnimating(false);
      return;
    }

    // Animate when scene changes
    if (scene !== prevSceneRef.current && scene) {
      setIsAnimating(true);

      // Wait for transition then update displayed scene
      const timer = setTimeout(() => {
        setDisplayedScene(scene);
        setImageLoaded(false);
        setIsAnimating(false);
        prevSceneRef.current = scene;
      }, transitionDuration / 2);

      return () => clearTimeout(timer);
    }
  }, [scene, transitionDuration]);

  const handleImageLoad = () => {
    setImageLoaded(true);
  };

  const getNarrationSizeClass = () => {
    switch (settings.narrationSize) {
      case "small":
        return "narration-small";
      case "large":
        return "narration-large";
      default:
        return "narration-medium";
    }
  };

  if (!displayedScene) {
    return (
      <div className="tv-player-empty">
        <div className="loading-spinner" />
        <p>Loading story...</p>
        <style>{`
          .tv-player-empty {
            flex: 1;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            color: rgba(255, 255, 255, 0.7);
            gap: 16px;
          }

          .loading-spinner {
            width: 40px;
            height: 40px;
            border: 3px solid rgba(255, 255, 255, 0.2);
            border-top-color: rgba(255, 255, 255, 0.8);
            border-radius: 50%;
            animation: spin 1s linear infinite;
          }

          @keyframes spin {
            to { transform: rotate(360deg); }
          }
        `}</style>
      </div>
    );
  }

  // Get the image URL (could be in image or image_url field)
  const imageUrl = resolveFileUrl(displayedScene?.image_url || displayedScene?.image || '');

  return (
    <div className="tv-player">
      {/* Scene Image */}
      <div className={`scene-image-container ${isAnimating ? "transitioning" : ""}`}>
        {imageUrl ? (
          <img
            src={imageUrl}
            alt={`Scene ${displayedScene.idx + 1}`}
            className={`scene-image ${imageLoaded ? "loaded" : ""}`}
            onLoad={handleImageLoad}
          />
        ) : isImageLoading ? (
          <div className="scene-loading">
            <div className="image-loading-spinner" />
            <p className="loading-text">Generating image...</p>
            <p className="loading-subtext">The story will continue when ready</p>
          </div>
        ) : (
          <div className="scene-placeholder">
            <div className="placeholder-icon">
              <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <rect x="3" y="3" width="18" height="18" rx="2" />
                <circle cx="8.5" cy="8.5" r="1.5" />
                <path d="M21 15l-5-5L5 21" />
              </svg>
            </div>
            <p>Scene {displayedScene.idx + 1}</p>
          </div>
        )}
      </div>

      {/* Narration Text */}
      <div className={`narration-container ${settings.narrationPosition === "top" ? "narration-top" : "narration-bottom"}`}>
        <div className={`narration-text ${getNarrationSizeClass()} ${isAnimating ? "" : "visible"}`}>
          {settings.showSceneNumber && (
            <span className="scene-indicator">
              {chapterNumber > 1 && `Ch.${chapterNumber} · `}Scene {displayedScene.idx + 1}
            </span>
          )}
          <p>{displayedScene.narration}</p>
        </div>
      </div>

      {/* Loading Next Chapter Overlay */}
      {isLoadingNextChapter && (
        <div className="chapter-loading-overlay">
          <div className="chapter-loading-content">
            <div className="loading-spinner" />
            <p className="chapter-loading-title">Chapter {chapterNumber} Complete</p>
            <p className="chapter-loading-subtitle">Loading next chapter...</p>
          </div>
          <style>{`
            .chapter-loading-overlay {
              position: absolute;
              inset: 0;
              background: rgba(0, 0, 0, 0.85);
              display: flex;
              align-items: center;
              justify-content: center;
              z-index: 100;
              animation: fadeIn 0.5s ease-out;
            }
            .chapter-loading-content {
              text-align: center;
              color: white;
            }
            .chapter-loading-title {
              font-size: 24px;
              font-weight: 600;
              margin-top: 20px;
              margin-bottom: 8px;
            }
            .chapter-loading-subtitle {
              font-size: 16px;
              opacity: 0.7;
            }
            @keyframes fadeIn {
              from { opacity: 0; }
              to { opacity: 1; }
            }
          `}</style>
        </div>
      )}

      <style>{`
        .tv-player {
          flex: 1;
          display: flex;
          flex-direction: column;
          position: relative;
          overflow: hidden;
          width: 100%;
          height: 100%;
        }

        .scene-image-container {
          position: absolute;
          inset: 0;
          display: flex;
          align-items: center;
          justify-content: center;
          transition: opacity ${transitionDuration}ms ease-in-out;
        }

        .scene-image-container.transitioning {
          opacity: 0.5;
        }

        .scene-image {
          width: 100%;
          height: 100%;
          object-fit: cover;
          opacity: 0;
          transition: opacity 500ms ease-in-out;
        }

        .scene-image.loaded {
          opacity: 1;
        }

        .scene-placeholder {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          color: rgba(255, 255, 255, 0.4);
          gap: 16px;
        }

        .placeholder-icon {
          opacity: 0.5;
        }

        .scene-loading {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          color: rgba(255, 255, 255, 0.8);
          gap: 16px;
          padding: 40px;
        }

        .image-loading-spinner {
          width: 60px;
          height: 60px;
          border: 4px solid rgba(139, 92, 246, 0.2);
          border-top-color: rgba(139, 92, 246, 0.8);
          border-radius: 50%;
          animation: spin 1s linear infinite;
        }

        .loading-text {
          font-size: 18px;
          font-weight: 500;
          color: rgba(255, 255, 255, 0.9);
          margin: 0;
        }

        .loading-subtext {
          font-size: 14px;
          color: rgba(255, 255, 255, 0.5);
          margin: 0;
        }

        @keyframes spin {
          to { transform: rotate(360deg); }
        }

        .narration-container {
          position: absolute;
          left: 0;
          right: 0;
          padding: 0 5%;
          pointer-events: none;
          z-index: 10;
        }

        .narration-top {
          top: 60px;
        }

        .narration-bottom {
          bottom: 120px;
        }

        .narration-text {
          background: rgba(0, 0, 0, 0.75);
          backdrop-filter: blur(8px);
          -webkit-backdrop-filter: blur(8px);
          padding: 20px 28px;
          border-radius: 12px;
          max-width: 900px;
          margin: 0 auto;
          text-align: center;
          opacity: 0;
          transform: translateY(20px);
          transition: opacity 600ms ease-out, transform 600ms ease-out;
          box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
        }

        .narration-text.visible {
          opacity: 1;
          transform: translateY(0);
        }

        .narration-small p {
          font-size: 16px;
          line-height: 1.6;
        }

        .narration-medium p {
          font-size: 20px;
          line-height: 1.7;
        }

        .narration-large p {
          font-size: 24px;
          line-height: 1.8;
        }

        .narration-text p {
          color: #fff;
          margin: 0;
          text-shadow: 0 1px 3px rgba(0, 0, 0, 0.5);
        }

        .scene-indicator {
          display: block;
          font-size: 12px;
          text-transform: uppercase;
          letter-spacing: 2px;
          color: rgba(255, 255, 255, 0.7);
          margin-bottom: 10px;
        }

        @media (max-width: 768px) {
          .narration-container {
            padding: 0 16px;
          }

          .narration-text {
            padding: 16px 20px;
          }

          .narration-small p { font-size: 14px; }
          .narration-medium p { font-size: 16px; }
          .narration-large p { font-size: 18px; }

          .narration-bottom {
            bottom: 100px;
          }
        }
      `}</style>
    </div>
  );
};

export default TVModePlayer;
