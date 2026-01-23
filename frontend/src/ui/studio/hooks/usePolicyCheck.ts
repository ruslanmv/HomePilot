import { useState, useCallback, useEffect, useRef } from "react";
import type { PolicyResult } from "../components";
import { studioFetch, studioPost } from "../lib/api";

interface ImagePolicyResult extends PolicyResult {
  content_rating: string;
  nsfw_enabled: boolean;
  policy_type: string;
  explicit_allowed: boolean;
  info?: {
    sfw: string;
    mature: string;
  };
}

interface NSFWInfo {
  nsfw_enabled: boolean;
  env_var: string;
  current_value: string;
  when_enabled: Record<string, string>;
  always_blocked: Record<string, string>;
  recommended_models: string[];
  how_to_enable: string;
}

/**
 * Hook for real-time policy checking
 */
export function usePolicyCheck(debounceMs: number = 300) {
  const [policyResult, setPolicyResult] = useState<ImagePolicyResult | null>(
    null
  );
  const [checking, setChecking] = useState(false);
  const [nsfwInfo, setNsfwInfo] = useState<NSFWInfo | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Fetch NSFW info
  const fetchNSFWInfo = useCallback(async () => {
    try {
      const data = await studioFetch<NSFWInfo>("/studio/image/nsfw-info");
      setNsfwInfo(data);
    } catch (e) {
      console.error("Failed to fetch NSFW info:", e);
    }
  }, []);

  // Check image policy
  const checkImagePolicy = useCallback(
    async (
      prompt: string,
      contentRating: "sfw" | "mature",
      provider: string = "comfyui"
    ): Promise<ImagePolicyResult | null> => {
      if (!prompt.trim()) {
        setPolicyResult(null);
        return null;
      }

      setChecking(true);
      try {
        const params = new URLSearchParams({
          prompt,
          content_rating: contentRating,
          provider,
        });

        const result = await studioFetch<ImagePolicyResult>(
          `/studio/image/policy-check?${params}`,
          { method: "POST" }
        );
        setPolicyResult(result);
        return result;
      } catch (e) {
        console.error("Policy check error:", e);
        return null;
      } finally {
        setChecking(false);
      }
    },
    []
  );

  // Debounced policy check
  const debouncedCheck = useCallback(
    (
      prompt: string,
      contentRating: "sfw" | "mature",
      provider: string = "comfyui"
    ) => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }

      debounceRef.current = setTimeout(() => {
        checkImagePolicy(prompt, contentRating, provider);
      }, debounceMs);
    },
    [checkImagePolicy, debounceMs]
  );

  // Check text/story policy (for video context)
  const checkStoryPolicy = useCallback(
    async (
      videoId: string,
      prompt: string,
      provider: string = "ollama"
    ): Promise<PolicyResult | null> => {
      try {
        return await studioPost<PolicyResult>(
          `/studio/videos/${videoId}/policy/check`,
          { prompt, provider }
        );
      } catch (e) {
        console.error("Story policy check error:", e);
        return null;
      }
    },
    []
  );

  // Clear policy result
  const clearPolicy = useCallback(() => {
    setPolicyResult(null);
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
    };
  }, []);

  // Fetch NSFW info on mount
  useEffect(() => {
    fetchNSFWInfo();
  }, [fetchNSFWInfo]);

  return {
    policyResult,
    checking,
    nsfwInfo,
    checkImagePolicy,
    debouncedCheck,
    checkStoryPolicy,
    clearPolicy,
    fetchNSFWInfo,
  };
}
