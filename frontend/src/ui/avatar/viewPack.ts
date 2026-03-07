import type { AvatarResult } from './types'

export type ViewAngle = 'front' | 'left_45' | 'left' | 'right_45' | 'right' | 'back'
export type ViewSource = 'anchor' | 'latest' | 'equipped'

export interface ViewAngleOption {
  id: ViewAngle
  label: string
  shortLabel: string
  prompt: string
  icon: string
}

export const VIEW_ANGLE_OPTIONS: ViewAngleOption[] = [
  {
    id: 'front',
    label: 'Front',
    shortLabel: 'F',
    prompt: 'front view, camera centered, standing naturally, same person, same outfit, same hairstyle, same body proportions',
    icon: '\u25C9',
  },
  {
    id: 'left_45',
    label: '45\u00B0 Left',
    shortLabel: 'L45',
    prompt: 'left three-quarter view, rotated 45 degrees to the left, same person, same outfit, same hairstyle, same body proportions',
    icon: '\u25D6',
  },
  {
    id: 'left',
    label: 'Left',
    shortLabel: 'L',
    prompt: 'left side profile, rotated 90 degrees to the left, same person, same outfit, same hairstyle, same body proportions',
    icon: '\u25D0',
  },
  {
    id: 'right_45',
    label: '45\u00B0 Right',
    shortLabel: 'R45',
    prompt: 'right three-quarter view, rotated 45 degrees to the right, same person, same outfit, same hairstyle, same body proportions',
    icon: '\u25D7',
  },
  {
    id: 'right',
    label: 'Right',
    shortLabel: 'R',
    prompt: 'right side profile, rotated 90 degrees to the right, same person, same outfit, same hairstyle, same body proportions',
    icon: '\u25D1',
  },
  {
    id: 'back',
    label: 'Back',
    shortLabel: 'B',
    prompt: 'back view, turned away from camera, same outfit colors and silhouette, same hairstyle length and color, same body proportions',
    icon: '\u25CE',
  },
]

export type ViewResultMap = Partial<Record<ViewAngle, AvatarResult>>
export type ViewPreviewMap = Partial<Record<ViewAngle, string>>

export function getViewAngleOption(angle: ViewAngle): ViewAngleOption {
  return VIEW_ANGLE_OPTIONS.find((item) => item.id === angle) ?? VIEW_ANGLE_OPTIONS[0]
}

export function extractViewAngle(metadata?: Record<string, unknown> | null): ViewAngle | null {
  const value = metadata?.view_angle
  if (typeof value !== 'string') return null
  return VIEW_ANGLE_OPTIONS.some((item) => item.id === value) ? (value as ViewAngle) : null
}
