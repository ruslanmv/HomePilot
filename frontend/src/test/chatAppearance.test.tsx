/**
 * Chat Appearance: when the project's picture sits beside assistant
 * messages, and how tightly messages are spaced. Changes apply at once,
 * everywhere, and only to the avatars beside messages.
 */
import React from 'react'
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  CHAT_APPEARANCE_EVENT,
  CHAT_APPEARANCE_STORAGE_KEY,
  DEFAULT_CHAT_APPEARANCE,
  assistantAvatarSlot,
  messageGapClass,
  readChatAppearance,
  writeChatAppearance,
} from '../ui/chatAppearance'
import { ChatAppearanceSettings } from '../ui/components/ChatAppearanceSettings'
import { ChatSettingsPopover, DEFAULT_CHAT_SETTINGS } from '../ui/components/ChatSettingsPopover'

afterEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
})

describe('preference', () => {
  it('defaults to thumbnails at the start of message groups, normal spacing', () => {
    expect(DEFAULT_CHAT_APPEARANCE).toEqual({ thumbnails: 'grouped', compact: false, faceZoom: false })
    expect(readChatAppearance()).toEqual(DEFAULT_CHAT_APPEARANCE)
  })

  it('ignores unknown stored values', () => {
    localStorage.setItem(CHAT_APPEARANCE_STORAGE_KEY, JSON.stringify({ thumbnails: 'sometimes', compact: 'yes' }))
    expect(readChatAppearance()).toEqual(DEFAULT_CHAT_APPEARANCE)
    localStorage.setItem(CHAT_APPEARANCE_STORAGE_KEY, '{not json')
    expect(readChatAppearance()).toEqual(DEFAULT_CHAT_APPEARANCE)
  })

  it('is saved, merged, and announced so open chats update at once', () => {
    const seen = vi.fn()
    window.addEventListener(CHAT_APPEARANCE_EVENT, seen)
    writeChatAppearance({ thumbnails: 'hidden' })
    writeChatAppearance({ compact: true })
    window.removeEventListener(CHAT_APPEARANCE_EVENT, seen)
    expect(readChatAppearance()).toEqual({ thumbnails: 'hidden', compact: true, faceZoom: false })
    expect(seen).toHaveBeenCalledTimes(2)
  })
})

describe('the rule beside each reply', () => {
  const user = { role: 'user' }
  const reply = { role: 'assistant' }
  const call = { role: 'assistant', callMemory: { durationSec: 3 } }

  it('always: a picture on every reply', () => {
    expect(assistantAvatarSlot('always', user)).toBe('avatar')
    expect(assistantAvatarSlot('always', reply)).toBe('avatar')
  })

  it('grouped: a picture on the first reply of a run, an aligned gap after it', () => {
    expect(assistantAvatarSlot('grouped', undefined)).toBe('avatar')
    expect(assistantAvatarSlot('grouped', user)).toBe('avatar')
    expect(assistantAvatarSlot('grouped', reply)).toBe('spacer')
    expect(assistantAvatarSlot('grouped', call)).toBe('avatar') // a call row breaks the run
    expect(assistantAvatarSlot('grouped', { role: 'system' })).toBe('avatar')
  })

  it('hidden: nothing, so the text starts at the edge', () => {
    expect(assistantAvatarSlot('hidden', user)).toBe('none')
    expect(assistantAvatarSlot('hidden', reply)).toBe('none')
  })

  it('compact spacing halves the gap between messages', () => {
    expect(messageGapClass(false)).toBe('space-y-8')
    expect(messageGapClass(true)).toBe('space-y-4')
  })
})

describe('Settings → Chat → Appearance', () => {
  const replies = () => screen.getAllByRole('article', { name: 'Angel' })

  it('offers the three choices, with message groups recommended and selected', () => {
    render(<ChatAppearanceSettings previewName="Angel" />)
    const group = screen.getByRole('radiogroup', { name: 'Persona thumbnails' })
    const options = within(group).getAllByRole('radio')
    expect(options.map((o) => o.textContent)).toEqual([
      expect.stringContaining('Always show'),
      expect.stringContaining('Only at the beginning of message groups'),
      expect.stringContaining('Hide thumbnails in chat'),
    ])
    expect(options[1]).toHaveAttribute('aria-checked', 'true')
    expect(options[1]).toHaveTextContent('Recommended')
  })

  it('the live preview follows the choice; the header keeps the picture', () => {
    render(<ChatAppearanceSettings previewName="Angel" previewAvatarUrls={['http://hp/face']} />)
    const title = screen.getByTestId('chat-appearance-preview-title')

    expect(title).toHaveTextContent('Grouped thumbnails')
    expect(replies().map((r) => r.getAttribute('data-slot'))).toEqual(['avatar', 'spacer'])

    fireEvent.click(screen.getByRole('radio', { name: /Always show/ }))
    expect(replies().map((r) => r.getAttribute('data-slot'))).toEqual(['avatar', 'avatar'])

    fireEvent.click(screen.getByRole('radio', { name: /Hide thumbnails in chat/ }))
    expect(title).toHaveTextContent('Thumbnails hidden')
    expect(replies().map((r) => r.getAttribute('data-slot'))).toEqual(['none', 'none'])
    for (const r of replies()) expect(r.querySelector('img')).toBeNull()
    // The preview's header (like the real chat header) still shows the picture.
    expect(screen.getByRole('figure', { name: 'Live preview' }).querySelectorAll('img')).toHaveLength(1)
    expect(readChatAppearance().thumbnails).toBe('hidden')
  })

  it('compact spacing is a switch, and tightens the preview at once', () => {
    render(<ChatAppearanceSettings previewName="Angel" />)
    const sw = screen.getByRole('switch', { name: 'Compact message spacing' })
    expect(sw).toHaveAttribute('aria-checked', 'false')
    expect(screen.getByTestId('chat-appearance-preview-list')).toHaveClass('space-y-8')
    fireEvent.click(sw)
    expect(sw).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByTestId('chat-appearance-preview-list')).toHaveClass('space-y-4')
    expect(readChatAppearance().compact).toBe(true)
  })

  it('every message keeps an accessible name, picture or not', () => {
    writeChatAppearance({ thumbnails: 'hidden' })
    render(<ChatAppearanceSettings previewName="Angel" />)
    expect(screen.getByRole('article', { name: 'You' })).toBeInTheDocument()
    expect(replies()).toHaveLength(2)
  })

  it('a change made elsewhere (the chat popover, another tab) shows here at once', () => {
    render(<ChatAppearanceSettings previewName="Angel" />)
    act(() => {
      writeChatAppearance({ thumbnails: 'always' })
    })
    expect(screen.getByRole('radio', { name: /Always show/ })).toHaveAttribute('aria-checked', 'true')
  })
})

describe('Zoom pictures to the face', () => {
  it('is off by default, so the original picture is shown', () => {
    expect(readChatAppearance().faceZoom).toBe(false)
    // A preference saved before the switch existed keeps the original picture too.
    localStorage.setItem(CHAT_APPEARANCE_STORAGE_KEY, JSON.stringify({ thumbnails: 'always', compact: true }))
    expect(readChatAppearance()).toEqual({ thumbnails: 'always', compact: true, faceZoom: false })
  })

  it('is a switch in Settings → Chat → Appearance, saved and announced at once', () => {
    const heard = vi.fn()
    window.addEventListener(CHAT_APPEARANCE_EVENT, heard)
    render(<ChatAppearanceSettings />)
    const sw = screen.getByRole('switch', { name: 'Zoom pictures to the face' })
    expect(sw).toHaveAttribute('aria-checked', 'false')
    expect(sw).toHaveAccessibleDescription(/original picture/)
    fireEvent.click(sw)
    expect(sw).toHaveAttribute('aria-checked', 'true')
    expect(readChatAppearance().faceZoom).toBe(true)
    expect(heard).toHaveBeenCalled()
    fireEvent.click(sw)
    expect(readChatAppearance().faceZoom).toBe(false)
    window.removeEventListener(CHAT_APPEARANCE_EVENT, heard)
  })
})

describe("the chat's own settings popover", () => {
  it('holds the same choices, applied to every chat', () => {
    render(<ChatSettingsPopover open onClose={() => {}} settings={DEFAULT_CHAT_SETTINGS} onChange={() => {}} />)
    const group = screen.getByRole('radiogroup', { name: 'Persona thumbnails' })
    expect(within(group).getByRole('radio', { name: 'Only at the beginning of message groups' })).toHaveAttribute('aria-checked', 'true')
    fireEvent.click(within(group).getByRole('radio', { name: 'Hide thumbnails in chat' }))
    expect(readChatAppearance().thumbnails).toBe('hidden')
    fireEvent.click(screen.getByRole('switch', { name: 'Compact spacing' }))
    expect(readChatAppearance().compact).toBe(true)
  })
})
