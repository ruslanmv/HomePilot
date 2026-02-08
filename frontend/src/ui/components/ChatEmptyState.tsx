import React from 'react'

import { AgentIntent, AgentIntentTiles } from './AgentIntentTiles'

type Props = {
  title: string
  description?: string
  isAgent?: boolean
  capabilityLabels?: string[]
  onPickPrompt: (text: string) => void
  agentIntent?: AgentIntent | null
  onAgentIntentChange?: (intent: AgentIntent | null) => void
}

export function ChatEmptyState({
  title,
  description,
  isAgent,
  capabilityLabels = [],
  onPickPrompt,
  agentIntent = null,
  onAgentIntentChange,
}: Props) {
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
              : 'Start a conversation, upload files, or use voice mode.'}
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

          {isAgent ? (
            <>
              <AgentIntentTiles value={agentIntent} onChange={(i) => onAgentIntentChange?.(i)} />

              <div className="mt-4 text-xs text-white/55 leading-relaxed">
                {agentIntent
                  ? "Tip: describe your goal in one sentence — I'll route this to the right tools."
                  : 'Pick an intent to get a focused starting point.'}
              </div>
            </>
          ) : null}
        </div>

        <div className="mt-4 text-center text-[11px] text-white/40">
          HomePilot can make mistakes. Verify important outputs.
        </div>
      </div>
    </div>
  )
}
