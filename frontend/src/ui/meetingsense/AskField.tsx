/**
 * Ask this meeting (batch MS33, wave W13).
 *
 * `POST /v1/meetingsense/{id}/ask` has existed since MS13 and nothing has ever called it from
 * a browser. It is the strongest thing MeetingSense can do after a recording and it had no
 * surface at all.
 *
 * ── Why it ships beside the summary and not alone ────────────────────────────────────────
 *
 * There are two people leaving a meeting: "just tell me what happened" and "I need one
 * specific thing". The summary answers the first with no interaction; this answers the second.
 * Either one alone leaves half the audience doing the work by hand.
 *
 * ── Citations are links ──────────────────────────────────────────────────────────────────
 *
 * The server returns `cited` — the stamps it offered the model that survived into the answer —
 * so a stamp is only made clickable when the server vouched for it. A model that writes
 * "12:30 units" has not cited anything, and turning that into a jump would be the UI inventing
 * a source. `answerParts` does the splitting; this only renders it.
 *
 * The exchange stays on the card rather than being posted into the chat. The question is about
 * the meeting, the answer cites the meeting, and putting them in the conversation would mean
 * every "what was that number" permanently rewrites the thread the meeting was recorded in.
 */
import React, { useCallback, useRef, useState } from 'react';
import { answerParts } from './meetingRecord';

export interface AskExchange {
    id: string;
    question: string;
    answer: string;
    cited: string[];
    error: string | null;
    pending: boolean;
}

export interface AskFieldProps {
    meetingId: string | null;
    /** Injected in tests; defaults to `fetch`. */
    fetcher?: typeof fetch;
    base?: string;
    /** Opens the transcript at a cited moment. */
    onSeek?: (ms: number) => void;
    placeholder?: string;
}

let counter = 0;
const nextId = () => `ask-${(counter += 1)}`;

export function AskField({
    meetingId, fetcher, base = '', onSeek, placeholder = 'Ask this meeting…',
}: AskFieldProps) {
    const [text, setText] = useState('');
    const [exchanges, setExchanges] = useState<AskExchange[]>([]);
    const busy = useRef(false);

    const send = useCallback(async () => {
        const question = text.trim();
        // Two guards, and they are different questions: an empty box is a user pressing Enter
        // on nothing, and `busy` is a second Enter before the first answer landed.
        if (!question || !meetingId || busy.current) return;
        const get = fetcher || (typeof fetch === 'function' ? fetch : null);
        if (!get) return;

        const id = nextId();
        busy.current = true;
        setText('');
        setExchanges((rows) => [
            ...rows,
            { id, question, answer: '', cited: [], error: null, pending: true },
        ]);

        const settle = (patch: Partial<AskExchange>) => {
            setExchanges((rows) => rows.map((row) => (row.id === id ? { ...row, ...patch, pending: false } : row)));
        };

        try {
            const res = await get(`${base}/v1/meetingsense/${encodeURIComponent(meetingId)}/ask`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: question }),
            });
            if (!res.ok) {
                settle({ error: 'That question could not be answered.' });
                return;
            }
            const body = (await res.json()) as { text?: string; cited?: string[]; error?: string };
            if (body?.error && !body?.text) {
                settle({ error: 'That question could not be answered.' });
                return;
            }
            settle({
                answer: typeof body?.text === 'string' ? body.text : '',
                cited: Array.isArray(body?.cited) ? body.cited : [],
            });
        } catch {
            settle({ error: 'That question could not be answered.' });
        } finally {
            busy.current = false;
        }
    }, [text, meetingId, fetcher, base]);

    if (!meetingId) return null;

    return (
        <div className="ms-ask" data-testid="ms-ask">
            {exchanges.length ? (
                <ol className="ms-ask__log" data-testid="ms-ask-log">
                    {exchanges.map((row) => (
                        <li key={row.id} className="ms-ask__turn" data-testid="ms-ask-turn">
                            <p className="ms-ask__q" data-testid="ms-ask-question">{row.question}</p>
                            {row.pending ? (
                                <p className="ms-ask__a ms-ask__a--pending" data-testid="ms-ask-pending">
                                    Looking through the meeting…
                                </p>
                            ) : row.error ? (
                                <p className="ms-ask__a ms-ask__a--error" role="status" data-testid="ms-ask-error">
                                    {row.error}
                                </p>
                            ) : (
                                <p className="ms-ask__a" data-testid="ms-ask-answer">
                                    {answerParts(row.answer, row.cited).map((part, index) =>
                                        part.kind === 'cite' ? (
                                            <button
                                                key={`c${index}`}
                                                type="button"
                                                className="ms-ask__cite"
                                                onClick={() => onSeek?.(part.ms)}
                                                title="Show this in the transcript"
                                                data-testid="ms-ask-cite"
                                            >
                                                {part.text}
                                            </button>
                                        ) : (
                                            <React.Fragment key={`t${index}`}>{part.text}</React.Fragment>
                                        ),
                                    )}
                                </p>
                            )}
                        </li>
                    ))}
                </ol>
            ) : null}

            <form
                className="ms-ask__form"
                onSubmit={(event) => {
                    event.preventDefault();
                    void send();
                }}
            >
                <input
                    type="text"
                    className="ms-ask__input"
                    value={text}
                    onChange={(event) => setText(event.target.value)}
                    placeholder={placeholder}
                    aria-label="Ask this meeting"
                    data-testid="ms-ask-input"
                />
                <button
                    type="submit"
                    className="ms-ask__send"
                    disabled={!text.trim()}
                    aria-label="Ask"
                    data-testid="ms-ask-send"
                >
                    <span aria-hidden="true">↑</span>
                </button>
            </form>
        </div>
    );
}

export default AskField;
