/**
 * The two things the header's Meeting control can say (batch MS32, wave W12).
 *
 * MS29 put a record button under the composer and let it explain itself in place: a disabled
 * control with a sentence next to it, permanently, on every chat screen. That sentence was
 * the server's own `stt.hint` — `Set WHISPER_MODEL (e.g. small) …` — so a person who never
 * intends to record a meeting was reading an environment-variable name under their message
 * box forever.
 *
 * Two rules come out of that and this file exists to hold them:
 *
 * **A setup problem is contextual, not permanent.** Nothing about configuration is on screen
 * until somebody presses the control that needs it. `SetupPanel` is what they get then.
 *
 * **Normal users are never shown environment-variable names.** The server's hint is precise
 * and belongs somewhere — Settings → Voice Assistant → Meeting transcription, where somebody
 * has already chosen to look at configuration (`MeetingTranscriptionCard`). Here the copy
 * names the capability and points at that page, which is the whole of what a chat user can
 * act on.
 *
 * Both panels are pure presentation with no context and no fetches, so the copy is assertable
 * without a provider and the header control stays a state machine rather than a page.
 */
import React from 'react';
import { elapsedLabel } from './meetingState';
import type { MeetingSenseStatus } from './entryPoint';

/** Why the meeting control cannot start a meeting, in a chat user's terms. */
export interface MeetingBlock {
    /** Stable id, so a test names a case rather than matching prose. */
    id: 'off' | 'no-conversation' | 'no-stt';
    title: string;
    body: string;
    /** Whether Settings can actually fix it. "The server has it off" cannot. */
    settings: boolean;
}

/**
 * The blocked state, or `null` when a meeting can start.
 *
 * Deliberately *not* `MeetingButton.blockedReason`: that one returns the server's hint
 * verbatim, which is right for a developer-facing surface and wrong for this one. Two
 * functions rather than a flag because they answer to different audiences, and a shared one
 * with a `technical` parameter is how the env-var string leaks back into chat.
 */
export function meetingBlock(
    status: MeetingSenseStatus | null,
    conversationId: string | null,
): MeetingBlock | null {
    if (!status?.enabled) {
        return {
            id: 'off',
            title: 'Meetings are unavailable',
            body: 'This HomePilot server has meeting capture turned off.',
            settings: false,
        };
    }
    if (!conversationId) {
        return {
            id: 'no-conversation',
            title: 'Open a conversation first',
            body: 'A meeting is recorded into a conversation, so start or open one and try again.',
            settings: false,
        };
    }
    if (status.stt && status.stt.available === false) {
        return {
            id: 'no-stt',
            title: "Meeting transcription isn't configured",
            body: 'Configure a transcription provider to use meeting mode.',
            settings: true,
        };
    }
    return null;
}

export interface SetupPanelProps {
    block: MeetingBlock;
    onOpenSettings: () => void;
    onClose: () => void;
}

/** What a press produces when the meeting cannot start. Shown on click, never before. */
export function SetupPanel({ block, onOpenSettings, onClose }: SetupPanelProps) {
    return (
        <div data-testid="ms-setup-panel" data-block={block.id} className="flex flex-col gap-2">
            <div className="text-[13px] text-white/90 font-medium leading-snug">{block.title}</div>
            <div className="text-[12px] text-white/45 leading-relaxed">{block.body}</div>
            {block.settings ? (
                <button
                    type="button"
                    onClick={() => {
                        onClose();
                        onOpenSettings();
                    }}
                    data-testid="ms-setup-settings"
                    className={[
                        'mt-1 self-start px-3 py-1.5 rounded-lg text-[12px]',
                        'bg-white/[0.06] border border-white/10 text-white/80',
                        'hover:bg-white/10 hover:text-white active:bg-white/[0.14]',
                        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/30',
                        'transition-colors duration-150',
                    ].join(' ')}
                >
                    Open Settings
                </button>
            ) : null}
        </div>
    );
}

export interface LivePanelProps {
    elapsedMs: number;
    /** `phaseLabel`-style wording, already resolved by the caller. */
    phase: string;
    micMuted: boolean;
    stopping: boolean;
    undoSecondsLeft?: number | null;
    onMute: (muted: boolean) => void;
    onEnd: () => void;
    onUndo: () => void;
}

/**
 * The running meeting, in a popover that does not move the chat.
 *
 * There is no Pause. The recorder has mute and it has stop, and a "Pause" that silently means
 * "mute the microphone" would tell somebody their meeting is paused while the room is still
 * being captured — the one lie a recording control must never tell. The button says the thing
 * it does.
 *
 * Stop is a ten-second countdown, not an instant (MS6): the seconds a user spends deciding are
 * usually the seconds somebody was still talking, so capture keeps running and Undo leaves no
 * hole. The panel shows that countdown rather than pretending the meeting has ended.
 */
export function LivePanel({
    elapsedMs, phase, micMuted, stopping, undoSecondsLeft, onMute, onEnd, onUndo,
}: LivePanelProps) {
    return (
        <div data-testid="ms-live-panel" className="flex flex-col gap-2.5">
            <div className="flex items-baseline justify-between gap-3">
                <span className="text-[13px] text-white/90 font-medium">Meeting</span>
                <span
                    className="text-[13px] text-white/70 tabular-nums"
                    data-testid="ms-panel-elapsed"
                >
                    {elapsedLabel(elapsedMs)}
                </span>
            </div>
            <div className="flex items-center gap-2 text-[12px] text-white/45">
                <span
                    aria-hidden="true"
                    className="w-1.5 h-1.5 rounded-full bg-red-400 shrink-0"
                />
                <span data-testid="ms-panel-phase">{phase}</span>
            </div>
            <div className="flex items-center gap-2 pt-0.5">
                {stopping ? (
                    <button
                        type="button"
                        onClick={onUndo}
                        data-testid="ms-panel-undo"
                        className={[
                            'px-3 py-1.5 rounded-lg text-[12px]',
                            'bg-white/[0.06] border border-white/10 text-white/80',
                            'hover:bg-white/10 hover:text-white active:bg-white/[0.14]',
                            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/30',
                            'transition-colors duration-150',
                        ].join(' ')}
                    >
                        Undo{undoSecondsLeft != null ? ` · ${undoSecondsLeft}s` : ''}
                    </button>
                ) : (
                    <>
                        <button
                            type="button"
                            onClick={() => onMute(!micMuted)}
                            aria-pressed={micMuted}
                            data-testid="ms-panel-mute"
                            className={[
                                'px-3 py-1.5 rounded-lg text-[12px]',
                                'bg-white/[0.06] border border-white/10 text-white/80',
                                'hover:bg-white/10 hover:text-white active:bg-white/[0.14]',
                                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/30',
                                'transition-colors duration-150',
                            ].join(' ')}
                        >
                            {micMuted ? 'Unmute mic' : 'Mute mic'}
                        </button>
                        <button
                            type="button"
                            onClick={onEnd}
                            data-testid="ms-panel-end"
                            className={[
                                'px-3 py-1.5 rounded-lg text-[12px]',
                                'bg-red-500/10 border border-red-500/30 text-red-200',
                                'hover:bg-red-500/20 active:bg-red-500/25',
                                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400/40',
                                'transition-colors duration-150',
                            ].join(' ')}
                        >
                            End meeting
                        </button>
                    </>
                )}
            </div>
        </div>
    );
}

export default LivePanel;
