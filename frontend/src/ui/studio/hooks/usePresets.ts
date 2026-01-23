import { useState, useEffect, useCallback } from "react";
import type { Preset, SamplerSettings } from "../components";

interface PresetsResponse {
  presets: Preset[];
  mature_mode_enabled: boolean;
}

interface ApplyPresetResult {
  positive: string;
  negative: string;
  sampler_settings: SamplerSettings | null;
  applied: boolean;
  blocked: boolean;
  block_reason: string | null;
  preset_label?: string;
  recommended_models?: string[];
  safety_guidelines?: string[];
}

/**
 * Hook for managing generation presets
 */
export function usePresets() {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [animePresets, setAnimePresets] = useState<Preset[]>([]);
  const [matureEnabled, setMatureEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Fetch all presets
  const fetchPresets = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/studio/presets");
      if (!res.ok) throw new Error("Failed to fetch presets");
      const data: PresetsResponse = await res.json();
      setPresets(data.presets || []);
      setMatureEnabled(data.mature_mode_enabled || false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, []);

  // Fetch anime-specific presets
  const fetchAnimePresets = useCallback(async () => {
    try {
      const res = await fetch("/studio/presets/anime");
      if (!res.ok) throw new Error("Failed to fetch anime presets");
      const data = await res.json();
      setAnimePresets(data.presets || []);
    } catch (e) {
      console.error("Failed to fetch anime presets:", e);
    }
  }, []);

  // Apply a preset to a prompt
  const applyPreset = useCallback(
    async (
      prompt: string,
      presetId: string,
      contentRating: "sfw" | "mature"
    ): Promise<ApplyPresetResult> => {
      const res = await fetch(
        `/studio/presets/apply?content_rating=${contentRating}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ prompt, preset_id: presetId }),
        }
      );

      if (!res.ok) {
        throw new Error("Failed to apply preset");
      }

      return res.json();
    },
    []
  );

  // Get preset by ID
  const getPreset = useCallback(
    (presetId: string): Preset | undefined => {
      return presets.find((p) => p.id === presetId);
    },
    [presets]
  );

  // Initial fetch
  useEffect(() => {
    fetchPresets();
    fetchAnimePresets();
  }, [fetchPresets, fetchAnimePresets]);

  return {
    presets,
    animePresets,
    matureEnabled,
    loading,
    error,
    fetchPresets,
    applyPreset,
    getPreset,
  };
}
