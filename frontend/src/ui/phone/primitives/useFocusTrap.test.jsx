/**
 * Unit tests for ``useFocusTrap``.
 *
 * Each test names the exact invariant it protects so a regression
 * points at the broken guarantee, not a generic symptom.
 */
import React, { useRef } from 'react';
import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/react';
import { useFocusTrap } from './useFocusTrap';
// Test harness — minimal dialog with three buttons. A trigger button
// sits OUTSIDE the trap to verify the restore-on-unmount path.
const Harness = ({ enabled = true, visible = true }) => {
    const ref = useRef(null);
    useFocusTrap(ref, enabled && visible);
    if (!visible)
        return null;
    return (<div ref={ref} data-testid="trap">
      <button data-testid="first">First</button>
      <button data-testid="middle">Middle</button>
      <button data-testid="last">Last</button>
    </div>);
};
describe('useFocusTrap', () => {
    it('focuses the first tabbable child on mount', () => {
        render(<Harness />);
        expect(document.activeElement?.getAttribute('data-testid')).toBe('first');
    });
    it('wraps Tab from the last child back to the first', () => {
        render(<Harness />);
        const trap = document.querySelector('[data-testid="trap"]');
        const last = document.querySelector('[data-testid="last"]');
        last.focus();
        expect(document.activeElement).toBe(last);
        fireEvent.keyDown(trap, { key: 'Tab' });
        expect(document.activeElement?.getAttribute('data-testid')).toBe('first');
    });
    it('wraps Shift+Tab from the first child back to the last', () => {
        render(<Harness />);
        const trap = document.querySelector('[data-testid="trap"]');
        const first = document.querySelector('[data-testid="first"]');
        first.focus();
        fireEvent.keyDown(trap, { key: 'Tab', shiftKey: true });
        expect(document.activeElement?.getAttribute('data-testid')).toBe('last');
    });
    it('does NOT intercept Tab when focus is mid-list', () => {
        render(<Harness />);
        const trap = document.querySelector('[data-testid="trap"]');
        const middle = document.querySelector('[data-testid="middle"]');
        middle.focus();
        const ev = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true });
        const prevented = !trap.dispatchEvent(ev);
        // Event should NOT be preventDefault'd at an interior position —
        // the browser's native focus order takes over.
        expect(prevented).toBe(false);
    });
    it('restores focus to the previously-focused element on unmount', () => {
        // Mount a trigger via render so we don't depend on direct
        // document manipulation (kept jsdom-agnostic).
        const Trigger = ({ withTrap }) => (<>
        <button data-testid="trigger" autoFocus>Open</button>
        {withTrap ? <Harness /> : null}
      </>);
        const { rerender } = render(<Trigger withTrap={false}/>);
        // The trigger starts focused via autoFocus (jsdom honours it).
        const trigger = document.querySelector('[data-testid="trigger"]');
        trigger.focus();
        expect(document.activeElement).toBe(trigger);
        rerender(<Trigger withTrap={true}/>);
        // Trap seizes focus.
        expect(document.activeElement?.getAttribute('data-testid')).toBe('first');
        rerender(<Trigger withTrap={false}/>);
        // Trap unmounts → restores.
        expect(document.activeElement).toBe(trigger);
    });
    it('no-ops when enabled=false', () => {
        const Holder = () => (<>
        <button data-testid="outside" autoFocus>Outside</button>
        <Harness enabled={false}/>
      </>);
        render(<Holder />);
        const outside = document.querySelector('[data-testid="outside"]');
        outside.focus();
        expect(document.activeElement).toBe(outside);
    });
});
