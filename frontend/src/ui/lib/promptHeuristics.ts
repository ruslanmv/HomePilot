/**
 * Whether a message is too small for a long-running mode. Deep research on "hello" is
 * minutes of planning and searching for nothing, so the composer asks once before running
 * it — and never switches a chosen mode silently.
 */
const GREETING =
  /^(hi|hello|hey|yo|hola|ciao|salve|bonjour|hallo|thanks|thank you|thx|ok|okay|test|ping|good (morning|afternoon|evening)|how are you)\b[\s!.?,]*$/i

export function isTrivialPrompt(text: string): boolean {
  const t = (text || '').trim()
  if (!t) return true
  if (GREETING.test(t)) return true
  const words = t.split(/\s+/).filter(Boolean)
  return words.length <= 3 && !t.includes('?') && t.length <= 24
}
