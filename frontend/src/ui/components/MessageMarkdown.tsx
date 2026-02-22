import React, { useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Check, Copy } from 'lucide-react'

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
          className="inline-flex items-center gap-1.5 text-[11px] px-2 py-1 rounded-full bg-white/10 hover:bg-white/15 border border-white/10 hover:border-white/20 text-white/75 hover:text-white transition"
          title="Copy code"
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

/**
 * Industry-grade Markdown renderer for assistant messages:
 * - GFM tables, task lists, etc.
 * - Safe by default (no raw HTML).
 * - Code blocks have header + language + copy button.
 */
export function MessageMarkdown({ text, onImageClick, backendUrl }: { text: string; onImageClick?: (src: string) => void; backendUrl?: string }) {
  const normalized = useMemo(() => (text ?? '').replace(/\r\n/g, '\n'), [text])

  /** Resolve backend-relative image paths (e.g. /comfy/view/..., /files/...) to full URLs.
   *  Appends auth token for /files/ paths that require authentication. */
  const resolveImgSrc = (src?: string): string | undefined => {
    if (!src) return src
    if (src.startsWith('http://') || src.startsWith('https://') || src.startsWith('data:') || src.startsWith('blob:')) {
      // For absolute backend URLs that contain /files/, append token
      if (backendUrl && src.includes('/files/')) {
        const tok = localStorage.getItem('homepilot_auth_token') || ''
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
      // Append token for /files/ paths
      if (path.startsWith('/files/')) {
        const tok = localStorage.getItem('homepilot_auth_token') || ''
        if (tok) {
          const sep = full.includes('?') ? '&' : '?'
          return `${full}${sep}token=${encodeURIComponent(tok)}`
        }
      }
      return full
    }
    return src
  }

  return (
    <div className="prose prose-invert max-w-none prose-p:my-2 prose-pre:my-2 prose-ul:my-2 prose-ol:my-2 prose-li:my-1 prose-hr:my-4 prose-blockquote:my-3">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ children, href, ...props }) => (
            <a
              {...props}
              href={href}
              target="_blank"
              rel="noreferrer"
              className="underline decoration-white/30 hover:decoration-white/70 text-white"
            >
              {children}
            </a>
          ),
          code: ({ children, className }) => {
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
          h1: ({ children }) => <h1 className="text-xl font-semibold mt-3 mb-2">{children}</h1>,
          h2: ({ children }) => <h2 className="text-lg font-semibold mt-3 mb-2">{children}</h2>,
          h3: ({ children }) => <h3 className="text-base font-semibold mt-3 mb-2">{children}</h3>,
          ul: ({ children }) => <ul className="list-disc pl-5 space-y-1">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal pl-5 space-y-1">{children}</ol>,
          li: ({ children }) => <li className="leading-relaxed">{children}</li>,
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-white/15 pl-4 italic text-white/90">{children}</blockquote>
          ),
          table: ({ children }) => (
            <div className="overflow-x-auto rounded-2xl border border-white/10">
              <table className="w-full text-sm">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-white/5">{children}</thead>,
          th: ({ children }) => <th className="text-left px-3 py-2 font-semibold">{children}</th>,
          td: ({ children }) => <td className="px-3 py-2 border-t border-white/10">{children}</td>,
          img: ({ src, alt }) => {
            const resolved = resolveImgSrc(src)
            return (
              <img
                src={resolved}
                alt={alt || 'Photo'}
                onClick={resolved ? () => onImageClick?.(resolved) : undefined}
                className="w-72 max-h-96 h-auto object-contain rounded-xl border border-white/10 bg-black/20 my-2 cursor-zoom-in hover:opacity-90 transition-opacity"
                loading="lazy"
                onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
              />
            )
          },
          p: ({ children }) => <p className="leading-relaxed">{children}</p>,
        }}
      >
        {normalized}
      </ReactMarkdown>
    </div>
  )
}
