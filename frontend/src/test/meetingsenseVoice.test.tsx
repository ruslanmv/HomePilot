/**
 * The mode badge, the consent copy, and the setup wizard (batch MS27).
 *
 * Three things a browser owns, and all three are about telling the truth about what is running.
 *
 * The pill is §2a's "recording state is unmissable", and MS27 changes what a recording can *be*
 * — Coach reads a document, Practice speaks aloud into the call. A pill that said only
 * "recording" would be accurate and would hide the part that matters.
 *
 * The wizard's job is the *check*. A setup flow that ends on "you're all set" without verifying
 * is how somebody arrives at a mock interview with no sound and no idea which of four steps
 * did not take.
 */
import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import axe from 'axe-core';

import { RecordingPill } from '../ui/meetingsense/RecordingPill';
import { VoiceSetup } from '../ui/meetingsense/VoiceSetup';
import { EMPTY_VIEW, consentSentences, modeLabel } from '../ui/meetingsense/meetingState';

const LIVE = { ...EMPTY_VIEW, phase: 'live' as const, elapsedMs: 60_000 };

// ── the mode badge ──────────────────────────────────────────────────────────

describe('the mode on the pill', () => {
    it('names each speaking mode', () => {
        expect(modeLabel('participant')).toBe('Participant');
        expect(modeLabel('presenter')).toBe('Presenter');
        expect(modeLabel('coach')).toBe('Coach');
        expect(modeLabel('practice')).toBe('Practice');
    });

    it('leaves note-taker unlabelled', () => {
        // A badge that is always there is a badge nobody reads, which would cost it its
        // meaning in the four modes where it matters.
        expect(modeLabel('note-taker')).toBe('');
        expect(modeLabel(null)).toBe('');
    });

    it('reads "Coach" on the pill', () => {
        // The batch row asks for this one by name.
        render(<RecordingPill view={{ ...LIVE, mode: 'coach' }} />);
        expect(screen.getByTestId('ms-mode').textContent).toBe('Coach');
    });

    it('shows no badge in note-taker', () => {
        render(<RecordingPill view={{ ...LIVE, mode: 'note-taker' }} />);
        expect(screen.queryByTestId('ms-mode')).toBeNull();
    });

    it('announces the badge rather than only drawing it', () => {
        // A screen-reader user has no badge to glance at, and "the assistant is about to speak
        // into this call" is not something they should have to go looking for. Being *inside*
        // the live region is not enough — the meter is inside it too and is `aria-hidden`,
        // which is right for a meter and would be silence here.
        render(<RecordingPill view={{ ...LIVE, mode: 'practice' }} />);
        const pill = screen.getByTestId('ms-pill');
        const badge = screen.getByTestId('ms-mode');
        expect(pill.getAttribute('aria-live')).toBe('polite');
        expect(pill.contains(badge)).toBe(true);
        expect(badge.getAttribute('aria-hidden')).toBeNull();
        expect(badge.closest('[aria-hidden="true"]')).toBeNull();
    });

    it('shows the audience queue when there is one', () => {
        render(<RecordingPill view={{ ...LIVE, mode: 'presenter', queued: 3 }} />);
        expect(screen.getByTestId('ms-queued').textContent).toBe('3 questions waiting');
    });

    it('says "question" for one', () => {
        render(<RecordingPill view={{ ...LIVE, mode: 'presenter', queued: 1 }} />);
        expect(screen.getByTestId('ms-queued').textContent).toBe('1 question waiting');
    });

    it('shows nothing when the queue is empty', () => {
        render(<RecordingPill view={{ ...LIVE, mode: 'presenter', queued: 0 }} />);
        expect(screen.queryByTestId('ms-queued')).toBeNull();
    });

    it('has no axe violations with a badge on', async () => {
        const { container } = render(
            <RecordingPill view={{ ...LIVE, mode: 'coach', queued: 2 }} />,
        );
        const results = await axe.run(container);
        expect(results.violations.map((v) => v.id)).toEqual([]);
    });
});

// ── consent copy ────────────────────────────────────────────────────────────

describe('consent copy says what the mode does', () => {
    const base = { stt: { provider: 'whisper' }, retention: 'text' };

    it('coach says where its suggestions come from and where they do not', () => {
        const lines = consentSentences({ ...base, mode: 'coach' }).join(' ');
        expect(lines).toMatch(/prep material you uploaded/);
        // The refusal, in the consent sheet, in the user's words. It is enforced in
        // `coaching.py`; this is where the user is told about it.
        expect(lines).toMatch(/not given anything read off your screen/);
    });

    it('practice warns that everyone will hear it', () => {
        // A synthetic voice in a call that nobody else agreed to is the thing a consent sheet
        // exists for.
        const lines = consentSentences({ ...base, mode: 'practice' }).join(' ');
        expect(lines).toMatch(/speaks aloud into the call/);
        expect(lines).toMatch(/Everyone in the meeting will hear it/);
    });

    it('participant says it answers out loud, and drafts rather than answers for you', () => {
        const lines = consentSentences({ ...base, mode: 'participant' }).join(' ');
        expect(lines).toMatch(/answers out loud when somebody in the call says its name/);
        expect(lines).toMatch(/never answered for you/);
    });

    it('presenter says nothing is said out loud', () => {
        expect(consentSentences({ ...base, mode: 'presenter' }).join(' '))
            .toMatch(/Nothing is said out loud while you are presenting/);
    });

    it('note-taker adds nothing, and the recording sentences are untouched', () => {
        // The floor. Its consent copy is what MS6 shipped, byte for byte.
        const plain = consentSentences(base);
        expect(consentSentences({ ...base, mode: 'note-taker' })).toEqual(plain);
        expect(consentSentences({ ...base, mode: null })).toEqual(plain);
    });

    it('every mode still carries the recording sentences', () => {
        for (const mode of ['coach', 'practice', 'participant', 'presenter'] as const) {
            const lines = consentSentences({ ...base, mode });
            expect(lines.some((l) => /transcribed on this machine/.test(l))).toBe(true);
            expect(lines.some((l) => /Tell the other people/.test(l))).toBe(true);
        }
    });

    it('the telling-people sentence is always last', () => {
        // It is the one thing the user has to do, so it is the one they read last and act on.
        for (const mode of ['coach', 'practice', null] as const) {
            const lines = consentSentences({ ...base, mode });
            expect(lines[lines.length - 1]).toMatch(/Tell the other people/);
        }
    });
});

// ── the setup wizard ────────────────────────────────────────────────────────

describe('VoiceSetup', () => {
    const GUIDE = {
        system: 'Darwin',
        product: 'BlackHole',
        url: 'https://existential.audio/blackhole/',
        steps: ['Install BlackHole (2ch).', 'Create a Multi-Output Device.', 'Set the mic.'],
    };
    const NEEDS = {
        ok: false, reason: 'no_virtual_device' as const,
        detail: 'No virtual audio device found. Install BlackHole and set your mic to it.',
        guide: GUIDE,
    };

    it('shows the steps and where to get the driver', () => {
        render(<VoiceSetup capability={NEEDS} />);
        expect(screen.getByTestId('ms-voice-steps').querySelectorAll('li').length).toBe(3);
        expect(screen.getByTestId('ms-voice-link').getAttribute('href')).toBe(GUIDE.url);
    });

    it('says it is ready, and names the device', () => {
        render(<VoiceSetup capability={{ ok: true, device: 'BlackHole 2ch' }} />);
        expect(screen.getByText(/BlackHole 2ch/)).toBeTruthy();
        expect(screen.queryByTestId('ms-voice-steps')).toBeNull();
    });

    it('offers a browser no driver it cannot use, and no retry that cannot work', () => {
        // With `onCheck` wired, which is the case that matters: re-checking in a browser can
        // never succeed, so a "Check again" button here is the wizard proposing a fix it knows
        // will fail. The refusal is also announced — it is the answer to "can I use this".
        const onCheck = vi.fn(async () => ({ ok: false, reason: 'browser' }));
        render(
            <VoiceSetup
                capability={{
                    ok: false, reason: 'browser',
                    detail: 'Speaking into a meeting needs the desktop app.',
                }}
                onCheck={onCheck}
            />,
        );
        expect(screen.getByText(/needs the desktop app/)).toBeTruthy();
        expect(screen.queryByTestId('ms-voice-steps')).toBeNull();
        expect(screen.queryByTestId('ms-voice-check')).toBeNull();
        expect(screen.getByTestId('ms-voice-setup').getAttribute('role')).toBe('status');
        expect(onCheck).not.toHaveBeenCalled();
    });

    it('checks rather than congratulating', async () => {
        // The whole reason the wizard has a last step.
        const onCheck = vi.fn(async () => ({ ok: true, device: 'BlackHole 2ch' }));
        render(<VoiceSetup capability={NEEDS} onCheck={onCheck} />);
        fireEvent.click(screen.getByTestId('ms-voice-check'));
        await waitFor(() => expect(screen.getByText(/BlackHole 2ch/)).toBeTruthy());
        expect(onCheck).toHaveBeenCalled();
    });

    it('a failed check says so instead of moving on', async () => {
        const onCheck = vi.fn(async () => NEEDS);
        render(<VoiceSetup capability={NEEDS} onCheck={onCheck} />);
        fireEvent.click(screen.getByTestId('ms-voice-check'));
        await waitFor(() => expect(screen.getByTestId('ms-voice-failed')).toBeTruthy());
        expect(screen.getByTestId('ms-voice-steps')).toBeTruthy();
    });

    it('renders nothing before the capability is known', () => {
        const { container } = render(<VoiceSetup capability={null} />);
        expect(container.innerHTML).toBe('');
    });

    it('has no axe violations', async () => {
        const { container } = render(<VoiceSetup capability={NEEDS} onCheck={async () => NEEDS} />);
        const results = await axe.run(container);
        expect(results.violations.map((v) => v.id)).toEqual([]);
    });
});
