// frontend/src/ui/Expert.tsx
// Expert mode UI — streaming chat with:
//   • Multi-provider selector (auto/local/groq/grok/gemini/claude/openai)
//   • Thinking mode selector (auto/fast/think/heavy)
//   • Live step panels for think/heavy pipelines with collapsible agent output
//   • Complexity badge and provider attribution on every response
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Brain, Send, Loader2, Zap, ChevronDown, ChevronUp,
  RotateCcw, Info, Cpu, Globe, Server, Sparkles,
  AlertCircle, FlaskConical, Layers, ChevronRight,
} from "lucide-react";
import {
  expertStream, fetchExpertInfo,
  ExpertProvider, ThinkingMode, ExpertMessage, ExpertInfo, StreamMeta, StreamStep,
} from "../../expertApi";

// ─────────────────────────────────────────────────────────────────────────────
// Provider metadata
// ─────────────────────────────────────────────────────────────────────────────

const PROVIDER_META: Record<string, {
  label: string; color: string; icon: React.ReactNode; hint: string;
}> = {
  auto:   { label: "Auto",   color: "text-purple-400",  icon: <Brain size={13} />,     hint: "Smart routing by complexity" },
  local:  { label: "Local",  color: "text-green-400",   icon: <Server size={13} />,    hint: "Ollama — free & private" },
  groq:   { label: "Groq",   color: "text-yellow-400",  icon: <Zap size={13} />,       hint: "Llama 3.3 70B — ultra fast, free" },
  grok:   { label: "Grok",   color: "text-sky-400",     icon: <Globe size={13} />,     hint: "xAI Grok — real-time web" },
  gemini: { label: "Gemini", color: "text-blue-400",    icon: <Sparkles size={13} />,  hint: "Google Gemini — multimodal" },
  claude: { label: "Claude", color: "text-orange-400",  icon: <Brain size={13} />,     hint: "Anthropic Claude — reasoning" },
  openai: { label: "OpenAI", color: "text-emerald-400", icon: <Cpu size={13} />,       hint: "GPT-4o — general purpose" },
};

// ─────────────────────────────────────────────────────────────────────────────
// Thinking mode metadata
// ─────────────────────────────────────────────────────────────────────────────

const MODE_META: Record<ThinkingMode, {
  label: string; desc: string; color: string; icon: React.ReactNode;
}> = {
  auto:  { label: "Auto",   desc: "Picks pipeline by complexity",    color: "text-purple-400", icon: <Brain size={13} /> },
  fast:  { label: "Fast",   desc: "Single call, instant response",   color: "text-green-400",  icon: <Zap size={13} /> },
  think: { label: "Think",  desc: "Analyze → Plan → Solve",          color: "text-blue-400",   icon: <FlaskConical size={13} /> },
  heavy: { label: "Heavy",  desc: "4-agent: Research→Reason→Synth→Validate", color: "text-orange-400", icon: <Layers size={13} /> },
};

// ─────────────────────────────────────────────────────────────────────────────
// Step label metadata (for think + heavy pipelines)
// ─────────────────────────────────────────────────────────────────────────────

const STEP_COLOR: Record<string, string> = {
  analyze:    "text-blue-400 border-blue-500/20 bg-blue-500/5",
  plan:       "text-yellow-400 border-yellow-500/20 bg-yellow-500/5",
  solve:      "text-green-400 border-green-500/20 bg-green-500/5",
  critique:   "text-purple-400 border-purple-500/20 bg-purple-500/5",
  research:   "text-sky-400 border-sky-500/20 bg-sky-500/5",
  reasoning:  "text-indigo-400 border-indigo-500/20 bg-indigo-500/5",
  synthesis:  "text-emerald-400 border-emerald-500/20 bg-emerald-500/5",
  validation: "text-rose-400 border-rose-500/20 bg-rose-500/5",
};

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface StepPanel {
  name: string;
  label: string;
  provider?: string;
  content: string;
  done: boolean;
}

interface ChatTurn {
  id: string;
  role: "user" | "assistant";
  content: string;
  provider?: string;
  complexity?: number;
  thinkingMode?: string;
  streaming?: boolean;
  activeStep?: string;
  steps: StepPanel[];
  error?: boolean;
}

// ─────────────────────────────────────────────────────────────────────────────
// Sub-components
// ─────────────────────────────────────────────────────────────────────────────

function ProviderBadge({ provider, complexity, mode }: {
  provider: string; complexity?: number; mode?: string;
}) {
  const meta = PROVIDER_META[provider] ?? { label: provider, color: "text-gray-400", icon: <Cpu size={13} />, hint: "" };
  return (
    <span className={`inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full bg-white/5 border border-white/8 ${meta.color}`} title={meta.hint}>
      {meta.icon} {meta.label}
      {complexity !== undefined && <span className="text-white/25 ml-0.5">c:{complexity}</span>}
      {mode && mode !== "fast" && (
        <span className={`ml-1 ${MODE_META[mode as ThinkingMode]?.color ?? "text-gray-400"}`}>
          {MODE_META[mode as ThinkingMode]?.icon}
        </span>
      )}
    </span>
  );
}

function StepPanelView({ step, isActive }: { step: StepPanel; isActive: boolean }) {
  const [open, setOpen] = useState(isActive);
  const colors = STEP_COLOR[step.name] ?? "text-white/50 border-white/10 bg-white/3";

  useEffect(() => { if (isActive) setOpen(true); }, [isActive]);

  return (
    <div className={`rounded-xl border text-xs mb-2 overflow-hidden ${colors}`}>
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-3 py-2 hover:bg-white/5 transition-colors"
      >
        <span className="flex items-center gap-1.5 font-medium">
          {isActive && !step.done && <Loader2 size={11} className="animate-spin" />}
          {step.done && <span className="opacity-60">✓</span>}
          {step.label || step.name}
          {step.provider && (
            <span className="text-white/25 font-normal">· {step.provider}</span>
          )}
        </span>
        {open ? <ChevronUp size={12} className="opacity-40" /> : <ChevronRight size={12} className="opacity-40" />}
      </button>
      {open && step.content && (
        <div className="px-3 pb-3 text-white/60 whitespace-pre-wrap leading-relaxed max-h-64 overflow-y-auto border-t border-white/5 pt-2">
          {step.content}
          {isActive && !step.done && (
            <span className="inline-block w-1.5 h-3 ml-0.5 bg-current animate-pulse rounded-sm align-text-bottom opacity-60" />
          )}
        </div>
      )}
    </div>
  );
}

function MessageBubble({ turn }: { turn: ChatTurn }) {
  if (turn.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-2xl rounded-br-sm px-4 py-3 text-sm leading-relaxed bg-purple-600/25 border border-purple-500/20 text-white/90">
          {turn.content}
        </div>
      </div>
    );
  }

  const hasPipeline = turn.steps.length > 0;
  const isFinalVisible = !turn.streaming || (turn.steps.length > 0 && turn.content.length > 0);

  return (
    <div className="flex justify-start">
      <div className="max-w-[88%] w-full">
        {/* Pipeline step panels */}
        {hasPipeline && (
          <div className="mb-2">
            {turn.steps.map(step => (
              <StepPanelView
                key={step.name}
                step={step}
                isActive={turn.activeStep === step.name}
              />
            ))}
          </div>
        )}

        {/* Final answer bubble */}
        {(turn.content || turn.streaming) && (
          <div className={`rounded-2xl rounded-bl-sm px-4 py-3 text-sm leading-relaxed ${
            turn.error
              ? "bg-red-500/10 border border-red-500/20 text-red-300"
              : "bg-white/5 border border-white/8 text-white/85"
          }`}>
            <div className="whitespace-pre-wrap break-words">
              {turn.content}
              {turn.streaming && !hasPipeline && (
                <span className="inline-block w-2 h-4 ml-0.5 bg-purple-400 animate-pulse rounded-sm align-text-bottom" />
              )}
              {turn.streaming && hasPipeline && turn.activeStep === "" && turn.content && (
                <span className="inline-block w-2 h-4 ml-0.5 bg-green-400 animate-pulse rounded-sm align-text-bottom" />
              )}
            </div>

            {/* Attribution footer */}
            {!turn.streaming && turn.provider && (
              <div className="mt-2 pt-2 border-t border-white/5">
                <ProviderBadge
                  provider={turn.provider}
                  complexity={turn.complexity}
                  mode={turn.thinkingMode}
                />
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Selector dropdowns
// ─────────────────────────────────────────────────────────────────────────────

function ProviderSelector({
  value, onChange, available, disabled,
}: {
  value: ExpertProvider; onChange: (v: ExpertProvider) => void;
  available: string[]; disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const meta = PROVIDER_META[value] ?? PROVIDER_META.auto;
  const allOptions: ExpertProvider[] = ["auto", ...available.filter(p => p !== "auto") as ExpertProvider[]];

  return (
    <div className="relative">
      <button
        onClick={() => !disabled && setOpen(o => !o)}
        disabled={disabled}
        className="flex items-center gap-1.5 px-2.5 py-2 h-10 rounded-xl bg-white/5 border border-white/10 text-xs text-white/50 hover:text-white/80 hover:bg-white/8 transition-colors min-w-[80px] disabled:opacity-40"
      >
        <span className={meta.color}>{meta.icon}</span>
        <span>{meta.label}</span>
        {open ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
      </button>
      {open && (
        <div className="absolute bottom-12 left-0 z-50 w-52 bg-[#1c1c21] border border-white/10 rounded-xl shadow-2xl overflow-hidden">
          <div className="px-3 py-1.5 text-[10px] text-white/25 uppercase tracking-wider border-b border-white/5">Provider</div>
          {allOptions.map(p => {
            const m = PROVIDER_META[p] ?? { label: p, color: "text-gray-400", icon: <Cpu size={13} />, hint: "" };
            return (
              <button key={p} onClick={() => { onChange(p); setOpen(false); }}
                className={`flex items-center gap-2 w-full px-3 py-2 text-xs hover:bg-white/5 transition-colors ${p === value ? "bg-white/5" : ""}`}>
                <span className={m.color}>{m.icon}</span>
                <div className="text-left">
                  <div className={`font-medium ${m.color}`}>{m.label}</div>
                  <div className="text-white/25 text-[10px]">{m.hint}</div>
                </div>
                {p === value && <span className="ml-auto text-purple-400">✓</span>}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ModeSelector({
  value, onChange, disabled,
}: {
  value: ThinkingMode; onChange: (v: ThinkingMode) => void; disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const meta = MODE_META[value];

  return (
    <div className="relative">
      <button
        onClick={() => !disabled && setOpen(o => !o)}
        disabled={disabled}
        className="flex items-center gap-1.5 px-2.5 py-2 h-10 rounded-xl bg-white/5 border border-white/10 text-xs text-white/50 hover:text-white/80 hover:bg-white/8 transition-colors min-w-[76px] disabled:opacity-40"
      >
        <span className={meta.color}>{meta.icon}</span>
        <span>{meta.label}</span>
        {open ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
      </button>
      {open && (
        <div className="absolute bottom-12 left-0 z-50 w-64 bg-[#1c1c21] border border-white/10 rounded-xl shadow-2xl overflow-hidden">
          <div className="px-3 py-1.5 text-[10px] text-white/25 uppercase tracking-wider border-b border-white/5">Thinking Pipeline</div>
          {(["auto", "fast", "think", "heavy"] as ThinkingMode[]).map(m => {
            const mm = MODE_META[m];
            return (
              <button key={m} onClick={() => { onChange(m); setOpen(false); }}
                className={`flex items-center gap-2 w-full px-3 py-2.5 text-xs hover:bg-white/5 transition-colors ${m === value ? "bg-white/5" : ""}`}>
                <span className={mm.color}>{mm.icon}</span>
                <div className="text-left">
                  <div className={`font-medium ${mm.color}`}>{mm.label}</div>
                  <div className="text-white/25 text-[10px]">{mm.desc}</div>
                </div>
                {m === value && <span className="ml-auto text-purple-400">✓</span>}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Main component
// ─────────────────────────────────────────────────────────────────────────────

const EXAMPLES = [
  { text: "What is 2+2?",                           hint: "→ fast" },
  { text: "Explain transformer attention mechanisms", hint: "→ think" },
  { text: "Design a distributed caching system",     hint: "→ heavy" },
  { text: "Debug: why is my Python list empty?",     hint: "→ auto" },
];

export default function ExpertView() {
  const [info, setInfo] = useState<ExpertInfo | null>(null);
  const [infoError, setInfoError] = useState(false);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [provider, setProvider] = useState<ExpertProvider>("auto");
  const [thinkingMode, setThinkingMode] = useState<ThinkingMode>("auto");
  const [streaming, setStreaming] = useState(false);
  const [showInfo, setShowInfo] = useState(false);

  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    fetchExpertInfo().then(setInfo).catch(() => setInfoError(true));
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`;
  }, [input]);

  const canSend = input.trim().length > 0 && !streaming;

  const handleSend = useCallback(() => {
    const query = input.trim();
    if (!query || streaming) return;

    const userTurn: ChatTurn = { id: `u-${Date.now()}`, role: "user", content: query, steps: [] };
    const assistantId = `a-${Date.now()}`;
    const assistantTurn: ChatTurn = {
      id: assistantId, role: "assistant", content: "",
      streaming: true, steps: [], activeStep: "",
    };

    setTurns(prev => [...prev, userTurn, assistantTurn]);
    setInput("");
    setStreaming(true);

    const history: ExpertMessage[] = turns
      .filter(t => !t.streaming)
      .map(t => ({ role: t.role, content: t.content }));

    abortRef.current = expertStream(
      { query, provider, thinking_mode: thinkingMode, history },
      {
        onMeta: (meta: StreamMeta) => {
          setTurns(prev => prev.map(t =>
            t.id === assistantId
              ? { ...t, provider: meta.provider, complexity: meta.complexity, thinkingMode: meta.thinking_mode }
              : t
          ));
        },

        onStep: (step: StreamStep) => {
          setTurns(prev => prev.map(t => {
            if (t.id !== assistantId) return t;
            const exists = t.steps.find(s => s.name === step.step);
            const newStep: StepPanel = { name: step.step, label: step.label, provider: step.provider, content: "", done: false };
            return {
              ...t,
              activeStep: step.step,
              steps: exists ? t.steps : [...t.steps, newStep],
            };
          }));
        },

        onStepEnd: (stepName: string) => {
          setTurns(prev => prev.map(t => {
            if (t.id !== assistantId) return t;
            return {
              ...t,
              activeStep: "",
              steps: t.steps.map(s => s.name === stepName ? { ...s, done: true } : s),
            };
          }));
        },

        onToken: (token: string, step?: string) => {
          setTurns(prev => prev.map(t => {
            if (t.id !== assistantId) return t;
            if (step) {
              // Token belongs to a pipeline step
              return {
                ...t,
                steps: t.steps.map(s =>
                  s.name === step ? { ...s, content: s.content + token } : s
                ),
              };
            }
            // Token is the final answer (fast mode)
            return { ...t, content: t.content + token };
          }));
        },

        onFinalAnswer: (token: string) => {
          // Final answer from think/heavy pipeline — goes to turn.content bubble
          setTurns(prev => prev.map(t =>
            t.id === assistantId ? { ...t, content: t.content + token } : t
          ));
        },

        onDone: () => {
          setTurns(prev => prev.map(t =>
            t.id === assistantId ? { ...t, streaming: false, activeStep: undefined } : t
          ));
          setStreaming(false);
        },

        onError: (err: string) => {
          setTurns(prev => prev.map(t =>
            t.id === assistantId
              ? { ...t, content: `Error: ${err}`, streaming: false, error: true, activeStep: undefined }
              : t
          ));
          setStreaming(false);
        },
      }
    );
  }, [input, provider, thinkingMode, streaming, turns]);

  const handleStop = () => {
    abortRef.current?.abort();
    setStreaming(false);
    setTurns(prev => prev.map(t => t.streaming ? { ...t, streaming: false, activeStep: undefined } : t));
  };

  const handleClear = () => {
    if (streaming) handleStop();
    setTurns([]);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (canSend) handleSend(); }
  };

  const availableProviders = info?.available_providers ?? [];

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-full bg-[#0f0f11] text-white select-none">

      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-white/8 flex-shrink-0">
        <div className="flex items-center gap-2">
          <Brain size={18} className="text-purple-400" />
          <span className="font-semibold text-white/90 text-sm tracking-wide">Expert</span>
          <span className="hidden sm:inline text-xs text-white/25">· sovereign AI</span>
        </div>
        <div className="flex items-center gap-1.5">
          <button onClick={() => setShowInfo(s => !s)}
            className="p-1.5 rounded-lg text-white/30 hover:text-white/70 hover:bg-white/5 transition-colors" title="Status">
            <Info size={14} />
          </button>
          {turns.length > 0 && (
            <button onClick={handleClear}
              className="p-1.5 rounded-lg text-white/30 hover:text-white/70 hover:bg-white/5 transition-colors" title="Clear">
              <RotateCcw size={14} />
            </button>
          )}
        </div>
      </div>

      {/* Status panel */}
      {showInfo && (
        <div className="px-5 py-3 border-b border-white/8 bg-white/2 text-xs text-white/45 flex-shrink-0 space-y-1.5">
          {infoError ? (
            <div className="flex items-center gap-1.5 text-red-400"><AlertCircle size={12} /> Cannot reach Expert backend</div>
          ) : info ? (
            <>
              <div className="flex flex-wrap gap-1">
                <span className="text-white/25">Providers:</span>
                {info.available_providers.map(p => {
                  const m = PROVIDER_META[p];
                  return m ? (
                    <span key={p} className={`${m.color} flex items-center gap-1`}>{m.icon} {m.label}</span>
                  ) : <span key={p}>{p}</span>;
                })}
              </div>
              <div><span className="text-white/25">Auto routing: </span>≤{info.local_threshold} → fast · ≤{info.groq_threshold} → think · &gt;{info.groq_threshold} → heavy</div>
              <div><span className="text-white/25">Local model: </span>{info.local_model}</div>
            </>
          ) : <div className="flex items-center gap-1.5"><Loader2 size={11} className="animate-spin" /> Loading…</div>}
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-5 space-y-5">
        {turns.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-5 text-center">
            <div>
              <Brain size={44} className="text-purple-500/60 mx-auto mb-3" />
              <p className="font-semibold text-white/60 text-base">Ask the Expert</p>
              <p className="text-xs text-white/25 mt-1">Routes to the best pipeline automatically</p>
            </div>
            <div className="grid grid-cols-2 gap-2 max-w-md w-full">
              {EXAMPLES.map(ex => (
                <button key={ex.text} onClick={() => setInput(ex.text)}
                  className="px-3 py-2.5 rounded-xl border border-white/8 bg-white/3 text-xs text-left hover:bg-white/6 hover:border-white/15 transition-all group">
                  <div className="text-white/55 group-hover:text-white/80 line-clamp-2">{ex.text}</div>
                  <div className="text-white/20 text-[10px] mt-1">{ex.hint}</div>
                </button>
              ))}
            </div>
            <div className="flex gap-3 text-[10px] text-white/20 mt-2">
              {(["fast", "think", "heavy"] as ThinkingMode[]).map(m => {
                const mm = MODE_META[m];
                return (
                  <span key={m} className={`flex items-center gap-1 ${mm.color}`}>
                    {mm.icon} <span className="text-white/30">{mm.label}: {mm.desc}</span>
                  </span>
                );
              })}
            </div>
          </div>
        )}

        {turns.map(turn => <MessageBubble key={turn.id} turn={turn} />)}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-4 pb-4 pt-2 border-t border-white/8 flex-shrink-0">
        <div className="flex items-end gap-2">
          <ProviderSelector
            value={provider}
            onChange={setProvider}
            available={availableProviders}
            disabled={streaming}
          />
          <ModeSelector
            value={thinkingMode}
            onChange={setThinkingMode}
            disabled={streaming}
          />
          <textarea
            ref={textareaRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask anything… Enter to send"
            rows={1}
            disabled={streaming}
            className="flex-1 resize-none rounded-xl bg-white/5 border border-white/10 text-white/85 placeholder-white/20 text-sm px-4 py-2.5 focus:outline-none focus:border-purple-500/40 focus:bg-white/7 transition-all min-h-10 max-h-40 disabled:opacity-50"
          />
          {streaming ? (
            <button onClick={handleStop}
              className="flex-shrink-0 w-10 h-10 flex items-center justify-center rounded-xl bg-red-500/15 border border-red-500/25 text-red-400 hover:bg-red-500/25 transition-colors"
              title="Stop">
              <span className="w-3 h-3 bg-red-400 rounded-sm" />
            </button>
          ) : (
            <button onClick={handleSend} disabled={!canSend}
              className="flex-shrink-0 w-10 h-10 flex items-center justify-center rounded-xl bg-purple-600/80 hover:bg-purple-600 disabled:opacity-25 disabled:cursor-not-allowed border border-purple-500/30 text-white transition-colors"
              title="Send (Enter)">
              <Send size={15} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
