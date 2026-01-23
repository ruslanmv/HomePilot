import { useState, useEffect, useCallback } from "react";
import type { Model } from "../components";

interface ModelsResponse {
  models: Model[];
}

/**
 * Hook for fetching and managing image generation models
 */
export function useModels(contentRating: "sfw" | "mature" = "sfw") {
  const [models, setModels] = useState<Model[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloadingModels, setDownloadingModels] = useState<Set<string>>(
    new Set()
  );

  // Fetch models from catalog
  const fetchModels = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Fetch from model catalog API
      const res = await fetch("/api/models?provider=comfyui&type=image");
      if (!res.ok) throw new Error("Failed to fetch models");

      const data: ModelsResponse = await res.json();

      // Add downloaded status (would check against local storage or API)
      const modelsWithStatus = data.models.map((model) => ({
        ...model,
        downloaded: checkModelDownloaded(model.id),
      }));

      setModels(modelsWithStatus);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      // Fallback to hardcoded list
      setModels(getDefaultModels());
    } finally {
      setLoading(false);
    }
  }, []);

  // Filter models based on content rating
  const filteredModels = models.filter((model) => {
    if (contentRating === "sfw") {
      return !model.nsfw;
    }
    return true; // In mature mode, show all
  });

  // Get anime models only
  const animeModels = models.filter((model) => model.anime);

  // Get NSFW models only
  const nsfwModels = models.filter((model) => model.nsfw);

  // Get recommended NSFW models
  const recommendedNsfwModels = models.filter((model) => model.recommended_nsfw);

  // Download a model
  const downloadModel = useCallback(async (modelId: string): Promise<boolean> => {
    setDownloadingModels((prev) => new Set(prev).add(modelId));

    try {
      const res = await fetch("/api/models/download", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model_id: modelId }),
      });

      if (!res.ok) throw new Error("Download failed");

      // Update model status
      setModels((prev) =>
        prev.map((m) => (m.id === modelId ? { ...m, downloaded: true } : m))
      );

      return true;
    } catch (e) {
      console.error("Model download failed:", e);
      return false;
    } finally {
      setDownloadingModels((prev) => {
        const next = new Set(prev);
        next.delete(modelId);
        return next;
      });
    }
  }, []);

  // Check if model is downloaded (from localStorage for now)
  const isModelDownloaded = useCallback((modelId: string): boolean => {
    return checkModelDownloaded(modelId);
  }, []);

  // Get model by ID
  const getModel = useCallback(
    (modelId: string): Model | undefined => {
      return models.find((m) => m.id === modelId);
    },
    [models]
  );

  // Initial fetch
  useEffect(() => {
    fetchModels();
  }, [fetchModels]);

  return {
    models,
    filteredModels,
    animeModels,
    nsfwModels,
    recommendedNsfwModels,
    loading,
    error,
    downloadingModels,
    fetchModels,
    downloadModel,
    isModelDownloaded,
    getModel,
  };
}

// Helper: Check if model is downloaded
function checkModelDownloaded(modelId: string): boolean {
  const downloaded = localStorage.getItem("downloaded_models");
  if (!downloaded) return false;
  try {
    const list = JSON.parse(downloaded) as string[];
    return list.includes(modelId);
  } catch {
    return false;
  }
}

// Helper: Default models when API fails
function getDefaultModels(): Model[] {
  return [
    {
      id: "abyssOrangeMix3_aom3a1b.safetensors",
      label: "AbyssOrangeMix3 (AOM3)",
      description:
        "Premier SD 1.5 anime model. Excellent for fan service, ecchi, and mature anime content.",
      size_gb: 2.13,
      resolution: "512x512",
      nsfw: true,
      recommended_nsfw: true,
      anime: true,
      downloaded: false,
    },
    {
      id: "counterfeit_v30.safetensors",
      label: "Counterfeit V3.0",
      description:
        "High-quality anime model with vibrant colors. Great for detailed character art.",
      size_gb: 2.13,
      resolution: "512x512",
      nsfw: true,
      anime: true,
      downloaded: false,
    },
    {
      id: "anything_v5PrtRE.safetensors",
      label: "Anything V5 (Prt-RE)",
      description:
        "Versatile anime model for all styles. Supports NSFW content.",
      size_gb: 4.27,
      resolution: "512x512",
      nsfw: true,
      anime: true,
      downloaded: false,
    },
    {
      id: "sd_xl_base_1.0.safetensors",
      label: "SDXL Base 1.0",
      description:
        "Stable Diffusion XL base model. Best balance of quality and speed.",
      size_gb: 6.94,
      resolution: "1024x1024",
      nsfw: false,
      downloaded: false,
    },
    {
      id: "dreamshaper_8.safetensors",
      label: "DreamShaper 8",
      description: "Versatile model for artistic and realistic styles.",
      size_gb: 2.13,
      resolution: "512x512",
      nsfw: true,
      recommended_nsfw: true,
      downloaded: false,
    },
  ];
}
