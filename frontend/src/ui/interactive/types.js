/**
 * Shared runtime-facing types and helpers for the Interactive tab.
 *
 * These mirror the backend pydantic models at
 * `backend/app/interactive/models.py`. Adding a field here does
 * not require a backend change — pydantic is configured with
 * `extra="allow"`, so the wire format is forward-compatible.
 *
 * Treat every optional field as optional; the UI should render
 * gracefully when it's absent.
 */

/**
 * InteractionType
 * @typedef {"standard_project" | "persona_live_play"} InteractionType
 */

/**
 * AudienceProfile
 *
 * Expanded for persona-live production support:
 * - frozen portrait/avatar URLs
 * - fit/position hints for the player stage
 *
 * @typedef {Object} AudienceProfile
 * @property {string=} role
 * @property {string=} level
 * @property {string=} language
 * @property {string=} locale_hint
 * @property {InteractionType=} interaction_type
 * @property {string=} persona_label
 * @property {string=} persona_project_id
 * @property {string=} persona_avatar_url
 * @property {string=} persona_portrait_url
 * @property {"cover" | "contain"=} persona_image_fit
 * @property {string=} persona_image_position
 */

/**
 * Experience
 * Minimal runtime shape used by the frontend helper below.
 *
 * @typedef {Object} Experience
 * @property {AudienceProfile=} audience_profile
 */

/**
 * Read the interaction type off an Experience.
 *
 * Defaults to "standard_project" when the field is absent
 * (older experiences created before persona-live stamping).
 *
 * Keeps the player's branch logic trivial:
 * `if (type === "persona_live_play") { ... }`
 *
 * @param {Experience | null | undefined} exp
 * @returns {InteractionType}
 */
export function resolveInteractionType(exp) {
  const raw = exp?.audience_profile?.interaction_type;
  return raw === "persona_live_play" ? "persona_live_play" : "standard_project";
}

/**
 * Safely normalize an arbitrary audience_profile-like object into a
 * production-friendly shape the UI can consume without lots of guards.
 *
 * This is optional but useful anywhere the player/editor wants the
 * newer persona fields while staying backward-compatible.
 *
 * @param {any} profile
 * @returns {AudienceProfile}
 */
export function normalizeAudienceProfile(profile) {
  const p = profile && typeof profile === "object" ? profile : {};

  const fit = p.persona_image_fit === "cover" ? "cover" : (
    p.persona_image_fit === "contain" ? "contain" : undefined
  );

  const interactionType =
    p.interaction_type === "persona_live_play"
      ? "persona_live_play"
      : "standard_project";

  return {
    ...p,
    role: stringOrUndefined(p.role),
    level: stringOrUndefined(p.level),
    language: stringOrUndefined(p.language),
    locale_hint: stringOrUndefined(p.locale_hint),
    interaction_type: interactionType,
    persona_label: stringOrUndefined(p.persona_label),
    persona_project_id: stringOrUndefined(p.persona_project_id),
    persona_avatar_url: stringOrUndefined(p.persona_avatar_url),
    persona_portrait_url: stringOrUndefined(p.persona_portrait_url),
    persona_image_fit: fit,
    persona_image_position: stringOrUndefined(p.persona_image_position),
  };
}

/** Typed error returned by the API client on non-2xx responses. */
export class InteractiveApiError extends Error {
  constructor(message, status, code = "unknown", data = {}) {
    super(message);
    this.name = "InteractiveApiError";
    this.status = status;
    this.code = code;
    this.data = data;
  }
}

function stringOrUndefined(value) {
  const v = String(value ?? "").trim();
  return v ? v : undefined;
}