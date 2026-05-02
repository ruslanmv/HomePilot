/** API types and fetch helper for Machine Capacity metrics. */
export async function fetchSystemResources(backendUrl, apiKey) {
    const headers = {};
    if (apiKey)
        headers['x-api-key'] = apiKey;
    const res = await fetch(`${backendUrl}/v1/system/resources`, { headers });
    if (!res.ok)
        throw new Error(`HTTP ${res.status}`);
    return res.json();
}
