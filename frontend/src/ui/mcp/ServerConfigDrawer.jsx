/**
 * ServerConfigDrawer — unified setup wizard for builtin MCP servers
 * that require configuration (OAuth tokens, API keys, etc.).
 *
 * Three-phase flow:
 *   1. Setup Guide — prerequisite steps with external links
 *   2. Credential Form — dynamic fields from backend config schema
 *   3. Connect & Verify — save, restart, health check
 *
 * Works with any `requires_config` type: GOOGLE_OAUTH, SLACK_TOKEN,
 * GITHUB_TOKEN, NOTION_TOKEN, MS_GRAPH_TOKEN, MS_TEAMS_AUTH.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { X, ArrowRight, ArrowLeft, Check, ExternalLink, Eye, EyeOff, Loader2, Key, Shield, AlertCircle, CheckCircle, Settings, ToggleLeft, ToggleRight, ChevronDown, RefreshCw, } from 'lucide-react';
import { getBuiltinSetupGuide } from './builtinSetupGuides';
// ── Step indicator ──────────────────────────────────────────────────────
function StepIndicator({ current, total }) {
    return (<div className="flex items-center gap-2">
      {Array.from({ length: total }, (_, i) => (<div key={i} className={`h-1.5 rounded-full transition-all duration-300 ${i < current
                ? 'w-6 bg-cyan-400'
                : i === current
                    ? 'w-6 bg-cyan-400/60'
                    : 'w-3 bg-white/15'}`}/>))}
      <span className="text-[11px] text-white/30 ml-1">
        {current + 1} / {total}
      </span>
    </div>);
}
// ── Toggle switch ────────────────────────────────────────────────────────
function ToggleSwitch({ checked, onChange }) {
    return (<button type="button" onClick={() => onChange(!checked)} className="flex items-center gap-2 text-white/60 hover:text-white/80 transition-colors">
      {checked ? (<ToggleRight size={24} className="text-cyan-400"/>) : (<ToggleLeft size={24} className="text-white/30"/>)}
      <span className="text-xs">{checked ? 'Enabled' : 'Disabled'}</span>
    </button>);
}
// ── Main drawer ─────────────────────────────────────────────────────────
export function ServerConfigDrawer({ server, backendUrl, apiKey, onClose, onComplete }) {
    const [state, setState] = useState('loading');
    const [guideStep, setGuideStep] = useState(0);
    const [config, setConfig] = useState(null);
    const [fieldValues, setFieldValues] = useState({});
    const [showSecrets, setShowSecrets] = useState({});
    const [error, setError] = useState(null);
    const [validationErrors, setValidationErrors] = useState([]);
    const guide = getBuiltinSetupGuide(server.id);
    const guideSteps = guide?.prerequisiteSteps ?? [];
    const headers = { 'Content-Type': 'application/json' };
    if (apiKey)
        headers['x-api-key'] = apiKey;
    // ── Load config schema from backend ────────────────────────────────
    const loadConfig = useCallback(async () => {
        setState('loading');
        try {
            const res = await fetch(`${backendUrl}/v1/agentic/servers/${encodeURIComponent(server.id)}/config`, { headers: apiKey ? { 'x-api-key': apiKey } : {} });
            if (!res.ok)
                throw new Error(`HTTP ${res.status}`);
            const data = (await res.json());
            setConfig(data);
            // Initialize field values from current config
            const initial = {};
            for (const f of data.fields) {
                // Don't pre-fill masked secrets
                initial[f.key] = f.type === 'secret' && f.value?.includes('••') ? '' : (f.value || f.default || '');
            }
            setFieldValues(initial);
            // If already configured, skip guide and go to credentials
            if (data.configured && guideSteps.length === 0) {
                setState('credentials');
            }
            else {
                setState(guideSteps.length > 0 ? 'guide' : 'credentials');
            }
        }
        catch (e) {
            setError(e?.message || 'Failed to load config');
            setState('error');
        }
    }, [backendUrl, apiKey, server.id, guideSteps.length]);
    useEffect(() => {
        void loadConfig();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    // ── Field value change ─────────────────────────────────────────────
    const setField = (key, value) => {
        setFieldValues((prev) => ({ ...prev, [key]: value }));
        setValidationErrors([]);
    };
    // ── Check if a conditional field should be visible ─────────────────
    const isFieldVisible = (field) => {
        if (!field.condition)
            return true;
        const [condKey, condVal] = field.condition.split('=');
        return fieldValues[condKey] === condVal;
    };
    // ── Validate ───────────────────────────────────────────────────────
    const validateLocally = () => {
        if (!config)
            return false;
        const errors = [];
        for (const f of config.fields) {
            if (!isFieldVisible(f))
                continue;
            if (f.required && !fieldValues[f.key]?.trim()) {
                errors.push(`${f.label} is required`);
            }
        }
        setValidationErrors(errors);
        return errors.length === 0;
    };
    // ── Save & restart ─────────────────────────────────────────────────
    const handleSave = async () => {
        if (!validateLocally())
            return;
        setState('saving');
        setError(null);
        try {
            const res = await fetch(`${backendUrl}/v1/agentic/servers/${encodeURIComponent(server.id)}/config`, {
                method: 'POST',
                headers,
                body: JSON.stringify({ fields: fieldValues }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                throw new Error(data.detail || `HTTP ${res.status}`);
            }
            setState('success');
        }
        catch (e) {
            setError(e?.message || 'Save failed');
            setState('error');
        }
    };
    // ── Navigation ─────────────────────────────────────────────────────
    const handleGuideNext = () => {
        if (guideStep < guideSteps.length - 1) {
            setGuideStep(guideStep + 1);
        }
        else {
            setState('credentials');
        }
    };
    const handleGuideBack = () => {
        if (guideStep > 0) {
            setGuideStep(guideStep - 1);
        }
    };
    const handleBackToCredentials = () => {
        setState('credentials');
        setError(null);
        setValidationErrors([]);
    };
    // ── Total steps for progress indicator ─────────────────────────────
    const totalSteps = guideSteps.length + 1; // guide steps + credential step
    const currentStep = state === 'guide' ? guideStep : guideSteps.length;
    // ── Render: loading ────────────────────────────────────────────────
    const renderLoading = () => (<div className="flex flex-col items-center justify-center py-16 space-y-4">
      <Loader2 size={28} className="text-cyan-400 animate-spin"/>
      <p className="text-sm text-white/40">Loading configuration...</p>
    </div>);
    // ── Render: guide step ─────────────────────────────────────────────
    const renderGuideStep = () => {
        const step = guideSteps[guideStep];
        if (!step)
            return null;
        return (<div className="space-y-6">
        {/* Current step card */}
        <div className="rounded-xl bg-white/5 border border-white/10 p-5 space-y-3">
          <div className="flex items-start gap-3">
            <div className="w-8 h-8 rounded-lg bg-cyan-500/20 flex items-center justify-center shrink-0">
              <span className="text-sm font-bold text-cyan-300">{guideStep + 1}</span>
            </div>
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-white">{step.title}</h3>
              <p className="text-sm text-white/60 mt-1 leading-relaxed">{step.description}</p>
            </div>
          </div>
          {step.link && (<a href={step.link.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 text-sm font-medium text-cyan-300 hover:text-cyan-200 transition-colors mt-2">
              <ExternalLink size={14}/>
              {step.link.label}
            </a>)}
        </div>

        {/* Steps overview */}
        <div className="space-y-2">
          {guideSteps.map((s, i) => (<div key={i} className={`flex items-center gap-3 px-3 py-2 rounded-lg transition-colors ${i === guideStep ? 'bg-white/5' : ''}`}>
              <div className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold ${i < guideStep
                    ? 'bg-emerald-500/30 text-emerald-300'
                    : i === guideStep
                        ? 'bg-cyan-500/30 text-cyan-300'
                        : 'bg-white/10 text-white/30'}`}>
                {i < guideStep ? <Check size={10}/> : i + 1}
              </div>
              <span className={`text-xs ${i === guideStep
                    ? 'text-white/80 font-medium'
                    : i < guideStep
                        ? 'text-white/50'
                        : 'text-white/30'}`}>
                {s.title}
              </span>
            </div>))}
          {/* Show credential step in overview */}
          <div className="flex items-center gap-3 px-3 py-2 rounded-lg">
            <div className="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold bg-white/10 text-white/30">
              {guideSteps.length + 1}
            </div>
            <span className="text-xs text-white/30">Enter credentials</span>
          </div>
        </div>
      </div>);
    };
    // ── Render: credential form ────────────────────────────────────────
    const renderCredentials = () => {
        if (!config)
            return null;
        const visibleFields = config.fields.filter(isFieldVisible);
        return (<div className="space-y-5">
        {/* Header info */}
        {guide && (<div className="rounded-xl bg-cyan-500/5 border border-cyan-500/15 p-4">
            <p className="text-xs text-white/50 leading-relaxed">
              Enter the credentials from the previous steps. Your credentials are stored locally
              in the server's configuration file and are never sent to external services.
            </p>
          </div>)}

        {/* Validation errors */}
        {validationErrors.length > 0 && (<div className="rounded-xl bg-red-500/5 border border-red-500/20 p-4 space-y-1">
            {validationErrors.map((err, i) => (<div key={i} className="flex items-center gap-2 text-xs text-red-300">
                <AlertCircle size={12} className="shrink-0"/>
                {err}
              </div>))}
          </div>)}

        {/* Dynamic fields */}
        {visibleFields.map((field) => (<div key={field.key} className="space-y-2">
            <div className="flex items-center gap-2">
              {field.type === 'secret' ? (<Key size={14} className="text-cyan-400"/>) : field.type === 'toggle' ? (<Shield size={14} className="text-amber-400"/>) : (<Settings size={14} className="text-white/40"/>)}
              <label className="text-sm font-medium text-white">
                {field.label}
                {field.required && <span className="text-red-400 ml-0.5">*</span>}
              </label>
            </div>

            {field.type === 'toggle' ? (<ToggleSwitch checked={fieldValues[field.key] === 'true'} onChange={(v) => setField(field.key, v ? 'true' : 'false')}/>) : field.type === 'select' ? (<div className="relative">
                <select value={fieldValues[field.key] || field.default || ''} onChange={(e) => setField(field.key, e.target.value)} className="w-full bg-black/30 border border-white/10 rounded-xl px-4 py-3 pr-10 text-sm text-white appearance-none focus:outline-none focus:border-cyan-500/50 transition-colors">
                  {(field.options || []).map((opt) => (<option key={opt} value={opt} className="bg-[#0b0b12]">
                      {opt}
                    </option>))}
                </select>
                <ChevronDown size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-white/30 pointer-events-none"/>
              </div>) : (<div className="relative">
                <input type={field.type === 'secret' && !showSecrets[field.key] ? 'password' : 'text'} value={fieldValues[field.key] || ''} onChange={(e) => setField(field.key, e.target.value)} placeholder={field.placeholder || ''} className="w-full bg-black/30 border border-white/10 rounded-xl px-4 py-3 pr-10 text-sm text-white placeholder-white/25 focus:outline-none focus:border-cyan-500/50 transition-colors font-mono"/>
                {field.type === 'secret' && (<button type="button" onClick={() => setShowSecrets((prev) => ({
                            ...prev,
                            [field.key]: !prev[field.key],
                        }))} className="absolute right-3 top-1/2 -translate-y-1/2 text-white/30 hover:text-white/60 transition-colors">
                    {showSecrets[field.key] ? <EyeOff size={16}/> : <Eye size={16}/>}
                  </button>)}
              </div>)}

            {field.hint && (<p className="text-[11px] text-white/35 leading-relaxed pl-1">{field.hint}</p>)}
          </div>))}
      </div>);
    };
    // ── Render: saving ─────────────────────────────────────────────────
    const renderSaving = () => (<div className="flex flex-col items-center justify-center py-12 space-y-4">
      <div className="w-16 h-16 rounded-2xl bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center">
        <Loader2 size={28} className="text-cyan-400 animate-spin"/>
      </div>
      <div className="text-center">
        <h3 className="text-sm font-semibold text-white">Configuring {server.label}</h3>
        <p className="text-xs text-white/40 mt-1">Saving credentials and restarting server...</p>
      </div>
    </div>);
    // ── Render: success ────────────────────────────────────────────────
    const renderSuccess = () => (<div className="flex flex-col items-center justify-center py-10 space-y-5">
      <div className="w-16 h-16 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center">
        <CheckCircle size={28} className="text-emerald-400"/>
      </div>
      <div className="text-center">
        <h3 className="text-base font-semibold text-white">{server.label} configured!</h3>
        <p className="text-xs text-white/40 mt-2">
          Credentials saved. {server.installed ? 'The server has been restarted with the new configuration.' : 'Click "Install" to start the server.'}
        </p>
      </div>
      <button onClick={() => {
            onComplete();
            onClose();
        }} className="flex items-center gap-2 px-6 py-2.5 bg-emerald-500 hover:bg-emerald-600 text-white text-sm font-medium rounded-xl transition-colors">
        <Check size={16}/>
        Done
      </button>
    </div>);
    // ── Render: error ──────────────────────────────────────────────────
    const renderError = () => (<div className="flex flex-col items-center justify-center py-10 space-y-5">
      <div className="w-16 h-16 rounded-2xl bg-red-500/10 border border-red-500/20 flex items-center justify-center">
        <AlertCircle size={28} className="text-red-400"/>
      </div>
      <div className="text-center">
        <h3 className="text-base font-semibold text-white">Configuration Failed</h3>
        <p className="text-sm text-red-300/80 mt-1 max-w-xs">{error}</p>
      </div>
      <div className="flex gap-3">
        <button onClick={handleBackToCredentials} className="flex items-center gap-2 px-4 py-2 bg-white/5 hover:bg-white/10 text-white/70 text-sm rounded-xl transition-colors border border-white/10">
          <ArrowLeft size={14}/>
          Go Back
        </button>
        <button onClick={handleSave} className="flex items-center gap-2 px-4 py-2 bg-red-500/20 hover:bg-red-500/30 text-red-300 text-sm rounded-xl transition-colors">
          <RefreshCw size={14}/>
          Try Again
        </button>
      </div>
    </div>);
    // ── Main render ────────────────────────────────────────────────────
    const showGuide = state === 'guide';
    const showCredentials = state === 'credentials';
    const showFooter = showGuide || showCredentials;
    return (<div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm"/>

      {/* Panel */}
      <div className="relative w-full max-w-md bg-[#0b0b12] border-l border-white/10 h-full overflow-y-auto animate-slide-in-right" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="sticky top-0 bg-[#0b0b12]/95 backdrop-blur border-b border-white/10 px-6 py-4 z-10">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-500/20 to-blue-500/20 border border-white/10 flex items-center justify-center">
                <Settings size={18} className="text-cyan-400"/>
              </div>
              <div>
                <h2 className="text-base font-semibold text-white">
                  {guide?.title || `Configure ${server.label}`}
                </h2>
                {guide?.subtitle && (<p className="text-xs text-white/40 mt-0.5">{guide.subtitle}</p>)}
                {!guide && config?.requires_config && (<p className="text-xs text-white/40 mt-0.5">
                    Requires: {config.requires_config}
                  </p>)}
              </div>
            </div>
            <button onClick={onClose} className="p-2 text-white/50 hover:text-white hover:bg-white/10 rounded-xl transition-colors">
              <X size={18}/>
            </button>
          </div>

          {/* Progress indicator */}
          {showFooter && totalSteps > 1 && (<StepIndicator current={currentStep} total={totalSteps}/>)}
        </div>

        {/* Body */}
        <div className="px-6 py-6">
          {state === 'loading' && renderLoading()}
          {showGuide && renderGuideStep()}
          {showCredentials && renderCredentials()}
          {state === 'saving' && renderSaving()}
          {state === 'success' && renderSuccess()}
          {state === 'error' && renderError()}
        </div>

        {/* Footer navigation */}
        {showFooter && (<div className="sticky bottom-0 bg-[#0b0b12]/95 backdrop-blur border-t border-white/10 px-6 py-4 flex items-center justify-between">
            <button onClick={showGuide ? handleGuideBack : () => { if (guideSteps.length > 0) {
            setState('guide');
            setGuideStep(guideSteps.length - 1);
        } }} disabled={showGuide && guideStep === 0} className="flex items-center gap-1.5 px-3 py-2 text-sm text-white/50 hover:text-white/80 disabled:opacity-30 disabled:cursor-default transition-colors">
              <ArrowLeft size={14}/>
              Back
            </button>

            {showGuide ? (<button onClick={handleGuideNext} className="flex items-center gap-2 px-5 py-2.5 bg-cyan-500 hover:bg-cyan-600 text-white text-sm font-medium rounded-xl transition-all">
                {guideStep < guideSteps.length - 1 ? 'Next' : 'Enter Credentials'}
                <ArrowRight size={14}/>
              </button>) : (<button onClick={handleSave} className="flex items-center gap-2 px-5 py-2.5 bg-cyan-500 hover:bg-cyan-600 text-white text-sm font-medium rounded-xl transition-all">
                Save & Connect
                <ArrowRight size={14}/>
              </button>)}
          </div>)}
      </div>

      <style>{`
        @keyframes slide-in-right {
          from { transform: translateX(100%); }
          to { transform: translateX(0); }
        }
        .animate-slide-in-right {
          animation: slide-in-right 0.2s ease-out;
        }
      `}</style>
    </div>);
}
