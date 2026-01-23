import React, { useState, useEffect } from "react";

type StoryTone = "romantic" | "sensual" | "slow_burn" | "passionate" | "tender";
type ExplicitnessLevel = "fade_to_black" | "suggestive" | "sensual";

type MatureGuide = {
  title: string;
  description: string;
  philosophy: string;
  allowed_elements: string[];
  blocked_elements: string[];
  example_prompt: { good: string; bad: string };
  example_output: string;
  tips: string[];
};

type PreparedPrompt = {
  system: string;
  user: string;
  metadata: {
    genre: string;
    tone: string;
    explicitness: string;
    content_rating: string;
  };
};

type Props = {
  videoId: string;
  onPromptReady?: (prepared: PreparedPrompt) => void;
};

const TONE_OPTIONS: { value: StoryTone; label: string; description: string }[] = [
  { value: "sensual", label: "Sensual", description: "Emotionally intimate, atmospheric" },
  { value: "slow_burn", label: "Slow Burn", description: "Building tension gradually" },
  { value: "passionate", label: "Passionate", description: "Intense emotions, tasteful" },
  { value: "tender", label: "Tender", description: "Gentle, emotionally vulnerable" },
  { value: "romantic", label: "Romantic", description: "Warm, connection-focused" },
];

const EXPLICITNESS_OPTIONS: { value: ExplicitnessLevel; label: string; description: string }[] = [
  { value: "fade_to_black", label: "Fade to Black", description: "Scene ends before intimacy, implication only" },
  { value: "suggestive", label: "Suggestive", description: "Tension and desire, no physical description" },
  { value: "sensual", label: "Sensual", description: "Emotional/atmospheric intimacy, tasteful prose" },
];

/**
 * Wizard component for creating mature/adult fiction stories.
 *
 * Guides users through:
 * 1. Understanding what's allowed (literary erotica, not porn)
 * 2. Setting appropriate parameters
 * 3. Writing a proper prompt
 * 4. Reviewing constraints
 */
export function MatureStoryWizard({ videoId, onPromptReady }: Props) {
  const [step, setStep] = useState<1 | 2 | 3 | 4>(1);
  const [guide, setGuide] = useState<MatureGuide | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form state
  const [tone, setTone] = useState<StoryTone>("sensual");
  const [explicitness, setExplicitness] = useState<ExplicitnessLevel>("suggestive");
  const [setting, setSetting] = useState("");
  const [characters, setCharacters] = useState("two consenting adults");
  const [prompt, setPrompt] = useState("");

  // Result state
  const [preparedPrompt, setPreparedPrompt] = useState<PreparedPrompt | null>(null);
  const [policyResult, setPolicyResult] = useState<{ ok: boolean; error?: string } | null>(null);

  // Load the mature content guide
  useEffect(() => {
    fetch("/studio/mature-guide")
      .then((r) => r.json())
      .then((j) => setGuide(j.guide))
      .catch(() => {});
  }, []);

  async function preparePrompt() {
    setLoading(true);
    setError(null);

    try {
      const r = await fetch(`/studio/videos/${videoId}/story/prepare`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt,
          tone,
          explicitness,
          setting: setting || undefined,
          characters: characters || "two consenting adults",
          provider: "ollama",
        }),
      });

      const j = await r.json();

      if (!r.ok) {
        throw new Error(j?.detail || j?.error || `HTTP ${r.status}`);
      }

      setPreparedPrompt(j.prepared_prompt);
      setPolicyResult(j.policy_check);

      if (j.policy_check?.ok) {
        setStep(4);
        onPromptReady?.(j.prepared_prompt);
      } else {
        setError(j.policy_check?.error || "Policy check failed");
      }
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  // Step 1: Guidelines
  const renderStep1 = () => (
    <div className="space-y-4">
      <div className="text-lg font-semibold">Step 1: Understand the Guidelines</div>

      {guide ? (
        <div className="space-y-4">
          <div className="p-4 bg-blue-500/10 border border-blue-500/30 rounded">
            <div className="font-medium">{guide.title}</div>
            <div className="text-sm opacity-80 mt-1">{guide.philosophy}</div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="p-3 border rounded bg-green-500/5">
              <div className="font-medium text-sm text-green-600 dark:text-green-400">
                Allowed
              </div>
              <ul className="text-xs mt-2 space-y-1">
                {guide.allowed_elements.map((item, i) => (
                  <li key={i} className="flex items-start gap-1">
                    <span className="text-green-500">✓</span> {item}
                  </li>
                ))}
              </ul>
            </div>

            <div className="p-3 border rounded bg-red-500/5">
              <div className="font-medium text-sm text-red-600 dark:text-red-400">
                Not Allowed
              </div>
              <ul className="text-xs mt-2 space-y-1">
                {guide.blocked_elements.map((item, i) => (
                  <li key={i} className="flex items-start gap-1">
                    <span className="text-red-500">✗</span> {item}
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <div className="p-3 border rounded">
            <div className="text-sm font-medium">Example of Good Output</div>
            <div className="text-xs opacity-80 mt-2 italic whitespace-pre-wrap">
              {guide.example_output}
            </div>
          </div>

          <label className="flex items-start gap-2 text-sm p-3 border rounded bg-yellow-500/10">
            <input type="checkbox" className="mt-1" required />
            <span>
              I understand that Mature mode is for literary adult fiction only.
              All characters will be adults (18+), and content will focus on
              emotional connection rather than explicit acts.
            </span>
          </label>
        </div>
      ) : (
        <div className="text-sm opacity-70">Loading guidelines...</div>
      )}

      <div className="flex justify-end">
        <button
          className="px-4 py-2 rounded border bg-primary text-primary-foreground"
          onClick={() => setStep(2)}
        >
          I Understand, Continue
        </button>
      </div>
    </div>
  );

  // Step 2: Configure tone and explicitness
  const renderStep2 = () => (
    <div className="space-y-4">
      <div className="text-lg font-semibold">Step 2: Set Tone & Boundaries</div>

      <div>
        <label className="text-sm font-medium block mb-2">Tone</label>
        <div className="grid grid-cols-1 gap-2">
          {TONE_OPTIONS.map((opt) => (
            <label
              key={opt.value}
              className={`flex items-start gap-2 p-3 border rounded cursor-pointer ${
                tone === opt.value ? "border-primary bg-primary/5" : ""
              }`}
            >
              <input
                type="radio"
                name="tone"
                value={opt.value}
                checked={tone === opt.value}
                onChange={(e) => setTone(e.target.value as StoryTone)}
                className="mt-1"
              />
              <div>
                <div className="font-medium text-sm">{opt.label}</div>
                <div className="text-xs opacity-70">{opt.description}</div>
              </div>
            </label>
          ))}
        </div>
      </div>

      <div>
        <label className="text-sm font-medium block mb-2">Explicitness Level</label>
        <div className="grid grid-cols-1 gap-2">
          {EXPLICITNESS_OPTIONS.map((opt) => (
            <label
              key={opt.value}
              className={`flex items-start gap-2 p-3 border rounded cursor-pointer ${
                explicitness === opt.value ? "border-primary bg-primary/5" : ""
              }`}
            >
              <input
                type="radio"
                name="explicitness"
                value={opt.value}
                checked={explicitness === opt.value}
                onChange={(e) => setExplicitness(e.target.value as ExplicitnessLevel)}
                className="mt-1"
              />
              <div>
                <div className="font-medium text-sm">{opt.label}</div>
                <div className="text-xs opacity-70">{opt.description}</div>
              </div>
            </label>
          ))}
        </div>
      </div>

      <div className="flex justify-between">
        <button className="px-4 py-2 rounded border" onClick={() => setStep(1)}>
          Back
        </button>
        <button
          className="px-4 py-2 rounded border bg-primary text-primary-foreground"
          onClick={() => setStep(3)}
        >
          Continue
        </button>
      </div>
    </div>
  );

  // Step 3: Write the prompt
  const renderStep3 = () => (
    <div className="space-y-4">
      <div className="text-lg font-semibold">Step 3: Describe Your Story</div>

      <div>
        <label className="text-sm font-medium block mb-1">Setting</label>
        <input
          className="w-full border rounded px-3 py-2 text-sm"
          placeholder="e.g., Candlelit room in a Parisian apartment, evening"
          value={setting}
          onChange={(e) => setSetting(e.target.value)}
        />
      </div>

      <div>
        <label className="text-sm font-medium block mb-1">Characters</label>
        <input
          className="w-full border rounded px-3 py-2 text-sm"
          placeholder="e.g., two consenting adults who reunite after years apart"
          value={characters}
          onChange={(e) => setCharacters(e.target.value)}
        />
        <div className="text-xs opacity-60 mt-1">
          All characters are automatically affirmed as adults (18+)
        </div>
      </div>

      <div>
        <label className="text-sm font-medium block mb-1">Story Prompt</label>
        <textarea
          className="w-full border rounded px-3 py-2 text-sm resize-none"
          rows={4}
          placeholder="Describe the scene, emotional context, and what you want to happen. Focus on feelings and atmosphere..."
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
        />
        <div className="text-xs opacity-60 mt-1">
          Tip: Focus on emotional connection and atmosphere, not physical actions
        </div>
      </div>

      {guide && (
        <div className="p-3 border rounded bg-muted/30">
          <div className="text-xs font-medium mb-1">Tips:</div>
          <ul className="text-xs opacity-70 space-y-1">
            {guide.tips.slice(0, 3).map((tip, i) => (
              <li key={i}>• {tip}</li>
            ))}
          </ul>
        </div>
      )}

      {error && (
        <div className="p-3 border rounded bg-red-500/10 border-red-500/30 text-sm">
          {error}
        </div>
      )}

      <div className="flex justify-between">
        <button className="px-4 py-2 rounded border" onClick={() => setStep(2)}>
          Back
        </button>
        <button
          className="px-4 py-2 rounded border bg-primary text-primary-foreground disabled:opacity-50"
          onClick={preparePrompt}
          disabled={!prompt.trim() || loading}
        >
          {loading ? "Checking..." : "Prepare Prompt"}
        </button>
      </div>
    </div>
  );

  // Step 4: Review prepared prompt
  const renderStep4 = () => (
    <div className="space-y-4">
      <div className="text-lg font-semibold">Step 4: Review & Generate</div>

      {policyResult?.ok && (
        <div className="p-3 border rounded bg-green-500/10 border-green-500/30">
          <div className="font-medium text-sm text-green-600 dark:text-green-400">
            ✓ Policy Check Passed
          </div>
          <div className="text-xs opacity-80 mt-1">
            Your prompt meets content guidelines for mature fiction.
          </div>
        </div>
      )}

      {preparedPrompt && (
        <div className="space-y-3">
          <div className="p-3 border rounded">
            <div className="text-xs font-medium opacity-70 mb-1">Metadata</div>
            <div className="text-xs grid grid-cols-2 gap-2">
              <div>Genre: <span className="font-medium">{preparedPrompt.metadata.genre}</span></div>
              <div>Tone: <span className="font-medium">{preparedPrompt.metadata.tone}</span></div>
              <div>Level: <span className="font-medium">{preparedPrompt.metadata.explicitness}</span></div>
              <div>Rating: <span className="font-medium">{preparedPrompt.metadata.content_rating}</span></div>
            </div>
          </div>

          <div className="p-3 border rounded">
            <div className="text-xs font-medium opacity-70 mb-1">Prepared User Prompt</div>
            <div className="text-xs whitespace-pre-wrap bg-muted/30 p-2 rounded max-h-48 overflow-auto">
              {preparedPrompt.user}
            </div>
          </div>

          <details className="p-3 border rounded">
            <summary className="text-xs font-medium opacity-70 cursor-pointer">
              View System Prompt (for LLM)
            </summary>
            <div className="text-xs whitespace-pre-wrap bg-muted/30 p-2 rounded mt-2 max-h-48 overflow-auto">
              {preparedPrompt.system}
            </div>
          </details>
        </div>
      )}

      <div className="flex justify-between">
        <button className="px-4 py-2 rounded border" onClick={() => setStep(3)}>
          Back & Edit
        </button>
        <button
          className="px-4 py-2 rounded border bg-primary text-primary-foreground"
          onClick={() => {
            if (preparedPrompt) {
              onPromptReady?.(preparedPrompt);
            }
          }}
        >
          Use This Prompt
        </button>
      </div>
    </div>
  );

  return (
    <div className="max-w-2xl mx-auto p-4">
      {/* Progress indicator */}
      <div className="flex items-center gap-2 mb-6">
        {[1, 2, 3, 4].map((s) => (
          <React.Fragment key={s}>
            <div
              className={`w-8 h-8 rounded-full flex items-center justify-center text-sm ${
                step >= s
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground"
              }`}
            >
              {s}
            </div>
            {s < 4 && <div className={`flex-1 h-1 ${step > s ? "bg-primary" : "bg-muted"}`} />}
          </React.Fragment>
        ))}
      </div>

      {/* Step content */}
      {step === 1 && renderStep1()}
      {step === 2 && renderStep2()}
      {step === 3 && renderStep3()}
      {step === 4 && renderStep4()}
    </div>
  );
}
