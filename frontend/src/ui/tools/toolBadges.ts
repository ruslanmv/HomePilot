/**
 * Heuristic badge computation for catalog tools.
 *
 * Derives visual badges (MCP, REST, A2A, Built-in, etc.) from
 * tool metadata.  Also derives the source MCP server name from the
 * tool's URL (which encodes the port) so the Tools tab can show
 * which server each tool belongs to.
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

/** Map MCP server ports to human-readable server labels. */
const PORT_TO_SERVER: Record<number, string> = {
  9101: 'Personal Assistant',
  9102: 'Knowledge',
  9103: 'Decision Copilot',
  9104: 'Executive Briefing',
  9105: 'Web Search',
  9110: 'Local Notes',
  9111: 'Local Projects',
  9112: 'Web Fetch',
  9113: 'Shell Safe',
  9114: 'Gmail',
  9115: 'Google Calendar',
  9116: 'Microsoft Graph',
  9117: 'Slack',
  9118: 'GitHub',
  9119: 'Notion',
  9120: 'Inventory',
}

/**
 * Derive the source MCP server label from a tool's URL.
 * Returns null if the URL doesn't match a known HomePilot port.
 */
export function deriveSourceServer(url?: string | null): string | null {
  if (!url) return null
  const match = url.match(/:(\d{4,5})\//)
  if (!match) return null
  const port = parseInt(match[1], 10)
  return PORT_TO_SERVER[port] || null
}

export function computeBadges(
  name: string,
  description: string,
  integType?: string | null,
  url?: string | null,
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

  // Add source server badge if tool has a known HomePilot MCP URL
  const source = deriveSourceServer(url)
  if (source) {
    badges.push({ label: source, color: 'text-white/50', bg: 'bg-white/5' })
  }

  return badges
}
