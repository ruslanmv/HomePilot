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
/**
 * Read the interaction type off an Experience. Defaults to
 * "standard_project" when the field is absent (old experiences
 * created before FIX-6 didn't stamp it). Keeps the player's
 * branch logic trivial: ``if (type === 'persona_live_play') …``.
 */
export function resolveInteractionType(exp) {
    const raw = exp?.audience_profile?.interaction_type;
    return raw === "persona_live_play" ? "persona_live_play" : "standard_project";
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
