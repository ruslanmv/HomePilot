/**
 * Avatar Studio — API client functions.
 */
export async function fetchAvatarPacks(backendUrl, apiKey) {
    const base = (backendUrl || '').replace(/\/+$/, '');
    const headers = {};
    if (apiKey)
        headers['x-api-key'] = apiKey;
    const res = await fetch(`${base}/v1/avatars/packs`, { headers });
    if (!res.ok)
        throw new Error(await res.text());
    return res.json();
}
export async function installAvatarPack(backendUrl, packId, apiKey) {
    const base = (backendUrl || '').replace(/\/+$/, '');
    const headers = { 'Content-Type': 'application/json' };
    if (apiKey)
        headers['x-api-key'] = apiKey;
    const res = await fetch(`${base}/v1/avatars/packs/install`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ pack_id: packId }),
    });
    if (!res.ok)
        throw new Error(await res.text());
    return res.json();
}
/**
 * Fetch engine capabilities (ComfyUI, StyleGAN availability).
 * Additive — does not affect existing API functions.
 */
export async function fetchAvatarCapabilities(backendUrl, apiKey) {
    const base = (backendUrl || '').replace(/\/+$/, '');
    const headers = {};
    if (apiKey)
        headers['x-api-key'] = apiKey;
    const res = await fetch(`${base}/v1/avatars/capabilities`, { headers });
    if (!res.ok)
        throw new Error(await res.text());
    return res.json();
}
export async function generateAvatars(backendUrl, body, apiKey, signal) {
    const base = (backendUrl || '').replace(/\/+$/, '');
    const headers = {
        'Content-Type': 'application/json',
    };
    if (apiKey)
        headers['x-api-key'] = apiKey;
    const res = await fetch(`${base}/v1/avatars/generate`, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
        signal,
    });
    if (!res.ok)
        throw new Error(await res.text());
    return res.json();
}
/**
 * Generate full-body images from a face reference via the hybrid pipeline.
 * Uses ComfyUI with identity preservation (InstantID/PhotoMaker).
 */
export async function generateHybridFullBody(backendUrl, body, apiKey, signal) {
    const base = (backendUrl || '').replace(/\/+$/, '');
    const headers = {
        'Content-Type': 'application/json',
    };
    if (apiKey)
        headers['x-api-key'] = apiKey;
    const res = await fetch(`${base}/v1/avatars/hybrid/fullbody`, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
        signal,
    });
    if (!res.ok)
        throw new Error(await res.text());
    return res.json();
}
