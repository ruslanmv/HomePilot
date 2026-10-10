/**
 * Edit Profile Picture — frame the persona's picture for its round avatar.
 *
 * Drag to move; zoom with the slider, the − / + buttons, the mouse wheel or a
 * pinch; arrow keys move the picture when the crop area has focus. A circle
 * shows what the avatar keeps, and the preview draws exactly that region at
 * the sizes it is shown in. The picture is the persona's original at full
 * resolution; "Change photo" picks a replacement. Saving sends the framing to
 * the backend, which cuts the square from the original (see avatarCrop.ts).
 *
 * Cancel discards changes; closing any other way with unsaved changes asks
 * first. A failed save keeps everything as it was and says why.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import Cropper from 'react-easy-crop'
import { Check, ImagePlus, Loader2, Minus, Plus, RotateCcw, X } from 'lucide-react'
import {
  PHOTO_TYPES,
  photoProblem,
  previewStyle,
  sameView,
  type AvatarCrop,
  type CropArea,
  type SaveResult,
} from '../avatarCrop'

type View = { crop: { x: number; y: number }; zoom: number }

const MIN_ZOOM = 1
const MAX_ZOOM = 5
const ZOOM_STEP = 0.1
const CENTRED: View = { crop: { x: 0, y: 0 }, zoom: 1 }

export type AvatarCropEditorProps = {
  open: boolean
  name: string
  /** The persona's original picture (full resolution), or null when it has none. */
  imageUrl: string | null
  /** The framing saved last time, to reopen at the same place. */
  savedCrop?: AvatarCrop | null
  onClose: () => void
  onSave: (input: { area: CropArea; zoom: number; file: File | null }) => Promise<SaveResult>
  /** Go back to the automatic thumbnail (shown only when a saved crop is in use). */
  onRestoreAutomatic?: () => Promise<SaveResult>
}

export function AvatarCropEditor({ open, ...rest }: AvatarCropEditorProps) {
  // Mount fresh on every open, so Cancel always means "nothing happened".
  if (!open) return null
  return <EditorDialog {...rest} />
}

function EditorDialog({ name, imageUrl, savedCrop, onClose, onSave, onRestoreAutomatic }: Omit<AvatarCropEditorProps, 'open'>) {
  const [file, setFile] = useState<File | null>(null)
  const [src, setSrc] = useState<string | null>(imageUrl)
  const [view, setView] = useState<View>(CENTRED)
  const [baseline, setBaseline] = useState<View | null>(null)
  const [area, setArea] = useState<CropArea | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [imageFailed, setImageFailed] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirmDiscard, setConfirmDiscard] = useState(false)

  const viewRef = useRef(view)
  viewRef.current = view
  const dialogRef = useRef<HTMLDivElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const returnFocus = useRef<HTMLElement | null>(null)

  // Reopen at the saved framing only for the picture it was saved on.
  const initialArea = !file && savedCrop ? savedCrop.area : undefined
  const dirty = !!file || (!!baseline && !sameView(view, baseline))

  // Start inside the dialog: the crop area once the picture is there (arrow
  // keys move it), the dialog itself until then.
  const focusStart = useCallback(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    const active = document.activeElement
    if (active && active !== dialog && dialog.contains(active)) return // the user is already somewhere
    const target = dialog.querySelector<HTMLElement>('[data-autofocus]')
    ;(target || dialog).focus({ preventScroll: true })
  }, [])

  useEffect(() => {
    returnFocus.current = document.activeElement as HTMLElement | null
    focusStart()
    return () => { returnFocus.current?.focus?.({ preventScroll: true }) }
  }, [focusStart])

  // Object URLs for a chosen photo are released when replaced or closed.
  useEffect(() => () => { if (src && src.startsWith('blob:')) URL.revokeObjectURL(src) }, [src])

  const requestClose = useCallback(() => {
    if (saving) return
    if (dirty) setConfirmDiscard(true)
    else onClose()
  }, [dirty, onClose, saving])

  // Escape and Tab belong to this dialog while it is open. It is often opened
  // over another dialog (the Conversation Hub) that listens on the document in
  // the capture phase, so listen on the window — which runs first — and stop
  // the key there: Escape must never close what is underneath, or skip the
  // "discard changes?" question.
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.preventDefault()
      e.stopImmediatePropagation()
      if (confirmDiscard) setConfirmDiscard(false)
      else requestClose()
      return
    }
    if (e.key !== 'Tab' || !dialogRef.current) return
    e.stopImmediatePropagation()
    const dialog = dialogRef.current
    const items = Array.from(
      dialog.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]):not([type="file"]), [tabindex="0"]'),
    ).filter((el) => el.getClientRects().length > 0)
    if (!items.length) { e.preventDefault(); return }
    const first = items[0]
    const last = items[items.length - 1]
    const active = document.activeElement
    if (!active || !dialog.contains(active) || active === dialog) {
      e.preventDefault()
      ;(e.shiftKey ? last : first).focus()
    } else if (e.shiftKey && active === first) { e.preventDefault(); last.focus() }
    else if (!e.shiftKey && active === last) { e.preventDefault(); first.focus() }
  }
  const onKeyRef = useRef(onKey)
  onKeyRef.current = onKey
  useEffect(() => {
    const listener = (e: KeyboardEvent) => onKeyRef.current(e)
    window.addEventListener('keydown', listener, true)
    return () => window.removeEventListener('keydown', listener, true)
  }, [])

  // Keyboard users answering "discard changes?" start on the safe choice.
  const keepEditingRef = useRef<HTMLButtonElement>(null)
  useEffect(() => { if (confirmDiscard) keepEditingRef.current?.focus({ preventScroll: true }) }, [confirmDiscard])

  const onMediaLoaded = useCallback(() => {
    setLoaded(true)
    setImageFailed(false)
    // The cropper settles the initial framing on load; that is the "unchanged" state.
    requestAnimationFrame(() => {
      setBaseline(viewRef.current)
      focusStart()
    })
  }, [focusStart])

  const choosePhoto = (picked: File | undefined) => {
    if (!picked) return
    const problem = photoProblem(picked)
    if (problem) { setError(problem); return }
    setError(null)
    setFile(picked)
    setSrc(URL.createObjectURL(picked))
    setView(CENTRED)
    setBaseline(null)
    setArea(null)
    setLoaded(false)
  }

  const zoomBy = (delta: number) => {
    setView((v) => ({ ...v, zoom: Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Math.round((v.zoom + delta) * 100) / 100)) }))
  }

  const save = async () => {
    if (!area || saving) return
    setSaving(true)
    setError(null)
    const res = await onSave({ area, zoom: view.zoom, file })
    setSaving(false)
    if (res.ok) onClose()
    else setError(res.error)
  }

  const restoreAutomatic = async () => {
    if (!onRestoreAutomatic || saving) return
    setSaving(true)
    setError(null)
    const res = await onRestoreAutomatic()
    setSaving(false)
    if (res.ok) onClose()
    else setError(res.error)
  }

  const percent = Math.round(view.zoom * 100)

  // Portalled to <body> like ModalSheet, so where it is opened from (a drawer
  // with a transform, say) can never change how it is laid out.
  return createPortal(
    <div className="fixed inset-0 z-[80] flex items-stretch justify-center sm:items-center sm:p-4">
      <div className="absolute inset-0 bg-black/70" onClick={requestClose} aria-hidden />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="hp-crop-title"
        aria-describedby="hp-crop-desc"
        tabIndex={-1}
        className="relative flex max-h-[100dvh] w-full max-w-[920px] flex-col overflow-y-auto border-white/10 bg-[#0d0d14] text-white shadow-2xl outline-none sm:max-h-[92dvh] sm:rounded-3xl sm:border"
      >
        <header className="flex items-start gap-4 px-5 pt-5 sm:px-7 sm:pt-6">
          <div className="min-w-0 flex-1">
            <h2 id="hp-crop-title" className="text-xl font-semibold sm:text-2xl">Edit Profile Picture</h2>
            <p id="hp-crop-desc" className="mt-1 text-sm text-white/60">
              Crop and position {name ? `${name}'s` : 'the'} photo. Drag to move, use the slider or scroll to zoom.
            </p>
          </div>
          <button
            type="button"
            onClick={requestClose}
            aria-label="Close"
            className="grid h-10 w-10 shrink-0 place-items-center rounded-full text-white/60 hover:bg-white/10 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-violet-400"
          >
            <X size={20} />
          </button>
        </header>

        <div className="grid grid-cols-[minmax(0,1fr)] gap-3 px-5 pt-4 sm:gap-4 sm:px-7 md:grid-cols-[minmax(0,1fr)_200px]">
          <div
            className="relative aspect-square w-full overflow-hidden rounded-2xl border border-white/10 bg-black md:aspect-auto md:h-[440px]"
            data-testid="crop-stage"
          >
            {src && !imageFailed ? (
              <Cropper
                key={src}
                image={src}
                crop={view.crop}
                zoom={view.zoom}
                minZoom={MIN_ZOOM}
                maxZoom={MAX_ZOOM}
                aspect={1}
                cropShape="round"
                showGrid
                restrictPosition
                keyboardStep={8}
                initialCroppedAreaPercentages={initialArea}
                onCropChange={(crop) => setView((v) => ({ ...v, crop }))}
                onZoomChange={(zoom) => setView((v) => ({ ...v, zoom }))}
                onCropAreaChange={(a) => setArea(a)}
                onCropComplete={(a) => setArea(a)}
                onMediaLoaded={onMediaLoaded}
                mediaProps={{ alt: '', onError: () => setImageFailed(true) } as React.ImgHTMLAttributes<HTMLElement>}
                cropperProps={{
                  'aria-label': 'Crop area. Drag, or use the arrow keys, to move the picture.',
                  'data-autofocus': '',
                } as React.HTMLAttributes<HTMLDivElement>}
                style={{
                  cropAreaStyle: { border: '2px solid rgba(167, 139, 250, 0.95)', color: 'rgba(0, 0, 0, 0.62)' },
                }}
              />
            ) : (
              <div className="grid h-full place-items-center p-6 text-center">
                <div>
                  <p className="text-sm text-white/70">
                    {imageFailed ? 'The picture could not be loaded.' : 'This persona has no picture yet.'}
                  </p>
                  <button
                    type="button"
                    onClick={() => fileRef.current?.click()}
                    data-autofocus
                    className="mt-4 inline-flex h-11 items-center gap-2 rounded-xl border border-white/15 bg-white/[0.06] px-4 text-sm font-semibold hover:bg-white/[0.1]"
                  >
                    <ImagePlus size={16} /> Choose a photo
                  </button>
                </div>
              </div>
            )}
            {src && !loaded && !imageFailed ? (
              <div className="pointer-events-none absolute inset-0 grid place-items-center" role="status" aria-label="Loading picture">
                <Loader2 className="animate-spin text-white/60" size={28} />
              </div>
            ) : null}
          </div>

          <aside className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-2xl border border-white/10 bg-white/[0.02] p-3 sm:p-4 md:flex-col md:flex-nowrap md:items-start md:gap-y-3" aria-label="Preview">
            <div className="basis-full text-sm font-semibold text-white/85 md:basis-auto">Preview</div>
            <div
              className="h-[88px] w-[88px] shrink-0 rounded-full bg-white/5 ring-2 ring-violet-400/80 sm:h-[120px] sm:w-[120px] md:h-[168px] md:w-[168px]"
              style={src && area && !imageFailed ? previewStyle(src, area) : undefined}
              data-testid="crop-preview"
              role="img"
              aria-label={`${name || 'Persona'} avatar preview`}
            />
            <div className="flex items-center gap-3 text-xs text-white/50">
              {[48, 28].map((s) => (
                <div
                  key={s}
                  className="shrink-0 rounded-full bg-white/5 ring-1 ring-white/20"
                  style={{ width: s, height: s, ...(src && area && !imageFailed ? previewStyle(src, area) : {}) }}
                  aria-hidden
                />
              ))}
              <span>In chat</span>
            </div>
            {savedCrop && !file && onRestoreAutomatic ? (
              <button
                type="button"
                onClick={restoreAutomatic}
                disabled={saving}
                className="basis-full py-1 text-left text-xs font-medium text-white/50 underline-offset-4 hover:text-white/80 hover:underline disabled:opacity-40 md:mt-auto md:basis-auto"
              >
                Use automatic thumbnail
              </button>
            ) : null}
          </aside>
        </div>

        <div className="flex items-center gap-3 px-5 pt-4 sm:px-7">
          <button
            type="button"
            onClick={() => zoomBy(-ZOOM_STEP)}
            disabled={!loaded || view.zoom <= MIN_ZOOM}
            aria-label="Zoom out"
            className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-white/15 text-white/80 hover:bg-white/10 disabled:opacity-40"
          >
            <Minus size={18} />
          </button>
          <input
            type="range"
            min={MIN_ZOOM}
            max={MAX_ZOOM}
            step={0.01}
            value={view.zoom}
            disabled={!loaded}
            onChange={(e) => setView((v) => ({ ...v, zoom: Number(e.target.value) }))}
            aria-label="Zoom"
            aria-valuetext={`${percent}%`}
            className="h-2 min-w-0 flex-1 cursor-pointer accent-violet-500"
          />
          <button
            type="button"
            onClick={() => zoomBy(ZOOM_STEP)}
            disabled={!loaded || view.zoom >= MAX_ZOOM}
            aria-label="Zoom in"
            className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-white/15 text-white/80 hover:bg-white/10 disabled:opacity-40"
          >
            <Plus size={18} />
          </button>
          <span className="w-14 shrink-0 text-right text-sm tabular-nums text-white/80" aria-live="polite">{percent}%</span>
        </div>

        {error ? (
          <p role="alert" className="mx-5 mt-4 rounded-xl border border-rose-400/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200 sm:mx-7">{error}</p>
        ) : null}

        {confirmDiscard ? (
          <div role="alertdialog" aria-label="Discard changes?" className="mx-5 mt-4 flex flex-wrap items-center gap-3 rounded-xl border border-amber-400/30 bg-amber-500/10 px-3 py-2.5 text-sm text-amber-100 sm:mx-7">
            <span className="min-w-0 flex-1">Discard your changes to the picture?</span>
            <button ref={keepEditingRef} type="button" onClick={() => setConfirmDiscard(false)} className="h-9 rounded-lg px-3 font-semibold hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-300">Keep editing</button>
            <button type="button" onClick={onClose} className="h-9 rounded-lg bg-amber-500/80 px-3 font-semibold text-black hover:bg-amber-400">Discard</button>
          </div>
        ) : null}

        {/* On phones the actions stay in reach at the bottom while the rest scrolls. */}
        <footer className="sticky bottom-0 mt-auto flex flex-wrap items-center gap-3 border-t border-white/10 bg-[#0d0d14] px-5 pb-[max(1rem,env(safe-area-inset-bottom))] pt-3 sm:static sm:border-t-0 sm:px-7 sm:pb-6 sm:pt-5">
          <button
            type="button"
            onClick={() => setView(CENTRED)}
            disabled={!loaded || saving}
            className="inline-flex h-11 items-center gap-2 rounded-xl border border-white/15 px-4 text-sm font-semibold text-white/85 hover:bg-white/10 disabled:opacity-40"
          >
            <RotateCcw size={16} /> Reset
          </button>
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            disabled={saving}
            className="inline-flex h-11 items-center gap-2 rounded-xl border border-white/15 px-4 text-sm font-semibold text-white/85 hover:bg-white/10 disabled:opacity-40"
          >
            <ImagePlus size={16} /> Change photo
          </button>
          <input
            ref={fileRef}
            type="file"
            accept={PHOTO_TYPES.join(',')}
            className="hidden"
            onChange={(e) => { choosePhoto(e.target.files?.[0]); e.target.value = '' }}
          />
          <div className="flex w-full items-center gap-3 sm:ml-auto sm:w-auto">
            <button
              type="button"
              onClick={onClose}
              disabled={saving}
              className="h-11 flex-1 rounded-xl border border-white/15 px-5 text-sm font-semibold text-white/90 hover:bg-white/10 disabled:opacity-40 sm:flex-none"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={save}
              disabled={!loaded || !area || saving}
              className="inline-flex h-11 flex-1 items-center justify-center gap-2 rounded-xl bg-violet-600 px-5 text-sm font-semibold text-white shadow-lg shadow-violet-900/40 hover:bg-violet-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-300 disabled:opacity-50 sm:flex-none"
            >
              {saving ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
              {saving ? 'Saving…' : 'Save Crop'}
            </button>
          </div>
        </footer>
      </div>
    </div>,
    document.body,
  )
}

export default AvatarCropEditor
