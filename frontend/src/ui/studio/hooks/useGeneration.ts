import { useState, useCallback } from "react";
import type { GenerationSettings } from "../components";

interface GenerationResult {
  id: string;
  imageUrl: string;
  prompt: string;
  negativePrompt: string;
  settings: GenerationSettings;
  contentRating: "sfw" | "mature";
  timestamp: number;
}

interface GenerationProgress {
  step: number;
  totalSteps: number;
  percentage: number;
}

/**
 * Hook for image generation workflow
 */
export function useGeneration() {
  const [isGenerating, setIsGenerating] = useState(false);
  const [progress, setProgress] = useState<GenerationProgress | null>(null);
  const [lastResult, setLastResult] = useState<GenerationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<GenerationResult[]>([]);

  // Generate image via ComfyUI
  const generate = useCallback(
    async (
      prompt: string,
      negativePrompt: string,
      settings: GenerationSettings,
      contentRating: "sfw" | "mature"
    ): Promise<GenerationResult | null> => {
      setIsGenerating(true);
      setError(null);
      setProgress({ step: 0, totalSteps: settings.steps, percentage: 0 });

      try {
        // Build ComfyUI workflow request
        const workflow = {
          prompt: {
            positive: prompt,
            negative: negativePrompt,
          },
          settings: {
            model: settings.model,
            width: settings.width,
            height: settings.height,
            steps: settings.steps,
            cfg_scale: settings.cfg,
            sampler: settings.sampler,
            clip_skip: settings.clipSkip,
            seed: settings.seed === "random" ? -1 : settings.seed,
          },
        };

        // In real implementation, this would call ComfyUI API
        // For now, simulate generation with progress updates
        const totalSteps = settings.steps;
        for (let step = 1; step <= totalSteps; step++) {
          await new Promise((resolve) => setTimeout(resolve, 80));
          setProgress({
            step,
            totalSteps,
            percentage: Math.round((step / totalSteps) * 100),
          });
        }

        // Simulate result
        const result: GenerationResult = {
          id: `gen_${Date.now()}`,
          imageUrl: `/api/generated/${Date.now()}.png`,
          prompt,
          negativePrompt,
          settings,
          contentRating,
          timestamp: Date.now(),
        };

        setLastResult(result);
        setHistory((prev) => [result, ...prev].slice(0, 100)); // Keep last 100

        return result;
      } catch (e) {
        const errorMsg = e instanceof Error ? e.message : "Generation failed";
        setError(errorMsg);
        return null;
      } finally {
        setIsGenerating(false);
        setProgress(null);
      }
    },
    []
  );

  // Generate variations of an existing image
  const generateVariations = useCallback(
    async (
      baseResult: GenerationResult,
      count: number = 4
    ): Promise<GenerationResult[]> => {
      const variations: GenerationResult[] = [];

      for (let i = 0; i < count; i++) {
        const variationSettings = {
          ...baseResult.settings,
          seed: Math.floor(Math.random() * 2147483647),
        };

        const result = await generate(
          baseResult.prompt,
          baseResult.negativePrompt,
          variationSettings,
          baseResult.contentRating
        );

        if (result) {
          variations.push(result);
        }
      }

      return variations;
    },
    [generate]
  );

  // Upscale an image (placeholder)
  const upscale = useCallback(
    async (
      imageUrl: string,
      scale: number = 2
    ): Promise<string | null> => {
      setIsGenerating(true);
      try {
        // Simulate upscale
        await new Promise((resolve) => setTimeout(resolve, 2000));
        return `${imageUrl}?upscaled=${scale}x`;
      } catch (e) {
        setError("Upscale failed");
        return null;
      } finally {
        setIsGenerating(false);
      }
    },
    []
  );

  // Clear history
  const clearHistory = useCallback(() => {
    setHistory([]);
    setLastResult(null);
  }, []);

  // Delete from history
  const deleteFromHistory = useCallback((id: string) => {
    setHistory((prev) => prev.filter((item) => item.id !== id));
    setLastResult((prev) => (prev?.id === id ? null : prev));
  }, []);

  return {
    isGenerating,
    progress,
    lastResult,
    error,
    history,
    generate,
    generateVariations,
    upscale,
    clearHistory,
    deleteFromHistory,
  };
}
