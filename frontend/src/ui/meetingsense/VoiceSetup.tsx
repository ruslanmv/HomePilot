/**
 * The virtual-microphone setup wizard (batch MS27, Practice).
 *
 * Practice speaks aloud into the *call*, which a browser tab cannot do: it can play audio, and
 * the meeting's microphone will not hear it unless the operating system routes it there. That
 * routing is a driver the user installs — VB-Cable on Windows, BlackHole on macOS, a null sink
 * on Linux — and this is the page that tells them which one and then **checks**.
 *
 * The checking is the whole point. A setup wizard that ends on "you're all set!" without
 * verifying is how somebody arrives at a mock interview with no sound and no idea which of
 * four steps did not take. So the last step is a probe against the devices the desktop app can
 * actually see, and it can fail.
 *
 * It also refuses honestly. In a browser there is nothing to install that would help, so it
 * says that instead of showing instructions the user cannot act on.
 */
import React, { useCallback, useState } from 'react';

export interface VoiceGuide {
    system: string;
    product: string;
    url: string;
    steps: string[];
}

export interface VoiceCapability {
    ok: boolean;
    device?: string;
    reason?: 'browser' | 'no_virtual_device' | string;
    detail?: string;
    guide?: VoiceGuide;
}

export interface VoiceSetupProps {
    capability: VoiceCapability | null;
    /** Re-probe. Returns the fresh capability — the wizard never assumes the step worked. */
    onCheck?: () => Promise<VoiceCapability>;
}

export function VoiceSetup({ capability, onCheck }: VoiceSetupProps) {
    const [checking, setChecking] = useState(false);
    const [result, setResult] = useState<VoiceCapability | null>(null);
    const state = result || capability;

    const check = useCallback(async () => {
        if (!onCheck) return;
        setChecking(true);
        try {
            setResult(await onCheck());
        } finally {
            setChecking(false);
        }
    }, [onCheck]);

    if (!state) return null;

    if (state.ok) {
        return (
            <div className="ms-voice ms-voice--ready" data-testid="ms-voice-setup" role="status">
                <p className="ms-voice__headline">
                    Ready to speak into your meeting through <strong>{state.device}</strong>.
                </p>
                <p className="ms-voice__note">
                    Set your meeting app&rsquo;s microphone to this device if you have not already.
                </p>
            </div>
        );
    }

    if (state.reason === 'browser') {
        // Nothing to install would help here, so nothing is offered. Instructions the user
        // cannot act on read as a wizard that did not understand the question.
        return (
            <div className="ms-voice ms-voice--unavailable" data-testid="ms-voice-setup" role="status">
                <p className="ms-voice__headline">{state.detail}</p>
            </div>
        );
    }

    const guide = state.guide;
    return (
        <div className="ms-voice ms-voice--setup" data-testid="ms-voice-setup">
            <p className="ms-voice__headline">{state.detail}</p>
            {guide ? (
                <>
                    <ol className="ms-voice__steps" data-testid="ms-voice-steps">
                        {guide.steps.map((step, i) => (
                            <li key={i} className="ms-voice__step">{step}</li>
                        ))}
                    </ol>
                    <a
                        className="ms-voice__link"
                        href={guide.url}
                        target="_blank"
                        rel="noreferrer noopener"
                        data-testid="ms-voice-link"
                    >
                        Get {guide.product}
                    </a>
                </>
            ) : null}
            {onCheck ? (
                <button
                    type="button"
                    className="ms-voice__check"
                    onClick={check}
                    disabled={checking}
                    data-testid="ms-voice-check"
                >
                    {checking ? 'Checking…' : 'Check again'}
                </button>
            ) : null}
            {result && !result.ok ? (
                // The step is only done when the probe says so. Saying "all set" here would be
                // the wizard telling the user something it has not checked.
                <p className="ms-voice__failed" role="status" data-testid="ms-voice-failed">
                    Still not finding it. On Windows the driver only loads after a restart.
                </p>
            ) : null}
        </div>
    );
}

export default VoiceSetup;
