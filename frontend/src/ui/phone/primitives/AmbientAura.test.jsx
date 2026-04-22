/**
 * Unit tests for ``AmbientAura``.
 *
 * Covers the visual contract (positioning, intensity scaling,
 * hue normalization) + the reduced-motion opt-out.
 */
import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/react';
import AmbientAura from './AmbientAura';
function getLayer(container, idx) {
    const root = container.firstElementChild;
    return root.children[idx];
}
describe('AmbientAura', () => {
    it('renders as a fixed, pointer-events-none, z-index:-1 backdrop', () => {
        const { container } = render(<AmbientAura hue={340}/>);
        const root = container.firstElementChild;
        expect(root.style.position).toBe('fixed');
        expect(root.style.pointerEvents).toBe('none');
        expect(root.style.zIndex).toBe('-1');
    });
    it('is aria-hidden (decorative only)', () => {
        const { container } = render(<AmbientAura hue={340}/>);
        const root = container.firstElementChild;
        expect(root.getAttribute('aria-hidden')).toBe('true');
    });
    it('renders two independently-styled gradient layers', () => {
        const { container } = render(<AmbientAura hue={0}/>);
        const a = getLayer(container, 0);
        const b = getLayer(container, 1);
        expect(a.style.background).not.toBe(b.style.background);
    });
    it('intensity scales the primary layer alpha', () => {
        const lo = render(<AmbientAura hue={340} intensity={0.1}/>);
        const hi = render(<AmbientAura hue={340} intensity={0.9}/>);
        // Same hue, different alpha → the gradient strings must differ.
        expect(getLayer(lo.container, 0).style.background).not.toBe(getLayer(hi.container, 0).style.background);
    });
    it('hue normalizes negatives (-20 → 340)', () => {
        const a = render(<AmbientAura hue={-20}/>);
        const b = render(<AmbientAura hue={340}/>);
        expect(getLayer(a.container, 0).style.background).toBe(getLayer(b.container, 0).style.background);
    });
    it('animated=false sets no animationName', () => {
        const { container } = render(<AmbientAura hue={340} animated={false}/>);
        const a = getLayer(container, 0);
        const b = getLayer(container, 1);
        expect(a.style.animationName).toBe('');
        expect(b.style.animationName).toBe('');
    });
    it('reduced-motion disables animation even when animated=true', () => {
        const mq = {
            matches: true,
            addEventListener: vi.fn(),
            removeEventListener: vi.fn(),
        };
        vi.stubGlobal('matchMedia', vi.fn(() => mq));
        const { container } = render(<AmbientAura hue={340} animated={true}/>);
        expect(getLayer(container, 0).style.animationName).toBe('');
        vi.unstubAllGlobals();
    });
});
