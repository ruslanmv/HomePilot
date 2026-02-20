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

type ChatResponse = {
  conversation_id?: string
  text?: string
  media?: {
    images?: string[]
    final_prompt?: string
    seeds?: number[]
    width?: number
    height?: number
    steps?: number
    cfg?: number
    model?: string
  }
}

function authHeaders(apiKey?: string): Record<string, string> {
  const h: Record<string, string> = { 'Content-Type': 'application/json' }
  if (apiKey && apiKey.trim().length > 0) h['x-api-key'] = apiKey
  return h
}

/**
 * Generate persona avatar images using the existing /chat imagine pipeline.
 * Returns full image URLs, the final prompt, model, and seeds for reproducibility.
 */
export async function generatePersonaImages(params: {
  backendUrl: string
  apiKey?: string
  prompt: string
  negativePrompt?: string
  provider?: string
  imgModel?: string
  imgBatchSize?: number
  imgAspectRatio?: string
  imgPreset?: string
  promptRefinement?: boolean
  nsfwMode?: boolean
  /** 'standard' (default) or 'identity' (face-preserving via InstantID) */
  generationMode?: 'standard' | 'identity'
  /** Reference image URL for identity mode (face to preserve) */
  referenceImageUrl?: string
}): Promise<{ urls: string[]; final_prompt?: string; model?: string; seeds?: number[] }> {
  const body: Record<string, unknown> = {
    message: `imagine ${params.prompt}`,
    mode: 'imagine',
    provider: params.provider ?? 'ollama',
    imgModel: params.imgModel ?? 'dreamshaper_8.safetensors',
    imgBatchSize: params.imgBatchSize ?? 4,
    imgAspectRatio: params.imgAspectRatio ?? '2:3',
    imgPreset: params.imgPreset ?? 'med',
    promptRefinement: params.promptRefinement ?? true,
    nsfwMode: params.nsfwMode ?? false,
  }

  // Identity-preserving mode: pass generation_mode + reference image to backend
  if (params.generationMode === 'identity') {
    body.generation_mode = 'identity'
    if (params.referenceImageUrl) body.reference_image_url = params.referenceImageUrl
  }

  const res = await fetch(`${params.backendUrl}/chat`, {
    method: 'POST',
    headers: authHeaders(params.apiKey),
    body: JSON.stringify(body),
  })

  if (!res.ok) throw new Error(`Image generation failed: ${res.status}`)
  const data = (await res.json()) as ChatResponse

  return {
    urls: data.media?.images ?? [],
    final_prompt: data.media?.final_prompt,
    model: data.media?.model,
    seeds: data.media?.seeds,
  }
}

/**
 * Create a new project with project_type:"persona" and embedded persona data.
 * Now also supports agentic data (goal, capabilities) from the wizard.
 */
export async function createPersonaProject(params: {
  backendUrl: string
  apiKey?: string
  name: string
  description?: string
  persona_agent: Record<string, unknown>
  persona_appearance: Record<string, unknown>
  agentic?: Record<string, unknown>
}): Promise<{ project: Record<string, unknown> }> {
  const payload: Record<string, unknown> = {
    name: params.name,
    description: params.description ?? '',
    project_type: 'persona',
    persona_agent: params.persona_agent,
    persona_appearance: params.persona_appearance,
  }
  if (params.agentic) payload.agentic = params.agentic

  const res = await fetch(`${params.backendUrl}/projects`, {
    method: 'POST',
    headers: authHeaders(params.apiKey),
    body: JSON.stringify(payload),
  })

  if (!res.ok) throw new Error(`Create persona project failed: ${res.status}`)
  return await res.json()
}

/**
 * Generate an outfit variation for an existing persona.
 * Uses the stored character_prompt + a new outfit_prompt to generate
 * images that maintain the same character appearance.
 */
export async function generateOutfitImages(params: {
  backendUrl: string
  apiKey?: string
  characterPrompt: string
  outfitPrompt: string
  imgModel?: string
  imgPreset?: string
  imgAspectRatio?: string
  nsfwMode?: boolean
  /** 'standard' (default) or 'identity' (face-preserving via InstantID) */
  generationMode?: 'standard' | 'identity'
  /** Reference image URL for identity mode (face to preserve) */
  referenceImageUrl?: string
}): Promise<{ urls: string[]; final_prompt?: string; model?: string; seeds?: number[] }> {
  const combinedPrompt = `${params.characterPrompt}, ${params.outfitPrompt}, elegant lighting, realistic, sharp focus`

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
  })
}
