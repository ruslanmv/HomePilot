/** API types and fetch helper for the System Status dashboard. */
export async function fetchSystemOverview(backendUrl, apiKey) {
    const headers = {};
    if (apiKey)
        headers['x-api-key'] = apiKey;
    const res = await fetch(`${backendUrl}/v1/system/overview`, { headers });
    if (!res.ok)
        throw new Error(`HTTP ${res.status}`);
    return res.json();
}
