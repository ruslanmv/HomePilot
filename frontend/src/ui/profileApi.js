/**
 * Profile API client — additive module (v1).
 *
 * Talks to /v1/profile, /v1/profile/secrets, and /v1/memory endpoints.
 * NSFW on/off is NOT managed here — it remains global in SettingsPanel.
 */
/** Factory for an empty CommunicationInfo — used when the backend
 *  response predates the feature and the UI needs a safe baseline. */
export function emptyCommunicationInfo() {
    return {
        phone_e164: '',
        whatsapp_e164: '',
        telegram_username: '',
        preferred_contact_channel: 'none',
        preferred_call_channel: 'none',
        allow_ai_outbound: false,
    };
}
function headers(apiKey) {
    const h = { 'Content-Type': 'application/json' };
    if (apiKey)
        h['X-API-Key'] = apiKey;
    return h;
}
// ---------------------------------------------------------------------------
// Profile
// ---------------------------------------------------------------------------
export async function fetchProfile(backendUrl, apiKey) {
    const res = await fetch(`${backendUrl}/v1/profile`, { headers: headers(apiKey) });
    if (!res.ok)
        throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (!data.ok)
        throw new Error(data.message || 'Failed to load profile');
    return data.profile;
}
export async function saveProfile(backendUrl, apiKey, profile) {
    const res = await fetch(`${backendUrl}/v1/profile`, {
        method: 'PUT',
        headers: headers(apiKey),
        body: JSON.stringify(profile),
    });
    if (!res.ok) {
        const txt = await res.text().catch(() => '');
        throw new Error(txt || `HTTP ${res.status}`);
    }
    const data = await res.json();
    if (!data.ok)
        throw new Error(data.message || 'Failed to save profile');
}
// ---------------------------------------------------------------------------
// Secrets
// ---------------------------------------------------------------------------
export async function listSecrets(backendUrl, apiKey) {
    const res = await fetch(`${backendUrl}/v1/profile/secrets`, { headers: headers(apiKey) });
    if (!res.ok)
        throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (!data.ok)
        throw new Error(data.message || 'Failed to load secrets');
    return data.secrets;
}
export async function upsertSecret(backendUrl, apiKey, body) {
    const res = await fetch(`${backendUrl}/v1/profile/secrets`, {
        method: 'PUT',
        headers: headers(apiKey),
        body: JSON.stringify(body),
    });
    if (!res.ok)
        throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (!data.ok)
        throw new Error(data.message || 'Failed to save secret');
}
export async function deleteSecret(backendUrl, apiKey, key) {
    const res = await fetch(`${backendUrl}/v1/profile/secrets/${encodeURIComponent(key)}`, {
        method: 'DELETE',
        headers: headers(apiKey),
    });
    if (!res.ok)
        throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (!data.ok)
        throw new Error(data.message || 'Failed to delete secret');
}
// ---------------------------------------------------------------------------
// Memory
// ---------------------------------------------------------------------------
export async function fetchMemory(backendUrl, apiKey) {
    const res = await fetch(`${backendUrl}/v1/memory`, { headers: headers(apiKey) });
    if (!res.ok)
        throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (!data.ok)
        throw new Error(data.message || 'Failed to load memory');
    return (data.memory?.items || []);
}
export async function saveMemory(backendUrl, apiKey, items) {
    const res = await fetch(`${backendUrl}/v1/memory`, {
        method: 'PUT',
        headers: headers(apiKey),
        body: JSON.stringify({ items }),
    });
    if (!res.ok)
        throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (!data.ok)
        throw new Error(data.message || 'Failed to save memory');
}
export async function deleteMemoryItem(backendUrl, apiKey, id) {
    const res = await fetch(`${backendUrl}/v1/memory/${encodeURIComponent(id)}`, {
        method: 'DELETE',
        headers: headers(apiKey),
    });
    if (!res.ok)
        throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (!data.ok)
        throw new Error(data.message || 'Failed to delete memory item');
}
// ---------------------------------------------------------------------------
// Per-User Profile (Bearer auth — multi-user aware)
// These hit /v1/user-profile/* and /v1/user-memory/* endpoints.
// ---------------------------------------------------------------------------
function bearerHeaders(token) {
    const h = { 'Content-Type': 'application/json' };
    if (token)
        h['Authorization'] = `Bearer ${token}`;
    return h;
}
export async function fetchUserProfile(backendUrl, token) {
    const res = await fetch(`${backendUrl}/v1/user-profile`, { headers: bearerHeaders(token), credentials: 'include' });
    if (!res.ok)
        throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (!data.ok)
        throw new Error(data.message || 'Failed to load user profile');
    return data.profile;
}
export async function saveUserProfile(backendUrl, token, profile) {
    const res = await fetch(`${backendUrl}/v1/user-profile`, {
        method: 'PUT',
        headers: bearerHeaders(token),
        credentials: 'include',
        body: JSON.stringify(profile),
    });
    if (!res.ok) {
        const txt = await res.text().catch(() => '');
        throw new Error(txt || `HTTP ${res.status}`);
    }
    const data = await res.json();
    if (!data.ok)
        throw new Error(data.message || 'Failed to save user profile');
}
export async function listUserSecrets(backendUrl, token) {
    const res = await fetch(`${backendUrl}/v1/user-profile/secrets`, { headers: bearerHeaders(token) });
    if (!res.ok)
        throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (!data.ok)
        throw new Error(data.message || 'Failed to load secrets');
    return data.secrets;
}
export async function upsertUserSecret(backendUrl, token, body) {
    const res = await fetch(`${backendUrl}/v1/user-profile/secrets`, {
        method: 'PUT',
        headers: bearerHeaders(token),
        body: JSON.stringify(body),
    });
    if (!res.ok)
        throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (!data.ok)
        throw new Error(data.message || 'Failed to save secret');
}
export async function deleteUserSecret(backendUrl, token, key) {
    const res = await fetch(`${backendUrl}/v1/user-profile/secrets/${encodeURIComponent(key)}`, {
        method: 'DELETE',
        headers: bearerHeaders(token),
    });
    if (!res.ok)
        throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (!data.ok)
        throw new Error(data.message || 'Failed to delete secret');
}
export async function fetchUserMemory(backendUrl, token) {
    const res = await fetch(`${backendUrl}/v1/user-memory`, { headers: bearerHeaders(token) });
    if (!res.ok)
        throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (!data.ok)
        throw new Error(data.message || 'Failed to load memory');
    return (data.memory?.items || []);
}
export async function saveUserMemory(backendUrl, token, items) {
    const res = await fetch(`${backendUrl}/v1/user-memory`, {
        method: 'PUT',
        headers: bearerHeaders(token),
        body: JSON.stringify({ items }),
    });
    if (!res.ok)
        throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (!data.ok)
        throw new Error(data.message || 'Failed to save memory');
}
export async function deleteUserMemoryItem(backendUrl, token, id) {
    const res = await fetch(`${backendUrl}/v1/user-memory/${encodeURIComponent(id)}`, {
        method: 'DELETE',
        headers: bearerHeaders(token),
    });
    if (!res.ok)
        throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (!data.ok)
        throw new Error(data.message || 'Failed to delete memory item');
}
// ---------------------------------------------------------------------------
// Avatar upload/delete (Bearer auth)
// ---------------------------------------------------------------------------
export async function uploadAvatar(backendUrl, token, file) {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch(`${backendUrl}/v1/auth/avatar`, {
        method: 'PUT',
        headers: token ? { 'Authorization': `Bearer ${token}` } : {},
        credentials: 'include',
        body: form,
    });
    if (!res.ok) {
        const txt = await res.text().catch(() => '');
        throw new Error(txt || `HTTP ${res.status}`);
    }
    const data = await res.json();
    if (!data.ok)
        throw new Error(data.message || 'Failed to upload avatar');
    return data.avatar_url;
}
export async function deleteAvatar(backendUrl, token) {
    const res = await fetch(`${backendUrl}/v1/auth/avatar`, {
        method: 'DELETE',
        headers: token ? { 'Authorization': `Bearer ${token}` } : {},
        credentials: 'include',
    });
    if (!res.ok)
        throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (!data.ok)
        throw new Error(data.message || 'Failed to delete avatar');
}
