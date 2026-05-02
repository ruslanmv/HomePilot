/**
 * McpSetupWizard — guided step-by-step drawer to configure an MCP server
 * after it has been added from the Discover catalog.
 *
 * Auth type handling:
 *   Open         → already works, no wizard needed
 *   API Key/API  → step-through instructions, then credential input, then POST register
 *   OAuth2.1     → info-only: explains that OAuth is handled by the server itself
 *   OAuth        → info-only: same as OAuth2.1
 *   OAuth2.1+Key → credential input (uses API key path)
 *
 * The wizard never opens a fake /oauth/authorize endpoint — OAuth servers
 * handle their own auth when an MCP client connects to the server URL.
 *
 * Phase 10 — fully additive, does not modify any existing component.
 */
import React, { useState } from 'react';
import { X, ArrowRight, ArrowLeft, Check, ExternalLink, Eye, EyeOff, Loader2, Shield, Key, Lock, Globe, Zap, AlertCircle, CheckCircle, Copy, } from 'lucide-react';
import { getSetupGuide, needsCredentialInput, needsOAuthFlow, isOpenAuth, } from './setupInstructions';
function authIcon(authType) {
    if (isOpenAuth(authType))
        return Globe;
    if (needsOAuthFlow(authType))
        return Lock;
    return Key;
}
// ── Step indicator ──────────────────────────────────────────────────────
function StepIndicator({ current, total }) {
    return (<div className="flex items-center gap-2">
      {Array.from({ length: total }, (_, i) => (<div key={i} className={`h-1.5 rounded-full transition-all duration-300 ${i < current
                ? 'w-6 bg-purple-400'
                : i === current
                    ? 'w-6 bg-purple-400/60'
                    : 'w-3 bg-white/15'}`}/>))}
      <span className="text-[11px] text-white/30 ml-1">
        {current + 1} of {total}
      </span>
    </div>);
}
// ── Main wizard ─────────────────────────────────────────────────────────
export function McpSetupWizard({ server, backendUrl, apiKey: appApiKey, onClose, onComplete }) {
    const guide = getSetupGuide(server.id, server.auth_type);
    const requiresCred = needsCredentialInput(server.auth_type);
    const requiresOAuth = needsOAuthFlow(server.auth_type);
    const isOpen = isOpenAuth(server.auth_type);
    const [step, setStep] = useState(0);
    const [state, setState] = useState('instructions');
    const [credential, setCredential] = useState('');
    const [showCredential, setShowCredential] = useState(false);
    const [error, setError] = useState(null);
    const [toolCount, setToolCount] = useState(null);
    const [copiedUrl, setCopiedUrl] = useState(false);
    const AuthIcon = authIcon(server.auth_type);
    // ── Submit credential (API Key / API / OAuth2.1 & API Key) ─────────
    const handleSubmitCredential = async () => {
        if (!credential.trim())
            return;
        setState('connecting');
        setError(null);
        try {
            const headers = { 'Content-Type': 'application/json' };
            if (appApiKey)
                headers['x-api-key'] = appApiKey;
            const res = await fetch(`${backendUrl}/v1/agentic/registry/${encodeURIComponent(server.id)}/register`, {
                method: 'POST',
                headers,
                body: JSON.stringify({ api_key: credential.trim() }),
            });
            const json = await res.json().catch(() => ({}));
            if (!res.ok) {
                throw new Error(json.detail || json.message || `HTTP ${res.status}`);
            }
            const toolMatch = json.message?.match(/(\d+)\s*tool/);
            if (toolMatch)
                setToolCount(parseInt(toolMatch[1], 10));
            setState('success');
        }
        catch (e) {
            setError(e?.message || 'Connection failed');
            setState('error');
        }
    };
    // ── Copy server URL ─────────────────────────────────────────────────
    const copyServerUrl = () => {
        navigator.clipboard.writeText(server.url).catch(() => { });
        setCopiedUrl(true);
        setTimeout(() => setCopiedUrl(false), 2000);
    };
    // ── Render: instruction step ───────────────────────────────────────
    const renderInstructionStep = () => {
        const guideStep = guide.steps[step];
        if (!guideStep)
            return null;
        return (<div className="space-y-6">
        {/* Step card */}
        <div className="rounded-xl bg-white/5 border border-white/10 p-5 space-y-3">
          <div className="flex items-start gap-3">
            <div className="w-8 h-8 rounded-lg bg-purple-500/20 flex items-center justify-center shrink-0">
              <span className="text-sm font-bold text-purple-300">{step + 1}</span>
            </div>
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-white">{guideStep.title}</h3>
              <p className="text-sm text-white/60 mt-1 leading-relaxed">{guideStep.description}</p>
            </div>
          </div>
          {guideStep.link && (<a href={guideStep.link.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 text-sm font-medium text-purple-300 hover:text-purple-200 transition-colors mt-2">
              <ExternalLink size={14}/>
              {guideStep.link.label}
            </a>)}
        </div>

        {/* All steps overview (mini) */}
        <div className="space-y-2">
          {guide.steps.map((s, i) => (<div key={i} className={`flex items-center gap-3 px-3 py-2 rounded-lg transition-colors ${i === step ? 'bg-white/5' : ''}`}>
              <div className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold ${i < step
                    ? 'bg-emerald-500/30 text-emerald-300'
                    : i === step
                        ? 'bg-purple-500/30 text-purple-300'
                        : 'bg-white/10 text-white/30'}`}>
                {i < step ? <Check size={10}/> : i + 1}
              </div>
              <span className={`text-xs ${i === step ? 'text-white/80 font-medium' : i < step ? 'text-white/50' : 'text-white/30'}`}>
                {s.title}
              </span>
            </div>))}
        </div>
      </div>);
    };
    // ── Render: credential input ───────────────────────────────────────
    const renderCredentialInput = () => (<div className="space-y-5">
      <div className="rounded-xl bg-white/5 border border-white/10 p-5 space-y-4">
        <div className="flex items-center gap-2">
          <Key size={16} className="text-cyan-400"/>
          <h3 className="text-sm font-semibold text-white">
            {guide.credentialLabel || 'API Key'}
          </h3>
        </div>

        <div className="relative">
          <input type={showCredential ? 'text' : 'password'} value={credential} onChange={(e) => setCredential(e.target.value)} placeholder={guide.credentialPlaceholder || 'Paste your key here...'} className="w-full bg-black/30 border border-white/10 rounded-xl px-4 py-3 pr-10 text-sm text-white placeholder-white/25 focus:outline-none focus:border-cyan-500/50 transition-colors font-mono" autoFocus onKeyDown={(e) => {
            if (e.key === 'Enter' && credential.trim())
                handleSubmitCredential();
        }}/>
          <button type="button" onClick={() => setShowCredential(!showCredential)} className="absolute right-3 top-1/2 -translate-y-1/2 text-white/30 hover:text-white/60 transition-colors">
            {showCredential ? <EyeOff size={16}/> : <Eye size={16}/>}
          </button>
        </div>

        {guide.credentialHint && (<div className="flex items-start gap-2">
            <Shield size={12} className="text-white/30 mt-0.5 shrink-0"/>
            <p className="text-[11px] text-white/40 leading-relaxed">{guide.credentialHint}</p>
          </div>)}
      </div>
    </div>);
    // ── Render: OAuth info (no fake redirect) ──────────────────────────
    const renderOAuthInfo = () => (<div className="space-y-5">
      {/* Current step info */}
      {renderInstructionStep()}

      {/* Server URL section */}
      <div className="rounded-xl bg-amber-500/5 border border-amber-500/20 p-5 space-y-4">
        <div className="flex items-center gap-2">
          <Lock size={16} className="text-amber-400"/>
          <h3 className="text-sm font-semibold text-white">Server Endpoint</h3>
        </div>
        <p className="text-xs text-white/50 leading-relaxed">
          This server uses {server.auth_type} authentication. The OAuth flow is handled
          directly by the server when your MCP client connects. Copy the URL below and
          configure it in your MCP client.
        </p>

        {/* Copyable URL */}
        <div className="flex items-center gap-2">
          <code className="flex-1 text-xs text-amber-200/80 bg-black/30 border border-white/10 rounded-lg px-3 py-2.5 font-mono break-all">
            {server.url}
          </code>
          <button onClick={copyServerUrl} className="shrink-0 p-2 text-white/40 hover:text-white/70 bg-white/5 hover:bg-white/10 rounded-lg transition-colors" title="Copy URL">
            {copiedUrl ? <Check size={14} className="text-emerald-400"/> : <Copy size={14}/>}
          </button>
        </div>

        {/* Open in browser */}
        <a href={server.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 text-sm font-medium text-amber-300 hover:text-amber-200 transition-colors">
          <ExternalLink size={14}/>
          Open server endpoint
        </a>
      </div>

      {/* Provider link */}
      <div className="rounded-xl bg-white/5 border border-white/10 p-4">
        <p className="text-xs text-white/40 leading-relaxed">
          The server is registered in your gateway. When an MCP-compatible client connects
          to this endpoint, {server.provider} will prompt you to authorize access.
          You can also visit the provider directly:
        </p>
        <a href={`https://${new URL(server.url).hostname}`} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 text-xs font-medium text-cyan-300 hover:text-cyan-200 transition-colors mt-2">
          <Globe size={12}/>
          {new URL(server.url).hostname}
        </a>
      </div>
    </div>);
    // ── Render: connecting ─────────────────────────────────────────────
    const renderConnecting = () => (<div className="flex flex-col items-center justify-center py-12 space-y-4">
      <div className="w-16 h-16 rounded-2xl bg-purple-500/10 border border-purple-500/20 flex items-center justify-center">
        <Loader2 size={28} className="text-purple-400 animate-spin"/>
      </div>
      <div className="text-center">
        <h3 className="text-sm font-semibold text-white">Connecting to {server.name}</h3>
        <p className="text-xs text-white/40 mt-1">Validating credentials and discovering tools...</p>
      </div>
    </div>);
    // ── Render: success ────────────────────────────────────────────────
    const renderSuccess = () => (<div className="flex flex-col items-center justify-center py-10 space-y-5">
      <div className="w-16 h-16 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center">
        <CheckCircle size={28} className="text-emerald-400"/>
      </div>
      <div className="text-center">
        <h3 className="text-base font-semibold text-white">{server.name} is ready!</h3>
        {toolCount !== null && (<p className="text-sm text-emerald-300 mt-1">
            {toolCount} tool{toolCount !== 1 ? 's' : ''} discovered
          </p>)}
        <p className="text-xs text-white/40 mt-2">
          You can now use {server.name} tools in your conversations.
        </p>
      </div>
      <button onClick={() => { onComplete(); onClose(); }} className="flex items-center gap-2 px-6 py-2.5 bg-emerald-500 hover:bg-emerald-600 text-white text-sm font-medium rounded-xl transition-colors">
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
        <h3 className="text-base font-semibold text-white">Setup Failed</h3>
        <p className="text-sm text-red-300/80 mt-1 max-w-xs">{error}</p>
      </div>
      <div className="flex gap-3">
        <button onClick={() => { setState('instructions'); setStep(0); setError(null); }} className="flex items-center gap-2 px-4 py-2 bg-white/5 hover:bg-white/10 text-white/70 text-sm rounded-xl transition-colors border border-white/10">
          <ArrowLeft size={14}/>
          Go Back
        </button>
        <button onClick={() => { setState(requiresCred ? 'credentials' : 'instructions'); setError(null); }} className="flex items-center gap-2 px-4 py-2 bg-red-500/20 hover:bg-red-500/30 text-red-300 text-sm rounded-xl transition-colors">
          Try Again
        </button>
      </div>
    </div>);
    // ── Navigation logic ───────────────────────────────────────────────
    const handleNext = () => {
        if (requiresCred) {
            if (step < guide.steps.length - 1) {
                setStep(step + 1);
            }
            else {
                setState('credentials');
            }
            return;
        }
        // OAuth: just step through info pages, no submit
        if (step < guide.steps.length - 1) {
            setStep(step + 1);
        }
    };
    const handleBack = () => {
        if (state === 'credentials') {
            setState('instructions');
            return;
        }
        if (step > 0)
            setStep(step - 1);
    };
    // ── Determine current view ─────────────────────────────────────────
    const showInstructions = state === 'instructions';
    const showCredentials = state === 'credentials';
    const showConnecting = state === 'connecting';
    const showSuccess = state === 'success';
    const showError = state === 'error';
    const isLastInstructionStep = step >= guide.steps.length - 1;
    const canGoNext = requiresCred
        ? !isLastInstructionStep || state === 'instructions'
        : !isLastInstructionStep;
    const nextLabel = requiresCred && isLastInstructionStep
        ? 'Enter Credentials'
        : requiresOAuth
            ? (isLastInstructionStep ? null : 'Next')
            : 'Next';
    // Total steps for indicator
    const totalStepsForIndicator = guide.steps.length + (requiresCred ? 1 : 0);
    return (<div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm"/>

      {/* Panel */}
      <div className="relative w-full max-w-md bg-[#0b0b12] border-l border-white/10 h-full overflow-y-auto animate-slide-in-right" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="sticky top-0 bg-[#0b0b12]/95 backdrop-blur border-b border-white/10 px-6 py-4 z-10">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-purple-500/20 to-cyan-500/20 border border-white/10 flex items-center justify-center">
                <Zap size={18} className="text-purple-400"/>
              </div>
              <div>
                <h2 className="text-base font-semibold text-white">Setup {server.name}</h2>
                <div className="flex items-center gap-2 mt-0.5">
                  <AuthIcon size={11} className="text-white/40"/>
                  <span className="text-xs text-white/40">{server.auth_type}</span>
                  <span className="text-white/20">·</span>
                  <span className="text-xs text-white/40">{server.provider}</span>
                </div>
              </div>
            </div>
            <button onClick={onClose} className="p-2 text-white/50 hover:text-white hover:bg-white/10 rounded-xl transition-colors">
              <X size={18}/>
            </button>
          </div>

          {/* Progress (only for credential-based flows) */}
          {(showInstructions || showCredentials) && !requiresOAuth && (<StepIndicator current={showCredentials ? guide.steps.length : step} total={totalStepsForIndicator}/>)}
        </div>

        {/* Body */}
        <div className="px-6 py-6">
          {showInstructions && requiresOAuth && renderOAuthInfo()}
          {showInstructions && !requiresOAuth && renderInstructionStep()}
          {showCredentials && renderCredentialInput()}
          {showConnecting && renderConnecting()}
          {showSuccess && renderSuccess()}
          {showError && renderError()}
        </div>

        {/* Footer navigation */}
        {(showInstructions || showCredentials) && !showSuccess && !showError && (<div className="sticky bottom-0 bg-[#0b0b12]/95 backdrop-blur border-t border-white/10 px-6 py-4 flex items-center justify-between">
            <button onClick={handleBack} disabled={step === 0 && !showCredentials} className="flex items-center gap-1.5 px-3 py-2 text-sm text-white/50 hover:text-white/80 disabled:opacity-30 disabled:cursor-default transition-colors">
              <ArrowLeft size={14}/>
              Back
            </button>

            {showCredentials ? (<button onClick={handleSubmitCredential} disabled={!credential.trim()} className="flex items-center gap-2 px-5 py-2.5 bg-purple-500 hover:bg-purple-600 disabled:bg-white/10 disabled:text-white/30 text-white text-sm font-medium rounded-xl transition-all">
                Connect
                <ArrowRight size={14}/>
              </button>) : requiresOAuth ? (
            /* OAuth: just a Done/Close button */
            <button onClick={onClose} className="flex items-center gap-2 px-5 py-2.5 bg-white/10 hover:bg-white/15 text-white text-sm font-medium rounded-xl transition-all">
                Done
              </button>) : nextLabel ? (<button onClick={handleNext} disabled={!canGoNext} className="flex items-center gap-2 px-5 py-2.5 bg-purple-500 hover:bg-purple-600 disabled:bg-white/10 disabled:text-white/30 text-white text-sm font-medium rounded-xl transition-all">
                {nextLabel}
                <ArrowRight size={14}/>
              </button>) : null}
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
