/**
 * API client for the edit-session sidecar service.
 *
 * This module provides functions to interact with the edit session endpoints,
 * enabling natural language image editing workflows.
 */
/**
 * Generate authentication headers if API key is provided.
 */
function authHeaders(apiKey) {
    return apiKey ? { 'X-API-Key': apiKey } : {};
}
/**
 * Upload an image to start or continue an edit session.
 *
 * @param params - Upload parameters
 * @returns Session state after upload
 */
export async function uploadToEditSession(params) {
    const { backendUrl, apiKey, conversationId, file, instruction } = params;
    const base = backendUrl.replace(/\/+$/, '');
    const url = `${base}/v1/edit-sessions/${encodeURIComponent(conversationId)}/image`;
    const fd = new FormData();
    fd.append('file', file);
    if (instruction?.trim()) {
        fd.append('instruction', instruction.trim());
    }
    const res = await fetch(url, {
        method: 'POST',
        headers: { ...authHeaders(apiKey) },
        body: fd,
    });
    if (!res.ok) {
        const text = await res.text().catch(() => `HTTP ${res.status}`);
        throw new Error(text);
    }
    return res.json();
}
/**
 * Send a natural language edit message to modify the active image.
 *
 * @param params - Message parameters
 * @returns Edit result with generated images
 */
export async function sendEditMessage(params) {
    const { backendUrl, apiKey, conversationId, ...body } = params;
    const base = backendUrl.replace(/\/+$/, '');
    const url = `${base}/v1/edit-sessions/${encodeURIComponent(conversationId)}/message`;
    const res = await fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            ...authHeaders(apiKey),
        },
        body: JSON.stringify(body),
    });
    if (!res.ok) {
        const text = await res.text().catch(() => `HTTP ${res.status}`);
        throw new Error(text);
    }
    return res.json();
}
/**
 * Select a generated image as the new active base for further edits.
 *
 * @param params - Selection parameters
 * @returns Updated session state
 */
export async function selectActiveImage(params) {
    const { backendUrl, apiKey, conversationId, image_url } = params;
    const base = backendUrl.replace(/\/+$/, '');
    const url = `${base}/v1/edit-sessions/${encodeURIComponent(conversationId)}/select`;
    const res = await fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            ...authHeaders(apiKey),
        },
        body: JSON.stringify({ image_url }),
    });
    if (!res.ok) {
        const text = await res.text().catch(() => `HTTP ${res.status}`);
        throw new Error(text);
    }
    return res.json();
}
/**
 * Get the current state of an edit session.
 *
 * @param params - Session parameters
 * @returns Current session state
 */
export async function getEditSession(params) {
    const { backendUrl, apiKey, conversationId } = params;
    const base = backendUrl.replace(/\/+$/, '');
    const url = `${base}/v1/edit-sessions/${encodeURIComponent(conversationId)}`;
    const res = await fetch(url, {
        method: 'GET',
        headers: { ...authHeaders(apiKey) },
    });
    if (!res.ok) {
        const text = await res.text().catch(() => `HTTP ${res.status}`);
        throw new Error(text);
    }
    return res.json();
}
/**
 * Clear all data for an edit session.
 *
 * @param params - Session parameters
 * @returns Success indicator
 */
export async function clearEditSession(params) {
    const { backendUrl, apiKey, conversationId } = params;
    const base = backendUrl.replace(/\/+$/, '');
    const url = `${base}/v1/edit-sessions/${encodeURIComponent(conversationId)}`;
    const res = await fetch(url, {
        method: 'DELETE',
        headers: { ...authHeaders(apiKey) },
    });
    if (!res.ok) {
        const text = await res.text().catch(() => `HTTP ${res.status}`);
        throw new Error(text);
    }
    return res.json();
}
/**
 * Delete a single version from an edit session.
 *
 * @param params - Delete parameters
 * @returns Updated session state
 */
export async function deleteVersion(params) {
    const { backendUrl, apiKey, conversationId, imageUrl } = params;
    const base = backendUrl.replace(/\/+$/, '');
    const url = `${base}/v1/edit-sessions/${encodeURIComponent(conversationId)}/version?image_url=${encodeURIComponent(imageUrl)}`;
    const res = await fetch(url, {
        method: 'DELETE',
        headers: { ...authHeaders(apiKey) },
    });
    if (!res.ok) {
        const text = await res.text().catch(() => `HTTP ${res.status}`);
        throw new Error(text);
    }
    return res.json();
}
/**
 * Revert to a previous image from history.
 *
 * @param params - Revert parameters
 * @returns Updated session state
 */
export async function revertToHistory(params) {
    const { backendUrl, apiKey, conversationId, index } = params;
    const base = backendUrl.replace(/\/+$/, '');
    const url = `${base}/v1/edit-sessions/${encodeURIComponent(conversationId)}/revert?index=${index}`;
    const res = await fetch(url, {
        method: 'POST',
        headers: { ...authHeaders(apiKey) },
    });
    if (!res.ok) {
        const text = await res.text().catch(() => `HTTP ${res.status}`);
        throw new Error(text);
    }
    return res.json();
}
/**
 * Extract image URLs from a HomePilot response.
 *
 * Handles various response shapes:
 * - { media: { images: [...] } }
 * - { images: [...] }
 * - { data: { media: { images: [...] } } }
 *
 * @param raw - Raw response object
 * @returns Array of unique image URLs
 */
export function extractImages(raw) {
    const out = [];
    const add = (u) => {
        if (typeof u === 'string' && (u.startsWith('http://') || u.startsWith('https://'))) {
            out.push(u);
        }
    };
    // Try media.images
    const media = raw?.media;
    if (media?.images && Array.isArray(media.images)) {
        media.images.forEach(add);
    }
    // Try top-level images
    if (raw?.images && Array.isArray(raw.images)) {
        raw.images.forEach(add);
    }
    // Try data.media.images
    const data = raw?.data;
    if (data?.media) {
        const dataMedia = data.media;
        if (dataMedia?.images && Array.isArray(dataMedia.images)) {
            dataMedia.images.forEach(add);
        }
    }
    // De-duplicate while preserving order
    return Array.from(new Set(out));
}
/**
 * Import an existing image by URL — server-side copy, no browser round-trip.
 *
 * This avoids the client download → re-upload pattern that fails on WSL
 * mounted filesystems and is wasteful for images already on the server.
 *
 * Accepts /files/{asset_id}, /comfy/view/..., or ComfyUI absolute URLs.
 *
 * @param params - Import parameters
 * @returns New asset info with url and optional asset_id
 */
export async function importImageByUrl(params) {
    const { backendUrl, apiKey, url } = params;
    const base = backendUrl.replace(/\/+$/, '');
    const endpoint = `${base}/v1/import-image`;
    const res = await fetch(endpoint, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            ...authHeaders(apiKey),
        },
        body: JSON.stringify({ url }),
    });
    if (!res.ok) {
        const text = await res.text().catch(() => `HTTP ${res.status}`);
        throw new Error(text);
    }
    return res.json();
}
/**
 * Upload an image to an edit session by URL — entirely server-side.
 *
 * The backend resolves the image URL (/files/..., /comfy/view/...) to a file
 * on disk and forwards it to the edit session sidecar as a multipart upload.
 * No browser download/reupload needed.
 *
 * @param params - Upload parameters
 * @returns Session state after upload
 */
export async function uploadToEditSessionByUrl(params) {
    const { backendUrl, apiKey, conversationId, imageUrl } = params;
    const base = backendUrl.replace(/\/+$/, '');
    const endpoint = `${base}/v1/edit-sessions/${encodeURIComponent(conversationId)}/image`;
    const res = await fetch(endpoint, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            ...authHeaders(apiKey),
        },
        body: JSON.stringify({ image_url: imageUrl }),
    });
    if (!res.ok) {
        const text = await res.text().catch(() => `HTTP ${res.status}`);
        throw new Error(text);
    }
    return res.json();
}
