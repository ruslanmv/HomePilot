/**
 * Linking Hugging Face has to change what the Models tab opens.
 * A Space whose settings already say Hugging Face was still dropped onto the
 * ComfyUI installer for images, video, and vision, so the account never appeared.
 */
import { describe, expect, it } from 'vitest'
import { huggingFaceListType, isComfyOnlyType, modelsProviderFor } from '../ui/lib/modelsProvider'

const linked = {
  providerChat: 'huggingface',
  providerMultimodal: 'huggingface',
  providerImages: 'huggingface',
  providerVideo: 'huggingface',
}

describe('Models tab follows the linked Hugging Face account', () => {
  it('opens Hugging Face for chat, vision, images, video, and edits', () => {
    for (const type of ['chat', 'multimodal', 'image', 'video', 'edit'] as const) {
      expect(modelsProviderFor(type, linked)).toBe('huggingface')
    }
  })

  it('keeps upscale, LoRA, and add-ons on ComfyUI', () => {
    for (const type of ['enhance', 'addons', 'lora'] as const) {
      expect(modelsProviderFor(type, linked)).toBe('comfyui')
      expect(isComfyOnlyType(type)).toBe(true)
      expect(huggingFaceListType(type)).toBeNull()
    }
  })

  it('edits are chosen from the image list', () => {
    expect(huggingFaceListType('edit')).toBe('image')
  })

  it('a local install without Hugging Face still opens Ollama and ComfyUI', () => {
    expect(modelsProviderFor('chat', {})).toBe('ollama')
    expect(modelsProviderFor('multimodal', { providerChat: 'ollama' })).toBe('ollama')
    expect(modelsProviderFor('image', { providerImages: 'comfyui' })).toBe('comfyui')
    expect(modelsProviderFor('video', {})).toBe('comfyui')
  })
})
