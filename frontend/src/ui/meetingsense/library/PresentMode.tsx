/**
 * Present mode: the Executive Brief as full-screen slides, one section per slide, from the
 * same validated brief the page shows. Arrow keys and Space move, Escape leaves, and the
 * counter says where you are. Nothing is re-generated for presenting.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { ChevronLeft, ChevronRight, Maximize2, X } from 'lucide-react';
import { ExecutiveBriefView, type BriefSection } from './meeting-summary/ExecutiveBrief';
import type { ExecutiveBrief, MeetingAnalysis } from './intelligenceApi';

export function slidesFor(brief: ExecutiveBrief): BriefSection[][] {
    const slides: BriefSection[][] = [['header']];
    if (brief.risks.length || brief.blockers.length) slides.push(['risks']);
    if (brief.decisions.length) slides.push(['decisions']);
    if (brief.actions.length) slides.push(['actions']);
    if (brief.open_questions.length) slides.push(['questions']);
    if (brief.takeaway) slides.push(['takeaway', 'footer']);
    return slides;
}

export function PresentMode({ analysis, brief, title, onClose, onEvidence }: {
    analysis: MeetingAnalysis; brief: ExecutiveBrief; title: string; onClose: () => void; onEvidence?: (ms: number, itemId: string) => void;
}) {
    const slides = useMemo(() => slidesFor(brief), [brief]);
    const [index, setIndex] = useState(0);
    const last = slides.length - 1;

    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            if (e.key === 'Escape') onClose();
            if (e.key === 'ArrowRight' || e.key === ' ' || e.key === 'PageDown') { e.preventDefault(); setIndex((i) => Math.min(last, i + 1)); }
            if (e.key === 'ArrowLeft' || e.key === 'PageUp') { e.preventDefault(); setIndex((i) => Math.max(0, i - 1)); }
            if (e.key === 'Home') setIndex(0);
            if (e.key === 'End') setIndex(last);
        };
        document.addEventListener('keydown', onKey);
        return () => document.removeEventListener('keydown', onKey);
    }, [last, onClose]);

    const fullscreen = () => { void document.documentElement.requestFullscreen?.().catch(() => undefined); };

    return (
        <div className="fixed inset-0 z-[80] flex flex-col bg-[#07070a] text-white" role="dialog" aria-modal="true" aria-label={`Presenting ${title}`} data-testid="present-mode">
            <header className="flex items-center gap-3 px-5 py-3 text-sm text-white/70">
                <span className="truncate font-medium text-white/90">{title}</span>
                <span className="ml-auto tabular-nums" data-testid="present-counter">{index + 1} / {slides.length}</span>
                <button type="button" onClick={fullscreen} aria-label="Full screen" className="grid h-9 w-9 place-items-center rounded-full hover:bg-white/10"><Maximize2 size={16} /></button>
                <button type="button" onClick={onClose} aria-label="Exit presentation" className="grid h-9 w-9 place-items-center rounded-full hover:bg-white/10"><X size={16} /></button>
            </header>
            <div className="flex min-h-0 flex-1 items-center justify-center px-6 pb-6 sm:px-14">
                <button type="button" onClick={() => setIndex((i) => Math.max(0, i - 1))} disabled={index === 0} aria-label="Previous slide"
                    className="mr-4 hidden h-12 w-12 shrink-0 place-items-center rounded-full border border-white/10 hover:bg-white/10 disabled:opacity-30 sm:grid"><ChevronLeft /></button>
                <div className="hp-present-slide max-h-full w-full max-w-5xl overflow-y-auto">
                    <ExecutiveBriefView analysis={analysis} brief={brief} only={slides[index]} onEvidence={onEvidence} className="text-[1.05rem]" />
                </div>
                <button type="button" onClick={() => setIndex((i) => Math.min(last, i + 1))} disabled={index === last} aria-label="Next slide"
                    className="ml-4 hidden h-12 w-12 shrink-0 place-items-center rounded-full border border-white/10 hover:bg-white/10 disabled:opacity-30 sm:grid"><ChevronRight /></button>
            </div>
            <div className="flex items-center justify-center gap-1.5 pb-4" aria-hidden>
                {slides.map((_, i) => <span key={i} className={`h-1.5 rounded-full transition-all ${i === index ? 'w-6 bg-violet-400' : 'w-1.5 bg-white/25'}`} />)}
            </div>
        </div>
    );
}

export default PresentMode;
