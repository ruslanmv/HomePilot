import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const read = (path) => readFileSync(resolve(ROOT, path), 'utf8');

const provider = read('frontend/src/ui/meetingsense/MeetingSenseProvider.tsx');
const workspace = read('frontend/src/ui/meetingsense/MeetingWorkspace.tsx');
const hook = read('frontend/src/ui/meetingsense/useMeetingSense.ts');
const media = read('frontend/public/js/homepilot-meetingsense-media.js');

describe('dedicated Meeting Workspace contract', () => {
    it('mints a dedicated conversation only for the meeting and rolls back failed starts', () => {
        expect(provider).toContain('freshMeetingConversationId()');
        expect(provider).toContain('const nextConversation = freshMeetingConversationId()');
        expect(provider).toContain('conversationId: nextConversation');
        expect(provider).toContain('setWorkspaceMounted(false)');
        expect(provider).toContain('onOpenConversation?.(nextConversation)');
        expect(provider.indexOf('onOpenConversation?.(nextConversation)'))
            .toBeGreaterThan(provider.indexOf('if (!result.ok)'));
    });

    it('restores only origin meeting conversations as Meeting Workspaces', () => {
        expect(provider).toContain("row?.thread_kind === 'origin'");
        expect(provider).toContain('meeting.hydrateRecord(record)');
        expect(provider).toContain('<MeetingWorkspace');
        expect(provider).not.toContain('<RecordingPill');
        expect(provider).not.toContain('<MeetingCard');
    });

    it('uses one authoritative live capture presentation', () => {
        expect(workspace).toContain('HomePilot sees');
        expect(workspace).toContain('Ask about this meeting…');
        expect(workspace).toContain('End & create recap');
        expect(workspace).toContain('These indicators report the actual capture path');
        expect(provider).toContain("button.style.display = 'none'");
        expect(provider).toContain("panel.style.display = 'none'");
        expect(workspace).not.toContain('>Share screen<');
    });

    it('reuses the already granted MeetingSense screen stream instead of opening another share', () => {
        expect(media).toContain('recorder.getScreenPreviewStream = function');
        expect(media).toContain("dispatch('ms:screen_source'");
        expect(media).toContain('recorder.resumeScreenCapture = async function');
        expect(workspace).not.toContain('getDisplayMedia');
    });

    it('drives capture health from tracks and RMS rather than permission alone', () => {
        expect(media).toContain("sourceEvent('microphone', true, 'no_signal'");
        expect(media).toContain("sourceEvent('meeting_audio', true, 'no_signal'");
        expect(media).toContain("sourceEvent(source, true, 'receiving'");
        expect(media).toContain('NO_SIGNAL_MS');
        expect(media).toContain("dispatch('ms:source_changed'");
    });

    it('releases capture immediately when End is confirmed', () => {
        expect(hook).toContain('await recorder?.stop();');
        expect(hook).not.toContain('UNDO_WINDOW_MS');
        expect(hook).not.toContain('setTimeout(finishStop');
        expect(workspace).toContain('stop microphone and screen capture immediately');
        expect(workspace).toContain('Preparing recap');
    });
});
