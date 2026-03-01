/** Teams module types */

export type MeetingMessage = {
  id: string
  sender_id: string
  sender_name: string
  content: string
  role: 'user' | 'assistant'
  tools_used: string[]
  timestamp: number
}

/** Snapshot of a persona's speaking intent (computed by orchestrator). */
export type IntentSnapshot = {
  wants_to_speak: boolean
  confidence: number
  reason: string
  intent_type: string // "idea" | "risk" | "clarify" | "summary" | "action"
  urgency: number
  topic_tags: string[]
  ts: number
}

/** Metadata for a single auto-raised hand (managed by orchestrator). */
export type HandRaiseMeta = {
  raised_at_round: number
  expires_round: number
  reason: string
  confidence_at_raise: number
  intent_type: string
}

/** Meeting participation policy (room-level defaults). */
export type MeetingPolicy = {
  max_speakers_per_event?: number
  max_rounds_per_event?: number
  speak_threshold?: number
  cooldown_turns?: number
  // Hand-raise policy
  hand_raise_threshold?: number
  hand_raise_ttl_rounds?: number
  max_visible_hands?: number
  // Redundancy + dominance
  redundancy_threshold?: number
  dominance_lookback?: number
  dominance_penalty?: number
}

/** Shared document attached to a meeting room. */
export type TeamDocument = {
  id: string
  name: string
  type: 'pdf' | 'md' | 'txt' | 'file' | 'url'
  kind: 'file' | 'url'
  url?: string
  uploaded_by?: string
  size_bytes?: number
  created_at: number
}

/**
 * Extended room policy including LLM, view, and advanced settings.
 * Used by TeamsSettingsDrawer for UI-level configuration.
 * Extends MeetingPolicy with additional operational knobs.
 */
export type TeamsRoomPolicy = MeetingPolicy & {
  // LLM & Performance
  llm_provider?: string
  llm_model?: string
  llm_base_url?: string
  llm_concurrency?: number
  llm_timeout_secs?: number
  // View preferences
  view_layout?: 'oval' | 'grid'
  view_show_labels?: boolean
  view_show_animations?: boolean
  // Advanced
  memory_depth?: number
}

/** Play Mode conversation style presets. */
export type PlayModeStyle = 'discussion' | 'debate' | 'roundtable' | 'roleplay' | 'simulation'

/** Play Mode state stored on the room. */
export type PlayModeState = {
  enabled: boolean
  style: PlayModeStyle
  interval_ms: number      // pause between auto-steps (ms)
  max_rounds: number        // hard stop after N rounds
  round_count: number       // rounds completed in this session
  paused_by_user: boolean   // user manually paused
}

export type MeetingRoom = {
  id: string
  name: string
  description: string
  participant_ids: string[]
  turn_mode: 'round-robin' | 'free-form' | 'moderated' | 'reactive'
  topic?: string  // Main discussion topic
  agenda: string[]
  messages: MeetingMessage[]
  documents?: TeamDocument[]
  created_at: number
  updated_at: number
  status: 'active' | 'archived'
  // Computed summary fields (injected by list_rooms for landing page)
  message_count?: number
  participant_count?: number
  last_activity?: number
  // Orchestration state (populated by /react endpoint)
  policy?: MeetingPolicy
  intents?: Record<string, IntentSnapshot>
  hand_raises?: string[]
  hand_raise_meta?: Record<string, HandRaiseMeta>
  muted?: string[]
  cooldowns?: Record<string, number>
  called_on?: string
  round?: number
  // Play Mode (autonomous AI conversation)
  play_mode?: PlayModeState
}

export type PersonaSummary = {
  id: string
  name: string
  description?: string
  project_type?: string
  created_at?: number
  persona_agent?: {
    label?: string
    role?: string
    system_prompt?: string
    persona_class?: string
    allowed_tools?: string[]
    response_style?: {
      tone?: string
      max_length?: string
      use_emoji?: boolean
    }
    key_techniques?: string[]
    unique_behaviors?: string[]
  }
  persona_appearance?: {
    style_preset?: string
    gender?: string
    selected_filename?: string
    selected_thumb_filename?: string
    sets?: Array<{ set_id: string; images: unknown[] }>
    outfits?: unknown[]
    persona_voice?: {
      provider?: string
      voiceURI?: string
      name?: string
      lang?: string
      rate?: number
      pitch?: number
      volume?: number
    }
  }
  agentic?: {
    goal?: string
    capabilities?: string[]
    execution_profile?: string
    ask_before_acting?: boolean
    tool_details?: Array<{ name: string; description?: string }>
    agent_details?: Array<{ name: string; description?: string }>
  }
}
