/**
 * The work behind an Expert answer, as one quiet card above the reply: a small badge, a title
 * ("Reasoning completed", "Validated response"), a muted subline ("Expert · 3 steps"), and the
 * elapsed time. Open while it works, collapsed once done. Opening it shows the stages with
 * their state, the tool chips, the validator's verdict and any notices.
 *
 * One animation at a time: collapsed, the badge spins and the title names the current stage;
 * open, the badge is still and only the active stage pulses in the list.
 *
 * It is an operational summary — stages, tools, elapsed time, validation — never a model's
 * private reasoning: stage outputs stay behind a "Show output" disclosure.
 */
import React from 'react'
import {
  Check, ChevronDown, ChevronRight, FolderOpen, Globe, LayoutGrid, Lightbulb, Loader2, Search,
  ShieldAlert, ShieldCheck, Telescope, X, Zap,
} from 'lucide-react'

import type { ExpertStep, ExpertToolChip, ExpertTrace, ExpertVerdict } from '../lib/expertStream'

const MODE_LABEL: Record<string, string> = { fast: 'Fast', think: 'Expert', expert: 'Expert', heavy: 'Heavy', deep: 'Deep research' }

/** Professional names for the pipeline stages (the server's labels carry emoji). */
const STAGE: Record<string, { doing: string; done: string; detail: string }> = {
  analyze: { doing: 'Analyzing the request', done: 'Analyzed the request', detail: 'What is asked, the domain, the gaps' },
  plan: { doing: 'Planning the approach', done: 'Planned the approach', detail: 'The steps to a complete answer' },
  solve: { doing: 'Writing the answer', done: 'Wrote the answer', detail: 'With tools when a fact was needed' },
  critique: { doing: 'Reviewing the answer', done: 'Reviewed the answer', detail: '' },
  research: { doing: 'Investigating', done: 'Investigated', detail: 'Searched and read the sources' },
  reasoning: { doing: 'Evaluating', done: 'Evaluated', detail: 'Reasoned from the evidence' },
  synthesis: { doing: 'Drafting the answer', done: 'Drafted the answer', detail: '' },
  validation: { doing: 'Validating', done: 'Validated', detail: 'Checked accuracy and consistency' },
}

export function stageCopy(step: Pick<ExpertStep, 'step' | 'label'>): { doing: string; done: string; detail: string } {
  const known = STAGE[step.step]
  if (known) return known
  const clean = (step.label || step.step).replace(/^[^\p{L}\p{N}]+/u, '').replace(/…$/u, '').trim()
  return { doing: `${clean}…`, done: clean, detail: '' }
}

const VERDICT_TITLE: Record<string, string> = {
  validated: 'Validated response',
  corrected: 'Corrected after validation',
  needs_review: 'Needs review',
  reviewed: 'Reviewed response',
}

const DEEP_TITLE: Record<string, string> = {
  planning: 'Planning the research', researching: 'Researching', writing: 'Writing the report',
  done: 'Research complete', failed: 'Research failed', cancelled: 'Research stopped',
}

export function shortModel(model?: string | null): string {
  return (model || '').split('/').pop() || ''
}

/** Title and subline for the card head. `open` changes what the head says while pending, so
 *  the running stage is named once: in the head when collapsed, in the list when open. */
export function stripParts(trace: ExpertTrace, pending?: boolean, open?: boolean): { title: string; sub: string } {
  const plan = trace.plan ?? []
  const steps = trace.steps
  const mode = MODE_LABEL[trace.mode || ''] || ''
  const doneSteps = steps.filter((s) => s.status === 'done').length
  const running = steps.find((s) => s.status === 'running')
  const runningTool = trace.tools.find((t) => t.status === 'running')
  const toolsPart = trace.tools.length ? `${trace.tools.length} tool${trace.tools.length === 1 ? '' : 's'}` : ''
  const parts = (...xs: Array<string | false | undefined | ''>) => xs.filter(Boolean).join(' · ')

  if (plan.length) {
    const finished = plan.filter((p) => p.status === 'done').length
    const progress = `${finished} of ${plan.length} questions`
    if (pending) {
      const status = trace.status || 'researching'
      return open
        ? { title: parts('Deep research', progress), sub: DEEP_TITLE[status] || 'Working' }
        : { title: status === 'researching' ? parts(DEEP_TITLE[status], progress) : DEEP_TITLE[status] || 'Working', sub: 'Deep research' }
    }
    return { title: DEEP_TITLE[trace.status || 'done'] || 'Research complete', sub: parts('Deep research', progress, toolsPart) }
  }
  if (pending) {
    if (open) return { title: parts(mode || 'Working', 'working'), sub: steps.length > 1 ? `Step ${Math.min(doneSteps + 1, steps.length)} of ${steps.length}` : runningTool?.label || '' }
    if (runningTool) return { title: runningTool.label, sub: parts(mode) }
    if (running) return { title: stageCopy(running).doing, sub: steps.length > 1 ? `${mode ? `${mode} · ` : ''}step ${doneSteps + 1} of ${steps.length}` : mode }
    return { title: 'Working', sub: mode }
  }
  if (steps.length) {
    const title = trace.mode === 'heavy' && trace.verdict ? VERDICT_TITLE[trace.verdict.verdict] || 'Reasoning completed' : 'Reasoning completed'
    return { title, sub: parts(mode, `${doneSteps} step${doneSteps === 1 ? '' : 's'}`, toolsPart) }
  }
  if (trace.tools.length) return { title: `Used ${toolsPart}`, sub: parts(mode, trace.tools.map((t) => t.label).join(' · ')) }
  if (trace.notices.length) return { title: 'Note', sub: trace.notices[0] }
  return { title: mode || 'Details', sub: trace.effort?.reason || '' }
}

/** Kept for callers that only need the headline. */
export function stripTitle(trace: ExpertTrace, pending?: boolean, open?: boolean): string {
  return stripParts(trace, pending, open).title
}

function modeIcon(trace: ExpertTrace, pending: boolean, open: boolean) {
  if (pending && !open) return <Loader2 size={15} className="animate-spin motion-reduce:animate-none" />
  if (trace.plan?.length) return <Telescope size={15} />
  if (trace.mode === 'heavy') return trace.verdict ? <ShieldCheck size={15} /> : <LayoutGrid size={15} />
  if (trace.mode === 'fast') return <Zap size={15} />
  return <Lightbulb size={15} />
}

function chipIcon(chip: ExpertToolChip) {
  if (chip.status === 'running') return <Loader2 size={11} className="animate-spin motion-reduce:animate-none" />
  if (chip.status === 'failed') return <X size={11} />
  if (/project/i.test(chip.label)) return <FolderOpen size={11} />
  return /web/i.test(chip.label) ? <Globe size={11} /> : <Search size={11} />
}

export function ToolChips({ tools }: { tools: ExpertToolChip[] }) {
  if (!tools.length) return null
  return (
    <div className="flex flex-wrap gap-[6px]" data-testid="expert-tools">
      {tools.map((t) => (
        <span
          key={t.id}
          data-testid="expert-tool-chip"
          data-status={t.status}
          className={[
            'inline-flex items-center gap-[6px] rounded-[7px] border px-[7px] py-[3px] text-[10.5px]',
            t.status === 'failed' ? 'border-[#d7bc8e55] text-[#d7bc8e]' : 'border-[#2b2d2e] text-[#9a9d9a]',
          ].join(' ')}
          title={t.summary || t.label}
        >
          {chipIcon(t)}
          <span className="truncate max-w-[20rem]">{t.label}</span>
          {t.status === 'done' && t.summary ? <span className="text-[#7e817f]">· {t.summary}</span> : null}
        </span>
      ))}
    </div>
  )
}

function VerdictBadge({ verdict, compact }: { verdict: ExpertVerdict; compact?: boolean }) {
  const kind = verdict.verdict
  const style =
    kind === 'validated' ? 'border-[#a5c49a44] bg-[#a5c49a14] text-[#c5dcbc]'
    : kind === 'corrected' ? 'border-[#8fb3c744] bg-[#8fb3c714] text-[#bcd6e3]'
    : kind === 'needs_review' ? 'border-[#d7bc8e55] bg-[#d7bc8e14] text-[#e6d2ab]'
    : 'border-[#2b2d2e] bg-transparent text-[#9a9d9a]'
  const label = kind === 'validated' ? 'Validated' : kind === 'corrected' ? 'Corrected by validator' : kind === 'needs_review' ? 'Needs review' : 'Reviewed'
  return (
    <span
      data-testid="expert-verdict"
      className={['inline-flex items-center gap-1 rounded-full border text-[10.5px]', compact ? 'px-2 py-[2px]' : 'px-[9px] py-[4px]', style].join(' ')}
      title={verdict.note}
    >
      {kind === 'validated' || kind === 'corrected' ? <ShieldCheck size={11} /> : <ShieldAlert size={11} />}
      {label}
    </span>
  )
}

function StageSymbol({ state }: { state: 'done' | 'active' | 'pending' | 'skipped' }) {
  if (state === 'done') return <span className="grid h-[18px] w-[18px] shrink-0 place-items-center rounded-full bg-[#a5c49a18] text-[#a5c49a]"><Check size={11} /></span>
  if (state === 'skipped') return <span className="grid h-[18px] w-[18px] shrink-0 place-items-center rounded-full bg-[#1c1e21] text-[#7e817f]"><X size={11} /></span>
  if (state === 'active') return <span className="grid h-[18px] w-[18px] shrink-0 place-items-center rounded-full bg-[#d7bc8e22] text-[#d7bc8e] animate-pulse motion-reduce:animate-none"><span className="h-[6px] w-[6px] rounded-full bg-current" /></span>
  return <span className="grid h-[18px] w-[18px] shrink-0 place-items-center rounded-full bg-[#1c1e21] text-[#7e817f]"><span className="h-[5px] w-[5px] rounded-full bg-current" /></span>
}

/** A validator's "limitations" worth showing: not empty, and not a way of saying "none". */
export function hasLimitations(text?: string | null): boolean {
  const t = (text || '').trim().replace(/[.!]+$/, '').toLowerCase()
  return Boolean(t) && !['none', 'n/a', 'na', 'no', 'nothing', 'null', '-', 'no limitations', 'none noted'].includes(t)
}

/** A stage's reasoning, read as it is written: quiet prose behind a hairline, following the
 *  newest line while the stage runs. Shown only when the chat's "Show reasoning" is on. */
function Reasoning({ text, live }: { text: string; live: boolean }) {
  const ref = React.useRef<HTMLDivElement | null>(null)
  React.useEffect(() => {
    const el = ref.current
    if (el && live) el.scrollTop = el.scrollHeight
  }, [text, live])
  return (
    <div
      ref={ref}
      data-testid="expert-reasoning"
      className="mt-[6px] max-h-64 overflow-y-auto whitespace-pre-wrap break-words border-l border-[#2f3234] pl-3 text-[11.5px] leading-[1.65] text-[#9a9d9a]"
    >
      {text}
    </div>
  )
}

export function ExpertSteps({
  trace, pending, defaultOpen, showReasoning,
}: { trace: ExpertTrace; pending?: boolean; defaultOpen?: boolean; showReasoning?: boolean }) {
  // Open while it works, collapsed once done — unless the reader toggled it themselves.
  const [toggled, setToggled] = React.useState<boolean | null>(defaultOpen ?? null)
  const open = toggled ?? Boolean(pending)
  const hasSteps = trace.steps.length > 0
  const hasPlan = Boolean(trace.plan && trace.plan.length)
  const nothing = !hasSteps && !hasPlan && !trace.tools.length && !trace.verdict && !trace.notices.length
  if (nothing) return null
  const parts = stripParts(trace, pending, open)
  const title = parts.title
  // While the turn waits in line for a busy provider, the subline says so instead of the stage.
  const sub = pending && trace.waiting ? trace.waiting : parts.sub
  const model = shortModel(trace.model)
  const elapsed = typeof trace.elapsed_s === 'number' ? `${trace.elapsed_s}s` : ''

  return (
    <div className="mb-4 overflow-hidden rounded-[15px] border border-[#2b2d2e] bg-[#17191c] shadow-[0_2px_9px_rgba(0,0,0,0.18)]" data-testid="expert-steps">
      <button
        type="button"
        onClick={() => setToggled(!open)}
        className="flex w-full items-center gap-[10px] px-[15px] py-[12px] text-left hover:bg-[#1e2023] transition-colors"
        aria-expanded={open}
        aria-label={open ? 'Hide how this was answered' : 'Show how this was answered'}
      >
        <span className="grid h-[27px] w-[27px] shrink-0 place-items-center rounded-[9px] bg-[#adc09b22] text-[#ced7c1]">
          {modeIcon(trace, Boolean(pending), open)}
        </span>
        <span className="min-w-0 flex-1">
          <span
            className={['block truncate text-[12px] font-semibold leading-tight text-[#e9e9e5]', pending && !open ? 'hp-shimmer-text' : ''].join(' ')}
            data-testid="expert-title"
          >
            {title}
          </span>
          {sub ? <span className="mt-[3px] block truncate text-[11px] text-[#7e817f]">{sub}</span> : null}
        </span>
        <span className="ml-auto flex shrink-0 items-center gap-[10px] text-[11px] text-[#7e817f]">
          {!open && !pending && trace.verdict ? <VerdictBadge verdict={trace.verdict} compact /> : null}
          {pending && !open ? (
            <span className="inline-flex items-center gap-[6px]"><span className="h-[6px] w-[6px] rounded-full bg-[#d7bc8e] animate-pulse motion-reduce:animate-none" />Live</span>
          ) : elapsed ? <span>{elapsed}</span> : null}
          {model ? <span className="hidden max-w-[12rem] truncate sm:inline" title={trace.model || ''}>{model}</span> : null}
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>
      </button>
      {open ? (
        <div className="space-y-[10px] border-t border-[#242627] px-4 pb-[14px] pt-[12px] sm:pl-[52px]">
          {trace.project?.id ? (
            <div className="flex items-center gap-2 text-[11px] text-[#c5dcbc]" data-testid="expert-project">
              <FolderOpen size={12} />
              Using project {trace.project.name || trace.project.id}
            </div>
          ) : null}
          {hasPlan ? (
            <ol className="space-y-[2px]" data-testid="expert-plan">
              {trace.plan!.map((p) => (
                <li key={p.id} className="flex items-start gap-[11px] py-[5px] text-[12px] text-[#e9e9e5]">
                  <StageSymbol state={p.status === 'done' ? 'done' : p.status === 'running' ? 'active' : p.status === 'skipped' || p.status === 'failed' ? 'skipped' : 'pending'} />
                  <span className="min-w-0">
                    <span className={['font-medium', p.status === 'skipped' || p.status === 'failed' ? 'line-through text-[#7e817f]' : ''].join(' ')}>{p.title}</span>
                    {p.summary ? <span className="mt-[2px] block truncate text-[11px] text-[#7e817f]">{p.summary}</span> : null}
                  </span>
                </li>
              ))}
            </ol>
          ) : null}
          {hasSteps ? (
            <ol className="space-y-[2px]">
              {trace.steps.map((s) => {
                const copy = stageCopy(s)
                const active = s.status === 'running'
                return (
                  <li key={s.step} className="flex items-start gap-[11px] py-[5px] text-[12px] text-[#e9e9e5]">
                    <StageSymbol state={active ? 'active' : 'done'} />
                    <span className="min-w-0 flex-1">
                      <span className="font-medium">{active ? copy.doing : copy.done}</span>
                      {copy.detail ? <span className="mt-[2px] block text-[11px] text-[#7e817f]">{copy.detail}</span> : null}
                      {s.content && s.role !== 'answer' && !(s.step === 'validation' && trace.verdict && !active) ? (
                        showReasoning ? (
                          <Reasoning text={s.content} live={active} />
                        ) : (
                          <details className="mt-[4px]">
                            <summary className="cursor-pointer list-none text-[11px] text-[#7e817f] hover:text-[#c9ccc8]">Show output</summary>
                            <pre className="mt-1 max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-[#101113] p-2 text-[11px] leading-snug text-[#9a9d9a]">{s.content}</pre>
                          </details>
                        )
                      ) : null}
                    </span>
                  </li>
                )
              })}
            </ol>
          ) : null}
          <ToolChips tools={trace.tools} />
          {trace.verdict ? (
            <div className="space-y-[6px]" data-testid="expert-verdict-detail">
              <div className="flex flex-wrap items-center gap-2">
                <VerdictBadge verdict={trace.verdict} />
                <span className="text-[11px] text-[#7e817f]">{trace.verdict.note}{trace.verdict.method ? ` · ${trace.verdict.method}` : ''}</span>
              </div>
              {trace.verdict.issues?.length ? (
                <ul className="space-y-[2px] pl-1">
                  {trace.verdict.issues.map((i, idx) => (
                    <li key={idx} className="text-[11px] text-[#c9ccc8]">
                      <span className={i.severity === 'high' ? 'text-[#e6d2ab]' : 'text-[#7e817f]'}>{i.severity}</span> · {i.text}
                    </li>
                  ))}
                </ul>
              ) : null}
              {hasLimitations(trace.verdict.limitations) ? <div className="text-[11px] text-[#7e817f]">Not verified: {trace.verdict.limitations}</div> : null}
            </div>
          ) : null}
          {trace.notices.length ? (
            <ul className="space-y-[2px]" data-testid="expert-notices">
              {trace.notices.map((n) => (
                <li key={n} className="flex items-start gap-2 text-[11px] text-[#b9b3a4]"><span className="mt-[6px] h-[4px] w-[4px] shrink-0 rounded-full bg-[#d7bc8e]" />{n}</li>
              ))}
            </ul>
          ) : null}
          {trace.effort?.reason && (hasSteps || hasPlan) ? <div className="text-[10.5px] text-[#5f625f]">{trace.effort.reason}</div> : null}
        </div>
      ) : null}
    </div>
  )
}

export default ExpertSteps
