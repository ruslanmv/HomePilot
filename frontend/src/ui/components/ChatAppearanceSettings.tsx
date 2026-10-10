/**
 * Settings → Chat → Appearance: when the project's picture sits beside
 * assistant messages, and how tightly messages are spaced — with a live
 * preview that uses the same rule as the chat itself.
 *
 * Applies immediately and is remembered on this device for every project; it
 * does not touch the Save/Reset draft of the settings around it.
 * `ChatAppearanceQuick` is the same two choices, compact, for the chat's own
 * settings popover.
 */
import React from 'react'
import {
  THUMBNAIL_OPTIONS,
  assistantAvatarSlot,
  messageGapClass,
  useChatAppearance,
  writeChatAppearance,
  type PersonaThumbnails,
} from '../chatAppearance'
import { AvatarImage } from './ProjectAvatar'

const PREVIEW_MESSAGES: Array<{ role: 'user' | 'assistant'; text: string }> = [
  { role: 'user', text: 'Hi, how are you?' },
  { role: 'assistant', text: "I'm doing wonderful! How can I help you today?" },
  { role: 'assistant', text: "It's lovely to chat with you!" },
]

const PREVIEW_TITLE: Record<PersonaThumbnails, string> = {
  always: 'Thumbnail on every reply',
  grouped: 'Grouped thumbnails',
  hidden: 'Thumbnails hidden',
}

function Switch({ checked, onChange, labelledBy, describedBy }: { checked: boolean; onChange: (v: boolean) => void; labelledBy: string; describedBy?: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-labelledby={labelledBy}
      aria-describedby={describedBy}
      onClick={() => onChange(!checked)}
      className={[
        'relative h-6 w-10 shrink-0 rounded-full border transition-colors',
        checked ? 'border-violet-400/60 bg-violet-500/70' : 'border-white/15 bg-white/[0.06]',
      ].join(' ')}
    >
      <span
        className={[
          'absolute top-1/2 h-4 w-4 -translate-y-1/2 rounded-full bg-white transition-all',
          checked ? 'left-[20px]' : 'left-[3px] opacity-60',
        ].join(' ')}
      />
    </button>
  )
}

function PreviewAvatar({ urls, name, size }: { urls: Array<string | null | undefined>; name: string; size: number }) {
  const initial = (name.trim()[0] || 'P').toUpperCase()
  return (
    <AvatarImage
      urls={urls}
      className="shrink-0 rounded-full object-cover ring-1 ring-white/20"
      fallback={
        <span
          aria-hidden
          className="grid shrink-0 place-items-center rounded-full bg-gradient-to-br from-pink-500 to-violet-600 font-semibold text-white ring-1 ring-white/20"
          style={{ width: size, height: size, fontSize: size * 0.42 }}
        >
          {initial}
        </span>
      }
      style={{ width: size, height: size }}
    />
  )
}

/** The chat rule, drawn small: what the conversation will look like. */
export function ChatAppearancePreview({ name, avatarUrls }: { name: string; avatarUrls: Array<string | null | undefined> }) {
  const { thumbnails, compact } = useChatAppearance()
  return (
    <figure className="rounded-2xl border border-white/10 bg-black/40" aria-label="Live preview">
      <figcaption className="flex items-center justify-between gap-3 border-b border-white/[0.06] px-4 py-2.5 text-xs">
        <span className="font-semibold uppercase tracking-wider text-white/45">Live preview</span>
        <span className="text-white/70" data-testid="chat-appearance-preview-title">{PREVIEW_TITLE[thumbnails]}</span>
      </figcaption>
      <div className="px-4 pb-4 pt-3">
        {/* The header keeps the picture whatever the setting. */}
        <div className="mb-4 flex items-center gap-2">
          <PreviewAvatar urls={avatarUrls} name={name} size={24} />
          <span className="truncate text-sm font-medium text-white/90">{name}</span>
          <span className="rounded-full border border-pink-400/30 bg-pink-500/15 px-2 py-0.5 text-[10px] font-medium text-pink-200">Persona</span>
        </div>
        <div className={messageGapClass(compact)} data-testid="chat-appearance-preview-list">
          {PREVIEW_MESSAGES.map((m, i) => {
            if (m.role === 'user') {
              return (
                <div key={i} role="article" aria-label="You" className="flex justify-end">
                  <div className="max-w-[85%] rounded-2xl border border-white/10 bg-white/10 px-3 py-2 text-sm text-white/90">{m.text}</div>
                </div>
              )
            }
            const slot = assistantAvatarSlot(thumbnails, PREVIEW_MESSAGES[i - 1])
            return (
              <div key={i} role="article" aria-label={name} className="flex items-start gap-3" data-slot={slot}>
                {slot === 'avatar' ? <PreviewAvatar urls={avatarUrls} name={name} size={28} /> : null}
                {slot === 'spacer' ? <span aria-hidden className="w-7 shrink-0" /> : null}
                <p className="min-w-0 pt-1 text-sm leading-relaxed text-white/85">{m.text}</p>
              </div>
            )
          })}
        </div>
      </div>
    </figure>
  )
}

export function ChatAppearanceSettings({
  previewName = 'Persona',
  previewAvatarUrls = [],
}: {
  /** The open persona's name and picture make the preview look like your chat. */
  previewName?: string
  previewAvatarUrls?: Array<string | null | undefined>
}) {
  const { thumbnails, compact } = useChatAppearance()
  return (
    <div className="space-y-6">
      <section aria-labelledby="hp-ca-thumbs" className="space-y-3">
        <div>
          <h3 id="hp-ca-thumbs" className="text-sm font-semibold text-white">Persona thumbnails</h3>
          <p className="mt-0.5 text-xs text-white/55">Choose when to display the project's avatar next to assistant messages.</p>
        </div>
        <div role="radiogroup" aria-labelledby="hp-ca-thumbs" className="grid gap-2">
          {THUMBNAIL_OPTIONS.map((o) => {
            const on = o.id === thumbnails
            return (
              <button
                key={o.id}
                type="button"
                role="radio"
                aria-checked={on}
                onClick={() => writeChatAppearance({ thumbnails: o.id })}
                className={[
                  'flex min-h-[44px] items-start gap-3 rounded-xl border px-3 py-2.5 text-left',
                  on ? 'border-violet-400/50 bg-violet-500/[0.10] text-white' : 'border-white/10 bg-white/[0.02] text-white/75 hover:bg-white/[0.05]',
                ].join(' ')}
              >
                <span
                  aria-hidden
                  className={[
                    'mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded-full border',
                    on ? 'border-violet-300' : 'border-white/30',
                  ].join(' ')}
                >
                  {on ? <span className="h-2 w-2 rounded-full bg-violet-300" /> : null}
                </span>
                <span className="min-w-0">
                  <span className="flex flex-wrap items-center gap-2 text-sm font-medium">
                    {o.label}
                    {o.id === 'grouped' ? (
                      <span className="rounded-full border border-emerald-400/30 bg-emerald-500/15 px-2 py-0.5 text-[10px] font-semibold text-emerald-200">Recommended</span>
                    ) : null}
                  </span>
                  <span className="mt-0.5 block text-xs leading-snug text-white/50">{o.hint}</span>
                </span>
              </button>
            )
          })}
        </div>
      </section>

      <section className="flex items-start justify-between gap-4 rounded-xl border border-white/10 bg-white/[0.02] px-3 py-3">
        <div className="min-w-0">
          <h3 id="hp-ca-compact" className="text-sm font-semibold text-white">Compact message spacing</h3>
          <p id="hp-ca-compact-desc" className="mt-0.5 text-xs text-white/55">Reduces vertical spacing between messages for easier reading.</p>
        </div>
        <Switch checked={compact} onChange={(v) => writeChatAppearance({ compact: v })} labelledBy="hp-ca-compact" describedBy="hp-ca-compact-desc" />
      </section>

      <ChatAppearancePreview name={previewName} avatarUrls={previewAvatarUrls} />

      <p className="text-xs text-white/45">
        Applies to every project, right away. Only the picture beside messages changes — the chat header,
        project card, Conversation Hub and Voice keep it. Pictures are never modified.
      </p>
    </div>
  )
}

/** The same choices, compact, for the chat's settings popover. */
export function ChatAppearanceQuick() {
  const { thumbnails, compact } = useChatAppearance()
  return (
    <div className="space-y-3">
      <div>
        <div id="hp-caq-thumbs" className="text-sm text-white/90">Persona thumbnails</div>
        <div className="text-[11px] text-white/45">Beside assistant messages · all chats</div>
      </div>
      <div role="radiogroup" aria-labelledby="hp-caq-thumbs" className="grid grid-cols-3 gap-2">
        {THUMBNAIL_OPTIONS.map((o) => {
          const on = o.id === thumbnails
          return (
            <button
              key={o.id}
              type="button"
              role="radio"
              aria-checked={on}
              aria-label={o.label}
              title={o.label}
              onClick={() => writeChatAppearance({ thumbnails: o.id })}
              className={[
                'rounded-xl border px-2 py-2 text-xs font-semibold transition-all',
                on ? 'border-white/25 bg-white/15 text-white' : 'border-white/10 bg-white/5 text-white/70 hover:border-white/15 hover:bg-white/10',
              ].join(' ')}
            >
              {o.short}
            </button>
          )
        })}
      </div>
      <div className="flex items-center justify-between gap-3">
        <div>
          <div id="hp-caq-compact" className="text-sm text-white/90">Compact spacing</div>
          <div className="text-[11px] text-white/45">Tighter gaps between messages</div>
        </div>
        <Switch checked={compact} onChange={(v) => writeChatAppearance({ compact: v })} labelledBy="hp-caq-compact" />
      </div>
    </div>
  )
}

export default ChatAppearanceSettings
