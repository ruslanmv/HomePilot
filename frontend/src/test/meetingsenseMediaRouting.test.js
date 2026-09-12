import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const SHIPPED = resolve(ROOT, 'frontend/public/js/homepilot-meetingsense-media.js');
const MIRROR = resolve(ROOT, 'community/addons/meetingsense/homepilot-meetingsense-media.js');
const INDEX = resolve(ROOT, 'frontend/index.html');
const SOURCE = readFileSync(SHIPPED, 'utf8');

function fakeTrack(kind, label = '') {
    return { kind, label, readyState: 'live', stop: vi.fn() };
}

function fakeStream({ audio = 0, video = 0 } = {}) {
    const audioTracks = Array.from({ length: audio }, () => fakeTrack('audio'));
    const videoTracks = Array.from({ length: video }, () => fakeTrack('video', 'Shared screen'));
    return {
        getAudioTracks: () => audioTracks,
        getVideoTracks: () => videoTracks,
        getTracks: () => [...audioTracks, ...videoTracks],
    };
}

function install({ displayStream = fakeStream({ audio: 1, video: 1 }), micStream = fakeStream({ audio: 1 }) } = {}) {
    const recorder = {
        recording: false,
        meetingId: 'meeting-1',
        audioMode: 'none',
        _elapsedSamples: 0,
        _tracks: [],
        _mediaClockMs: vi.fn(() => 0),
        _connect: vi.fn(async () => ({ ok: true })),
        _startWatching: vi.fn(() => true),
        _teardown: vi.fn(),
        startWithStreams: vi.fn(async () => ({ ok: true, meetingId: 'meeting-1', audioMode: 'system+mic' })),
        internals: { trackLabel: vi.fn(() => 'Shared screen') },
    };
    const getDisplayMedia = vi.fn(async () => displayStream);
    const getUserMedia = vi.fn(async () => micStream);
    Object.defineProperty(navigator, 'mediaDevices', {
        configurable: true,
        value: { getDisplayMedia, getUserMedia },
    });
    window.hpMeetingSense = recorder;
    // eslint-disable-next-line no-new-func
    new Function(SOURCE).call(window);
    return { recorder, getDisplayMedia, getUserMedia, displayStream, micStream };
}

beforeEach(() => {
    localStorage.clear();
    delete window.hpMeetingSense;
});

describe('MeetingSense media routing', () => {
    it('ships the same routing contract in public and community addon copies', () => {
        const digest = (path) => createHash('sha256').update(readFileSync(path)).digest('hex');
        expect(digest(MIRROR)).toBe(digest(SHIPPED));
    });

    it('loads the routing contract after the recorder and before React', () => {
        const html = readFileSync(INDEX, 'utf8');
        const recorderAt = html.indexOf('/js/homepilot-meetingsense.js');
        const routingAt = html.indexOf('/js/homepilot-meetingsense-media.js');
        const reactAt = html.indexOf('/src/main.tsx');
        expect(recorderAt).toBeGreaterThan(-1);
        expect(routingAt).toBeGreaterThan(recorderAt);
        expect(reactAt).toBeGreaterThan(routingAt);
    });

    it('does not open a microphone when My microphone is off', async () => {
        const { recorder, getDisplayMedia, getUserMedia } = install();
        const result = await window.hpMeetingSense.start({
            conversationId: 'chat-1',
            audio: true,
            mic: false,
            watch: false,
        });

        expect(result.ok).toBe(true);
        expect(getDisplayMedia).toHaveBeenCalledWith({ video: true, audio: true });
        expect(getUserMedia).not.toHaveBeenCalled();
        expect(recorder.startWithStreams).toHaveBeenCalledTimes(1);
        expect(recorder.startWithStreams.mock.calls[0][0].mic).toBe(null);
    });

    it('uses the selected microphone and saved DSP settings for mic-only meetings', async () => {
        localStorage.setItem('homepilot_media_preferences_v1', JSON.stringify({
            microphoneDeviceId: 'usb-mic-42',
            echoCancellation: false,
            noiseSuppression: true,
            autoGainControl: false,
        }));
        const { recorder, getDisplayMedia, getUserMedia } = install();

        const result = await window.hpMeetingSense.start({
            conversationId: 'chat-1',
            audio: false,
            mic: true,
            watch: false,
        });

        expect(result.ok).toBe(true);
        expect(getDisplayMedia).not.toHaveBeenCalled();
        expect(getUserMedia).toHaveBeenCalledWith({
            video: false,
            audio: {
                deviceId: { exact: 'usb-mic-42' },
                echoCancellation: false,
                noiseSuppression: true,
                autoGainControl: false,
            },
        });
        expect(recorder.startWithStreams).toHaveBeenCalledTimes(1);
    });

    it('requests screen video without display audio when Meeting audio is off', async () => {
        const display = fakeStream({ video: 1 });
        const { getDisplayMedia } = install({ displayStream: display });

        const result = await window.hpMeetingSense.start({
            conversationId: 'chat-1',
            audio: false,
            mic: true,
            watch: true,
        });

        expect(result.ok).toBe(true);
        expect(getDisplayMedia).toHaveBeenCalledWith({ video: true, audio: false });
    });

    it('starts a screen-only meeting when both audio sources are off', async () => {
        const display = fakeStream({ video: 1 });
        const { recorder, getDisplayMedia, getUserMedia } = install({ displayStream: display });

        const result = await window.hpMeetingSense.start({
            conversationId: 'chat-1',
            audio: false,
            mic: false,
            watch: true,
        });

        expect(result).toMatchObject({ ok: true, audioMode: 'none', watching: true });
        expect(getDisplayMedia).toHaveBeenCalledWith({ video: true, audio: false });
        expect(getUserMedia).not.toHaveBeenCalled();
        expect(recorder.startWithStreams).not.toHaveBeenCalled();
        expect(recorder._connect).toHaveBeenCalledTimes(1);
        expect(recorder._startWatching).toHaveBeenCalledWith(display, expect.objectContaining({ watch: true }));
    });

    it('opens no browser capture when every source is off', async () => {
        const { getDisplayMedia, getUserMedia } = install();
        const result = await window.hpMeetingSense.start({
            conversationId: 'chat-1',
            audio: false,
            mic: false,
            watch: false,
        });

        expect(result.ok).toBe(false);
        expect(result.error).toContain('Choose at least one capture source');
        expect(getDisplayMedia).not.toHaveBeenCalled();
        expect(getUserMedia).not.toHaveBeenCalled();
    });

    it('reports the real microphone error instead of silently continuing', async () => {
        const display = fakeStream({ audio: 1, video: 1 });
        const { getUserMedia } = install({ displayStream: display });
        const error = new Error('device is already busy');
        error.name = 'NotReadableError';
        getUserMedia.mockRejectedValueOnce(error);

        const result = await window.hpMeetingSense.start({
            conversationId: 'chat-1',
            audio: true,
            mic: true,
            watch: true,
        });

        expect(result.ok).toBe(false);
        expect(result.error).toContain('Selected microphone could not be opened (NotReadableError)');
        display.getTracks().forEach((track) => expect(track.stop).toHaveBeenCalledTimes(1));
    });

    it('fails clearly when Meeting audio was requested but the chosen share has no audio track', async () => {
        const display = fakeStream({ video: 1 });
        const { getUserMedia } = install({ displayStream: display });

        const result = await window.hpMeetingSense.start({
            conversationId: 'chat-1',
            audio: true,
            mic: true,
            watch: true,
        });

        expect(result.ok).toBe(false);
        expect(result.error).toContain('shared source has no audio track');
        expect(getUserMedia).not.toHaveBeenCalled();
        display.getTracks().forEach((track) => expect(track.stop).toHaveBeenCalledTimes(1));
    });
});
