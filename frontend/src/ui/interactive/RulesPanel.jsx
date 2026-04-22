/**
 * RulesPanel — personalization rules CRUD.
 *
 * Backend already enforces DSL validation (see
 * personalize/rules.py::validate_rule). We mirror the allowed-key
 * list here so the form can surface local hints, but the final
 * word on validity belongs to the server — on 400 we render the
 * server's `data.problems` array inline.
 *
 * Rules are compact JSON blobs. The form exposes:
 *   - name (free text)
 *   - priority (int; lower = higher priority)
 *   - enabled (toggle)
 *   - condition + action (JSON textareas with live parse errors)
 *
 * Advanced users can edit the JSON directly; typical users see
 * a hint listing the allowed keys so they don't have to read the
 * backend source.
 */
import React, { useCallback, useMemo, useState } from "react";
import { Sparkles, Trash2 } from "lucide-react";
import { DangerButton, EmptyState, ErrorBanner, Modal, Panel, PrimaryButton, SecondaryButton, SkeletonRow, useAsyncResource, useToast, } from "./ui";
const ALLOWED_CONDITION_KEYS = [
    "role", "level", "language", "country",
    "has_tag", "mood", "min_affinity", "max_affinity", "metric",
];
const ALLOWED_ACTION_KEYS = [
    "route_to_node", "prefer_tone", "bump_affinity",
];
export function RulesPanel({ api, projectId }) {
    const toast = useToast();
    const resource = useAsyncResource((signal) => api.listRules(projectId, signal), [api, projectId]);
    const [createOpen, setCreateOpen] = useState(false);
    const [confirmDelete, setConfirmDelete] = useState(null);
    const items = useMemo(() => resource.data || [], [resource.data]);
    const onCreated = useCallback((created) => {
        resource.setData((prev) => {
            const next = [...(prev || []), created];
            next.sort((a, b) => a.priority - b.priority);
            return next;
        });
    }, [resource]);
    const onDelete = useCallback(async () => {
        const target = confirmDelete;
        if (!target)
            return;
        const snapshot = items;
        resource.setData((prev) => (prev || []).filter((r) => r.id !== target.id));
        setConfirmDelete(null);
        try {
            await api.deleteRule(target.id);
            toast.toast({ variant: "success", title: "Rule deleted" });
        }
        catch (err) {
            const e = err;
            resource.setData(snapshot);
            toast.toast({
                variant: "error",
                title: "Couldn't delete rule",
                message: e.message || "The rule has been restored.",
            });
        }
    }, [api, confirmDelete, items, resource, toast]);
    return (<Panel title="Personalization rules" subtitle="Declarative rules that bias the runtime router. Lower priority wins." actions={<PrimaryButton onClick={() => setCreateOpen(true)} size="sm" icon={<Sparkles className="w-4 h-4" aria-hidden/>}>
          New rule
        </PrimaryButton>}>
      {resource.error ? (<ErrorBanner title="Couldn't load rules" message={resource.error} onRetry={resource.reload}/>) : resource.loading && !resource.data ? (<div className="flex flex-col gap-2" aria-busy="true">
          {Array.from({ length: 3 }).map((_, i) => <SkeletonRow key={i}/>)}
        </div>) : items.length === 0 ? (<EmptyState icon={<Sparkles className="w-12 h-12" aria-hidden/>} title="No personalization rules" description="Rules let you route viewers based on mood, affinity, or audience facets. Great for adaptive paths without coding." action={<PrimaryButton onClick={() => setCreateOpen(true)} icon={<Sparkles className="w-4 h-4" aria-hidden/>}>
              Add your first rule
            </PrimaryButton>}/>) : (<ul className="flex flex-col gap-2">
          {items.map((r) => (<RuleRow key={r.id} rule={r} onDelete={() => setConfirmDelete(r)}/>))}
        </ul>)}

      <NewRuleModal open={createOpen} onClose={() => setCreateOpen(false)} api={api} projectId={projectId} onCreated={(r) => {
            onCreated(r);
            setCreateOpen(false);
            toast.toast({ variant: "success", title: "Rule created", message: r.name });
        }}/>

      <Modal open={!!confirmDelete} onClose={() => setConfirmDelete(null)} title="Delete rule?" footer={<>
            <SecondaryButton onClick={() => setConfirmDelete(null)}>Cancel</SecondaryButton>
            <DangerButton onClick={onDelete} icon={<Trash2 className="w-4 h-4" aria-hidden/>}>
              Delete
            </DangerButton>
          </>}>
        <p className="text-sm text-[#cfd8dc]">
          This permanently removes <span className="font-medium">{confirmDelete?.name}</span>.
        </p>
      </Modal>
    </Panel>);
}
// ────────────────────────────────────────────────────────────────
// Rule row
// ────────────────────────────────────────────────────────────────
function RuleRow({ rule, onDelete }) {
    const condKeys = Object.keys(rule.condition || {});
    const actionKeys = Object.keys(rule.action || {});
    return (<li className="bg-[#121212] border border-[#3f3f3f] rounded-md p-3 flex items-start justify-between gap-3">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium text-[#f1f1f1]">{rule.name}</span>
          <span className="text-[10px] text-[#777]">priority {rule.priority}</span>
          {!rule.enabled && (<span className="text-[10px] uppercase tracking-wide text-amber-300 bg-amber-400/10 border border-amber-400/30 rounded px-1.5 py-0.5">
              disabled
            </span>)}
        </div>
        <div className="mt-1.5 flex flex-wrap gap-1.5 text-[11px]">
          {condKeys.length > 0 ? condKeys.map((k) => (<code key={`c:${k}`} className="bg-[#1f1f1f] border border-[#3f3f3f] rounded px-1.5 py-0.5 text-[#cfd8dc]">
              when {k}
            </code>)) : <span className="text-[#777]">no conditions</span>}
          {actionKeys.map((k) => (<code key={`a:${k}`} className="bg-[#3ea6ff]/10 border border-[#3ea6ff]/40 rounded px-1.5 py-0.5 text-[#3ea6ff]">
              → {k}
            </code>))}
        </div>
      </div>
      <button type="button" onClick={onDelete} aria-label={`Delete ${rule.name}`} className="text-[#aaa] hover:text-red-400 p-1 rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500">
        <Trash2 className="w-4 h-4" aria-hidden/>
      </button>
    </li>);
}
// ────────────────────────────────────────────────────────────────
// New-rule modal
// ────────────────────────────────────────────────────────────────
function NewRuleModal({ open, onClose, api, projectId, onCreated, }) {
    const toast = useToast();
    const [name, setName] = useState("");
    const [priority, setPriority] = useState(100);
    const [enabled, setEnabled] = useState(true);
    const [conditionText, setConditionText] = useState('{\n  "mood": "flirty"\n}');
    const [actionText, setActionText] = useState('{\n  "bump_affinity": 0.05\n}');
    const [submitting, setSubmitting] = useState(false);
    const [serverProblems, setServerProblems] = useState(null);
    const conditionErr = useMemo(() => parseJsonError(conditionText), [conditionText]);
    const actionErr = useMemo(() => parseJsonError(actionText), [actionText]);
    const reset = useCallback(() => {
        setName("");
        setPriority(100);
        setEnabled(true);
        setConditionText('{\n  "mood": "flirty"\n}');
        setActionText('{\n  "bump_affinity": 0.05\n}');
        setServerProblems(null);
    }, []);
    const canSubmit = name.trim().length > 0 && !conditionErr && !actionErr && !submitting;
    const submit = useCallback(async () => {
        if (!canSubmit)
            return;
        setSubmitting(true);
        setServerProblems(null);
        try {
            const condition = JSON.parse(conditionText);
            const action = JSON.parse(actionText);
            const created = await api.createRule(projectId, {
                name: name.trim(), condition, action,
                priority, enabled,
            });
            reset();
            onCreated(created);
        }
        catch (err) {
            const e = err;
            const problems = Array.isArray(e.data?.problems) ? e.data.problems : null;
            if (problems && problems.length > 0) {
                setServerProblems(problems);
            }
            else {
                toast.toast({
                    variant: "error",
                    title: "Couldn't create rule",
                    message: e.message || "Check the JSON and try again.",
                });
            }
            setSubmitting(false);
        }
    }, [actionText, api, canSubmit, conditionText, enabled, name, onCreated, priority, projectId, reset, toast]);
    return (<Modal open={open} onClose={() => { if (!submitting) {
        reset();
        onClose();
    } }} title="New personalization rule" widthClass="max-w-2xl" footer={<>
          <SecondaryButton onClick={() => { reset(); onClose(); }} disabled={submitting}>
            Cancel
          </SecondaryButton>
          <PrimaryButton onClick={submit} disabled={!canSubmit} loading={submitting}>
            Create
          </PrimaryButton>
        </>}>
      <div className="flex flex-col gap-4">
        <Field label="Name" required>
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Warm up when the viewer is flirty" maxLength={80} className="w-full bg-[#121212] border border-[#3f3f3f] rounded-md px-3 py-2 text-sm outline-none focus:border-[#3ea6ff]"/>
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Priority" hint="Lower wins ties. Default 100.">
            <input type="number" min={1} max={1000} value={priority} onChange={(e) => setPriority(Math.max(1, parseInt(e.target.value, 10) || 1))} className="w-full bg-[#121212] border border-[#3f3f3f] rounded-md px-3 py-2 text-sm outline-none focus:border-[#3ea6ff]"/>
          </Field>
          <Field label="Enabled">
            <label className="inline-flex items-center gap-2 mt-1">
              <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} className="accent-[#3ea6ff]"/>
              <span className="text-sm text-[#cfd8dc]">Active at runtime</span>
            </label>
          </Field>
        </div>

        <Field label="Condition (JSON)" hint={`Allowed keys: ${ALLOWED_CONDITION_KEYS.join(", ")}.`}>
          <textarea rows={5} value={conditionText} onChange={(e) => setConditionText(e.target.value)} className={[
            "w-full bg-[#121212] border rounded-md px-3 py-2 text-xs font-mono outline-none",
            conditionErr ? "border-red-500/50 focus:border-red-500" : "border-[#3f3f3f] focus:border-[#3ea6ff]",
        ].join(" ")} spellCheck={false}/>
          {conditionErr && <p className="text-[11px] text-red-400 mt-1">{conditionErr}</p>}
        </Field>

        <Field label="Action (JSON)" hint={`Allowed keys: ${ALLOWED_ACTION_KEYS.join(", ")}.`}>
          <textarea rows={4} value={actionText} onChange={(e) => setActionText(e.target.value)} className={[
            "w-full bg-[#121212] border rounded-md px-3 py-2 text-xs font-mono outline-none",
            actionErr ? "border-red-500/50 focus:border-red-500" : "border-[#3f3f3f] focus:border-[#3ea6ff]",
        ].join(" ")} spellCheck={false}/>
          {actionErr && <p className="text-[11px] text-red-400 mt-1">{actionErr}</p>}
        </Field>

        {serverProblems && serverProblems.length > 0 && (<div role="alert" className="border border-red-500/40 bg-red-500/5 rounded-md p-3 text-xs text-red-300">
            <div className="font-medium mb-1">The server rejected this rule:</div>
            <ul className="list-disc pl-5 space-y-0.5">
              {serverProblems.map((p, i) => <li key={i}>{p}</li>)}
            </ul>
          </div>)}
      </div>
    </Modal>);
}
function Field({ label, hint, required, children, }) {
    return (<div className="flex flex-col gap-1">
      <label className="text-xs font-medium text-[#cfd8dc]">
        {label}
        {required && <span className="text-[#3ea6ff] ml-0.5" aria-label="required">*</span>}
      </label>
      {hint && <p className="text-[11px] text-[#777] -mt-0.5">{hint}</p>}
      {children}
    </div>);
}
function parseJsonError(text) {
    try {
        const parsed = JSON.parse(text);
        if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
            return "Must be a JSON object.";
        }
        return null;
    }
    catch (e) {
        return `Invalid JSON: ${e.message}`;
    }
}
