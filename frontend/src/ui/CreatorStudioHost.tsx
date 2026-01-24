import React, { useEffect, useState, useCallback } from "react";
import { ArrowLeft, X, ChevronDown } from "lucide-react";
import { useStudioStore } from "./studio/stores/studioStore";
import { CreatorStudioEditor } from "./CreatorStudioEditor";

type PlatformPreset = "youtube_16_9" | "shorts_9_16" | "slides_16_9";
type ContentRating = "sfw" | "mature";
type AvailableModel = { id: string; name: string };

interface CreatorStudioHostProps {
  backendUrl: string;
  apiKey?: string;
  /** Optional project ID to open in editor mode */
  projectId?: string;
  /** Called when user wants to return to Play Mode landing page */
  onExit: () => void;
}

/**
 * CreatorStudioHost - Handles both wizard (new) and editor (existing) modes
 *
 * - If projectId is provided: opens the editor for that project
 * - If no projectId: shows the New Project wizard
 * - After wizard creates a project: switches to editor mode
 */
export function CreatorStudioHost({
  backendUrl,
  apiKey,
  projectId: initialProjectId,
  onExit,
}: CreatorStudioHostProps) {
  const authKey = (apiKey || "").trim();

  // Mode: "wizard" for creating new, "editor" for existing project
  const [mode, setMode] = useState<"wizard" | "editor">(initialProjectId ? "editor" : "wizard");
  const [currentProjectId, setCurrentProjectId] = useState<string | undefined>(initialProjectId);
  const [isNewlyCreated, setIsNewlyCreated] = useState(false);
  const [projectSettings, setProjectSettings] = useState({ targetSceneCount: 8, sceneDuration: 5, llmModel: "" });

  // Bootstrap connection info for API calls
  useEffect(() => {
    const store = useStudioStore.getState();
    if (store.setConnection) {
      store.setConnection(backendUrl, authKey);
    }
  }, [backendUrl, authKey]);

  // If we have a project ID, show the editor
  if (mode === "editor" && currentProjectId) {
    return (
      <CreatorStudioEditor
        projectId={currentProjectId}
        backendUrl={backendUrl}
        apiKey={apiKey}
        onExit={onExit}
        autoGenerateFirst={isNewlyCreated}
        targetSceneCount={projectSettings.targetSceneCount}
        defaultLLMModel={projectSettings.llmModel}
      />
    );
  }

  // Otherwise, show the wizard
  return (
    <CreatorStudioWizard
      backendUrl={backendUrl}
      apiKey={apiKey}
      onExit={onExit}
      onProjectCreated={(projectId, settings) => {
        // Switch to editor mode with the new project
        setCurrentProjectId(projectId);
        setIsNewlyCreated(true);  // Flag for auto-generating first scene
        setProjectSettings(settings);
        setMode("editor");
      }}
    />
  );
}

// ============================================================================
// Wizard Component (extracted for clarity)
// ============================================================================

interface WizardProps {
  backendUrl: string;
  apiKey?: string;
  onExit: () => void;
  onProjectCreated: (projectId: string, settings: { targetSceneCount: number; sceneDuration: number; llmModel: string }) => void;
}

function CreatorStudioWizard({
  backendUrl,
  apiKey,
  onExit,
  onProjectCreated,
}: WizardProps) {
  const authKey = (apiKey || "").trim();

  // Wizard state - 5 steps: Details, Visuals, Checks, Review, Outline
  const [step, setStep] = useState<1 | 2 | 3 | 4 | 5>(1);

  // Core fields
  const [title, setTitle] = useState("");
  const [logline, setLogline] = useState("");
  const [platformPreset, setPlatformPreset] = useState<PlatformPreset>("youtube_16_9");
  const [contentRating, setContentRating] = useState<ContentRating>("sfw");
  const [allowMature, setAllowMature] = useState(false);
  const [localOnly, setLocalOnly] = useState(true);

  // Wizard fields
  const [goal, setGoal] = useState<"Entertain" | "Educate" | "Inspire">("Educate");
  const [tones, setTones] = useState<string[]>(["Documentary", "Calm"]);
  const [visualStyle, setVisualStyle] = useState<"Cinematic" | "Digital Art" | "Anime">("Cinematic");
  const [lockIdentity, setLockIdentity] = useState(true);

  // Episode/scene configuration
  const [targetSceneCount, setTargetSceneCount] = useState(8);
  const [sceneDuration, setSceneDuration] = useState(5);

  // LLM Model selection
  const [availableLLMModels, setAvailableLLMModels] = useState<AvailableModel[]>([]);
  const [selectedLLMModel, setSelectedLLMModel] = useState("");
  const [loadingModels, setLoadingModels] = useState(false);

  // Mature consent modal
  const [showMatureModal, setShowMatureModal] = useState(false);
  const [matureConsentChecked, setMatureConsentChecked] = useState(false);

  // UI state
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Outline generation state (Step 5)
  const [generatingOutline, setGeneratingOutline] = useState(false);
  const [generatedOutline, setGeneratedOutline] = useState<any>(null);
  const [tempProjectId, setTempProjectId] = useState<string | null>(null);

  // Fetch available LLM models
  const fetchLLMModels = useCallback(async () => {
    setLoadingModels(true);
    try {
      const url = `${backendUrl.replace(/\/+$/, "")}/models?provider=ollama`;
      const res = await fetch(url, {
        headers: authKey ? { "x-api-key": authKey } : {},
      });
      if (res.ok) {
        const data = await res.json();
        if (data.models) {
          const models = data.models.map((m: { id: string; name?: string }) => ({
            id: m.id,
            name: m.name || m.id,
          }));
          setAvailableLLMModels(models);
          // Auto-select first model if none selected
          if (!selectedLLMModel && models.length > 0) {
            // Prefer llama3:8b if available, otherwise first model
            const preferred = models.find((m: AvailableModel) => m.id === "llama3:8b") || models[0];
            setSelectedLLMModel(preferred.id);
          }
        }
      }
    } catch (e) {
      console.log("[Wizard] Failed to fetch LLM models:", e);
    } finally {
      setLoadingModels(false);
    }
  }, [backendUrl, authKey, selectedLLMModel]);

  // Fetch models on mount
  useEffect(() => {
    fetchLLMModels();
  }, [fetchLLMModels]);

  // Build tags for backend
  const tagsForBackend = React.useMemo(() => {
    const t: string[] = [];
    if (goal) t.push(`goal:${goal.toLowerCase()}`);
    if (visualStyle) t.push(`visual:${visualStyle.toLowerCase().replaceAll(" ", "_")}`);
    if (tones.length) t.push(...tones.map((x) => `tone:${x.toLowerCase().replaceAll(" ", "_")}`));
    if (lockIdentity) t.push("lock:identity");
    // Include episode configuration
    t.push(`scenes:${targetSceneCount}`);
    t.push(`duration:${sceneDuration}`);
    // Include selected LLM model
    if (selectedLLMModel) t.push(`llm:${selectedLLMModel}`);
    return Array.from(new Set(t));
  }, [goal, visualStyle, tones, lockIdentity, targetSceneCount, sceneDuration, selectedLLMModel]);

  const canProceedStep1 = title.trim().length > 0;
  const canCreate = title.trim().length > 0 && !loading && generatedOutline;

  function goTo(next: 1 | 2 | 3 | 4 | 5) {
    setError(null);
    setStep(next);
  }

  function canNav(target: number) {
    // Can navigate to previous steps or the next step
    // But step 5 (Outline) requires going through step 4 first
    if (target === 5) return step === 5 || (step === 4 && generatedOutline);
    return target < step || target === step + 1;
  }

  function toggleTone(t: string) {
    setTones((prev) => {
      const has = prev.includes(t);
      if (has) return prev.filter((x) => x !== t);
      return [...prev, t];
    });
  }

  function requestMature() {
    setShowMatureModal(true);
    setMatureConsentChecked(false);
  }

  function confirmMatureEnabled() {
    if (!matureConsentChecked) return;
    setShowMatureModal(false);
    setContentRating("mature");
    setAllowMature(true);
    setLocalOnly(true);
  }

  function cancelMature() {
    setShowMatureModal(false);
    setMatureConsentChecked(false);
  }

  // Create project and generate outline (transition from Step 4 to Step 5)
  async function handleGenerateOutline() {
    if (!title.trim()) {
      setError("Project name is required.");
      setStep(1);
      return;
    }

    setGeneratingOutline(true);
    setError(null);
    setGeneratedOutline(null);

    try {
      // Step 1: Create the project first (if not already created)
      let projectId = tempProjectId;

      if (!projectId) {
        const url = `${backendUrl.replace(/\/+$/, "")}/studio/videos`;
        const payload = {
          title: title.trim(),
          logline: logline.trim(),
          tags: tagsForBackend,
          platformPreset,
          targetDurationSec: targetSceneCount * sceneDuration,
          contentRating,
          policyMode: contentRating === "mature" ? "restricted" : "youtube_safe",
          providerPolicy: {
            allowMature: contentRating === "mature" ? !!allowMature : false,
            allowedProviders: ["ollama"],
            localOnly: contentRating === "mature" ? !!localOnly : true,
          },
        };

        const res = await fetch(url, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(authKey ? { "x-api-key": authKey } : {}),
          },
          body: JSON.stringify(payload),
        });

        if (!res.ok) {
          const text = await res.text().catch(() => "");
          throw new Error(`HTTP ${res.status}${text ? `: ${text}` : ""}`);
        }

        const data = await res.json();
        projectId = data.video?.id;

        if (!projectId) {
          throw new Error("No project ID returned from server");
        }

        setTempProjectId(projectId);
      }

      // Step 2: Generate the outline
      const outlineUrl = `${backendUrl.replace(/\/+$/, "")}/studio/videos/${projectId}/generate-outline`;
      const outlinePayload = {
        target_scenes: targetSceneCount,
        scene_duration: sceneDuration,
        ollama_model: selectedLLMModel || undefined,
      };

      const outlineRes = await fetch(outlineUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(authKey ? { "x-api-key": authKey } : {}),
        },
        body: JSON.stringify(outlinePayload),
      });

      if (!outlineRes.ok) {
        const text = await outlineRes.text().catch(() => "");
        throw new Error(`Failed to generate outline: HTTP ${outlineRes.status}${text ? `: ${text}` : ""}`);
      }

      const outlineData = await outlineRes.json();
      if (!outlineData.ok || !outlineData.outline) {
        throw new Error("Outline generation failed - no outline returned");
      }

      setGeneratedOutline(outlineData.outline);
      setStep(5); // Move to outline review step

    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setGeneratingOutline(false);
    }
  }

  async function handleCreate() {
    // Project should already be created during outline generation
    if (!tempProjectId) {
      setError("Project not created yet. Please generate outline first.");
      return;
    }

    if (!generatedOutline) {
      setError("No outline generated. Please generate outline first.");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      // Project already exists with outline - just open it in the editor
      onProjectCreated(tempProjectId, { targetSceneCount, sceneDuration, llmModel: selectedLLMModel });
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen w-full bg-[#0f0f0f] text-[#f1f1f1] flex flex-col">
      {/* Header with Exit Button */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-[#2a2a2a] bg-[#1a1a1a]">
        <button
          className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-[#aaa] hover:text-[#f1f1f1] hover:bg-[#2a2a2a] rounded-lg transition-colors"
          onClick={onExit}
          title="Return to Studio"
        >
          <ArrowLeft size={16} />
          <span>Back to Studio</span>
        </button>
        <span className="text-sm font-semibold text-[#f1f1f1]">Creator Studio</span>
        <div className="w-[120px]" /> {/* Spacer for centering */}
      </div>

      {/* Mature Consent Modal */}
      {showMatureModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/80" onClick={cancelMature} />
          <div className="relative w-full max-w-md rounded-lg border border-[#3f3f3f] bg-[#1f1f1f] shadow-2xl">
            <div className="p-5">
              <div className="text-lg font-medium">Enable Mature Mode?</div>
              <div className="mt-2 text-sm text-[#aaa] leading-relaxed">
                This enables adult/mature generation for this project. Use only where legal and compliant with platform policies.
              </div>

              <div className="mt-4 rounded border border-[#3f3f3f] bg-[#121212] p-4">
                <div className="text-sm font-medium">This allows:</div>
                <ul className="mt-2 text-sm text-[#aaa] space-y-1 list-disc pl-5">
                  <li>Adult/NSFW image generation</li>
                  <li>Mature story themes</li>
                  <li>Access to mature presets (when enabled server-side)</li>
                </ul>
              </div>

              <label className="mt-4 flex items-start gap-3 cursor-pointer select-none">
                <input
                  type="checkbox"
                  className="mt-1 w-[18px] h-[18px] accent-[#3ea6ff]"
                  checked={matureConsentChecked}
                  onChange={(e) => setMatureConsentChecked(e.target.checked)}
                />
                <div className="text-sm">
                  I am 18+ and I consent to enable Mature Mode for this project.
                </div>
              </label>

              <div className="mt-5 flex items-center justify-end gap-3">
                <button
                  className="px-6 py-2 text-sm font-medium text-[#aaa] hover:text-[#f1f1f1] uppercase"
                  onClick={cancelMature}
                >
                  Cancel
                </button>
                <button
                  className="px-6 py-2 text-sm font-semibold bg-[#3ea6ff] text-black rounded-sm hover:bg-[#6ebbff] disabled:opacity-50 disabled:cursor-not-allowed uppercase"
                  disabled={!matureConsentChecked}
                  onClick={confirmMatureEnabled}
                >
                  Enable
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Main Wizard Content */}
      <div className="flex-1 flex items-center justify-center p-5">
        <div className="w-full max-w-[900px] bg-[#1f1f1f] rounded-lg border border-[#3f3f3f] shadow-[0_4px_20px_rgba(0,0,0,0.5)] overflow-hidden flex flex-col" style={{ height: "min(80vh, 700px)", minHeight: "600px" }}>
          {/* Wizard Header */}
          <div className="px-6 py-4 border-b border-[#3f3f3f] flex items-center justify-between">
            <div className="text-xl font-medium">New Project</div>
            <button
              className="p-2 rounded-full text-[#aaa] hover:text-[#f1f1f1] hover:bg-[#3f3f3f] transition-colors"
              onClick={onExit}
              title="Close wizard"
            >
              <X size={20} />
            </button>
          </div>

          {/* Horizontal Stepper */}
          <div className="flex justify-center py-5 border-b border-[#3f3f3f] bg-[#1f1f1f]">
            <StepNav step={step} mine={1} label="Details" canNav={canNav(1)} onClick={() => canNav(1) && goTo(1)} totalSteps={5} />
            <StepNav step={step} mine={2} label="Visuals" canNav={canNav(2)} onClick={() => canNav(2) && goTo(2)} totalSteps={5} />
            <StepNav step={step} mine={3} label="Checks" canNav={canNav(3)} onClick={() => canNav(3) && goTo(3)} totalSteps={5} />
            <StepNav step={step} mine={4} label="Review" canNav={canNav(4)} onClick={() => canNav(4) && goTo(4)} totalSteps={5} />
            <StepNav step={step} mine={5} label="Outline" canNav={canNav(5)} onClick={() => canNav(5) && goTo(5)} totalSteps={5} />
          </div>

          {/* Content Area */}
          <div className="flex-1 overflow-y-auto px-12 py-8">
            {/* STEP 1: Details */}
            {step === 1 && (
              <div>
                <h1 className="text-2xl font-medium">Details</h1>
                <p className="mt-2 text-sm text-[#aaa]">Give your project a title and choose the format.</p>

                <div className="mt-6">
                  <label className="block text-xs font-medium text-[#aaa] mb-2">Title (required)</label>
                  <input
                    type="text"
                    className="w-full px-3 py-3 bg-[#121212] border border-[#3f3f3f] rounded text-base outline-none focus:border-[#3ea6ff]"
                    placeholder="Add a title that describes your content"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                  />
                </div>

                <div className="mt-6">
                  <label className="block text-xs font-medium text-[#aaa] mb-3">Format</label>
                  <div className="grid grid-cols-3 gap-4">
                    <FormatCard
                      icon="TV"
                      title="YouTube Video"
                      sub="16:9 Landscape"
                      selected={platformPreset === "youtube_16_9"}
                      onClick={() => setPlatformPreset("youtube_16_9")}
                    />
                    <FormatCard
                      icon="Phone"
                      title="YouTube Short"
                      sub="9:16 Vertical"
                      selected={platformPreset === "shorts_9_16"}
                      onClick={() => setPlatformPreset("shorts_9_16")}
                    />
                    <FormatCard
                      icon="Image"
                      title="Slides"
                      sub="16:9 Presentation"
                      selected={platformPreset === "slides_16_9"}
                      onClick={() => setPlatformPreset("slides_16_9")}
                    />
                  </div>
                </div>

                <div className="mt-6">
                  <label className="block text-xs font-medium text-[#aaa] mb-3">Intent</label>
                  <div className="flex gap-2 flex-wrap">
                    {(["Entertain", "Educate", "Inspire"] as const).map((g) => (
                      <Chip key={g} active={goal === g} onClick={() => setGoal(g)}>
                        {g}
                      </Chip>
                    ))}
                  </div>
                </div>

                {/* Episode Configuration */}
                <div className="mt-6 grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-medium text-[#aaa] mb-2">Scenes per Episode</label>
                    <div className="flex gap-2 flex-wrap">
                      {[4, 6, 8, 10, 12].map((count) => (
                        <button
                          key={count}
                          type="button"
                          onClick={() => setTargetSceneCount(count)}
                          className={[
                            "px-4 py-2 rounded text-sm border transition-colors",
                            targetSceneCount === count
                              ? "bg-[#3ea6ff] text-black border-transparent font-medium"
                              : "bg-[#282828] text-[#aaa] border-transparent hover:bg-[#3f3f3f] hover:text-[#f1f1f1]",
                          ].join(" ")}
                        >
                          {count}
                        </button>
                      ))}
                    </div>
                    <p className="text-xs text-[#777] mt-1">
                      ~{targetSceneCount * sceneDuration}s total ({Math.floor(targetSceneCount * sceneDuration / 60)}:{String((targetSceneCount * sceneDuration) % 60).padStart(2, '0')})
                    </p>
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-[#aaa] mb-2">Scene Duration (sec)</label>
                    <div className="flex gap-2 flex-wrap">
                      {[3, 5, 7, 10].map((dur) => (
                        <button
                          key={dur}
                          type="button"
                          onClick={() => setSceneDuration(dur)}
                          className={[
                            "px-4 py-2 rounded text-sm border transition-colors",
                            sceneDuration === dur
                              ? "bg-[#3ea6ff] text-black border-transparent font-medium"
                              : "bg-[#282828] text-[#aaa] border-transparent hover:bg-[#3f3f3f] hover:text-[#f1f1f1]",
                          ].join(" ")}
                        >
                          {dur}s
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* STEP 2: Visuals */}
            {step === 2 && (
              <div>
                <h1 className="text-2xl font-medium">Visual Elements</h1>
                <p className="mt-2 text-sm text-[#aaa]">Choose the aesthetic for your generated content.</p>

                <div className="mt-6">
                  <label className="block text-xs font-medium text-[#aaa] mb-3">Style Preset</label>
                  <div className="grid grid-cols-3 gap-4">
                    <FormatCard
                      icon="Camera"
                      title="Cinematic"
                      sub="High fidelity realism"
                      selected={visualStyle === "Cinematic"}
                      onClick={() => setVisualStyle("Cinematic")}
                    />
                    <FormatCard
                      icon="Palette"
                      title="Digital Art"
                      sub="Stylized illustration"
                      selected={visualStyle === "Digital Art"}
                      onClick={() => setVisualStyle("Digital Art")}
                    />
                    <FormatCard
                      icon="Star"
                      title="Anime"
                      sub="Japanese animation style"
                      selected={visualStyle === "Anime"}
                      onClick={() => setVisualStyle("Anime")}
                    />
                  </div>
                </div>

                <div className="mt-6">
                  <label className="block text-xs font-medium text-[#aaa] mb-3">Mood & Tone</label>
                  <div className="flex gap-2 flex-wrap">
                    {["Documentary", "Dramatic", "Calm", "Upbeat", "Dark"].map((t) => (
                      <Chip key={t} active={tones.includes(t)} onClick={() => toggleTone(t)}>
                        {t}
                      </Chip>
                    ))}
                  </div>
                </div>

                {/* LLM Model Selection */}
                <div className="mt-6">
                  <label className="block text-xs font-medium text-[#aaa] mb-3">AI Story Model</label>
                  <p className="text-xs text-[#777] mb-3">Select the AI model for generating outlines and narration</p>
                  <div className="relative">
                    <select
                      value={selectedLLMModel}
                      onChange={(e) => setSelectedLLMModel(e.target.value)}
                      className="w-full px-4 py-3 bg-[#121212] border border-[#3f3f3f] rounded text-base outline-none focus:border-[#3ea6ff] appearance-none cursor-pointer"
                      disabled={loadingModels}
                    >
                      {loadingModels ? (
                        <option value="">Loading models...</option>
                      ) : availableLLMModels.length === 0 ? (
                        <option value="">No models available</option>
                      ) : (
                        availableLLMModels.map((m) => (
                          <option key={m.id} value={m.id}>
                            {m.name}
                          </option>
                        ))
                      )}
                    </select>
                    <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-5 h-5 text-[#aaa] pointer-events-none" />
                  </div>
                  {availableLLMModels.length === 0 && !loadingModels && (
                    <p className="text-xs text-[#ff6b6b] mt-2">
                      No Ollama models found. Make sure Ollama is running with at least one model pulled.
                    </p>
                  )}
                </div>
              </div>
            )}

            {/* STEP 3: Checks */}
            {step === 3 && (
              <div>
                <h1 className="text-2xl font-medium">Checks</h1>
                <p className="mt-2 text-sm text-[#aaa]">We'll check your project for consistency and policy compliance.</p>

                <div className="mt-6 bg-[#282828] border border-[#3f3f3f] rounded">
                  <CheckRow
                    checked={lockIdentity}
                    title="Consistency Lock"
                    desc="Keep characters and environments stable across scenes."
                    onToggle={() => setLockIdentity((v) => !v)}
                  />
                  <CheckRow
                    checked={contentRating === "sfw"}
                    title="Policy Filter (SFW)"
                    desc="Strictly filter explicit content. Uncheck for Mature mode (18+)."
                    onToggle={() => {
                      if (contentRating === "sfw") {
                        requestMature();
                      } else {
                        setContentRating("sfw");
                        setAllowMature(false);
                      }
                    }}
                    last
                  />
                </div>

                {contentRating === "mature" && (
                  <div className="mt-4 p-4 bg-[#8B5CF6]/10 border border-[#8B5CF6]/30 rounded text-sm">
                    <span className="font-medium text-[#A78BFA]">Mature Mode Enabled</span>
                    <span className="text-[#aaa] ml-2">- This project may generate explicit content.</span>
                  </div>
                )}

                <div className="mt-5 text-sm text-[#aaa] flex items-center gap-2">
                  <span className="text-[#2ba640]">OK</span> Checks complete. No issues found.
                </div>
              </div>
            )}

            {/* STEP 4: Review */}
            {step === 4 && (
              <div>
                <h1 className="text-2xl font-medium">Review</h1>
                <p className="mt-2 text-sm text-[#aaa]">Review your settings, then generate your story outline.</p>

                <div className="mt-6 bg-[#121212] border border-[#3f3f3f] rounded p-5">
                  <ReviewLine label="Title" value={title.trim() || "Untitled Project"} />
                  <ReviewLine label="Format" value={platformPresetToLabel(platformPreset)} />
                  <ReviewLine label="Style" value={`${visualStyle} (${tones.length ? tones.join(", ") : "Default"})`} />
                  <ReviewLine
                    label="Episode Length"
                    value={`${targetSceneCount} scenes × ${sceneDuration}s = ~${Math.floor(targetSceneCount * sceneDuration / 60)}:${String((targetSceneCount * sceneDuration) % 60).padStart(2, '0')}`}
                  />
                  <ReviewLine label="AI Model" value={selectedLLMModel || "Default"} />
                  <ReviewLine
                    label="Safety"
                    value={contentRating === "sfw" ? "Safe (SFW)" : "Mature (18+)"}
                    color={contentRating === "sfw" ? "text-[#2ba640]" : "text-[#8B5CF6]"}
                    last
                  />
                </div>

                {error && (
                  <div className="mt-4 p-4 bg-red-500/10 border border-red-500/30 rounded text-sm text-red-300">
                    {error}
                  </div>
                )}

                <div className="mt-6">
                  <label className="block text-xs font-medium text-[#aaa] mb-2">Description (optional)</label>
                  <textarea
                    className="w-full px-3 py-3 bg-[#121212] border border-[#3f3f3f] rounded text-base outline-none focus:border-[#3ea6ff] resize-none"
                    rows={2}
                    placeholder="A short description of your project..."
                    value={logline}
                    onChange={(e) => setLogline(e.target.value)}
                  />
                </div>

                <div className="mt-4 text-sm">
                  <div className="text-[#f1f1f1]">Private project</div>
                  <div className="text-[#aaa]">Only you can view and edit this project initially.</div>
                </div>
              </div>
            )}

            {/* STEP 5: Outline Generation & Review */}
            {step === 5 && (
              <div>
                <h1 className="text-2xl font-medium">Story Outline</h1>
                <p className="mt-2 text-sm text-[#aaa]">
                  {generatingOutline
                    ? "Generating your story outline with AI..."
                    : "Review your AI-generated story outline before creating the project."}
                </p>

                {/* Generation Loading State */}
                {generatingOutline && (
                  <div className="mt-8 flex flex-col items-center justify-center py-12">
                    <div className="w-16 h-16 border-4 border-[#3ea6ff] border-t-transparent rounded-full animate-spin" />
                    <p className="mt-4 text-[#aaa]">Generating {targetSceneCount} scenes...</p>
                    <p className="mt-2 text-xs text-[#666]">This may take a minute depending on your AI model</p>
                  </div>
                )}

                {/* Error State */}
                {error && !generatingOutline && (
                  <div className="mt-4 p-4 bg-red-500/10 border border-red-500/30 rounded text-sm text-red-300">
                    {error}
                    <button
                      className="ml-4 underline hover:text-red-200"
                      onClick={() => {
                        setError(null);
                        handleGenerateOutline();
                      }}
                    >
                      Try Again
                    </button>
                  </div>
                )}

                {/* Generated Outline Display */}
                {generatedOutline && !generatingOutline && (
                  <div className="mt-6 space-y-4">
                    {/* Story Arc Summary */}
                    {generatedOutline.story_arc && (
                      <div className="bg-[#121212] border border-[#3f3f3f] rounded p-4">
                        <div className="text-sm font-medium text-[#3ea6ff] mb-2">Story Arc</div>
                        <div className="text-xs text-[#aaa] space-y-1">
                          <div><span className="text-[#f1f1f1]">Beginning:</span> {generatedOutline.story_arc.beginning}</div>
                          <div><span className="text-[#f1f1f1]">Rising Action:</span> {generatedOutline.story_arc.rising_action}</div>
                          <div><span className="text-[#f1f1f1]">Climax:</span> {generatedOutline.story_arc.climax}</div>
                          <div><span className="text-[#f1f1f1]">Resolution:</span> {generatedOutline.story_arc.resolution}</div>
                        </div>
                      </div>
                    )}

                    {/* Scenes List */}
                    <div className="bg-[#121212] border border-[#3f3f3f] rounded overflow-hidden">
                      <div className="px-4 py-3 border-b border-[#3f3f3f] flex items-center justify-between">
                        <span className="text-sm font-medium">Scenes ({generatedOutline.scenes?.length || 0})</span>
                        <span className="text-xs text-[#aaa]">Click a scene to preview</span>
                      </div>
                      <div className="max-h-[300px] overflow-y-auto">
                        {generatedOutline.scenes?.map((scene: any, idx: number) => (
                          <div key={idx} className="px-4 py-3 border-b border-[#2a2a2a] last:border-b-0 hover:bg-[#1a1a1a] transition-colors">
                            <div className="flex items-start gap-3">
                              <div className="w-8 h-8 rounded-full bg-[#3ea6ff]/20 text-[#3ea6ff] flex items-center justify-center text-sm font-medium flex-shrink-0">
                                {scene.scene_number || idx + 1}
                              </div>
                              <div className="flex-1 min-w-0">
                                <div className="text-sm font-medium text-[#f1f1f1]">{scene.title}</div>
                                <div className="text-xs text-[#aaa] mt-1 line-clamp-2">{scene.narration}</div>
                                <details className="mt-2">
                                  <summary className="text-xs text-[#666] cursor-pointer hover:text-[#aaa]">
                                    View image prompt
                                  </summary>
                                  <div className="mt-2 p-2 bg-[#0a0a0a] rounded text-xs text-[#888] leading-relaxed">
                                    {scene.image_prompt}
                                  </div>
                                </details>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Regenerate Option */}
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-[#aaa]">Not happy with the outline?</span>
                      <button
                        className="text-[#3ea6ff] hover:underline"
                        onClick={() => {
                          setGeneratedOutline(null);
                          handleGenerateOutline();
                        }}
                        disabled={generatingOutline}
                      >
                        Regenerate Outline
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="px-6 py-4 border-t border-[#3f3f3f] flex justify-end gap-3">
            {step > 1 && step !== 5 && (
              <button
                className="px-6 py-2 text-sm font-medium text-[#aaa] hover:text-[#f1f1f1] uppercase"
                onClick={() => goTo((step - 1) as 1 | 2 | 3 | 4 | 5)}
                disabled={loading || generatingOutline}
              >
                Back
              </button>
            )}
            {step === 5 && !generatingOutline && (
              <button
                className="px-6 py-2 text-sm font-medium text-[#aaa] hover:text-[#f1f1f1] uppercase"
                onClick={() => goTo(4)}
                disabled={loading}
              >
                Back to Review
              </button>
            )}
            {step < 4 ? (
              <button
                className="px-6 py-2 text-sm font-semibold bg-[#3ea6ff] text-black rounded-sm hover:bg-[#6ebbff] disabled:opacity-50 disabled:cursor-not-allowed uppercase"
                disabled={step === 1 && !canProceedStep1}
                onClick={() => goTo((step + 1) as 1 | 2 | 3 | 4 | 5)}
              >
                Next
              </button>
            ) : step === 4 ? (
              <button
                className="px-6 py-2 text-sm font-semibold bg-[#3ea6ff] text-black rounded-sm hover:bg-[#6ebbff] disabled:opacity-50 disabled:cursor-not-allowed uppercase"
                disabled={generatingOutline || !title.trim()}
                onClick={handleGenerateOutline}
              >
                {generatingOutline ? "Generating..." : "Generate Outline"}
              </button>
            ) : (
              <button
                className="px-6 py-2 text-sm font-semibold bg-[#3ea6ff] text-black rounded-sm hover:bg-[#6ebbff] disabled:opacity-50 disabled:cursor-not-allowed uppercase"
                disabled={!canCreate || generatingOutline}
                onClick={handleCreate}
              >
                {loading ? "Creating..." : "Create Project"}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Loading Toast */}
      {loading && (
        <div className="fixed bottom-20 left-1/2 -translate-x-1/2 bg-[#333] text-white px-6 py-3 rounded text-sm shadow-lg">
          Creating Project...
        </div>
      )}
    </div>
  );
}

/* Horizontal Step Navigation */
function StepNav({
  step,
  mine,
  label,
  canNav,
  onClick,
  totalSteps = 4,
}: {
  step: number;
  mine: number;
  label: string;
  canNav: boolean;
  onClick: () => void;
  totalSteps?: number;
}) {
  const isActive = step === mine;
  const isDone = step > mine;

  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "flex flex-col items-center w-[120px] relative",
        canNav ? "cursor-pointer" : "cursor-default",
      ].join(" ")}
    >
      {/* Connector line */}
      {mine < totalSteps && (
        <div
          className={[
            "absolute top-3 left-1/2 w-full h-0.5 z-0",
            isDone ? "bg-[#3ea6ff]" : "bg-[#3f3f3f]",
          ].join(" ")}
        />
      )}

      {/* Circle */}
      <div
        className={[
          "w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold mb-2 z-10 transition-all",
          isActive
            ? "bg-[#3ea6ff] text-white scale-110"
            : isDone
              ? "bg-[#3f3f3f] text-[#3ea6ff]"
              : "bg-[#3f3f3f] text-[#aaa]",
        ].join(" ")}
      >
        {mine}
      </div>

      {/* Label */}
      <div
        className={[
          "text-xs font-medium uppercase tracking-wide",
          isActive ? "text-[#f1f1f1]" : "text-[#aaa]",
        ].join(" ")}
      >
        {label}
      </div>
    </button>
  );
}

/* Format/Style Card */
function FormatCard({
  icon,
  title,
  sub,
  selected,
  onClick,
}: {
  icon: string;
  title: string;
  sub: string;
  selected: boolean;
  onClick: () => void;
}) {
  const iconMap: Record<string, string> = {
    TV: "TV",
    Phone: "Phone",
    Image: "Img",
    Camera: "Cam",
    Palette: "Art",
    Star: "Ani",
  };

  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "bg-[#1f1f1f] border rounded p-5 text-center transition-colors flex flex-col items-center gap-2",
        selected
          ? "border-[#3ea6ff] bg-[rgba(62,166,255,0.08)]"
          : "border-[#3f3f3f] hover:bg-[#282828]",
      ].join(" ")}
    >
      <div className="text-2xl">{iconMap[icon] || icon}</div>
      <div className="text-[15px] font-medium">{title}</div>
      <div className="text-xs text-[#aaa]">{sub}</div>
    </button>
  );
}

/* Chip for single/multi select */
function Chip({
  active,
  children,
  onClick,
}: {
  active: boolean;
  children: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "px-4 py-2 rounded-full text-sm border transition-colors",
        active
          ? "bg-[#f1f1f1] text-[#0f0f0f] font-medium border-transparent"
          : "bg-[#282828] text-[#aaa] border-transparent hover:bg-[#3f3f3f] hover:text-[#f1f1f1]",
      ].join(" ")}
    >
      {children}
    </button>
  );
}

/* Check Row for Step 3 */
function CheckRow({
  checked,
  title,
  desc,
  onToggle,
  last,
}: {
  checked: boolean;
  title: string;
  desc: string;
  onToggle: () => void;
  last?: boolean;
}) {
  return (
    <div className={["flex items-start gap-3 p-4", !last && "border-b border-[#3f3f3f]"].filter(Boolean).join(" ")}>
      <input
        type="checkbox"
        className="w-[18px] h-[18px] accent-[#3ea6ff] mt-0.5"
        checked={checked}
        onChange={onToggle}
      />
      <div>
        <div className="text-sm font-medium">{title}</div>
        <div className="text-xs text-[#aaa] mt-1">{desc}</div>
      </div>
    </div>
  );
}

/* Review Line for Step 4 */
function ReviewLine({
  label,
  value,
  color,
  last,
}: {
  label: string;
  value: string;
  color?: string;
  last?: boolean;
}) {
  return (
    <div className={["flex justify-between py-3", !last && "border-b border-[#3f3f3f]"].filter(Boolean).join(" ")}>
      <span className="text-[#aaa]">{label}</span>
      <span className={["font-medium", color || "text-[#f1f1f1]"].join(" ")}>{value}</span>
    </div>
  );
}

function platformPresetToLabel(p: PlatformPreset) {
  if (p === "youtube_16_9") return "YouTube Video (16:9)";
  if (p === "shorts_9_16") return "YouTube Short (9:16)";
  return "Slides (16:9)";
}

export default CreatorStudioHost;
