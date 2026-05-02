/**
 * Unit tests for the pure detector in bargeIn.ts. Covers the exact
 * § 6 invariants (single-spike rejection, sustain gate, refractory).
 * The hook form is intentionally not tested here — it's a thin
 * wrapper around the detector + rAF; coverage lives in the overlay
 * integration path.
 */
import { describe, it, expect } from 'vitest';
import { detectBargeIn } from './bargeIn';
const OPTS = {
    threshold: 0.08,
    minSustainMs: 80,
    minRefractoryMs: 400,
};
function genConstant(level, durMs, stepMs = 16) {
    const out = [];
    for (let t = 0; t <= durMs; t += stepMs) {
        out.push({ tMs: t, level });
    }
    return out;
}
describe('detectBargeIn', () => {
    it('fires once after sustained speech above threshold', () => {
        // Steady high level for 200 ms — comfortably over the 80 ms sustain.
        const events = detectBargeIn(genConstant(0.2, 200), OPTS);
        expect(events.length).toBe(1);
        expect(events[0]).toBeGreaterThanOrEqual(OPTS.minSustainMs);
    });
    it('does NOT fire on a single spike below sustain', () => {
        // One 16 ms spike followed by silence. Below 80 ms sustain → drops.
        const samples = [
            { tMs: 0, level: 0.0 },
            { tMs: 16, level: 0.2 },
            { tMs: 32, level: 0.0 },
            { tMs: 48, level: 0.0 },
            { tMs: 64, level: 0.0 },
        ];
        expect(detectBargeIn(samples, OPTS)).toEqual([]);
    });
    it('does NOT fire when level never exceeds threshold', () => {
        const events = detectBargeIn(genConstant(0.04, 400), OPTS);
        expect(events).toEqual([]);
    });
    it('honours the refractory window (no double-fire during sustained speech)', () => {
        // 1500 ms of steady speech. Without refractory we'd fire every
        // tick after 80 ms. With refractory we fire at most once per
        // minRefractoryMs (~400 ms).
        const events = detectBargeIn(genConstant(0.2, 1500), OPTS);
        expect(events.length).toBeGreaterThan(0);
        // At 16 ms steps and 400 ms refractory: expect ~3 events.
        expect(events.length).toBeLessThanOrEqual(4);
        // Consecutive events must be at least refractory-ms apart.
        for (let i = 1; i < events.length; i++) {
            expect(events[i] - events[i - 1]).toBeGreaterThanOrEqual(OPTS.minRefractoryMs);
        }
    });
    it('resets the sustain counter after a dip below threshold', () => {
        // 50 ms above, 30 ms below, 100 ms above. First run is too short;
        // second run also too short on its own because counter reset.
        const samples = [
            ...Array.from({ length: 4 }, (_, i) => ({
                tMs: i * 16, level: 0.2,
            })),
            { tMs: 64, level: 0.0 },
            { tMs: 80, level: 0.0 },
            ...Array.from({ length: 4 }, (_, i) => ({
                tMs: 96 + i * 16, level: 0.2,
            })),
        ];
        expect(detectBargeIn(samples, OPTS)).toEqual([]);
    });
});
