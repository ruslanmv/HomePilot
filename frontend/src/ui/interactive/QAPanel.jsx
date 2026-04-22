/**
 * QAPanel — run the backend checks + render results.
 *
 * On mount we try to fetch the most recent report (latestReport)
 * so a returning author sees the last verdict without clicking.
 * The primary CTA runs a fresh check; the result replaces the
 * displayed report atomically. Issues are grouped by severity
 * (error → warning → info) and sorted within each bucket by code
 * so every run renders the same way.
 *
 * The backend issue shape is permissive — `detail` is a free-form
 * string, but common extras like `node_id` / `edge_id` /
 * `rule_id` get surfaced as chips for quick navigation context.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Info, Play, RefreshCw, ShieldCheck, XCircle, } from "lucide-react";
import { ErrorBanner, Panel, PrimaryButton, SecondaryButton, useToast, } from "./ui";
const VERDICT_STYLES = {
    pass: {
        icon: <ShieldCheck className="w-5 h-5 text-emerald-400" aria-hidden/>,
        border: "border-emerald-500/40", bg: "bg-emerald-500/5",
        label: "Ready to publish", detail: "All checks passed.",
    },
    warn: {
        icon: <AlertTriangle className="w-5 h-5 text-amber-400" aria-hidden/>,
        border: "border-amber-500/40", bg: "bg-amber-500/5",
        label: "Warnings present", detail: "You can publish, but there are concerns worth reviewing.",
    },
    fail: {
        icon: <XCircle className="w-5 h-5 text-red-400" aria-hidden/>,
        border: "border-red-500/40", bg: "bg-red-500/5",
        label: "Blocked", detail: "Fix the errors below before publishing.",
    },
};
export function QAPanel({ api, projectId }) {
    const toast = useToast();
    const [state, setState] = useState({ kind: "empty" });
    const [running, setRunning] = useState(false);
    const [bootstrapError, setBootstrapError] = useState(null);
    const [bootstrapping, setBootstrapping] = useState(true);
    // Pull the latest persisted report on mount so returning users
    // see the most recent verdict without re-running. Silently
    // tolerate "no report yet" (empty dict).
    useEffect(() => {
        const ctrl = new AbortController();
        let cancelled = false;
        setBootstrapping(true);
        setBootstrapError(null);
        api.latestReport(projectId, ctrl.signal)
            .then((resp) => {
            if (cancelled)
                return;
            const report = (resp.report || {});
            const summary = report.summary;
            const issues = report.issues;
            const createdAt = report.created_at;
            if (summary?.verdict && Array.isArray(issues)) {
                setState({
                    kind: "result",
                    result: {
                        verdict: summary.verdict,
                        counts: summary.counts || { error: 0, warning: 0, info: 0, total: issues.length },
                        issues,
                    },
                    at: createdAt ? new Date(createdAt) : null,
                });
            }
        })
            .catch((err) => {
            if (cancelled || err.name === "AbortError")
                return;
            setBootstrapError(err.message || "Couldn't load the latest report.");
        })
            .finally(() => { if (!cancelled)
            setBootstrapping(false); });
        return () => { cancelled = true; ctrl.abort(); };
    }, [api, projectId]);
    const runNow = useCallback(async () => {
        setRunning(true);
        try {
            const result = await api.runQa(projectId);
            setState({ kind: "result", result, at: new Date() });
            toast.toast({
                variant: result.verdict === "fail" ? "error" : result.verdict === "warn" ? "warning" : "success",
                title: `QA ${result.verdict}`,
                message: result.counts.total
                    ? `${result.counts.error} errors · ${result.counts.warning} warnings · ${result.counts.info} info`
                    : "No issues found.",
            });
        }
        catch (err) {
            const e = err;
            toast.toast({
                variant: "error",
                title: "QA run failed",
                message: e.message || "Try again.",
            });
        }
        finally {
            setRunning(false);
        }
    }, [api, projectId, toast]);
    const grouped = useMemo(() => groupIssues(state.kind === "result" ? state.result.issues : []), [state]);
    return (<Panel title="Quality checks" subtitle="Structural + content checks run before publish." actions={<div className="flex gap-2">
          {state.kind === "result" && (<SecondaryButton onClick={runNow} size="sm" loading={running} icon={<RefreshCw className="w-4 h-4" aria-hidden/>}>
              Re-run
            </SecondaryButton>)}
          {state.kind === "empty" && !bootstrapping && (<PrimaryButton onClick={runNow} size="sm" loading={running} icon={<Play className="w-4 h-4" aria-hidden/>}>
              Run QA
            </PrimaryButton>)}
        </div>}>
      {bootstrapError && (<div className="mb-4">
          <ErrorBanner title="Couldn't fetch the latest report" message={bootstrapError} onRetry={() => window.location.reload()}/>
        </div>)}

      {bootstrapping ? (<div className="text-sm text-[#aaa]">Loading latest report…</div>) : state.kind === "empty" ? (<div className="text-sm text-[#aaa]">
          No QA report yet for this project. Click <strong>Run QA</strong> to
          check for structural issues, empty narration, unreachable actions,
          and policy mismatches.
        </div>) : (<div className="flex flex-col gap-4">
          <VerdictBanner result={state.result} at={state.at}/>
          {state.result.counts.total === 0 ? (<div className="text-sm text-emerald-300">
              <CheckCircle2 className="w-4 h-4 inline -mt-0.5 mr-1" aria-hidden/>
              No issues found.
            </div>) : (<div className="flex flex-col gap-4">
              {["error", "warning", "info"].map((sev) => {
                    const issues = grouped[sev];
                    if (!issues || issues.length === 0)
                        return null;
                    return <IssueGroup key={sev} severity={sev} issues={issues}/>;
                })}
            </div>)}
        </div>)}
    </Panel>);
}
// ────────────────────────────────────────────────────────────────
function VerdictBanner({ result, at }) {
    const style = VERDICT_STYLES[result.verdict];
    return (<div className={["rounded-md border p-3 flex items-start gap-3", style.border, style.bg].join(" ")}>
      {style.icon}
      <div className="flex-1 min-w-0">
        <div className="text-sm font-semibold text-[#f1f1f1]">{style.label}</div>
        <div className="text-xs text-[#cfd8dc] mt-0.5">{style.detail}</div>
        <div className="text-[11px] text-[#777] mt-1.5 flex gap-3 flex-wrap">
          <span>{result.counts.error} errors</span>
          <span>{result.counts.warning} warnings</span>
          <span>{result.counts.info} info</span>
          {at && <span>· checked {formatTime(at)}</span>}
        </div>
      </div>
    </div>);
}
function IssueGroup({ severity, issues }) {
    const heading = severity === "error" ? "Errors" : severity === "warning" ? "Warnings" : "Info";
    const IconMap = { error: XCircle, warning: AlertTriangle, info: Info };
    const Icon = IconMap[severity];
    const color = severity === "error"
        ? "text-red-400"
        : severity === "warning"
            ? "text-amber-400"
            : "text-[#3ea6ff]";
    return (<section>
      <h3 className={["text-xs uppercase tracking-wide font-medium mb-2 flex items-center gap-1.5", color].join(" ")}>
        <Icon className="w-3.5 h-3.5" aria-hidden/>
        {heading} · {issues.length}
      </h3>
      <ul className="flex flex-col gap-2">
        {issues.map((issue, i) => <IssueRow key={`${issue.code}-${i}`} issue={issue}/>)}
      </ul>
    </section>);
}
function IssueRow({ issue }) {
    const extras = [];
    for (const k of ["node_id", "edge_id", "action_id", "rule_id", "profile_id"]) {
        const v = issue[k];
        if (typeof v === "string" && v)
            extras.push([k.replace(/_id$/, ""), v]);
    }
    return (<li className="bg-[#121212] border border-[#3f3f3f] rounded-md p-3">
      <div className="flex items-center gap-2 flex-wrap">
        <code className="text-[11px] bg-[#1f1f1f] border border-[#3f3f3f] rounded px-1.5 py-0.5 text-[#cfd8dc]">
          {issue.code}
        </code>
        {extras.map(([k, v]) => (<code key={`${k}:${v}`} className="text-[11px] bg-[#1f1f1f] border border-[#3f3f3f] rounded px-1.5 py-0.5 text-[#777]">
            {k}:{v}
          </code>))}
      </div>
      <p className="mt-1.5 text-sm text-[#f1f1f1]">{issue.detail}</p>
    </li>);
}
function groupIssues(issues) {
    const groups = { error: [], warning: [], info: [] };
    for (const iss of issues) {
        const bucket = groups[iss.severity] || groups.info;
        bucket.push(iss);
    }
    Object.keys(groups).forEach((k) => {
        groups[k].sort((a, b) => a.code.localeCompare(b.code));
    });
    return groups;
}
function formatTime(d) {
    const h = d.getHours().toString().padStart(2, "0");
    const m = d.getMinutes().toString().padStart(2, "0");
    return `${h}:${m}`;
}
