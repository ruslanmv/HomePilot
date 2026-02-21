/**
 * Avatar Studio module — additive feature for persona avatar generation.
 *
 * Provides a complete Avatar Studio view (mode === 'avatar' in App.tsx)
 * with generation modes, reference upload, and results grid.
 */

export { default as AvatarStudio } from './AvatarStudio'
export * from './types'
export * from './avatarApi'
export { useAvatarPacks } from './useAvatarPacks'
export { useGenerateAvatars } from './useGenerateAvatars'
