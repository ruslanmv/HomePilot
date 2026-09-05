/**
 * What the meeting was for (batch MS33, wave W13).
 *
 * The transcript is the recording. This is the product.
 *
 * People record meetings precisely so they do not have to reread them, so Summary, Decisions
 * and Actions are the default view and the transcript is evidence reached for when a specific
 * claim is in doubt. Ten waves shipped the evidence and none shipped the answer.
 *
 * ── The order is the argument ────────────────────────────────────────────────────────────
 *
 *   Summary    what happened, in prose, readable without any interaction at all
 *   Decisions  what is now settled — the thing people ask each other about for weeks
 *   Actions    what is owed, by whom
 *
 * Anything with no content contributes no heading. An empty "Decisions · 0" teaches people
 * the section is unreliable, and they stop reading the ones that do have content.
 *
 * ── Timestamps are navigation ────────────────────────────────────────────────────────────
 *
 * Every item the model cited carries the moment it was said, and clicking it opens the
 * transcript there. A citation that cannot be followed is decoration; one that can is the
 * difference between trusting the summary and rereading the meeting to check it.
 */
import React from 'react';
import { stampLabel } from './meetingState';
import {
    items,
    summaryOf,
    type NoteItem,
} from './meetingRecord';

export interface MeetingSummaryProps {
    body: Record<string, unknown> | null;
    /** Still being written — the last notes window flushes when the meeting stops. */
    pending?: boolean;
    /** Opens the transcript at a moment. Absent leaves stamps as plain text. */
    onSeek?: (ms: number) => void;
}

function Stamp({ t0, onSeek }: { t0?: number; onSeek?: (ms: number) => void }) {
    if (t0 == null) return null;
    const label = stampLabel(t0);
    if (!onSeek) {
        return <span className="ms-sum__stamp" data-testid="ms-sum-stamp">{label}</span>;
    }
    return (
        <button
            type="button"
            className="ms-sum__stamp ms-sum__stamp--link"
            onClick={() => onSeek(t0)}
            title="Show this in the transcript"
            data-testid="ms-sum-stamp"
        >
            {label}
        </button>
    );
}

function ItemList({
    id, items: rows, heading, checkbox, onSeek,
}: {
    id: string;
    items: NoteItem[];
    heading: string;
    checkbox?: boolean;
    onSeek?: (ms: number) => void;
}) {
    if (!rows.length) return null;
    return (
        <section className="ms-sum__block" data-testid={`ms-sum-${id}`}>
            <h4 className="ms-sum__heading">
                {heading}
                <span className="ms-sum__count" data-testid={`ms-sum-${id}-count`}>· {rows.length}</span>
            </h4>
            <ul className="ms-sum__list">
                {rows.map((row, index) => (
                    <li
                        key={`${id}-${index}-${row.text.slice(0, 24)}`}
                        className="ms-sum__item"
                        data-resolved={row.resolved ? 'true' : undefined}
                        data-testid={`ms-sum-${id}-item`}
                    >
                        {checkbox ? <span className="ms-sum__box" aria-hidden="true">☐</span> : null}
                        {/* The owner leads, because "who" is the first thing somebody scanning
                            their own actions is looking for. */}
                        {row.owner ? <span className="ms-sum__owner">{row.owner}</span> : null}
                        <span className="ms-sum__text">{row.text}</span>
                        <Stamp t0={row.t0} onSeek={onSeek} />
                    </li>
                ))}
            </ul>
        </section>
    );
}

export function MeetingSummary({ body, pending = false, onSeek }: MeetingSummaryProps) {
    const summary = summaryOf(body);
    const decisions = items(body, 'decisions');
    const actions = items(body, 'actions');
    const questions = items(body, 'questions').filter((q) => !q.resolved);

    const empty = !summary && !decisions.length && !actions.length && !questions.length;

    if (empty) {
        return (
            <div className="ms-sum ms-sum--empty" data-testid="ms-summary">
                <p className="ms-sum__note" data-testid="ms-sum-empty">
                    {pending
                        ? 'Writing the summary…'
                        // Not an error. A short meeting, or one where nothing was decided,
                        // genuinely has no notes, and saying so is more honest than a spinner
                        // that never resolves.
                        : 'No summary for this meeting. The transcript is below.'}
                </p>
            </div>
        );
    }

    return (
        <div className="ms-sum" data-testid="ms-summary">
            {summary ? (
                <section className="ms-sum__block" data-testid="ms-sum-summary">
                    <h4 className="ms-sum__heading">Summary</h4>
                    <p className="ms-sum__prose">{summary}</p>
                </section>
            ) : null}

            <ItemList id="decisions" heading="Decisions" items={decisions} onSeek={onSeek} />
            <ItemList id="actions" heading="Actions" items={actions} checkbox onSeek={onSeek} />
            {/* Open questions are the third thing a reader wants and the first thing a
                summary usually loses. Resolved ones are filtered out here rather than struck
                through: this is the payoff view, and the meeting's own record keeps them. */}
            <ItemList id="questions" heading="Open questions" items={questions} onSeek={onSeek} />

            {pending ? (
                <p className="ms-sum__note" data-testid="ms-sum-pending">Still writing…</p>
            ) : null}
        </div>
    );
}

export default MeetingSummary;
