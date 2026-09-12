import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Video } from 'lucide-react';
// The Vite pre-resolver only redirects App.tsx's `./SettingsPanel` import to
// this wrapper. From here, normal TypeScript resolution reaches the canonical
// SettingsPanel.tsx, so there is no recursion and no stale JSX fallback.
import LegacySettingsPanel from './SettingsPanel';
import AudioVideoSettings from './components/AudioVideoSettings';

type SettingsPanelProps = {
  value: any;
  onChangeDraft: (next: any) => void;
  onSave: () => void;
  onClose: () => void;
};

type NavHost = {
  host: HTMLElement;
  mobile: boolean;
};

type MountedHosts = {
  navs: NavHost[];
  contentHost: HTMLDivElement;
  content: HTMLElement;
  cleanupNavListeners: () => void;
};

const MEDIA_TAB_ATTR = 'data-homepilot-audio-video-tab';
const MEDIA_CONTENT_ATTR = 'data-homepilot-audio-video-content';

/**
 * Additive wrapper around the canonical Enterprise Settings panel.
 *
 * HomePilot currently keeps generated TSX/JSX twins. A tiny Vite pre-resolver
 * redirects only App.tsx's extensionless SettingsPanel import to this wrapper.
 * This component then resolves `./SettingsPanel` normally back to the canonical
 * TypeScript implementation and adds one real navigation item plus an Audio &
 * Video content surface without forking the large existing panel.
 *
 * The DOM adapter is deliberately narrow: it anchors to the dialog's accessible
 * labels and direct body structure, not pixel positions or generated class names.
 * It can be removed once Audio & Video becomes a native SettingsPanel section.
 */
export default function SettingsPanelWithMedia(props: SettingsPanelProps) {
  const [mediaOpen, setMediaOpen] = useState(false);
  const [mounted, setMounted] = useState<MountedHosts | null>(null);

  useEffect(() => {
    let cancelled = false;
    let frame = 0;
    let attempts = 0;

    const install = () => {
      if (cancelled) return;

      const dialog = document.querySelector<HTMLElement>(
        '[role="dialog"][aria-label="Enterprise Settings"]',
      );
      const navElements = dialog
        ? Array.from(dialog.querySelectorAll<HTMLElement>('nav[aria-label="Settings sections"]'))
        : [];
      const body = navElements[0]?.parentElement ?? null;
      const content = body
        ? Array.from(body.children).find(
            (node): node is HTMLElement =>
              node instanceof HTMLElement && node.classList.contains('overflow-y-auto'),
          ) ?? null
        : null;

      if (!dialog || navElements.length === 0 || !content) {
        attempts += 1;
        if (attempts < 20) frame = requestAnimationFrame(install);
        return;
      }

      const navs: NavHost[] = [];
      const listenerCleanups: Array<() => void> = [];

      navElements.forEach((nav) => {
        const existing = nav.querySelector<HTMLElement>(`[${MEDIA_TAB_ATTR}]`);
        if (existing) existing.remove();

        const host = document.createElement('span');
        host.setAttribute(MEDIA_TAB_ATTR, 'host');
        host.style.display = 'contents';

        const voiceButton = Array.from(nav.querySelectorAll('button')).find(
          (button) => button.textContent?.trim().includes('Voice'),
        );
        if (voiceButton) voiceButton.insertAdjacentElement('afterend', host);
        else nav.appendChild(host);

        const onLegacyNavigation = (event: Event) => {
          const target = event.target instanceof Element ? event.target : null;
          if (target?.closest(`[${MEDIA_TAB_ATTR}="button"]`)) return;
          if (target?.closest('button')) setMediaOpen(false);
        };
        nav.addEventListener('click', onLegacyNavigation);
        listenerCleanups.push(() => nav.removeEventListener('click', onLegacyNavigation));

        navs.push({
          host,
          mobile: nav.classList.contains('md:hidden'),
        });
      });

      const contentHost = document.createElement('div');
      contentHost.setAttribute(MEDIA_CONTENT_ATTR, 'true');
      contentHost.style.display = 'none';
      content.appendChild(contentHost);

      if (!cancelled) {
        setMounted({
          navs,
          contentHost,
          content,
          cleanupNavListeners: () => listenerCleanups.forEach((cleanup) => cleanup()),
        });
      }
    };

    frame = requestAnimationFrame(install);
    return () => {
      cancelled = true;
      cancelAnimationFrame(frame);
      setMounted((current) => {
        if (!current) return null;
        current.cleanupNavListeners();
        current.navs.forEach(({ host }) => host.remove());
        current.contentHost.remove();
        return null;
      });
    };
  }, []);

  useEffect(() => {
    if (!mounted) return;

    const siblings = Array.from(mounted.content.children).filter(
      (child): child is HTMLElement => child instanceof HTMLElement && child !== mounted.contentHost,
    );

    if (mediaOpen) {
      siblings.forEach((child) => {
        if (!child.hasAttribute('data-hp-previous-display')) {
          child.setAttribute('data-hp-previous-display', child.style.display || '');
        }
        child.style.display = 'none';
      });
      mounted.contentHost.style.display = 'block';
      mounted.content.scrollTop = 0;
    } else {
      mounted.contentHost.style.display = 'none';
      siblings.forEach((child) => {
        const previous = child.getAttribute('data-hp-previous-display');
        if (previous !== null) {
          child.style.display = previous;
          child.removeAttribute('data-hp-previous-display');
        }
      });
    }

    return () => {
      mounted.contentHost.style.display = 'none';
      siblings.forEach((child) => {
        const previous = child.getAttribute('data-hp-previous-display');
        if (previous !== null) {
          child.style.display = previous;
          child.removeAttribute('data-hp-previous-display');
        }
      });
    };
  }, [mediaOpen, mounted]);

  return (
    <>
      <LegacySettingsPanel {...props} />

      {mounted?.navs.map(({ host, mobile }, index) =>
        createPortal(
          <button
            key={index}
            type="button"
            {...{ [MEDIA_TAB_ATTR]: 'button' }}
            aria-current={mediaOpen ? 'page' : undefined}
            onClick={() => setMediaOpen(true)}
            className={
              mobile
                ? [
                    'flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs whitespace-nowrap transition-colors',
                    mediaOpen
                      ? 'bg-[#9b5cff]/[0.16] border border-[#9b5cff]/45 text-white'
                      : 'border border-white/10 text-white/55 hover:text-white/80',
                  ].join(' ')
                : [
                    'flex items-center gap-2.5 px-3 py-2 rounded-[10px] text-sm text-left transition-colors',
                    'focus:outline-none focus-visible:ring-2 focus-visible:ring-[#9b5cff]/75',
                    mediaOpen
                      ? 'bg-[#9b5cff]/[0.16] border border-[#9b5cff]/45 text-white'
                      : 'border border-transparent text-white/58 hover:text-white/85 hover:bg-white/[0.04]',
                  ].join(' ')
            }
          >
            <Video size={mobile ? 13 : 16} className={mediaOpen ? 'text-[#b98bff]' : 'text-white/40'} />
            <span className={mobile ? '' : 'truncate'}>Audio &amp; Video</span>
          </button>,
          host,
        ),
      )}

      {mounted && mediaOpen
        ? createPortal(<AudioVideoSettings />, mounted.contentHost)
        : null}
    </>
  );
}
