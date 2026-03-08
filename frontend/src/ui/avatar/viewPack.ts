import type { AvatarResult } from './types'

export type ViewAngle = 'front' | 'left' | 'right' | 'back'
export type ViewSource = 'anchor' | 'latest' | 'equipped'

export interface ViewAngleOption {
  id: ViewAngle
  label: string
  shortLabel: string
  prompt: string
  /** Negative prompt tokens to prevent the reference pose from dominating. */
  negativePrompt: string
  icon: string
  /** Denoise override — higher values let the text prompt control pose.
   *  Front uses default (0.85), non-front uses 1.0 for full prompt control. */
  denoise: number
  /** When true, use 'standard' generation mode instead of 'identity' to avoid
   *  face preservation fighting the desired pose (e.g. back view). */
  skipIdentity?: boolean
}

export const VIEW_ANGLE_OPTIONS: ViewAngleOption[] = [
  {
    id: 'front',
    label: 'Front',
    shortLabel: 'F',
    prompt: 'front view, facing the camera directly, centered composition, standing naturally, full body visible from head to thighs, same person, same outfit, same hairstyle, same body proportions',
    negativePrompt: '',
    icon: '\u25C9',
    denoise: 0.85,
  },
  {
    id: 'left',
    label: 'Left',
    shortLabel: 'L',
    prompt: 'character turntable reference sheet, full left profile view, camera positioned directly to the right of the subject, head and body turned 90 degrees to the left, only left side of face visible showing left ear left cheekbone jaw line and nose tip in profile silhouette, left shoulder directly facing camera, full body profile silhouette visible showing bust contour waist curve hip shape and thigh line from the side, outfit visible in profile showing how garment fits along the body silhouette, full body visible from head to thighs, identical person same outfit same skin tone same body proportions, consistent lighting',
    negativePrompt: 'front view, facing camera, looking at camera, frontal, both eyes visible, symmetrical face, three-quarter view, 45 degree angle, right side visible, back view, rear view',
    icon: '\u25D0',
    denoise: 1.0,
  },
  {
    id: 'right',
    label: 'Right',
    shortLabel: 'R',
    prompt: 'character turntable reference sheet, full right profile view, camera positioned directly to the left of the subject, head and body turned 90 degrees to the right, only right side of face visible showing right ear right cheekbone jaw line and nose tip in profile silhouette, right shoulder directly facing camera, full body profile silhouette visible showing bust contour waist curve hip shape and thigh line from the side, outfit visible in profile showing how garment fits along the body silhouette, full body visible from head to thighs, identical person same outfit same skin tone same body proportions, consistent lighting',
    negativePrompt: 'front view, facing camera, looking at camera, frontal, both eyes visible, symmetrical face, three-quarter view, 45 degree angle, left side visible, back view, rear view',
    icon: '\u25D1',
    denoise: 1.0,
  },
  {
    id: 'back',
    label: 'Back',
    shortLabel: 'B',
    prompt: 'character turntable reference sheet, rear view from directly behind, camera positioned behind the subject, person facing completely away from camera, back of head visible showing hair from behind, full back of body visible showing shoulders and upper back and lower back and waist and hips and buttocks and upper thighs from behind, outfit visible from behind showing the rear design of the garment how it fits across the back and hips and backside, spine centered in frame, no face visible at all, full body visible from head to thighs, identical outfit colors and design as front view, same body proportions and height, consistent lighting',
    negativePrompt: 'front view, facing camera, looking at camera, face visible, eyes visible, nose visible, mouth visible, front of body, frontal pose, turning head, looking over shoulder, three-quarter view, profile view, side view',
    icon: '\u25CE',
    denoise: 1.0,
    skipIdentity: true,
  },
]

export type ViewResultMap = Partial<Record<ViewAngle, AvatarResult>>
export type ViewPreviewMap = Partial<Record<ViewAngle, string>>
/** Unix timestamps (Date.now()) for when each angle was generated/cached. */
export type ViewTimestampMap = Partial<Record<ViewAngle, number>>

export function getViewAngleOption(angle: ViewAngle): ViewAngleOption {
  return VIEW_ANGLE_OPTIONS.find((item) => item.id === angle) ?? VIEW_ANGLE_OPTIONS[0]
}

export function extractViewAngle(metadata?: Record<string, unknown> | null): ViewAngle | null {
  const value = metadata?.view_angle
  if (typeof value !== 'string') return null
  return VIEW_ANGLE_OPTIONS.some((item) => item.id === value) ? (value as ViewAngle) : null
}
