/**
 * PersonaProfilePanel — Teams-style participant profile card.
 *
 * Opens as a slide-over panel when clicking on a participant's avatar
 * in the meeting table or left rail. Shows real persona project data
 * in a clean, professional layout with MMORPG-inspired stats.
 *
 * Syncs with actual project values: class, role, tone, skills, tools,
 * portraits, creation date, execution stance, and capabilities.
 */

import React, { useMemo } from 'react'
import {
  X,
  Shield,
  Sparkles,
  Wrench,
  Palette,
  Calendar,
  Zap,
  Brain,
  Swords,
  Image,
  Shirt,
  Target,
  Volume2,
  Crown,
  ChevronRight,
  Users,
  Bot,
  RotateCcw,
} from 'lucide-react'
import type { PersonaSummary, PersonaAppearanceOutfit } from './types'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface PersonaProfilePanelProps {
  persona: PersonaSummary
  backendUrl: string
  onClose: () => void
  /** Optional: current meeting status for this persona */
  status?: 'speaking' | 'wants-to-speak' | 'listening' | 'muted'
  /** Optional: callback when user clicks Inspect Outfit */
  onInspectOutfit?: (outfitId: string, initialAngle?: 'front' | 'left' | 'right' | 'back') => void
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function resolveAvatarUrl(p: PersonaSummary, backendUrl: string): string | null {
  const file = p.persona_appearance?.selected_thumb_filename || p.persona_appearance?.selected_filename
  if (!file) return null
  if (file.startsWith('http')) return file
  return `${backendUrl}/files/${file}`
}

/** Map persona_class to a display label + color */
const CLASS_STYLES: Record<string, { label: string; color: string; bg: string }> = {
  secretary: { label: 'Secretary', color: 'text-blue-300', bg: 'bg-blue-500/15 border-blue-500/25' },
  assistant: { label: 'Assistant', color: 'text-cyan-300', bg: 'bg-cyan-500/15 border-cyan-500/25' },
  companion: { label: 'Companion', color: 'text-emerald-300', bg: 'bg-emerald-500/15 border-emerald-500/25' },
  girlfriend: { label: 'Partner', color: 'text-pink-300', bg: 'bg-pink-500/15 border-pink-500/25' },
  partner: { label: 'Partner', color: 'text-rose-300', bg: 'bg-rose-500/15 border-rose-500/25' },
  custom: { label: 'Custom', color: 'text-violet-300', bg: 'bg-violet-500/15 border-violet-500/25' },
}

const STANCE_STYLES: Record<string, { icon: React.ReactNode; label: string; desc: string }> = {
  fast: { icon: <Zap size={12} />, label: 'Swift', desc: 'Low latency, fewer tool calls' },
  balanced: { icon: <Shield size={12} />, label: 'Balanced', desc: 'Good mix of speed and depth' },
  quality: { icon: <Target size={12} />, label: 'Thorough', desc: 'Multi-step reasoning' },
}

const CAPABILITY_ICONS: Record<string, React.ReactNode> = {
  generate_images: <Image size={12} />,
  generate_videos: <Sparkles size={12} />,
  analyze_documents: <Brain size={12} />,
  automate_external: <Wrench size={12} />,
}

const CAPABILITY_LABELS: Record<string, string> = {
  generate_images: 'Generate images',
  generate_videos: 'Generate short videos',
  analyze_documents: 'Analyze documents',
  automate_external: 'Automate external services',
}

/** Get the equipped or first outfit from persona appearance */
function getEquippedOutfit(persona: PersonaSummary): PersonaAppearanceOutfit | null {
  const outfits = persona.persona_appearance?.outfits || []
  return outfits.find((o) => o.equipped) || outfits[0] || null
}

/** Get available view angles from an outfit's view_pack */
function getOutfitAvailableViews(outfit: PersonaAppearanceOutfit | null): Array<'front' | 'left' | 'right' | 'back'> {
  const vp = outfit?.view_pack || {}
  return (['front', 'left', 'right', 'back'] as const).filter((a) => !!vp[a])
}

/** Compute stat bars from real persona data */
function computeStats(p: PersonaSummary): Array<{ label: string; value: number; color: string }> {
  const agent = p.persona_agent
  const agentic = p.agentic
  const appearance = p.persona_appearance

  // Depth: based on system prompt length (longer = more depth)
  const promptLen = agent?.system_prompt?.length || 0
  const depth = Math.min(100, Math.round((promptLen / 3000) * 100))

  // Versatility: based on capabilities + tools
  const capCount = agentic?.capabilities?.length || 0
  const toolCount = agent?.allowed_tools?.length || 0
  const versatility = Math.min(100, Math.round(((capCount * 15) + (toolCount * 2))))

  // Personality: based on tone, techniques, unique behaviors
  const hasTone = agent?.response_style?.tone ? 20 : 0
  const techCount = agent?.key_techniques?.length || 0
  const behavCount = agent?.unique_behaviors?.length || 0
  const personality = Math.min(100, hasTone + (techCount * 12) + (behavCount * 15) + 20)

  // Visual: based on portraits and outfits
  const imageCount = (appearance?.sets || []).reduce((n, s) => n + (s.images?.length || 0), 0)
  const outfitCount = appearance?.outfits?.length || 0
  const visual = Math.min(100, (imageCount * 20) + (outfitCount * 15))

  return [
    { label: 'Depth', value: depth, color: 'bg-blue-400' },
    { label: 'Versatility', value: versatility, color: 'bg-emerald-400' },
    { label: 'Personality', value: personality, color: 'bg-violet-400' },
    { label: 'Visual', value: visual, color: 'bg-amber-400' },
  ]
}

/** Compute persona "level" from data richness */
function computeLevel(p: PersonaSummary): number {
  let xp = 1
  if (p.persona_agent?.system_prompt && p.persona_agent.system_prompt.length > 100) xp++
  if (p.persona_agent?.role) xp++
  if (p.persona_agent?.response_style?.tone) xp++
  if (p.persona_agent?.key_techniques?.length) xp++
  if (p.persona_appearance?.selected_filename) xp++
  if ((p.persona_appearance?.sets?.length || 0) > 0) xp++
  if ((p.persona_appearance?.outfits?.length || 0) > 0) xp++
  if ((p.agentic?.capabilities?.length || 0) > 0) xp++
  if ((p.persona_agent?.allowed_tools?.length || 0) > 2) xp++
  return Math.min(xp, 10)
}

function formatAge(createdAt?: number): string {
  if (!createdAt) return 'Unknown'
  const now = Date.now() / 1000
  const days = Math.floor((now - createdAt) / 86400)
  if (days < 1) return 'Today'
  if (days === 1) return '1 day'
  if (days < 30) return `${days} days`
  if (days < 365) return `${Math.floor(days / 30)} month${Math.floor(days / 30) > 1 ? 's' : ''}`
  return `${Math.floor(days / 365)} year${Math.floor(days / 365) > 1 ? 's' : ''}`
}

// ---------------------------------------------------------------------------
// Status badge styles
// ---------------------------------------------------------------------------

const STATUS_STYLES: Record<string, { dot: string; text: string; label: string }> = {
  speaking: { dot: 'bg-emerald-400', text: 'text-emerald-300', label: 'Speaking' },
  'wants-to-speak': { dot: 'bg-amber-400', text: 'text-amber-300', label: 'Wants to speak' },
  listening: { dot: 'bg-white/30', text: 'text-white/40', label: 'In meeting' },
  muted: { dot: 'bg-red-400', text: 'text-red-300', label: 'Muted' },
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function PersonaProfilePanel({ persona, backendUrl, onClose, status, onInspectOutfit }: PersonaProfilePanelProps) {
  const avatarUrl = resolveAvatarUrl(persona, backendUrl)
  const agent = persona.persona_agent
  const appearance = persona.persona_appearance
  const agentic = persona.agentic

  const personaClass = agent?.persona_class || 'custom'
  const classStyle = CLASS_STYLES[personaClass] || CLASS_STYLES.custom
  const level = useMemo(() => computeLevel(persona), [persona])
  const stats = useMemo(() => computeStats(persona), [persona])

  const portraitCount = useMemo(() => {
    return (appearance?.sets || []).reduce((n, s) => n + (s.images?.length || 0), 0)
  }, [appearance])

  const outfitCount = appearance?.outfits?.length || 0
  const equippedOutfit = useMemo(() => getEquippedOutfit(persona), [persona])
  const outfitViews = useMemo(() => getOutfitAvailableViews(equippedOutfit), [equippedOutfit])
  const skillCount = agentic?.capabilities?.length || 0
  const toolCount = agent?.allowed_tools?.length || 0
  const stance = STANCE_STYLES[agentic?.execution_profile || 'balanced'] || STANCE_STYLES.balanced
  const statusStyle = STATUS_STYLES[status || 'listening']

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/50 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-sm h-full bg-[#0a0a0a] border-l border-white/[0.08] overflow-y-auto animate-rail-slide-right"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Close button */}
        <div className="sticky top-0 z-10 flex justify-end p-3 bg-[#0a0a0a]/80 backdrop-blur-sm">
          <button
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-white/5 text-white/30 hover:text-white/60 transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* ═══════════ HERO ═══════════ */}
        <div className="px-6 pb-5 text-center">
          {/* Avatar */}
          <div className="relative inline-block">
            <div className={`w-36 h-36 rounded-full overflow-hidden border-[3px] mx-auto ${
              status === 'speaking'
                ? 'border-emerald-400/60 shadow-lg shadow-emerald-500/20'
                : status === 'wants-to-speak'
                  ? 'border-amber-400/40 shadow-md shadow-amber-500/15'
                  : 'border-white/15'
            }`}>
              {avatarUrl ? (
                <img src={avatarUrl} alt={persona.name} className="w-full h-full object-cover" />
              ) : (
                <div className="w-full h-full bg-white/5 flex items-center justify-center text-4xl text-white/25 font-bold">
                  {persona.name[0]?.toUpperCase()}
                </div>
              )}
            </div>

            {/* Level badge */}
            <div className="absolute -bottom-1 left-1/2 -translate-x-1/2 px-2.5 py-0.5 rounded-full bg-[#0a0a0a] border border-white/15 text-[10px] font-bold text-white/60">
              LV {level}
            </div>
          </div>

          {/* Name */}
          <h2 className="mt-4 text-lg font-bold text-white">{persona.name}</h2>

          {/* Class badge + Status */}
          <div className="flex items-center justify-center gap-2 mt-2">
            <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-semibold border ${classStyle.bg} ${classStyle.color}`}>
              <Crown size={11} />
              {classStyle.label}
            </span>
            {status && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium bg-white/[0.04] border border-white/[0.08]">
                <span className={`w-2 h-2 rounded-full ${statusStyle.dot}`} />
                <span className={statusStyle.text}>{statusStyle.label}</span>
              </span>
            )}
          </div>

          {/* Wearing pill + 360 preview badge */}
          {(equippedOutfit || outfitViews.length > 0) && (
            <div className="flex items-center justify-center gap-2 mt-2.5 flex-wrap">
              {equippedOutfit && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-white/[0.04] border border-white/[0.08] text-white/40">
                  <Shirt size={10} className="text-amber-400/60" />
                  Wearing: <span className="text-white/60 capitalize">{equippedOutfit.label || 'Outfit'}</span>
                </span>
              )}
              {outfitViews.length > 0 && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-violet-500/10 border border-violet-500/20 text-violet-300/70">
                  <RotateCcw size={9} />
                  360 preview
                </span>
              )}
            </div>
          )}

          {/* Role subtitle */}
          {agent?.role && (
            <p className="mt-2 text-xs text-white/40">{agent.role}</p>
          )}

          {/* Description */}
          {persona.description && (
            <p className="mt-3 text-[13px] text-white/50 leading-relaxed max-w-xs mx-auto">
              {persona.description}
            </p>
          )}
        </div>

        {/* ═══════════ STATS BARS ═══════════ */}
        <div className="px-6 py-4 border-t border-white/[0.06]">
          <div className="text-[10px] font-semibold text-white/30 uppercase tracking-wider mb-3">Character Stats</div>
          <div className="space-y-2.5">
            {stats.map((stat) => (
              <div key={stat.label} className="flex items-center gap-3">
                <span className="text-xs text-white/50 w-20">{stat.label}</span>
                <div className="flex-1 h-2 rounded-full bg-white/[0.06] overflow-hidden">
                  <div
                    className={`h-full rounded-full ${stat.color} transition-all duration-500`}
                    style={{ width: `${stat.value}%` }}
                  />
                </div>
                <span className="text-[11px] text-white/40 w-8 text-right font-mono">{stat.value}</span>
              </div>
            ))}
          </div>
        </div>

        {/* ═══════════ CURRENT LOOK ═══════════ */}
        {equippedOutfit && (
          <div className="px-6 py-4 border-t border-white/[0.06]">
            <div className="text-[10px] font-semibold text-white/30 uppercase tracking-wider mb-3">Current Look</div>
            <div className="flex items-center gap-3 px-3 py-2.5 rounded-xl bg-white/[0.02] border border-white/[0.06]">
              <Shirt size={14} className="text-white/30 shrink-0" />
              <div className="min-w-0 flex-1">
                <div className="text-[12px] text-white/60 font-medium truncate capitalize">
                  {equippedOutfit.label || 'Outfit'}
                </div>
                {outfitViews.length > 0 && (
                  <div className="text-[10px] text-white/30 mt-0.5">
                    360 preview &middot; {outfitViews.length} views
                  </div>
                )}
              </div>
              {onInspectOutfit && (
                <button
                  onClick={() => onInspectOutfit(equippedOutfit.id || '', equippedOutfit.hero_view || 'front')}
                  className="px-2.5 py-1 text-[10px] font-medium text-white/50 bg-white/[0.04] border border-white/[0.08] rounded-lg hover:bg-white/[0.08] hover:text-white/70 transition-colors shrink-0"
                >
                  Inspect
                </button>
              )}
            </div>
            {/* View angle chips */}
            {outfitViews.length > 0 && (
              <div className="flex gap-1.5 mt-2 px-1">
                {outfitViews.map((angle) => (
                  <button
                    key={angle}
                    onClick={() => onInspectOutfit?.(equippedOutfit.id || '', angle)}
                    className="px-2.5 py-1 text-[10px] font-medium text-white/40 bg-white/[0.03] border border-white/[0.06] rounded-full hover:bg-white/[0.08] hover:text-white/60 transition-colors capitalize"
                  >
                    {angle}
                  </button>
                ))}
              </div>
            )}
            {/* Discoverability hint */}
            {outfitViews.length > 0 && (
              <p className="text-[10px] text-white/20 mt-2.5 px-1 italic">
                Try asking &ldquo;turn around&rdquo; or &ldquo;show me your back&rdquo; in chat
              </p>
            )}
          </div>
        )}

        {/* ═══════════ QUICK INFO ═══════════ */}
        <div className="px-6 py-4 border-t border-white/[0.06]">
          <div className="text-[10px] font-semibold text-white/30 uppercase tracking-wider mb-3">Character Sheet</div>
          <div className="grid grid-cols-2 gap-2">
            {/* Tone */}
            {agent?.response_style?.tone && (
              <InfoTile
                icon={<Volume2 size={13} />}
                label="Tone"
                value={agent.response_style.tone}
              />
            )}
            {/* Style */}
            {appearance?.style_preset && (
              <InfoTile
                icon={<Palette size={13} />}
                label="Style"
                value={appearance.style_preset}
              />
            )}
            {/* Portraits */}
            <InfoTile
              icon={<Image size={13} />}
              label="Portraits"
              value={`${portraitCount}`}
            />
            {/* Wardrobe */}
            <InfoTile
              icon={<Shirt size={13} />}
              label="Wardrobe"
              value={`${outfitCount} outfit${outfitCount !== 1 ? 's' : ''}`}
            />
            {/* Stance */}
            <InfoTile
              icon={stance.icon}
              label="Stance"
              value={stance.label}
            />
            {/* Age */}
            <InfoTile
              icon={<Calendar size={13} />}
              label="Age"
              value={formatAge(persona.created_at)}
            />
          </div>
        </div>

        {/* ═══════════ SKILLS ═══════════ */}
        {skillCount > 0 && (
          <div className="px-6 py-4 border-t border-white/[0.06]">
            <div className="text-[10px] font-semibold text-white/30 uppercase tracking-wider mb-3">
              Skills ({skillCount})
            </div>
            <div className="space-y-1.5">
              {(agentic?.capabilities || []).map((cap) => (
                <div key={cap} className="flex items-center gap-2 px-3 py-2 rounded-lg bg-white/[0.02] border border-white/[0.06]">
                  <span className="text-emerald-400/60">{CAPABILITY_ICONS[cap] || <Sparkles size={12} />}</span>
                  <span className="text-xs text-white/60">{CAPABILITY_LABELS[cap] || cap}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ═══════════ EQUIPMENT (TOOLS) ═══════════ */}
        <div className="px-6 py-4 border-t border-white/[0.06]">
          <div className="text-[10px] font-semibold text-white/30 uppercase tracking-wider mb-3">
            Equipment (Tools)
          </div>
          {toolCount > 0 ? (
            <div className="flex items-center gap-2 px-3 py-2.5 rounded-lg bg-white/[0.02] border border-white/[0.06]">
              <Wrench size={14} className="text-white/30" />
              <span className="text-xs text-white/50">{toolCount} tools enabled</span>
              <ChevronRight size={12} className="text-white/20 ml-auto" />
            </div>
          ) : (
            <div className="text-xs text-white/25 italic">No tools configured</div>
          )}
          {/* Tool details if available */}
          {agentic?.tool_details && agentic.tool_details.length > 0 && (
            <div className="mt-2 space-y-1">
              {agentic.tool_details.slice(0, 6).map((t, i) => (
                <div key={i} className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-white/[0.01]">
                  <Swords size={10} className="text-white/20" />
                  <span className="text-[11px] text-white/40 truncate">{t.name}</span>
                </div>
              ))}
              {agentic.tool_details.length > 6 && (
                <div className="text-[10px] text-white/20 text-center mt-1">
                  +{agentic.tool_details.length - 6} more
                </div>
              )}
            </div>
          )}
        </div>

        {/* ═══════════ PARTY MEMBERS (AGENTS) ═══════════ */}
        {agentic?.agent_details && agentic.agent_details.length > 0 && (
          <div className="px-6 py-4 border-t border-white/[0.06]">
            <div className="text-[10px] font-semibold text-white/30 uppercase tracking-wider mb-3">
              Party Members ({agentic.agent_details.length})
            </div>
            <div className="space-y-1.5">
              {agentic.agent_details.map((a, i) => (
                <div key={i} className="flex items-center gap-2 px-3 py-2 rounded-lg bg-white/[0.02] border border-white/[0.06]">
                  <Bot size={13} className="text-violet-400/50" />
                  <span className="text-xs text-white/50">{a.name}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ═══════════ QUEST OBJECTIVE ═══════════ */}
        {agentic?.goal && (
          <div className="px-6 py-4 border-t border-white/[0.06]">
            <div className="text-[10px] font-semibold text-white/30 uppercase tracking-wider mb-3">Quest Objective</div>
            <p className="text-xs text-white/50 leading-relaxed">{agentic.goal}</p>
          </div>
        )}

        {/* ═══════════ CHARACTER SUMMARY ═══════════ */}
        <div className="px-6 py-4 border-t border-white/[0.06] mb-4">
          <div className="text-[10px] font-semibold text-white/30 uppercase tracking-wider mb-3">Character Summary</div>
          <div className="space-y-1.5 text-xs">
            <SummaryRow label="Class" value={`${classStyle.label}`} icon={<Crown size={11} className={classStyle.color} />} />
            {agent?.role && <SummaryRow label="Role" value={agent.role} icon={<Users size={11} className="text-white/30" />} />}
            {agent?.response_style?.tone && <SummaryRow label="Tone" value={agent.response_style.tone} icon={<Volume2 size={11} className="text-white/30" />} />}
            <SummaryRow label="Portraits" value={`${portraitCount}`} icon={<Image size={11} className="text-white/30" />} />
            <SummaryRow label="Wardrobe" value={`${outfitCount} outfits`} icon={<Shirt size={11} className="text-white/30" />} />
            <SummaryRow label="Equipment" value={toolCount > 0 ? `${toolCount} tools` : 'None'} icon={<Wrench size={11} className="text-white/30" />} />
            <SummaryRow label="Skills" value={`${skillCount}`} icon={<Sparkles size={11} className="text-white/30" />} />
            <SummaryRow label="Stance" value={`${stance.label}${agentic?.ask_before_acting ? ' / Cautious' : ''}`} icon={stance.icon} />
            <SummaryRow label="Level" value={`${level}`} icon={<Shield size={11} className="text-white/30" />} />
          </div>
        </div>
      </div>

      <style>{`
        @keyframes rail-slide-right {
          from { transform: translateX(100%); opacity: 0; }
          to { transform: translateX(0); opacity: 1; }
        }
        .animate-rail-slide-right {
          animation: rail-slide-right 200ms ease-out;
        }
      `}</style>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function InfoTile({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center gap-2 px-3 py-2.5 rounded-xl bg-white/[0.02] border border-white/[0.06]">
      <span className="text-white/25">{icon}</span>
      <div className="min-w-0">
        <div className="text-[9px] text-white/25 uppercase tracking-wider">{label}</div>
        <div className="text-[12px] text-white/60 font-medium truncate capitalize">{value}</div>
      </div>
    </div>
  )
}

function SummaryRow({ label, value, icon }: { label: string; value: string; icon?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-1 px-1">
      <span className="flex items-center gap-1.5 text-white/30">
        {icon}
        {label}
      </span>
      <span className="text-white/55 font-medium capitalize">{value}</span>
    </div>
  )
}
