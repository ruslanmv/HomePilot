export type AgenticIntent = 'generate_images' | 'generate_videos'

/**
 * Conservative, reliable intent detector.
 * - Supports slash commands: /image, /video
 * - Supports common language: "generate a picture", "make a video", etc.
 * - Returns a cleaned prompt for tools (strips /image or /video prefix)
 */
export function detectAgenticIntent(raw: string): { intent: AgenticIntent | null; prompt: string } {
  const text = (raw || '').trim()
  if (!text) return { intent: null, prompt: '' }

  const lower = text.toLowerCase()

  // Slash commands (highest confidence)
  if (lower.startsWith('/image') || lower.startsWith('/img') || lower.startsWith('/pic')) {
    const prompt = text.replace(/^\/(image|img|pic)\s*/i, '').trim()
    return { intent: 'generate_images', prompt: prompt || '' }
  }
  if (lower.startsWith('/video') || lower.startsWith('/animate')) {
    const prompt = text.replace(/^\/(video|animate)\s*/i, '').trim()
    return { intent: 'generate_videos', prompt: prompt || '' }
  }

  // Natural language — images
  const wantsImageVerb =
    lower.includes('generate') || lower.includes('create') || lower.includes('make') || lower.includes('draw')
  const wantsImageNoun =
    lower.includes('image') || lower.includes('picture') || lower.includes('photo') || lower.includes('portrait') || lower.includes('art')
  const wantsImagePhrase =
    lower.includes('a picture of') || lower.includes('an image of') || lower.includes('generate me') || lower.includes('create an image')

  if ((wantsImageVerb && wantsImageNoun) || wantsImagePhrase) {
    return { intent: 'generate_images', prompt: text }
  }

  // Natural language — videos
  const wantsVideoVerb = lower.includes('generate') || lower.includes('create') || lower.includes('make')
  const wantsVideoNoun = lower.includes('video') || lower.includes('animation') || lower.includes('clip') || lower.includes('animate')
  const wantsVideoPhrase = lower.includes('a video of') || lower.includes('generate a video') || lower.includes('make an animation')

  if ((wantsVideoVerb && wantsVideoNoun) || wantsVideoPhrase) {
    return { intent: 'generate_videos', prompt: text }
  }

  return { intent: null, prompt: text }
}
