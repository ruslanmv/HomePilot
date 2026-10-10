/**
 * Edit Profile Picture: the user frames the persona's picture; the framing is
 * saved to the persona, shown at once, and can be refined later.
 *
 * The cropper itself (react-easy-crop) needs real image loading, which jsdom
 * does not do, so it is replaced here by a stand-in that reports the same
 * events: the picture loaded, the framing changed. Everything around it — what
 * is sent, when changes count as unsaved, what Cancel and a failed save do —
 * is the real editor.
 */
import React from 'react'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('react-easy-crop', () => ({
  default: function FakeCropper(props: any) {
    React.useEffect(() => {
      props.onMediaLoaded?.({ width: 400, height: 600, naturalWidth: 800, naturalHeight: 1200 })
      const a = props.initialCroppedAreaPercentages || { x: 0, y: 16.67, width: 100, height: 66.67 }
      props.onCropComplete?.(a, a)
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])
    return (
      <div data-testid="fake-cropper" data-image={props.image} data-zoom={props.zoom} data-shape={props.cropShape} data-aspect={props.aspect}>
        <button type="button" onClick={() => { props.onCropChange({ x: 40, y: -20 }); props.onCropComplete?.({ x: 20, y: 5, width: 50, height: 33.3 }, {}) }}>
          drag
        </button>
      </div>
    )
  },
}))

import {
  activeAvatarCrop,
  photoProblem,
  previewStyle,
  saveAvatarCrop,
} from '../ui/avatarCrop'
import { AvatarCropEditor } from '../ui/components/AvatarCropEditor'
import { ModalSheet } from '../ui/components/ModalSheet'

afterEach(() => {
  vi.restoreAllMocks()
})

// requestAnimationFrame runs the baseline capture; make it synchronous for the tests.
vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => { cb(0); return 0 })

describe('the saved framing', () => {
  const pap = {
    selected_filename: 'projects/p/persona/appearance/avatar_a.png',
    selected_thumb_filename: 'projects/p/persona/appearance/thumb_avatar_a_crop_1.webp',
    avatar_crop: { source: 'projects/p/persona/appearance/avatar_a.png', output: 'projects/p/persona/appearance/thumb_avatar_a_crop_1.webp', area: { x: 10, y: 5, width: 50, height: 33 }, zoom: 2 },
  }

  it('is in use while it is the thumbnail the persona shows', () => {
    expect(activeAvatarCrop({ persona_appearance: pap })?.zoom).toBe(2)
  })

  it('stops being used when another picture was chosen elsewhere', () => {
    expect(activeAvatarCrop({ persona_appearance: { ...pap, selected_thumb_filename: 'thumb_avatar_b.webp' } })).toBeNull()
    expect(activeAvatarCrop({ persona_appearance: { ...pap, avatar_crop: { ...pap.avatar_crop, area: null } } })).toBeNull()
    expect(activeAvatarCrop(null)).toBeNull()
  })
})

describe('choosing a replacement photo', () => {
  it('accepts PNG, JPEG and WebP within the size limit', () => {
    expect(photoProblem({ type: 'image/jpeg', size: 2_000_000 })).toBeNull()
    expect(photoProblem({ type: 'image/gif', size: 100 })).toMatch(/PNG, JPEG or WebP/)
    expect(photoProblem({ type: 'image/png', size: 30 * 1024 * 1024 })).toMatch(/larger than 25 MB/)
    expect(photoProblem({ type: 'image/png', size: 0 })).toMatch(/empty/)
  })
})

describe('the live preview', () => {
  it('draws exactly the framed region, at any size the preview is shown', () => {
    const s = previewStyle('/p.png', { x: 25, y: 10, width: 50, height: 25 })
    expect(s.backgroundSize).toBe('200% 400%')
    // In a 100px box: a 200x400px picture moved 50px left and 40px up.
    const [px, py] = String(s.backgroundPosition).split(' ').map(parseFloat)
    expect((100 - 200) * (px / 100)).toBeCloseTo(-50, 3)
    expect((100 - 400) * (py / 100)).toBeCloseTo(-40, 3)
    // The whole picture: no offset.
    expect(previewStyle('/p.png', { x: 0, y: 0, width: 100, height: 100 }).backgroundPosition).toBe('0% 0%')
  })
})

describe('saving', () => {
  it('sends the framing (and a replacement photo) as a form, and reports the server reason on failure', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, persona_appearance: { a: 1 }, project: { updated_at: 5 } }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'Use a PNG, JPEG or WebP picture' }), { status: 400 }))
    const file = new File(['x'], 'me.png', { type: 'image/png' })
    const ok = await saveAvatarCrop({ backendUrl: 'http://hp/', projectId: 'p 1', area: { x: 1, y: 2, width: 3, height: 4 }, zoom: 1.23456, file, headers: { 'x-api-key': 'k' } })
    expect(ok).toEqual({ ok: true, project: { updated_at: 5 }, persona_appearance: { a: 1 } })
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('http://hp/projects/p%201/persona/avatar/crop')
    expect(init.method).toBe('POST')
    const fd = init.body as FormData
    expect(JSON.parse(fd.get('area') as string)).toEqual({ x: 1, y: 2, width: 3, height: 4 })
    expect(fd.get('zoom')).toBe('1.235')
    expect((fd.get('file') as File).name).toBe('me.png')
    expect(init.headers).toEqual({ 'x-api-key': 'k' })
    const bad = await saveAvatarCrop({ backendUrl: 'http://hp', projectId: 'p', area: { x: 0, y: 0, width: 1, height: 1 }, zoom: 1 })
    expect(bad).toEqual({ ok: false, error: 'Use a PNG, JPEG or WebP picture' })
  })

  it('says so when HomePilot cannot be reached', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValueOnce(new TypeError('Failed to fetch'))
    const r = await saveAvatarCrop({ backendUrl: 'http://hp', projectId: 'p', area: { x: 0, y: 0, width: 1, height: 1 }, zoom: 1 })
    expect(r.ok).toBe(false)
  })
})

function renderEditor(over: Partial<React.ComponentProps<typeof AvatarCropEditor>> = {}) {
  const onClose = vi.fn()
  const onSave = vi.fn(async () => ({ ok: true as const, project: null, persona_appearance: {} }))
  const utils = render(
    <AvatarCropEditor open name="Girlfriend" imageUrl="http://hp/files/avatar_a.png" onClose={onClose} onSave={onSave} {...over} />,
  )
  return { ...utils, onClose, onSave }
}

describe('Edit Profile Picture', () => {
  it('opens on the original picture as a round, square crop, centred, at 100%', () => {
    renderEditor()
    expect(screen.getByRole('dialog', { name: 'Edit Profile Picture' })).toBeInTheDocument()
    const c = screen.getByTestId('fake-cropper')
    expect(c.dataset.image).toBe('http://hp/files/avatar_a.png')
    expect(c.dataset.shape).toBe('round')
    expect(c.dataset.aspect).toBe('1')
    expect(screen.getByText('100%')).toBeInTheDocument()
    expect(screen.getByTestId('crop-preview').style.backgroundImage).toContain('avatar_a.png')
  })

  it('zooms with the slider and the buttons, and Reset returns to the centred picture', () => {
    renderEditor()
    fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }))
    fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }))
    expect(screen.getByText('120%')).toBeInTheDocument()
    fireEvent.change(screen.getByRole('slider', { name: 'Zoom' }), { target: { value: '2.5' } })
    expect(screen.getByText('250%')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Reset/ }))
    expect(screen.getByText('100%')).toBeInTheDocument()
  })

  it('saves the framing and the zoom, then closes', async () => {
    const { onSave, onClose } = renderEditor()
    fireEvent.click(screen.getByRole('button', { name: 'drag' }))
    fireEvent.change(screen.getByRole('slider', { name: 'Zoom' }), { target: { value: '1.8' } })
    fireEvent.click(screen.getByRole('button', { name: /Save Crop/ }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(onSave).toHaveBeenCalledWith({ area: { x: 20, y: 5, width: 50, height: 33.3 }, zoom: 1.8, file: null })
  })

  it('a failed save keeps the editor and the framing, and says why', async () => {
    const onSave = vi.fn(async () => ({ ok: false as const, error: 'Saving failed (HTTP 500).' }))
    const { onClose } = renderEditor({ onSave })
    fireEvent.change(screen.getByRole('slider', { name: 'Zoom' }), { target: { value: '2' } })
    fireEvent.click(screen.getByRole('button', { name: /Save Crop/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Saving failed (HTTP 500).')
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByText('200%')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Save Crop/ })).toBeEnabled()
  })

  it('Cancel discards changes at once; closing another way with changes asks first', () => {
    const a = renderEditor()
    fireEvent.change(screen.getByRole('slider', { name: 'Zoom' }), { target: { value: '2' } })
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(a.onClose).not.toHaveBeenCalled()
    expect(screen.getByRole('alertdialog', { name: 'Discard changes?' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }))
    expect(screen.queryByRole('alertdialog')).toBeNull()
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    fireEvent.click(screen.getByRole('button', { name: 'Discard' }))
    expect(a.onClose).toHaveBeenCalledTimes(1)
    a.unmount()

    const b = renderEditor()
    fireEvent.change(screen.getByRole('slider', { name: 'Zoom' }), { target: { value: '2' } })
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(b.onClose).toHaveBeenCalledTimes(1)
  })

  it('without changes, Escape simply closes', () => {
    const { onClose } = renderEditor()
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()
  })

  it('reopens at the saved framing, and can go back to the automatic thumbnail', async () => {
    const onRestoreAutomatic = vi.fn(async () => ({ ok: true as const, project: null, persona_appearance: {} }))
    const saved = { source: 's', output: 'o', area: { x: 30, y: 10, width: 40, height: 26.7 }, zoom: 2.5 }
    const { onClose } = renderEditor({ savedCrop: saved, onRestoreAutomatic })
    const [w, h] = screen.getByTestId('crop-preview').style.backgroundSize.split(' ').map(parseFloat)
    expect(w).toBeCloseTo(250, 3)
    expect(h).toBeCloseTo(10000 / 26.7, 3)
    fireEvent.click(screen.getByRole('button', { name: 'Use automatic thumbnail' }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(onRestoreAutomatic).toHaveBeenCalled()
  })

  it('Change photo loads a replacement into the editor and sends it with the framing', async () => {
    const created = vi.fn(() => 'blob:local-photo')
    Object.assign(URL, { createObjectURL: created, revokeObjectURL: vi.fn() })
    const { onSave } = renderEditor()
    const input = document.body.querySelector('input[type="file"]') as HTMLInputElement
    const photo = new File(['png'], 'new.png', { type: 'image/png' })
    await act(async () => { fireEvent.change(input, { target: { files: [photo] } }) })
    expect(screen.getByTestId('fake-cropper').dataset.image).toBe('blob:local-photo')
    fireEvent.click(screen.getByRole('button', { name: /Save Crop/ }))
    await waitFor(() => expect(onSave).toHaveBeenCalled())
    expect((onSave.mock.calls[0] as any)[0].file).toBe(photo)
  })

  it('refuses a file it cannot use, and keeps the current picture', async () => {
    renderEditor()
    const input = document.body.querySelector('input[type="file"]') as HTMLInputElement
    await act(async () => { fireEvent.change(input, { target: { files: [new File(['x'], 'a.gif', { type: 'image/gif' })] } }) })
    expect(screen.getByRole('alert')).toHaveTextContent('Choose a PNG, JPEG or WebP picture.')
    expect(screen.getByTestId('fake-cropper').dataset.image).toBe('http://hp/files/avatar_a.png')
  })

  it('without a picture it offers to choose one', () => {
    renderEditor({ imageUrl: null })
    expect(screen.getByText('This persona has no picture yet.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Choose a photo/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Save Crop/ })).toBeDisabled()
  })

  it('opened over another dialog, it owns Escape and keeps focus inside', () => {
    const sheetClose = vi.fn()
    const onClose = vi.fn()
    render(
      <>
        <ModalSheet label="Conversation Hub" onRequestClose={sheetClose} header={<button type="button">Hub close</button>}>
          <p>hub</p>
        </ModalSheet>
        <AvatarCropEditor open name="Angel" imageUrl="http://hp/files/avatar_a.png" onClose={onClose} onSave={vi.fn()} />
      </>,
    )
    const editor = screen.getByRole('dialog', { name: 'Edit Profile Picture' })
    expect(editor.contains(document.activeElement)).toBe(true)
    fireEvent.change(screen.getByRole('slider', { name: 'Zoom' }), { target: { value: '2' } })
    fireEvent.keyDown(document.activeElement!, { key: 'Escape' })
    expect(sheetClose).not.toHaveBeenCalled()
    expect(screen.getByRole('alertdialog', { name: 'Discard changes?' })).toBeInTheDocument()
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Keep editing' }))
    fireEvent.keyDown(document.activeElement!, { key: 'Escape' })
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(sheetClose).not.toHaveBeenCalled()
    expect(onClose).not.toHaveBeenCalled()
  })
})
