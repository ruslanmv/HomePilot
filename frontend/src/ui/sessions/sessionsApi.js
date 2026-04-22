/**
 * Persona Sessions API Client — Companion-Grade
 *
 * Handles session lifecycle: create, resolve, end, list.
 * Also handles Long-Term Memory (LTM) queries.
 *
 * Additive: does not modify any existing API calls.
 */
import { resolveBackendUrl } from '../lib/backendUrl';
// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------
function getBackendUrl() {
    return resolveBackendUrl();
}
function getAuthHeaders() {
    const apiKey = localStorage.getItem('homepilot_api_key') || '';
    const headers = { 'Content-Type': 'application/json' };
    if (apiKey)
        headers['Authorization'] = `Bearer ${apiKey}`;
    return headers;
}
// ---------------------------------------------------------------------------
// Session API
// ---------------------------------------------------------------------------
/**
 * Resolve the best session to resume (or create one if none exist).
 * This is the main entry point — bulletproof resume algorithm.
 */
export async function resolveSession(projectId, mode = 'text') {
    const res = await fetch(`${getBackendUrl()}/persona/sessions/resolve`, {
        method: 'POST',
        headers: getAuthHeaders(),
        credentials: 'include',
        body: JSON.stringify({ project_id: projectId, mode }),
    });
    const data = await res.json();
    if (!data.ok)
        throw new Error(data.message || 'Failed to resolve session');
    return data.session;
}
/**
 * Create a session for a persona project.
 * The backend will soft-reuse a recent low-activity session by default.
 * Pass forceNew=true to always create a fresh session.
 */
export async function createSession(projectId, mode = 'text', title, forceNew = false) {
    const res = await fetch(`${getBackendUrl()}/persona/sessions`, {
        method: 'POST',
        headers: getAuthHeaders(),
        credentials: 'include',
        body: JSON.stringify({ project_id: projectId, mode, title, force_new: forceNew }),
    });
    const data = await res.json();
    if (!data.ok)
        throw new Error(data.message || 'Failed to create session');
    return data.session;
}
/**
 * End a session (marks ended_at, triggers summary + memory extraction).
 */
export async function endSession(sessionId) {
    await fetch(`${getBackendUrl()}/persona/sessions/${sessionId}/end`, {
        method: 'POST',
        headers: getAuthHeaders(),
        credentials: 'include',
    });
}
/**
 * List all sessions for a persona project.
 */
export async function listSessions(projectId, limit = 50) {
    const res = await fetch(`${getBackendUrl()}/persona/sessions?project_id=${encodeURIComponent(projectId)}&limit=${limit}`, { headers: getAuthHeaders(), credentials: 'include' });
    const data = await res.json();
    if (!data.ok)
        throw new Error(data.message || 'Failed to list sessions');
    return data.sessions;
}
/**
 * Get a single session by ID.
 */
export async function getSession(sessionId) {
    const res = await fetch(`${getBackendUrl()}/persona/sessions/${sessionId}`, {
        headers: getAuthHeaders(),
        credentials: 'include',
    });
    const data = await res.json();
    if (!data.ok)
        throw new Error(data.message || 'Failed to get session');
    return data.session;
}
// ---------------------------------------------------------------------------
// Long-Term Memory API
// ---------------------------------------------------------------------------
/**
 * Get all memories for a persona project ("What I know about you").
 */
export async function getMemories(projectId, category) {
    const params = new URLSearchParams({ project_id: projectId });
    if (category)
        params.set('category', category);
    const res = await fetch(`${getBackendUrl()}/persona/memory?${params}`, {
        headers: getAuthHeaders(),
        credentials: 'include',
    });
    const data = await res.json();
    if (!data.ok)
        throw new Error(data.message || 'Failed to get memories');
    return { memories: data.memories, count: data.count };
}
/**
 * Manually add or update a memory entry.
 */
export async function upsertMemory(projectId, category, key, value, confidence = 1.0) {
    await fetch(`${getBackendUrl()}/persona/memory`, {
        method: 'POST',
        headers: getAuthHeaders(),
        credentials: 'include',
        body: JSON.stringify({
            project_id: projectId,
            category,
            key,
            value,
            confidence,
            source_type: 'user_statement',
        }),
    });
}
/**
 * Delete a specific memory or forget all.
 */
export async function forgetMemory(projectId, category, key) {
    await fetch(`${getBackendUrl()}/persona/memory`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
        credentials: 'include',
        body: JSON.stringify({ project_id: projectId, category, key }),
    });
}
