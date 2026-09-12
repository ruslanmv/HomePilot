import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const read = (path) => readFileSync(resolve(ROOT, path), 'utf8');

const settings = read('frontend/src/ui/components/AudioVideoSettings.tsx');
const controller = read('frontend/src/ui/voice/useVoiceController.ts');
const vad = read('frontend/src/ui/voice/vad.ts');
const chatPanel = read('frontend/src/ui/VoicePanel.tsx');
const debug = read('frontend/src/ui/media/microphoneDebug.ts');

describe('microphone diagnostics and settings playback contract', () => {
  it('records a real local microphone sample and exposes playback', () => {
    expect(settings).toContain('new MediaRecorder(stream)');
    expect(settings).toContain('MICROPHONE_TEST_MS = 5000');
    expect(settings).toContain('recording_ready');
    expect(settings).toContain('<audio');
    expect(settings).toContain('Playback your microphone recording');
    expect(settings).toContain('never uploads the recording');
  });

  it('removes the duplicated troubleshooting test grid', () => {
    expect(settings).not.toContain('title="Troubleshooting"');
    expect(settings).not.toContain('Run audio test');
    expect(settings).not.toContain('Run video test');
    expect(settings).not.toContain('Run screen test');
    expect(settings).not.toContain('testScreenSharing');
  });

  it('awaits browser speech recognition instead of treating a click as success', () => {
    expect(controller).toContain('await Promise.resolve(svc.startSTT({}))');
    expect(controller).toContain('stt_start_accepted');
    expect(controller).toContain('stt_start_rejected');
    expect(controller).toContain('browser-managed-web-speech');
  });

  it('traces the selected VAD microphone and real track lifecycle', () => {
    expect(vad).toContain("microphoneDebug('vad', 'capture_request'");
    expect(vad).toContain("microphoneDebug('vad', 'capture_opened'");
    expect(vad).toContain("microphoneDebug('vad', 'track_ended'");
    expect(vad).toContain("microphoneDebug('vad', 'speech_detected'");
  });

  it('traces microphone button clicks from chat', () => {
    expect(chatPanel).toContain("microphoneDebug('chat', 'talk_button_click'");
    expect(chatPanel).toContain('void voice.startManualListening()');
  });

  it('keeps a bounded metadata-only trace buffer for DevTools debugging', () => {
    expect(debug).toContain('__HOMEPILOT_MIC_DEBUG__');
    expect(debug).toContain('MAX_ENTRIES = 200');
    expect(debug).toContain('no audio bytes and no recognized transcript');
    expect(debug).toContain('[HomePilot:Mic]');
  });
});
