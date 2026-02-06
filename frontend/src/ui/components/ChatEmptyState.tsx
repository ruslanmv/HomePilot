import React from 'react'

type Props = {
  title: string
  description?: string
  isAgent?: boolean
  capabilityLabels?: string[]
  onPickPrompt: (text: string) => void
}

const AGENT_PROMPTS = [
  'Generate an image of a cozy modern living room, soft sunlight, photorealistic.',
  'Generate a short video of ocean waves at sunrise, cinematic.',
  'Summarize the files I upload into key takeaways.',
]

const CHAT_PROMPTS = [
  'Summarize this topic in 5 bullet points.',
  'Help me write a professional email.',
  'Explain this concept like I\'m new to it.',
]

export function ChatEmptyState({
  title,
  description,
  isAgent,
  capabilityLabels = [],
  onPickPrompt,
}: Props) {
  const prompts = isAgent ? AGENT_PROMPTS : CHAT_PROMPTS

  return (
    <div className="h-full w-full flex items-center justify-center px-6">
      <div className="w-full max-w-2xl">
        <div className="rounded-3xl border border-white/10 bg-white/5 p-8 shadow-[0_20px_80px_rgba(0,0,0,0.35)]">
          <div className="text-2xl font-semibold text-white">{title}</div>

          <div className="mt-2 text-sm text-white/60 leading-relaxed">
            {description?.trim()
              ? description
              : isAgent
              ? 'This project is an advanced assistant. Ask normally — it can use available capabilities when needed.'
              : 'Ask anything, upload files, or start with a prompt below.'}
          </div>

          {isAgent && capabilityLabels.length > 0 ? (
            <div className="mt-4">
              <div className="text-xs font-semibold text-white/70">This assistant can:</div>
              <div className="mt-2 flex flex-wrap gap-2">
                {capabilityLabels.map((c) => (
                  <span
                    key={c}
                    className="text-xs px-2 py-1 rounded-full bg-white/10 border border-white/10 text-white/80"
                  >
                    {c}
                  </span>
                ))}
              </div>
            </div>
          ) : null}

          <div className="mt-6 grid grid-cols-1 sm:grid-cols-2 gap-2">
            {prompts.map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => onPickPrompt(p)}
                className="text-left px-4 py-3 rounded-2xl bg-black/20 hover:bg-black/30 border border-white/10 hover:border-white/20 text-sm text-white/80 transition-all"
              >
                {p}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-4 text-center text-[11px] text-white/40">
          HomePilot can make mistakes. Verify important outputs.
        </div>
      </div>
    </div>
  )
}
