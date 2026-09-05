/**
 * The first-run consent sheet (batch MS6, §2a "consent that informs").
 *
 * A sheet that says "this will record audio" and nothing else is a formality. This one names
 * **which** speech provider will hear the meeting and **where** the audio goes, because
 * somebody who set `STT_BASE_URL` months ago for voice calls would otherwise ship an hour of a
 * board meeting to it having agreed only to "recording".
 *
 * "Don't show again" is per machine — it is a browser preference, not an account setting, and
 * the machine is what has the microphone. The reminder to tell participants is *not* covered
 * by it: that line stays in the pill on every single start.
 *
 * A real modal, so it traps focus: this is the one moment where the rest of the page must
 * wait, because a consent sheet the user can tab behind has not been read.
 */
import React, { useCallback, useEffect, useRef } from 'react';
import { consentSentences } from './meetingState';

export const CONSENT_STORAGE_KEY = 'meetingsense_consent_ack';

export interface ConsentStatus {
    stt?: { provider?: string | null; remote?: boolean; segments?: boolean };
    retention?: string;
}

export interface ConsentSheetProps {
    status: ConsentStatus | null;
    onAccept: (rememberChoice: boolean) => void;
    onCancel: () => void;
}

/** Whether the sheet has been dismissed on this machine. Never throws: a browser with storage
 *  blocked simply shows the sheet again, which is the safe direction to be wrong in. */
export function consentAcknowledged(storage?: Storage): boolean {
    try {
        return (storage ?? window.localStorage).getItem(CONSENT_STORAGE_KEY) === 'true';
    } catch (_) {
        return false;
    }
}

export function rememberConsent(storage?: Storage): void {
    try {
        (storage ?? window.localStorage).setItem(CONSENT_STORAGE_KEY, 'true');
    } catch (_) {
        /* private mode, blocked storage — the sheet just appears again */
    }
}

export function ConsentSheet({ status, onAccept, onCancel }: ConsentSheetProps) {
    const sheet = useRef<HTMLDivElement | null>(null);
    const remember = useRef<HTMLInputElement | null>(null);
    const sentences = consentSentences(status);

    const onKeyDown = useCallback(
        (event: React.KeyboardEvent) => {
            if (event.key === 'Escape') {
                onCancel();
                return;
            }
            if (event.key !== 'Tab') return;
            const focusable = sheet.current?.querySelectorAll<HTMLElement>(
                'button, input, [href], [tabindex]:not([tabindex="-1"])',
            );
            if (!focusable || !focusable.length) return;
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            // Wrapped by hand rather than left to the browser: tabbing out of a consent sheet
            // and starting a recording from a control behind it is exactly the outcome the
            // sheet exists to prevent.
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        },
        [onCancel],
    );

    useEffect(() => {
        sheet.current?.querySelector<HTMLElement>('button')?.focus();
    }, []);

    return (
        <div
            className="ms-consent"
            role="dialog"
            aria-modal="true"
            aria-labelledby="ms-consent-title"
            ref={sheet}
            onKeyDown={onKeyDown}
            data-testid="ms-consent"
        >
            <h2 id="ms-consent-title">Before you record</h2>
            <ul className="ms-consent__points">
                {sentences.map((line) => (
                    <li key={line}>{line}</li>
                ))}
            </ul>
            <label className="ms-consent__remember">
                <input type="checkbox" ref={remember} data-testid="ms-consent-remember" />
                <span>Don’t show this again on this computer</span>
            </label>
            <div className="ms-consent__actions">
                <button
                    type="button"
                    onClick={() => onAccept(!!remember.current?.checked)}
                    data-testid="ms-consent-accept"
                >
                    Start recording
                </button>
                <button type="button" onClick={onCancel} data-testid="ms-consent-cancel">
                    Cancel
                </button>
            </div>
        </div>
    );
}

export default ConsentSheet;
