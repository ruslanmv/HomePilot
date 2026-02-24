/**
 * Heuristic badge computation for catalog tools.
 *
 * Derives visual badges (MCP, REST, A2A, Built-in, etc.) from
 * tool metadata.  In the future these can be surfaced from the
 * `raw` field returned by Context Forge.
 */

export type ToolBadge = {
  label: string
  color: string          // Tailwind text color class
  bg: string             // Tailwind bg color class
}

const MCP_PATTERNS = /\b(mcp|gateway|sse|stdio|streamable)/i
const REST_PATTERNS = /\b(rest|http|api|webhook)/i
const A2A_PATTERNS  = /\b(a2a|agent-to-agent|agent2agent)/i
const BUILTIN_NAMES = new Set([
  'generate_images', 'generate_videos', 'imagine',
  'video_gen', 'img_gen', 'flux',
])

export function computeBadges(
  name: string,
  description: string,
  integType?: string | null,
): ToolBadge[] {
  const badges: ToolBadge[] = []
  const combined = `${name} ${description} ${integType || ''}`

  if (integType?.toUpperCase() === 'MCP' || MCP_PATTERNS.test(combined)) {
    badges.push({ label: 'MCP', color: 'text-cyan-300', bg: 'bg-cyan-500/20' })
  }
  if (integType?.toUpperCase() === 'REST' || REST_PATTERNS.test(combined)) {
    badges.push({ label: 'REST', color: 'text-amber-300', bg: 'bg-amber-500/20' })
  }
  if (integType?.toUpperCase() === 'A2A' || A2A_PATTERNS.test(combined)) {
    badges.push({ label: 'A2A', color: 'text-violet-300', bg: 'bg-violet-500/20' })
  }
  if (BUILTIN_NAMES.has(name.toLowerCase())) {
    badges.push({ label: 'Built-in', color: 'text-emerald-300', bg: 'bg-emerald-500/20' })
  }

  if (badges.length === 0) {
    badges.push({ label: 'Tool', color: 'text-blue-300', bg: 'bg-blue-500/20' })
  }

  return badges
}
