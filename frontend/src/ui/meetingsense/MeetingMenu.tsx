/**
 * Everything secondary (batch MS33, wave W13).
 *
 * Five capabilities have existed on the server for waves with no way to reach them: export,
 * a new thread from a meeting, attaching one to a project, deleting one, and — as of this
 * batch — renaming one. The temptation is a row of five buttons under every meeting. That
 * would make the secondary actions louder than the summary they sit under, on every card,
 * forever.
 *
 * So: one `•••`, and one rule inside it.
 *
 * ── Safe now, deliberate later ───────────────────────────────────────────────────────────
 *
 *   Rename            immediate — it changes a label and the old one is a rename away
 *   Export            immediate — it reads, it writes nothing
 *   Discuss in new chat  immediate — it creates, it destroys nothing
 *   Add to project    a chooser — "which project" has no safe default, and D4 says being
 *                     recorded must never put a meeting into one
 *   Delete meeting    a confirmation naming what goes, and a destructive-styled button
 *
 * "Discuss in new chat" rather than "Continue conversation": `POST /{id}/thread` creates a
 * *new* conversation with a brief in it. "Continue" would describe the opposite of what the
 * button does, and a label that lies about its direction is worse than no label.
 *
 * Delete is last, under a rule, and it is the only item here that cannot be undone by
 * pressing something else afterwards.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';

export type MenuAction = 'rename' | 'export' | 'thread' | 'project' | 'delete';

export interface Project {
    id: string;
    name?: string | null;
}

export interface MeetingMenuProps {
    meetingId: string;
    title: string;
    fetcher?: typeof fetch;
    base?: string;
    /** Navigate to the conversation a new thread created. */
    onOpenConversation?: (conversationId: string) => void;
    /** The meeting is gone; the card should stop rendering it. */
    onDeleted?: () => void;
    /** The title changed on the server. */
    onRenamed?: (title: string) => void;
}

type Dialog = null | 'rename' | 'project' | 'delete';

export function MeetingMenu({
    meetingId, title, fetcher, base = '', onOpenConversation, onDeleted, onRenamed,
}: MeetingMenuProps) {
    const [open, setOpen] = useState(false);
    const [dialog, setDialog] = useState<Dialog>(null);
    const [projects, setProjects] = useState<Project[] | null>(null);
    const [projectId, setProjectId] = useState('');
    const [draftTitle, setDraftTitle] = useState(title);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const wrap = useRef<HTMLDivElement | null>(null);

    const get = useCallback(
        () => fetcher || (typeof fetch === 'function' ? fetch : null),
        [fetcher],
    );

    useEffect(() => {
        if (!open) return undefined;
        const onKey = (event: KeyboardEvent) => {
            if (event.key === 'Escape') setOpen(false);
        };
        const onDown = (event: MouseEvent) => {
            const node = wrap.current;
            if (node && !node.contains(event.target as Node)) setOpen(false);
        };
        document.addEventListener('keydown', onKey);
        document.addEventListener('mousedown', onDown);
        return () => {
            document.removeEventListener('keydown', onKey);
            document.removeEventListener('mousedown', onDown);
        };
    }, [open]);

    const url = (suffix = '') => `${base}/v1/meetingsense/${encodeURIComponent(meetingId)}${suffix}`;

    const exportAs = useCallback((fmt: 'md' | 'srt' | 'json') => {
        setOpen(false);
        try {
            // A plain navigation, because the response carries Content-Disposition and the
            // browser's own download is the thing that respects where the user keeps files.
            // Fetching it into memory to re-offer it would be a worse copy of that.
            window.open(`${url('/export')}?fmt=${fmt}`, '_blank', 'noopener');
        } catch {
            setError('The export could not be opened.');
        }
    }, [meetingId, base]);

    const discuss = useCallback(async () => {
        const call = get();
        if (!call) return;
        setOpen(false);
        setBusy(true);
        try {
            const res = await call(url('/thread'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({}),
            });
            if (!res.ok) throw new Error('failed');
            const body = (await res.json()) as { conversation_id?: string };
            if (body?.conversation_id) onOpenConversation?.(body.conversation_id);
            else setError('The new chat could not be opened.');
        } catch {
            setError('The new chat could not be opened.');
        } finally {
            setBusy(false);
        }
    }, [get, meetingId, base, onOpenConversation]);

    const openProjects = useCallback(async () => {
        setOpen(false);
        setDialog('project');
        setError(null);
        const call = get();
        if (!call || projects) return;
        try {
            const res = await call(`${base}/projects`);
            const body = res.ok ? await res.json() : null;
            const rows = Array.isArray(body) ? body : Array.isArray(body?.projects) ? body.projects : [];
            setProjects(rows as Project[]);
        } catch {
            setProjects([]);
        }
    }, [get, base, projects]);

    // One rule per action, read by both the guard and the button. Written twice they drift,
    // and the direction they drift in is a disabled-looking button that still fires.
    const canAttach = Boolean(projectId) && !busy;
    const canRename = Boolean(draftTitle.trim()) && !busy;

    const attach = useCallback(async () => {
        const call = get();
        if (!call || !canAttach) return;
        setBusy(true);
        try {
            const res = await call(url('/attach'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ project_id: projectId }),
            });
            if (!res.ok) throw new Error('failed');
            setDialog(null);
        } catch {
            setError('The meeting could not be added to that project.');
        } finally {
            setBusy(false);
        }
    }, [get, canAttach, projectId, meetingId, base]);

    const rename = useCallback(async () => {
        const call = get();
        const next = draftTitle.trim();
        if (!call || !canRename) return;
        setBusy(true);
        try {
            const res = await call(url(''), {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title: next }),
            });
            if (!res.ok) throw new Error('failed');
            onRenamed?.(next);
            setDialog(null);
        } catch {
            setError('The meeting could not be renamed.');
        } finally {
            setBusy(false);
        }
    }, [get, canRename, draftTitle, meetingId, base, onRenamed]);

    const remove = useCallback(async () => {
        const call = get();
        if (!call) return;
        setBusy(true);
        try {
            const res = await call(url(''), { method: 'DELETE' });
            if (!res.ok) throw new Error('failed');
            setDialog(null);
            onDeleted?.();
        } catch {
            setError('The meeting could not be deleted.');
        } finally {
            setBusy(false);
        }
    }, [get, meetingId, base, onDeleted]);

    return (
        <div className="ms-menu" ref={wrap} data-testid="ms-menu">
            <button
                type="button"
                className="ms-menu__trigger"
                onClick={() => setOpen((v) => !v)}
                aria-haspopup="menu"
                aria-expanded={open}
                aria-label="More"
                title="More"
                data-testid="ms-menu-trigger"
            >
                <span aria-hidden="true">•••</span>
            </button>

            {open ? (
                <div className="ms-menu__sheet" role="menu" data-testid="ms-menu-sheet">
                    <button type="button" role="menuitem" data-testid="ms-menu-rename"
                        onClick={() => { setOpen(false); setDraftTitle(title); setError(null); setDialog('rename'); }}>
                        Rename meeting
                    </button>
                    <button type="button" role="menuitem" data-testid="ms-menu-export"
                        onClick={() => exportAs('md')}>
                        Export
                    </button>
                    <div className="ms-menu__formats">
                        {(['md', 'srt', 'json'] as const).map((fmt) => (
                            <button key={fmt} type="button" role="menuitem"
                                data-testid={`ms-menu-export-${fmt}`} onClick={() => exportAs(fmt)}>
                                {fmt.toUpperCase()}
                            </button>
                        ))}
                    </div>
                    <button type="button" role="menuitem" data-testid="ms-menu-thread"
                        onClick={() => void discuss()} disabled={busy}>
                        Discuss in new chat
                    </button>
                    <button type="button" role="menuitem" data-testid="ms-menu-project"
                        onClick={() => void openProjects()}>
                        Add to project…
                    </button>
                    <hr className="ms-menu__rule" />
                    <button type="button" role="menuitem" className="ms-menu__danger"
                        data-testid="ms-menu-delete"
                        onClick={() => { setOpen(false); setError(null); setDialog('delete'); }}>
                        Delete meeting…
                    </button>
                </div>
            ) : null}

            {dialog ? (
                <div className="ms-dialog" role="dialog" aria-modal="true"
                    aria-label={dialog === 'delete' ? 'Delete meeting' : dialog === 'project' ? 'Add to project' : 'Rename meeting'}
                    data-testid={`ms-dialog-${dialog}`}>
                    <div className="ms-dialog__panel">
                        {dialog === 'rename' ? (
                            <>
                                <h4 className="ms-dialog__title">Rename meeting</h4>
                                <input
                                    type="text" className="ms-dialog__input" value={draftTitle}
                                    onChange={(e) => setDraftTitle(e.target.value)}
                                    aria-label="Meeting title" data-testid="ms-dialog-title-input"
                                />
                                <div className="ms-dialog__actions">
                                    <button type="button" onClick={() => setDialog(null)} data-testid="ms-dialog-cancel">Cancel</button>
                                    <button type="button" className="ms-dialog__go" onClick={() => void rename()}
                                        disabled={!canRename} data-testid="ms-confirm-rename">Rename</button>
                                </div>
                            </>
                        ) : dialog === 'project' ? (
                            <>
                                <h4 className="ms-dialog__title">Add “{title}” to</h4>
                                <select
                                    className="ms-dialog__select" value={projectId}
                                    onChange={(e) => setProjectId(e.target.value)}
                                    aria-label="Project" data-testid="ms-dialog-project-select"
                                >
                                    <option value="">Choose a project…</option>
                                    {(projects || []).map((p) => (
                                        <option key={p.id} value={p.id}>{p.name || p.id}</option>
                                    ))}
                                </select>
                                {projects && !projects.length ? (
                                    <p className="ms-dialog__note" data-testid="ms-dialog-no-projects">
                                        There are no projects yet.
                                    </p>
                                ) : null}
                                <div className="ms-dialog__actions">
                                    <button type="button" onClick={() => setDialog(null)} data-testid="ms-dialog-cancel">Cancel</button>
                                    {/* Disabled until a project is chosen. There is no sensible
                                        default and D4 forbids guessing one. */}
                                    <button type="button" className="ms-dialog__go" onClick={() => void attach()}
                                        disabled={!canAttach} data-testid="ms-confirm-attach">Add</button>
                                </div>
                            </>
                        ) : (
                            <>
                                <h4 className="ms-dialog__title">Delete “{title}”?</h4>
                                <p className="ms-dialog__note" data-testid="ms-dialog-delete-note">
                                    This permanently removes its transcript, slides, notes and searchable
                                    meeting data.
                                </p>
                                <div className="ms-dialog__actions">
                                    <button type="button" onClick={() => setDialog(null)} data-testid="ms-dialog-cancel">Cancel</button>
                                    <button type="button" className="ms-dialog__danger" onClick={() => void remove()}
                                        disabled={busy} data-testid="ms-confirm-delete">Delete meeting</button>
                                </div>
                            </>
                        )}
                        {error ? <p className="ms-dialog__error" role="status" data-testid="ms-menu-error">{error}</p> : null}
                    </div>
                </div>
            ) : null}

            {error && !dialog ? (
                <span className="ms-menu__error" role="status" data-testid="ms-menu-error">{error}</span>
            ) : null}
        </div>
    );
}

export default MeetingMenu;
