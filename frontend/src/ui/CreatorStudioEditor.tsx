import React, { useEffect, useState, useCallback } from "react";
import {
  ArrowLeft,
  Play,
  Pause,
  ChevronLeft,
  ChevronRight,
  Plus,
  RefreshCw,
  Check,
  Loader2,
  ImageIcon,
  Tv,
} from "lucide-react";
import { useTVModeStore } from "./studio/stores/tvModeStore";
import type { TVScene } from "./studio/stores/tvModeStore";
import { TVModeContainer } from "./studio/components/TVMode/TVModeContainer";

// Types
type SceneStatus = "pending" | "generating" | "ready" | "error";

type Scene = {
  id: string;
  videoId: string;
  idx: number;
  narration: string;
  imagePrompt: string;
  negativePrompt: string;
  imageUrl: string | null;
  audioUrl: string | null;
  status: SceneStatus;
  durationSec: number;
  createdAt: number;
  updatedAt: number;
};

type Project = {
  id: string;
  title: string;
  logline: string;
  status: "draft" | "in_review" | "approved" | "archived";
  platformPreset: string;
  contentRating: "sfw" | "mature";
  createdAt: number;
  updatedAt: number;
};

interface CreatorStudioEditorProps {
  projectId: string;
  backendUrl: string;
  apiKey?: string;
  onExit: () => void;
  /** Auto-generate first scene on load (for newly created projects) */
  autoGenerateFirst?: boolean;
  /** Target number of scenes for the project */
  targetSceneCount?: number;
  /** Image generation settings */
  imageProvider?: string;
  imageModel?: string;
  imageWidth?: number;
  imageHeight?: number;
  imageSteps?: number;
  imageCfg?: number;
}

/**
 * CreatorStudioEditor - Preview-first editor for Creator Studio projects
 *
 * Shows:
 * - Header with back button, title, status, save indicator
 * - Scene Chips rail (horizontal)
 * - Preview panel (dominant)
 * - Actions bar
 */
export function CreatorStudioEditor({
  projectId,
  backendUrl,
  apiKey,
  onExit,
  autoGenerateFirst = false,
  targetSceneCount = 8,
  imageProvider = "comfyui",
  imageModel,
  imageWidth = 1344,
  imageHeight = 768,
  imageSteps,
  imageCfg,
}: CreatorStudioEditorProps) {
  const authKey = (apiKey || "").trim();
  const [hasAutoTriggered, setHasAutoTriggered] = useState(false);

  // TV Mode store
  const tvModeActive = useTVModeStore((s) => s.isActive);
  const enterTVMode = useTVModeStore((s) => s.enterTVMode);
  const updateSceneImageByIdx = useTVModeStore((s) => s.updateSceneImageByIdx);

  // State
  const [project, setProject] = useState<Project | null>(null);
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentSceneIndex, setCurrentSceneIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [lastSaved, setLastSaved] = useState<Date | null>(null);
  const [isGeneratingScene, setIsGeneratingScene] = useState(false);
  const [isGeneratingImage, setIsGeneratingImage] = useState(false);

  // API helpers
  const fetchApi = useCallback(
    async <T,>(path: string): Promise<T> => {
      const url = `${backendUrl.replace(/\/+$/, "")}${path}`;
      const res = await fetch(url, {
        method: "GET",
        headers: {
          "Content-Type": "application/json",
          ...(authKey ? { "x-api-key": authKey } : {}),
        },
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(`HTTP ${res.status}${text ? `: ${text}` : ""}`);
      }
      return (await res.json()) as T;
    },
    [backendUrl, authKey]
  );

  const postApi = useCallback(
    async <T,>(path: string, body: any): Promise<T> => {
      const url = `${backendUrl.replace(/\/+$/, "")}${path}`;
      const res = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(authKey ? { "x-api-key": authKey } : {}),
        },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(`HTTP ${res.status}${text ? `: ${text}` : ""}`);
      }
      return (await res.json()) as T;
    },
    [backendUrl, authKey]
  );

  const patchApi = useCallback(
    async <T,>(path: string, body: any): Promise<T> => {
      const url = `${backendUrl.replace(/\/+$/, "")}${path}`;
      const res = await fetch(url, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          ...(authKey ? { "x-api-key": authKey } : {}),
        },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(`HTTP ${res.status}${text ? `: ${text}` : ""}`);
      }
      return (await res.json()) as T;
    },
    [backendUrl, authKey]
  );

  // Convert Creator Studio scene to TV Mode scene format
  const sceneToTVScene = useCallback((scene: Scene): TVScene => {
    return {
      idx: scene.idx,
      narration: scene.narration || "",
      image_prompt: scene.imagePrompt || "",
      negative_prompt: scene.negativePrompt || "",
      duration_s: scene.durationSec || 5,
      tags: {},
      image_url: scene.imageUrl || null,
      status: scene.status === "ready" ? "ready" : "pending",
      imageStatus: scene.imageUrl ? "ready" : "pending",
    };
  }, []);

  // Enter TV Mode with current scenes
  const handleEnterTVMode = useCallback(() => {
    if (!project || scenes.length === 0) return;

    const tvScenes = scenes.map(sceneToTVScene);
    enterTVMode(projectId, project.title, tvScenes, currentSceneIndex);
  }, [project, projectId, scenes, currentSceneIndex, enterTVMode, sceneToTVScene]);

  // Generate image for a scene
  const generateImageForScene = useCallback(
    async (sceneId: string, imagePrompt: string, force: boolean = false) => {
      if (isGeneratingImage && !force) {
        console.log('[CreatorStudioEditor] Already generating image, skipping');
        return;
      }

      setIsGeneratingImage(true);
      console.log('[CreatorStudioEditor] Generating image for scene:', sceneId);

      try {
        const llmProvider = imageProvider === 'comfyui' ? 'ollama' : imageProvider;

        const data = await postApi<{ media?: { images?: string[] } }>(
          '/chat',
          {
            message: `imagine ${imagePrompt}`,
            mode: 'imagine',
            provider: llmProvider,
            imgModel: imageModel || undefined,
            imgWidth: imageWidth,
            imgHeight: imageHeight,
            imgSteps: imageSteps,
            imgCfg: imageCfg,
            promptRefinement: false,
          }
        );

        const imageUrl = data?.media?.images?.[0];
        if (imageUrl) {
          console.log('[CreatorStudioEditor] Image generated:', imageUrl);

          // Update scene with image URL via API
          await patchApi(`/studio/videos/${projectId}/scenes/${sceneId}`, {
            imageUrl,
            status: 'ready',
          });

          // Update local state
          setScenes((prev) =>
            prev.map((s) =>
              s.id === sceneId ? { ...s, imageUrl, status: 'ready' as SceneStatus } : s
            )
          );
          setLastSaved(new Date());
        } else {
          console.warn('[CreatorStudioEditor] No image returned from backend');
        }
      } catch (e: any) {
        console.error('[CreatorStudioEditor] Failed to generate image:', e);
      } finally {
        setIsGeneratingImage(false);
      }
    },
    [projectId, imageProvider, imageModel, imageWidth, imageHeight, imageSteps, imageCfg, postApi, patchApi, isGeneratingImage]
  );

  // Load project and scenes
  useEffect(() => {
    async function loadData() {
      setLoading(true);
      setError(null);
      try {
        const [projectRes, scenesRes] = await Promise.all([
          fetchApi<{ video: Project }>(`/studio/videos/${projectId}`),
          fetchApi<{ scenes: Scene[] }>(`/studio/videos/${projectId}/scenes`),
        ]);
        setProject(projectRes.video);
        setScenes(scenesRes.scenes);
      } catch (e: any) {
        setError(e.message || String(e));
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, [projectId, fetchApi]);

  // Auto-generate first scene when project is newly created
  useEffect(() => {
    if (
      autoGenerateFirst &&
      !hasAutoTriggered &&
      !loading &&
      project &&
      scenes.length === 0 &&
      !isGeneratingScene
    ) {
      console.log('[CreatorStudioEditor] Auto-generating first scene for new project');
      setHasAutoTriggered(true);
      generateFirstSceneWithAI();
    }
  }, [autoGenerateFirst, hasAutoTriggered, loading, project, scenes.length, isGeneratingScene]);

  // Current scene
  const currentScene = scenes[currentSceneIndex] || null;

  // Extract visual style from project tags
  const getVisualStyle = useCallback(() => {
    if (!project) return "cinematic";
    const tags = (project as any).tags || [];
    const visualTag = tags.find((t: string) => t.startsWith("visual:"));
    if (visualTag) {
      const style = visualTag.replace("visual:", "").replace(/_/g, " ");
      return style;
    }
    return "cinematic";
  }, [project]);

  // Extract tone from project tags
  const getTones = useCallback(() => {
    if (!project) return ["documentary"];
    const tags = (project as any).tags || [];
    const tones = tags.filter((t: string) => t.startsWith("tone:")).map((t: string) =>
      t.replace("tone:", "").replace(/_/g, " ")
    );
    return tones.length > 0 ? tones : ["documentary"];
  }, [project]);

  // Generate AI-powered scene with better prompts
  const generateFirstSceneWithAI = useCallback(async () => {
    if (!project || isGeneratingScene) return;
    setIsGeneratingScene(true);

    try {
      const visualStyle = getVisualStyle();
      const tones = getTones();
      const toneDesc = tones.join(", ");

      // Build a richer AI-powered prompt
      const narration = `The story begins. ${project.logline || `Welcome to "${project.title}".`}`;
      const imagePrompt = `${visualStyle} style, ${project.logline || project.title}, opening scene, establishing shot, ${toneDesc} mood, high quality, detailed, 4k, masterpiece`;
      const negativePrompt = "blurry, low quality, text, watermark, ugly, deformed, disfigured, bad anatomy, worst quality, low resolution";

      const data = await postApi<{ scene: Scene }>(
        `/studio/videos/${projectId}/scenes`,
        {
          narration,
          imagePrompt,
          negativePrompt,
          durationSec: 5.0,
        }
      );

      setScenes((prev) => [...prev, data.scene]);
      setCurrentSceneIndex(0);
      setLastSaved(new Date());

      // Auto-generate image for the first scene
      console.log('[CreatorStudioEditor] Auto-generating image for first scene');
      generateImageForScene(data.scene.id, data.scene.imagePrompt);
    } catch (e: any) {
      console.error('[CreatorStudioEditor] Failed to create scene:', e);
      alert(`Failed to create scene: ${e.message}`);
    } finally {
      setIsGeneratingScene(false);
    }
  }, [project, projectId, isGeneratingScene, postApi, getVisualStyle, getTones]);

  // Generate first scene (non-AI fallback)
  const generateFirstScene = useCallback(async () => {
    if (!project || isGeneratingScene) return;
    setIsGeneratingScene(true);

    try {
      // Create a scene with a default prompt based on project
      const data = await postApi<{ scene: Scene }>(
        `/studio/videos/${projectId}/scenes`,
        {
          narration: `Opening scene for "${project.title}"`,
          imagePrompt: `${project.logline || project.title}, cinematic, high quality, detailed`,
          negativePrompt: "blurry, low quality, text, watermark",
          durationSec: 5.0,
        }
      );

      setScenes((prev) => [...prev, data.scene]);
      setCurrentSceneIndex(0);
      setLastSaved(new Date());
    } catch (e: any) {
      alert(`Failed to create scene: ${e.message}`);
    } finally {
      setIsGeneratingScene(false);
    }
  }, [project, projectId, isGeneratingScene, postApi]);

  // Generate next scene with AI-powered prompts
  const generateNextScene = useCallback(async () => {
    if (!project || isGeneratingScene) return;
    setIsGeneratingScene(true);

    try {
      const sceneNum = scenes.length + 1;
      const visualStyle = getVisualStyle();
      const tones = getTones();
      const toneDesc = tones.join(", ");

      // Build richer prompts
      const narration = `Scene ${sceneNum}. The story continues...`;
      const imagePrompt = `${visualStyle} style, ${project.logline || project.title}, scene ${sceneNum}, ${toneDesc} mood, high quality, detailed, 4k, masterpiece`;
      const negativePrompt = "blurry, low quality, text, watermark, ugly, deformed, disfigured, bad anatomy, worst quality, low resolution";

      const data = await postApi<{ scene: Scene }>(
        `/studio/videos/${projectId}/scenes`,
        {
          narration,
          imagePrompt,
          negativePrompt,
          durationSec: 5.0,
        }
      );

      setScenes((prev) => [...prev, data.scene]);
      setCurrentSceneIndex(scenes.length);
      setLastSaved(new Date());

      // Auto-generate image for the new scene
      console.log('[CreatorStudioEditor] Auto-generating image for scene:', sceneNum);
      generateImageForScene(data.scene.id, data.scene.imagePrompt);
    } catch (e: any) {
      alert(`Failed to create scene: ${e.message}`);
    } finally {
      setIsGeneratingScene(false);
    }
  }, [project, projectId, scenes.length, isGeneratingScene, postApi, getVisualStyle, getTones, generateImageForScene]);

  // Generate next scene for TV Mode
  const generateNextForTVMode = useCallback(async () => {
    if (!project || isGeneratingScene) return null;

    try {
      const sceneNum = scenes.length + 1;
      const visualStyle = getVisualStyle();
      const tones = getTones();
      const toneDesc = tones.join(", ");

      const narration = `Scene ${sceneNum}. The story continues...`;
      const imagePrompt = `${visualStyle} style, ${project.logline || project.title}, scene ${sceneNum}, ${toneDesc} mood, high quality, detailed, 4k, masterpiece`;
      const negativePrompt = "blurry, low quality, text, watermark, ugly, deformed, disfigured, bad anatomy, worst quality, low resolution";

      const data = await postApi<{ scene: Scene }>(
        `/studio/videos/${projectId}/scenes`,
        {
          narration,
          imagePrompt,
          negativePrompt,
          durationSec: 5.0,
        }
      );

      setScenes((prev) => [...prev, data.scene]);

      // Return TV scene format
      return sceneToTVScene(data.scene);
    } catch (e: any) {
      console.error('[CreatorStudioEditor] Failed to generate scene for TV mode:', e);
      return null;
    }
  }, [project, projectId, scenes.length, isGeneratingScene, postApi, getVisualStyle, getTones, sceneToTVScene]);

  // Ensure image for TV Mode scene
  const ensureImageForTVMode = useCallback((tvScene: TVScene) => {
    // Find the corresponding Creator Studio scene
    const scene = scenes.find(s => s.idx === tvScene.idx);
    if (!scene) return;

    // If no image, generate one
    if (!tvScene.image_url && !tvScene.image) {
      generateImageForScene(scene.id, scene.imagePrompt).then(() => {
        // After generation, update the TV mode store
        const updatedScene = scenes.find(s => s.idx === tvScene.idx);
        if (updatedScene?.imageUrl) {
          updateSceneImageByIdx(tvScene.idx, updatedScene.imageUrl);
        }
      });
    }
  }, [scenes, generateImageForScene, updateSceneImageByIdx]);

  // Status badge color
  const getStatusBadge = (status: string) => {
    switch (status) {
      case "draft":
        return { bg: "bg-yellow-500/20", text: "text-yellow-300", label: "Draft" };
      case "approved":
        return { bg: "bg-green-500/20", text: "text-green-300", label: "Finished" };
      case "in_review":
        return { bg: "bg-blue-500/20", text: "text-blue-300", label: "In Review" };
      case "archived":
        return { bg: "bg-gray-500/20", text: "text-gray-300", label: "Archived" };
      default:
        return { bg: "bg-gray-500/20", text: "text-gray-300", label: status };
    }
  };

  // Loading state
  if (loading) {
    return (
      <div className="min-h-screen w-full bg-black text-white flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="w-8 h-8 animate-spin text-purple-500" />
          <div className="text-white/60">Loading project...</div>
        </div>
      </div>
    );
  }

  // Error state
  if (error || !project) {
    return (
      <div className="min-h-screen w-full bg-black text-white flex items-center justify-center">
        <div className="flex flex-col items-center gap-4 max-w-md text-center">
          <div className="text-red-400 text-lg">Failed to load project</div>
          <div className="text-white/60 text-sm">{error || "Project not found"}</div>
          <button
            onClick={onExit}
            className="mt-4 px-6 py-2 bg-white/10 hover:bg-white/20 rounded-lg transition-colors"
          >
            ← Back to Studio
          </button>
        </div>
      </div>
    );
  }

  const statusBadge = getStatusBadge(project.status);

  return (
    <div className="min-h-screen w-full bg-black text-white flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/10 bg-black/80">
        <div className="flex items-center gap-4">
          <button
            onClick={onExit}
            className="flex items-center gap-2 px-3 py-1.5 text-sm text-white/60 hover:text-white hover:bg-white/10 rounded-lg transition-colors"
          >
            <ArrowLeft size={16} />
            <span>Back to Studio</span>
          </button>

          <div className="h-6 w-px bg-white/20" />

          <div>
            <div className="text-base font-semibold text-white">{project.title}</div>
            <div className="text-xs text-white/50">
              {scenes.length} scene{scenes.length !== 1 ? "s" : ""}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* Status Badge */}
          <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${statusBadge.bg} ${statusBadge.text}`}>
            {statusBadge.label}
          </span>

          {/* Save Indicator */}
          <div className="flex items-center gap-1.5 text-xs text-white/50">
            {isSaving ? (
              <>
                <Loader2 size={12} className="animate-spin" />
                <span>Saving...</span>
              </>
            ) : lastSaved ? (
              <>
                <Check size={12} className="text-green-400" />
                <span>Saved</span>
              </>
            ) : (
              <span>Auto-save enabled</span>
            )}
          </div>

          {/* Watch / TV Mode Button */}
          {scenes.length > 0 && (
            <button
              onClick={handleEnterTVMode}
              className="flex items-center gap-2 px-4 py-2 bg-white/10 hover:bg-white/20 rounded-lg text-sm font-medium transition-colors"
              title="Watch in TV Mode"
            >
              <Tv size={14} />
              Watch
            </button>
          )}

          {/* Primary CTA */}
          {scenes.length > 0 && (
            <button
              onClick={generateNextScene}
              disabled={isGeneratingScene}
              className="flex items-center gap-2 px-4 py-2 bg-purple-500 hover:bg-purple-600 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-sm font-medium transition-colors"
            >
              {isGeneratingScene ? (
                <>
                  <Loader2 size={14} className="animate-spin" />
                  Generating...
                </>
              ) : (
                <>
                  <Plus size={14} />
                  Generate next scene
                </>
              )}
            </button>
          )}
        </div>
      </div>

      {/* Scene Chips Rail */}
      {scenes.length > 0 && (
        <div className="w-full overflow-x-auto border-b border-white/10 bg-black/40">
          <div className="flex gap-2 px-4 py-3 min-w-max">
            {scenes.map((scene, idx) => {
              const isActive = idx === currentSceneIndex;
              const hasImage = Boolean(scene.imageUrl);

              return (
                <button
                  key={scene.id}
                  onClick={() => setCurrentSceneIndex(idx)}
                  className={`
                    relative rounded-lg overflow-hidden transition-all
                    ${isActive
                      ? "ring-2 ring-purple-500 ring-offset-2 ring-offset-black"
                      : "opacity-70 hover:opacity-100"
                    }
                  `}
                  type="button"
                  title={`Scene ${idx + 1}`}
                >
                  {/* Thumbnail */}
                  <div className="w-16 h-10 flex items-center justify-center bg-white/5">
                    {hasImage ? (
                      <img
                        src={scene.imageUrl!}
                        alt={`Scene ${idx + 1}`}
                        className="w-full h-full object-cover"
                      />
                    ) : (
                      <ImageIcon size={16} className="text-white/30" />
                    )}
                  </div>

                  {/* Scene number badge */}
                  <div className="absolute bottom-1 right-1 text-[10px] bg-black/60 px-1 rounded">
                    {idx + 1}
                  </div>
                </button>
              );
            })}

            {/* Add Scene Chip */}
            <button
              onClick={generateNextScene}
              disabled={isGeneratingScene}
              className="w-16 h-10 rounded-lg border border-dashed border-white/20 hover:border-white/40 flex items-center justify-center transition-colors disabled:opacity-50"
              title="Add scene"
            >
              <Plus size={16} className="text-white/40" />
            </button>
          </div>
        </div>
      )}

      {/* Main Content */}
      {scenes.length === 0 ? (
        // Empty State
        <div className="flex-1 flex items-center justify-center p-8">
          <div className="max-w-md text-center">
            <div className="w-24 h-24 mx-auto mb-6 rounded-2xl bg-gradient-to-br from-purple-500/20 to-pink-500/20 flex items-center justify-center">
              <ImageIcon size={48} className="text-purple-400/60" />
            </div>

            <h2 className="text-2xl font-semibold text-white mb-2">No scenes yet</h2>
            <p className="text-white/60 mb-6">
              Your project is ready. Generate your first scene to start creating your story.
            </p>

            <button
              onClick={generateFirstScene}
              disabled={isGeneratingScene}
              className="inline-flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-purple-500 to-pink-500 hover:from-purple-600 hover:to-pink-600 disabled:opacity-50 disabled:cursor-not-allowed rounded-xl text-base font-semibold transition-colors"
            >
              {isGeneratingScene ? (
                <>
                  <Loader2 size={18} className="animate-spin" />
                  Generating first scene...
                </>
              ) : (
                <>
                  <Play size={18} />
                  Generate first scene
                </>
              )}
            </button>

            <p className="text-xs text-white/40 mt-4">
              This will create a scene based on your project settings
            </p>
          </div>
        </div>
      ) : (
        // Preview + Actions
        <div className="flex-1 flex flex-col">
          {/* Preview Panel */}
          <div className="flex-1 flex items-center justify-center p-6 bg-gradient-to-b from-black to-black/80">
            <div className="relative max-w-4xl w-full aspect-video rounded-xl overflow-hidden bg-white/5">
              {currentScene?.imageUrl ? (
                <img
                  src={currentScene.imageUrl}
                  alt={`Scene ${currentSceneIndex + 1}`}
                  className="w-full h-full object-cover"
                />
              ) : (
                <div className="w-full h-full flex flex-col items-center justify-center gap-4">
                  {isGeneratingImage ? (
                    <>
                      <Loader2 size={32} className="animate-spin text-purple-400" />
                      <div className="text-white/60">Generating image...</div>
                    </>
                  ) : (
                    <>
                      <ImageIcon size={48} className="text-white/20" />
                      <div className="text-white/40">No image generated yet</div>
                    </>
                  )}
                </div>
              )}

              {/* Narration overlay */}
              {currentScene?.narration && (
                <div className="absolute bottom-0 left-0 right-0 p-4 bg-gradient-to-t from-black/80 to-transparent">
                  <p className="text-white text-sm">{currentScene.narration}</p>
                </div>
              )}
            </div>
          </div>

          {/* Actions Bar */}
          <div className="flex items-center justify-between px-6 py-4 border-t border-white/10 bg-black/80">
            {/* Playback Controls */}
            <div className="flex items-center gap-2">
              <button
                onClick={() => setCurrentSceneIndex((i) => Math.max(0, i - 1))}
                disabled={currentSceneIndex === 0}
                className="p-2 text-white/60 hover:text-white hover:bg-white/10 rounded-lg disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                title="Previous scene"
              >
                <ChevronLeft size={20} />
              </button>

              <button
                onClick={() => setIsPlaying(!isPlaying)}
                className="p-3 bg-white/10 hover:bg-white/20 rounded-full transition-colors"
                title={isPlaying ? "Pause" : "Play"}
              >
                {isPlaying ? <Pause size={20} /> : <Play size={20} />}
              </button>

              <button
                onClick={() => setCurrentSceneIndex((i) => Math.min(scenes.length - 1, i + 1))}
                disabled={currentSceneIndex >= scenes.length - 1}
                className="p-2 text-white/60 hover:text-white hover:bg-white/10 rounded-lg disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                title="Next scene"
              >
                <ChevronRight size={20} />
              </button>

              <span className="ml-2 text-sm text-white/50">
                Scene {currentSceneIndex + 1} of {scenes.length}
              </span>
            </div>

            {/* Scene Actions */}
            <div className="flex items-center gap-3">
              <button
                onClick={() => {
                  if (currentScene) {
                    generateImageForScene(currentScene.id, currentScene.imagePrompt, true);
                  }
                }}
                disabled={isGeneratingImage || !currentScene}
                className="flex items-center gap-2 px-4 py-2 bg-white/10 hover:bg-white/20 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-sm transition-colors"
              >
                {isGeneratingImage ? (
                  <>
                    <Loader2 size={14} className="animate-spin" />
                    Generating...
                  </>
                ) : (
                  <>
                    <RefreshCw size={14} />
                    Regenerate
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* TV Mode Overlay */}
      {tvModeActive && (
        <TVModeContainer
          onGenerateNext={generateNextForTVMode}
          onEnsureImage={ensureImageForTVMode}
        />
      )}
    </div>
  );
}

export default CreatorStudioEditor;
