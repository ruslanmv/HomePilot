/**
 * AvatarUploader — avatar upload/remove control for the ProfileSettingsModal.
 *
 * Shows current avatar (or initials fallback) with "Upload" and "Remove" actions.
 * Uses the PUT /v1/auth/avatar and DELETE /v1/auth/avatar endpoints.
 *
 * ADDITIVE ONLY — new component, does not modify existing code.
 */
import React, { useRef, useState } from 'react'
import UserAvatar from './UserAvatar'
import { uploadAvatar, deleteAvatar } from '../profileApi'
import { Camera, Trash2 } from 'lucide-react'

interface AvatarUploaderProps {
  backendUrl: string
  token: string
  displayName: string
  avatarUrl: string
  onAvatarChange: (newUrl: string) => void
}

export default function AvatarUploader({
  backendUrl,
  token,
  displayName,
  avatarUrl,
  onAvatarChange,
}: AvatarUploaderProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setError('')
    setUploading(true)
    try {
      const url = await uploadAvatar(backendUrl, token, file)
      onAvatarChange(url)
    } catch (err: any) {
      setError(err?.message || 'Upload failed')
    }
    setUploading(false)
    // Reset input so the same file can be re-selected
    if (inputRef.current) inputRef.current.value = ''
  }

  async function handleRemove() {
    setError('')
    try {
      await deleteAvatar(backendUrl, token)
      onAvatarChange('')
    } catch (err: any) {
      setError(err?.message || 'Remove failed')
    }
  }

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 20 }}>
      <UserAvatar
        displayName={displayName || 'User'}
        avatarUrl={avatarUrl}
        size={64}
      />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={() => inputRef.current?.click()}
            disabled={uploading}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 5,
              padding: '6px 12px',
              borderRadius: 8,
              border: '1px solid rgba(148, 163, 184, 0.2)',
              background: 'rgba(59, 130, 246, 0.1)',
              color: '#93c5fd',
              fontSize: 12,
              fontWeight: 500,
              cursor: uploading ? 'wait' : 'pointer',
            }}
          >
            <Camera size={13} />
            {uploading ? 'Uploading...' : 'Upload photo'}
          </button>
          {avatarUrl && (
            <button
              onClick={handleRemove}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 5,
                padding: '6px 12px',
                borderRadius: 8,
                border: '1px solid rgba(148, 163, 184, 0.15)',
                background: 'transparent',
                color: '#94a3b8',
                fontSize: 12,
                fontWeight: 500,
                cursor: 'pointer',
              }}
            >
              <Trash2 size={13} />
              Remove
            </button>
          )}
        </div>
        {error && <span style={{ color: '#ef4444', fontSize: 11 }}>{error}</span>}
        <span style={{ color: '#475569', fontSize: 11 }}>PNG, JPG, or WebP. Max 5MB.</span>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept=".png,.jpg,.jpeg,.webp"
        onChange={handleFileChange}
        style={{ display: 'none' }}
      />
    </div>
  )
}
