/**
 * The web sources behind a chat answer (backend/app/web_search.py).
 *
 * The pattern people now expect from search-grounded assistants: a quiet line saying what was
 * searched and how many sources were used, the sources as chips that open the page, and every
 * [n] in the answer itself a link to source n. Nothing here fetches anything — no favicons from
 * a third-party service; a source's mark is its own first letter — so opening an old chat
 * contacts no site.
 *
 * When search could not run, the answer was written from the model's own knowledge, and this
 * says so in amber with what to start, instead of letting stale facts pass as current.
 */
import React, { createContext, useState } from 'react'
import { AlertTriangle, ChevronDown, Globe } from 'lucide-react'

export type WebSearchStatus = { available: boolean; provider?: string; hint?: string }

/**
 * This chat's "Search the web" switch, shared by the composer's + menu and Chat settings so
 * the two can never disagree. `available` is false outside the standard chat — persona and
 * project chats keep their own setup — and the controls then do not render at all.
 */
export const WebSearchToggleContext = createContext<{
  available: boolean
  on: boolean
  setOn: (next: boolean) => void
  check: () => Promise<WebSearchStatus>
} | null>(null)

export type WebSource = {
  n: number
  title: string
  url: string
  domain: string
  snippet?: string
  published?: string | null
  read?: boolean
}

export type WebSearchInfo = {
  status: 'ok' | 'no_results' | 'unavailable'
  query: string
  sources: WebSource[]
  took_ms?: number
  message?: string
  hint?: string
}

export function parseWebSearch(raw: unknown): WebSearchInfo | null {
  if (!raw || typeof raw !== 'object') return null
  const v = raw as Record<string, unknown>
  const status = v.status === 'ok' || v.status === 'no_results' || v.status === 'unavailable' ? v.status : null
  if (!status) return null
  const sources = Array.isArray(v.sources)
    ? (v.sources as Array<Record<string, unknown>>)
        .filter((s) => s && typeof s.url === 'string' && /^https?:\/\//i.test(s.url as string))
        .map((s, i) => ({
          n: Number(s.n) || i + 1,
          title: String(s.title || s.domain || s.url),
          url: String(s.url),
          domain: String(s.domain || ''),
          snippet: typeof s.snippet === 'string' ? s.snippet : undefined,
          published: typeof s.published === 'string' ? s.published : null,
          read: !!s.read,
        }))
    : []
  return {
    status,
    query: typeof v.query === 'string' ? v.query : '',
    sources,
    took_ms: typeof v.took_ms === 'number' ? v.took_ms : undefined,
    message: typeof v.message === 'string' ? v.message : undefined,
    hint: typeof v.hint === 'string' ? v.hint : undefined,
  }
}

/**
 * The answer's [n] markers as links to their sources, for the markdown renderer. Only numbers
 * that are real sources, never inside code, and never a marker that is already a link.
 */
export function linkCitations(text: string, sources: WebSource[]): string {
  if (!text || !sources.length) return text
  const byN = new Map(sources.map((s) => [s.n, s]))
  return text
    .split(/(```[\s\S]*?```|`[^`\n]*`)/g)
    .map((part, i) => {
      if (i % 2 === 1) return part // code
      return part.replace(/\[(\d{1,2})\](?!\()/g, (whole, digits: string, offset: number, all: string) => {
        if (offset > 0 && all[offset - 1] === '[') return whole // already "[[n]](…)"
        const source = byN.get(Number(digits))
        if (!source) return whole
        const title = source.title.replace(/["\\]/g, '')
        return `[[${digits}]](${source.url} "${title}")`
      })
    })
    .join('')
}

function SourceChip({ source }: { source: WebSource }) {
  return (
    <a
      href={source.url}
      target="_blank"
      rel="noopener noreferrer"
      title={source.snippet ? `${source.title}\n\n${source.snippet}` : source.title}
      data-testid="web-source"
      className="group inline-flex max-w-[15rem] items-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-2.5 py-1.5 text-left transition-colors hover:border-white/20 hover:bg-white/[0.07]"
    >
      <span className="grid h-5 w-5 shrink-0 place-items-center rounded-md bg-white/10 text-[10px] font-semibold uppercase text-white/70" aria-hidden>
        {(source.domain || '?').charAt(0)}
      </span>
      <span className="min-w-0">
        <span className="block truncate text-[12px] leading-4 text-white/85 group-hover:text-white">{source.title}</span>
        <span className="block truncate text-[11px] leading-4 text-white/40">
          {source.n}. {source.domain}
          {source.published ? ` · ${source.published.slice(0, 10)}` : ''}
        </span>
      </span>
    </a>
  )
}

export function WebSources({ web }: { web: WebSearchInfo }) {
  const [all, setAll] = useState(false)

  if (web.status === 'unavailable') {
    return (
      <div className="mt-3 flex items-start gap-2 rounded-xl border border-amber-400/20 bg-amber-400/[0.06] px-3 py-2 text-[12px] leading-5 text-amber-100/85" role="note" data-testid="web-unavailable">
        <AlertTriangle size={14} className="mt-0.5 shrink-0 text-amber-300" aria-hidden />
        <span>
          {web.message || "Web search isn't available right now, so this answer may be out of date."}
          {web.hint ? <span className="block text-amber-100/55">{web.hint}</span> : null}
        </span>
      </div>
    )
  }

  if (web.status === 'no_results') {
    return (
      <div className="mt-3 flex items-center gap-2 text-[12px] text-white/45" data-testid="web-no-results">
        <Globe size={13} aria-hidden /> The web search for “{web.query}” found nothing usable.
      </div>
    )
  }

  const shown = all ? web.sources : web.sources.slice(0, 4)
  return (
    <section className="mt-3" aria-label="Web sources" data-testid="web-sources">
      <div className="flex items-center gap-1.5 text-[12px] text-white/45">
        <Globe size={13} aria-hidden />
        <span>
          Searched the web for <span className="text-white/65">“{web.query}”</span> · {web.sources.length} source{web.sources.length === 1 ? '' : 's'}
        </span>
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        {shown.map((s) => <SourceChip key={s.n} source={s} />)}
        {web.sources.length > shown.length ? (
          <button type="button" onClick={() => setAll(true)}
            className="inline-flex items-center gap-1 rounded-xl border border-white/10 px-2.5 py-1.5 text-[12px] text-white/55 hover:bg-white/[0.06] hover:text-white">
            +{web.sources.length - shown.length} more <ChevronDown size={12} aria-hidden />
          </button>
        ) : null}
      </div>
    </section>
  )
}

export default WebSources
