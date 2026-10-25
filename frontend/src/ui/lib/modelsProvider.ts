/**
 * Which provider the Models tab opens for a model type.
 *
 * On the hosted Space, Settings already point chat, vision, images, and video at
 * Hugging Face. The Models tab used to ignore that and open ComfyUI's installer,
 * so linking an account never showed the models that account can run.
 * Upscale, LoRA, and add-ons have no Hugging Face list: they install into ComfyUI.
 */

export type ModelsTabType =
  | 'chat'
  | 'multimodal'
  | 'image'
  | 'video'
  | 'edit'
  | 'enhance'
  | 'addons'
  | 'lora'

export type ModelsProviderSettings = {
  providerChat?: string
  providerImages?: string
  providerVideo?: string
  providerMultimodal?: string
}

const COMFY_ONLY: ModelsTabType[] = ['enhance', 'addons', 'lora']

export function modelsProviderFor(type: ModelsTabType, settings: ModelsProviderSettings): string {
  if (type === 'chat') return settings.providerChat || 'ollama'
  if (type === 'multimodal') {
    const chosen = settings.providerMultimodal || settings.providerChat
    return chosen === 'huggingface' ? 'huggingface' : 'ollama'
  }
  if (type === 'image' || type === 'edit') {
    return settings.providerImages === 'huggingface' ? 'huggingface' : 'comfyui'
  }
  if (type === 'video') {
    return settings.providerVideo === 'huggingface' ? 'huggingface' : 'comfyui'
  }
  return 'comfyui'
}

/** Image-to-image edits are picked from the image list. The other Comfy-only types are not. */
export function huggingFaceListType(type: ModelsTabType): 'chat' | 'multimodal' | 'image' | 'video' | null {
  if (type === 'edit') return 'image'
  if (type === 'chat' || type === 'multimodal' || type === 'image' || type === 'video') return type
  return null
}

export function isComfyOnlyType(type: ModelsTabType): boolean {
  return COMFY_ONLY.includes(type)
}
