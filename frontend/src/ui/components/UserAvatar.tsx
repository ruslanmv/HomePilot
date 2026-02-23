/**
 * UserAvatar — displays a user's avatar image or a generated initials fallback.
 *
 * Usage:
 *   <UserAvatar displayName="Alice" avatarUrl="/files/avatar_xxx.png" size={40} />
 *   <UserAvatar displayName="Bob" size={32} />  // shows initials "B"
 *
 * ADDITIVE ONLY — new component, does not modify existing code.
 */
import React, { useState } from 'react'

interface UserAvatarProps {
  displayName: string
  avatarUrl?: string
  size?: number
  onClick?: () => void
  style?: React.CSSProperties
}

/** Deterministic color from a string (name-based, visually distinct). */
function nameToColor(name: string): string {
  const colors = [
    '#3b82f6', '#8b5cf6', '#ec4899', '#06b6d4', '#f59e0b',
    '#10b981', '#ef4444', '#6366f1', '#14b8a6', '#f97316',
  ]
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash)
  }
  return colors[Math.abs(hash) % colors.length]
}

function getInitials(name: string): string {
  const parts = (name || '').trim().split(/\s+/)
  if (parts.length >= 2) {
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
  }
  return (name || '?')[0].toUpperCase()
}

export default function UserAvatar({
  displayName,
  avatarUrl,
  size = 40,
  onClick,
  style,
}: UserAvatarProps) {
  const [imgError, setImgError] = useState(false)
  const hasImage = avatarUrl && !imgError

  const baseStyle: React.CSSProperties = {
    width: size,
    height: size,
    borderRadius: '50%',
    overflow: 'hidden',
    flexShrink: 0,
    cursor: onClick ? 'pointer' : 'default',
    ...style,
  }

  if (hasImage) {
    // Resolve relative URLs against the backend, append auth token for /files/ paths
    const backendUrl = localStorage.getItem('homepilot_backend_url') || 'http://localhost:8000'
    let fullUrl = avatarUrl.startsWith('http') ? avatarUrl : `${backendUrl}${avatarUrl}`
    if (fullUrl.includes('/files/')) {
      const tok = localStorage.getItem('homepilot_auth_token') || ''
      if (tok) {
        const sep = fullUrl.includes('?') ? '&' : '?'
        fullUrl = `${fullUrl}${sep}token=${encodeURIComponent(tok)}`
      }
    }

    return (
      <div style={baseStyle} onClick={onClick}>
        <img
          src={fullUrl}
          alt={displayName}
          onError={() => setImgError(true)}
          style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
        />
      </div>
    )
  }

  // Initials fallback
  const bg = nameToColor(displayName)
  return (
    <div
      style={{
        ...baseStyle,
        background: bg,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: '#fff',
        fontWeight: 700,
        fontSize: Math.round(size * 0.4),
        fontFamily: 'system-ui, sans-serif',
        userSelect: 'none',
      }}
      onClick={onClick}
    >
      {getInitials(displayName)}
    </div>
  )
}
