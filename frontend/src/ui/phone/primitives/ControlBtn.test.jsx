/**
 * Unit tests for ``ControlBtn``.
 *
 * Covers the variant matrix the handoff specifies + accessibility
 * guarantees. Each test names the exact invariant it protects.
 */
import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ControlBtn from './ControlBtn';
const Icon = () => <svg data-testid="icon" width="10" height="10"/>;
describe('ControlBtn', () => {
    it('renders an aria-labelled button with the visible caption', () => {
        render(<ControlBtn icon={<Icon />} label="Mute"/>);
        const btn = screen.getByRole('button', { name: /mute/i });
        expect(btn).toBeTruthy();
        // Caption is rendered as a sibling — asserting the text is
        // present in the subtree is enough; CSS visibility is not a
        // thing jsdom computes reliably.
        expect(screen.getByText('Mute')).toBeTruthy();
    });
    it('hides the caption when showLabel=false, preserves aria-label', () => {
        render(<ControlBtn icon={<Icon />} label="Mute" showLabel={false}/>);
        expect(screen.getByRole('button', { name: /mute/i })).toBeTruthy();
        // No caption element.
        expect(screen.queryByText('Mute', { selector: 'span' })).toBeNull();
    });
    it('fires onClick when enabled', () => {
        const onClick = vi.fn();
        render(<ControlBtn icon={<Icon />} label="End" onClick={onClick}/>);
        fireEvent.click(screen.getByRole('button', { name: /end/i }));
        expect(onClick).toHaveBeenCalledTimes(1);
    });
    it('suppresses onClick when disabled', () => {
        const onClick = vi.fn();
        render(<ControlBtn icon={<Icon />} label="End" onClick={onClick} disabled/>);
        const btn = screen.getByRole('button', { name: /end/i });
        expect(btn.disabled).toBe(true);
        fireEvent.click(btn);
        expect(onClick).not.toHaveBeenCalled();
    });
    it('renders each tone with a distinct background', () => {
        const { rerender } = render(<ControlBtn icon={<Icon />} label="x" tone="neutral"/>);
        const bg = (name) => screen.getByRole('button', { name }).style.background;
        const neutralBg = bg('x');
        rerender(<ControlBtn icon={<Icon />} label="x" tone="active"/>);
        const activeBg = bg('x');
        rerender(<ControlBtn icon={<Icon />} label="x" tone="danger"/>);
        const dangerBg = bg('x');
        expect(neutralBg).not.toBe(activeBg);
        expect(neutralBg).not.toBe(dangerBg);
        expect(activeBg).not.toBe(dangerBg);
    });
    it('sizes map to 48 / 60 / 72 px', () => {
        const { rerender } = render(<ControlBtn icon={<Icon />} label="x" size="sm"/>);
        const read = () => screen.getByRole('button', { name: 'x' }).style.width;
        expect(read()).toBe('48px');
        rerender(<ControlBtn icon={<Icon />} label="x" size="md"/>);
        expect(read()).toBe('60px');
        rerender(<ControlBtn icon={<Icon />} label="x" size="lg"/>);
        expect(read()).toBe('72px');
    });
    it('reflects pressed state via aria-pressed when provided', () => {
        const { rerender } = render(<ControlBtn icon={<Icon />} label="Mic" pressed={false}/>);
        const btn = screen.getByRole('button', { name: /mic/i });
        expect(btn.getAttribute('aria-pressed')).toBe('false');
        rerender(<ControlBtn icon={<Icon />} label="Mic" pressed={true}/>);
        expect(btn.getAttribute('aria-pressed')).toBe('true');
    });
    it('omits aria-pressed when not a toggle', () => {
        render(<ControlBtn icon={<Icon />} label="End"/>);
        const btn = screen.getByRole('button', { name: /end/i });
        expect(btn.getAttribute('aria-pressed')).toBeNull();
    });
});
