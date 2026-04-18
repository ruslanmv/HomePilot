/**
 * useFocusTrap — keep keyboard focus inside a container while it's
 * mounted, and restore it to the trigger element on unmount.
 *
 * Used by CallScreen and LockScreenIncoming so Tab doesn't escape
 * the call modal into the background chat (which is dimmed + not
 * interactive — losing focus there would strand screen-reader and
 * keyboard users outside the dialog).
 *
 * Behaviour:
 *
 *   1. On mount, the previously-focused element is remembered; if the
 *      container isn't already focused, the first focusable child is
 *      focused.
 *   2. Tab / Shift-Tab at the container's boundaries wraps to the
 *      opposite edge, not out of the trap.
 *   3. Escape is NOT handled here — dialogs that want Escape-to-close
 *      wire it explicitly. Keeping the hook single-purpose.
 *   4. On unmount, focus is restored to the remembered element.
 *      Falls back silently if that element is gone.
 *
 * Pass a React ref to the container. The hook reads tabbable
 * children live on every Tab, so containers with dynamic content
 * (a message list that grows mid-call) stay trapped without the
 * caller having to re-declare focusables.
 */
import { useEffect, type RefObject } from 'react'

// What counts as "tabbable." Matches the WAI-ARIA list; keep
// narrow so we don't grab hidden / disabled elements.
const TABBABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'textarea:not([disabled])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

function tabbableChildren(root: HTMLElement): HTMLElement[] {
  const list = Array.from(root.querySelectorAll<HTMLElement>(TABBABLE_SELECTOR))
  return list.filter((el) => {
    // Skip offscreen / visually-hidden elements. offsetParent is
    // null for display:none but not for visibility:hidden; the
    // aria-hidden check catches the latter when callers mark it.
    if (el.getAttribute('aria-hidden') === 'true') return false
    if (el.hidden) return false
    return true
  })
}

export function useFocusTrap<T extends HTMLElement>(
  ref: RefObject<T>,
  enabled: boolean = true,
): void {
  useEffect(() => {
    if (!enabled) return
    const root = ref.current
    if (!root) return

    const previouslyFocused =
      typeof document !== 'undefined'
        ? (document.activeElement as HTMLElement | null)
        : null

    // Initial focus — first tabbable child if the container doesn't
    // already own focus. We don't want to steal focus if the user
    // has clicked into an input inside the trap before the hook
    // mounted (rare but possible with async render paths).
    if (!root.contains(document.activeElement)) {
      const focusables = tabbableChildren(root)
      focusables[0]?.focus()
    }

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return
      const focusables = tabbableChildren(root)
      if (focusables.length === 0) {
        // Nothing inside is focusable — trap by eating the Tab.
        e.preventDefault()
        return
      }
      const first = focusables[0]
      const last = focusables[focusables.length - 1]
      const active = document.activeElement as HTMLElement | null
      if (e.shiftKey) {
        if (active === first || !root.contains(active)) {
          e.preventDefault()
          last.focus()
        }
      } else {
        if (active === last) {
          e.preventDefault()
          first.focus()
        }
      }
    }

    root.addEventListener('keydown', onKeyDown)
    return () => {
      root.removeEventListener('keydown', onKeyDown)
      // Restore — best-effort. If the previously-focused element
      // was removed from the DOM while the trap was active,
      // focus() silently no-ops.
      try {
        previouslyFocused?.focus?.()
      } catch {
        /* ignore */
      }
    }
  }, [ref, enabled])
}
