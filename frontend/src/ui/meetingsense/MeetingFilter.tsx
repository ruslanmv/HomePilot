/**
 * The "Meetings" chip in History (batch MS28, wave W10).
 *
 * D5's answer to "where does the catalog live", and the cheaper half of MS28 on purpose: a
 * meeting *is* a conversation, so the surface that costs nothing is the list the user already
 * opens. No nav change, no second place to look, no new mental model — a chip that narrows
 * History to the conversations with a recording behind them.
 *
 * **Off is History exactly as it was.** The chip renders nothing at all when this install has
 * no meetings, so an account that has never recorded one sees the History it has always seen,
 * down to the DOM.
 */
import React from 'react';

export interface MeetingFilterProps {
    /** How many of the conversations on screen are meetings. Zero renders nothing. */
    count: number;
    active: boolean;
    onToggle: (active: boolean) => void;
}

export function MeetingFilter({ count, active, onToggle }: MeetingFilterProps) {
    // Nothing to filter is nothing to offer. A chip reading "Meetings · 0" is a control whose
    // only outcome is an empty list, which teaches the user the feature is broken.
    if (count <= 0) return null;

    return (
        <div className="px-4 pb-3 flex items-center gap-2" data-testid="ms-history-filter">
            <button
                type="button"
                onClick={() => onToggle(!active)}
                aria-pressed={active}
                data-testid="ms-history-chip"
                className={
                    active
                        ? 'px-3 py-1 rounded-full text-xs border border-cyan-500/40 bg-cyan-500/10 text-cyan-200 transition-colors'
                        : 'px-3 py-1 rounded-full text-xs border border-white/10 bg-white/[0.03] text-white/60 hover:text-white/90 hover:border-white/20 transition-colors'
                }
            >
                🎙 Meetings
                <span className="ml-1.5 text-white/40" data-testid="ms-history-count">{count}</span>
            </button>
            {active ? (
                <button
                    type="button"
                    onClick={() => onToggle(false)}
                    className="text-xs text-white/40 hover:text-white/70 transition-colors"
                    data-testid="ms-history-clear"
                >
                    Show everything
                </button>
            ) : null}
        </div>
    );
}

export default MeetingFilter;
