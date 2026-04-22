/**
 * Unit tests for streamTts — the pluggable streaming TTS surface.
 * Anchored to § 5.3 of docs/analysis/voice-call-streaming-design.md.
 */
import { describe, it, expect } from 'vitest';
import { createStreamingTts, streamTtsInternals } from './streamTts';
const { splitIntoSentences, NullStreamTts } = streamTtsInternals;
describe('splitIntoSentences', () => {
    it('splits on sentence enders followed by whitespace', () => {
        const { sentences, remainder } = splitIntoSentences('hello there. how are you? fine! and you');
        expect(sentences).toEqual([
            'hello there.',
            'how are you?',
            'fine!',
        ]);
        expect(remainder).toBe('and you');
    });
    it('keeps partial trailing text as remainder', () => {
        const { sentences, remainder } = splitIntoSentences('partial sentence');
        expect(sentences).toEqual([]);
        expect(remainder).toBe('partial sentence');
    });
    it('is safe on empty input', () => {
        const { sentences, remainder } = splitIntoSentences('');
        expect(sentences).toEqual([]);
        expect(remainder).toBe('');
    });
    it('splits on newlines + semicolons', () => {
        const { sentences, remainder } = splitIntoSentences('one thing;\n another thing.\n tail');
        // Exact count + order matters so regressions are obvious.
        expect(sentences.length).toBeGreaterThanOrEqual(2);
        expect(sentences[0]).toContain('one thing');
        expect(remainder.trim()).toBe('tail');
    });
});
describe('NullStreamTts fallback', () => {
    it('is safe to call every method; never claims to be speaking', () => {
        const tts = new NullStreamTts();
        expect(tts.isSpeaking).toBe(false);
        tts.appendDelta('hello');
        tts.flush();
        tts.stop();
        expect(tts.isSpeaking).toBe(false);
    });
});
describe('createStreamingTts factory', () => {
    it('returns an object implementing the StreamingTts contract', () => {
        const tts = createStreamingTts();
        expect(typeof tts.appendDelta).toBe('function');
        expect(typeof tts.flush).toBe('function');
        expect(typeof tts.stop).toBe('function');
        expect(typeof tts.isSpeaking).toBe('boolean');
    });
});
