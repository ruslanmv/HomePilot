/**
 * The MeetingSense entry point (batch MS5).
 *
 * Today the ScreenSense button opens a share picker and fires one question. When MeetingSense
 * is enabled on the backend, that button also opens a small popover with two toggles and a
 * start button; when it is not, the button is left exactly as it was.
 *
 * ── The rule this module exists to keep ──────────────────────────────────────────────────
 *
 * **ScreenSense is not edited by any batch.** Its promise is a silent still with no backend,
 * and it keeps working for people who never turn MeetingSense on. So this attaches to the
 * button ScreenSense already mounted rather than replacing it, and with the flag off it makes
 * no DOM change at all — a test asserts the button's `outerHTML` is byte-identical before and
 * after `attach()` runs.
 *
 * "Ask once" is the existing click handler, untouched. The popover's own button re-fires it.
 *
 * ── Why the copy lives here and not in a component ───────────────────────────────────────
 *
 * Half of this file is sentences. That is deliberate: the thing that makes a recorder
 * trustworthy is that every disabled control says *why* it is disabled and *what to set*, and
 * a greyed-out toggle with no explanation is the failure mode this batch exists to prevent.
 * `describe()` is a pure function from a `/status` body to those sentences, so the copy is
 * unit-testable without a DOM, and a test can assert that no generic "unavailable" ever
 * reaches the bundle.
 */

export interface SttStatus {
    available?: boolean;
    provider?: string | null;
    segments?: boolean;
    remote?: boolean;
    device?: string | null;
    device_note?: string;
    hint?: string | null;
}

export interface MeetingSenseStatus {
    enabled?: boolean;
    ready?: boolean;
    retention?: string;
    stt?: SttStatus;
    vision?: { available?: boolean; model?: string | null; hint?: string | null };
}

export interface Capabilities {
    /** Whether this browser can share system audio at all. */
    canCaptureDisplay: boolean;
    /** Coarse platform, only used for the one message that differs by it. */
    platform?: 'mac' | 'windows' | 'linux' | 'mobile' | 'unknown';
}

export interface Notice {
    /** Stable id, so a test names a message rather than matching prose. */
    id: string;
    tone: 'info' | 'warn' | 'blocked';
    text: string;
}

export interface Description {
    /** Whether the popover should be offered at all. */
    offer: boolean;
    /** Whether "Record audio" can be switched on. */
    canRecordAudio: boolean;
    /** Whether "Watch screen" can be switched on. */
    canWatchScreen: boolean;
    /** What the STT line reads, always present when the popover is offered. */
    provider: string;
    notices: Notice[];
}

/**
 * Turn a `/v1/meetingsense/status` body plus this browser's capabilities into the exact
 * sentences the popover shows.
 *
 * Every branch here answers two questions — why is this off, and what would turn it on. The
 * server's own `hint` is used verbatim wherever it exists rather than being restated: it
 * already names the environment variable, and a second copy of that name in the client is a
 * second place to keep in step.
 */
export function describe(status: MeetingSenseStatus | null, caps: Capabilities): Description {
    const notices: Notice[] = [];
    const stt = (status && status.stt) || {};

    if (!status || !status.enabled) {
        return {
            offer: false,
            canRecordAudio: false,
            canWatchScreen: false,
            provider: '',
            notices: [
                {
                    id: 'disabled',
                    tone: 'blocked',
                    text: 'MeetingSense is off on this server. Set MEETINGSENSE_ENABLED=true to turn it on.',
                },
            ],
        };
    }

    // ── speech ────────────────────────────────────────────────────────────────────────────
    const canRecordAudio = !!stt.available;
    if (!canRecordAudio) {
        notices.push({
            id: 'stt-unavailable',
            tone: 'blocked',
            // The server names the variable; repeating it here would be the second place.
            text: stt.hint || 'No speech provider is configured, so audio cannot be transcribed.',
        });
    } else if (stt.remote) {
        // A legitimate choice, but the user should be the one making it — and the endpoint is
        // never echoed, because it can carry a key.
        notices.push({
            id: 'stt-remote',
            tone: 'warn',
            text: `Audio is sent to your configured speech endpoint (${stt.provider || 'remote'}), not transcribed on this machine.`,
        });
    }

    if (canRecordAudio && stt.segments === false) {
        notices.push({
            id: 'stt-no-timestamps',
            tone: 'warn',
            text: 'This provider does not report timings, so the transcript will have no timestamps to cite.',
        });
    }

    if (stt.device_note) {
        // "requested cuda, running on cpu" — the silent fallback that makes people conclude
        // the latency budget is unachievable.
        notices.push({ id: 'stt-device', tone: 'warn', text: `Speech model: ${stt.device_note}.` });
    }

    // ── capture ───────────────────────────────────────────────────────────────────────────
    const canWatchScreen = caps.canCaptureDisplay;
    if (!caps.canCaptureDisplay) {
        notices.push({
            id: caps.platform === 'mobile' ? 'capture-mobile' : 'capture-unsupported',
            tone: 'blocked',
            text:
                caps.platform === 'mobile'
                    ? 'Recording a meeting needs a desktop browser — this one cannot share screen audio.'
                    : 'This browser cannot share screen audio. Chrome or Edge on a desktop can.',
        });
    } else if (caps.platform === 'mac') {
        notices.push({
            id: 'capture-mac',
            tone: 'warn',
            text: 'macOS does not let a browser capture the call’s audio: this records your microphone only, unless you add a virtual audio device.',
        });
    } else if (caps.platform === 'linux') {
        notices.push({
            id: 'capture-linux',
            tone: 'warn',
            text: 'On Linux, share a browser tab with “Share tab audio” ticked — a window or whole-screen share carries no audio.',
        });
    }

    // ── slides ────────────────────────────────────────────────────────────────────────────
    const vision = (status && status.vision) || {};
    if (!vision.available) {
        notices.push({
            id: 'vision-unavailable',
            tone: 'info',
            text: vision.hint || 'Slides will not be captioned; the transcript is unaffected.',
        });
    }

    return {
        offer: true,
        canRecordAudio,
        canWatchScreen,
        provider: stt.provider || 'none',
        notices,
    };
}

/** What this browser can do, read once. Split out so a test can supply it directly. */
export function detectCapabilities(win: any = globalThis): Capabilities {
    const nav = win.navigator || {};
    const ua = String(nav.userAgent || '');
    const mobile = /Android|iPhone|iPad|iPod|Mobile/i.test(ua);
    const canCaptureDisplay =
        !mobile && !!(nav.mediaDevices && typeof nav.mediaDevices.getDisplayMedia === 'function');

    let platform: Capabilities['platform'] = 'unknown';
    if (mobile) platform = 'mobile';
    else if (/Mac|Darwin/i.test(ua)) platform = 'mac';
    else if (/Win/i.test(ua)) platform = 'windows';
    else if (/Linux|X11/i.test(ua)) platform = 'linux';

    return { canCaptureDisplay, platform };
}

export interface AttachOptions {
    status: MeetingSenseStatus | null;
    capabilities?: Capabilities;
    /** Called with the chosen toggles when "Start session" is pressed. */
    onStart?: (choice: { watchScreen: boolean; recordAudio: boolean; liveNotes: boolean }) => void;
    document?: Document;
}

export interface EntryPoint {
    popover: HTMLElement;
    open: () => void;
    close: () => void;
    destroy: () => void;
    readonly isOpen: boolean;
}

const POPOVER_ID = 'meetingsense-popover';

/** Marks the synthetic click the popover re-dispatches, so it is let through to ScreenSense. */
const ASK_ONCE = '__meetingsenseAskOnce';
type AskOnceEvent = Event & { [ASK_ONCE]?: boolean };

/**
 * Give an existing button a MeetingSense popover, or leave it exactly as it is.
 *
 * Returns `null` when MeetingSense is disabled — and returning null is the *whole* contract:
 * nothing is appended, no attribute is set, no listener is added, so the button a user sees
 * with the flag off is the button ScreenSense mounted, character for character.
 */
export function attach(button: HTMLElement, options: AttachOptions): EntryPoint | null {
    const doc = options.document || button.ownerDocument;
    const caps = options.capabilities || detectCapabilities(doc.defaultView || globalThis);
    const described = describe(options.status, caps);
    if (!described.offer) return null;

    const popover = buildPopover(doc, described, caps);
    let open = false;

    const setOpen = (next: boolean) => {
        open = next;
        popover.hidden = !next;
        button.setAttribute('aria-expanded', next ? 'true' : 'false');
        if (next) {
            const first = popover.querySelector<HTMLElement>('input:not([disabled]),button');
            if (first) first.focus();
        }
    };

    const onButtonClick = (event: Event) => {
        // ScreenSense's own click handler is still on this button and would fire "Ask once"
        // alongside the popover, so one click would both ask a question and open a menu. It
        // cannot be removed — ScreenSense is not edited by any batch — so it is suppressed
        // here, in the capture phase, and re-fired deliberately by the popover's own
        // "Ask once" button. That re-dispatch carries a marker so this handler lets it past.
        if ((event as AskOnceEvent)[ASK_ONCE]) return;
        event.stopImmediatePropagation();
        event.preventDefault();
        setOpen(!open);
    };

    const onKeyDown = (event: KeyboardEvent) => {
        if (event.key !== 'Escape' || !open) return;
        setOpen(false);
        // Focus goes back where it came from. A popover that closes into nothing leaves a
        // keyboard user at the top of the document with no idea what happened.
        button.focus();
    };

    button.setAttribute('aria-expanded', 'false');
    button.setAttribute('aria-controls', POPOVER_ID);
    button.setAttribute('aria-haspopup', 'true');
    // Capture phase, so this runs before the listener ScreenSense attached in the bubble phase
    // and can stop it. Registered non-capture, it would run second and be too late.
    button.addEventListener('click', onButtonClick, true);
    doc.addEventListener('keydown', onKeyDown);

    const askOnce = popover.querySelector<HTMLButtonElement>('[data-ms="ask"]');
    if (askOnce) {
        askOnce.addEventListener('click', () => {
            setOpen(false);
            // The unchanged path: ScreenSense's own handler, reached by re-dispatching the
            // click it was written for rather than by reimplementing what it does.
            const event = new MouseEvent('click', { bubbles: true, cancelable: true });
            (event as AskOnceEvent)[ASK_ONCE] = true;
            button.dispatchEvent(event);
        });
    }

    const startButton = popover.querySelector<HTMLButtonElement>('[data-ms="start"]');
    if (startButton) {
        startButton.addEventListener('click', () => {
            const checked = (name: string) =>
                !!popover.querySelector<HTMLInputElement>(`[data-ms="${name}"]`)?.checked;
            options.onStart?.({
                watchScreen: checked('watch'),
                recordAudio: checked('record'),
                liveNotes: checked('notes'),
            });
            setOpen(false);
        });
    }

    doc.body.appendChild(popover);

    return {
        popover,
        open: () => setOpen(true),
        close: () => setOpen(false),
        get isOpen() {
            return open;
        },
        destroy() {
            button.removeEventListener('click', onButtonClick, true);
            doc.removeEventListener('keydown', onKeyDown);
            button.removeAttribute('aria-expanded');
            button.removeAttribute('aria-controls');
            button.removeAttribute('aria-haspopup');
            popover.remove();
        },
    };
}

/**
 * The popover itself (design Part 1 §2.1).
 *
 * A `<dialog>` would bring a focus trap for free but also a modal backdrop, and a recorder's
 * entry point must not black out the meeting behind it. So it is a labelled group, and the
 * keyboard work is done explicitly.
 */
export function buildPopover(doc: Document, described: Description, caps: Capabilities): HTMLElement {
    const root = doc.createElement('section');
    root.id = POPOVER_ID;
    root.hidden = true;
    root.setAttribute('aria-label', 'Screen awareness');
    root.style.cssText = [
        'position:fixed',
        'right:18px',
        'bottom:64px',
        'z-index:2147483000',
        'max-width:340px',
        'padding:14px 16px',
        'border-radius:12px',
        'border:1px solid rgba(90,110,160,.4)',
        'background:#0a0f1e',
        'color:#e6ecfa',
        'font:400 13px/1.5 system-ui,sans-serif',
        'box-shadow:0 8px 28px rgba(0,0,0,.5)',
    ].join(';');

    const heading = doc.createElement('h2');
    heading.textContent = 'Screen awareness';
    heading.style.cssText = 'margin:0 0 10px;font:600 14px/1.3 system-ui,sans-serif;color:#e6ecfa';
    root.appendChild(heading);

    const toggle = (name: string, label: string, hint: string, enabled: boolean) => {
        const wrap = doc.createElement('label');
        wrap.style.cssText = 'display:flex;gap:8px;align-items:flex-start;margin:0 0 8px';
        const input = doc.createElement('input');
        input.type = 'checkbox';
        input.dataset.ms = name;
        input.disabled = !enabled;
        const text = doc.createElement('span');
        const strong = doc.createElement('strong');
        strong.textContent = label;
        strong.style.cssText = 'font-weight:600';
        text.appendChild(strong);
        if (hint) {
            const small = doc.createElement('span');
            small.textContent = ` — ${hint}`;
            small.style.cssText = 'color:#9fb0d0';
            text.appendChild(small);
        }
        wrap.append(input, text);
        return wrap;
    };

    // On a browser that cannot capture, the controls are hidden rather than shown greyed: a
    // disabled control on a phone invites tapping it, and the sentence below already says why.
    if (caps.canCaptureDisplay) {
        root.appendChild(toggle('watch', 'Watch screen', 'slide-aware snapshots', described.canWatchScreen));
        root.appendChild(toggle('record', 'Record audio', 'live transcript', described.canRecordAudio));
        root.appendChild(toggle('notes', 'Live AI notes in chat', '', described.canRecordAudio));
    }

    const provider = doc.createElement('p');
    provider.dataset.ms = 'provider';
    provider.textContent = `Speech: ${described.provider}`;
    provider.style.cssText = 'margin:10px 0 6px;color:#9fb0d0';
    root.appendChild(provider);

    if (described.notices.length) {
        const list = doc.createElement('ul');
        list.style.cssText = 'margin:0 0 10px;padding-left:18px;color:#c2cee6';
        for (const notice of described.notices) {
            const item = doc.createElement('li');
            item.dataset.ms = `notice:${notice.id}`;
            item.dataset.tone = notice.tone;
            item.textContent = notice.text;
            item.style.cssText = 'margin:0 0 4px';
            list.appendChild(item);
        }
        root.appendChild(list);
    }

    const consent = doc.createElement('p');
    consent.style.cssText = 'margin:0 0 12px;color:#9fb0d0';
    consent.textContent = 'Tell participants you are recording.';
    root.appendChild(consent);

    const actions = doc.createElement('div');
    actions.style.cssText = 'display:flex;gap:8px';
    const start = doc.createElement('button');
    start.type = 'button';
    start.dataset.ms = 'start';
    start.textContent = 'Start session';
    start.disabled = !described.canRecordAudio && !described.canWatchScreen;
    start.style.cssText =
        'padding:8px 12px;border-radius:8px;border:1px solid rgba(120,150,220,.5);background:#16233d;color:#e6ecfa;font:600 13px/1 system-ui,sans-serif;cursor:pointer';
    const ask = doc.createElement('button');
    ask.type = 'button';
    ask.dataset.ms = 'ask';
    ask.textContent = 'Ask once';
    ask.title = 'One screenshot and one question — exactly as before';
    ask.style.cssText =
        'padding:8px 12px;border-radius:8px;border:1px solid rgba(90,110,160,.4);background:transparent;color:#c2cee6;font:600 13px/1 system-ui,sans-serif;cursor:pointer';

    actions.append(start, ask);
    root.appendChild(actions);

    return root;
}

/** Read the status endpoint. Never throws: a status the UI cannot read is a status that is off. */
export async function fetchStatus(base = ''): Promise<MeetingSenseStatus | null> {
    try {
        const response = await fetch(`${base}/v1/meetingsense/status`);
        if (!response.ok) return null;
        return (await response.json()) as MeetingSenseStatus;
    } catch (_) {
        return null;
    }
}
