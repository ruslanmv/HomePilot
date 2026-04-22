/**
 * PublishPanel — channel picker + publish flow + version history.
 *
 * Three states the backend can return from POST /publish:
 *
 *   published  New row on ix_publications. Version incremented.
 *   unchanged  Manifest digest matches the latest publication on
 *              this channel — no-op, existing row returned.
 *   blocked    QA verdict is 'fail' at publish time. The author
 *              must fix errors before re-publishing.
 *
 * Each surfaces a distinct toast variant. The version history
 * list below refreshes after every publish attempt so authors
 * see the new row / unchanged state immediately.
 */
import React, { useCallback, useState } from "react";
import { CheckCircle2, Clock, Send, ShieldAlert } from "lucide-react";
import { EmptyState, ErrorBanner, Panel, PrimaryButton, SkeletonRow, useAsyncResource, useToast, } from "./ui";
const CHANNELS = [
    { id: "web_embed", label: "Web embed", hint: "Embeddable player for any website." },
    { id: "studio_preview", label: "Studio preview", hint: "Internal testing / QA walkthroughs." },
    { id: "export", label: "Export", hint: "Downloadable bundle (JSON manifest)." },
];
export function PublishPanel({ api, projectId }) {
    const toast = useToast();
    const [channel, setChannel] = useState("web_embed");
    const [publishing, setPublishing] = useState(false);
    const [lastResult, setLastResult] = useState(null);
    const publications = useAsyncResource((signal) => api.listPublications(projectId, signal), [api, projectId]);
    const publishNow = useCallback(async () => {
        setPublishing(true);
        try {
            const result = await api.publish(projectId, channel);
            setLastResult(result);
            const title = {
                published: "Publish succeeded",
                unchanged: "No changes to publish",
                blocked: "Publish blocked",
            }[result.status];
            const variant = {
                published: "success",
                unchanged: "info",
                blocked: "error",
            }[result.status];
            toast.toast({ variant, title, message: result.detail });
            publications.reload();
        }
        catch (err) {
            const e = err;
            toast.toast({
                variant: "error",
                title: "Publish failed",
                message: e.message || "Check the backend status and try again.",
            });
        }
        finally {
            setPublishing(false);
        }
    }, [api, channel, projectId, publications, toast]);
    return (<div className="flex flex-col gap-6">
      <Panel title="Publish this experience" subtitle="Pick a channel. Publishing runs QA first — a 'fail' verdict will block the attempt." actions={<PrimaryButton onClick={publishNow} loading={publishing} icon={<Send className="w-4 h-4" aria-hidden/>}>
            Publish to {CHANNELS.find((c) => c.id === channel)?.label || channel}
          </PrimaryButton>}>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          {CHANNELS.map((c) => {
            const selected = channel === c.id;
            return (<button key={c.id} type="button" onClick={() => setChannel(c.id)} aria-pressed={selected} className={[
                    "text-left bg-[#121212] border rounded-md p-3 transition-colors",
                    "focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff]",
                    selected
                        ? "border-[#3ea6ff] bg-[rgba(62,166,255,0.08)] ring-1 ring-[#3ea6ff]"
                        : "border-[#3f3f3f] hover:border-[#555] hover:bg-[#1a1a1a]",
                ].join(" ")}>
                <div className="text-sm font-medium text-[#f1f1f1]">{c.label}</div>
                <div className="text-xs text-[#aaa] mt-0.5">{c.hint}</div>
              </button>);
        })}
        </div>

        {lastResult && <ResultBanner result={lastResult}/>}
      </Panel>

      <Panel title="Version history" subtitle="Every successful publish lands here, newest first.">
        {publications.error ? (<ErrorBanner title="Couldn't load publications" message={publications.error} onRetry={publications.reload}/>) : publications.loading && !publications.data ? (<div className="flex flex-col gap-2" aria-busy="true">
            {Array.from({ length: 3 }).map((_, i) => <SkeletonRow key={i}/>)}
          </div>) : (publications.data || []).length === 0 ? (<EmptyState icon={<Clock className="w-12 h-12" aria-hidden/>} title="No publications yet" description="Publishing above will create the first version record."/>) : (<ul className="flex flex-col gap-2">
            {publications.data.map((p) => <PublicationRow key={p.id} pub={p}/>)}
          </ul>)}
      </Panel>
    </div>);
}
function ResultBanner({ result }) {
    const palette = {
        published: { border: "border-emerald-500/40", bg: "bg-emerald-500/5",
            text: "text-emerald-300",
            icon: <CheckCircle2 className="w-4 h-4 text-emerald-400" aria-hidden/> },
        unchanged: { border: "border-[#3ea6ff]/40", bg: "bg-[#3ea6ff]/5",
            text: "text-[#cfd8dc]",
            icon: <Clock className="w-4 h-4 text-[#3ea6ff]" aria-hidden/> },
        blocked: { border: "border-red-500/40", bg: "bg-red-500/5",
            text: "text-red-300",
            icon: <ShieldAlert className="w-4 h-4 text-red-400" aria-hidden/> },
    }[result.status];
    return (<div className={["mt-4 rounded-md border p-3 flex items-start gap-3", palette.border, palette.bg].join(" ")}>
      {palette.icon}
      <div className={["text-sm flex-1 min-w-0", palette.text].join(" ")}>
        <div className="font-medium capitalize">{result.status}</div>
        <div className="text-xs mt-0.5">{result.detail}</div>
        {result.status === "blocked" && result.qa && (<div className="text-xs mt-1.5">
            <span className="font-medium">{result.qa.counts.error}</span> errors,
            {" "}<span className="font-medium">{result.qa.counts.warning}</span> warnings.
            Open the <strong>QA</strong> tab to review.
          </div>)}
        {result.publication && result.status === "published" && (<div className="text-xs mt-1.5 text-[#aaa]">
            v{result.publication.version} · channel {result.publication.channel}
          </div>)}
      </div>
    </div>);
}
function PublicationRow({ pub }) {
    const digest = typeof pub.metadata?.digest === "string"
        ? pub.metadata.digest.slice(0, 12)
        : null;
    return (<li className="bg-[#121212] border border-[#3f3f3f] rounded-md p-3 flex items-center justify-between gap-3">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-[#f1f1f1]">v{pub.version}</span>
          <span className="text-[11px] text-[#777] uppercase tracking-wide">{pub.channel}</span>
        </div>
        {digest && (<div className="text-[11px] text-[#777] mt-0.5">
            digest <code className="text-[#cfd8dc]">{digest}…</code>
          </div>)}
      </div>
      <div className="text-[11px] text-[#777] shrink-0">
        {pub.published_at ? new Date(pub.published_at).toLocaleString() : "—"}
      </div>
    </li>);
}
