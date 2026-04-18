/**
 * phone/icons.tsx — shared SVG icon set for the call surface.
 *
 * We can't use lucide-react directly for a few of these because the
 * design spec in ``Phone Call UI.html`` bakes in a specific stroke
 * weight (1.6–1.8) + line-cap geometry that differs from lucide's
 * defaults. Keeping them in one file lets design tweaks land in a
 * single diff instead of sprinkled across component JSX.
 *
 * All icons accept ``size`` + ``color`` props so they inherit the
 * parent context cleanly. Defaults tuned for the 30–40 px avatar
 * chips typical across the phone surface.
 */

import React from 'react'

interface IconProps {
  size?: number
  color?: string
  title?: string
  strokeWidth?: number
}

const base = (
  size: number,
  color: string,
  strokeWidth: number,
  title: string | undefined,
  children: React.ReactNode,
) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke={color}
    strokeWidth={strokeWidth}
    strokeLinecap="round"
    strokeLinejoin="round"
    role={title ? 'img' : 'presentation'}
    aria-hidden={title ? undefined : 'true'}
    aria-label={title}
  >
    {title ? <title>{title}</title> : null}
    {children}
  </svg>
)

export const IconMic: React.FC<IconProps> = ({
  size = 22, color = 'currentColor', strokeWidth = 1.6, title,
}) => base(size, color, strokeWidth, title, (
  <>
    <rect x="9" y="3" width="6" height="12" rx="3" />
    <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
  </>
))

export const IconMicOff: React.FC<IconProps> = ({
  size = 22, color = 'currentColor', strokeWidth = 1.6, title,
}) => base(size, color, strokeWidth, title, (
  <>
    <path d="M9 9V6a3 3 0 0 1 6 0v5m0 4a3 3 0 0 1-6 0" />
    <path d="M5 11a7 7 0 0 0 11.5 5.3M19 11a7 7 0 0 1-.4 2.3M12 18v3" />
    <path d="M3 3l18 18" />
  </>
))

export const IconPhone: React.FC<IconProps> = ({
  size = 22, color = 'currentColor', strokeWidth = 1.6, title,
}) => base(size, color, strokeWidth, title, (
  <path d="M5 4h3l2 5-2.5 1.5a11 11 0 0 0 6 6L15 14l5 2v3a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z" />
))

export const IconPhoneEnd: React.FC<IconProps> = ({
  size = 22, color = 'currentColor', strokeWidth = 1.8, title,
}) => base(size, color, strokeWidth, title, (
  <path
    d="M4 14c5-5 11-5 16 0l-2 2-3-1v-2a9 9 0 0 0-6 0v2l-3 1-2-2z"
    transform="rotate(135 12 12)"
  />
))

/** Phone with a superimposed slash — used by the missed-call card
 *  so the missed variant reads differently from a normal call event
 *  even at thumbnail sizes. */
export const IconPhoneMissed: React.FC<IconProps> = ({
  size = 22, color = 'currentColor', strokeWidth = 1.8, title,
}) => base(size, color, strokeWidth, title, (
  <>
    <path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6 19.79 19.79 0 01-3.07-8.67A2 2 0 014.11 2h3a2 2 0 012 1.72 12.84 12.84 0 00.7 2.81 2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45 12.84 12.84 0 002.81.7 2 2 0 011.72 2.03z" />
    <line x1="23" y1="1" x2="17" y2="7" />
    <line x1="17" y1="1" x2="23" y2="7" />
  </>
))

export const IconChat: React.FC<IconProps> = ({
  size = 22, color = 'currentColor', strokeWidth = 1.6, title,
}) => base(size, color, strokeWidth, title, (
  <>
    <path d="M4 5h16v11H9l-5 4z" />
    <circle cx="9" cy="10.5" r="0.9" fill={color} stroke="none" />
    <circle cx="12" cy="10.5" r="0.9" fill={color} stroke="none" />
    <circle cx="15" cy="10.5" r="0.9" fill={color} stroke="none" />
  </>
))

export const IconSpeaker: React.FC<IconProps> = ({
  size = 22, color = 'currentColor', strokeWidth = 1.6, title,
}) => base(size, color, strokeWidth, title, (
  <>
    <path d="M4 9v6h4l5 4V5L8 9H4z" />
    <path d="M17 8a5 5 0 0 1 0 8M19.5 5.5a8.5 8.5 0 0 1 0 13" />
  </>
))

export const IconVideo: React.FC<IconProps> = ({
  size = 22, color = 'currentColor', strokeWidth = 1.6, title,
}) => base(size, color, strokeWidth, title, (
  <>
    <rect x="3" y="6" width="13" height="12" rx="2" />
    <path d="M16 10l5-3v10l-5-3z" />
  </>
))

export const IconBack: React.FC<IconProps> = ({
  size = 22, color = 'currentColor', strokeWidth = 1.8, title,
}) => base(size, color, strokeWidth, title, (
  <path d="M15 5l-7 7 7 7" />
))

/** Small star glyph used by the "Vesper remembers" label on the
 *  highlights variant of PostCallCard. Fill-mode rendering (rather
 *  than stroke) reads better at 9–11 px. */
export const IconSparkle: React.FC<IconProps> = ({
  size = 12, color = 'currentColor', title,
}) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill={color}
    role={title ? 'img' : 'presentation'}
    aria-hidden={title ? undefined : 'true'}
    aria-label={title}
  >
    {title ? <title>{title}</title> : null}
    <path d="M12 2l1.8 6.2L20 10l-6.2 1.8L12 18l-1.8-6.2L4 10l6.2-1.8z" />
  </svg>
)

/** Dev-only barrel for consumers that want to spread all icons into
 *  a single map (PostCallCard's Icon.phone-style call sites). */
export const PhoneIcons = {
  mic: IconMic,
  micOff: IconMicOff,
  phone: IconPhone,
  phoneEnd: IconPhoneEnd,
  phoneMissed: IconPhoneMissed,
  chat: IconChat,
  speaker: IconSpeaker,
  video: IconVideo,
  back: IconBack,
  sparkle: IconSparkle,
} as const
