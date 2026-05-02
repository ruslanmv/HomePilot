/**
 * Unit tests for ``Aura``.
 *
 * Pins the identity-stability contract (same seed → same hue) and
 * the visual contract (mood offsets, photoUrl branch, reduced-motion
 * opt-out).
 */
import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/react';
import Aura from './Aura';
function getRootStyle(container) {
    return container.firstElementChild.style;
}
describe('Aura', () => {
    it('renders a role=img with an aria-label', () => {
        const { container } = render(<Aura seed="vesper"/>);
        const img = container.firstElementChild;
        expect(img.getAttribute('role')).toBe('img');
        expect(img.getAttribute('aria-label')).toMatch(/avatar/i);
    });
    it('same seed → identical gradient string across renders', () => {
        const a = render(<Aura seed="vesper"/>);
        const b = render(<Aura seed="vesper"/>);
        expect(getRootStyle(a.container).background).toBe(getRootStyle(b.container).background);
    });
    it('different seeds → different gradient strings', () => {
        const a = render(<Aura seed="vesper"/>);
        const b = render(<Aura seed="atlas"/>);
        expect(getRootStyle(a.container).background).not.toBe(getRootStyle(b.container).background);
    });
    it('mood shifts the gradient vs the default (calm)', () => {
        const calm = render(<Aura seed="vesper" mood="calm"/>);
        const warm = render(<Aura seed="vesper" mood="warm"/>);
        const alert = render(<Aura seed="vesper" mood="alert"/>);
        expect(getRootStyle(calm.container).background).not.toBe(getRootStyle(warm.container).background);
        expect(getRootStyle(calm.container).background).not.toBe(getRootStyle(alert.container).background);
        expect(getRootStyle(warm.container).background).not.toBe(getRootStyle(alert.container).background);
    });
    it('photoUrl path renders an <img> and drops the gradient', () => {
        const { container } = render(<Aura seed="vesper" photoUrl="https://example.test/avatar.png"/>);
        const root = container.firstElementChild;
        // No gradient when a photo is supplied.
        expect(root.style.background).toBe('transparent');
        const img = root.querySelector('img');
        expect(img).toBeTruthy();
        expect(img?.getAttribute('src')).toBe('https://example.test/avatar.png');
    });
    it('size prop controls the rendered width + height', () => {
        const { container } = render(<Aura seed="vesper" size={96}/>);
        const root = container.firstElementChild;
        expect(root.style.width).toBe('96px');
        expect(root.style.height).toBe('96px');
    });
    it('animated=false disables the hue-drift animation', () => {
        const { container } = render(<Aura seed="vesper" animated={false}/>);
        const root = container.firstElementChild;
        // No animationName should be set when motion is opt-out.
        expect(root.style.animationName).toBe('');
    });
    it('reduced-motion disables the hue-drift animation even when animated=true', () => {
        const mq = {
            matches: true,
            addEventListener: vi.fn(),
            removeEventListener: vi.fn(),
        };
        vi.stubGlobal('matchMedia', vi.fn(() => mq));
        const { container } = render(<Aura seed="vesper" animated={true}/>);
        const root = container.firstElementChild;
        expect(root.style.animationName).toBe('');
        vi.unstubAllGlobals();
    });
});
