/**
 * Persona API client — Phase 2
 *
 * Uses the real /chat endpoint (mode:"imagine") for image generation
 * and /projects for project creation. Now includes:
 *   - Seed tracking for reproducibility
 *   - Outfit variation generation
 *   - Agentic data in project creation
 *
 * Image URLs are stored as-is (full ComfyUI view URLs) — same pattern
 * as Imagine.tsx — no filename extraction needed.
 */
function authHeaders(apiKey) {
    const h = { 'Content-Type': 'application/json' };
    if (apiKey && apiKey.trim().length > 0)
        h['x-api-key'] = apiKey;
    // Additive: logged-in user session — Bearer JWT from localStorage.
    try {
        if (typeof window !== 'undefined') {
            const tok = window.localStorage.getItem('homepilot_auth_token') || '';
            if (tok)
                h['authorization'] = `Bearer ${tok}`;
        }
    }
    catch { /* ignore */ }
    return h;
}
/**
 * Generate persona avatar images using the existing /chat imagine pipeline.
 * Returns full image URLs, the final prompt, model, and seeds for reproducibility.
 */
export async function generatePersonaImages(params) {
    const body = {
        message: `imagine ${params.prompt}`,
        mode: 'imagine',
        provider: params.provider ?? 'ollama',
        imgModel: params.imgModel ?? 'dreamshaper_8.safetensors',
        imgBatchSize: params.imgBatchSize ?? 4,
        imgAspectRatio: params.imgAspectRatio ?? '2:3',
        imgPreset: params.imgPreset ?? 'med',
        promptRefinement: params.promptRefinement ?? true,
        nsfwMode: params.nsfwMode ?? false,
    };
    // Identity-preserving mode: pass generation_mode + reference image to backend
    if (params.generationMode === 'identity') {
        body.generation_mode = 'identity';
        if (params.referenceImageUrl)
            body.reference_image_url = params.referenceImageUrl;
    }
    const res = await fetch(`${params.backendUrl}/chat`, {
        method: 'POST',
        headers: authHeaders(params.apiKey),
        credentials: 'include',
        body: JSON.stringify(body),
    });
    if (!res.ok)
        throw new Error(`Image generation failed: ${res.status}`);
    const data = (await res.json());
    return {
        urls: data.media?.images ?? [],
        final_prompt: data.media?.final_prompt,
        model: data.media?.model,
        seeds: data.media?.seeds,
    };
}
/**
 * Create a new project with project_type:"persona" and embedded persona data.
 * Now also supports agentic data (goal, capabilities) from the wizard.
 */
export async function createPersonaProject(params) {
    const payload = {
        name: params.name,
        description: params.description ?? '',
        project_type: 'persona',
        persona_agent: params.persona_agent,
        persona_appearance: params.persona_appearance,
    };
    if (params.agentic)
        payload.agentic = params.agentic;
    const res = await fetch(`${params.backendUrl}/projects`, {
        method: 'POST',
        headers: authHeaders(params.apiKey),
        credentials: 'include',
        body: JSON.stringify(payload),
    });
    if (!res.ok)
        throw new Error(`Create persona project failed: ${res.status}`);
    return await res.json();
}
/**
 * Generate an outfit variation for an existing persona.
 * Uses the stored character_prompt + a new outfit_prompt to generate
 * images that maintain the same character appearance.
 */
/**
 * Commit newly generated images to durable project storage immediately.
 *
 * Called right after generation so photos appear in inventory and chat
 * without waiting for Save.  Returns updated image list with /files/ URLs.
 */
export async function commitGeneratedImages(params) {
    const body = {
        kind: params.kind,
        images: params.images,
    };
    if (params.kind === 'outfit') {
        if (params.outfitId)
            body.outfit_id = params.outfitId;
        if (params.outfitLabel)
            body.outfit_label = params.outfitLabel;
        if (params.outfitPrompt)
            body.outfit_prompt = params.outfitPrompt;
        if (params.generationSettings)
            body.generation_settings = params.generationSettings;
    }
    const res = await fetch(`${params.backendUrl}/projects/${params.projectId}/persona/appearance/commit_generated`, { method: 'POST', headers: authHeaders(params.apiKey), credentials: 'include', body: JSON.stringify(body) });
    if (!res.ok)
        throw new Error(`commit_generated failed: ${res.status}`);
    return res.json();
}
/**
 * Generate an outfit variation for an existing persona.
 * Uses the stored character_prompt + a new outfit_prompt to generate
 * images that maintain the same character appearance.
 */
export async function generateOutfitImages(params) {
    const combinedPrompt = `${params.characterPrompt}, ${params.outfitPrompt}, elegant lighting, realistic, sharp focus`;
    return generatePersonaImages({
        backendUrl: params.backendUrl,
        apiKey: params.apiKey,
        prompt: combinedPrompt,
        imgModel: params.imgModel,
        imgBatchSize: 4,
        imgAspectRatio: params.imgAspectRatio ?? '2:3',
        imgPreset: params.imgPreset ?? 'med',
        promptRefinement: true,
        nsfwMode: params.nsfwMode ?? false,
        generationMode: params.generationMode,
        referenceImageUrl: params.referenceImageUrl,
    });
}
