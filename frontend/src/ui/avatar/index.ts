/**
 * Avatar Studio module — additive feature for persona avatar generation.
 *
 * Provides a complete Avatar Studio view (mode === 'avatar' in App.tsx)
 * with generation modes, reference upload, and results grid.
 */

export { default as AvatarStudio } from './AvatarStudio'
export * from './types'
export * from './avatarApi'
export * from './galleryTypes'
export { useAvatarPacks } from './useAvatarPacks'
export { useGenerateAvatars } from './useGenerateAvatars'
export { useAvatarGallery } from './useAvatarGallery'
export { AvatarGallery } from './AvatarGallery'
export { useOutfitGeneration } from './useOutfitGeneration'
export { OutfitPanel } from './OutfitPanel'
export { SaveAsPersonaModal } from './SaveAsPersonaModal'
