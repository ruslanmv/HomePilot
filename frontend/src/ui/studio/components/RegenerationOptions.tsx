import React, { useEffect, useState } from "react";

type Option = {
  id: string;
  label: string;
  description: string;
  constraint: string;
};

type Props = {
  onSelect: (constraintId: string, newPrompt: string) => void;
  currentPrompt: string;
};

/**
 * Regeneration options for adjusting story output.
 *
 * Allows users to refine output without re-prompting by selecting
 * predefined constraints like "More Romantic" or "Fade to Black".
 */
export function RegenerationOptions({ onSelect, currentPrompt }: Props) {
  const [options, setOptions] = useState<Option[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    fetch("/studio/regeneration-options")
      .then((r) => r.json())
      .then((j) => setOptions(j.options || []))
      .catch(() => {});
  }, []);

  async function applyConstraint(constraintId: string) {
    setLoading(true);
    setSelectedId(constraintId);

    try {
      const r = await fetch("/studio/prompt/regenerate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt: currentPrompt,
          constraint_id: constraintId,
        }),
      });

      const j = await r.json();
      onSelect(constraintId, j.prompt);
    } catch (e) {
      console.error("Failed to apply constraint:", e);
    } finally {
      setLoading(false);
    }
  }

  if (!options.length) {
    return null;
  }

  return (
    <div className="space-y-2">
      <div className="text-sm font-medium">Regenerate with:</div>
      <div className="flex flex-wrap gap-2">
        {options.map((opt) => (
          <button
            key={opt.id}
            className={`px-3 py-1.5 text-xs rounded border transition-colors ${
              selectedId === opt.id
                ? "bg-primary text-primary-foreground"
                : "hover:bg-muted/30"
            }`}
            onClick={() => applyConstraint(opt.id)}
            disabled={loading}
            title={opt.description}
          >
            {opt.label}
          </button>
        ))}
      </div>
      <div className="text-xs opacity-60">
        Click to adjust the output style without re-writing your prompt
      </div>
    </div>
  );
}
