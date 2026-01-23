import React, { useState, useEffect, useRef } from "react";
import { useTVModeStore } from "../../stores/tvModeStore";
import type { TVScene } from "./types";

interface TVModePlayerProps {
  scene: TVScene | undefined;
  isTransitioning: boolean;
  transitionDuration: number;
}

export const TVModePlayer: React.FC<TVModePlayerProps> = ({
  scene,
  isTransitioning,
  transitionDuration,
}) => {
  const { settings, storyTitle, currentSceneIndex } = useTVModeStore();
  const [imageLoaded, setImageLoaded] = useState(false);
  const [displayedScene, setDisplayedScene] = useState(scene);
  const [isAnimating, setIsAnimating] = useState(false);
  const prevSceneRef = useRef<TVScene | undefined>(undefined);

  // Handle scene transitions
  useEffect(() => {
    if (scene !== prevSceneRef.current) {
      setIsAnimating(true);

      // Wait for transition then update displayed scene
      const timer = setTimeout(() => {
        setDisplayedScene(scene);
        setImageLoaded(false);
        setIsAnimating(false);
      }, transitionDuration / 2);

      prevSceneRef.current = scene;
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

  return (
    <div className="tv-player">
      {/* Scene Image */}
      <div className={`scene-image-container ${isAnimating ? "transitioning" : ""}`}>
        {displayedScene.image ? (
          <img
            src={displayedScene.image}
            alt={`Scene ${displayedScene.idx + 1}`}
            className={`scene-image ${imageLoaded ? "loaded" : ""}`}
            onLoad={handleImageLoad}
          />
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
            <span className="scene-indicator">Scene {displayedScene.idx + 1}</span>
          )}
          <p>{displayedScene.narration}</p>
        </div>
      </div>

      <style>{`
        .tv-player {
          flex: 1;
          display: flex;
          flex-direction: column;
          position: relative;
          overflow: hidden;
        }

        .scene-image-container {
          flex: 1;
          display: flex;
          align-items: center;
          justify-content: center;
          position: relative;
          transition: opacity ${transitionDuration}ms ease-in-out;
        }

        .scene-image-container.transitioning {
          opacity: 0.5;
        }

        .scene-image {
          max-width: 100%;
          max-height: 100%;
          object-fit: contain;
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

        .narration-container {
          position: absolute;
          left: 0;
          right: 0;
          padding: 0 5%;
          pointer-events: none;
        }

        .narration-top {
          top: 80px;
        }

        .narration-bottom {
          bottom: 100px;
        }

        .narration-text {
          background: linear-gradient(
            to bottom,
            rgba(0, 0, 0, 0) 0%,
            rgba(0, 0, 0, 0.8) 10%,
            rgba(0, 0, 0, 0.8) 90%,
            rgba(0, 0, 0, 0) 100%
          );
          padding: 24px 32px;
          border-radius: 8px;
          max-width: 900px;
          margin: 0 auto;
          text-align: center;
          opacity: 0;
          transform: translateY(20px);
          transition: opacity 600ms ease-out, transform 600ms ease-out;
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
          text-shadow: 0 2px 4px rgba(0, 0, 0, 0.5);
        }

        .scene-indicator {
          display: block;
          font-size: 12px;
          text-transform: uppercase;
          letter-spacing: 2px;
          color: rgba(255, 255, 255, 0.6);
          margin-bottom: 8px;
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
            bottom: 80px;
          }
        }
      `}</style>
    </div>
  );
};

export default TVModePlayer;
