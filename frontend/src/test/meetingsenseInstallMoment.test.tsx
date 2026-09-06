/**
 * The install moment (batch LS4).
 *
 * The acceptance is a property of the rendered tree, not of a string somewhere: **no
 * environment-variable name appears anywhere in the normal path.** `WHISPER_MODEL` survives only
 * under Advanced, and this walks what actually rendered to prove it.
 *
 * That distinction matters because the copy was already careful once. MS29 put the server's hint
 * — `Set WHISPER_MODEL (e.g. small) …` — under the chat composer, permanently, for everybody
 * including people who will never record a meeting. MS32 moved it to Settings, which was right,
 * and left it as the first thing somebody reads on the page where they came to turn transcription
 * on. Precision does not stop being useful when it stops being the headline.
 *
 * So: an install button and two sentences in the normal path, and the precise hint one disclosure
 * down, closed. The download size comes from the pack manifest the server reports — never a
 * figure typed into this file, because conversion and quantisation change the installed footprint
 * and any number written here is wrong the first time the pack is rebuilt.
 */
import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

import { MeetingTranscriptionCard } from '../ui/meetingsense/MeetingTranscriptionCard';

const HINT = 'Set WHISPER_MODEL (e.g. small) for local transcription, or STT_BASE_URL for a remote one.';

/** Every environment-variable name a person must never meet in the normal path. */
const ENV_NAMES = [
    'WHISPER_MODEL', 'WHISPER_DEVICE', 'WHISPER_COMPUTE', 'STT_BASE_URL',
    'HOMEPILOT_SPEECH_DIR', 'HOMEPILOT_SPEECH_PACK', 'MEETINGSENSE_STT',
];

function status(localSpeech: unknown, { available = false } = {}) {
    return async () => ({
        enabled: true,
        ready: false,
        stt: { available, provider: null, hint: HINT, local_speech: localSpeech },
    });
}

const NOT_INSTALLED = {
    available: false,
    local: true,
    label: 'Transcription — Local · not installed',
    pack: { pack: null, label: 'Whisper Small', reason: 'not-installed', size_mb: 484 },
};

/**
 * The normal path: everything on screen that is not inside a closed disclosure.
 *
 * `<details>` without `open` is what "one level down" means here, and reading `textContent` off
 * the whole card would count it — which is exactly the mistake that would let the env-var names
 * back into the headline while the test still passed.
 */
function normalPathText(container: HTMLElement): string {
    const clone = container.cloneNode(true) as HTMLElement;
    clone.querySelectorAll('details:not([open])').forEach((node) => node.remove());
    return clone.textContent || '';
}

describe('the install moment', () => {
    it('offers an install button instead of a configuration instruction', async () => {
        render(<MeetingTranscriptionCard load={status(NOT_INSTALLED)} />);
        const button = await screen.findByTestId('ms-settings-install-btn');
        expect(button.textContent).toContain('Install Local Transcription');
        expect(await screen.findByTestId('ms-settings-install')).toBeTruthy();
    });

    it('says what you get and where the audio goes', async () => {
        const { container } = render(<MeetingTranscriptionCard load={status(NOT_INSTALLED)} />);
        await screen.findByTestId('ms-settings-install');
        const text = normalPathText(container);
        expect(text).toContain('Local transcription needs to be installed.');
        expect(text).toContain('entirely on this computer');
        expect(text).toContain('No account or cloud speech service required.');
    });

    it('names no environment variable anywhere in the normal path', async () => {
        const { container } = render(<MeetingTranscriptionCard load={status(NOT_INSTALLED)} />);
        await screen.findByTestId('ms-settings-install');
        const text = normalPathText(container);
        for (const name of ENV_NAMES) {
            expect(text).not.toContain(name);
        }
    });

    it('and keeps the precise hint one disclosure down, closed', async () => {
        // Precision belongs somewhere. Somebody debugging a server needs the exact variable
        // name, and they are the person who opens Advanced.
        render(<MeetingTranscriptionCard load={status(NOT_INSTALLED)} />);
        const advanced = await screen.findByTestId('ms-settings-advanced');
        expect(advanced.tagName.toLowerCase()).toBe('details');
        expect(advanced.hasAttribute('open')).toBe(false);
        expect(advanced.textContent).toContain('WHISPER_MODEL');
    });

    it('takes the download size from the manifest, not from this file', async () => {
        // Conversion and quantisation change the footprint. A number typed into the UI is wrong
        // the first time the pack is rebuilt.
        const { rerender } = render(<MeetingTranscriptionCard load={status(NOT_INSTALLED)} />);
        expect((await screen.findByTestId('ms-settings-install-size')).textContent).toContain('484 MB');

        rerender(
            <MeetingTranscriptionCard
                load={status({ ...NOT_INSTALLED, pack: { ...NOT_INSTALLED.pack, size_mb: 1620 } })}
            />,
        );
        await waitFor(() =>
            expect(screen.getByTestId('ms-settings-install-size').textContent).toContain('1.6 GB'),
        );
    });

    it('tells a half-finished install from a corrupt one', async () => {
        // Different problems with different next steps. A single spinner over both would be the
        // same shrug this series has been removing.
        const { rerender, container } = render(
            <MeetingTranscriptionCard
                load={status({ ...NOT_INSTALLED, pack: { ...NOT_INSTALLED.pack, reason: 'incomplete' } })}
            />,
        );
        await screen.findByTestId('ms-settings-install');
        expect(normalPathText(container)).toContain('did not finish');

        rerender(
            <MeetingTranscriptionCard
                load={status({ ...NOT_INSTALLED, pack: { ...NOT_INSTALLED.pack, reason: 'corrupt' } })}
            />,
        );
        await waitFor(() => expect(normalPathText(container)).toContain('checksum'));
    });

    it('shows no install prompt once transcription is ready', async () => {
        render(
            <MeetingTranscriptionCard
                load={status({ ...NOT_INSTALLED, available: true }, { available: true })}
            />,
        );
        await screen.findByTestId('ms-settings-state');
        expect(screen.queryByTestId('ms-settings-install')).toBeNull();
    });

    it('still renders on a server too old to report a pack', async () => {
        // An older server sends no `local_speech` key at all, and the card must not blank out.
        const { container } = render(<MeetingTranscriptionCard load={status(undefined)} />);
        await screen.findByTestId('ms-settings-install');
        expect(normalPathText(container)).toContain('Local transcription needs to be installed.');
        for (const name of ENV_NAMES) {
            expect(normalPathText(container)).not.toContain(name);
        }
    });
});
