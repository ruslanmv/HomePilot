/**
 * ModalSheet — a dialog that is full-screen on phones and a centred card on
 * larger screens.
 *
 * Why it exists: dialogs used to be rendered wherever they were opened. When
 * that place was the mobile nav drawer (which slides in with a CSS transform),
 * the dialog's `position: fixed` was resolved against the drawer instead of the
 * screen — a transformed ancestor becomes the containing block for fixed
 * descendants — so "full-screen" settings came out as a 280px column pinned to
 * the left. The sheet is portalled to <body>, so where it is opened from can
 * never change how it is laid out.
 *
 * It also owns the behaviour every dialog needs: one scrolling body between a
 * fixed header and a sticky footer (above the home indicator), Escape or the
 * phone's Back gesture to close, focus moved in on open and back on close, Tab
 * kept inside, no background scrolling while open, and a short enter/leave
 * transition (motion system, animation 20).
 */
import React, { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { useBackToClose } from '../lib/useBackToClose'
import { motionAllowed } from '../motion/prefs'

/**
 * Plays the leave transition on a copy of the sheet after React has removed
 * it, so owners can keep rendering `{open && <Sheet/>}` and still get an exit.
 * The copy is inert and hidden from assistive technology.
 */
function playLeave(node: HTMLElement | null) {
  if (!node || !motionAllowed()) return
  const ghost = node.cloneNode(true) as HTMLElement
  ghost.setAttribute('data-leaving', '')
  ghost.setAttribute('aria-hidden', 'true')
  ghost.setAttribute('inert', '')
  ghost.removeAttribute('id')
  ghost.querySelectorAll('[id]').forEach((el) => el.removeAttribute('id'))
  document.body.appendChild(ghost)
  const remove = () => ghost.remove()
  ghost.addEventListener('animationend', (e) => { if (e.target === ghost) remove() })
  window.setTimeout(remove, 400)
}

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

export function ModalSheet({
  labelledBy,
  onRequestClose,
  header,
  footer,
  children,
  zIndex = 200,
  bodyRef,
  className = '',
  label,
}: {
  /** id of the element that names the dialog */
  labelledBy?: string
  /** accessible name when no visible element names the dialog */
  label?: string
  /** extra classes on the sheet (e.g. a themed surface) */
  className?: string
  /** Escape or a backdrop click; the owner decides (e.g. confirm unsaved changes). */
  onRequestClose: () => void
  header: React.ReactNode
  footer?: React.ReactNode
  children: React.ReactNode
  zIndex?: number
  bodyRef?: React.Ref<HTMLDivElement>
}) {
  const sheetRef = useRef<HTMLDivElement>(null)
  const backdropRef = useRef<HTMLDivElement>(null)
  const closeRef = useRef(onRequestClose)
  closeRef.current = onRequestClose
  useBackToClose(true, () => closeRef.current())

  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null
    const { overflow } = document.body.style
    document.body.style.overflow = 'hidden'
    // Focus the first control (usually the close button) so keyboard and
    // screen-reader users start inside the dialog.
    const first = sheetRef.current?.querySelector<HTMLElement>(FOCUSABLE)
    ;(first || sheetRef.current)?.focus({ preventScroll: true })

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        closeRef.current()
        return
      }
      if (e.key !== 'Tab' || !sheetRef.current) return
      const items = Array.from(sheetRef.current.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => {
        if (el.hidden || el.closest('[hidden], [aria-hidden="true"]')) return false
        const style = getComputedStyle(el)
        return style.display !== 'none' && style.visibility !== 'hidden'
      })
      if (!items.length) return
      const firstItem = items[0]
      const lastItem = items[items.length - 1]
      if (e.shiftKey && document.activeElement === firstItem) {
        e.preventDefault()
        lastItem.focus()
      } else if (!e.shiftKey && document.activeElement === lastItem) {
        e.preventDefault()
        firstItem.focus()
      }
    }
    document.addEventListener('keydown', onKey, true)
    const backdrop = backdropRef.current
    return () => {
      // Only a real close removes the node; StrictMode's dev-only effect re-run keeps it.
      window.setTimeout(() => { if (backdrop && !backdrop.isConnected) playLeave(backdrop) }, 0)
      document.removeEventListener('keydown', onKey, true)
      document.body.style.overflow = overflow
      previouslyFocused?.focus?.({ preventScroll: true })
    }
  }, [])

  return createPortal(
    <div
      ref={backdropRef}
      className="hp-sheet-backdrop"
      style={{ zIndex }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) closeRef.current()
      }}
    >
      <div
        ref={sheetRef}
        className={`hp-sheet ${className}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        aria-label={labelledBy ? undefined : label}
        tabIndex={-1}
      >
        <div className="hp-sheet__header">{header}</div>
        <div className="hp-sheet__body" ref={bodyRef}>{children}</div>
        {footer ? <div className="hp-sheet__footer">{footer}</div> : null}
      </div>
    </div>,
    document.body,
  )
}

export default ModalSheet
