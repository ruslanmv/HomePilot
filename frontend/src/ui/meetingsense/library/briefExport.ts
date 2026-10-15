/**
 * Exports for the Executive Brief: a PDF through the browser's print dialog, and a PNG
 * rendered from the live DOM. Both work on the report element the page already shows, so
 * what prints is exactly what was reviewed.
 *
 * Printing clones the report into a dedicated root; print styles (`styles.css`) hide the
 * application shell and show only that root, so the dark UI never reaches the printer.
 */

const PRINT_ROOT_ID = 'hp-print-root';
const PRINT_CLASS = 'hp-print-brief';

export function printBrief(report: HTMLElement): void {
    const existing = document.getElementById(PRINT_ROOT_ID);
    existing?.remove();
    const root = document.createElement('div');
    root.id = PRINT_ROOT_ID;
    root.appendChild(report.cloneNode(true));
    document.body.appendChild(root);
    document.body.classList.add(PRINT_CLASS);
    const cleanup = () => {
        document.body.classList.remove(PRINT_CLASS);
        root.remove();
        window.removeEventListener('afterprint', cleanup);
    };
    window.addEventListener('afterprint', cleanup);
    // Give the browser a frame to lay the clone out before the dialog snapshots the page.
    window.setTimeout(() => {
        try { window.print(); } finally { window.setTimeout(cleanup, 1500); }
    }, 50);
}

export function safeFilename(title: string, suffix: string): string {
    const base = (title || 'meeting').replace(/[^\w\- ]+/g, '').trim().replace(/\s+/g, '-').toLowerCase() || 'meeting';
    return `${base}-${suffix}`;
}

export async function downloadBriefPng(report: HTMLElement, filename: string): Promise<void> {
    const { toPng } = await import('html-to-image');
    const url = await toPng(report, { pixelRatio: 2, backgroundColor: '#ffffff', cacheBust: true });
    const a = document.createElement('a');
    a.href = url;
    a.download = filename.endsWith('.png') ? filename : `${filename}.png`;
    document.body.appendChild(a);
    a.click();
    a.remove();
}
