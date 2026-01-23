import { useState, useCallback, useEffect } from "react";

type ContentRating = "sfw" | "mature";

interface ContentRatingState {
  contentRating: ContentRating;
  matureEnabled: boolean;
  verified: boolean;
}

/**
 * Hook for managing content rating state
 */
export function useContentRating(initialRating: ContentRating = "sfw") {
  const [state, setState] = useState<ContentRatingState>({
    contentRating: initialRating,
    matureEnabled: false,
    verified: false,
  });

  // Check if mature mode is enabled server-side
  const checkMatureEnabled = useCallback(async () => {
    try {
      const res = await fetch("/studio/image/nsfw-info");
      if (res.ok) {
        const data = await res.json();
        setState((prev) => ({
          ...prev,
          matureEnabled: data.nsfw_enabled || false,
        }));
      }
    } catch (e) {
      console.error("Failed to check mature mode:", e);
    }
  }, []);

  // Set content rating (with verification for mature)
  const setContentRating = useCallback(
    (rating: ContentRating, verified: boolean = false) => {
      if (rating === "mature" && !verified) {
        // Require verification for mature mode
        return false;
      }

      setState((prev) => ({
        ...prev,
        contentRating: rating,
        verified: rating === "mature" ? verified : false,
      }));

      // Persist to localStorage
      localStorage.setItem("studio_content_rating", rating);
      if (rating === "mature" && verified) {
        localStorage.setItem("studio_mature_verified", "true");
      }

      return true;
    },
    []
  );

  // Update video content rating via API
  const updateVideoRating = useCallback(
    async (videoId: string, rating: ContentRating): Promise<boolean> => {
      try {
        const res = await fetch(
          `/studio/videos/${videoId}/content-rating?contentRating=${rating}`,
          { method: "PATCH" }
        );
        return res.ok;
      } catch (e) {
        console.error("Failed to update video rating:", e);
        return false;
      }
    },
    []
  );

  // Check verification status
  const checkVerification = useCallback(() => {
    const verified = localStorage.getItem("studio_mature_verified") === "true";
    const savedRating = localStorage.getItem("studio_content_rating") as ContentRating | null;

    if (savedRating && verified) {
      setState((prev) => ({
        ...prev,
        contentRating: savedRating,
        verified,
      }));
    }
  }, []);

  // Clear verification
  const clearVerification = useCallback(() => {
    localStorage.removeItem("studio_mature_verified");
    setState((prev) => ({
      ...prev,
      contentRating: "sfw",
      verified: false,
    }));
  }, []);

  // Initial checks
  useEffect(() => {
    checkMatureEnabled();
    checkVerification();
  }, [checkMatureEnabled, checkVerification]);

  return {
    contentRating: state.contentRating,
    matureEnabled: state.matureEnabled,
    verified: state.verified,
    setContentRating,
    updateVideoRating,
    clearVerification,
    checkMatureEnabled,
  };
}
