import React from 'react'

export type AgentIntent = 'understand' | 'decide' | 'summarize' | 'research'

export const INTENT_COPY: Record<
  AgentIntent,
  { icon: string; title: string; description: string; placeholder: string }
> = {
  understand: {
    icon: '📚',
    title: 'Understand something',
    description: 'Explain a concept, doc, or idea clearly.',
    placeholder: 'What would you like me to explain?',
  },
  decide: {
    icon: '🧠',
    title: 'Make a decision',
    description: 'Compare options and recommend next steps.',
    placeholder: 'What decision are you trying to make?',
  },
  summarize: {
    icon: '📝',
    title: 'Create a summary',
    description: 'Turn content into a concise, useful recap.',
    placeholder: 'What should I summarize?',
  },
  research: {
    icon: '🔍',
    title: 'Research a topic',
    description: 'Gather sources and synthesize key points.',
    placeholder: 'What topic should I research?',
  },
}

export function AgentIntentTiles({
  value,
  onChange,
}: {
  value: AgentIntent | null
  onChange: (intent: AgentIntent) => void
}) {
  const intents: AgentIntent[] = ['understand', 'decide', 'summarize', 'research']

  return (
    <div className="mt-6">
      <div className="text-sm text-white/70">What do you want help with?</div>

      <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
        {intents.map((intent) => {
          const c = INTENT_COPY[intent]
          const active = value === intent
          return (
            <button
              key={intent}
              type="button"
              onClick={() => onChange(intent)}
              className={[
                'text-left rounded-2xl border transition-all',
                'px-4 py-4',
                active
                  ? 'bg-white/10 border-white/30 shadow-[0_10px_40px_rgba(0,0,0,0.35)]'
                  : 'bg-black/20 border-white/10 hover:bg-black/30 hover:border-white/20',
              ].join(' ')}
            >
              <div className="flex items-start gap-3">
                <div className="text-xl leading-none mt-0.5">{c.icon}</div>
                <div>
                  <div className="text-base font-semibold text-white">{c.title}</div>
                  <div className="mt-1 text-sm text-white/60 leading-relaxed">{c.description}</div>
                </div>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
