/**
 * The composer's `+` menu, and the header it emptied.
 *
 * ── What this reorganisation is about ────────────────────────────────────────────────────
 *
 * Three entry points existed for one idea — "give HomePilot something to look at" — and each
 * was somewhere else: a paperclip in the composer, Meeting in the header beside Call, and
 * screen sharing as a floating blue button the page mounted for itself. None was findable
 * from the others, and the floating one sat permanently over the conversation.
 *
 * They are now one menu, and the composer row says three distinct things in three places:
 *
 *     [+]  What do you want to know?          [ Fast ▾ ]  [🎤]
 *      │                                          │        │
 *      │                                          │        └── how it is submitted
 *      │                                          └─────────── how HomePilot should answer
 *      └────────────────────────────────────────────────────── what it should look at
 *
 * Nothing underneath changed: the file input is the same input, screen sharing is the same
 * `hpScreenSense.enable()`, and a meeting is the same `useMeetingControls().begin()`. This is
 * a rearrangement of entry points, which is exactly why it is worth pinning — a rearrangement
 * is the kind of change that silently drops a capability.
 */
import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { ComposerPlusMenu, ScreenShareStatus } from '../ui/components/ComposerPlusMenu';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const app = readFileSync(resolve(ROOT, 'frontend/src/ui/App.tsx'), 'utf8');
const indexHtml = readFileSync(resolve(ROOT, 'frontend/index.html'), 'utf8');

function stubScreenSense(over: Record<string, unknown> = {}) {
    const api = {
        mode: 'browser',
        enabled: false,
        enable: vi.fn(async function (this: Record<string, unknown>) { api.enabled = true; }),
        stop: vi.fn(() => { api.enabled = false; }),
        ...over,
    };
    (globalThis as Record<string, unknown>).hpScreenSense = api;
    return api;
}

beforeEach(() => {
    delete (globalThis as Record<string, unknown>).hpScreenSense;
});

afterEach(() => {
    delete (globalThis as Record<string, unknown>).hpScreenSense;
    vi.clearAllMocks();
});

const open = () => fireEvent.click(screen.getByTestId('composer-plus-button'));

describe('the header keeps only what you do with the app', () => {
    it('no longer mounts the Meeting button', () => {
        // Meeting is something you give the app to look at, not something you do with it, so
        // it moved to the `+` menu with the file, the screenshot and the screen.
        expect(app).not.toContain('<MeetingAction />');
        expect(app).not.toContain("from './meetingsense/MeetingAction'");
    });

    it('still has Call, Settings and New Chat', () => {
        // The point was to empty the header of one thing, not to thin it out generally.
        expect(app).toContain('aria-label="Start call"');
        expect(app).toContain('aria-label="Chat settings"');
        expect(app).toContain('aria-label="New Chat"');
    });
});

describe('the paperclip became +', () => {
    it('is replaced, not joined', () => {
        // A `+` next to a 📎 is two buttons for one intent, and the reader has to work out
        // which one is the superset.
        expect(app).not.toContain('<Paperclip size={18} />');
        expect(app).toContain('<ComposerPlusMenu onAddFile={() => fileInputRef.current?.click()} />');
    });

    it('keeps the existing file input exactly as it was', () => {
        // The upload path is the one thing here that must not be touched, and the menu's first
        // item fires the same click the paperclip did.
        expect(app).toContain('ref={fileInputRef}');
        expect(app).toContain('accept="image/*"');
    });

    it('opens the real file picker from the first item', () => {
        const onAddFile = vi.fn();
        render(<ComposerPlusMenu onAddFile={onAddFile} />);
        open();
        fireEvent.click(screen.getByTestId('composer-plus-file'));

        expect(onAddFile).toHaveBeenCalledTimes(1);
        // And the menu gets out of the way, because the OS picker is about to take over.
        expect(screen.queryByTestId('composer-plus-menu')).toBeNull();
    });

    it('is announced as a menu button', () => {
        render(<ComposerPlusMenu onAddFile={vi.fn()} />);
        const button = screen.getByTestId('composer-plus-button');
        expect(button).toHaveAttribute('aria-haspopup', 'menu');
        expect(button).toHaveAttribute('aria-expanded', 'false');
        open();
        expect(button).toHaveAttribute('aria-expanded', 'true');
    });

    it('opens upward, because the composer is at the bottom of the viewport', () => {
        render(<ComposerPlusMenu onAddFile={vi.fn()} />);
        open();
        expect(screen.getByTestId('composer-plus-menu').className).toContain('bottom-full');
    });

    it('can extend beyond the composer pill without being clipped', () => {
        expect(app).toContain("'relative w-full overflow-visible'");
        expect(app).not.toContain("'relative w-full overflow-hidden'");
    });

    it('closes on Escape and on an outside click', () => {
        // A menu only one of them closes is a menu somebody clicks twice to dismiss.
        render(<ComposerPlusMenu onAddFile={vi.fn()} />);
        open();
        fireEvent.keyDown(document, { key: 'Escape' });
        expect(screen.queryByTestId('composer-plus-menu')).toBeNull();

        open();
        fireEvent.mouseDown(document.body);
        expect(screen.queryByTestId('composer-plus-menu')).toBeNull();
    });
});

describe('screen sharing moved out of the floating button', () => {
    it('stops ScreenSense mounting its own', () => {
        // Two entry points for one feature, one of them a blue circle permanently over the
        // chat. The flag must be set *before* the script, which reads it as it initialises.
        expect(indexHtml).toContain('window.HOMEPILOT_SCREENSENSE_NO_AUTOBUTTON = true;');
        expect(indexHtml.indexOf('HOMEPILOT_SCREENSENSE_NO_AUTOBUTTON'))
            .toBeLessThan(indexHtml.indexOf('/js/homepilot-screensense.js'));
    });

    it('still loads ScreenSense itself', () => {
        // Suppressing the button is not deleting the engine — the menu drives the same API.
        expect(indexHtml).toContain('/js/homepilot-screensense.js');
    });

    it('starts the existing share flow', async () => {
        const api = stubScreenSense();
        render(<ComposerPlusMenu onAddFile={vi.fn()} />);
        open();
        fireEvent.click(screen.getByTestId('composer-plus-share'));

        await waitFor(() => expect(api.enable).toHaveBeenCalledTimes(1));
    });

    it('offers to stop once a share is live', async () => {
        const api = stubScreenSense({ enabled: true });
        render(<ComposerPlusMenu onAddFile={vi.fn()} />);
        open();

        await waitFor(() => expect(screen.getByTestId('composer-plus-share-stop')).toBeTruthy());
        expect(screen.queryByTestId('composer-plus-share')).toBeNull();
        fireEvent.click(screen.getByTestId('composer-plus-share-stop'));
        await waitFor(() => expect(api.stop).toHaveBeenCalledTimes(1));
    });

    it('reads the engine each time rather than trusting its own memory', async () => {
        // A share ends in ways nothing here observes — the browser's own "Stop sharing" bar, a
        // window closing. Claiming a share is live after it stopped is the one error that
        // matters, so the menu re-reads `enabled` on every open.
        const api = stubScreenSense({ enabled: true });
        render(<ComposerPlusMenu onAddFile={vi.fn()} />);
        open();
        await waitFor(() => expect(screen.getByTestId('composer-plus-share-stop')).toBeTruthy());

        fireEvent.keyDown(document, { key: 'Escape' });
        api.enabled = false; // ended outside the app
        open();

        await waitFor(() => expect(screen.getByTestId('composer-plus-share')).toBeTruthy());
    });

    it('offers no share row where the browser cannot share', () => {
        // Desktop captures without a persistent share and upload has none to start. A
        // permanently dead row teaches that the product is broken; an absent one teaches
        // nothing, which is right when there is nothing to learn.
        stubScreenSense({ mode: 'desktop' });
        render(<ComposerPlusMenu onAddFile={vi.fn()} />);
        open();
        expect(screen.queryByTestId('composer-plus-share')).toBeNull();
        expect(screen.getByTestId('composer-plus-file')).toBeTruthy();
    });

    it('survives ScreenSense not being loaded at all', () => {
        render(<ComposerPlusMenu onAddFile={vi.fn()} />);
        open();
        expect(screen.queryByTestId('composer-plus-share')).toBeNull();
    });

    it('keeps screenshot and share as separate ideas', () => {
        // Close technically, different in meaning: a screenshot is one image attached to one
        // message, a share is an ongoing permission. Collapsing them hides the privacy half.
        stubScreenSense();
        render(<ComposerPlusMenu onAddFile={vi.fn()} onScreenshot={vi.fn()} />);
        open();
        expect(screen.getByTestId('composer-plus-screenshot')).toBeTruthy();
        expect(screen.getByTestId('composer-plus-share')).toBeTruthy();
    });
});

describe('an active share stays visible', () => {
    it('shows a status line with a way out', async () => {
        // The floating button was also the only sign a share was running. Removing it without
        // replacing that would take away a privacy indicator rather than tidying up.
        const api = stubScreenSense({ enabled: true });
        render(<ScreenShareStatus />);

        await waitFor(() => expect(screen.getByTestId('screen-share-status')).toBeTruthy());
        expect(screen.getByTestId('screen-share-status').textContent).toContain('Screen sharing');
        fireEvent.click(screen.getByTestId('screen-share-stop'));
        expect(api.stop).toHaveBeenCalledTimes(1);
    });

    it('shows nothing while idle', () => {
        stubScreenSense({ enabled: false });
        render(<ScreenShareStatus />);
        expect(screen.queryByTestId('screen-share-status')).toBeNull();
    });

    it('is mounted by the composer', () => {
        expect(app).toContain('<ScreenShareStatus />');
    });
});

describe('the right-hand side is untouched', () => {
    it('keeps the reasoning selector and the microphone where they were', () => {
        // `+` is what to look at, `Fast ▾` is how to answer, the mic is how to submit. Three
        // different questions, so three different controls.
        expect(app).toContain('showChatReasoningSelector');
        expect(app).toContain('data-testid="composer-mic"');
    });
});
