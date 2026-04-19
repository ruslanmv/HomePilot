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

export interface Experience {
  id: string;
  user_id?: string;
  studio_video_id?: string;
  title: string;
  description?: string;
  objective?: string;
  experience_mode: ExperienceMode;
  policy_profile_id: string;
  audience_profile?: Record<string, unknown>;
  branch_count?: number;
  max_depth?: number;
  status: ExperienceStatus;
  tags?: string[];
  created_at?: string;
  updated_at?: string;
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
