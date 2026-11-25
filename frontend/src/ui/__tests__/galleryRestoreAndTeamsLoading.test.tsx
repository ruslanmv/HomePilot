import React from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { AvatarLandingPage, thumbUrl } from '../avatar/AvatarLandingPage'
import { mergeGalleries } from '../avatar/useAvatarGallery'
import { TeamsLandingPage } from '../teams/TeamsLandingPage'
import type { GalleryItem } from '../avatar/galleryTypes'

afterEach(() => cleanup())

const baseAvatarProps = {
  items: [] as GalleryItem[],
  backendUrl: 'http://b',
  onNewAvatar: () => {},
  onOpenItem: () => {},
  onDeleteItem: () => {},
}

describe('Avatar landing page', () => {
  it('shows a loading message, not the empty state, while the gallery loads', () => {
    render(<AvatarLandingPage {...baseAvatarProps} loading />)
    expect(screen.getByText('Loading your avatars…')).toBeTruthy()
    expect(screen.queryByText('Create your first avatar')).toBeNull()
  })

  it('restores avatars from this computer and reports how many', async () => {
    const restore = vi.fn(async () => 12)
    render(<AvatarLandingPage {...baseAvatarProps} onRestoreFromComputer={restore} />)
    fireEvent.click(screen.getByText('Restore avatars from this computer'))
    expect(await screen.findByText('Restored 12 avatars from this computer.')).toBeTruthy()
    expect(restore).toHaveBeenCalledOnce()
  })
})

describe('thumbUrl', () => {
  it('asks the backend for a thumbnail of ComfyUI images only', () => {
    expect(thumbUrl('/comfy/view/a.png', 'http://b')).toBe('http://b/comfy/view/a.png?thumb=384')
    expect(thumbUrl('/comfy/view/a.png?subfolder=avatar', 'http://b')).toBe('http://b/comfy/view/a.png?subfolder=avatar&thumb=384')
    expect(thumbUrl('http://x/other.png', 'http://b')).toBe('http://x/other.png')
  })
})

describe('mergeGalleries', () => {
  it('unions by id, newest first', () => {
    const a = [{ id: '1', url: '/a', mode: 'creative', createdAt: 1 }] as GalleryItem[]
    const b = [
      { id: '1', url: '/a', mode: 'creative', createdAt: 1 },
      { id: '2', url: '/b', mode: 'creative', createdAt: 5 },
    ] as GalleryItem[]
    expect(mergeGalleries(a, b).map((i) => i.id)).toEqual(['2', '1'])
  })
})

describe('Teams landing page', () => {
  const teamsProps = {
    rooms: [],
    personas: [],
    backendUrl: 'http://b',
    onNewSession: () => {},
    onOpenRoom: () => {},
    onDeleteRoom: () => {},
  }

  it('shows a loading screen while sessions load', () => {
    render(<TeamsLandingPage {...teamsProps} loading />)
    expect(screen.getByText('Loading your team sessions…')).toBeTruthy()
    expect(screen.queryByText('Create your first team session')).toBeNull()
  })

  it('shows an error with retry instead of the empty state when loading failed', () => {
    const retry = vi.fn()
    render(<TeamsLandingPage {...teamsProps} loading={false} error="HTTP 500" onRetry={retry} />)
    expect(screen.getByText('Could not load your team sessions')).toBeTruthy()
    expect(screen.queryByText('Create your first team session')).toBeNull()
    fireEvent.click(screen.getByText('Try again'))
    expect(retry).toHaveBeenCalledOnce()
  })

    it('shows the empty state once loading is done', () => {
    render(<TeamsLandingPage {...teamsProps} loading={false} />)
    expect(screen.getByText('Create your first team session')).toBeTruthy()
  })
})
