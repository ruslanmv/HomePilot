/**
 * Meeting intelligence client — the typed analysis, the visual page, suggested questions and
 * server-kept action items (`/v1/meetingsense/library/item/{id}/analysis…`).
 *
 * The types mirror `backend/app/meetingsense/intelligence/schema.py` (schema v1). Kept in its
 * own file so `api.ts` — which the landing page depends on — only ever gains, never changes.
 */
import { backendBase, requestHeaders } from '../api';
import { LibraryError, type LibraryJob } from './api';

export interface Evidence { segment_id?: string | null; t0_ms: number; t1_ms?: number | null; quote: string }
export interface Topic { id: string; label: string; t0_ms: number; t1_ms: number; summary: string }
export type DecisionStatus = 'confirmed' | 'proposed' | 'rejected';
export interface Decision { id: string; statement: string; status: DecisionStatus; topic_id?: string | null; evidence: Evidence[]; confidence: number }
export type Severity = 'high' | 'medium' | 'low';
export interface Risk { id: string; title: string; severity: Severity; detail: string; root_cause: string; solutions: string[]; status: string; evidence: Evidence[] }
export type ActionStatus = 'open' | 'done' | 'dropped';
export interface ActionItem { id: string; text: string; owner?: string | null; due?: string | null; due_text?: string | null; status: ActionStatus; evidence: Evidence[]; confidence: number }
export interface OpenQuestion { id: string; text: string; owner?: string | null; evidence: Evidence[] }
export interface Conclusion { id: string; text: string; evidence: Evidence[] }
export interface SpeakerStat { label: string; talk_ms: number; share: number; lines: number }
export interface ValidatorReport { kept: number; dropped: number; repaired: number; notes: string[] }

export interface MeetingAnalysis {
    schema_version: number;
    meeting_id: string;
    transcript_version_id?: string | null;
    language: string;
    title: string;
    one_line: string;
    topics: Topic[];
    decisions: Decision[];
    risks: Risk[];
    action_items: ActionItem[];
    open_questions: OpenQuestion[];
    conclusions: Conclusion[];
    speakers: SpeakerStat[];
    degraded?: string | null;
    model?: string | null;
    created_at: number;
    validator?: ValidatorReport | null;
}

export type QuestionKind = 'decisions' | 'actions' | 'risks' | 'why' | 'open' | 'general';
export interface SuggestedQuestion { id: string; text: string; kind: QuestionKind }

export type BlockType = 'header' | 'kpi_row' | 'section' | 'risk_cards' | 'decision_list' | 'comparison_table' | 'timeline' | 'callout' | 'quote';
export interface VisualBlock {
    type: BlockType; title?: string | null; items: string[]; text?: string | null;
    columns: string[]; rows: string[][]; tone?: string | null; meta: Record<string, any>;
}
export type ActionBucket = 'Immediate' | 'This week' | 'Next steps';
export interface BriefCard { item: string; title: string; summary: string; note: string; severity: Severity; polished: boolean }
export interface BriefRow { item: string; option: string; status: DecisionStatus; status_label: string; impact: string; polished: boolean }
export interface BriefStep { item: string; bucket: ActionBucket; label: string; text: string; owner?: string | null; polished: boolean }
export interface ExecutiveBrief {
    eyebrow: string; title: string; intro: string;
    risks: BriefCard[]; blockers: BriefCard[]; decisions: BriefRow[]; actions: BriefStep[];
    open_questions: string[]; takeaway: string; takeaway_items: string[];
    source_count: number; polished: boolean; notes: string[];
}
export interface VisualSpec { schema_version: number; analysis_id: string; template: string; blocks: VisualBlock[]; brief?: ExecutiveBrief | null }

export type AnalysisState = 'none' | 'pending' | 'ready' | 'failed' | 'no_transcript';
export interface AnalysisPayload {
    state: AnalysisState;
    job?: LibraryJob | null;
    id?: string; created_at?: number; model?: string | null; degraded?: string | null; schema_version?: number; versions?: number;
    analysis?: MeetingAnalysis; visual?: VisualSpec | null; questions?: SuggestedQuestion[]; report?: ValidatorReport | null;
}

export interface ActionRow {
    id: string; meeting_id: string; analysis_id: string; item_id: string; text: string; owner: string | null; due: string | null;
    due_text: string | null; status: ActionStatus; evidence: Evidence[]; updated_at: number;
}

export type AnalysisItem = Decision | Risk | ActionItem | OpenQuestion | Conclusion | Topic;

/** `d3` → the decision with that id, whichever list holds it. */
export function findItem(analysis: MeetingAnalysis | undefined | null, id: string): AnalysisItem | undefined {
    if (!analysis) return undefined;
    const lists: AnalysisItem[][] = [analysis.decisions, analysis.risks, analysis.action_items, analysis.open_questions, analysis.conclusions, analysis.topics];
    for (const list of lists) {
        const hit = (list || []).find((x) => x.id === id);
        if (hit) return hit;
    }
    return undefined;
}

/** `"00:12:34"` → 754000; a number passes through. */
export function stampToMs(value: string | number | null | undefined): number | null {
    if (typeof value === 'number') return value;
    const m = /(\d{1,2}):(\d{2}):(\d{2})/.exec(String(value || ''));
    if (!m) return null;
    return (Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3])) * 1000;
}

export function msToClock(ms: number): string {
    const total = Math.max(0, Math.floor(ms / 1000));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

/** The analysis as a Markdown document — the download behind "Download .md". */
export function analysisToMarkdown(a: MeetingAnalysis): string {
    const stamp = (e: Evidence[]) => (e.length ? ` _(${msToClock(e[0].t0_ms)})_` : '');
    const out: string[] = [`# ${a.title || 'Meeting'}`, ''];
    if (a.one_line) out.push(a.one_line, '');
    if (a.degraded) out.push('> No language model answered; this is assembled from the meeting\'s own words.', '');
    if (a.decisions.length) {
        out.push('## Decisions', '');
        a.decisions.forEach((d) => out.push(`- **${d.status === 'confirmed' ? 'Confirmed' : d.status === 'rejected' ? 'Rejected' : 'Proposed'}:** ${d.statement}${stamp(d.evidence)}`));
        out.push('');
    }
    if (a.risks.length) {
        out.push('## Risks and problems', '');
        a.risks.forEach((r) => {
            out.push(`- **${r.title}** (${r.severity})${r.detail ? ` — ${r.detail}` : ''}${stamp(r.evidence)}`);
            if (r.root_cause) out.push(`  - Root cause: ${r.root_cause}`);
            r.solutions.forEach((s) => out.push(`  - Solution: ${s}`));
        });
        out.push('');
    }
    if (a.action_items.length) {
        out.push('## Action items', '');
        a.action_items.forEach((x) => out.push(`- [${x.status === 'done' ? 'x' : ' '}] ${x.text}${x.owner ? ` — ${x.owner}` : ''}${x.due_text ? ` (${x.due_text})` : ''}${stamp(x.evidence)}`));
        out.push('');
    }
    if (a.open_questions.length) {
        out.push('## Open questions', '');
        a.open_questions.forEach((q) => out.push(`- ${q.text}${stamp(q.evidence)}`));
        out.push('');
    }
    if (a.conclusions.length) {
        out.push('## Conclusions', '');
        a.conclusions.forEach((c) => out.push(`- ${c.text}${stamp(c.evidence)}`));
        out.push('');
    }
    if (a.topics.length > 1) {
        out.push('## The meeting in order', '');
        a.topics.forEach((t) => out.push(`- **${msToClock(t.t0_ms)}–${msToClock(t.t1_ms)}** ${t.label}${t.summary ? ` — ${t.summary}` : ''}`));
        out.push('');
    }
    return out.join('\n');
}

function url(path: string): string {
    return `${backendBase()}${path}`;
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = { ...requestHeaders(), ...(init.headers as Record<string, string> || {}) };
    let res: Response;
    try {
        res = await fetch(url(path), { credentials: 'include', ...init, headers });
    } catch {
        throw new LibraryError('HomePilot could not be reached.', 0, 'offline');
    }
    let body: any = null;
    try { body = await res.json(); } catch { /* empty body */ }
    if (!res.ok) {
        const detail = body?.detail;
        if (detail && typeof detail === 'object') {
            throw new LibraryError(detail.message || `HTTP ${res.status}`, res.status, detail.code || '', detail.hint || '');
        }
        throw new LibraryError(typeof detail === 'string' ? detail : `HTTP ${res.status}`, res.status);
    }
    return body as T;
}

const json = (body: unknown): RequestInit => ({ body: JSON.stringify(body) });
const item = (meetingId: string) => `/v1/meetingsense/library/item/${encodeURIComponent(meetingId)}`;

export const intelligenceApi = {
    analysis: (meetingId: string) => call<AnalysisPayload>(`${item(meetingId)}/analysis`),
    run: (meetingId: string, body: Record<string, unknown> = {}) =>
        call<{ job: LibraryJob; state: AnalysisState }>(`${item(meetingId)}/analysis`, { method: 'POST', ...json(body) }),
    /** Write the Executive Brief again from the latest analysis, without re-extracting. */
    relayout: (meetingId: string, body: Record<string, unknown> = {}) =>
        call<{ job: LibraryJob; state: AnalysisState }>(`${item(meetingId)}/visual`, { method: 'POST', ...json(body) }),
    questions: (meetingId: string) => call<{ questions: SuggestedQuestion[] }>(`${item(meetingId)}/questions`),
    actions: (meetingId: string) => call<{ actions: ActionRow[] }>(`${item(meetingId)}/actions`),
    updateAction: (meetingId: string, itemId: string, body: Partial<Pick<ActionRow, 'status' | 'owner' | 'due' | 'text'>>) =>
        call<{ action: ActionRow }>(`${item(meetingId)}/actions/${encodeURIComponent(itemId)}`, { method: 'PATCH', ...json(body) }),
};

/** A 404 from the analysis route means the feature is off (or the meeting is not ours). */
export function isNotEnabled(e: unknown): boolean {
    return e instanceof LibraryError && e.status === 404;
}
