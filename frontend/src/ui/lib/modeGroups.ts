/**
 * When switching mode should throw the conversation away.
 *
 * Chat, voice, project, search and imagine are one continuous conversation — moving between
 * them keeps the thread. Edit and animate are separate sessions working on an image or a
 * video, and letting the chat transcript bleed into them confuses the model about what it
 * is being asked to operate on. So a move *between* those groups starts fresh.
 *
 * ── Why this is a function and not four lines inside the effect ─────────────────────────
 *
 * Because it is a rule with a sharp edge, and the edge cost a bug. Everything that is not a
 * conversation surface — Routines, Teams, Models, the meeting library — is `other`, and
 * `other` is deliberately excluded from resetting: you can step out to a settings-ish
 * screen and come back without losing your place.
 *
 * But coming *back in* from `other` is a group change like any other, so it resets. That is
 * right when somebody clicks Chat in the nav, and wrong when the app is navigating them
 * into a specific conversation it just loaded — which is what opening a routine's result
 * does. The caller has to switch mode **before** fetching, so this reset lands while there
 * is nothing to lose. `loadConversation` does exactly that, and says so.
 */

export type ModeGroup = 'chat' | 'edit' | 'animate' | 'other'

const CHAT_LIKE = ['chat', 'voice', 'project', 'search', 'imagine']

export function modeGroup(mode: string): ModeGroup {
  if (CHAT_LIKE.includes(mode)) return 'chat'
  if (mode === 'edit') return 'edit'
  if (mode === 'animate') return 'animate'
  return 'other'
}

/**
 * Whether moving `prev` → `next` should start a new, empty conversation.
 *
 * Never when landing on `other`: those surfaces do not host a conversation, so clearing one
 * on the way to Routines would lose the thread for no reason and leave nothing in its place.
 */
export function resetsConversation(prev: string, next: string): boolean {
  const from = modeGroup(prev)
  const to = modeGroup(next)
  return from !== to && to !== 'other'
}
