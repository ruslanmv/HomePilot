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
  Edit3,
  Wand2,
  Save,
  X,
  Settings,
  FileText,
  Sparkles,
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
  metadata?: {
    story_outline?: StoryOutline;
  };
};

type SceneOutline = {
  scene_number: number;
  title: string;
  description: string;
  narration: string;
  image_prompt: string;
  negative_prompt: string;
  duration_sec: number;
};

type StoryOutline = {
  title: string;
  logline: string;
  visual_style: string;
  tone: string;
  story_arc: {
    beginning: string;
    rising_action: string;
    climax: string;
    falling_action: string;
    resolution: string;
  };
  scenes: SceneOutline[];
};

type AvailableModel = {
  id: string;
  name: string;
  provider?: string;
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

  // Story outline state
  const [storyOutline, setStoryOutline] = useState<StoryOutline | null>(null);
  const [isGeneratingOutline, setIsGeneratingOutline] = useState(false);
  const [showOutlinePanel, setShowOutlinePanel] = useState(false);

  // Scene editor state
  const [showSceneEditor, setShowSceneEditor] = useState(false);
  const [editingScene, setEditingScene] = useState<Scene | null>(null);
  const [editNarration, setEditNarration] = useState("");
  const [editImagePrompt, setEditImagePrompt] = useState("");
  const [editNegativePrompt, setEditNegativePrompt] = useState("");
  const [isSavingScene, setIsSavingScene] = useState(false);

  // Model selection state
  const [availableLLMModels, setAvailableLLMModels] = useState<AvailableModel[]>([]);
  const [availableImageModels, setAvailableImageModels] = useState<AvailableModel[]>([]);
  const [selectedLLMModel, setSelectedLLMModel] = useState<string>("");
  const [selectedImageModel, setSelectedImageModel] = useState<string>(imageModel || "");
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

  // Generate AI-powered story outline
  const generateStoryOutline = useCallback(async () => {
    if (!project || isGeneratingOutline) return;
    setIsGeneratingOutline(true);

    try {
      console.log('[CreatorStudioEditor] Generating story outline...');
      const data = await postApi<{ ok: boolean; outline: StoryOutline; model_used: string }>(
        `/studio/videos/${projectId}/generate-outline`,
        {
          target_scenes: targetSceneCount,
          scene_duration: 5,
          ollama_model: selectedLLMModel || undefined,
        }
      );

      if (data.ok && data.outline) {
        setStoryOutline(data.outline);
        console.log('[CreatorStudioEditor] Story outline generated:', data.outline.title);
      }
    } catch (e: any) {
      console.error('[CreatorStudioEditor] Failed to generate outline:', e);
      alert(`Failed to generate outline: ${e.message}`);
    } finally {
      setIsGeneratingOutline(false);
    }
  }, [project, projectId, targetSceneCount, selectedLLMModel, isGeneratingOutline, postApi]);

  // Load existing story outline
  const loadStoryOutline = useCallback(async () => {
    try {
      const data = await fetchApi<{ ok: boolean; outline: StoryOutline | null }>(
        `/studio/videos/${projectId}/outline`
      );
      if (data.ok && data.outline) {
        setStoryOutline(data.outline);
      }
    } catch (e) {
      console.log('[CreatorStudioEditor] No existing outline found');
    }
  }, [projectId, fetchApi]);

  // Open scene editor
  const openSceneEditor = useCallback((scene: Scene) => {
    setEditingScene(scene);
    setEditNarration(scene.narration || "");
    setEditImagePrompt(scene.imagePrompt || "");
    setEditNegativePrompt(scene.negativePrompt || "");
    setShowSceneEditor(true);
  }, []);

  // Save scene edits
  const saveSceneEdits = useCallback(async () => {
    if (!editingScene) return;
    setIsSavingScene(true);

    try {
      await patchApi(`/studio/videos/${projectId}/scenes/${editingScene.id}`, {
        narration: editNarration,
        imagePrompt: editImagePrompt,
        negativePrompt: editNegativePrompt,
      });

      // Update local state
      setScenes((prev) =>
        prev.map((s) =>
          s.id === editingScene.id
            ? { ...s, narration: editNarration, imagePrompt: editImagePrompt, negativePrompt: editNegativePrompt }
            : s
        )
      );
      setLastSaved(new Date());
      setShowSceneEditor(false);
      setEditingScene(null);
    } catch (e: any) {
      console.error('[CreatorStudioEditor] Failed to save scene:', e);
      alert(`Failed to save scene: ${e.message}`);
    } finally {
      setIsSavingScene(false);
    }
  }, [editingScene, editNarration, editImagePrompt, editNegativePrompt, projectId, patchApi]);

  // Fetch available models
  const fetchAvailableModels = useCallback(async () => {
    try {
      // Fetch LLM models (Ollama)
      const llmData = await fetchApi<{ models: { id: string; name?: string }[] }>(
        '/models?provider=ollama'
      );
      if (llmData.models) {
        setAvailableLLMModels(llmData.models.map(m => ({ id: m.id, name: m.name || m.id })));
      }
    } catch (e) {
      console.log('[CreatorStudioEditor] Failed to fetch LLM models:', e);
    }

    try {
      // Fetch image models (ComfyUI)
      const imgData = await fetchApi<{ models: string[] }>(
        '/models?provider=comfyui&model_type=image'
      );
      if (imgData.models) {
        setAvailableImageModels(imgData.models.map(m => ({ id: m, name: m })));
      }
    } catch (e) {
      console.log('[CreatorStudioEditor] Failed to fetch image models:', e);
    }
  }, [fetchApi]);

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

  // Generate scene from outline (defined after generateImageForScene to avoid circular dependency)
  const generateSceneFromOutline = useCallback(async (sceneIndex: number) => {
    if (!storyOutline || sceneIndex >= storyOutline.scenes.length) return;

    setIsGeneratingScene(true);
    try {
      const data = await postApi<{ ok: boolean; scene: Scene }>(
        `/studio/videos/${projectId}/scenes/generate-from-outline?scene_index=${sceneIndex}`,
        {}
      );

      if (data.ok && data.scene) {
        setScenes((prev) => [...prev, data.scene]);
        setCurrentSceneIndex(scenes.length);
        setLastSaved(new Date());

        // Auto-generate image
        generateImageForScene(data.scene.id, data.scene.imagePrompt);
      }
    } catch (e: any) {
      console.error('[CreatorStudioEditor] Failed to generate scene from outline:', e);
      alert(`Failed to generate scene: ${e.message}`);
    } finally {
      setIsGeneratingScene(false);
    }
  }, [projectId, storyOutline, scenes.length, postApi, generateImageForScene]);

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

  // Load available models and existing outline on mount
  useEffect(() => {
    fetchAvailableModels();
    loadStoryOutline();
  }, [fetchAvailableModels, loadStoryOutline]);

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
      let narration: string;
      let imagePrompt: string;
      let negativePrompt: string = "blurry, low quality, text, watermark, ugly, deformed, disfigured, bad anatomy, worst quality, low resolution";

      // Use story outline if available
      if (storyOutline && storyOutline.scenes && storyOutline.scenes.length > 0) {
        const outlineScene = storyOutline.scenes[0];
        narration = outlineScene.narration;
        imagePrompt = outlineScene.image_prompt;
        negativePrompt = outlineScene.negative_prompt || negativePrompt;
        console.log('[CreatorStudioEditor] Using story outline for first scene');
      } else {
        // Fallback to AI-generated prompts
        const visualStyle = getVisualStyle();
        const tones = getTones();
        const toneDesc = tones.join(", ");
        narration = `The story begins. ${project.logline || `Welcome to "${project.title}".`}`;
        imagePrompt = `${visualStyle} style, ${project.logline || project.title}, opening scene, establishing shot, ${toneDesc} mood, high quality, detailed, 4k, masterpiece`;
      }

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
  }, [project, projectId, isGeneratingScene, postApi, getVisualStyle, getTones, storyOutline, generateImageForScene]);

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

  // Generate next scene with AI-powered prompts (uses story outline if available)
  const generateNextScene = useCallback(async () => {
    if (!project || isGeneratingScene) return;
    setIsGeneratingScene(true);

    try {
      const sceneNum = scenes.length + 1;
      let narration: string;
      let imagePrompt: string;
      let negativePrompt: string = "blurry, low quality, text, watermark, ugly, deformed, disfigured, bad anatomy, worst quality, low resolution";

      // Use story outline if available and we haven't exceeded the planned scenes
      if (storyOutline && storyOutline.scenes && scenes.length < storyOutline.scenes.length) {
        const outlineScene = storyOutline.scenes[scenes.length];
        narration = outlineScene.narration;
        imagePrompt = outlineScene.image_prompt;
        negativePrompt = outlineScene.negative_prompt || negativePrompt;
        console.log(`[CreatorStudioEditor] Using outline for scene ${sceneNum}: "${outlineScene.title}"`);
      } else {
        // Fallback to AI-generated prompts
        const visualStyle = getVisualStyle();
        const tones = getTones();
        const toneDesc = tones.join(", ");
        narration = `Scene ${sceneNum}. The story continues...`;
        imagePrompt = `${visualStyle} style, ${project.logline || project.title}, scene ${sceneNum}, ${toneDesc} mood, high quality, detailed, 4k, masterpiece`;
      }

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
  }, [project, projectId, scenes.length, isGeneratingScene, postApi, getVisualStyle, getTones, storyOutline, generateImageForScene]);

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
          <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
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

          {/* Story Outline Button */}
          <button
            onClick={() => setShowOutlinePanel(true)}
            className="flex items-center gap-2 px-4 py-2 bg-white/10 hover:bg-white/20 rounded-lg text-sm font-medium transition-colors"
            title="Story Outline"
          >
            <Wand2 size={14} />
            Outline
          </button>

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
              className="flex items-center gap-2 px-4 py-2 bg-blue-500 hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-sm font-medium transition-colors"
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
                      ? "ring-2 ring-blue-500 ring-offset-2 ring-offset-black"
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
            <div className="w-24 h-24 mx-auto mb-6 rounded-2xl bg-gradient-to-br from-blue-500/20 to-cyan-500/20 flex items-center justify-center">
              <ImageIcon size={48} className="text-blue-400/60" />
            </div>

            <h2 className="text-2xl font-semibold text-white mb-2">No scenes yet</h2>
            <p className="text-white/60 mb-6">
              Your project is ready. Generate your first scene to start creating your story.
            </p>

            <button
              onClick={generateFirstScene}
              disabled={isGeneratingScene}
              className="inline-flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-blue-500 to-cyan-500 hover:from-blue-600 hover:to-cyan-600 disabled:opacity-50 disabled:cursor-not-allowed rounded-xl text-base font-semibold transition-colors"
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
                      <Loader2 size={32} className="animate-spin text-blue-400" />
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
              {/* Edit Scene Button */}
              <button
                onClick={() => currentScene && openSceneEditor(currentScene)}
                disabled={!currentScene}
                className="flex items-center gap-2 px-4 py-2 bg-white/10 hover:bg-white/20 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-sm transition-colors"
                title="Edit scene narration and prompts"
              >
                <Edit3 size={14} />
                Edit
              </button>

              {/* Regenerate Image Button */}
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

      {/* Scene Editor Modal */}
      {showSceneEditor && editingScene && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/80" onClick={() => setShowSceneEditor(false)} />
          <div className="relative w-full max-w-2xl rounded-xl border border-white/10 bg-[#1a1a1a] shadow-2xl max-h-[90vh] overflow-y-auto">
            {/* Modal Header */}
            <div className="flex items-center justify-between p-5 border-b border-white/10">
              <div className="flex items-center gap-3">
                <Edit3 size={20} className="text-blue-400" />
                <h2 className="text-lg font-semibold">Edit Scene {editingScene.idx + 1}</h2>
              </div>
              <button
                onClick={() => setShowSceneEditor(false)}
                className="p-2 rounded-lg hover:bg-white/10 transition-colors"
              >
                <X size={18} />
              </button>
            </div>

            {/* Modal Content */}
            <div className="p-5 space-y-5">
              {/* Narration */}
              <div>
                <label className="block text-sm font-medium text-white/70 mb-2">
                  <FileText size={14} className="inline mr-2" />
                  Narration
                </label>
                <textarea
                  value={editNarration}
                  onChange={(e) => setEditNarration(e.target.value)}
                  className="w-full px-4 py-3 bg-black/40 border border-white/10 rounded-lg text-white placeholder-white/30 focus:border-blue-500 focus:outline-none resize-none"
                  rows={3}
                  placeholder="Enter narration text for this scene..."
                />
              </div>

              {/* Image Prompt */}
              <div>
                <label className="block text-sm font-medium text-white/70 mb-2">
                  <Sparkles size={14} className="inline mr-2" />
                  Image Prompt
                </label>
                <textarea
                  value={editImagePrompt}
                  onChange={(e) => setEditImagePrompt(e.target.value)}
                  className="w-full px-4 py-3 bg-black/40 border border-white/10 rounded-lg text-white placeholder-white/30 focus:border-blue-500 focus:outline-none resize-none"
                  rows={4}
                  placeholder="Describe the visual elements for image generation..."
                />
              </div>

              {/* Negative Prompt */}
              <div>
                <label className="block text-sm font-medium text-white/70 mb-2">
                  Negative Prompt
                </label>
                <textarea
                  value={editNegativePrompt}
                  onChange={(e) => setEditNegativePrompt(e.target.value)}
                  className="w-full px-4 py-3 bg-black/40 border border-white/10 rounded-lg text-white placeholder-white/30 focus:border-blue-500 focus:outline-none resize-none"
                  rows={2}
                  placeholder="Elements to avoid in the image..."
                />
              </div>

              {/* Model Selection */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-white/70 mb-2">
                    <Settings size={14} className="inline mr-2" />
                    LLM Model
                  </label>
                  <select
                    value={selectedLLMModel}
                    onChange={(e) => setSelectedLLMModel(e.target.value)}
                    className="w-full px-3 py-2 bg-black/40 border border-white/10 rounded-lg text-white focus:border-blue-500 focus:outline-none"
                  >
                    <option value="">Default</option>
                    {availableLLMModels.map((m) => (
                      <option key={m.id} value={m.id}>{m.name}</option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium text-white/70 mb-2">
                    <ImageIcon size={14} className="inline mr-2" />
                    Image Model
                  </label>
                  <select
                    value={selectedImageModel}
                    onChange={(e) => setSelectedImageModel(e.target.value)}
                    className="w-full px-3 py-2 bg-black/40 border border-white/10 rounded-lg text-white focus:border-blue-500 focus:outline-none"
                  >
                    <option value="">Default</option>
                    {availableImageModels.map((m) => (
                      <option key={m.id} value={m.id}>{m.name}</option>
                    ))}
                  </select>
                </div>
              </div>
            </div>

            {/* Modal Footer */}
            <div className="flex items-center justify-between p-5 border-t border-white/10">
              <button
                onClick={() => {
                  generateImageForScene(editingScene.id, editImagePrompt, true);
                  setShowSceneEditor(false);
                }}
                disabled={isGeneratingImage}
                className="flex items-center gap-2 px-4 py-2 bg-white/10 hover:bg-white/20 rounded-lg text-sm transition-colors"
              >
                <RefreshCw size={14} />
                Regenerate Image
              </button>

              <div className="flex items-center gap-3">
                <button
                  onClick={() => setShowSceneEditor(false)}
                  className="px-4 py-2 text-sm text-white/60 hover:text-white transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={saveSceneEdits}
                  disabled={isSavingScene}
                  className="flex items-center gap-2 px-5 py-2 bg-blue-500 hover:bg-blue-600 disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
                >
                  {isSavingScene ? (
                    <>
                      <Loader2 size={14} className="animate-spin" />
                      Saving...
                    </>
                  ) : (
                    <>
                      <Save size={14} />
                      Save Changes
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Story Outline Panel */}
      {showOutlinePanel && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/80" onClick={() => setShowOutlinePanel(false)} />
          <div className="relative w-full max-w-3xl rounded-xl border border-white/10 bg-[#1a1a1a] shadow-2xl max-h-[90vh] overflow-y-auto">
            {/* Panel Header */}
            <div className="flex items-center justify-between p-5 border-b border-white/10">
              <div className="flex items-center gap-3">
                <Wand2 size={20} className="text-blue-400" />
                <h2 className="text-lg font-semibold">Story Outline</h2>
              </div>
              <div className="flex items-center gap-3">
                <button
                  onClick={generateStoryOutline}
                  disabled={isGeneratingOutline}
                  className="flex items-center gap-2 px-4 py-2 bg-blue-500 hover:bg-blue-600 disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
                >
                  {isGeneratingOutline ? (
                    <>
                      <Loader2 size={14} className="animate-spin" />
                      Generating...
                    </>
                  ) : (
                    <>
                      <Sparkles size={14} />
                      {storyOutline ? "Regenerate" : "Generate"} Outline
                    </>
                  )}
                </button>
                <button
                  onClick={() => setShowOutlinePanel(false)}
                  className="p-2 rounded-lg hover:bg-white/10 transition-colors"
                >
                  <X size={18} />
                </button>
              </div>
            </div>

            {/* Panel Content */}
            <div className="p-5">
              {storyOutline ? (
                <div className="space-y-6">
                  {/* Story Arc */}
                  <div className="p-4 bg-black/30 rounded-lg">
                    <h3 className="text-sm font-semibold text-blue-400 mb-3">Story Arc</h3>
                    <div className="grid grid-cols-5 gap-2 text-xs">
                      <div className="p-2 bg-white/5 rounded">
                        <div className="text-white/50 mb-1">Beginning</div>
                        <div className="text-white/80">{storyOutline.story_arc?.beginning || "—"}</div>
                      </div>
                      <div className="p-2 bg-white/5 rounded">
                        <div className="text-white/50 mb-1">Rising</div>
                        <div className="text-white/80">{storyOutline.story_arc?.rising_action || "—"}</div>
                      </div>
                      <div className="p-2 bg-white/5 rounded">
                        <div className="text-white/50 mb-1">Climax</div>
                        <div className="text-white/80">{storyOutline.story_arc?.climax || "—"}</div>
                      </div>
                      <div className="p-2 bg-white/5 rounded">
                        <div className="text-white/50 mb-1">Falling</div>
                        <div className="text-white/80">{storyOutline.story_arc?.falling_action || "—"}</div>
                      </div>
                      <div className="p-2 bg-white/5 rounded">
                        <div className="text-white/50 mb-1">Resolution</div>
                        <div className="text-white/80">{storyOutline.story_arc?.resolution || "—"}</div>
                      </div>
                    </div>
                  </div>

                  {/* Scene Outlines */}
                  <div>
                    <h3 className="text-sm font-semibold text-white/70 mb-3">
                      Scene Outlines ({storyOutline.scenes?.length || 0} scenes)
                    </h3>
                    <div className="space-y-3">
                      {storyOutline.scenes?.map((scene, idx) => {
                        const alreadyGenerated = scenes.length > idx;
                        return (
                          <div
                            key={idx}
                            className={`p-4 rounded-lg border transition-colors ${
                              alreadyGenerated
                                ? "bg-green-500/10 border-green-500/30"
                                : "bg-black/30 border-white/10 hover:border-white/20"
                            }`}
                          >
                            <div className="flex items-start justify-between gap-4">
                              <div className="flex-1">
                                <div className="flex items-center gap-2 mb-1">
                                  <span className="text-sm font-medium text-white">
                                    Scene {scene.scene_number}: {scene.title}
                                  </span>
                                  {alreadyGenerated && (
                                    <span className="text-xs px-2 py-0.5 bg-green-500/20 text-green-400 rounded">
                                      Generated
                                    </span>
                                  )}
                                </div>
                                <p className="text-sm text-white/60 mb-2">{scene.description}</p>
                                <p className="text-xs text-white/40 italic">"{scene.narration}"</p>
                              </div>
                              {!alreadyGenerated && scenes.length === idx && (
                                <button
                                  onClick={() => {
                                    generateSceneFromOutline(idx);
                                    setShowOutlinePanel(false);
                                  }}
                                  disabled={isGeneratingScene}
                                  className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-500 hover:bg-blue-600 disabled:opacity-50 rounded text-xs font-medium transition-colors"
                                >
                                  <Plus size={12} />
                                  Generate
                                </button>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="text-center py-12">
                  <Wand2 size={48} className="mx-auto text-white/20 mb-4" />
                  <h3 className="text-lg font-medium text-white mb-2">No Outline Yet</h3>
                  <p className="text-white/50 mb-6 max-w-md mx-auto">
                    Generate an AI-powered story outline based on your project settings.
                    This creates a complete story arc with scene-by-scene planning.
                  </p>
                  <button
                    onClick={generateStoryOutline}
                    disabled={isGeneratingOutline}
                    className="inline-flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-blue-500 to-cyan-500 hover:from-blue-600 hover:to-cyan-600 disabled:opacity-50 rounded-xl font-semibold transition-colors"
                  >
                    {isGeneratingOutline ? (
                      <>
                        <Loader2 size={18} className="animate-spin" />
                        Generating Outline...
                      </>
                    ) : (
                      <>
                        <Sparkles size={18} />
                        Generate Story Outline
                      </>
                    )}
                  </button>
                </div>
              )}
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
