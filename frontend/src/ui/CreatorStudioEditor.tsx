import React, { useEffect, useState, useCallback } from "react";
import {
  ArrowLeft,
  Play,
  Pause,
  SkipBack,
  SkipForward,
  Plus,
  RefreshCw,
  Check,
  Loader2,
  ImageIcon,
  Monitor,
  Edit3,
  Wand2,
  Save,
  X,
  Settings,
  FileText,
  Sparkles,
  AlertCircle,
  Download,
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
  autoGenerateFirst?: boolean;
  targetSceneCount?: number;
  imageProvider?: string;
  imageModel?: string;
  imageWidth?: number;
  imageHeight?: number;
  imageSteps?: number;
  imageCfg?: number;
}

/**
 * CreatorStudioEditor - Professional editor for Creator Studio projects
 * Styled like Play Story mode but enhanced for creators
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
  const [hoveredSceneIdx, setHoveredSceneIdx] = useState<number | null>(null);

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

  const deleteApi = useCallback(
    async <T,>(path: string): Promise<T> => {
      const url = `${backendUrl.replace(/\/+$/, "")}${path}`;
      const res = await fetch(url, {
        method: "DELETE",
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

  // Delete scene
  const deleteScene = useCallback(async (sceneId: string) => {
    if (scenes.length <= 1) {
      alert("Cannot delete the last scene.");
      return;
    }

    if (!window.confirm("Delete this scene? This cannot be undone.")) {
      return;
    }

    try {
      console.log('[CreatorStudioEditor] Deleting scene:', sceneId);
      await deleteApi<{ ok: boolean }>(`/studio/videos/${projectId}/scenes/${sceneId}`);

      const deletedIndex = scenes.findIndex((s) => s.id === sceneId);

      setScenes((prev) => {
        const newScenes = prev
          .filter((s) => s.id !== sceneId)
          .map((s, i) => ({ ...s, idx: i }));
        return newScenes;
      });

      if (deletedIndex >= 0 && deletedIndex <= currentSceneIndex) {
        setCurrentSceneIndex((prev) => Math.max(0, prev - 1));
      }

      setLastSaved(new Date());
      console.log('[CreatorStudioEditor] Scene deleted successfully');
    } catch (e: any) {
      console.error('[CreatorStudioEditor] Failed to delete scene:', e);
      alert(`Failed to delete scene: ${e.message}`);
    }
  }, [projectId, scenes, currentSceneIndex, deleteApi]);

  // Fetch available models
  const fetchAvailableModels = useCallback(async () => {
    try {
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

          await patchApi(`/studio/videos/${projectId}/scenes/${sceneId}`, {
            imageUrl,
            status: 'ready',
          });

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

  // Generate scene from outline
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

      if (storyOutline && storyOutline.scenes && storyOutline.scenes.length > 0) {
        const outlineScene = storyOutline.scenes[0];
        narration = outlineScene.narration;
        imagePrompt = outlineScene.image_prompt;
        negativePrompt = outlineScene.negative_prompt || negativePrompt;
        console.log('[CreatorStudioEditor] Using story outline for first scene');
      } else {
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
      let narration: string;
      let imagePrompt: string;
      let negativePrompt: string = "blurry, low quality, text, watermark, ugly, deformed, disfigured, bad anatomy, worst quality, low resolution";

      if (storyOutline && storyOutline.scenes && scenes.length < storyOutline.scenes.length) {
        const outlineScene = storyOutline.scenes[scenes.length];
        narration = outlineScene.narration;
        imagePrompt = outlineScene.image_prompt;
        negativePrompt = outlineScene.negative_prompt || negativePrompt;
        console.log(`[CreatorStudioEditor] Using outline for scene ${sceneNum}: "${outlineScene.title}"`);
      } else {
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

      return sceneToTVScene(data.scene);
    } catch (e: any) {
      console.error('[CreatorStudioEditor] Failed to generate scene for TV mode:', e);
      return null;
    }
  }, [project, projectId, scenes.length, isGeneratingScene, postApi, getVisualStyle, getTones, sceneToTVScene]);

  // Ensure image for TV Mode scene
  const ensureImageForTVMode = useCallback((tvScene: TVScene) => {
    const scene = scenes.find(s => s.idx === tvScene.idx);
    if (!scene) return;

    if (!tvScene.image_url && !tvScene.image) {
      generateImageForScene(scene.id, scene.imagePrompt).then(() => {
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
        return { bg: "bg-amber-500/20", text: "text-amber-300", label: "Draft" };
      case "approved":
        return { bg: "bg-emerald-500/20", text: "text-emerald-300", label: "Finished" };
      case "in_review":
        return { bg: "bg-cyan-500/20", text: "text-cyan-300", label: "In Review" };
      case "archived":
        return { bg: "bg-slate-500/20", text: "text-slate-300", label: "Archived" };
      default:
        return { bg: "bg-slate-500/20", text: "text-slate-300", label: status };
    }
  };

  // Scene status indicator
  const SceneStatusIndicator = ({ status }: { status: SceneStatus }) => {
    switch (status) {
      case 'generating':
        return (
          <div className="w-4 h-4 rounded-full bg-black/60 flex items-center justify-center">
            <Loader2 size={10} className="text-cyan-400 animate-spin" />
          </div>
        );
      case 'ready':
        return null;
      case 'error':
        return (
          <div className="w-4 h-4 rounded-full bg-red-500/80 flex items-center justify-center">
            <AlertCircle size={10} className="text-white" />
          </div>
        );
      case 'pending':
      default:
        return (
          <div className="w-4 h-4 rounded-full bg-black/60 flex items-center justify-center">
            <div className="w-2 h-2 rounded-full bg-white/40" />
          </div>
        );
    }
  };

  // Loading state
  if (loading) {
    return (
      <div className="min-h-screen w-full bg-gradient-to-b from-black via-[#0a0a0f] to-[#0f0f18] text-white flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="w-10 h-10 animate-spin text-cyan-400" />
          <div className="text-white/60 text-sm">Loading project...</div>
        </div>
      </div>
    );
  }

  // Error state
  if (error || !project) {
    return (
      <div className="min-h-screen w-full bg-gradient-to-b from-black via-[#0a0a0f] to-[#0f0f18] text-white flex items-center justify-center">
        <div className="flex flex-col items-center gap-4 max-w-md text-center">
          <div className="w-16 h-16 rounded-2xl bg-red-500/10 border border-red-500/20 flex items-center justify-center mb-2">
            <AlertCircle size={28} className="text-red-400" />
          </div>
          <div className="text-red-400 text-lg font-medium">Failed to load project</div>
          <div className="text-white/50 text-sm">{error || "Project not found"}</div>
          <button
            onClick={onExit}
            className="mt-4 px-6 py-2.5 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl transition-colors text-sm"
          >
            ← Back to Studio
          </button>
        </div>
      </div>
    );
  }

  const statusBadge = getStatusBadge(project.status);

  return (
    <div className="min-h-screen w-full bg-gradient-to-b from-black via-[#0a0a0f] to-[#0f0f18] text-white flex flex-col">
      {/* Header - Compact & Cinematic */}
      <header className="flex items-center justify-between px-4 py-3 border-b border-white/5 bg-black/40 backdrop-blur-md">
        <div className="flex items-center gap-4">
          <button
            onClick={onExit}
            className="flex items-center gap-2 px-3 py-2 text-sm text-white/50 hover:text-white hover:bg-white/5 rounded-lg transition-all"
          >
            <ArrowLeft size={16} />
            <span className="hidden sm:inline">Back</span>
          </button>

          <div className="h-6 w-px bg-white/10" />

          <div>
            <h1 className="text-base font-semibold text-white">{project.title}</h1>
            <div className="text-xs text-white/40">
              {scenes.length} scene{scenes.length !== 1 ? "s" : ""} • Creator Studio
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Status Badge */}
          <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${statusBadge.bg} ${statusBadge.text}`}>
            {statusBadge.label}
          </span>

          {/* Save Indicator */}
          <div className="hidden sm:flex items-center gap-1.5 text-xs text-white/40 px-2">
            {isSaving ? (
              <>
                <Loader2 size={12} className="animate-spin" />
                <span>Saving...</span>
              </>
            ) : lastSaved ? (
              <>
                <Check size={12} className="text-emerald-400" />
                <span>Saved</span>
              </>
            ) : null}
          </div>

          {/* Story Outline Button */}
          <button
            onClick={() => setShowOutlinePanel(true)}
            className="flex items-center gap-2 px-3 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-sm transition-all"
            title="Story Outline"
          >
            <Wand2 size={14} className="text-cyan-400" />
            <span className="hidden sm:inline">Outline</span>
          </button>

          {/* Export Button */}
          <button
            className="flex items-center gap-2 px-3 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-sm transition-all"
            title="Export project"
          >
            <Download size={14} />
            <span className="hidden sm:inline">Export</span>
          </button>
        </div>
      </header>

      {/* Scene Chips Rail - Like Play Story */}
      {scenes.length > 0 && (
        <div className="w-full overflow-x-auto scrollbar-hide border-b border-white/5 bg-black/20">
          <div className="flex gap-2 px-4 py-3 min-w-max">
            {scenes.map((scene, idx) => {
              const isActive = idx === currentSceneIndex;
              const hasImage = Boolean(scene.imageUrl);
              const isHovered = hoveredSceneIdx === idx;
              const showDelete = isHovered && scenes.length > 1;

              return (
                <div
                  key={scene.id}
                  className="relative"
                  onMouseEnter={() => setHoveredSceneIdx(idx)}
                  onMouseLeave={() => setHoveredSceneIdx(null)}
                >
                  <button
                    onClick={() => setCurrentSceneIndex(idx)}
                    className={`
                      relative rounded-lg overflow-hidden transition-all duration-200
                      ${isActive
                        ? "ring-2 ring-cyan-400 ring-offset-2 ring-offset-black scale-105"
                        : "opacity-60 hover:opacity-100 hover:scale-102"
                      }
                    `}
                    type="button"
                    title={`Scene ${idx + 1}`}
                  >
                    <div className="w-20 h-12 flex items-center justify-center bg-white/5">
                      {hasImage ? (
                        <img
                          src={scene.imageUrl!}
                          alt={`Scene ${idx + 1}`}
                          className="w-full h-full object-cover"
                        />
                      ) : (
                        <ImageIcon size={16} className="text-white/20" />
                      )}
                    </div>

                    {/* Status indicator */}
                    <div className="absolute bottom-1 right-1">
                      <SceneStatusIndicator status={scene.status} />
                    </div>

                    {/* Scene number */}
                    {!scene.status || scene.status === 'ready' ? (
                      <div className="absolute bottom-1 left-1 text-[10px] bg-black/70 px-1.5 rounded font-medium">
                        {idx + 1}
                      </div>
                    ) : null}
                  </button>

                  {/* Delete button */}
                  {showDelete && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        deleteScene(scene.id);
                      }}
                      className="absolute -top-2 -right-2 w-5 h-5 rounded-full flex items-center justify-center transition-all transform hover:scale-110 bg-black/90 text-white/60 hover:text-white hover:bg-red-500 border border-white/10"
                      type="button"
                      title="Delete scene"
                    >
                      <X size={10} />
                    </button>
                  )}
                </div>
              );
            })}

            {/* Add Scene Chip */}
            <button
              onClick={generateNextScene}
              disabled={isGeneratingScene}
              className="w-20 h-12 rounded-lg border border-dashed border-white/20 hover:border-cyan-400/50 hover:bg-cyan-400/5 flex items-center justify-center transition-all disabled:opacity-40"
              title="Add scene"
            >
              {isGeneratingScene ? (
                <Loader2 size={16} className="text-cyan-400 animate-spin" />
              ) : (
                <Plus size={16} className="text-white/40" />
              )}
            </button>
          </div>
        </div>
      )}

      {/* Main Content */}
      {scenes.length === 0 ? (
        // Empty State - Cinematic
        <div className="flex-1 flex items-center justify-center p-8">
          <div className="max-w-md text-center">
            <div className="w-28 h-28 mx-auto mb-8 rounded-3xl bg-gradient-to-br from-cyan-500/20 via-blue-500/10 to-transparent border border-cyan-500/20 flex items-center justify-center">
              <ImageIcon size={48} className="text-cyan-400/60" />
            </div>

            <h2 className="text-2xl font-semibold text-white mb-3">Create Your First Scene</h2>
            <p className="text-white/50 mb-8 leading-relaxed">
              Your project is ready. Generate a scene to start bringing your story to life with AI-powered visuals.
            </p>

            <button
              onClick={generateFirstScene}
              disabled={isGeneratingScene}
              className="inline-flex items-center gap-3 px-8 py-4 bg-gradient-to-r from-cyan-500 to-blue-500 hover:from-cyan-400 hover:to-blue-400 disabled:opacity-50 disabled:cursor-not-allowed rounded-2xl text-base font-semibold shadow-lg shadow-cyan-500/25 transition-all"
            >
              {isGeneratingScene ? (
                <>
                  <Loader2 size={20} className="animate-spin" />
                  Generating...
                </>
              ) : (
                <>
                  <Play size={20} fill="currentColor" />
                  Generate First Scene
                </>
              )}
            </button>

            <p className="text-xs text-white/30 mt-6">
              Powered by AI • Based on your project settings
            </p>
          </div>
        </div>
      ) : (
        // Preview + Actions - Cinematic Layout
        <div className="flex-1 flex flex-col">
          {/* Preview Panel - Dominant */}
          <div className="flex-1 relative overflow-hidden">
            {/* Background gradient */}
            <div className="absolute inset-0 bg-gradient-to-b from-transparent via-[#0a0a0f] to-[#0f0f18]" />

            {/* Main preview area */}
            <div className="absolute inset-0 flex items-center justify-center p-6">
              {currentScene?.imageUrl ? (
                <div className="relative max-w-full max-h-full group">
                  <img
                    src={currentScene.imageUrl}
                    alt={`Scene ${currentSceneIndex + 1}`}
                    className="max-h-[calc(100vh-320px)] max-w-full object-contain rounded-xl shadow-2xl shadow-black/50 transition-all duration-500"
                  />

                  {/* Regenerate overlay on hover */}
                  <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity duration-300 bg-black/50 rounded-xl">
                    <button
                      onClick={() => generateImageForScene(currentScene.id, currentScene.imagePrompt, true)}
                      disabled={isGeneratingImage}
                      className="flex items-center gap-2 px-5 py-2.5 bg-white/10 backdrop-blur-md border border-white/20 rounded-full text-white text-sm font-medium hover:bg-white/20 transition-all disabled:opacity-50"
                      type="button"
                    >
                      <RefreshCw size={14} className={isGeneratingImage ? 'animate-spin' : ''} />
                      Regenerate Image
                    </button>
                  </div>

                  {/* Generating overlay */}
                  {isGeneratingImage && (
                    <div className="absolute inset-0 flex items-center justify-center bg-black/70 rounded-xl">
                      <div className="flex flex-col items-center gap-3">
                        <Loader2 size={36} className="text-cyan-400 animate-spin" />
                        <span className="text-white/70 text-sm">Generating image...</span>
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                /* Empty state when no image */
                <div className="flex flex-col items-center justify-center text-center p-8">
                  {isGeneratingImage ? (
                    <>
                      <Loader2 size={48} className="text-cyan-400 animate-spin mb-4" />
                      <p className="text-white/60 text-sm">Generating image...</p>
                      {currentScene?.imagePrompt && (
                        <p className="text-white/30 text-xs mt-2 max-w-md line-clamp-2">{currentScene.imagePrompt}</p>
                      )}
                    </>
                  ) : (
                    <>
                      <div className="w-20 h-20 rounded-2xl bg-white/5 border border-white/10 flex items-center justify-center mb-4">
                        <ImageIcon size={32} className="text-white/20" />
                      </div>
                      <p className="text-white/40 text-sm mb-4">No image for this scene</p>
                      <button
                        onClick={() => currentScene && generateImageForScene(currentScene.id, currentScene.imagePrompt)}
                        className="flex items-center gap-2 px-5 py-2.5 bg-cyan-500 hover:bg-cyan-400 rounded-full text-white text-sm font-medium transition-colors"
                        type="button"
                      >
                        Generate Image
                      </button>
                    </>
                  )}
                </div>
              )}
            </div>

            {/* Narration subtitle overlay */}
            {currentScene?.narration && (
              <div className="absolute bottom-8 left-0 right-0 flex justify-center px-8 pointer-events-none">
                <div className="bg-black/80 backdrop-blur-md px-6 py-4 rounded-xl max-w-3xl shadow-xl border border-white/5">
                  <p className="text-base md:text-lg text-white leading-relaxed text-center">
                    {currentScene.narration}
                  </p>
                </div>
              </div>
            )}
          </div>

          {/* Action Bar - Like Play Story */}
          <div className="border-t border-white/5 bg-black/60 backdrop-blur-md">
            <div className="max-w-4xl mx-auto px-4 py-4">
              <div className="flex items-center justify-between gap-4">
                {/* Left: Playback controls */}
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setCurrentSceneIndex((i) => Math.max(0, i - 1))}
                    disabled={currentSceneIndex === 0}
                    className="p-3 text-white/40 hover:text-white hover:bg-white/5 rounded-full transition-all disabled:opacity-30 disabled:cursor-not-allowed"
                    type="button"
                    title="Previous scene"
                  >
                    <SkipBack size={20} />
                  </button>

                  <button
                    onClick={() => setIsPlaying(!isPlaying)}
                    className="p-4 bg-cyan-500 hover:bg-cyan-400 rounded-full transition-all shadow-lg shadow-cyan-500/25"
                    type="button"
                    title={isPlaying ? "Pause" : "Play"}
                  >
                    {isPlaying ? <Pause size={24} /> : <Play size={24} fill="currentColor" />}
                  </button>

                  <button
                    onClick={() => setCurrentSceneIndex((i) => Math.min(scenes.length - 1, i + 1))}
                    disabled={currentSceneIndex >= scenes.length - 1}
                    className="p-3 text-white/40 hover:text-white hover:bg-white/5 rounded-full transition-all disabled:opacity-30 disabled:cursor-not-allowed"
                    type="button"
                    title="Next scene"
                  >
                    <SkipForward size={20} />
                  </button>
                </div>

                {/* Center: Scene progress bar */}
                <div className="flex-1 mx-4 hidden sm:block">
                  <div className="flex gap-1">
                    {scenes.map((_, i) => (
                      <button
                        key={i}
                        onClick={() => setCurrentSceneIndex(i)}
                        className={`flex-1 h-1.5 rounded-full transition-all ${
                          i === currentSceneIndex
                            ? 'bg-cyan-400'
                            : i < currentSceneIndex
                            ? 'bg-white/30'
                            : 'bg-white/10'
                        }`}
                        type="button"
                        title={`Scene ${i + 1}`}
                      />
                    ))}
                  </div>
                </div>

                {/* Right: Actions */}
                <div className="flex items-center gap-2">
                  {/* Edit Scene Button */}
                  <button
                    onClick={() => currentScene && openSceneEditor(currentScene)}
                    disabled={!currentScene}
                    className="flex items-center gap-2 px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-full text-sm transition-all disabled:opacity-40"
                    title="Edit scene"
                  >
                    <Edit3 size={14} />
                    <span className="hidden sm:inline">Edit</span>
                  </button>

                  {/* Generate Next Scene */}
                  <button
                    onClick={generateNextScene}
                    disabled={isGeneratingScene}
                    className="flex items-center gap-2 px-4 py-2 bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-300 border border-cyan-500/30 rounded-full text-sm transition-all disabled:opacity-50"
                    title="Generate next scene"
                  >
                    {isGeneratingScene ? (
                      <>
                        <Loader2 size={14} className="animate-spin" />
                        <span className="hidden sm:inline">Generating...</span>
                      </>
                    ) : (
                      <>
                        <Plus size={14} />
                        <span className="hidden sm:inline">Next Scene</span>
                      </>
                    )}
                  </button>

                  {/* TV Mode */}
                  <button
                    onClick={handleEnterTVMode}
                    disabled={scenes.length === 0}
                    className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-cyan-500/20 to-blue-500/20 hover:from-cyan-500/30 hover:to-blue-500/30 text-cyan-300 border border-cyan-500/30 rounded-full text-sm transition-all disabled:opacity-40"
                    type="button"
                    title="Watch in TV Mode"
                  >
                    <Monitor size={14} />
                    <span className="hidden sm:inline">TV Mode</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Scene Editor Modal */}
      {showSceneEditor && editingScene && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/80 backdrop-blur-sm" onClick={() => setShowSceneEditor(false)} />
          <div className="relative w-full max-w-2xl rounded-2xl border border-white/10 bg-[#0f0f18] shadow-2xl max-h-[90vh] overflow-y-auto">
            {/* Modal Header */}
            <div className="flex items-center justify-between p-5 border-b border-white/10">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-cyan-500/20 flex items-center justify-center">
                  <Edit3 size={18} className="text-cyan-400" />
                </div>
                <div>
                  <h2 className="text-lg font-semibold">Edit Scene {editingScene.idx + 1}</h2>
                  <p className="text-xs text-white/40">Update narration and prompts</p>
                </div>
              </div>
              <button
                onClick={() => setShowSceneEditor(false)}
                className="p-2 rounded-lg hover:bg-white/5 transition-colors"
              >
                <X size={18} className="text-white/40" />
              </button>
            </div>

            {/* Modal Content */}
            <div className="p-5 space-y-5">
              {/* Narration */}
              <div>
                <label className="flex items-center gap-2 text-sm font-medium text-white/70 mb-2">
                  <FileText size={14} />
                  Narration
                </label>
                <textarea
                  value={editNarration}
                  onChange={(e) => setEditNarration(e.target.value)}
                  className="w-full px-4 py-3 bg-black/40 border border-white/10 rounded-xl text-white placeholder-white/30 focus:border-cyan-500/50 focus:ring-1 focus:ring-cyan-500/25 focus:outline-none resize-none transition-all"
                  rows={3}
                  placeholder="Enter narration text for this scene..."
                />
              </div>

              {/* Image Prompt */}
              <div>
                <label className="flex items-center gap-2 text-sm font-medium text-white/70 mb-2">
                  <Sparkles size={14} />
                  Image Prompt
                </label>
                <textarea
                  value={editImagePrompt}
                  onChange={(e) => setEditImagePrompt(e.target.value)}
                  className="w-full px-4 py-3 bg-black/40 border border-white/10 rounded-xl text-white placeholder-white/30 focus:border-cyan-500/50 focus:ring-1 focus:ring-cyan-500/25 focus:outline-none resize-none transition-all"
                  rows={4}
                  placeholder="Describe the visual elements for image generation..."
                />
              </div>

              {/* Negative Prompt */}
              <div>
                <label className="text-sm font-medium text-white/70 mb-2 block">
                  Negative Prompt
                </label>
                <textarea
                  value={editNegativePrompt}
                  onChange={(e) => setEditNegativePrompt(e.target.value)}
                  className="w-full px-4 py-3 bg-black/40 border border-white/10 rounded-xl text-white placeholder-white/30 focus:border-cyan-500/50 focus:ring-1 focus:ring-cyan-500/25 focus:outline-none resize-none transition-all"
                  rows={2}
                  placeholder="Elements to avoid in the image..."
                />
              </div>

              {/* Model Selection */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="flex items-center gap-2 text-sm font-medium text-white/70 mb-2">
                    <Settings size={14} />
                    LLM Model
                  </label>
                  <select
                    value={selectedLLMModel}
                    onChange={(e) => setSelectedLLMModel(e.target.value)}
                    className="w-full px-3 py-2.5 bg-black/40 border border-white/10 rounded-xl text-white focus:border-cyan-500/50 focus:outline-none transition-all"
                  >
                    <option value="">Default</option>
                    {availableLLMModels.map((m) => (
                      <option key={m.id} value={m.id}>{m.name}</option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="flex items-center gap-2 text-sm font-medium text-white/70 mb-2">
                    <ImageIcon size={14} />
                    Image Model
                  </label>
                  <select
                    value={selectedImageModel}
                    onChange={(e) => setSelectedImageModel(e.target.value)}
                    className="w-full px-3 py-2.5 bg-black/40 border border-white/10 rounded-xl text-white focus:border-cyan-500/50 focus:outline-none transition-all"
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
                className="flex items-center gap-2 px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-sm transition-all"
              >
                <RefreshCw size={14} />
                Regenerate Image
              </button>

              <div className="flex items-center gap-3">
                <button
                  onClick={() => setShowSceneEditor(false)}
                  className="px-4 py-2 text-sm text-white/50 hover:text-white transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={saveSceneEdits}
                  disabled={isSavingScene}
                  className="flex items-center gap-2 px-5 py-2.5 bg-cyan-500 hover:bg-cyan-400 disabled:opacity-50 rounded-xl text-sm font-medium transition-all"
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
          <div className="absolute inset-0 bg-black/80 backdrop-blur-sm" onClick={() => setShowOutlinePanel(false)} />
          <div className="relative w-full max-w-3xl rounded-2xl border border-white/10 bg-[#0f0f18] shadow-2xl max-h-[90vh] overflow-y-auto">
            {/* Panel Header */}
            <div className="flex items-center justify-between p-5 border-b border-white/10">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-cyan-500/20 flex items-center justify-center">
                  <Wand2 size={18} className="text-cyan-400" />
                </div>
                <div>
                  <h2 className="text-lg font-semibold">Story Outline</h2>
                  <p className="text-xs text-white/40">AI-powered story structure</p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <button
                  onClick={generateStoryOutline}
                  disabled={isGeneratingOutline}
                  className="flex items-center gap-2 px-4 py-2 bg-cyan-500 hover:bg-cyan-400 disabled:opacity-50 rounded-xl text-sm font-medium transition-all"
                >
                  {isGeneratingOutline ? (
                    <>
                      <Loader2 size={14} className="animate-spin" />
                      Generating...
                    </>
                  ) : (
                    <>
                      <Sparkles size={14} />
                      {storyOutline ? "Regenerate" : "Generate"}
                    </>
                  )}
                </button>
                <button
                  onClick={() => setShowOutlinePanel(false)}
                  className="p-2 rounded-lg hover:bg-white/5 transition-colors"
                >
                  <X size={18} className="text-white/40" />
                </button>
              </div>
            </div>

            {/* Panel Content */}
            <div className="p-5">
              {storyOutline ? (
                <div className="space-y-6">
                  {/* Story Arc */}
                  <div className="p-4 bg-black/30 rounded-xl border border-white/5">
                    <h3 className="text-sm font-semibold text-cyan-400 mb-3">Story Arc</h3>
                    <div className="grid grid-cols-5 gap-2 text-xs">
                      {['beginning', 'rising_action', 'climax', 'falling_action', 'resolution'].map((key, i) => (
                        <div key={key} className="p-2.5 bg-white/5 rounded-lg">
                          <div className="text-white/40 mb-1 capitalize">{['Beginning', 'Rising', 'Climax', 'Falling', 'Resolution'][i]}</div>
                          <div className="text-white/80">{(storyOutline.story_arc as any)?.[key] || "—"}</div>
                        </div>
                      ))}
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
                            className={`p-4 rounded-xl border transition-all ${
                              alreadyGenerated
                                ? "bg-emerald-500/10 border-emerald-500/30"
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
                                    <span className="text-xs px-2 py-0.5 bg-emerald-500/20 text-emerald-400 rounded-full">
                                      Generated
                                    </span>
                                  )}
                                </div>
                                <p className="text-sm text-white/50 mb-2">{scene.description}</p>
                                <p className="text-xs text-white/30 italic">"{scene.narration}"</p>
                              </div>
                              {!alreadyGenerated && scenes.length === idx && (
                                <button
                                  onClick={() => {
                                    generateSceneFromOutline(idx);
                                    setShowOutlinePanel(false);
                                  }}
                                  disabled={isGeneratingScene}
                                  className="flex items-center gap-1.5 px-3 py-1.5 bg-cyan-500 hover:bg-cyan-400 disabled:opacity-50 rounded-lg text-xs font-medium transition-all"
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
                <div className="text-center py-16">
                  <div className="w-20 h-20 mx-auto rounded-2xl bg-white/5 border border-white/10 flex items-center justify-center mb-6">
                    <Wand2 size={32} className="text-white/20" />
                  </div>
                  <h3 className="text-lg font-medium text-white mb-2">No Outline Yet</h3>
                  <p className="text-white/40 mb-8 max-w-md mx-auto">
                    Generate an AI-powered story outline based on your project settings.
                    This creates a complete story arc with scene-by-scene planning.
                  </p>
                  <button
                    onClick={generateStoryOutline}
                    disabled={isGeneratingOutline}
                    className="inline-flex items-center gap-3 px-8 py-4 bg-gradient-to-r from-cyan-500 to-blue-500 hover:from-cyan-400 hover:to-blue-400 disabled:opacity-50 rounded-2xl font-semibold shadow-lg shadow-cyan-500/25 transition-all"
                  >
                    {isGeneratingOutline ? (
                      <>
                        <Loader2 size={20} className="animate-spin" />
                        Generating Outline...
                      </>
                    ) : (
                      <>
                        <Sparkles size={20} />
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

      {/* Custom scrollbar hide */}
      <style>{`
        .scrollbar-hide::-webkit-scrollbar { display: none; }
        .scrollbar-hide { -ms-overflow-style: none; scrollbar-width: none; }
        .line-clamp-2 {
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
          overflow: hidden;
        }
      `}</style>
    </div>
  );
}

export default CreatorStudioEditor;
