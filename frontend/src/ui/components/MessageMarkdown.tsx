import React, { useCallback, useMemo, useState, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import { Check, Copy } from 'lucide-react'
import { fileAuthToken } from '../lib/fileUrl'
import { normalizeCitations } from './WebSources'

function useCopy(timeoutMs = 900) {
  const [copied, setCopied] = useState(false)
  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), timeoutMs)
    } catch {
      // noop (clipboard may be blocked)
    }
  }
  return { copied, copy }
}

function languageFromClassName(className?: string) {
  if (!className) return ''
  const m = /language-([a-z0-9_-]+)/i.exec(className)
  return m?.[1] ?? ''
}

/** Copy-enabled code block with language label */
function CodeBlock({ lang, raw }: { lang: string; raw: string }) {
  const { copied, copy } = useCopy()

  return (
    <div className="rounded-2xl border border-white/10 bg-black/35 overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 border-b border-white/10 bg-white/5">
        <div className="text-[11px] tracking-wide text-white/60">
          {lang ? lang.toUpperCase() : 'CODE'}
        </div>
        <button
          type="button"
          onClick={() => copy(raw)}
          className="hp-icon-btn inline-flex items-center gap-1.5 text-[11px] px-2 py-1 rounded-full bg-white/10 hover:bg-white/15 border border-white/10 hover:border-white/20 text-white/75 hover:text-white transition"
          title="Copy code"
          aria-label={copied ? 'Code copied' : 'Copy code'}
        >
          {copied ? <Check size={13} /> : <Copy size={13} />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre className="overflow-x-auto p-4">
        <code className="text-[13px] leading-relaxed">{raw}</code>
      </pre>
    </div>
  )
}

/** Image component with retry + visible error placeholder (no silent hiding). */
function MarkdownImage({ src, alt, rawSrc, onImageClick }: {
  src?: string; alt?: string; rawSrc?: string; onImageClick?: (src: string) => void
}) {
  const [state, setState] = useState<'loading' | 'loaded' | 'error'>('loading')
  const retryCount = useRef(0)
  const MAX_RETRIES = 2

  const handleError = useCallback(() => {
    if (retryCount.current < MAX_RETRIES) {
      retryCount.current += 1
      // Force re-fetch by appending a cache-bust param
      setState('loading')
    } else {
      setState('error')
    }
  }, [])

  if (state === 'error') {
    return (
      <div className="flex flex-col items-center gap-1.5 w-72 py-4 px-3 rounded-xl border border-white/10 bg-black/20 my-2 text-white/50 text-xs">
        <span>Image failed to load</span>
        {rawSrc && <span className="text-white/30 break-all text-[10px]">{rawSrc}</span>}
        <button
          type="button"
          onClick={() => { retryCount.current = 0; setState('loading') }}
          className="mt-1 px-2 py-0.5 rounded bg-white/10 hover:bg-white/20 text-white/60 hover:text-white/80 transition text-[11px]"
        >
          Retry
        </button>
      </div>
    )
  }

  // Append cache-bust on retries so browser re-fetches
  const finalSrc = retryCount.current > 0 && src
    ? `${src}${src.includes('?') ? '&' : '?'}_retry=${retryCount.current}`
    : src

  return (
    <img
      src={finalSrc}
      alt={alt || 'Photo'}
      onClick={src ? () => onImageClick?.(src) : undefined}
      className="w-72 max-h-96 h-auto object-contain rounded-xl my-2 cursor-zoom-in hover:opacity-90 transition-opacity"
      loading="lazy"
      onLoad={() => setState('loaded')}
      onError={handleError}
    />
  )
}

/**
 * Industry-grade Markdown renderer for assistant messages:
 * - GFM tables, task lists, etc.
 * - Safe by default (no raw HTML).
 * - Code blocks have header + language + copy button.
 */
/**
 * Math as models write it, in the form remark-math reads: `\[ … \]` becomes a `$$` block,
 * `\( … \)` becomes `$ … $`, and a `$` before a digit (a price: "$5 and $10") is escaped so it
 * never opens inline math. Code — fenced blocks and inline spans — is left exactly as written.
 */
export function normalizeMath(text: string): string {
  const parts = text.split(/(```[\s\S]*?(?:```|$)|`[^`\n]*`)/g)
  return parts
    .map((part, i) => {
      if (i % 2 === 1) return part                                   // code: untouched
      return part
        .replace(/\\\[([\s\S]+?)\\\]/g, (_m, body: string) => `\n$$\n${body.trim()}\n$$\n`)
        .replace(/\\\(([\s\S]+?)\\\)/g, (_m, body: string) => `$${body.trim()}$`)
        .replace(/(^|[^\\$])\$(?=\d)/g, '$1\\$')
    })
    .join('')
}

export function MessageMarkdown({ text, onImageClick, backendUrl }: { text: string; onImageClick?: (src: string) => void; backendUrl?: string }) {
  const normalized = useMemo(() => {
    let t = (text ?? '').replace(/\r\n/g, '\n')
    // Fix LLM-wrapped URLs: strip whitespace inside markdown image/link URLs
    // e.g. ![alt](http://host/path/ with-space) → ![alt](http://host/path/with-space)
    t = t.replace(/(!?\[[^\]]*\]\()([^)]+)\)/g, (_m, prefix, url) =>
      `${prefix}${url.replace(/\s+/g, '')})`
    )
    return normalizeMath(normalizeCitations(t))
  }, [text])

  /** Resolve backend-relative image paths (e.g. /comfy/view/..., /files/...) to full URLs.
   *  Appends auth token for /files/ paths that require authentication. */
  const resolveImgSrc = useCallback((src?: string): string | undefined => {
    if (!src) return src
    // Strip whitespace LLMs may inject mid-URL when line-wrapping
    src = src.replace(/\s+/g, '')
    // Resolve media:// refs via backend /media/resolve endpoint
    if (src.startsWith('media://') && backendUrl) {
      const tok = fileAuthToken(backendUrl)
      const base = backendUrl.replace(/\/+$/, '')
      const qp = tok ? `&token=${encodeURIComponent(tok)}` : ''
      // Pass current project_id as fallback so malformed LLM refs
      // (e.g. media://persona_1) can still resolve to the correct avatar
      const pid = localStorage.getItem('homepilot_current_project') || ''
      const pidParam = pid ? `&project_id=${encodeURIComponent(pid)}` : ''
      return `${base}/media/resolve?ref=${encodeURIComponent(src)}${qp}${pidParam}`
    }
    if (src.startsWith('http://') || src.startsWith('https://') || src.startsWith('data:') || src.startsWith('blob:')) {
      // For absolute backend URLs that contain /files/, the token — across origins only
      if (backendUrl && src.includes('/files/')) {
        const tok = fileAuthToken(backendUrl)
        if (tok) {
          const sep = src.includes('?') ? '&' : '?'
          return `${src}${sep}token=${encodeURIComponent(tok)}`
        }
      }
      return src
    }
    if (backendUrl) {
      const base = backendUrl.replace(/\/+$/, '')
      const path = src.startsWith('/') ? src : `/${src}`
      const full = `${base}${path}`
      // The token for /files/ paths — across origins only
      if (path.startsWith('/files/')) {
        const tok = fileAuthToken(backendUrl)
        if (tok) {
          const sep = full.includes('?') ? '&' : '?'
          return `${full}${sep}token=${encodeURIComponent(tok)}`
        }
      }
      return full
    }
    return src
  }, [backendUrl])

  // Memoize the components object so ReactMarkdown doesn't remount
  // custom elements (especially <img>) on every parent re-render.
  const mdComponents = useMemo(() => ({
    a: ({ children, href, title, ...props }: any) => {
      // A citation ("[n]" linked to its source) is a small numbered pill, as ChatGPT shows it.
      const label = Array.isArray(children) ? children.join('') : String(children ?? '')
      const cite = /^\[(\d{1,3})\]$/.exec(label.trim())
      if (cite) {
        return (
          <a
            {...props}
            href={href}
            title={title || href}
            target="_blank"
            rel="noreferrer"
            data-testid="citation"
            className="hp-cite ml-0.5 inline-flex h-[18px] min-w-[18px] -translate-y-[1px] items-center justify-center rounded-full bg-white/10 px-1.5 align-middle text-[11px] font-medium leading-none text-white/75 no-underline transition-colors hover:bg-violet-500/40 hover:text-white"
          >
            {cite[1]}
          </a>
        )
      }
      return (
        <a
          {...props}
          href={href}
          title={title}
          target="_blank"
          rel="noreferrer"
          className="underline decoration-white/30 hover:decoration-white/70 text-white"
        >
          {children}
        </a>
      )
    },
    code: ({ children, className }: any) => {
      const isBlock = !!className
      const lang = languageFromClassName(className)
      const raw = String(children ?? '').replace(/\n$/, '')
      if (!isBlock) {
        return (
          <code className="px-1.5 py-0.5 rounded-md bg-white/10 border border-white/10 text-[0.95em]">
            {children}
          </code>
        )
      }

      return <CodeBlock lang={lang} raw={raw} />
    },
    h1: ({ children }: any) => <h1 className="text-xl font-semibold mt-3 mb-2">{children}</h1>,
    h2: ({ children }: any) => <h2 className="text-lg font-semibold mt-3 mb-2">{children}</h2>,
    h3: ({ children }: any) => <h3 className="text-base font-semibold mt-3 mb-2">{children}</h3>,
    ul: ({ children }: any) => <ul className="list-disc pl-5 space-y-1">{children}</ul>,
    ol: ({ children }: any) => <ol className="list-decimal pl-5 space-y-1">{children}</ol>,
    li: ({ children }: any) => <li className="leading-relaxed">{children}</li>,
    blockquote: ({ children }: any) => (
      <blockquote className="border-l-2 border-white/15 pl-4 italic text-white/90">{children}</blockquote>
    ),
    table: ({ children }: any) => (
      <div className="overflow-x-auto rounded-2xl border border-white/10">
        <table className="w-full text-sm">{children}</table>
      </div>
    ),
    thead: ({ children }: any) => <thead className="bg-white/5">{children}</thead>,
    th: ({ children }: any) => <th className="text-left px-3 py-2 font-semibold">{children}</th>,
    td: ({ children }: any) => <td className="px-3 py-2 border-t border-white/10">{children}</td>,
    img: ({ src, alt }: any) => {
      const resolved = resolveImgSrc(src)
      return <MarkdownImage src={resolved} alt={alt} rawSrc={src} onImageClick={onImageClick} />
    },
    p: ({ children }: any) => <p className="leading-relaxed">{children}</p>,
  }), [resolveImgSrc, onImageClick])

  return (
    <div className="prose prose-invert max-w-none prose-p:my-2 prose-pre:my-2 prose-ul:my-2 prose-ol:my-2 prose-li:my-1 prose-hr:my-4 prose-blockquote:my-3">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        // throwOnError false: a malformed formula shows as red source text, never breaks the reply.
        rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: 'ignore' }]]}
        components={mdComponents}
      >
        {normalized}
      </ReactMarkdown>
    </div>
  )
}
