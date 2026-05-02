import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { buildAnglePrompt, buildIdentityLockSuffix, buildVisualDescriptorsFromMeta, compressOutfitForAngle, extractVisualDescriptors, getGarmentEmphasis, getViewAngleOption, resolveAngleTuning, sanitiseBasePromptForAngle, stripDescriptorDuplicates, VIEW_ANGLE_OPTIONS } from './viewPack';
// ---------------------------------------------------------------------------
// localStorage cache helpers
// ---------------------------------------------------------------------------
const CACHE_PREFIX = 'hp_viewpack_';
function cacheKeyFor(key) {
    return `${CACHE_PREFIX}${key}`;
}
function loadCached(key) {
    if (!key)
        return { results: {}, timestamps: {} };
    try {
        const raw = localStorage.getItem(cacheKeyFor(key));
        if (raw) {
            const parsed = JSON.parse(raw);
            // Support old format (plain ViewResultMap) and new format (CachedViewPack)
            if (parsed && typeof parsed === 'object' && 'results' in parsed) {
                return parsed;
            }
            // Legacy: plain ViewResultMap without timestamps
            return { results: parsed, timestamps: {} };
        }
    }
    catch { /* corrupt entry — ignore */ }
    return { results: {}, timestamps: {} };
}
function saveCached(key, results, timestamps) {
    if (!key)
        return;
    try {
        const hasEntries = Object.keys(results).length > 0;
        if (hasEntries) {
            const data = { results, timestamps };
            localStorage.setItem(cacheKeyFor(key), JSON.stringify(data));
        }
        else {
            localStorage.removeItem(cacheKeyFor(key));
        }
    }
    catch { /* storage full — silently fail */ }
}
function removeCached(key) {
    if (!key)
        return;
    try {
        localStorage.removeItem(cacheKeyFor(key));
    }
    catch { /* ignore */ }
}
// ---------------------------------------------------------------------------
// Backend helpers — commit & delete durable view-pack images
// ---------------------------------------------------------------------------
/** Commit a /comfy/view/ image to durable /files/ storage, optionally deleting the old one. */
async function commitViewImage(base, headers, comfyUrl, oldUrl) {
    try {
        const res = await fetch(`${base}/v1/viewpack/commit`, {
            method: 'POST',
            headers,
            body: JSON.stringify({ comfy_url: comfyUrl, old_url: oldUrl }),
        });
        if (res.ok) {
            const data = await res.json();
            if (data.ok && data.url)
                return data.url;
        }
    }
    catch { /* commit failed — fall back to ephemeral URL */ }
    return comfyUrl;
}
/** Ask backend to delete one or more durable view-pack images. Fire-and-forget. */
function deleteViewImages(base, headers, urls) {
    // Only send /files/ URLs — /comfy/view/ URLs are ephemeral and managed by ComfyUI
    const durable = urls.filter((u) => u.startsWith('/files/'));
    if (durable.length === 0)
        return;
    fetch(`${base}/v1/viewpack/delete`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ urls: durable }),
    }).catch(() => { });
}
// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------
/**
 * @param backendUrl  Backend base URL
 * @param apiKey      Optional API key
 * @param cacheKey    Unique key for localStorage persistence (e.g. characterId
 *                    or characterId+outfitId). When this changes the hook
 *                    loads the cached results for the new key.
 */
export function useViewPackGeneration(backendUrl, apiKey, cacheKey) {
    const [resultsByAngle, setResultsByAngle] = useState(() => loadCached(cacheKey).results);
    const [timestampsByAngle, setTimestampsByAngle] = useState(() => loadCached(cacheKey).timestamps);
    const [loadingAngles, setLoadingAngles] = useState({});
    const [warnings, setWarnings] = useState([]);
    const [error, setError] = useState(null);
    // Stable reference to current results for use inside callbacks
    const resultsRef = useRef(resultsByAngle);
    resultsRef.current = resultsByAngle;
    // Track previous cacheKey so we can save before switching.
    // Uses React's "adjusting state from props" pattern: when cacheKey changes
    // we synchronously swap the cached data during render so there is never a
    // stale-data frame where angle thumbnails from the OLD source are shown
    // alongside the NEW source's front image.
    const [prevKey, setPrevKey] = useState(cacheKey);
    const timestampsRef = useRef(timestampsByAngle);
    timestampsRef.current = timestampsByAngle;
    if (prevKey !== cacheKey) {
        // Save current in-memory results under the *previous* key
        saveCached(prevKey, resultsByAngle, timestampsRef.current);
        // Load the new key's cached data synchronously
        const loaded = loadCached(cacheKey);
        setPrevKey(cacheKey);
        setResultsByAngle(loaded.results);
        setTimestampsByAngle(loaded.timestamps);
        setLoadingAngles({});
        setWarnings([]);
        setError(null);
    }
    // Auto-persist whenever results change
    useEffect(() => {
        saveCached(cacheKey, resultsByAngle, timestampsByAngle);
    }, [cacheKey, resultsByAngle, timestampsByAngle]);
    const anyLoading = useMemo(() => Object.values(loadingAngles).some(Boolean), [loadingAngles]);
    /** Build common fetch headers. */
    const makeHeaders = useCallback(() => {
        const h = { 'Content-Type': 'application/json' };
        if (apiKey)
            h['x-api-key'] = apiKey;
        return h;
    }, [apiKey]);
    const generateAngle = useCallback(async (params) => {
        const base = (backendUrl || '').replace(/\/+$/, '');
        const headers = makeHeaders();
        const angleMeta = getViewAngleOption(params.angle);
        const rawBase = params.basePrompt?.trim() || 'portrait photograph';
        // Strip pose / camera / framing tokens that would contradict the angle
        // directive.  For 'front' this is a no-op (returns rawBase unchanged).
        // Keeps only outfit, appearance, and quality tokens so the clothing is
        // faithfully reproduced at every angle without front-bias contamination.
        const basePrompt = sanitiseBasePromptForAngle(rawBase, params.angle);
        // Build the positive prompt: angle-specific direction FIRST (highest weight),
        // then outfit description, then consistency suffix.
        // Angle directive is placed first so CLIP gives it the most attention weight.
        // The outfit description comes second — it's NOT duplicated via character_prompt
        // (we send character_prompt=undefined) to avoid tripling outfit tokens which
        // drowns out the angle instruction.
        //
        // The angle prompt and identity-lock suffix adapt to the front view's
        // framing type (half_body / mid_body / headshot) so the body range
        // matches across all angles — e.g. "head to waist" instead of
        // hardcoded "head to thighs".
        // Resolve per-angle tuning (denoise, promptWeight) from user settings or defaults
        const tunableAngle = params.angle !== 'front' ? params.angle : null;
        const angleTuning = tunableAngle ? resolveAngleTuning(tunableAngle, params.avatarSettings) : null;
        // Prefer structured appearance data from wizardMeta (exact values, no guessing).
        // Fall back to regex extraction from the prompt for legacy items without meta.
        const metaDescriptors = buildVisualDescriptorsFromMeta(params.wizardMeta);
        const visualDescriptors = metaDescriptors || extractVisualDescriptors(rawBase);
        // Strip tokens from the base prompt that are already covered by the visual
        // descriptors (e.g. "brown hair", "light skin tone") plus non-visual boilerplate
        // (e.g. "European features baseline", "semi-realistic") to free CLIP budget.
        const cleanedBase = stripDescriptorDuplicates(basePrompt, visualDescriptors);
        // For non-front angles, compress the outfit to save CLIP tokens and add
        // angle-specific garment emphasis (e.g. "thong strap visible on hip" for
        // side views, "lace pattern visible from behind" for back view).
        // Front view uses the full uncompressed outfit (plenty of CLIP budget).
        const outfitTokens = compressOutfitForAngle(cleanedBase, params.angle);
        const garmentEmphasis = getGarmentEmphasis(params.angle, cleanedBase);
        const viewPrompt = [
            buildAnglePrompt(params.angle, params.framingType, params.avatarSettings),
            visualDescriptors,
            outfitTokens,
            garmentEmphasis,
            buildIdentityLockSuffix(params.framingType),
        ].filter(Boolean).join(', ');
        // Build the negative prompt: prevent front-facing bias from the reference latent
        const negParts = [
            'lowres, blurry, bad anatomy, deformed, extra fingers, missing fingers, bad hands, disfigured face, watermark, text, multiple people, duplicate',
        ];
        if (angleMeta.negativePrompt) {
            negParts.push(angleMeta.negativePrompt);
        }
        const negativePrompt = negParts.join(', ');
        setLoadingAngles((current) => ({ ...current, [params.angle]: true }));
        setError(null);
        try {
            const res = await fetch(`${base}/v1/avatars/outfits`, {
                method: 'POST',
                headers,
                body: JSON.stringify({
                    reference_image_url: params.referenceImageUrl,
                    outfit_prompt: viewPrompt,
                    // character_prompt intentionally omitted for view pack generation.
                    // The outfit description is already in viewPrompt (via basePrompt).
                    // Sending it again as character_prompt causes the backend to include
                    // it a second time after _strip_outfit_tokens, tripling outfit token
                    // weight and drowning out the angle directive.
                    // Identity is preserved via the reference image + InstantID, not text.
                    negative_prompt: negativePrompt,
                    count: 1,
                    generation_mode: angleMeta.generationMode || 'identity',
                    checkpoint_override: params.checkpointOverride,
                    seed: params.seed,
                    // Denoise: user-tuned value (from settings) or built-in default.
                    denoise_override: angleTuning?.denoise ?? angleMeta.denoise,
                    // Per-direction mirror control: send target_orientation only when
                    // the corresponding toggle is enabled in settings.
                    // Left defaults ON (SD confuses left), right defaults OFF (reliable).
                    target_orientation: (params.angle === 'left' && (params.avatarSettings?.autoMirrorLeft ?? true)) ||
                        (params.angle === 'right' && (params.avatarSettings?.autoMirrorRight ?? false))
                        ? params.angle
                        : undefined,
                }),
            });
            if (!res.ok) {
                const text = await res.text().catch(() => '');
                throw new Error(`View generation failed: ${res.status} ${text}`);
            }
            const data = await res.json();
            const first = data.results?.[0];
            if (!first)
                throw new Error('View generation returned no images');
            // Commit to durable storage, deleting old image if regenerating
            const oldUrl = resultsRef.current[params.angle]?.url;
            const durableUrl = await commitViewImage(base, headers, first.url, oldUrl);
            const tagged = {
                ...first,
                url: durableUrl,
                metadata: {
                    ...(first.metadata || {}),
                    view_angle: params.angle,
                    view_prompt: viewPrompt,
                    view_negative: negativePrompt,
                },
            };
            setResultsByAngle((current) => ({ ...current, [params.angle]: tagged }));
            setTimestampsByAngle((current) => ({ ...current, [params.angle]: Date.now() }));
            if (data.warnings?.length) {
                setWarnings((current) => [...current, ...data.warnings]);
            }
            return tagged;
        }
        catch (err) {
            const message = err instanceof Error ? err.message : 'View generation failed';
            setError(message);
            throw err;
        }
        finally {
            setLoadingAngles((current) => ({ ...current, [params.angle]: false }));
        }
    }, [backendUrl, apiKey, makeHeaders]);
    /** Delete a single angle result (in-memory + cache + backend file). */
    const deleteAngle = useCallback((angle) => {
        // Delete the durable file on the backend
        const existing = resultsRef.current[angle];
        if (existing?.url) {
            const base = (backendUrl || '').replace(/\/+$/, '');
            deleteViewImages(base, makeHeaders(), [existing.url]);
        }
        setResultsByAngle((current) => {
            const next = { ...current };
            delete next[angle];
            return next;
        });
        setTimestampsByAngle((current) => {
            const next = { ...current };
            delete next[angle];
            return next;
        });
    }, [backendUrl, makeHeaders]);
    /** Clear all results for the current key (in-memory + cache + backend files). */
    const reset = useCallback(() => {
        // Collect all durable URLs and delete them on the backend
        const allUrls = Object.values(resultsRef.current)
            .map((r) => r?.url)
            .filter((u) => Boolean(u));
        if (allUrls.length > 0) {
            const base = (backendUrl || '').replace(/\/+$/, '');
            deleteViewImages(base, makeHeaders(), allUrls);
        }
        setResultsByAngle({});
        setTimestampsByAngle({});
        setLoadingAngles({});
        setWarnings([]);
        setError(null);
        removeCached(cacheKey);
    }, [cacheKey, backendUrl, makeHeaders]);
    const missingAngles = useCallback((existing) => {
        const source = existing || resultsByAngle;
        return VIEW_ANGLE_OPTIONS.filter((item) => !source[item.id]).map((item) => item.id);
    }, [resultsByAngle]);
    return {
        resultsByAngle,
        timestampsByAngle,
        loadingAngles,
        anyLoading,
        warnings,
        error,
        generateAngle,
        deleteAngle,
        reset,
        missingAngles,
    };
}
