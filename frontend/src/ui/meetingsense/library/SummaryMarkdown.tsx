/**
 * A generated meeting document, rendered as formatted text rather than raw markdown.
 * Links open in a new tab; images and raw HTML are not rendered (the text comes from a model).
 */
import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export function SummaryMarkdown({ text, className = '' }: { text: string; className?: string }) {
    return (
        <div className={`hp-meeting-md text-[15px] leading-relaxed text-white/85 ${className}`}>
            <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                skipHtml
                components={{
                    h1: ({ children }) => <h4 className="mb-2 mt-4 text-base font-semibold text-white first:mt-0">{children}</h4>,
                    h2: ({ children }) => <h4 className="mb-2 mt-4 text-base font-semibold text-white first:mt-0">{children}</h4>,
                    h3: ({ children }) => <h5 className="mb-1.5 mt-3 font-semibold text-white first:mt-0">{children}</h5>,
                    p: ({ children }) => <p className="mb-3 last:mb-0">{children}</p>,
                    ul: ({ children }) => <ul className="mb-3 list-disc space-y-1 pl-5 last:mb-0">{children}</ul>,
                    ol: ({ children }) => <ol className="mb-3 list-decimal space-y-1 pl-5 last:mb-0">{children}</ol>,
                    strong: ({ children }) => <strong className="font-semibold text-white">{children}</strong>,
                    a: ({ href, children }) => <a href={href} target="_blank" rel="noreferrer noopener" className="text-violet-300 underline-offset-2 hover:underline">{children}</a>,
                    img: () => null,
                    table: ({ children }) => <div className="mb-3 overflow-x-auto"><table className="w-full text-left text-sm">{children}</table></div>,
                    th: ({ children }) => <th className="border-b border-white/15 px-2 py-1 font-semibold">{children}</th>,
                    td: ({ children }) => <td className="border-b border-white/[0.06] px-2 py-1 align-top">{children}</td>,
                }}
            >
                {text}
            </ReactMarkdown>
        </div>
    );
}

export default SummaryMarkdown;
