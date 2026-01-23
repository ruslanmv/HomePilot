import React, { useState, useEffect } from "react";
import { useStudioStore } from "../stores/studioStore";

interface Genre {
  id: string;
  name: string;
  description: string;
  requires_mature: boolean;
  default_tone: string;
  allowed_tones: string[];
}

interface MatureGuide {
  title: string;
  description: string;
  philosophy: string;
  allowed_elements: string[];
  blocked_elements: string[];
  tips: string[];
  example_prompt: { good: string; bad: string };
  example_output: string;
}

interface RegenerationOption {
  id: string;
  label: string;
  description: string;
}

interface StoryBible {
  title: string;
  logline: string;
  setting: string;
  visual_style_rules: string[];
  recurring_characters: { name: string; description: string }[];
  recurring_locations: string[];
  do_not_change: string[];
}

interface StorySession {
  session_id: string;
  title: string;
  bible: StoryBible;
}

interface Scene {
  idx: number;
  narration: string;
  image_prompt: string;
  negative_prompt: string;
  duration_s: number;
  tags: Record<string, string>;
}

/**
 * Story Page
 *
 * Text/story generation with mature content support.
 */
export const StoryPage: React.FC = () => {
  const { contentRating, matureEnabled } = useStudioStore();

  // Form state
  const [selectedGenre, setSelectedGenre] = useState<string>("");
  const [tone, setTone] = useState<string>("sensual");
  const [explicitness, setExplicitness] = useState<string>("suggestive");
  const [setting, setSetting] = useState<string>("");
  const [characters, setCharacters] = useState<string>("two consenting adults");
  const [prompt, setPrompt] = useState<string>("");

  // Data state
  const [genres, setGenres] = useState<Genre[]>([]);
  const [matureGuide, setMatureGuide] = useState<MatureGuide | null>(null);
  const [regenOptions, setRegenOptions] = useState<RegenerationOption[]>([]);

  // Generation state
  const [generatedStory, setGeneratedStory] = useState<string>("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Story session state
  const [currentSession, setCurrentSession] = useState<StorySession | null>(null);
  const [scenes, setScenes] = useState<Scene[]>([]);

  // Fetch genres
  useEffect(() => {
    const fetchGenres = async () => {
      try {
        const res = await fetch(
          `/studio/genres?content_rating=${contentRating}`
        );
        if (res.ok) {
          const data = await res.json();
          setGenres(data.genres || []);
        }
      } catch (e) {
        console.error("Failed to fetch genres:", e);
      }
    };
    fetchGenres();
  }, [contentRating]);

  // Fetch mature guide
  useEffect(() => {
    if (contentRating === "mature") {
      const fetchGuide = async () => {
        try {
          const res = await fetch("/studio/mature-guide");
          if (res.ok) {
            const data = await res.json();
            setMatureGuide(data.guide);
          }
        } catch (e) {
          console.error("Failed to fetch mature guide:", e);
        }
      };
      fetchGuide();
    }
  }, [contentRating]);

  // Fetch regeneration options
  useEffect(() => {
    const fetchRegenOptions = async () => {
      try {
        const res = await fetch("/studio/regeneration-options");
        if (res.ok) {
          const data = await res.json();
          setRegenOptions(data.options || []);
        }
      } catch (e) {
        console.error("Failed to fetch regen options:", e);
      }
    };
    fetchRegenOptions();
  }, []);

  const selectedGenreData = genres.find((g) => g.id === selectedGenre);

  const handleGenerate = async () => {
    if (!prompt.trim()) return;

    setIsGenerating(true);
    setError(null);

    try {
      // Step 1: Start a new story session
      const startRes = await fetch("/story/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          premise: prompt.trim(),
          title_hint: selectedGenre || "",
          options: {
            visual_style: "cinematic, high detail, coherent lighting",
            aspect_ratio: "16:9",
            allow_nsfw: contentRating === "mature",
            refine_image_prompt: true,
          },
        }),
      });

      if (!startRes.ok) {
        const errText = await startRes.text().catch(() => "");
        throw new Error(`Failed to start story: ${startRes.status} ${errText}`);
      }

      const startData = await startRes.json();
      const session: StorySession = {
        session_id: startData.session_id,
        title: startData.title,
        bible: startData.bible,
      };
      setCurrentSession(session);

      // Step 2: Generate the first scene
      const sceneRes = await fetch("/story/next", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: session.session_id,
          refine_image_prompt: true,
        }),
      });

      if (!sceneRes.ok) {
        const errText = await sceneRes.text().catch(() => "");
        throw new Error(`Failed to generate scene: ${sceneRes.status} ${errText}`);
      }

      const sceneData = await sceneRes.json();
      const scene: Scene = sceneData.scene;
      setScenes([scene]);

      // Build story text from bible + scene
      const storyText = `# ${session.title}

**${session.bible.logline}**

---

${scene.narration}

---
*Image prompt: ${scene.image_prompt}*`;

      setGeneratedStory(storyText);
    } catch (e: any) {
      console.error("Story generation error:", e);
      setError(e.message || "Generation failed. Please try again.");
    } finally {
      setIsGenerating(false);
    }
  };

  const handleRegenerate = async (optionId: string) => {
    if (!currentSession) {
      setError("No active story session. Generate a story first.");
      return;
    }

    setIsGenerating(true);
    setError(null);

    try {
      // Call the regeneration endpoint
      const res = await fetch("/studio/prompt/regenerate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt: prompt.trim(),
          constraint: optionId,
          content_rating: contentRating,
        }),
      });

      if (!res.ok) {
        const errText = await res.text().catch(() => "");
        throw new Error(`Regeneration failed: ${res.status} ${errText}`);
      }

      const data = await res.json();

      // Generate a new scene with the regenerated prompt
      const sceneRes = await fetch("/story/next", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: currentSession.session_id,
          refine_image_prompt: true,
        }),
      });

      if (!sceneRes.ok) {
        const errText = await sceneRes.text().catch(() => "");
        throw new Error(`Failed to generate scene: ${sceneRes.status} ${errText}`);
      }

      const sceneData = await sceneRes.json();
      const scene: Scene = sceneData.scene;
      setScenes((prev) => [...prev, scene]);

      // Append new scene to story text
      const newText = `\n\n---\n\n${scene.narration}\n\n---\n*Image prompt: ${scene.image_prompt}*`;
      setGeneratedStory((prev) => prev + newText);
    } catch (e: any) {
      console.error("Regeneration error:", e);
      setError(e.message || "Regeneration failed.");
    } finally {
      setIsGenerating(false);
    }
  };

  // Add a function to continue the story (generate next scene)
  const handleContinueStory = async () => {
    if (!currentSession) {
      setError("No active story session. Generate a story first.");
      return;
    }

    setIsGenerating(true);
    setError(null);

    try {
      const sceneRes = await fetch("/story/next", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: currentSession.session_id,
          refine_image_prompt: true,
        }),
      });

      if (!sceneRes.ok) {
        const errText = await sceneRes.text().catch(() => "");
        throw new Error(`Failed to generate scene: ${sceneRes.status} ${errText}`);
      }

      const sceneData = await sceneRes.json();
      const scene: Scene = sceneData.scene;
      setScenes((prev) => [...prev, scene]);

      // Append new scene to story text
      const newText = `\n\n---\n\n${scene.narration}\n\n---\n*Image prompt: ${scene.image_prompt}*`;
      setGeneratedStory((prev) => prev + newText);
    } catch (e: any) {
      console.error("Continue story error:", e);
      setError(e.message || "Failed to continue story.");
    } finally {
      setIsGenerating(false);
    }
  };

  return (
    <div className="story-page">
      <div className="story-header">
        <h2>Story Generator</h2>
        {contentRating === "mature" && (
          <span className="mature-badge">\uD83D\uDD1E Mature Mode</span>
        )}
      </div>

      <div className="story-content">
        {/* Left: Form */}
        <div className="story-form">
          {/* Genre Selection */}
          <div className="form-group">
            <label>Genre</label>
            <select
              value={selectedGenre}
              onChange={(e) => {
                setSelectedGenre(e.target.value);
                const genre = genres.find((g) => g.id === e.target.value);
                if (genre) {
                  setTone(genre.default_tone);
                }
              }}
            >
              <option value="">Select a genre...</option>
              {genres.map((genre) => (
                <option
                  key={genre.id}
                  value={genre.id}
                  disabled={
                    genre.requires_mature && contentRating !== "mature"
                  }
                >
                  {genre.name}
                  {genre.requires_mature ? " \uD83D\uDD1E" : ""}
                </option>
              ))}
            </select>
            {selectedGenreData && (
              <p className="field-desc">{selectedGenreData.description}</p>
            )}
          </div>

          {/* Tone Selection - Only for mature */}
          {contentRating === "mature" && selectedGenreData && (
            <>
              <div className="form-group">
                <label>Tone</label>
                <select value={tone} onChange={(e) => setTone(e.target.value)}>
                  {selectedGenreData.allowed_tones.map((t) => (
                    <option key={t} value={t}>
                      {t.charAt(0).toUpperCase() + t.slice(1).replace("_", " ")}
                    </option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label>Explicitness Level</label>
                <div className="radio-group">
                  <label className="radio-option">
                    <input
                      type="radio"
                      name="explicitness"
                      value="fade_to_black"
                      checked={explicitness === "fade_to_black"}
                      onChange={(e) => setExplicitness(e.target.value)}
                    />
                    <span>
                      <strong>Fade to Black</strong>
                      <small>Implied intimacy, scene ends before explicit content</small>
                    </span>
                  </label>
                  <label className="radio-option">
                    <input
                      type="radio"
                      name="explicitness"
                      value="suggestive"
                      checked={explicitness === "suggestive"}
                      onChange={(e) => setExplicitness(e.target.value)}
                    />
                    <span>
                      <strong>Suggestive</strong>
                      <small>Romantic tension, sensual atmosphere</small>
                    </span>
                  </label>
                  <label className="radio-option">
                    <input
                      type="radio"
                      name="explicitness"
                      value="sensual"
                      checked={explicitness === "sensual"}
                      onChange={(e) => setExplicitness(e.target.value)}
                    />
                    <span>
                      <strong>Sensual</strong>
                      <small>Literary erotica, emotional intimacy</small>
                    </span>
                  </label>
                </div>
              </div>

              <div className="form-group">
                <label>Setting (Optional)</label>
                <input
                  type="text"
                  placeholder="e.g., Candlelit apartment, evening"
                  value={setting}
                  onChange={(e) => setSetting(e.target.value)}
                />
              </div>

              <div className="form-group">
                <label>Characters</label>
                <input
                  type="text"
                  placeholder="e.g., Two consenting adults, longtime friends"
                  value={characters}
                  onChange={(e) => setCharacters(e.target.value)}
                />
              </div>
            </>
          )}

          {/* Main Prompt */}
          <div className="form-group">
            <label>Story Prompt</label>
            <textarea
              placeholder={
                contentRating === "mature"
                  ? "Describe the scene you want to create... Focus on emotion and atmosphere."
                  : "Describe your story idea..."
              }
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={5}
            />
          </div>

          {/* Generate Button */}
          <button
            className="generate-btn"
            onClick={handleGenerate}
            disabled={isGenerating || !prompt.trim()}
          >
            {isGenerating ? "Generating..." : "\u2728 Generate Story"}
          </button>

          {error && <div className="error-msg">{error}</div>}
        </div>

        {/* Right: Output / Guide */}
        <div className="story-output">
          {generatedStory ? (
            <>
              <div className="output-header">
                <h3>Generated Story</h3>
                <div className="output-actions">
                  <button onClick={() => navigator.clipboard.writeText(generatedStory)}>
                    \uD83D\uDCCB Copy
                  </button>
                  <button onClick={() => setGeneratedStory("")}>
                    \uD83D\uDDD1 Clear
                  </button>
                </div>
              </div>

              <div className="story-text">{generatedStory}</div>

              {/* Continue Story Button */}
              {currentSession && (
                <div className="continue-section">
                  <button
                    className="continue-btn"
                    onClick={handleContinueStory}
                    disabled={isGenerating}
                  >
                    {isGenerating ? "Generating..." : "▶ Continue Story"}
                  </button>
                  <p className="scene-count">
                    {scenes.length} scene{scenes.length !== 1 ? "s" : ""} generated
                  </p>
                </div>
              )}

              {/* Regeneration Options */}
              {regenOptions.length > 0 && (
                <div className="regen-section">
                  <h4>Adjust Output</h4>
                  <div className="regen-options">
                    {regenOptions.map((opt) => (
                      <button
                        key={opt.id}
                        className="regen-btn"
                        onClick={() => handleRegenerate(opt.id)}
                        disabled={isGenerating}
                        title={opt.description}
                      >
                        {opt.label}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </>
          ) : matureGuide && contentRating === "mature" ? (
            <div className="guide-panel">
              <h3>{matureGuide.title}</h3>
              <p className="guide-philosophy">{matureGuide.philosophy}</p>

              <div className="guide-section">
                <h4>\u2713 Allowed Elements</h4>
                <ul>
                  {matureGuide.allowed_elements.map((item, i) => (
                    <li key={i}>{item}</li>
                  ))}
                </ul>
              </div>

              <div className="guide-section blocked">
                <h4>\u2717 Not Allowed</h4>
                <ul>
                  {matureGuide.blocked_elements.map((item, i) => (
                    <li key={i}>{item}</li>
                  ))}
                </ul>
              </div>

              <div className="guide-section">
                <h4>\uD83D\uDCA1 Tips</h4>
                <ul>
                  {matureGuide.tips.map((tip, i) => (
                    <li key={i}>{tip}</li>
                  ))}
                </ul>
              </div>

              <div className="example-section">
                <h4>Example Output</h4>
                <p className="example-text">{matureGuide.example_output}</p>
              </div>
            </div>
          ) : (
            <div className="empty-output">
              <span className="empty-icon">\uD83D\uDCDD</span>
              <p>Your generated story will appear here</p>
            </div>
          )}
        </div>
      </div>

      <style>{`
        .story-page {
          padding: 24px;
          height: 100%;
          display: flex;
          flex-direction: column;
        }

        .story-header {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-bottom: 20px;
        }

        .story-header h2 {
          margin: 0;
          font-size: 24px;
          color: var(--color-text);
        }

        .mature-badge {
          background: linear-gradient(135deg, #8B5CF6, #F59E0B);
          color: white;
          padding: 4px 12px;
          border-radius: 6px;
          font-size: 13px;
          font-weight: 500;
        }

        .story-content {
          flex: 1;
          display: flex;
          gap: 24px;
          overflow: hidden;
        }

        .story-form {
          width: 400px;
          flex-shrink: 0;
          overflow-y: auto;
          padding-right: 12px;
        }

        .form-group {
          margin-bottom: 20px;
        }

        .form-group label {
          display: block;
          font-weight: 500;
          color: var(--color-text);
          margin-bottom: 8px;
        }

        .form-group select,
        .form-group input[type="text"],
        .form-group textarea {
          width: 100%;
          padding: 10px 14px;
          border: 1px solid var(--color-border);
          border-radius: 8px;
          background: var(--color-surface);
          color: var(--color-text);
          font-size: 14px;
          font-family: inherit;
        }

        .form-group textarea {
          resize: vertical;
          min-height: 120px;
        }

        .field-desc {
          margin: 8px 0 0;
          font-size: 13px;
          color: var(--color-text-muted);
        }

        .radio-group {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .radio-option {
          display: flex;
          align-items: flex-start;
          gap: 12px;
          cursor: pointer;
          padding: 12px;
          border: 1px solid var(--color-border);
          border-radius: 8px;
          transition: all 0.2s;
        }

        .radio-option:hover {
          border-color: var(--color-primary);
        }

        .radio-option input {
          margin-top: 4px;
        }

        .radio-option span {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }

        .radio-option small {
          font-size: 12px;
          color: var(--color-text-muted);
        }

        .generate-btn {
          width: 100%;
          padding: 14px 24px;
          background: var(--color-primary);
          color: white;
          border: none;
          border-radius: 8px;
          font-size: 16px;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.2s;
        }

        .generate-btn:hover:not(:disabled) {
          background: var(--color-primary-hover);
        }

        .generate-btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        .error-msg {
          margin-top: 12px;
          padding: 10px 14px;
          background: rgba(239, 68, 68, 0.1);
          border: 1px solid rgba(239, 68, 68, 0.3);
          border-radius: 8px;
          color: #DC2626;
          font-size: 14px;
        }

        .story-output {
          flex: 1;
          background: var(--color-surface);
          border: 1px solid var(--color-border);
          border-radius: 12px;
          padding: 20px;
          overflow-y: auto;
        }

        .output-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 16px;
        }

        .output-header h3 {
          margin: 0;
          font-size: 16px;
          color: var(--color-text);
        }

        .output-actions {
          display: flex;
          gap: 8px;
        }

        .output-actions button {
          padding: 6px 12px;
          border: 1px solid var(--color-border);
          border-radius: 6px;
          background: var(--color-surface);
          color: var(--color-text-muted);
          font-size: 12px;
          cursor: pointer;
        }

        .output-actions button:hover {
          background: var(--color-surface-hover);
        }

        .story-text {
          font-size: 15px;
          line-height: 1.8;
          color: var(--color-text);
          white-space: pre-wrap;
        }

        .regen-section {
          margin-top: 24px;
          padding-top: 20px;
          border-top: 1px solid var(--color-border);
        }

        .regen-section h4 {
          margin: 0 0 12px;
          font-size: 14px;
          color: var(--color-text-muted);
        }

        .regen-options {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }

        .regen-btn {
          padding: 8px 14px;
          border: 1px solid var(--color-border);
          border-radius: 20px;
          background: var(--color-surface);
          color: var(--color-text);
          font-size: 13px;
          cursor: pointer;
          transition: all 0.2s;
        }

        .regen-btn:hover:not(:disabled) {
          border-color: var(--color-primary);
          color: var(--color-primary);
        }

        .regen-btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        .continue-section {
          margin-top: 20px;
          padding-top: 16px;
          border-top: 1px solid var(--color-border);
          display: flex;
          align-items: center;
          gap: 16px;
        }

        .continue-btn {
          padding: 12px 24px;
          background: linear-gradient(135deg, #8B5CF6, #6366F1);
          color: white;
          border: none;
          border-radius: 8px;
          font-size: 15px;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.2s;
        }

        .continue-btn:hover:not(:disabled) {
          transform: translateY(-1px);
          box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
        }

        .continue-btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        .scene-count {
          margin: 0;
          font-size: 13px;
          color: var(--color-text-muted);
        }

        .empty-output {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          height: 100%;
          color: var(--color-text-muted);
        }

        .empty-icon {
          font-size: 48px;
          margin-bottom: 12px;
        }

        .guide-panel h3 {
          margin: 0 0 12px;
          font-size: 18px;
          color: var(--color-text);
        }

        .guide-philosophy {
          margin: 0 0 20px;
          font-size: 14px;
          color: var(--color-text-muted);
          line-height: 1.6;
          padding: 12px;
          background: var(--color-background);
          border-radius: 8px;
        }

        .guide-section {
          margin-bottom: 20px;
        }

        .guide-section h4 {
          margin: 0 0 10px;
          font-size: 14px;
          color: #10B981;
        }

        .guide-section.blocked h4 {
          color: #EF4444;
        }

        .guide-section ul {
          margin: 0;
          padding-left: 20px;
        }

        .guide-section li {
          font-size: 13px;
          color: var(--color-text-muted);
          margin-bottom: 6px;
        }

        .example-section {
          background: var(--color-background);
          padding: 16px;
          border-radius: 8px;
        }

        .example-section h4 {
          margin: 0 0 12px;
          font-size: 14px;
          color: var(--color-text);
        }

        .example-text {
          margin: 0;
          font-size: 13px;
          line-height: 1.7;
          color: var(--color-text-muted);
          font-style: italic;
        }

        @media (max-width: 1024px) {
          .story-content {
            flex-direction: column;
          }

          .story-form {
            width: 100%;
          }
        }
      `}</style>
    </div>
  );
};

export default StoryPage;
