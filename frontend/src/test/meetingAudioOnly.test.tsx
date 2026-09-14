/**
 * A meeting does not require a screen, and a role needs names to be more than a label.
 *
 * Two gaps this covers, both of which made a built feature look broken:
 *
 * 1. The wizard has had three independent capture toggles since it shipped, but the recorder
 *    called `getDisplayMedia` unconditionally — so unticking "Meeting audio" and "Screen &
 *    slides" still put a screen-share picker in front of somebody whose meeting is a phone on
 *    the table next to the microphone.
 *
 * 2. MS26's question detector keys on `names` and its draft on the mode, and the frontend
 *    sent neither. Participant mode — "answers when addressed; drafts replies for you" — was
 *    therefore inert in the product no matter what the user picked.
 */

import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { MeetingStartDialog } from '../ui/meetingsense/MeetingStartDialog';
import { DEFAULT_CAPTURE, parseNames } from '../ui/meetingsense/CapturePopover';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const RECORDER = readFileSync(resolve(ROOT, 'frontend/public/js/homepilot-meetingsense.js'), 'utf8');
const PROVIDER = readFileSync(
    resolve(ROOT, 'frontend/src/ui/meetingsense/MeetingSenseProvider.tsx'), 'utf8',
);

const STATUS = {
    enabled: true,
    ready: true,
    retention: 'text',
    stt: { available: true, provider: 'whisper-local', remote: false },
};

function openDialog(capture = DEFAULT_CAPTURE) {
    const onCaptureChange = vi.fn();
    render(
        <MeetingStartDialog
            status={STATUS as never}
            capture={capture}
            onCaptureChange={onCaptureChange}
            onAccept={vi.fn()}
            onCancel={vi.fn()}
        />,
    );
    return onCaptureChange;
}

describe('parseNames', () => {
    it('splits the one field a person actually types', () => {
        // "Ruslan, Rus" is how somebody writes the two things they are called.
        expect(parseNames('Ruslan, Rus')).toEqual(['Ruslan', 'Rus']);
    });

    it('drops blanks and stray separators rather than sending empty names', () => {
        expect(parseNames(' Ana ,, , Anita ')).toEqual(['Ana', 'Anita']);
    });

    it('treats nothing as nothing, which is what keeps the detector narrow', () => {
        expect(parseNames('')).toEqual([]);
        expect(parseNames('   ')).toEqual([]);
        expect(parseNames(undefined as unknown as string)).toEqual([]);
    });
});

describe('the start wizard', () => {
    it('defaults the name fields empty, so nothing fires until asked', () => {
        expect(DEFAULT_CAPTURE.myNames).toBe('');
        expect(DEFAULT_CAPTURE.assistantName).toBe('');
    });

    it('does not ask who you are for a role that never speaks', () => {
        // Note-taker says nothing by design, so the field would change nothing.
        openDialog({ ...DEFAULT_CAPTURE, mode: null });
        expect(screen.queryByTestId('ms-start-my-names')).toBeNull();
    });

    it('asks for names on the roles that use them', () => {
        openDialog({ ...DEFAULT_CAPTURE, mode: 'participant' });
        expect(screen.getByTestId('ms-start-my-names')).toBeTruthy();
        expect(screen.getByTestId('ms-start-assistant-name')).toBeTruthy();
    });

    it('carries a typed name back without disturbing the capture sources', () => {
        const onCaptureChange = openDialog({ ...DEFAULT_CAPTURE, mode: 'participant' });
        fireEvent.change(screen.getByTestId('ms-start-my-names'), { target: { value: 'Ruslan' } });

        expect(onCaptureChange).toHaveBeenCalledWith({
            ...DEFAULT_CAPTURE, mode: 'participant', myNames: 'Ruslan',
        });
    });

    it('says the assistant answering nobody is the safe default', () => {
        openDialog({ ...DEFAULT_CAPTURE, mode: 'participant' });
        const field = screen.getByTestId('ms-start-assistant-name') as HTMLInputElement;
        expect(field.placeholder).toContain('never speaks');
    });
});

describe('capture sources are honoured, as source', () => {
    it('opens the display only when the call audio or the slides want it', () => {
        expect(RECORDER).toContain('const wantsSystemAudio = opts.audio !== false');
        expect(RECORDER).toContain('const wantsMic = opts.mic !== false');
        expect(RECORDER).toContain('const wantsDisplay = wantsSystemAudio || wantsSlides');
        expect(RECORDER).toContain("if (!wantsDisplay) throw new Error('display capture not requested')");
    });

    it('never opens a microphone nobody asked for', () => {
        // A "them only" meeting must not light the microphone indicator, and a permission
        // prompt for a device with no use is its own kind of broken.
        expect(RECORDER).toContain("if (!wantsMic) throw new Error('microphone not requested')");
    });

    it('omitting an option still means yes, so older callers are unchanged', () => {
        // `!== false` rather than a truthiness test, deliberately: every caller written before
        // these were read passes neither and must behave exactly as it did.
        expect(RECORDER).not.toContain('const wantsSystemAudio = !!opts.audio');
        expect(RECORDER).not.toContain('const wantsMic = !!opts.mic');
    });

    it('refuses a meeting with no audio source rather than recording silence', () => {
        // Finding out at the end that the transcript is empty is the worst possible moment.
        expect(RECORDER).toContain("return { ok: false, error: 'no audio source selected' }");
    });

    it('sends the names and the mode the wizard collected', () => {
        expect(RECORDER).toContain('names: Array.isArray(opts.names) ? opts.names : []');
        expect(RECORDER).toContain('assistant_names: Array.isArray(opts.assistantNames)');
        expect(RECORDER).toContain("mode: opts.mode || ''");
        expect(PROVIDER).toContain('names: parseNames(capture.myNames)');
        expect(PROVIDER).toContain('assistantNames: parseNames(capture.assistantName)');
    });
});
