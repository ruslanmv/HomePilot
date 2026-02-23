/**
 * AccountMenu — enterprise-grade account popover anchored to the sidebar avatar.
 *
 * Structure (Claude / Slack / GitHub pattern):
 *   [Avatar]  Display Name
 *             email / username
 *   ─────────────────────────
 *   Personalization
 *   Settings
 *   ─────────────────────────
 *   Help
 *   ─────────────────────────
 *   Log out
 *
 * UX rules:
 *  - Opens upward from the avatar (bottom-left anchor)
 *  - Closes on outside click or Esc
 *  - Keyboard-navigable (arrow keys, Enter)
 *  - Log out: one click, no confirmation, instant redirect
 *  - Identity at top, exit at bottom
 */
import React, { useEffect, useRef, useCallback } from 'react'
import { Settings, HelpCircle, LogOut, Palette } from 'lucide-react'
import UserAvatar from './UserAvatar'

export interface AccountMenuUser {
  id: string
  username: string
  display_name: string
  email: string
  avatar_url: string
}

interface AccountMenuProps {
  user: AccountMenuUser
  onClose: () => void
  onOpenSettings: () => void
  onOpenProfile: () => void
  onLogout: () => void
}

export default function AccountMenu({
  user,
  onClose,
  onOpenSettings,
  onOpenProfile,
  onLogout,
}: AccountMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null)
  const itemsRef = useRef<HTMLButtonElement[]>([])

  // Close on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose()
      }
    }
    // Delay to avoid the same click that opened the menu from closing it
    const timer = setTimeout(() => {
      document.addEventListener('mousedown', handleClickOutside)
    }, 0)
    return () => {
      clearTimeout(timer)
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [onClose])

  // Keyboard navigation
  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    const items = itemsRef.current.filter(Boolean)
    const currentIndex = items.indexOf(document.activeElement as HTMLButtonElement)

    switch (e.key) {
      case 'Escape':
        e.preventDefault()
        onClose()
        break
      case 'ArrowDown':
        e.preventDefault()
        if (currentIndex < items.length - 1) {
          items[currentIndex + 1]?.focus()
        } else {
          items[0]?.focus()
        }
        break
      case 'ArrowUp':
        e.preventDefault()
        if (currentIndex > 0) {
          items[currentIndex - 1]?.focus()
        } else {
          items[items.length - 1]?.focus()
        }
        break
      case 'Tab':
        e.preventDefault()
        onClose()
        break
    }
  }, [onClose])

  // Focus first item on mount
  useEffect(() => {
    const first = itemsRef.current.find(Boolean)
    first?.focus()
  }, [])

  const setItemRef = (index: number) => (el: HTMLButtonElement | null) => {
    if (el) itemsRef.current[index] = el
  }

  const menuItemClass = [
    'w-full text-left px-3 py-2 text-[13px] rounded-lg',
    'flex items-center gap-2.5',
    'text-white/80 hover:bg-white/8 hover:text-white',
    'focus:bg-white/8 focus:text-white focus:outline-none',
    'transition-colors cursor-pointer',
  ].join(' ')

  return (
    <div
      ref={menuRef}
      role="menu"
      aria-label="Account menu"
      onKeyDown={handleKeyDown}
      className="absolute bottom-[72px] left-3 w-[260px] bg-[#0f0f1a] border border-white/10 rounded-2xl shadow-2xl z-50 ring-1 ring-white/5 overflow-hidden"
      style={{ animation: 'accountMenuIn 150ms ease-out' }}
    >
      {/* Identity header */}
      <div className="px-4 py-3.5 flex items-center gap-3 border-b border-white/5">
        <UserAvatar
          displayName={user.display_name || user.username}
          avatarUrl={user.avatar_url}
          size={36}
        />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-white truncate">
            {user.display_name || user.username}
          </div>
          <div className="text-[11px] text-white/40 truncate">
            {user.email || `@${user.username}`}
          </div>
        </div>
      </div>

      {/* Main actions */}
      <div className="px-2 py-1.5">
        <button
          ref={setItemRef(0)}
          role="menuitem"
          className={menuItemClass}
          onClick={() => { onClose(); onOpenProfile() }}
        >
          <Palette size={15} className="text-white/40 shrink-0" />
          Personalization
        </button>
        <button
          ref={setItemRef(1)}
          role="menuitem"
          className={menuItemClass}
          onClick={() => { onClose(); onOpenSettings() }}
        >
          <Settings size={15} className="text-white/40 shrink-0" />
          Settings
        </button>
      </div>

      {/* Help */}
      <div className="border-t border-white/5 px-2 py-1.5">
        <button
          ref={setItemRef(2)}
          role="menuitem"
          className={menuItemClass}
          onClick={() => {
            onClose()
            window.open('https://github.com/ruslanmv/HomePilot', '_blank')
          }}
        >
          <HelpCircle size={15} className="text-white/40 shrink-0" />
          Help
        </button>
      </div>

      {/* Log out — always last, visually separated */}
      <div className="border-t border-white/5 px-2 py-1.5">
        <button
          ref={setItemRef(3)}
          role="menuitem"
          className={menuItemClass}
          onClick={onLogout}
        >
          <LogOut size={15} className="text-white/40 shrink-0" />
          Log out
        </button>
      </div>
    </div>
  )
}
