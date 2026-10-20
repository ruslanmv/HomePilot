/**
 * The meeting recording, as one compact row: Play, the title and time, a small waveform and a
 * chevron. The row is what the page shows by default, so the summary stays near the top;
 * Play works from it without opening anything. The chevron (or anywhere on the row) opens the
 * full waveform you can click or arrow through, ±10 s, speed, volume and Download, and the
 * choice is remembered on this computer.
 *
 * The waveform comes from the server (peaks of the stored copy); the audio streams with byte
 * ranges, so seeking an hour-long file does not download it first.
 */
import React, { forwardRef, useCallback, useEffect, useId, useImperativeHandle, useMemo, useRef, useState } from 'react';
import { ChevronDown, Download, Pause, Play, RotateCcw, RotateCw, Volume2, VolumeX } from 'lucide-react';
import { clock } from './format';

export interface PlayerHandle { seek: (ms: number, play?: boolean) => void }

const SPEEDS = [0.75, 1, 1.25, 1.5, 2];
const OPEN_KEY = 'hp_meeting_player_open';
const MINI_BARS = 56;

/** Max-pool `values` into `count` buckets (never more buckets than values). */
export function resample(values: number[], count: number): number[] {
    if (values.length <= count) return values;
    const out: number[] = [];
    const step = values.length / count;
    for (let i = 0; i < count; i += 1) {
        let peak = 0;
        for (let j = Math.floor(i * step); j < Math.floor((i + 1) * step); j += 1) peak = Math.max(peak, values[j] || 0);
        out.push(peak);
    }
    return out;
}

function readOpen(): boolean {
    try {
        return window.localStorage.getItem(OPEN_KEY) === '1';
    } catch {
        return false;
    }
}

export const WaveformPlayer = forwardRef<PlayerHandle, {
    src: string; peaks: number[]; durationMs: number | null; downloadUrl?: string; onTime?: (ms: number) => void; title?: string;
}>(function WaveformPlayer({ src, peaks, durationMs, downloadUrl, onTime, title = 'Meeting recording' }, ref) {
    const audio = useRef<HTMLAudioElement>(null);
    const panelId = useId();
    const [open, setOpen] = useState(readOpen);
    const [playing, setPlaying] = useState(false);
    const [time, setTime] = useState(0);
    const [duration, setDuration] = useState((durationMs || 0) / 1000);
    const [speed, setSpeed] = useState(1);
    const [volume, setVolume] = useState(0.8);
    const [muted, setMuted] = useState(false);
    const [hover, setHover] = useState<number | null>(null);
    const [failed, setFailed] = useState(false);

    useImperativeHandle(ref, () => ({
        seek(ms: number, play = true) {
            const el = audio.current;
            if (!el) return;
            el.currentTime = Math.max(0, ms / 1000);
            if (play) void el.play().catch(() => undefined);
        },
    }), []);

    useEffect(() => { if (audio.current) audio.current.playbackRate = speed; }, [speed]);
    useEffect(() => { if (audio.current) { audio.current.volume = volume; audio.current.muted = muted; } }, [volume, muted]);
    useEffect(() => { try { window.localStorage.setItem(OPEN_KEY, open ? '1' : '0'); } catch { /* ignore */ } }, [open]);

    const toggle = useCallback(() => {
        const el = audio.current;
        if (!el) return;
        if (el.paused) void el.play().catch(() => setFailed(true));
        else el.pause();
    }, []);

    const jump = (delta: number) => {
        const el = audio.current;
        if (!el) return;
        el.currentTime = Math.min(Math.max(0, el.currentTime + delta), duration || el.duration || 0);
    };

    // As many bars as fit (one per 4 px): the server sends a fixed number of peaks, and drawing
    // all of them with gaps on a narrow screen leaves bars too thin to see. Measured when the
    // full waveform opens, since it is not on the page while the row is closed.
    const strip = useRef<HTMLDivElement>(null);
    const [fit, setFit] = useState(120);
    useEffect(() => {
        const el = strip.current;
        if (!open || !el || typeof ResizeObserver === 'undefined') return undefined;
        const measure = () => setFit(Math.max(24, Math.floor(el.clientWidth / 4)));
        measure();
        const ro = new ResizeObserver(measure);
        ro.observe(el);
        return () => ro.disconnect();
    }, [open]);
    const bars = useMemo(() => (peaks.length ? resample(peaks, fit) : Array.from({ length: fit }, () => 0.05)), [peaks, fit]);
    const mini = useMemo(() => (peaks.length ? resample(peaks, MINI_BARS) : Array.from({ length: MINI_BARS }, () => 0.12)), [peaks]);
    const fraction = duration ? time / duration : 0;
    const started = playing || time > 0;

    const seekFromEvent = (e: React.MouseEvent<HTMLDivElement>) => {
        const rect = e.currentTarget.getBoundingClientRect();
        const f = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
        if (audio.current && duration) audio.current.currentTime = f * duration;
    };

    return (
        <section className="rounded-2xl border border-white/10 bg-white/[0.02]" aria-label={title} data-testid="recording-player"
            data-open={open ? 'true' : 'false'}>
            <div className="flex items-center gap-3 px-3 py-2.5 sm:gap-4 sm:px-4">
                {/* Play needs nothing opened first: listening is the one thing most people want here. */}
                <button type="button" onClick={toggle} aria-label={playing ? 'Pause' : 'Play'}
                    className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-violet-600 text-white shadow-lg shadow-violet-900/40 hover:bg-violet-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-300">
                    {playing ? <Pause size={18} /> : <Play size={18} className="translate-x-px" />}
                </button>
                <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-controls={panelId}
                    data-testid="recording-toggle"
                    className="group flex min-w-0 flex-1 items-center gap-4 rounded-xl py-1 pr-1 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-violet-400">
                    <span className="min-w-0 shrink-0">
                        <span className="block truncate font-semibold leading-tight text-white">{title}</span>
                        <span className="mt-0.5 block text-sm tabular-nums text-white/55">
                            {started ? <>{clock(time * 1000)} <span className="text-white/35">/ {clock(duration * 1000)}</span></> : clock(duration * 1000)}
                        </span>
                    </span>
                    {!open ? (
                        <span className="hidden h-7 min-w-0 max-w-xs flex-1 items-center gap-[2px] sm:flex" aria-hidden>
                            {mini.map((v, i) => (
                                <span key={i} className={`w-[2px] shrink-0 rounded-full ${i / mini.length < fraction ? 'bg-violet-400' : 'bg-white/30'}`}
                                    style={{ height: `${Math.max(14, Math.round(v * 100))}%` }} />
                            ))}
                        </span>
                    ) : null}
                    <span className="sr-only">{open ? 'Hide the playback controls' : 'Show the playback controls'}</span>
                    <ChevronDown size={18} aria-hidden
                        className={`ml-auto shrink-0 text-white/55 transition-transform group-hover:text-white ${open ? 'rotate-180' : ''}`} />
                </button>
            </div>

            {open ? (
                <div id={panelId} className="border-t border-white/[0.06] px-4 pb-4 pt-4 sm:px-5" data-testid="recording-controls">
                    <div
                        className="relative h-14 cursor-pointer select-none"
                        onClick={seekFromEvent}
                        onMouseMove={(e) => {
                            const rect = e.currentTarget.getBoundingClientRect();
                            setHover(Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width)));
                        }}
                        onMouseLeave={() => setHover(null)}
                        role="slider"
                        tabIndex={0}
                        aria-label="Position in the recording"
                        aria-valuemin={0}
                        aria-valuemax={Math.round(duration)}
                        aria-valuenow={Math.round(time)}
                        aria-valuetext={`${clock(time * 1000)} of ${clock(duration * 1000)}`}
                        onKeyDown={(e) => {
                            if (e.key === 'ArrowRight') { e.preventDefault(); jump(5); }
                            if (e.key === 'ArrowLeft') { e.preventDefault(); jump(-5); }
                            if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); toggle(); }
                        }}
                    >
                        <div ref={strip} className="flex h-full items-center gap-px">
                            {bars.map((v, i) => {
                                const played = i / bars.length < fraction;
                                return (
                                    <span key={i} className={`flex-1 rounded-full ${played ? 'bg-violet-400' : 'bg-white/25'}`}
                                        style={{ height: `${Math.max(6, Math.round(v * 100))}%` }} />
                                );
                            })}
                        </div>
                        <span className="pointer-events-none absolute top-0 h-full w-0.5 bg-violet-300" style={{ left: `${fraction * 100}%` }} aria-hidden />
                        {hover !== null && duration ? (
                            <span className="pointer-events-none absolute -top-7 -translate-x-1/2 rounded-md border border-white/10 bg-black px-1.5 py-0.5 text-xs tabular-nums"
                                style={{ left: `${hover * 100}%` }}>{clock(hover * duration * 1000)}</span>
                        ) : null}
                    </div>
                    <div className="mt-3 flex flex-wrap items-center gap-2 sm:gap-3">
                        <button type="button" onClick={() => jump(-10)} aria-label="Back 10 seconds" className="grid h-9 w-9 place-items-center rounded-full text-white/75 hover:bg-white/10"><RotateCcw size={17} /></button>
                        <button type="button" onClick={() => jump(10)} aria-label="Forward 10 seconds" className="grid h-9 w-9 place-items-center rounded-full text-white/75 hover:bg-white/10"><RotateCw size={17} /></button>
                        <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))} aria-label="Playback speed"
                            className="h-9 rounded-lg border border-white/10 bg-black px-2 text-sm text-white/80">
                            {SPEEDS.map((s) => <option key={s} value={s}>{s}×</option>)}
                        </select>
                        <div className="flex items-center gap-1.5">
                            <button type="button" onClick={() => setMuted((m) => !m)} aria-label={muted ? 'Unmute' : 'Mute'} className="grid h-9 w-9 place-items-center rounded-full text-white/75 hover:bg-white/10">
                                {muted ? <VolumeX size={17} /> : <Volume2 size={17} />}
                            </button>
                            <input type="range" min={0} max={1} step={0.05} value={volume} onChange={(e) => setVolume(Number(e.target.value))}
                                aria-label="Volume" className="w-20 accent-violet-500 sm:w-24" />
                        </div>
                        {downloadUrl ? (
                            <a href={downloadUrl} className="ml-auto inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 px-3 text-sm text-white/80 hover:bg-white/[0.06]">
                                <Download size={15} /> Download
                            </a>
                        ) : null}
                    </div>
                </div>
            ) : null}
            {failed ? <p className="px-4 pb-3 text-xs text-rose-200 sm:px-5">The recording could not be played in this browser. Use Download in the ⋯ menu.</p> : null}
            <audio
                ref={audio}
                src={src}
                preload="metadata"
                onPlay={() => setPlaying(true)}
                onPause={() => setPlaying(false)}
                onEnded={() => setPlaying(false)}
                onError={() => setFailed(true)}
                onLoadedMetadata={(e) => { const d = e.currentTarget.duration; if (Number.isFinite(d) && d > 0) setDuration(d); }}
                onTimeUpdate={(e) => { const t = e.currentTarget.currentTime; setTime(t); onTime?.(t * 1000); }}
            />
        </section>
    );
});

export default WaveformPlayer;
