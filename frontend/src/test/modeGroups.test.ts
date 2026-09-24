/**
 * When switching mode throws the conversation away.
 *
 * This rule is why "Open" on a routine landed on an empty chat. Routines is an `other`
 * surface, chat is a `chat` surface, so arriving in chat from Routines resets the
 * conversation — correct when somebody clicks Chat in the nav, and fatal when the app is
 * navigating them *into* a conversation it has just loaded.
 *
 * `loadConversation` therefore switches mode before it fetches, so this reset lands while
 * there is nothing to lose and the loaded messages arrive last. These tests pin the rule
 * that ordering depends on; the ordering itself is documented at the call site.
 */
import { describe, expect, it } from 'vitest'

import { modeGroup, resetsConversation } from '../ui/lib/modeGroups'

describe('mode groups', () => {
  it('treats every conversation surface as one group', () => {
    for (const mode of ['chat', 'voice', 'project', 'search', 'imagine']) {
      expect(modeGroup(mode), mode).toBe('chat')
    }
  })

  it('keeps edit and animate apart from chat and from each other', () => {
    // A transcript bleeding into an edit session confuses the model about what it is being
    // asked to operate on — the whole reason this rule exists.
    expect(modeGroup('edit')).toBe('edit')
    expect(modeGroup('animate')).toBe('animate')
  })

  it('calls everything that hosts no conversation "other"', () => {
    for (const mode of ['routines', 'teams', 'models', 'meetings', 'interactive']) {
      expect(modeGroup(mode), mode).toBe('other')
    }
  })
})

describe('whether a mode change resets the conversation', () => {
  it('keeps the thread while moving around the conversation surfaces', () => {
    expect(resetsConversation('chat', 'voice')).toBe(false)
    expect(resetsConversation('project', 'chat')).toBe(false)
    expect(resetsConversation('chat', 'chat')).toBe(false)
  })

  it('starts fresh when entering or leaving an edit or animate session', () => {
    expect(resetsConversation('chat', 'edit')).toBe(true)
    expect(resetsConversation('edit', 'chat')).toBe(true)
    expect(resetsConversation('edit', 'animate')).toBe(true)
  })

  it('never resets on the way out to a surface that hosts no conversation', () => {
    // Stepping out to Routines or Teams and coming back should not cost you your place.
    expect(resetsConversation('chat', 'routines')).toBe(false)
    expect(resetsConversation('edit', 'teams')).toBe(false)
  })

  it('does reset on the way back in — which is the trap', () => {
    /*
     * This is the true-and-dangerous case. Returning to chat from Routines is a group
     * change, so the conversation is reset — right for a nav click, wrong for the app
     * opening a routine's result.
     *
     * The resolution is ordering, not an exception: `loadConversation` switches mode first
     * and fetches second, so the reset happens before the messages exist. A future change
     * that moves `setMode` back below the fetch reintroduces the empty chat, and this test
     * is the note explaining why it must not.
     */
    expect(resetsConversation('routines', 'chat')).toBe(true)
    expect(resetsConversation('teams', 'chat')).toBe(true)
  })
})
