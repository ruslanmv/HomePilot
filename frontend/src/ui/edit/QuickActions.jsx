/**
 * QuickActions - One-click enhancement buttons for the Edit page.
 *
 * Provides quick access to AI enhancement features:
 * - Enhance (RealESRGAN): Improve photo quality
 * - Restore (SwinIR): Remove artifacts and compression
 * - Fix Faces (GFPGAN): Restore and enhance faces
 * - Upscale (UltraSharp): Increase resolution 2x/4x
 *
 * This component is additive and can be dropped into any page.
 */
import React, { useState, useEffect } from 'react';
import { Loader2, Sparkles, Wand2, User, Maximize, Info, AlertTriangle } from 'lucide-react';
import { enhanceImage, ENHANCE_MODES } from '../enhance/enhanceApi';
import { upscaleImage } from '../enhance/upscaleApi';
import { checkCapability } from '../enhance/capabilitiesApi';
/**
 * QuickActions component for one-click image enhancement.
 *
 * @example
 * ```tsx
 * <QuickActions
 *   backendUrl="http://localhost:8000"
 *   imageUrl={currentImage}
 *   onResult={(url, mode) => {
 *     console.log(`Enhanced with ${mode}: ${url}`)
 *     setCurrentImage(url)
 *   }}
 *   onError={(err) => setError(err)}
 * />
 * ```
 */
export function QuickActions({ backendUrl, apiKey, imageUrl, onResult, onError, disabled = false, compact = false, showInfo = false, }) {
    const [loading, setLoading] = useState(null);
    const [upscaleLoading, setUpscaleLoading] = useState(false);
    const [upscaleScale, setUpscaleScale] = useState(2);
    const [showInfoTip, setShowInfoTip] = useState(null);
    // Capability check for Fix Faces — avoids blind 503 errors
    const [facesAvailable, setFacesAvailable] = useState(null); // null = checking
    const [facesReason, setFacesReason] = useState(null);
    const [showFacesSetup, setShowFacesSetup] = useState(false);
    useEffect(() => {
        let cancelled = false;
        checkCapability(backendUrl, 'enhance_faces', apiKey)
            .then((cap) => {
            if (cancelled)
                return;
            setFacesAvailable(cap.available);
            if (!cap.available)
                setFacesReason(cap.reason ?? 'Face restoration nodes not installed in ComfyUI');
        })
            .catch(() => {
            if (!cancelled)
                setFacesAvailable(null); // unknown — let user try
        });
        return () => { cancelled = true; };
    }, [backendUrl, apiKey]);
    const handleEnhance = async (mode) => {
        if (!imageUrl || loading || disabled)
            return;
        // If Fix Faces is unavailable, show setup instructions instead of hitting 503
        if (mode === 'faces' && facesAvailable === false) {
            setShowFacesSetup(true);
            return;
        }
        setLoading(mode);
        try {
            const result = await enhanceImage({
                backendUrl,
                apiKey,
                imageUrl,
                mode,
                scale: mode === 'faces' ? 1 : 2, // Faces doesn't need upscaling
            });
            const enhancedUrl = result?.media?.images?.[0];
            if (enhancedUrl) {
                onResult(enhancedUrl, mode);
            }
            else {
                onError('Enhancement completed but no image was returned.');
            }
        }
        catch (e) {
            onError(e instanceof Error ? e.message : 'Enhancement failed');
        }
        finally {
            setLoading(null);
        }
    };
    const handleUpscale = async () => {
        if (!imageUrl || upscaleLoading || loading || disabled)
            return;
        setUpscaleLoading(true);
        try {
            const result = await upscaleImage({
                backendUrl,
                apiKey,
                imageUrl,
                scale: upscaleScale,
                model: '4x-UltraSharp.pth',
            });
            const upscaledUrl = result?.media?.images?.[0];
            if (upscaledUrl) {
                onResult(upscaledUrl, 'upscale');
            }
            else {
                onError('Upscale completed but no image was returned.');
            }
        }
        catch (e) {
            onError(e instanceof Error ? e.message : 'Upscale failed');
        }
        finally {
            setUpscaleLoading(false);
        }
    };
    const getIcon = (mode) => {
        switch (mode) {
            case 'photo':
                return <Sparkles size={compact ? 14 : 16}/>;
            case 'restore':
                return <Wand2 size={compact ? 14 : 16}/>;
            case 'faces':
                return <User size={compact ? 14 : 16}/>;
        }
    };
    const isDisabled = !imageUrl || disabled;
    const anyLoading = loading !== null || upscaleLoading;
    if (compact) {
        return (<div className="flex gap-1.5">
        {ENHANCE_MODES.map((modeInfo) => (<button key={modeInfo.id} onClick={() => handleEnhance(modeInfo.id)} disabled={isDisabled || anyLoading} title={`${modeInfo.label}: ${modeInfo.description}`} className={`
              p-2 rounded-lg transition-all
              ${loading === modeInfo.id
                    ? 'bg-purple-500/60 text-white animate-pulse'
                    : isDisabled || anyLoading
                        ? 'bg-white/5 text-white/30 cursor-not-allowed'
                        : 'bg-white/10 text-white/70 hover:bg-purple-500/30 hover:text-purple-300'}
            `}>
            {loading === modeInfo.id ? (<Loader2 size={14} className="animate-spin"/>) : (getIcon(modeInfo.id))}
          </button>))}
        {/* Compact upscale button */}
        <button onClick={handleUpscale} disabled={isDisabled || anyLoading} title={`Upscale ${upscaleScale}×: Increase resolution`} className={`
            p-2 rounded-lg transition-all
            ${upscaleLoading
                ? 'bg-blue-500/60 text-white animate-pulse'
                : isDisabled || anyLoading
                    ? 'bg-white/5 text-white/30 cursor-not-allowed'
                    : 'bg-white/10 text-white/70 hover:bg-blue-500/30 hover:text-blue-300'}
          `}>
          {upscaleLoading ? (<Loader2 size={14} className="animate-spin"/>) : (<Maximize size={14}/>)}
        </button>
      </div>);
    }
    // Technical info for each action
    const actionInfo = {
        photo: { endpoint: '/v1/enhance', model: 'RealESRGAN_x4plus', type: '1-click' },
        restore: { endpoint: '/v1/enhance', model: 'SwinIR', type: '1-click' },
        faces: { endpoint: '/v1/enhance', model: 'GFPGAN (ComfyUI)', type: '1-click' },
        upscale: { endpoint: '/v1/upscale', model: '4x-UltraSharp', type: '1-click' },
    };
    return (<div className="space-y-3">
      <div className="text-xs uppercase tracking-wider text-white/40 font-semibold flex items-center gap-2">
        <Sparkles size={14}/>
        Quick Enhance
      </div>

      <div className="grid grid-cols-1 gap-2">
        {ENHANCE_MODES.map((modeInfo) => (<div key={modeInfo.id} className="relative group/item">
            <button onClick={() => handleEnhance(modeInfo.id)} disabled={isDisabled || anyLoading} className={`
                w-full flex items-center gap-3 p-3 rounded-xl border transition-all text-left
                ${loading === modeInfo.id
                ? 'bg-purple-500/20 border-purple-500/40 text-purple-300'
                : isDisabled || anyLoading
                    ? 'bg-white/5 border-white/5 text-white/30 cursor-not-allowed'
                    : 'bg-white/5 border-white/10 text-white/80 hover:bg-purple-500/10 hover:border-purple-500/30 hover:text-purple-200'}
              `}>
              <div className={`
                w-9 h-9 rounded-lg flex items-center justify-center
                ${loading === modeInfo.id
                ? 'bg-purple-500/30'
                : 'bg-white/10'}
              `}>
                {loading === modeInfo.id ? (<Loader2 size={18} className="animate-spin text-purple-400"/>) : (getIcon(modeInfo.id))}
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium flex items-center gap-2">
                  {modeInfo.label}
                  <span className="text-[9px] px-1.5 py-0.5 rounded bg-white/10 text-white/40">1-click</span>
                </div>
                <div className="text-[10px] text-white/40 truncate flex items-center gap-1.5">
                  {modeInfo.id === 'faces' && facesAvailable === false && (<AlertTriangle size={10} className="text-amber-400/70 flex-shrink-0"/>)}
                  {modeInfo.id === 'faces' && facesAvailable === false
                ? 'Setup required — click for instructions'
                : modeInfo.description}
                </div>
              </div>
            </button>
            {/* Info tooltip */}
            {showInfo && (<div className="absolute right-2 top-1/2 -translate-y-1/2 opacity-0 group-hover/item:opacity-100 transition-opacity">
                <button onClick={(e) => { e.stopPropagation(); setShowInfoTip(showInfoTip === modeInfo.id ? null : modeInfo.id); }} className="p-1 text-white/30 hover:text-white/60">
                  <Info size={12}/>
                </button>
                {showInfoTip === modeInfo.id && (<div className="absolute right-0 top-full mt-1 z-20 w-48 p-2 bg-black/95 border border-white/20 rounded-lg text-[10px] text-white/70 shadow-xl">
                    <div className="font-mono text-purple-400">{actionInfo[modeInfo.id]?.endpoint}</div>
                    <div className="mt-1">Model: {actionInfo[modeInfo.id]?.model}</div>
                  </div>)}
              </div>)}
          </div>))}

        {/* Upscale section with 2x/4x toggle */}
        <div className="relative group/item">
          <div className={`
            flex items-center gap-3 p-3 rounded-xl border transition-all
            ${upscaleLoading
            ? 'bg-blue-500/20 border-blue-500/40'
            : isDisabled || anyLoading
                ? 'bg-white/5 border-white/5'
                : 'bg-white/5 border-white/10 hover:bg-blue-500/10 hover:border-blue-500/30'}
          `}>
            <button onClick={handleUpscale} disabled={isDisabled || anyLoading} className={`
                w-9 h-9 rounded-lg flex items-center justify-center transition-colors
                ${upscaleLoading
            ? 'bg-blue-500/30'
            : 'bg-white/10'}
                ${isDisabled || anyLoading ? 'cursor-not-allowed' : 'cursor-pointer hover:bg-blue-500/20'}
              `}>
              {upscaleLoading ? (<Loader2 size={18} className="animate-spin text-blue-400"/>) : (<Maximize size={16} className={isDisabled || anyLoading ? 'text-white/30' : 'text-white/70'}/>)}
            </button>
            <div className="flex-1 min-w-0">
              <div className={`text-sm font-medium flex items-center gap-2 ${isDisabled || anyLoading ? 'text-white/30' : 'text-white/80'}`}>
                Upscale
                <span className="text-[9px] px-1.5 py-0.5 rounded bg-white/10 text-white/40">1-click</span>
              </div>
              <div className="text-[10px] text-white/40">
                Increase resolution with AI
              </div>
            </div>
            {/* Scale toggle */}
            <div className="flex rounded-lg overflow-hidden border border-white/10">
              <button onClick={() => setUpscaleScale(2)} disabled={isDisabled || anyLoading} className={`px-2 py-1 text-xs font-medium transition-colors ${upscaleScale === 2
            ? 'bg-blue-500 text-white'
            : isDisabled || anyLoading
                ? 'bg-white/5 text-white/30 cursor-not-allowed'
                : 'bg-white/5 text-white/60 hover:bg-white/10'}`}>
                2×
              </button>
              <button onClick={() => setUpscaleScale(4)} disabled={isDisabled || anyLoading} className={`px-2 py-1 text-xs font-medium transition-colors ${upscaleScale === 4
            ? 'bg-blue-500 text-white'
            : isDisabled || anyLoading
                ? 'bg-white/5 text-white/30 cursor-not-allowed'
                : 'bg-white/5 text-white/60 hover:bg-white/10'}`}>
                4×
              </button>
            </div>
          </div>
          {/* Info tooltip for upscale */}
          {showInfo && (<div className="absolute right-14 top-1/2 -translate-y-1/2 opacity-0 group-hover/item:opacity-100 transition-opacity">
              <button onClick={(e) => { e.stopPropagation(); setShowInfoTip(showInfoTip === 'upscale' ? null : 'upscale'); }} className="p-1 text-white/30 hover:text-white/60">
                <Info size={12}/>
              </button>
              {showInfoTip === 'upscale' && (<div className="absolute right-0 top-full mt-1 z-20 w-48 p-2 bg-black/95 border border-white/20 rounded-lg text-[10px] text-white/70 shadow-xl">
                  <div className="font-mono text-blue-400">{actionInfo.upscale.endpoint}</div>
                  <div className="mt-1">Model: {actionInfo.upscale.model}</div>
                </div>)}
            </div>)}
        </div>
      </div>

      <p className="text-[10px] text-white/30 leading-relaxed">
        One-click AI enhancement. Results are added to your version history.
      </p>

      {/* Fix Faces setup guidance modal */}
      {showFacesSetup && (<>
          <div className="fixed inset-0 z-40 bg-black/60" onClick={() => setShowFacesSetup(false)}/>
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={() => setShowFacesSetup(false)}>
            <div className="bg-[#1a1a1f] border border-white/10 rounded-2xl shadow-2xl max-w-md w-full p-6 space-y-4" onClick={(e) => e.stopPropagation()}>
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-amber-500/15 flex items-center justify-center">
                  <AlertTriangle size={20} className="text-amber-400"/>
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-white/90">Fix Faces — Setup Required</h3>
                  <p className="text-[11px] text-white/40">ComfyUI face restoration nodes are not installed</p>
                </div>
              </div>

              <div className="bg-black/40 rounded-xl p-4 space-y-3 font-mono text-[11px] text-white/70 leading-relaxed">
                <div className="text-white/40 text-[10px] uppercase tracking-wider font-sans font-semibold">If Impact-Pack is already installed:</div>
                <div>
                  <span className="text-amber-400/70"># Restart ComfyUI so it registers the new nodes</span><br />
                  <span className="text-white/50">Then click <strong className="text-purple-300">Re-check</strong> below</span>
                </div>
                <div className="border-t border-white/10 pt-3">
                  <div className="text-white/40 text-[10px] uppercase tracking-wider font-sans font-semibold">If not installed yet:</div>
                </div>
                <div>
                  <span className="text-amber-400/70"># 1. Install Impact-Pack custom node</span><br />
                  <span className="text-green-400/80 select-all">cd ComfyUI/custom_nodes</span><br />
                  <span className="text-green-400/80 select-all">git clone https://github.com/ltdrdata/ComfyUI-Impact-Pack.git</span>
                </div>
                <div>
                  <span className="text-amber-400/70"># 2. Install Python deps (in ComfyUI's Python env)</span><br />
                  <span className="text-green-400/80 select-all">pip install ultralytics facexlib gfpgan</span>
                </div>
                <div>
                  <span className="text-amber-400/70"># 3. Restart ComfyUI</span>
                </div>
              </div>

              {facesReason && (<p className="text-[10px] text-white/30 leading-relaxed">{facesReason}</p>)}

              <div className="flex justify-end gap-2 pt-2">
                <button onClick={() => setShowFacesSetup(false)} className="px-4 py-2 rounded-lg text-xs font-medium text-white/50 hover:text-white/70 hover:bg-white/5 transition-all">
                  Close
                </button>
                <button onClick={async () => {
                setFacesAvailable(null); // show "checking" state
                try {
                    // Invalidate backend's node cache first, then re-probe
                    const base = backendUrl.replace(/\/+$/, '');
                    await fetch(`${base}/v1/capabilities/refresh`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            ...(apiKey ? { 'X-API-Key': apiKey } : {}),
                        },
                    });
                }
                catch { /* ignore — re-probe below will still work */ }
                try {
                    const cap = await checkCapability(backendUrl, 'enhance_faces', apiKey);
                    setFacesAvailable(cap.available);
                    if (cap.available) {
                        setShowFacesSetup(false);
                        setFacesReason(null);
                    }
                    else {
                        setFacesReason(cap.reason ?? 'Still not available — restart ComfyUI and try again');
                    }
                }
                catch {
                    setFacesAvailable(null);
                }
            }} className="px-4 py-2 rounded-lg text-xs font-medium bg-purple-500/20 text-purple-300 hover:bg-purple-500/30 border border-purple-500/20 transition-all">
                  {facesAvailable === null ? 'Checking...' : 'Re-check'}
                </button>
              </div>
            </div>
          </div>
        </>)}
    </div>);
}
export default QuickActions;
