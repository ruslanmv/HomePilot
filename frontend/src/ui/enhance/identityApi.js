/**
 * identityApi - API client for identity-aware edit operations.
 *
 * These operations use Avatar & Identity models (InsightFace + InstantID)
 * to perform edits that preserve facial identity.
 *
 * This is additive — existing enhance/edit endpoints are unchanged.
 */
// ---------------------------------------------------------------------------
// Tool definitions (for UI rendering)
// ---------------------------------------------------------------------------
export const IDENTITY_TOOLS = [
    {
        id: 'fix_faces_identity',
        label: 'Fix Faces+',
        description: 'Fix faces while preserving identity',
        pack: 'basic',
    },
    {
        id: 'inpaint_identity',
        label: 'Inpaint (Preserve Person)',
        description: 'Edit regions while keeping the face consistent',
        pack: 'basic',
    },
    {
        id: 'change_bg_identity',
        label: 'Change BG (Preserve Person)',
        description: 'Replace background while keeping the same person',
        pack: 'basic',
    },
    {
        id: 'face_swap',
        label: 'Face Swap',
        description: 'Transfer identity onto generated or existing images',
        pack: 'full',
    },
];
// ---------------------------------------------------------------------------
// API call
// ---------------------------------------------------------------------------
export async function applyIdentityTool(params) {
    const base = params.backendUrl.replace(/\/+$/, '');
    const body = {
        image_url: params.imageUrl,
        tool_type: params.toolType,
    };
    if (params.referenceImageUrl)
        body.reference_image_url = params.referenceImageUrl;
    if (params.maskDataUrl)
        body.mask_data_url = params.maskDataUrl;
    if (params.prompt)
        body.prompt = params.prompt;
    const headers = {
        'Content-Type': 'application/json',
    };
    if (params.apiKey)
        headers['X-API-Key'] = params.apiKey;
    const response = await fetch(`${base}/v1/edit/identity`, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
    });
    if (!response.ok) {
        const text = await response.text().catch(() => '');
        throw new Error(`Identity tool failed: ${response.status} ${text}`);
    }
    return response.json();
}
