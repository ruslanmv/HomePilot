/**
 * Inventory API client — calls backend /v1/inventory/* REST endpoints.
 */
// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function authHeaders(apiKey) {
    const h = { 'Content-Type': 'application/json' };
    if (apiKey && apiKey.trim().length > 0)
        h['x-api-key'] = apiKey;
    // Additive: attach the logged-in user's bearer JWT when present so
    // inventory endpoints that now accept 'user session OR api key'
    // (see backend/app/auth.py::require_api_key) authenticate without
    // the shared API key. Silent no-op on anonymous / not-yet-logged-in
    // sessions.
    try {
        if (typeof window !== 'undefined') {
            const tok = window.localStorage.getItem('homepilot_auth_token') || '';
            if (tok && !h['Authorization'])
                h['Authorization'] = `Bearer ${tok}`;
        }
    }
    catch {
        /* ignore storage errors */
    }
    return h;
}
/** Fetch init used by every inventory call. ``credentials: 'include'``
 *  makes the browser attach the ``homepilot_session`` cookie so the
 *  backend's user-session fallback path (see ``require_api_key``) can
 *  authenticate even when a bearer token isn't held in localStorage
 *  (e.g. SSR-style browser session). */
const WITH_CREDS = { credentials: 'include' };
// ---------------------------------------------------------------------------
// API calls
// ---------------------------------------------------------------------------
export async function fetchInventoryCategories(backendUrl, projectId, opts) {
    const params = new URLSearchParams({
        include_counts: 'true',
        include_tags: opts?.includeTags ? 'true' : 'false',
        sensitivity_max: opts?.sensitivityMax || 'safe',
    });
    const res = await fetch(`${backendUrl}/v1/inventory/${projectId}/categories?${params}`, { headers: authHeaders(opts?.apiKey), ...WITH_CREDS });
    if (!res.ok)
        throw new Error(`Inventory categories failed: ${res.status}`);
    return res.json();
}
export async function searchInventory(backendUrl, projectId, opts) {
    const params = new URLSearchParams({
        sensitivity_max: opts?.sensitivityMax || 'safe',
    });
    if (opts?.query)
        params.set('query', opts.query);
    if (opts?.types && opts.types.length > 0)
        params.set('types', opts.types.join(','));
    if (opts?.limit)
        params.set('limit', String(opts.limit));
    if (opts?.countOnly)
        params.set('count_only', 'true');
    const res = await fetch(`${backendUrl}/v1/inventory/${projectId}/search?${params}`, { headers: authHeaders(opts?.apiKey), ...WITH_CREDS });
    if (!res.ok)
        throw new Error(`Inventory search failed: ${res.status}`);
    return res.json();
}
export async function getInventoryItem(backendUrl, projectId, itemId, opts) {
    const params = new URLSearchParams({
        sensitivity_max: opts?.sensitivityMax || 'safe',
    });
    const res = await fetch(`${backendUrl}/v1/inventory/${projectId}/items/${encodeURIComponent(itemId)}?${params}`, { headers: authHeaders(opts?.apiKey), ...WITH_CREDS });
    if (!res.ok)
        throw new Error(`Inventory get failed: ${res.status}`);
    return res.json();
}
export async function resolveInventoryMedia(backendUrl, projectId, assetId, opts) {
    const res = await fetch(`${backendUrl}/v1/inventory/resolve`, {
        method: 'POST',
        headers: authHeaders(opts?.apiKey),
        ...WITH_CREDS,
        body: JSON.stringify({
            project_id: projectId,
            asset_id: assetId,
            sensitivity_max: opts?.sensitivityMax || 'safe',
        }),
    });
    if (!res.ok)
        throw new Error(`Inventory resolve failed: ${res.status}`);
    return res.json();
}
export async function resolvePersonaOutfitView(backendUrl, projectId, opts) {
    const res = await fetch(`${backendUrl}/v1/inventory/${projectId}/persona/outfit-view`, {
        method: 'POST',
        headers: authHeaders(opts.apiKey),
        ...WITH_CREDS,
        body: JSON.stringify({
            target: opts.target || 'current_outfit',
            angle: opts.angle,
            sensitivity_max: opts.sensitivityMax || 'safe',
        }),
    });
    if (!res.ok)
        throw new Error(`Resolve persona outfit view failed: ${res.status}`);
    return res.json();
}
export async function saveViewPackToOutfit(backendUrl, opts) {
    const res = await fetch(`${backendUrl}/v1/viewpack/save-to-outfit`, {
        method: 'POST',
        headers: authHeaders(opts.apiKey),
        ...WITH_CREDS,
        body: JSON.stringify({
            project_id: opts.projectId,
            outfit_id: opts.outfitId,
            view_pack: opts.viewPack,
            equipped: opts.equipped,
        }),
    });
    if (!res.ok)
        throw new Error(`Save view pack to outfit failed: ${res.status}`);
    return res.json();
}
export async function deleteInventoryItem(backendUrl, projectId, itemId, opts) {
    const res = await fetch(`${backendUrl}/v1/inventory/${projectId}/items/${encodeURIComponent(itemId)}`, { method: 'DELETE', headers: authHeaders(opts?.apiKey), ...WITH_CREDS });
    if (!res.ok)
        throw new Error(`Inventory delete failed: ${res.status}`);
    return res.json();
}
export async function listPersonaDocuments(backendUrl, projectId, opts) {
    const res = await fetch(`${backendUrl}/projects/${projectId}/persona/documents`, { headers: authHeaders(opts?.apiKey), ...WITH_CREDS });
    if (!res.ok)
        throw new Error(`List persona documents failed: ${res.status}`);
    return res.json();
}
export async function attachPersonaDocument(backendUrl, projectId, itemId, mode = 'indexed', opts) {
    const res = await fetch(`${backendUrl}/projects/${projectId}/persona/documents/attach`, {
        method: 'POST',
        headers: authHeaders(opts?.apiKey),
        ...WITH_CREDS,
        body: JSON.stringify({ item_id: itemId, mode }),
    });
    if (!res.ok)
        throw new Error(`Attach document failed: ${res.status}`);
    return res.json();
}
export async function setPersonaDocumentMode(backendUrl, projectId, itemId, mode, opts) {
    const res = await fetch(`${backendUrl}/projects/${projectId}/persona/documents/mode`, {
        method: 'POST',
        headers: authHeaders(opts?.apiKey),
        ...WITH_CREDS,
        body: JSON.stringify({ item_id: itemId, mode }),
    });
    if (!res.ok)
        throw new Error(`Set document mode failed: ${res.status}`);
    return res.json();
}
export async function detachPersonaDocument(backendUrl, projectId, itemId, opts) {
    const res = await fetch(`${backendUrl}/projects/${projectId}/persona/documents/${encodeURIComponent(itemId)}`, { method: 'DELETE', headers: authHeaders(opts?.apiKey), ...WITH_CREDS });
    if (!res.ok)
        throw new Error(`Detach document failed: ${res.status}`);
    return res.json();
}
export async function deletePersonaDocumentPermanently(backendUrl, projectId, itemId, opts) {
    const res = await fetch(`${backendUrl}/projects/${projectId}/persona/documents/${encodeURIComponent(itemId)}/permanent`, { method: 'DELETE', headers: authHeaders(opts?.apiKey), ...WITH_CREDS });
    if (!res.ok)
        throw new Error(`Delete document permanently failed: ${res.status}`);
    return res.json();
}
export async function uploadProjectItem(backendUrl, projectId, file, opts) {
    const form = new FormData();
    form.append('file', file);
    if (opts?.name)
        form.append('name', opts.name);
    if (opts?.description)
        form.append('description', opts.description);
    if (opts?.category)
        form.append('category', opts.category || 'file');
    if (opts?.tags)
        form.append('tags', opts.tags);
    const headers = {};
    if (opts?.apiKey)
        headers['x-api-key'] = opts.apiKey;
    const tok = (() => { try {
        return localStorage.getItem('homepilot_auth_token') || '';
    }
    catch {
        return '';
    } })();
    if (tok)
        headers['authorization'] = `Bearer ${tok}`;
    const res = await fetch(`${backendUrl}/projects/${projectId}/items/upload`, { method: 'POST', headers, body: form, ...WITH_CREDS });
    if (!res.ok)
        throw new Error(`Upload failed: ${res.status}`);
    return res.json();
}
