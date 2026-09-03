/**
 * The live card, the pill and the consent sheet (batch MS6).
 *
 * These test the §2a bar rather than the markup, because the markup is not the promise. The
 * promises are: nothing already shown changes, the reader is never yanked, a slow transcript
 * says it is slow, and Stop can be taken back without losing what was said while deciding.
 *
 * One limit is worth stating plainly rather than papering over. jsdom does not lay out or
 * paint, so `offsetHeight` is zero for everything and "the DOM height is identical before and
 * after a partial solidifies" **cannot be measured here**. What is asserted instead is the
 * structural fact underneath it — the provisional line and the real line are the same element
 * with the same class, and solidifying replaces it in place rather than adding a row. Pixels
 * belong to the manual matrix.
 */
import React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';
import axe from 'axe-core';

import { MeetingCard } from '../ui/meetingsense/MeetingCard';
import { SlideStrip } from '../ui/meetingsense/SlideStrip';
import { RecordingPill } from '../ui/meetingsense/RecordingPill';
import {
    ConsentSheet,
    CONSENT_STORAGE_KEY,
    consentAcknowledged,
    rememberConsent,
} from '../ui/meetingsense/ConsentSheet';
import { useMeetingSense } from '../ui/meetingsense/useMeetingSense';
import {
    BEHIND_THRESHOLD_MS,
    EMPTY_VIEW,
    consentSentences,
    elapsedLabel,
    latencyLabel,
    mergeSegment,
    mergeSlide,
    meterLevel,
    segmentsDuring,
    slideLabel,
    phaseLabel,
    shouldStickToBottom,
    speakerLabel,
    stampLabel,
    type MeetingView,
} from '../ui/meetingsense/meetingState';

function view(overrides: Partial<MeetingView> = {}): MeetingView {
    return { ...EMPTY_VIEW, phase: 'live', ...overrides };
}

const seg = (id: string, text: string, extra = {}) => ({ id, text, t0: 1000, speaker: 'them', ...extra });

// ── the state functions ─────────────────────────────────────────────────────

describe('mergeSegment', () => {
    it('appends a new segment', () => {
        expect(mergeSegment([], seg('a', 'one'))).toHaveLength(1);
    });

    it('ignores a segment it already has', () => {
        // Resume replays: after a reconnect the server re-sends everything above the sequence
        // the client acknowledged, and some of it is already on screen. Without this the last
        // few lines double at exactly the moment a "reconnecting" pill has already unsettled
        // the reader.
        const first = [seg('a', 'one')];
        expect(mergeSegment(first, seg('a', 'one'))).toBe(first);
    });

    it('keeps the copy already on screen rather than swapping in an identical one', () => {
        const shown = seg('a', 'one');
        const result = mergeSegment([shown], { ...shown });
        expect(result[0]).toBe(shown);
    });

    it('orders by sequence, not by arrival', () => {
        // A replayed segment can arrive after a newer live one. Appending would put an older
        // line at the bottom of the transcript.
        const out = mergeSegment([seg('a', 'one', { seq: 5 })], seg('b', 'two', { seq: 2 }));
        expect(out.map((s) => s.id)).toEqual(['b', 'a']);
    });

    it('appends when there is no sequence to order by', () => {
        const out = mergeSegment([seg('a', 'one')], seg('b', 'two'));
        expect(out.map((s) => s.id)).toEqual(['a', 'b']);
    });
});

describe('labels', () => {
    it('shows minutes and seconds, and hours only once there are any', () => {
        expect(elapsedLabel(65_000)).toBe('01:05');
        expect(elapsedLabel(3_725_000)).toBe('1:02:05');
    });

    it('pads a transcript stamp to three parts so the column stays aligned', () => {
        expect(stampLabel(65_000)).toBe('00:01:05');
        expect(stampLabel(undefined)).toBe('00:00:00');
    });

    it('turns wire speakers into words', () => {
        expect(speakerLabel('me')).toBe('You');
        expect(speakerLabel('them')).toBe('Them');
        expect(speakerLabel(null)).toBe('Speaker');
    });
});

describe('latencyLabel', () => {
    it('says nothing while the transcript is keeping up', () => {
        // A label that flickers on every sentence is worse than none: a transcript one
        // utterance behind is working normally.
        expect(latencyLabel(0)).toBeNull();
        expect(latencyLabel(BEHIND_THRESHOLD_MS - 1)).toBeNull();
    });

    it('says how far behind once it matters', () => {
        expect(latencyLabel(12_000)).toBe('catching up · 12 s behind');
    });
});

describe('phaseLabel', () => {
    it('names one thing at a time', () => {
        expect(phaseLabel(view({ phase: 'reconnecting', behindMs: 30_000 }))).toBe('reconnecting…');
        expect(phaseLabel(view({ phase: 'stopping' }))).toBe('stopping…');
        expect(phaseLabel(view())).toBe('recording');
    });

    it('prefers the latency to the plain word when there is one', () => {
        expect(phaseLabel(view({ behindMs: 9_000 }))).toBe('catching up · 9 s behind');
    });
});

describe('shouldStickToBottom', () => {
    it('is true at the bottom', () => {
        expect(shouldStickToBottom({ scrollTop: 900, scrollHeight: 1000, clientHeight: 100 })).toBe(true);
    });

    it('is false once the reader has scrolled up', () => {
        expect(shouldStickToBottom({ scrollTop: 200, scrollHeight: 1000, clientHeight: 100 })).toBe(false);
    });

    it('allows a little slack, so a pixel of drift does not unstick it', () => {
        expect(shouldStickToBottom({ scrollTop: 880, scrollHeight: 1000, clientHeight: 100 })).toBe(true);
    });
});

describe('meterLevel', () => {
    it('clamps rather than overflowing the bar', () => {
        expect(meterLevel([1])).toBe(1);
        expect(meterLevel([])).toBe(0);
    });

    it('follows the loudest channel', () => {
        expect(meterLevel([0, 0.1])).toBeCloseTo(0.6, 5);
    });
});

describe('consentSentences', () => {
    it('names the local model and says the audio stays put', () => {
        const lines = consentSentences({ stt: { provider: 'whisper-local' }, retention: 'text' });
        expect(lines[0]).toContain('whisper-local');
        expect(lines[0]).toMatch(/does not leave/);
    });

    it('says plainly when audio leaves the machine', () => {
        // Somebody who set STT_BASE_URL months ago for voice calls would otherwise ship an
        // hour of a board meeting to it having agreed only to "recording".
        const lines = consentSentences({ stt: { provider: 'openai-compat', remote: true } });
        expect(lines[0]).toContain('openai-compat');
        expect(lines[0]).toMatch(/is sent to/);
    });

    it('never shows the endpoint itself', () => {
        const lines = consentSentences({ stt: { provider: 'openai-compat', remote: true } });
        expect(lines.join(' ')).not.toMatch(/https?:\/\//);
    });

    it('describes what each retention mode keeps', () => {
        expect(consentSentences({ retention: 'text' })[1]).toMatch(/Only the transcript/);
        expect(consentSentences({ retention: 'text+frames' })[1]).toMatch(/slide images/);
        expect(consentSentences({ retention: 'all' })[1]).toMatch(/audio/);
    });

    it('always reminds the user to tell the room', () => {
        for (const retention of ['text', 'all']) {
            expect(consentSentences({ retention }).at(-1)).toMatch(/Tell the other people/);
        }
    });
});

// ── the card ────────────────────────────────────────────────────────────────

describe('MeetingCard', () => {
    it('renders each segment as a paragraph carrying its start time', () => {
        // `data-t0` is data, not decoration: MS10's slide join reads it.
        render(<MeetingCard view={view({ segments: [seg('a', 'the launch moves')] })} />);
        const line = screen.getByTestId('ms-segment');
        expect(line.tagName).toBe('P');
        expect(line.dataset.t0).toBe('1000');
        expect(line.textContent).toContain('the launch moves');
    });

    it('is a labelled, polite live region', () => {
        // A screen-reader user has no visual transcript; without this, lines arrive silently.
        render(<MeetingCard view={view()} />);
        const region = screen.getByTestId('ms-transcript');
        expect(region.getAttribute('aria-label')).toBe('Live transcript');
        expect(region.getAttribute('aria-live')).toBe('polite');
    });

    it('renders a provisional line as the same element as a real one', () => {
        // jsdom cannot measure height, so this is the structural fact underneath "no layout
        // jump": same tag, same base class, so the same CSS box applies and solidifying does
        // not change the shape of the row.
        const { rerender } = render(<MeetingCard view={view({ partial: { text: 'the launch', t0: 1000 } })} />);
        const provisional = screen.getByTestId('ms-partial');
        expect(provisional.tagName).toBe('P');
        expect(provisional.className.split(' ')).toContain('ms-line');

        rerender(<MeetingCard view={view({ segments: [seg('a', 'the launch moves')] })} />);
        const solid = screen.getByTestId('ms-segment');
        expect(solid.tagName).toBe(provisional.tagName);
        expect(solid.className.split(' ')).toContain('ms-line');
    });

    it('does not leave the provisional line beside the real one', () => {
        const { rerender } = render(<MeetingCard view={view({ partial: { text: 'the launch' } })} />);
        rerender(<MeetingCard view={view({ segments: [seg('a', 'the launch moves')], partial: null })} />);
        expect(screen.queryByTestId('ms-partial')).toBeNull();
        expect(screen.getAllByTestId('ms-segment')).toHaveLength(1);
    });

    it('keeps every line it had after a re-render', () => {
        // §2a: nothing already shown changes. A card that dropped a line on re-render would
        // be rewriting history, which is how a reader stops trusting a live transcript.
        const segments = [seg('a', 'one'), seg('b', 'two'), seg('c', 'three')];
        const { rerender } = render(<MeetingCard view={view({ segments })} />);
        const before = screen.getAllByTestId('ms-segment').map((n) => n.textContent);
        rerender(<MeetingCard view={view({ segments, behindMs: 9_000 })} />);
        const after = screen.getAllByTestId('ms-segment').map((n) => n.textContent);
        expect(after.slice(0, before.length)).toEqual(before);
    });

    it('says how far behind it is once that matters', () => {
        render(<MeetingCard view={view({ behindMs: 12_000 })} />);
        expect(screen.getByTestId('ms-behind').textContent).toBe('catching up · 12 s behind');
    });

    it('says nothing about latency while it is keeping up', () => {
        render(<MeetingCard view={view({ behindMs: 500 })} />);
        expect(screen.queryByTestId('ms-behind')).toBeNull();
    });

    it('shows a reconnecting state', () => {
        render(<MeetingCard view={view({ phase: 'reconnecting' })} />);
        expect(screen.getByTestId('ms-reconnecting')).toBeTruthy();
    });

    it('distinguishes an empty live meeting from an empty ended one', () => {
        // "Listening" and "nothing was transcribed" are different claims, and the reader
        // cannot tell which they are looking at from a blank box.
        const { rerender } = render(<MeetingCard view={view()} />);
        expect(screen.getByTestId('ms-empty').textContent).toMatch(/Listening/);
        rerender(<MeetingCard view={view({ phase: 'ended' })} />);
        expect(screen.getByTestId('ms-empty').textContent).toMatch(/Nothing was transcribed/);
    });

    it('offers export only once the meeting has ended', () => {
        const onExport = vi.fn();
        const { rerender } = render(<MeetingCard view={view()} onExport={onExport} />);
        expect(screen.queryByTestId('ms-export-md')).toBeNull();
        rerender(<MeetingCard view={view({ phase: 'ended' })} onExport={onExport} />);
        fireEvent.click(screen.getByTestId('ms-export-srt'));
        expect(onExport).toHaveBeenCalledWith('srt');
    });

    it('collapses to the last few lines when compact', () => {
        // A phone shows the summary and the tail; the whole transcript is a scroll trap on a
        // 380 px screen.
        const segments = Array.from({ length: 10 }, (_, i) => seg(`s${i}`, `line ${i}`));
        render(<MeetingCard view={view({ segments })} compact lastLines={3} />);
        const lines = screen.getAllByTestId('ms-segment');
        expect(lines).toHaveLength(3);
        expect(lines.at(-1)!.textContent).toContain('line 9');
    });
});

describe('MeetingCard scrolling', () => {
    function scrollerOf() {
        return screen.getByTestId('ms-transcript') as HTMLElement;
    }

    function place(el: HTMLElement, { scrollTop, scrollHeight, clientHeight }: Record<string, number>) {
        // jsdom has no layout, so the geometry is supplied. The logic under test is the
        // decision made *from* that geometry, which is the part with a bug in it.
        Object.defineProperty(el, 'scrollHeight', { value: scrollHeight, configurable: true });
        Object.defineProperty(el, 'clientHeight', { value: clientHeight, configurable: true });
        el.scrollTop = scrollTop;
    }

    it('follows the transcript down while the reader is at the bottom', () => {
        const segments = [seg('a', 'one')];
        const { rerender } = render(<MeetingCard view={view({ segments })} />);
        const el = scrollerOf();
        place(el, { scrollTop: 900, scrollHeight: 1000, clientHeight: 100 });
        fireEvent.scroll(el);

        place(el, { scrollTop: 900, scrollHeight: 2000, clientHeight: 100 });
        rerender(<MeetingCard view={view({ segments: [...segments, seg('b', 'two')] })} />);
        expect(el.scrollTop).toBe(2000);
    });

    it('leaves the reader where they are once they have scrolled up', () => {
        // The single most irritating thing a live transcript can do is yank somebody back to
        // the bottom mid-sentence.
        const segments = [seg('a', 'one')];
        const { rerender } = render(<MeetingCard view={view({ segments })} />);
        const el = scrollerOf();
        place(el, { scrollTop: 200, scrollHeight: 1000, clientHeight: 100 });
        fireEvent.scroll(el);

        rerender(<MeetingCard view={view({ segments: [...segments, seg('b', 'two')] })} />);
        expect(el.scrollTop).toBe(200);
    });

    it('offers a way back, counting what was missed', () => {
        const segments = [seg('a', 'one')];
        const { rerender } = render(<MeetingCard view={view({ segments })} />);
        const el = scrollerOf();
        place(el, { scrollTop: 200, scrollHeight: 1000, clientHeight: 100 });
        fireEvent.scroll(el);

        rerender(<MeetingCard view={view({ segments: [...segments, seg('b', 'two')] })} />);
        rerender(<MeetingCard view={view({ segments: [...segments, seg('b', 'two'), seg('c', 'three')] })} />);
        const jump = screen.getByTestId('ms-jump');
        expect(jump.textContent).toContain('2 new lines');

        place(el, { scrollTop: 200, scrollHeight: 3000, clientHeight: 100 });
        fireEvent.click(jump);
        expect(el.scrollTop).toBe(3000);
        expect(screen.queryByTestId('ms-jump')).toBeNull();
    });

    it('does not offer it while the reader is already at the bottom', () => {
        render(<MeetingCard view={view({ segments: [seg('a', 'one')] })} />);
        expect(screen.queryByTestId('ms-jump')).toBeNull();
    });
});

// ── the pill ────────────────────────────────────────────────────────────────

describe('RecordingPill', () => {
    it('is absent when nothing is recording', () => {
        render(<RecordingPill view={view({ phase: 'idle' })} />);
        expect(screen.queryByTestId('ms-pill')).toBeNull();
    });

    it('announces itself to assistive technology', () => {
        // A screen-reader user has no red dot, and "recording" is the one thing they must not
        // have to go looking for.
        render(<RecordingPill view={view()} />);
        const pill = screen.getByTestId('ms-pill');
        expect(pill.getAttribute('role')).toBe('status');
        expect(pill.getAttribute('aria-live')).toBe('polite');
    });

    it('shows the elapsed time, the provider and what is being captured', () => {
        render(<RecordingPill view={view({ elapsedMs: 65_000, provider: 'whisper-local', audioMode: 'system+mic' })} />);
        expect(screen.getByTestId('ms-elapsed').textContent).toBe('01:05');
        expect(screen.getByTestId('ms-capture').textContent).toBe('whisper-local · system+mic');
    });

    it('draws the level meter from the recorder', () => {
        render(<RecordingPill view={view({ levels: [0, 0.1] })} />);
        const fill = screen.getByTestId('ms-meter').firstElementChild as HTMLElement;
        expect(fill.style.width).toBe('60%');
    });

    it('carries the mute state where a screen reader can read it', () => {
        const onMute = vi.fn();
        render(<RecordingPill view={view({ micMuted: true })} onMute={onMute} />);
        const mute = screen.getByTestId('ms-mute');
        expect(mute.getAttribute('aria-pressed')).toBe('true');
        fireEvent.click(mute);
        expect(onMute).toHaveBeenCalledWith(false);
    });

    it('swaps stop and mute for undo while stopping', () => {
        render(<RecordingPill view={view({ phase: 'stopping' })} undoSecondsLeft={7} />);
        expect(screen.getByTestId('ms-undo').textContent).toBe('Undo · 7s');
        expect(screen.queryByTestId('ms-stop')).toBeNull();
    });

    it('says what it is doing, one thing at a time', () => {
        const { rerender } = render(<RecordingPill view={view({ behindMs: 8_000 })} />);
        expect(screen.getByTestId('ms-pill').textContent).toContain('catching up · 8 s behind');
        rerender(<RecordingPill view={view({ phase: 'reconnecting', behindMs: 8_000 })} />);
        const text = screen.getByTestId('ms-pill').textContent!;
        expect(text).toContain('reconnecting…');
        expect(text).not.toContain('catching up');
    });
});

// ── consent ─────────────────────────────────────────────────────────────────

describe('ConsentSheet', () => {
    beforeEach(() => {
        window.localStorage.clear();
    });

    it('names the provider it is about to send audio to', () => {
        render(
            <ConsentSheet
                status={{ stt: { provider: 'openai-compat', remote: true } }}
                onAccept={vi.fn()}
                onCancel={vi.fn()}
            />,
        );
        expect(screen.getByTestId('ms-consent').textContent).toContain('openai-compat');
    });

    it('is a real modal dialog', () => {
        render(<ConsentSheet status={null} onAccept={vi.fn()} onCancel={vi.fn()} />);
        const sheet = screen.getByTestId('ms-consent');
        expect(sheet.getAttribute('role')).toBe('dialog');
        expect(sheet.getAttribute('aria-modal')).toBe('true');
        expect(sheet.getAttribute('aria-labelledby')).toBeTruthy();
    });

    it('traps Tab inside itself', () => {
        // Tabbing out of a consent sheet and starting a recording from a control behind it is
        // exactly the outcome the sheet exists to prevent.
        render(<ConsentSheet status={null} onAccept={vi.fn()} onCancel={vi.fn()} />);
        const sheet = screen.getByTestId('ms-consent');
        const focusable = sheet.querySelectorAll<HTMLElement>('button, input');
        const last = focusable[focusable.length - 1];
        last.focus();
        fireEvent.keyDown(sheet, { key: 'Tab' });
        expect(document.activeElement).toBe(focusable[0]);
    });

    it('traps Shift+Tab too', () => {
        // Both directions, because a trap that only holds one way is not a trap — and the
        // backwards branch is the one a test written forwards never touches.
        render(<ConsentSheet status={null} onAccept={vi.fn()} onCancel={vi.fn()} />);
        const sheet = screen.getByTestId('ms-consent');
        const focusable = sheet.querySelectorAll<HTMLElement>('button, input');
        focusable[0].focus();
        fireEvent.keyDown(sheet, { key: 'Tab', shiftKey: true });
        expect(document.activeElement).toBe(focusable[focusable.length - 1]);
    });

    it('cancels on Escape', () => {
        const onCancel = vi.fn();
        render(<ConsentSheet status={null} onAccept={vi.fn()} onCancel={onCancel} />);
        fireEvent.keyDown(screen.getByTestId('ms-consent'), { key: 'Escape' });
        expect(onCancel).toHaveBeenCalled();
    });

    it('reports whether the box was ticked', () => {
        const onAccept = vi.fn();
        render(<ConsentSheet status={null} onAccept={onAccept} onCancel={vi.fn()} />);
        fireEvent.click(screen.getByTestId('ms-consent-remember'));
        fireEvent.click(screen.getByTestId('ms-consent-accept'));
        expect(onAccept).toHaveBeenCalledWith(true);
    });

    it('remembers per machine', () => {
        expect(consentAcknowledged()).toBe(false);
        rememberConsent();
        expect(window.localStorage.getItem(CONSENT_STORAGE_KEY)).toBe('true');
        expect(consentAcknowledged()).toBe(true);
    });

    it('shows the sheet again rather than throwing when storage is blocked', () => {
        // Private mode. Showing consent one extra time is the safe direction to be wrong in.
        const blocked = {
            getItem() {
                throw new Error('blocked');
            },
            setItem() {
                throw new Error('blocked');
            },
        } as unknown as Storage;
        expect(consentAcknowledged(blocked)).toBe(false);
        expect(() => rememberConsent(blocked)).not.toThrow();
    });
});

// ── accessibility ───────────────────────────────────────────────────────────

describe('accessibility', () => {
    const run = async () =>
        (await axe.run(document.body, { rules: { 'color-contrast': { enabled: false } } })).violations.map(
            (v) => v.id,
        );

    it('the live card and pill have no violations', async () => {
        render(
            <div>
                <RecordingPill view={view({ provider: 'whisper-local', audioMode: 'system+mic' })} />
                <MeetingCard view={view({ segments: [seg('a', 'one')], partial: { text: 'two' } })} />
            </div>,
        );
        expect(await run()).toEqual([]);
    });

    it('the degraded states have none either', async () => {
        // The tree a user in trouble actually reads: reconnecting, behind, with an error.
        render(
            <div>
                <RecordingPill view={view({ phase: 'reconnecting', behindMs: 20_000 })} />
                <MeetingCard view={view({ phase: 'reconnecting', behindMs: 20_000, error: 'stt_unavailable' })} />
            </div>,
        );
        expect(await run()).toEqual([]);
    });

    it('the consent sheet has none', async () => {
        render(<ConsentSheet status={{ stt: { provider: 'whisper-local' } }} onAccept={vi.fn()} onCancel={vi.fn()} />);
        expect(await run()).toEqual([]);
    });
});

// ── the hook ────────────────────────────────────────────────────────────────

describe('useMeetingSense', () => {
    function Harness({ recorder, target }: { recorder: any; target: EventTarget }) {
        const ms = useMeetingSense({ recorder, target, provider: 'whisper-local' });
        (Harness as any).last = ms;
        return (
            <div>
                <RecordingPill view={ms.view} undoSecondsLeft={ms.undoSecondsLeft} onStop={ms.stop} onUndo={ms.undo} />
                <MeetingCard view={ms.view} />
            </div>
        );
    }

    let target: EventTarget;
    let recorder: any;

    beforeEach(() => {
        vi.useFakeTimers();
        target = new EventTarget();
        recorder = {
            start: vi.fn(async () => ({ ok: true, meetingId: 'm1' })),
            stop: vi.fn(async () => ({ ok: true })),
            muteMic: vi.fn(),
            levels: [0.1],
            audioMode: 'system+mic',
        };
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    const emit = (name: string, detail: unknown) =>
        act(() => {
            target.dispatchEvent(new CustomEvent(name, { detail }));
        });

    it('turns segment events into lines', () => {
        render(<Harness recorder={recorder} target={target} />);
        act(() => {
            (Harness as any).last.setPhase('live');
        });
        emit('ms:segment', { id: 'a', text: 'the launch moves', t0: 1000, seq: 1 });
        expect(screen.getByTestId('ms-segment').textContent).toContain('the launch moves');
    });

    it('never doubles a replayed segment', () => {
        render(<Harness recorder={recorder} target={target} />);
        emit('ms:segment', { id: 'a', text: 'one', seq: 1 });
        emit('ms:segment', { id: 'a', text: 'one', seq: 1, replayed: true });
        expect(screen.getAllByTestId('ms-segment')).toHaveLength(1);
    });

    it('clears the provisional line when the real one lands', () => {
        render(<Harness recorder={recorder} target={target} />);
        emit('ms:partial', { text: 'the launch' });
        expect(screen.getByTestId('ms-partial')).toBeTruthy();
        emit('ms:segment', { id: 'a', text: 'the launch moves', seq: 1 });
        expect(screen.queryByTestId('ms-partial')).toBeNull();
    });

    it('follows the recorder into and out of a reconnect', () => {
        render(<Harness recorder={recorder} target={target} />);
        emit('ms:reconnecting', { attempt: 1, delay: 1000 });
        expect(screen.getByTestId('ms-reconnecting')).toBeTruthy();
        emit('ms:resumed', { meeting_id: 'm1' });
        expect(screen.queryByTestId('ms-reconnecting')).toBeNull();
    });

    it('reads behind_ms into the catching-up label', () => {
        render(<Harness recorder={recorder} target={target} />);
        emit('ms:status', { behind_ms: 9_000 });
        expect(screen.getByTestId('ms-behind').textContent).toContain('9 s behind');
    });

    it('keeps recording through the undo window', async () => {
        // The whole point. A Stop that stopped immediately would make Undo a lie: the ten
        // seconds somebody spends deciding are usually ten seconds somebody else was talking.
        render(<Harness recorder={recorder} target={target} />);
        await act(async () => {
            (Harness as any).last.stop();
        });
        expect(screen.getByTestId('ms-undo')).toBeTruthy();
        expect(recorder.stop).not.toHaveBeenCalled();

        emit('ms:segment', { id: 'late', text: 'one more thing', seq: 9 });
        expect(screen.getByTestId('ms-segment').textContent).toContain('one more thing');
    });

    it('undo puts it straight back to live with no gap', async () => {
        render(<Harness recorder={recorder} target={target} />);
        await act(async () => {
            (Harness as any).last.stop();
        });
        await act(async () => {
            (Harness as any).last.undo();
        });
        await act(async () => {
            await vi.advanceTimersByTimeAsync(20_000);
        });
        expect(recorder.stop).not.toHaveBeenCalled();
        expect(screen.getByTestId('ms-stop')).toBeTruthy();
    });

    it('stops for real once the window closes', async () => {
        render(<Harness recorder={recorder} target={target} />);
        await act(async () => {
            (Harness as any).last.stop();
        });
        await act(async () => {
            await vi.advanceTimersByTimeAsync(10_000);
        });
        expect(recorder.stop).toHaveBeenCalledTimes(1);
    });

    it('counts the undo window down', async () => {
        render(<Harness recorder={recorder} target={target} />);
        await act(async () => {
            (Harness as any).last.stop();
        });
        expect(screen.getByTestId('ms-undo').textContent).toBe('Undo · 10s');
        await act(async () => {
            await vi.advanceTimersByTimeAsync(3_000);
        });
        expect(screen.getByTestId('ms-undo').textContent).toBe('Undo · 7s');
    });

    it('a second stop does not shorten the window', async () => {
        render(<Harness recorder={recorder} target={target} />);
        await act(async () => {
            (Harness as any).last.stop();
        });
        await act(async () => {
            await vi.advanceTimersByTimeAsync(5_000);
            (Harness as any).last.stop();
            await vi.advanceTimersByTimeAsync(4_000);
        });
        expect(recorder.stop).not.toHaveBeenCalled();
    });

    it('refuses to start when the recorder script is not loaded', async () => {
        render(<Harness recorder={null} target={target} />);
        const result = await (Harness as any).last.start({ conversationId: 'c' });
        expect(result.ok).toBe(false);
    });
});

// ── slides (MS10) ───────────────────────────────────────────────────────────

/**
 * The strip is a renderer; the join is the claim. A slide on its own is a picture of a screen,
 * and a picture of a screen is not why anybody records a meeting — joined to the words spoken
 * while it was up, it answers "what were they saying when this chart was on?".
 *
 * The boundary is where a join like this is right or wrong, so most of these are about one
 * millisecond either side of a slide change.
 */

const slide = (id: string, t: number, caption: string | null = null) => ({
    id,
    t,
    url: `/files/${id}.jpg`,
    caption,
});

const at = (id: string, t0: number, text: string) => ({ id, t0, text, speaker: 'them' as const });

describe('mergeSlide', () => {
    it('upserts on id, because one slide arrives twice', () => {
        // Taken, then captioned. Appending both would put the same picture in the strip twice
        // with one of them blank.
        const taken = mergeSlide([], slide('k1', 4000));
        const captioned = mergeSlide(taken, { id: 'k1', t: 4000, url: '/files/k1.jpg', caption: 'Q3 revenue.' });
        expect(captioned).toHaveLength(1);
        expect(captioned[0].caption).toBe('Q3 revenue.');
    });

    it('merges rather than replaces, so a caption-only frame keeps the url', () => {
        const taken = mergeSlide([], slide('k1', 4000));
        const merged = mergeSlide(taken, { id: 'k1', url: '', caption: 'Q3 revenue.' } as any);
        expect(merged[0].url).toBe('/files/k1.jpg');
    });

    it('never blanks a caption already on screen with a later empty one', () => {
        // The two frames for one slide can arrive in either order across a reconnect, and a
        // `caption: null` from the "taken" frame landing second would erase a caption the
        // reader has already read — which is exactly what §2a forbids.
        const captioned = mergeSlide([], { ...slide('k1', 4000), caption: 'Q3 revenue.' });
        const later = mergeSlide(captioned, slide('k1', 4000));
        expect(later[0].caption).toBe('Q3 revenue.');
    });

    it('keeps the strip in time order however the frames arrive', () => {
        // A caption for slide 2 can land after slide 3 has been taken. Appending on arrival
        // would leave the strip in the order the vision model happened to answer in.
        let slides = mergeSlide([], slide('k1', 4000));
        slides = mergeSlide(slides, slide('k3', 40_000));
        slides = mergeSlide(slides, slide('k2', 20_000));
        expect(slides.map((s) => s.id)).toEqual(['k1', 'k2', 'k3']);
    });
});

describe('segmentsDuring — the join', () => {
    const slides = [slide('k1', 10_000), slide('k2', 20_000), slide('k3', 30_000)];

    it('takes the words spoken between one slide and the next', () => {
        const segments = [
            at('a', 5_000, 'before any slide'),
            at('b', 12_000, 'about slide one'),
            at('c', 22_000, 'about slide two'),
        ];
        expect(segmentsDuring(slides, segments, 0).map((s) => s.id)).toEqual(['b']);
        expect(segmentsDuring(slides, segments, 1).map((s) => s.id)).toEqual(['c']);
    });

    it('is half-open at the boundary: a segment starting on the change belongs to the new slide', () => {
        // The one that decides whether the join is right. A closed interval would put the
        // opening sentence of every slide under the slide before it — which is exactly the
        // sentence that says what the new slide is about.
        const segments = [at('edge', 20_000, 'so, moving on to the architecture')];
        expect(segmentsDuring(slides, segments, 0)).toEqual([]);
        expect(segmentsDuring(slides, segments, 1).map((s) => s.id)).toEqual(['edge']);
    });

    it('a millisecond before the change still belongs to the slide that was up', () => {
        const segments = [at('just', 19_999, 'and that is the revenue picture')];
        expect(segmentsDuring(slides, segments, 0).map((s) => s.id)).toEqual(['just']);
        expect(segmentsDuring(slides, segments, 1)).toEqual([]);
    });

    it('attributes a sentence spanning a change to the slide it began under, once', () => {
        // Splitting on overlap would show the same words under two slides, and a reader who
        // has just read them under slide 1 does not need them again under slide 2.
        const segments = [{ ...at('span', 19_000, 'this chart, and the next one too'), t1: 24_000 }];
        expect(segmentsDuring(slides, segments, 0).map((s) => s.id)).toEqual(['span']);
        expect(segmentsDuring(slides, segments, 1)).toEqual([]);
    });

    it('the last slide runs to the end of the meeting', () => {
        const segments = [at('late', 90_000, 'any questions?')];
        expect(segmentsDuring(slides, segments, 2).map((s) => s.id)).toEqual(['late']);
    });

    it('words spoken before the first slide belong to no slide', () => {
        // They are in the transcript, where they belong. Attaching them to slide 1 would put
        // the pre-meeting chat under the title slide.
        const segments = [at('early', 1_000, 'can everyone hear me?')];
        expect(segmentsDuring(slides, segments, 0)).toEqual([]);
    });

    it('an index nobody has is empty rather than a crash', () => {
        expect(segmentsDuring(slides, [at('a', 15_000, 'x')], 9)).toEqual([]);
        expect(segmentsDuring([], [at('a', 15_000, 'x')], 0)).toEqual([]);
    });
});

describe('slideLabel', () => {
    it('says a slide is not captioned rather than showing a blank', () => {
        expect(slideLabel(slide('k1', 0))).toBe('Not captioned');
        expect(slideLabel({ ...slide('k1', 0), caption: '   ' })).toBe('Not captioned');
    });

    it('uses the caption when there is one', () => {
        expect(slideLabel(slide('k1', 0, 'Q3 revenue, up 14%.'))).toBe('Q3 revenue, up 14%.');
    });
});

describe('SlideStrip', () => {
    const slides = [slide('k1', 10_000, 'The agenda.'), slide('k2', 20_000)];
    const segments = [at('a', 12_000, 'first, the numbers'), at('b', 25_000, 'and the architecture')];

    it('renders nothing at all when a meeting had no slides', () => {
        // Not an empty strip with a heading: a meeting with no slides should not grow a
        // section announcing that it has none.
        render(<SlideStrip slides={[]} segments={segments} />);
        expect(screen.queryByTestId('ms-slides')).toBeNull();
    });

    it('shows one entry per slide, with the timestamp and the caption', () => {
        render(<SlideStrip slides={slides} segments={segments} />);
        const entries = screen.getAllByTestId('ms-slide');
        expect(entries).toHaveLength(2);
        expect(entries[0]).toHaveAccessibleName('00:00:10 — The agenda.');
        expect(entries[1]).toHaveAccessibleName('00:00:20 — Not captioned');
    });

    it('opening a slide shows what was said while it was up', () => {
        render(<SlideStrip slides={slides} segments={segments} />);
        fireEvent.click(screen.getAllByTestId('ms-slide')[0]);
        expect(screen.getByTestId('ms-lightbox-caption')).toHaveTextContent('The agenda.');
        expect(screen.getAllByTestId('ms-lightbox-line').map((p) => p.textContent)).toEqual([
            expect.stringContaining('first, the numbers'),
        ]);
    });

    it('says so when nobody spoke over a slide, rather than showing a blank panel', () => {
        render(<SlideStrip slides={slides} segments={[at('b', 25_000, 'later')]} />);
        fireEvent.click(screen.getAllByTestId('ms-slide')[0]);
        expect(screen.getByTestId('ms-lightbox-silent')).toBeTruthy();
    });

    it('arrow keys move between slides and Escape closes', () => {
        render(<SlideStrip slides={slides} segments={segments} />);
        fireEvent.click(screen.getAllByTestId('ms-slide')[0]);
        fireEvent.keyDown(document, { key: 'ArrowRight' });
        expect(screen.getByTestId('ms-lightbox-caption')).toHaveTextContent('Not captioned');
        fireEvent.keyDown(document, { key: 'Escape' });
        expect(screen.queryByTestId('ms-lightbox')).toBeNull();
    });

    it('does not walk off either end', () => {
        render(<SlideStrip slides={slides} segments={segments} />);
        fireEvent.click(screen.getAllByTestId('ms-slide')[0]);
        fireEvent.keyDown(document, { key: 'ArrowLeft' });
        expect(screen.getByTestId('ms-lightbox-caption')).toHaveTextContent('The agenda.');
        fireEvent.keyDown(document, { key: 'ArrowRight' });
        fireEvent.keyDown(document, { key: 'ArrowRight' });
        expect(screen.getByTestId('ms-lightbox-caption')).toHaveTextContent('Not captioned');
    });

    it('the thumbnail image is decorative; the button carries the name', () => {
        // The caption is on the button, so a screen reader reads "00:00:10 — The agenda,
        // button" rather than the caption twice or "image, button".
        render(<SlideStrip slides={slides} segments={segments} />);
        const image = screen.getAllByTestId('ms-slide')[0].querySelector('img');
        expect(image?.getAttribute('alt')).toBe('');
    });

    it('has no accessibility violations, strip or lightbox', async () => {
        render(<SlideStrip slides={slides} segments={segments} />);
        const run = async () =>
            (await axe.run(document.body, { rules: { 'color-contrast': { enabled: false } } })).violations.map(
                (v) => v.id,
            );
        expect(await run()).toEqual([]);
        fireEvent.click(screen.getAllByTestId('ms-slide')[0]);
        expect(await run()).toEqual([]);
    });
});

describe('the card and the hook, with slides', () => {
    /** The card driven by the real hook, so a `slide` frame is followed end to end. */
    function SlideHarness({ target }: { target: EventTarget }) {
        const ms = useMeetingSense({ recorder: null, target });
        return <MeetingCard view={ms.view} />;
    }

    it('the card hangs the strip under the transcript', () => {
        render(
            <MeetingCard
                view={view({
                    segments: [at('a', 12_000, 'first, the numbers')],
                    slideList: [slide('k1', 10_000, 'The agenda.')],
                })}
            />,
        );
        const card = screen.getByTestId('ms-card');
        const nodes = Array.from(card.querySelectorAll('[data-testid]'));
        const transcript = nodes.indexOf(screen.getByTestId('ms-transcript'));
        const strip = nodes.indexOf(screen.getByTestId('ms-slides'));
        expect(strip).toBeGreaterThan(transcript);
    });

    it('a slide frame reaches the strip, and its caption fills in without a second entry', () => {
        const target = new EventTarget();
        render(<SlideHarness target={target} />);
        act(() => {
            target.dispatchEvent(
                new CustomEvent('ms:slide', { detail: { id: 'k1', t: 4000, url: '/files/k1.jpg', caption: null } }),
            );
        });
        expect(screen.getAllByTestId('ms-slide')).toHaveLength(1);
        expect(screen.getAllByTestId('ms-slide')[0]).toHaveAccessibleName('00:00:04 — Not captioned');

        act(() => {
            target.dispatchEvent(
                new CustomEvent('ms:slide', {
                    detail: { id: 'k1', t: 4000, url: '/files/k1.jpg', caption: 'The roadmap.' },
                }),
            );
        });
        expect(screen.getAllByTestId('ms-slide')).toHaveLength(1);
        expect(screen.getAllByTestId('ms-slide')[0]).toHaveAccessibleName('00:00:04 — The roadmap.');
    });

    it('a malformed slide frame is ignored rather than rendering a broken thumbnail', () => {
        const target = new EventTarget();
        render(<SlideHarness target={target} />);
        act(() => {
            target.dispatchEvent(new CustomEvent('ms:slide', { detail: { id: 'k1', t: 4000 } }));
        });
        expect(screen.queryByTestId('ms-slides')).toBeNull();
    });
});
