/**
 * CatalogPanel — CRUD for ix_action_catalog.
 *
 * Table view of actions (label, intent, level gate, scheme, XP,
 * cooldown) plus a "+ New action" modal. Delete is gated by a
 * confirm modal so one misclick doesn't nuke a gating action.
 *
 * Mutations are optimistic: create injects a tombstone row into
 * the cached data with a local id, rolls back on failure; delete
 * removes the row immediately and re-inserts it if the server
 * rejects. Both paths surface a toast.
 */
import React, { useCallback, useMemo, useState } from "react";
import { ListChecks, Plus, Trash2 } from "lucide-react";
import { DangerButton, EmptyState, ErrorBanner, Modal, Panel, PrimaryButton, SecondaryButton, SkeletonRow, useAsyncResource, useToast, } from "./ui";
const SCHEMES = [
    "xp_level", "mastery", "cefr", "affinity_tier", "certification",
];
export function CatalogPanel({ api, projectId }) {
    const toast = useToast();
    const resource = useAsyncResource((signal) => api.listActions(projectId, signal), [api, projectId]);
    const [createOpen, setCreateOpen] = useState(false);
    const [confirmDelete, setConfirmDelete] = useState(null);
    const items = useMemo(() => resource.data || [], [resource.data]);
    const onCreated = useCallback((created) => {
        resource.setData((prev) => [...(prev || []), created]);
    }, [resource]);
    const onDelete = useCallback(async () => {
        const target = confirmDelete;
        if (!target)
            return;
        const snapshot = items;
        resource.setData((prev) => (prev || []).filter((a) => a.id !== target.id));
        setConfirmDelete(null);
        try {
            await api.deleteAction(target.id);
            toast.toast({ variant: "success", title: "Action deleted" });
        }
        catch (err) {
            const e = err;
            resource.setData(snapshot);
            toast.toast({
                variant: "error",
                title: "Couldn't delete",
                message: e.message || "The action has been restored.",
            });
        }
    }, [api, confirmDelete, items, resource, toast]);
    return (<Panel title="Action catalog" subtitle="Actions viewers can take during playback. Level gates, cooldowns, and XP rewards apply per-turn." actions={<PrimaryButton onClick={() => setCreateOpen(true)} size="sm" icon={<Plus className="w-4 h-4" aria-hidden/>}>
          New action
        </PrimaryButton>}>
      {resource.error ? (<ErrorBanner title="Couldn't load the catalog" message={resource.error} onRetry={resource.reload}/>) : resource.loading && !resource.data ? (<div className="flex flex-col gap-2" aria-busy="true">
          {Array.from({ length: 4 }).map((_, i) => <SkeletonRow key={i}/>)}
        </div>) : items.length === 0 ? (<EmptyState icon={<ListChecks className="w-12 h-12" aria-hidden/>} title="No actions yet" description="Add at least one action to give viewers something to do during playback." action={<PrimaryButton onClick={() => setCreateOpen(true)} icon={<Plus className="w-4 h-4" aria-hidden/>}>
              Add your first action
            </PrimaryButton>}/>) : (<ActionTable items={items} onDelete={setConfirmDelete}/>)}

      <NewActionModal open={createOpen} onClose={() => setCreateOpen(false)} api={api} projectId={projectId} onCreated={(a) => {
            onCreated(a);
            setCreateOpen(false);
            toast.toast({ variant: "success", title: "Action created", message: a.label });
        }}/>

      <Modal open={!!confirmDelete} onClose={() => setConfirmDelete(null)} title="Delete action?" footer={<>
            <SecondaryButton onClick={() => setConfirmDelete(null)}>Cancel</SecondaryButton>
            <DangerButton onClick={onDelete} icon={<Trash2 className="w-4 h-4" aria-hidden/>}>
              Delete
            </DangerButton>
          </>}>
        <p className="text-sm text-[#cfd8dc]">
          This will remove <span className="font-medium">{confirmDelete?.label}</span> from the
          catalog. Existing sessions keep running; new sessions won't see it.
        </p>
      </Modal>
    </Panel>);
}
// ────────────────────────────────────────────────────────────────
// Table
// ────────────────────────────────────────────────────────────────
function ActionTable({ items, onDelete, }) {
    return (<div className="overflow-x-auto -mx-5 px-5">
      <table className="w-full min-w-[720px] text-sm">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wide text-[#777] border-b border-[#3f3f3f]">
            <th className="py-2 pr-3 font-medium">Label</th>
            <th className="py-2 pr-3 font-medium">Intent</th>
            <th className="py-2 pr-3 font-medium">Level gate</th>
            <th className="py-2 pr-3 font-medium">Scheme</th>
            <th className="py-2 pr-3 font-medium text-right">XP</th>
            <th className="py-2 pr-3 font-medium text-right">Cooldown</th>
            <th className="py-2 pl-3 font-medium text-right">&nbsp;</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[#2a2a2a]">
          {items.map((a) => (<tr key={a.id} className="hover:bg-[#121212]">
              <td className="py-2.5 pr-3 text-[#f1f1f1] font-medium">{a.label}</td>
              <td className="py-2.5 pr-3 text-[#cfd8dc]">
                {a.intent_code
                ? <code className="text-xs bg-[#121212] border border-[#3f3f3f] rounded px-1.5 py-0.5">{a.intent_code}</code>
                : <span className="text-[#777]">—</span>}
              </td>
              <td className="py-2.5 pr-3 text-[#cfd8dc]">
                {a.required_level ?? 1}
                <span className="text-[#777] text-xs"> / {a.required_metric_key || "level"}</span>
              </td>
              <td className="py-2.5 pr-3 text-[#cfd8dc]">{a.required_scheme || "xp_level"}</td>
              <td className="py-2.5 pr-3 text-[#cfd8dc] text-right">
                {a.xp_award ? <span>+{a.xp_award}</span> : <span className="text-[#777]">0</span>}
              </td>
              <td className="py-2.5 pr-3 text-[#cfd8dc] text-right">
                {a.cooldown_sec ? `${a.cooldown_sec}s` : <span className="text-[#777]">—</span>}
              </td>
              <td className="py-2.5 pl-3 text-right">
                <button type="button" onClick={() => onDelete(a)} aria-label={`Delete ${a.label}`} className="text-[#aaa] hover:text-red-400 p-1 rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500">
                  <Trash2 className="w-4 h-4" aria-hidden/>
                </button>
              </td>
            </tr>))}
        </tbody>
      </table>
    </div>);
}
// ────────────────────────────────────────────────────────────────
// New-action modal
// ────────────────────────────────────────────────────────────────
function NewActionModal({ open, onClose, api, projectId, onCreated, }) {
    const toast = useToast();
    const [label, setLabel] = useState("");
    const [intentCode, setIntentCode] = useState("");
    const [requiredLevel, setRequiredLevel] = useState(1);
    const [scheme, setScheme] = useState("xp_level");
    const [xpAward, setXpAward] = useState(0);
    const [cooldown, setCooldown] = useState(0);
    const [submitting, setSubmitting] = useState(false);
    const reset = useCallback(() => {
        setLabel("");
        setIntentCode("");
        setRequiredLevel(1);
        setScheme("xp_level");
        setXpAward(0);
        setCooldown(0);
    }, []);
    const canSubmit = label.trim().length > 0 && !submitting;
    const submit = useCallback(async () => {
        if (!canSubmit)
            return;
        setSubmitting(true);
        try {
            const created = await api.createAction(projectId, {
                label: label.trim(),
                intent_code: intentCode.trim(),
                required_level: requiredLevel,
                required_scheme: scheme,
                required_metric_key: scheme === "xp_level" ? "level" : "",
                xp_award: xpAward,
                cooldown_sec: cooldown,
            });
            reset();
            onCreated(created);
        }
        catch (err) {
            const e = err;
            toast.toast({
                variant: "error",
                title: "Couldn't create action",
                message: e.message || "Check the inputs and try again.",
            });
            setSubmitting(false);
        }
    }, [api, canSubmit, cooldown, intentCode, label, onCreated, projectId, requiredLevel, reset, scheme, toast, xpAward]);
    return (<Modal open={open} onClose={() => { if (!submitting) {
        reset();
        onClose();
    } }} title="New action" widthClass="max-w-xl" footer={<>
          <SecondaryButton onClick={() => { reset(); onClose(); }} disabled={submitting}>
            Cancel
          </SecondaryButton>
          <PrimaryButton onClick={submit} disabled={!canSubmit} loading={submitting}>
            Create
          </PrimaryButton>
        </>}>
      <div className="flex flex-col gap-4">
        <FormField label="Label" required>
          <input type="text" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. Greet the host" maxLength={80} className="w-full bg-[#121212] border border-[#3f3f3f] rounded-md px-3 py-2 text-sm outline-none focus:border-[#3ea6ff]"/>
        </FormField>
        <FormField label="Intent code" hint="Free-form string used to route to edges; e.g. 'greeting', 'flirt'.">
          <input type="text" value={intentCode} onChange={(e) => setIntentCode(e.target.value)} placeholder="(optional)" maxLength={40} className="w-full bg-[#121212] border border-[#3f3f3f] rounded-md px-3 py-2 text-sm outline-none focus:border-[#3ea6ff]"/>
        </FormField>
        <div className="grid grid-cols-2 gap-3">
          <FormField label="Required level">
            <input type="number" min={1} max={50} value={requiredLevel} onChange={(e) => setRequiredLevel(Math.max(1, parseInt(e.target.value, 10) || 1))} className="w-full bg-[#121212] border border-[#3f3f3f] rounded-md px-3 py-2 text-sm outline-none focus:border-[#3ea6ff]"/>
          </FormField>
          <FormField label="Progression scheme">
            <select value={scheme} onChange={(e) => setScheme(e.target.value)} className="w-full bg-[#121212] border border-[#3f3f3f] rounded-md px-3 py-2 text-sm outline-none focus:border-[#3ea6ff]">
              {SCHEMES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </FormField>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <FormField label="XP award" hint="XP granted when this action is taken (xp_level scheme).">
            <input type="number" min={0} max={500} value={xpAward} onChange={(e) => setXpAward(Math.max(0, parseInt(e.target.value, 10) || 0))} className="w-full bg-[#121212] border border-[#3f3f3f] rounded-md px-3 py-2 text-sm outline-none focus:border-[#3ea6ff]"/>
          </FormField>
          <FormField label="Cooldown (seconds)" hint="Per-session cooldown between repeat uses.">
            <input type="number" min={0} max={3600} value={cooldown} onChange={(e) => setCooldown(Math.max(0, parseInt(e.target.value, 10) || 0))} className="w-full bg-[#121212] border border-[#3f3f3f] rounded-md px-3 py-2 text-sm outline-none focus:border-[#3ea6ff]"/>
          </FormField>
        </div>
      </div>
    </Modal>);
}
function FormField({ label, hint, required, children, }) {
    return (<div className="flex flex-col gap-1">
      <label className="text-xs font-medium text-[#cfd8dc]">
        {label}
        {required && <span className="text-[#3ea6ff] ml-0.5" aria-label="required">*</span>}
      </label>
      {hint && <p className="text-[11px] text-[#777] -mt-0.5">{hint}</p>}
      {children}
    </div>);
}
