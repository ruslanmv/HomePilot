/**
 * Chat appearance — how conversations are laid out, kept per device and
 * applied to every project.
 *
 *   thumbnails  always    the assistant's picture beside every reply
 *               grouped   only on the first reply of a run (the default)
 *               hidden    no picture beside replies; text starts at the edge
 *   compact     tighter vertical spacing between messages
 *   faceZoom    small round pictures (chat header, replies, Conversation Hub,
 *               Voice) use the backend's crop around the face. Off by default:
 *               the original picture is shown, as it was saved.
 *
 * Only the avatar beside chat messages follows `thumbnails`: the project's
 * picture in the chat header, on its card, in the Conversation Hub and in
 * Voice is unchanged, and no picture is modified or deleted.
 *
 * Stored in localStorage like the Motion preference, and announced with an
 * `hp:chat-appearance-change` event so an open chat updates at once.
 */
import { useEffect, useState } from 'react'

export type PersonaThumbnails = 'always' | 'grouped' | 'hidden'
export type ChatAppearance = { thumbnails: PersonaThumbnails; compact: boolean; faceZoom: boolean }

export const CHAT_APPEARANCE_STORAGE_KEY = 'homepilot_chat_appearance'
export const CHAT_APPEARANCE_EVENT = 'hp:chat-appearance-change'
export const DEFAULT_CHAT_APPEARANCE: ChatAppearance = { thumbnails: 'grouped', compact: false, faceZoom: false }

const THUMBNAILS: readonly PersonaThumbnails[] = ['always', 'grouped', 'hidden']

export const THUMBNAIL_OPTIONS: ReadonlyArray<{ id: PersonaThumbnails; label: string; short: string; hint: string }> = [
  { id: 'always', label: 'Always show', short: 'Always', hint: 'The picture beside every reply.' },
  { id: 'grouped', label: 'Only at the beginning of message groups', short: 'Groups', hint: 'Once per run of replies — identity without the clutter.' },
  { id: 'hidden', label: 'Hide thumbnails in chat', short: 'Hidden', hint: 'Replies start at the edge; the header still shows the picture.' },
]

export function readChatAppearance(): ChatAppearance {
  try {
    const raw = localStorage.getItem(CHAT_APPEARANCE_STORAGE_KEY)
    if (!raw) return { ...DEFAULT_CHAT_APPEARANCE }
    const parsed = JSON.parse(raw) ?? {}
    return {
      thumbnails: THUMBNAILS.includes(parsed.thumbnails) ? parsed.thumbnails : DEFAULT_CHAT_APPEARANCE.thumbnails,
      compact: typeof parsed.compact === 'boolean' ? parsed.compact : DEFAULT_CHAT_APPEARANCE.compact,
      faceZoom: typeof parsed.faceZoom === 'boolean' ? parsed.faceZoom : DEFAULT_CHAT_APPEARANCE.faceZoom,
    }
  } catch {
    return { ...DEFAULT_CHAT_APPEARANCE }
  }
}

export function writeChatAppearance(next: Partial<ChatAppearance>): ChatAppearance {
  const merged: ChatAppearance = { ...readChatAppearance(), ...next }
  try {
    localStorage.setItem(CHAT_APPEARANCE_STORAGE_KEY, JSON.stringify(merged))
  } catch {
    /* private mode / storage full — the choice still applies to this page */
  }
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent(CHAT_APPEARANCE_EVENT, { detail: merged }))
  return merged
}

/** The current preference, kept up to date when it changes here or in another tab. */
export function useChatAppearance(): ChatAppearance {
  const [prefs, setPrefs] = useState<ChatAppearance>(readChatAppearance)
  useEffect(() => {
    const sync = () => setPrefs(readChatAppearance())
    const onStorage = (e: StorageEvent) => {
      if (e.key === CHAT_APPEARANCE_STORAGE_KEY) sync()
    }
    window.addEventListener(CHAT_APPEARANCE_EVENT, sync)
    window.addEventListener('storage', onStorage)
    return () => {
      window.removeEventListener(CHAT_APPEARANCE_EVENT, sync)
      window.removeEventListener('storage', onStorage)
    }
  }, [])
  return prefs
}

/**
 * What sits beside an assistant reply:
 *   'avatar'  the picture
 *   'spacer'  an empty slot the picture's width — a later reply in the same
 *             run, so its text lines up under the first one's
 *   'none'    nothing; the text starts at the edge
 * `previous` is the message shown just above (undefined at the top).
 */
export type AvatarSlot = 'avatar' | 'spacer' | 'none'

export function assistantAvatarSlot(
  thumbnails: PersonaThumbnails,
  previous?: { role: string; callMemory?: unknown } | null,
): AvatarSlot {
  if (thumbnails === 'hidden') return 'none'
  if (thumbnails === 'always') return 'avatar'
  const continuesRun = !!previous && previous.role === 'assistant' && !previous.callMemory
  return continuesRun ? 'spacer' : 'avatar'
}

/** Gap between messages, as a Tailwind class for the message list. */
export function messageGapClass(compact: boolean): string {
  return compact ? 'space-y-4' : 'space-y-8'
}
