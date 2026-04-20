/**
 * Shared TypeScript types for the Interactive tab.
 *
 * These mirror the backend pydantic models at
 * `backend/app/interactive/models.py`. Adding a field here does
 * not require a backend change — pydantic is configured with
 * ``extra="allow"``, so the wire format is forward-compatible.
 * Treat every optional field as optional; the UI should render
 * gracefully when it's absent.
 */

export type ExperienceMode =
  | "sfw_general"
  | "sfw_education"
  | "language_learning"
  | "enterprise_training"
  | "social_romantic"
  | "mature_gated";

export type ExperienceStatus =
  | "draft"
  | "in_review"
  | "approved"
  | "archived"
  | "published";

export type ProgressionScheme =
  | "xp_level"
  | "mastery"
  | "cefr"
  | "affinity_tier"
  | "certification";

/**
 * Interaction type is stamped onto `audience_profile` at create time
 * by the wizard (FIX-6). "standard_project" → YouTube-style branching
 * video player with a decision modal between scenes. "persona_live_play"
 * → candy.ai-style persona chat + Live Action sheet. We read it off
 * the audience_profile dict so the wire format stays
 * backward-compatible with pre-FIX-6 experiences.
 */
export type InteractionType = "standard_project" | "persona_live_play";

/**
 * Shape of the ``audience_profile`` blob the wizard stamps onto an
 * Experience. All fields are optional for forward-compat — the
 * backend allows arbitrary keys (``extra='allow'``).
 */
export interface AudienceProfile {
  role?: string;
  level?: string;
  language?: string;
  locale_hint?: string;
  /** "standard_project" | "persona_live_play"; undefined → default to standard. */
  interaction_type?: InteractionType;
  /** Human-readable persona display name (e.g. "Darkangel666"). */
  persona_label?: string;
  /** Persona project id (in the voice/persona subsystem). */
  persona_project_id?: string;
  /** Optional absolute or /files/ relative avatar URL. */
  persona_avatar_url?: string;
  [key: string]: unknown;
}

export interface Experience {
  id: string;
  user_id?: string;
  studio_video_id?: string;
  title: string;
  description?: string;
  objective?: string;
  experience_mode: ExperienceMode;
  policy_profile_id: string;
  audience_profile?: AudienceProfile;
  branch_count?: number;
  max_depth?: number;
  status: ExperienceStatus;
  tags?: string[];
  created_at?: string;
  updated_at?: string;
}

/**
 * Read the interaction type off an Experience. Defaults to
 * "standard_project" when the field is absent (old experiences
 * created before FIX-6 didn't stamp it). Keeps the player's
 * branch logic trivial: ``if (type === 'persona_live_play') …``.
 */
export function resolveInteractionType(exp: Experience | null | undefined): InteractionType {
  const raw = exp?.audience_profile?.interaction_type;
  return raw === "persona_live_play" ? "persona_live_play" : "standard_project";
}

export interface NodeItem {
  id: string;
  experience_id: string;
  kind: "scene" | "decision" | "merge" | "ending" | "assessment" | "remediation";
  title: string;
  narration?: string;
  image_prompt?: string;
  video_prompt?: string;
  duration_sec?: number;
  storyboard?: Record<string, unknown>;
  interaction_layout?: Record<string, unknown>;
  asset_ids?: string[];
  created_at?: string;
  updated_at?: string;
}

export interface EdgeItem {
  id: string;
  experience_id: string;
  from_node_id: string;
  to_node_id: string;
  trigger_kind: "auto" | "choice" | "hotspot" | "timer" | "fallback" | "intent";
  trigger_payload?: Record<string, unknown>;
  ordinal?: number;
  created_at?: string;
}

export interface ActionItem {
  id: string;
  experience_id: string;
  label: string;
  intent_code?: string;
  required_level?: number;
  required_scheme?: ProgressionScheme;
  required_metric_key?: string;
  policy_scope?: string[];
  cooldown_sec?: number;
  mood_delta?: Record<string, unknown>;
  xp_award?: number;
  max_uses_per_session?: number;
  repeat_penalty?: number;
  requires_consent?: string;
  applicable_modes?: string[];
  ordinal?: number;
}

export interface RuleItem {
  id: string;
  experience_id: string;
  name: string;
  condition: Record<string, unknown>;
  action: Record<string, unknown>;
  priority: number;
  enabled: boolean;
  created_at?: string;
}

export interface PlanningPreset {
  mode: string;
  objective_template: string;
  default_branch_count: number;
  default_depth: number;
  default_scenes_per_branch: number;
  default_topology: string;
  default_scheme: ProgressionScheme;
  seed_intents: string[];
}

export interface PlanIntent {
  prompt: string;
  mode: string;
  objective: string;
  topic: string;
  branch_count: number;
  depth: number;
  scenes_per_branch: number;
  success_metric: string;
  seed_intents: string[];
  scheme: ProgressionScheme;
  audience: {
    role: string;
    level: string;
    language: string;
    locale_hint: string;
    interests: string[];
  };
  raw_hints: Record<string, unknown>;
}

export interface QAIssue {
  code: string;
  severity: "error" | "warning" | "info";
  detail: string;
  [extra: string]: unknown;
}

export interface QAResult {
  verdict: "pass" | "warn" | "fail";
  counts: { error: number; warning: number; info: number; total: number };
  issues: QAIssue[];
  report_id?: string;
}

export interface Publication {
  id: string;
  experience_id: string;
  channel: "web_embed" | "studio_preview" | "export";
  manifest_url?: string;
  version: number;
  metadata?: Record<string, unknown>;
  published_at?: string;
}

export interface PublishResult {
  status: "published" | "unchanged" | "blocked";
  channel: string;
  detail: string;
  publication?: Publication;
  qa?: QAResult;
}

export interface HealthInfo {
  ok: boolean;
  service: string;
  enabled: boolean;
  limits: {
    max_branches: number;
    max_depth: number;
    max_nodes_per_experience: number;
  };
  chassis_guardrails: {
    require_consent_for_mature: boolean;
    enforce_region_block: boolean;
    moderate_mature_narration: boolean;
    blocked_regions: number;
  };
  runtime_latency_target_ms: number;
}

export interface AnalyticsSummary {
  experience_id: string;
  session_count: number;
  completed_sessions: number;
  completion_rate: number;
  total_turns: number;
  total_events: number;
  popular_actions: Array<{ action_id: string; uses: number }>;
  block_rate: number;
}

// ── AUTO-* auto-planner / generator types ──────────────────────

/** Pre-filled wizard form returned from POST /plan-auto. */
export interface PlanAutoForm {
  title: string;
  prompt: string;
  experience_mode: ExperienceMode;
  policy_profile_id: string;
  audience_role: string;
  audience_level: "beginner" | "intermediate" | "advanced";
  audience_language: string;
  audience_locale_hint: string;
  branch_count: number;
  depth: number;
  scenes_per_branch: number;
}

/** Full /plan-auto response. source='llm' means the LLM composer
 *  produced it; 'heuristic' means the deterministic fallback fired
 *  (LLM off, unreachable, or rejected). */
export interface PlanAutoResult {
  source: "llm" | "heuristic";
  form: PlanAutoForm;
  objective: string;
  topic: string;
  scheme: ProgressionScheme;
  success_metric: string;
  seed_intents: string[];
}

/** Response from POST /experiences/{id}/auto-generate. */
export interface AutoGenerateResult {
  source: "llm" | "heuristic" | "existing";
  already_generated: boolean;
  node_count: number;
  edge_count: number;
  action_count: number;
  warnings?: string[];
}

/**
 * One frame in the ``/auto-generate/stream`` SSE feed (PIPE-2).
 * Kinds the backend emits today:
 *   started · already_generated · generating_graph · graph_generated
 *   · persisting_nodes · persisting_edges · persisting_actions
 *   · seeding_rule · running_qa · qa_done · result · error · done
 * Treat unknown ``type`` values as noise — the stream is
 * forward-compatible by contract.
 */
export interface AutoGenerateStreamEvent {
  type: string;
  payload?: Record<string, unknown>;
}

// ── Live-play types ─────────────────────────────────────────────

export type SceneJobStatus = "pending" | "rendering" | "ready" | "failed";

export interface SceneJobView {
  id: string;
  session_id: string;
  turn_id: string;
  status: SceneJobStatus;
  job_id: string;
  asset_id: string;
  /** Resolved durable URL for the scene (empty when the asset is a stub
   *  or the backend couldn't resolve a public URL yet). */
  asset_url: string;
  prompt: string;
  duration_sec: number;
  error: string;
  created_at: string;
  updated_at: string;
}

export interface ChatResult {
  status: "ok" | "blocked";
  decision: {
    decision: string;
    reason_code: string;
    message: string;
    intent_code: string;
  };
  reply_text: string;
  scene_prompt?: string;
  duration_sec?: number;
  topic_continuity?: string;
  intent_code?: string;
  mood?: string;
  affinity_score?: number;
  viewer_turn_id?: string;
  character_turn_id?: string;
  video_job_id: string;
  video_job_status?: SceneJobStatus;
  video_asset_id?: string;
  /** Resolved durable URL for the scene — empty string when the backend
   *  only has a stub asset or hasn't resolved a public URL yet. */
  video_asset_url?: string;
}

export interface PendingResult {
  items: SceneJobView[];
  cursor: string;
}

export interface CatalogItemView {
  id: string;
  label: string;
  intent_code: string;
  required_level: number;
  required_scheme: string;
  cooldown_sec: number;
  xp_award: number;
  ordinal: number;
  unlocked: boolean;
  lock_reason: string;
}

export interface LevelDescriptionView {
  level: number;
  label: string;
  display: string;
  current_value: number;
  next_threshold: number;
}

export interface ProgressSnapshot {
  progress: Record<string, Record<string, number>>;
  descriptions: Record<string, LevelDescriptionView>;
  mood: string;
  affinity_score: number;
}

export interface ResolveResult {
  session_id: string;
  decision: { decision: string; reason_code: string; message: string };
  transition: {
    to_node_id: string;
    kind: string;
    label: string;
    payload: Record<string, unknown>;
  };
  intent_code: string;
  reward_deltas: Record<string, number>;
  level_description: { display: string; level: number };
  mood: string;
  affinity_score: number;
  matched_rule_id?: string | null;
}

/** Typed error returned by the API client on non-2xx responses. */
export class InteractiveApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly data: Record<string, unknown>;
  constructor(
    message: string, status: number, code = "unknown", data: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "InteractiveApiError";
    this.status = status;
    this.code = code;
    this.data = data;
  }
}
