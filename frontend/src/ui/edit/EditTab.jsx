/**
 * EditTab - Main component for the Edit mode workspace.
 *
 * TWO-VIEW ARCHITECTURE:
 * 1. Gallery View (Landing): Shows thumbnails of all edited images (like Imagine)
 * 2. Editor View: Full Grok-style editing workspace when an image is selected
 *
 * Features:
 * - localStorage persistence for edit history
 * - Cyber-Noir aesthetic (True Black backgrounds)
 * - Centralized Canvas for immersive editing
 * - Floating "Conversational" Input Bar at the bottom
 * - Right-side "Studio" controls panel with advanced edit options
 * - Horizontal Filmstrip for version history with metadata
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Sparkles, Trash2, Upload, Loader2, Wand2, AlertCircle, Settings2, Download, History, ChevronRight, ChevronDown, ChevronLeft, Maximize2, X, RotateCcw, Clock, Sliders, Edit3, Plus, PaintBucket, Info, } from 'lucide-react';
import { EditDropzone } from './EditDropzone';
import { LoraManager } from './LoraManager';
import { MaskCanvas } from './MaskCanvas';
import { upscaleImage } from '../enhance/upscaleApi';
import { QuickActions } from './QuickActions';
import { BackgroundTools } from './BackgroundTools';
import { OutpaintTools } from './OutpaintTools';
import { useAvatarCapabilities } from '../useAvatarCapabilities';
import { uploadToEditSession, uploadToEditSessionByUrl, sendEditMessage, selectActiveImage, clearEditSession, getEditSession, extractImages, deleteVersion, } from './editApi';
import { resolveFileUrl } from '../resolveFileUrl';
// -----------------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------------
function uid() {
    return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
function formatTimeAgo(timestamp) {
    const seconds = Math.floor((Date.now() - timestamp) / 1000);
    if (seconds < 60)
        return 'just now';
    if (seconds < 3600)
        return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400)
        return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
}
// -----------------------------------------------------------------------------
// Component
// -----------------------------------------------------------------------------
export function EditTab({ backendUrl, apiKey, conversationId, onOpenLightbox, provider, providerBaseUrl, providerModel, onNavigateToAvatar, nsfwMode, }) {
    // Refs
    const fileInputRef = useRef(null);
    const resultsEndRef = useRef(null);
    const gridStartRef = useRef(null);
    // Avatar identity capabilities (for optional Identity Tools section)
    const { capabilities: avatarCaps } = useAvatarCapabilities(backendUrl, apiKey);
    // ==========================================================================
    // STATE - Gallery (persisted to localStorage)
    // ==========================================================================
    const [galleryItems, setGalleryItems] = useState(() => {
        try {
            const stored = localStorage.getItem('homepilot_edit_items');
            if (stored) {
                const parsed = JSON.parse(stored);
                return Array.isArray(parsed) ? parsed : [];
            }
        }
        catch (error) {
            console.error('Failed to load edit items from localStorage:', error);
        }
        return [];
    });
    // View mode: 'gallery' or 'editor'
    const [viewMode, setViewMode] = useState('gallery');
    const [currentEditItem, setCurrentEditItem] = useState(null);
    // ==========================================================================
    // STATE - Editor Session
    // ==========================================================================
    const [active, setActive] = useState(null);
    const [versions, setVersions] = useState([]);
    const [results, setResults] = useState([]);
    const [prompt, setPrompt] = useState('');
    const [lastPrompt, setLastPrompt] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState(null);
    const [initialized, setInitialized] = useState(false);
    const [showSettings, setShowSettings] = useState(true);
    // State - Advanced Controls
    const [advancedMode, setAdvancedMode] = useState(false);
    const [editMode, setEditMode] = useState('auto');
    const [steps, setSteps] = useState(30);
    const [cfg, setCfg] = useState(5.5);
    const [denoise, setDenoise] = useState(0.55);
    const [seedLock, setSeedLock] = useState(false);
    const [seed, setSeed] = useState(0);
    const [useCN, setUseCN] = useState(false);
    const [cnStrength, setCnStrength] = useState(1.0);
    // State - LoRA Add-ons (additive — Golden Rule 1.0)
    const [activeLoras, setActiveLoras] = useState([]);
    // State - Inpainting Mask
    const [showMaskCanvas, setShowMaskCanvas] = useState(false);
    const [maskDataUrl, setMaskDataUrl] = useState(null);
    const [uploadingMask, setUploadingMask] = useState(false);
    // State - Upscaling
    const [isUpscaling, setIsUpscaling] = useState(false);
    const hasImage = Boolean(active);
    // Info overlay state (top-right ℹ button on main image)
    const [showInfo, setShowInfo] = useState(false);
    // Look up the version entry for the currently active image
    const activeVersionInfo = useMemo(() => {
        if (!active)
            return null;
        return versions.find(v => v.url === active) || null;
    }, [active, versions]);
    // ==========================================================================
    // EFFECTS
    // ==========================================================================
    // Save gallery items to localStorage
    useEffect(() => {
        try {
            localStorage.setItem('homepilot_edit_items', JSON.stringify(galleryItems));
        }
        catch (error) {
            console.error('Failed to save edit items to localStorage:', error);
        }
    }, [galleryItems]);
    // Load session when entering editor mode
    useEffect(() => {
        if (viewMode !== 'editor' || !currentEditItem)
            return;
        let cancelled = false;
        const loadSession = async () => {
            try {
                const session = await getEditSession({
                    backendUrl,
                    apiKey,
                    conversationId: currentEditItem.conversationId
                });
                if (!cancelled) {
                    setActive(session.active_image_url ?? currentEditItem.url);
                    if (session.versions && session.versions.length > 0) {
                        setVersions(session.versions);
                    }
                    else if (session.history) {
                        setVersions(session.history.map((url, i) => ({
                            url,
                            instruction: '',
                            created_at: Date.now() / 1000 - i * 60,
                            parent_url: null,
                            settings: {},
                        })));
                    }
                    setInitialized(true);
                }
            }
            catch {
                if (!cancelled) {
                    // Session doesn't exist yet, use the item's URL
                    setActive(currentEditItem.url);
                    setVersions([{
                            url: currentEditItem.url,
                            instruction: currentEditItem.instruction,
                            created_at: currentEditItem.createdAt / 1000,
                            parent_url: null,
                            settings: {},
                        }]);
                    setInitialized(true);
                }
            }
        };
        loadSession();
        return () => { cancelled = true; };
    }, [viewMode, currentEditItem, backendUrl, apiKey]);
    // Scroll to new results
    useEffect(() => {
        if (results.length > 0) {
            resultsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
        }
    }, [results]);
    // Auto-import image from Avatar Studio or ImageViewer (via sessionStorage handoff)
    useEffect(() => {
        const raw = sessionStorage.getItem('homepilot_edit_from_avatar');
        if (!raw || viewMode !== 'gallery')
            return;
        // Clear immediately to prevent re-processing
        sessionStorage.removeItem('homepilot_edit_from_avatar');
        // Parse source metadata if available, or treat as plain URL
        let sourceUrl;
        let sourceType;
        let sourceId;
        try {
            const parsed = JSON.parse(raw);
            sourceUrl = parsed.url || raw;
            sourceType = parsed.source_type;
            sourceId = parsed.source_id;
        }
        catch {
            sourceUrl = raw;
        }
        // Entirely server-side: backend resolves the URL to a file on disk
        // and forwards it to the edit session sidecar — no browser fetch needed
        const importImage = async () => {
            setBusy(true);
            setError(null);
            try {
                const newConversationId = uid();
                // Backend loads the image from /comfy/view/... or /files/... and
                // sends it directly to the edit session sidecar
                const data = await uploadToEditSessionByUrl({
                    backendUrl,
                    apiKey,
                    conversationId: newConversationId,
                    imageUrl: sourceUrl,
                });
                const uploadedUrl = data.active_image_url;
                if (!uploadedUrl) {
                    throw new Error('No image URL returned from edit session');
                }
                const newItem = {
                    id: uid(),
                    url: uploadedUrl,
                    createdAt: Date.now(),
                    originalUrl: uploadedUrl,
                    instruction: '[Imported]',
                    conversationId: newConversationId,
                    source: sourceType ? {
                        type: sourceType,
                        id: sourceId,
                        url: sourceUrl,
                    } : undefined,
                };
                setGalleryItems((prev) => [newItem, ...prev].slice(0, 100));
                setCurrentEditItem(newItem);
                setActive(uploadedUrl);
                setVersions([{
                        url: uploadedUrl,
                        instruction: '[Imported]',
                        created_at: Date.now() / 1000,
                        parent_url: null,
                        settings: {},
                    }]);
                setInitialized(true);
                setViewMode('editor');
            }
            catch (e) {
                setError(e instanceof Error ? e.message : 'Failed to import image');
            }
            finally {
                setBusy(false);
            }
        };
        importImage();
    }, [viewMode]); // eslint-disable-line react-hooks/exhaustive-deps
    // ==========================================================================
    // HELPERS
    // ==========================================================================
    const buildEditMessage = useCallback((userText, maskUrl) => {
        const parts = [userText.trim()];
        // Always include mask if provided (for inpainting)
        if (maskUrl) {
            parts.push(`--mask ${maskUrl}`);
            parts.push(`--mode inpaint`);
        }
        if (!advancedMode) {
            // Still inject LoRA flags even without advanced mode
            const enabledLorasBasic = activeLoras.filter((l) => l.enabled);
            for (const lora of enabledLorasBasic) {
                parts.push(`--lora ${lora.id}:${lora.weight.toFixed(2)}`);
            }
            return parts.join(' ');
        }
        // Add advanced parameters
        if (!maskUrl) {
            parts.push(`--mode ${editMode}`);
        }
        parts.push(`--steps ${steps}`);
        parts.push(`--cfg ${cfg}`);
        parts.push(`--denoise ${denoise}`);
        if (seedLock && seed > 0) {
            parts.push(`--seed ${seed}`);
        }
        if (useCN) {
            parts.push(`--cn on`);
            parts.push(`--cn-strength ${cnStrength}`);
        }
        // Inject active LoRA flags (additive — works even without advanced mode)
        const enabledLoras = activeLoras.filter((l) => l.enabled);
        for (const lora of enabledLoras) {
            parts.push(`--lora ${lora.id}:${lora.weight.toFixed(2)}`);
        }
        return parts.join(' ');
    }, [advancedMode, editMode, steps, cfg, denoise, seedLock, seed, useCN, cnStrength, activeLoras]);
    // Upload mask data URL to server and get a URL
    const uploadMask = useCallback(async (dataUrl) => {
        try {
            // Convert data URL to blob
            const response = await fetch(dataUrl);
            const blob = await response.blob();
            // Create form data
            const formData = new FormData();
            formData.append('file', blob, 'mask.png');
            // Upload to backend
            const uploadUrl = `${backendUrl}/upload`;
            const uploadRes = await fetch(uploadUrl, {
                method: 'POST',
                headers: apiKey ? { 'x-api-key': apiKey } : {},
                body: formData,
            });
            if (!uploadRes.ok) {
                throw new Error(`Upload failed: ${uploadRes.status}`);
            }
            const uploadData = await uploadRes.json();
            return uploadData.url || null;
        }
        catch (e) {
            console.error('Failed to upload mask:', e);
            return null;
        }
    }, [backendUrl, apiKey]);
    // ==========================================================================
    // HANDLERS - Gallery
    // ==========================================================================
    const handleUploadNew = useCallback(async (file, sourceInfo) => {
        setError(null);
        setBusy(true);
        const newConversationId = uid();
        try {
            const data = await uploadToEditSession({
                backendUrl,
                apiKey,
                conversationId: newConversationId,
                file,
            });
            const uploadedUrl = data.active_image_url;
            if (!uploadedUrl) {
                throw new Error('No image URL returned from upload');
            }
            const newItem = {
                id: uid(),
                url: uploadedUrl,
                createdAt: Date.now(),
                originalUrl: uploadedUrl,
                instruction: '[Original Upload]',
                conversationId: newConversationId,
                source: sourceInfo ? {
                    type: sourceInfo.sourceType,
                    id: sourceInfo.sourceId,
                    url: sourceInfo.sourceUrl,
                } : undefined,
            };
            setGalleryItems((prev) => [newItem, ...prev].slice(0, 100));
            // Open editor for this new item
            setCurrentEditItem(newItem);
            setActive(uploadedUrl);
            setVersions([{
                    url: uploadedUrl,
                    instruction: '[Original Upload]',
                    created_at: Date.now() / 1000,
                    parent_url: null,
                    settings: {},
                }]);
            setInitialized(true);
            setViewMode('editor');
        }
        catch (e) {
            setError(e instanceof Error ? e.message : 'Upload failed');
        }
        finally {
            setBusy(false);
        }
    }, [backendUrl, apiKey]);
    const handleOpenEditor = useCallback((item) => {
        setCurrentEditItem(item);
        setInitialized(false);
        setActive(null);
        setVersions([]);
        setResults([]);
        setPrompt('');
        setError(null);
        setViewMode('editor');
    }, []);
    const handleBackToGallery = useCallback(() => {
        setViewMode('gallery');
        setCurrentEditItem(null);
        setActive(null);
        setVersions([]);
        setResults([]);
        setPrompt('');
        setError(null);
        setInitialized(false);
    }, []);
    const handleDeleteItem = useCallback(async (item, e) => {
        if (e)
            e.stopPropagation();
        if (!confirm('Delete this edited image from gallery?'))
            return;
        // Remove from local gallery state (and localStorage via effect)
        setGalleryItems((prev) => prev.filter((i) => i.id !== item.id));
        // Also delete backend session data to ensure persistence
        try {
            await clearEditSession({
                backendUrl,
                apiKey,
                conversationId: item.conversationId,
            });
        }
        catch (err) {
            // Silently ignore - backend session may not exist or already deleted
            console.warn('[EditTab] Failed to clear backend session:', err);
        }
    }, [backendUrl, apiKey]);
    // ==========================================================================
    // HANDLERS - Editor
    // ==========================================================================
    const handlePickFile = useCallback(async (file) => {
        if (viewMode === 'gallery') {
            return handleUploadNew(file);
        }
        if (!currentEditItem)
            return;
        setError(null);
        setBusy(true);
        setResults([]);
        try {
            const data = await uploadToEditSession({
                backendUrl,
                apiKey,
                conversationId: currentEditItem.conversationId,
                file
            });
            setActive(data.active_image_url ?? null);
            if (data.versions && data.versions.length > 0) {
                setVersions(data.versions);
            }
            else if (data.history) {
                setVersions(data.history.map((url, i) => ({
                    url,
                    instruction: i === 0 ? '[Original Upload]' : '',
                    created_at: Date.now() / 1000 - i * 60,
                    parent_url: null,
                    settings: {},
                })));
            }
        }
        catch (e) {
            setError(e instanceof Error ? e.message : 'Upload failed');
        }
        finally {
            setBusy(false);
        }
    }, [viewMode, currentEditItem, backendUrl, apiKey, handleUploadNew]);
    const runEdit = useCallback(async (text) => {
        const trimmed = text.trim();
        if (!trimmed || !currentEditItem)
            return;
        setError(null);
        setBusy(true);
        setLastPrompt(trimmed);
        setResults([]);
        // Upload mask if one is set
        let uploadedMaskUrl = null;
        if (maskDataUrl) {
            setUploadingMask(true);
            uploadedMaskUrl = await uploadMask(maskDataUrl);
            setUploadingMask(false);
            if (!uploadedMaskUrl) {
                setError('Failed to upload mask. Please try again.');
                setBusy(false);
                return;
            }
        }
        const messageToSend = buildEditMessage(trimmed, uploadedMaskUrl);
        try {
            const out = await sendEditMessage({
                backendUrl,
                apiKey,
                conversationId: currentEditItem.conversationId,
                message: messageToSend,
                provider,
                provider_base_url: providerBaseUrl,
                model: providerModel,
            });
            const imgs = extractImages(out.raw);
            setResults(imgs);
            if (imgs.length) {
                const now = Date.now();
                const newVersions = imgs.map(url => ({
                    url,
                    instruction: trimmed,
                    created_at: now / 1000,
                    parent_url: active,
                    settings: {
                        steps, cfg, denoise, editMode,
                        seed: seedLock ? seed : undefined,
                        model: providerModel || undefined,
                        loras: activeLoras.filter(l => l.enabled).map(l => ({ id: l.id, weight: l.weight })),
                    },
                }));
                setVersions((prev) => {
                    const existing = prev.filter(v => !imgs.includes(v.url));
                    return [...newVersions, ...existing].slice(0, 20);
                });
                // Auto-select first result
                const firstResult = imgs[0];
                setActive(firstResult);
                // Update gallery - keep only one thumbnail per project (conversationId)
                // Always show the latest edited version, not duplicates
                setGalleryItems((prev) => {
                    // Remove any existing items with the same conversationId
                    const filtered = prev.filter(item => item.conversationId !== currentEditItem.conversationId);
                    // Create updated item with the latest version
                    const updatedItem = {
                        id: currentEditItem.id, // Keep same ID
                        url: firstResult, // Use the latest edited version
                        createdAt: now,
                        originalUrl: currentEditItem.originalUrl,
                        instruction: trimmed,
                        conversationId: currentEditItem.conversationId,
                        settings: {
                            steps, cfg, denoise, editMode,
                            seed: seedLock ? seed : undefined,
                            model: providerModel || undefined,
                            loras: activeLoras.filter(l => l.enabled).map(l => ({ id: l.id, weight: l.weight })),
                        },
                    };
                    // Add updated item at the beginning (most recent first)
                    return [updatedItem, ...filtered].slice(0, 100);
                });
                // Update current edit item reference
                setCurrentEditItem(prev => prev ? {
                    ...prev,
                    url: firstResult,
                    createdAt: now,
                    instruction: trimmed,
                } : prev);
                // Persist to backend
                selectActiveImage({
                    backendUrl,
                    apiKey,
                    conversationId: currentEditItem.conversationId,
                    image_url: firstResult,
                }).catch(err => console.warn('Failed to persist active image:', err));
                // Clear mask after successful edit
                if (maskDataUrl) {
                    setMaskDataUrl(null);
                }
                setResults([]);
            }
        }
        catch (e) {
            setError(e instanceof Error ? e.message : 'Edit failed');
        }
        finally {
            setBusy(false);
        }
    }, [currentEditItem, buildEditMessage, backendUrl, apiKey, provider, providerBaseUrl, providerModel, active, advancedMode, steps, cfg, denoise, editMode, maskDataUrl, uploadMask]);
    const handleUse = useCallback(async (url) => {
        if (!currentEditItem)
            return;
        setError(null);
        setBusy(true);
        setShowInfo(false);
        try {
            const state = await selectActiveImage({
                backendUrl,
                apiKey,
                conversationId: currentEditItem.conversationId,
                image_url: url,
            });
            setActive(state.active_image_url ?? url);
            if (state.versions && state.versions.length > 0) {
                setVersions(state.versions);
            }
            else if (state.history) {
                setVersions(state.history.map((u, i) => ({
                    url: u,
                    instruction: '',
                    created_at: Date.now() / 1000 - i * 60,
                    parent_url: null,
                    settings: {},
                })));
            }
            setResults([]);
        }
        catch (e) {
            setError(e instanceof Error ? e.message : 'Failed to set active image');
        }
        finally {
            setBusy(false);
        }
    }, [currentEditItem, backendUrl, apiKey]);
    const handleReset = useCallback(async () => {
        if (!currentEditItem)
            return;
        setError(null);
        setBusy(true);
        try {
            await clearEditSession({
                backendUrl,
                apiKey,
                conversationId: currentEditItem.conversationId,
            });
            setActive(null);
            setVersions([]);
            setResults([]);
            setPrompt('');
            setLastPrompt('');
        }
        catch (e) {
            setError(e instanceof Error ? e.message : 'Failed to reset');
        }
        finally {
            setBusy(false);
        }
    }, [currentEditItem, backendUrl, apiKey]);
    const handleSubmit = useCallback((e) => {
        e?.preventDefault();
        if (prompt.trim()) {
            runEdit(prompt);
            setPrompt('');
        }
    }, [prompt, runEdit]);
    const handleUpscale = useCallback(async () => {
        if (!active || !currentEditItem || isUpscaling)
            return;
        setIsUpscaling(true);
        setError(null);
        try {
            const result = await upscaleImage({
                backendUrl,
                apiKey,
                imageUrl: active,
                scale: 2,
                model: '4x-UltraSharp.pth',
            });
            const upscaledUrl = result?.media?.images?.[0];
            if (upscaledUrl) {
                // Add to versions (non-destructive)
                const now = Date.now();
                const newVersion = {
                    url: upscaledUrl,
                    instruction: '[Upscaled 2x]',
                    created_at: now / 1000,
                    parent_url: active,
                    settings: {},
                };
                setVersions((prev) => [newVersion, ...prev]);
                setActive(upscaledUrl);
                // Persist to backend
                selectActiveImage({
                    backendUrl,
                    apiKey,
                    conversationId: currentEditItem.conversationId,
                    image_url: upscaledUrl,
                }).catch(err => console.warn('Failed to persist upscaled image:', err));
            }
            else {
                setError('Upscale completed but no image was returned.');
            }
        }
        catch (e) {
            setError(e instanceof Error ? e.message : 'Upscale failed');
        }
        finally {
            setIsUpscaling(false);
        }
    }, [active, currentEditItem, isUpscaling, backendUrl, apiKey]);
    // Handler for QuickActions (Enhance, Restore, Fix Faces, Upscale)
    const handleQuickActionResult = useCallback((resultUrl, mode) => {
        if (!currentEditItem)
            return;
        const now = Date.now();
        const modeLabels = {
            photo: 'Enhanced',
            restore: 'Restored',
            faces: 'Faces Fixed',
            upscale: 'Upscaled',
        };
        const instruction = `[${modeLabels[mode] || mode}]`;
        const newVersion = {
            url: resultUrl,
            instruction,
            created_at: now / 1000,
            parent_url: active,
            settings: { mode },
        };
        setVersions((prev) => [newVersion, ...prev]);
        setActive(resultUrl);
        // Update gallery
        setGalleryItems((prev) => {
            const filtered = prev.filter(item => item.conversationId !== currentEditItem.conversationId);
            const updatedItem = {
                id: currentEditItem.id,
                url: resultUrl,
                createdAt: now,
                originalUrl: currentEditItem.originalUrl,
                instruction,
                conversationId: currentEditItem.conversationId,
            };
            return [updatedItem, ...filtered].slice(0, 100);
        });
        // Update current edit item reference
        setCurrentEditItem(prev => prev ? { ...prev, url: resultUrl, createdAt: now, instruction } : prev);
        // Persist to backend
        selectActiveImage({
            backendUrl,
            apiKey,
            conversationId: currentEditItem.conversationId,
            image_url: resultUrl,
        }).catch(err => console.warn('Failed to persist active image:', err));
    }, [currentEditItem, active, backendUrl, apiKey]);
    // Handler for BackgroundTools (Remove BG, Change BG, Blur BG)
    const handleBackgroundResult = useCallback((resultUrl, action) => {
        if (!currentEditItem)
            return;
        const now = Date.now();
        const actionLabels = {
            remove: 'BG Removed',
            replace: 'BG Changed',
            blur: 'BG Blurred',
        };
        const instruction = `[${actionLabels[action] || action}]`;
        const newVersion = {
            url: resultUrl,
            instruction,
            created_at: now / 1000,
            parent_url: active,
            settings: { action },
        };
        setVersions((prev) => [newVersion, ...prev]);
        setActive(resultUrl);
        // Update gallery
        setGalleryItems((prev) => {
            const filtered = prev.filter(item => item.conversationId !== currentEditItem.conversationId);
            const updatedItem = {
                id: currentEditItem.id,
                url: resultUrl,
                createdAt: now,
                originalUrl: currentEditItem.originalUrl,
                instruction,
                conversationId: currentEditItem.conversationId,
            };
            return [updatedItem, ...filtered].slice(0, 100);
        });
        setCurrentEditItem(prev => prev ? { ...prev, url: resultUrl, createdAt: now, instruction } : prev);
        selectActiveImage({
            backendUrl,
            apiKey,
            conversationId: currentEditItem.conversationId,
            image_url: resultUrl,
        }).catch(err => console.warn('Failed to persist active image:', err));
    }, [currentEditItem, active, backendUrl, apiKey]);
    // Handler for OutpaintTools (Extend canvas)
    const handleOutpaintResult = useCallback((resultUrl, direction, newSize) => {
        if (!currentEditItem)
            return;
        const now = Date.now();
        const directionLabels = {
            left: 'Extended Left',
            right: 'Extended Right',
            up: 'Extended Up',
            down: 'Extended Down',
            horizontal: 'Extended Horizontal',
            vertical: 'Extended Vertical',
            all: 'Extended All Sides',
        };
        const instruction = `[${directionLabels[direction] || 'Extended'}] → ${newSize[0]}×${newSize[1]}`;
        const newVersion = {
            url: resultUrl,
            instruction,
            created_at: now / 1000,
            parent_url: active,
            settings: { direction, newSize },
        };
        setVersions((prev) => [newVersion, ...prev]);
        setActive(resultUrl);
        // Update gallery
        setGalleryItems((prev) => {
            const filtered = prev.filter(item => item.conversationId !== currentEditItem.conversationId);
            const updatedItem = {
                id: currentEditItem.id,
                url: resultUrl,
                createdAt: now,
                originalUrl: currentEditItem.originalUrl,
                instruction,
                conversationId: currentEditItem.conversationId,
            };
            return [updatedItem, ...filtered].slice(0, 100);
        });
        setCurrentEditItem(prev => prev ? { ...prev, url: resultUrl, createdAt: now, instruction } : prev);
        selectActiveImage({
            backendUrl,
            apiKey,
            conversationId: currentEditItem.conversationId,
            image_url: resultUrl,
        }).catch(err => console.warn('Failed to persist active image:', err));
    }, [currentEditItem, active, backendUrl, apiKey]);
    // Handler for IdentityTools (Fix Faces+, Inpaint Preserve, Change BG Preserve, Face Swap)
    const handleIdentityToolResult = useCallback((resultUrl, toolType) => {
        if (!currentEditItem)
            return;
        const now = Date.now();
        const toolLabels = {
            fix_faces_identity: 'Faces Fixed+',
            inpaint_identity: 'Inpaint (ID)',
            change_bg_identity: 'BG Changed (ID)',
            face_swap: 'Face Swapped',
        };
        const instruction = `[${toolLabels[toolType] || toolType}]`;
        const newVersion = {
            url: resultUrl,
            instruction,
            created_at: now / 1000,
            parent_url: active,
            settings: { mode: toolType },
        };
        setVersions((prev) => [newVersion, ...prev]);
        setActive(resultUrl);
        // Update gallery
        setGalleryItems((prev) => {
            const filtered = prev.filter(item => item.conversationId !== currentEditItem.conversationId);
            const updatedItem = {
                id: currentEditItem.id,
                url: resultUrl,
                createdAt: now,
                originalUrl: currentEditItem.originalUrl,
                instruction,
                conversationId: currentEditItem.conversationId,
            };
            return [updatedItem, ...filtered].slice(0, 100);
        });
        setCurrentEditItem(prev => prev ? { ...prev, url: resultUrl, createdAt: now, instruction } : prev);
        selectActiveImage({
            backendUrl,
            apiKey,
            conversationId: currentEditItem.conversationId,
            image_url: resultUrl,
        }).catch(err => console.warn('Failed to persist active image:', err));
    }, [currentEditItem, active, backendUrl, apiKey]);
    const handleDeleteVersion = useCallback((versionUrl, e) => {
        if (e) {
            e.stopPropagation();
            e.preventDefault();
        }
        console.log('[EditTab] Deleting version:', versionUrl);
        // Delete from backend first, then update frontend state
        const conversationId = currentEditItem?.conversationId;
        if (conversationId) {
            deleteVersion({
                backendUrl,
                apiKey,
                conversationId,
                imageUrl: versionUrl,
            }).catch(err => console.warn('Failed to delete version from backend:', err));
        }
        setVersions((prev) => {
            const filtered = prev.filter(v => v.url !== versionUrl);
            console.log('[EditTab] Versions after delete:', filtered.length);
            // If this was the last version, delete the entire edit project
            if (filtered.length === 0 && currentEditItem) {
                console.log('[EditTab] Last version deleted — removing edit project');
                // Remove from gallery
                setGalleryItems((items) => items.filter((i) => i.id !== currentEditItem.id));
                // Clear backend session
                clearEditSession({
                    backendUrl,
                    apiKey,
                    conversationId: currentEditItem.conversationId,
                }).catch(err => console.warn('Failed to clear backend session:', err));
                // Fully reset editor state and return to gallery
                setActive(null);
                setCurrentEditItem(null);
                setResults([]);
                setPrompt('');
                setError(null);
                setInitialized(false);
                setViewMode('gallery');
                return filtered;
            }
            // Determine new active image after deletion
            let newActive = null;
            if (active === versionUrl && filtered.length > 0) {
                // Deleted the active version — navigate to the nearest alive photo
                const oldIndex = prev.findIndex(v => v.url === versionUrl);
                // Pick the previous version (older), or the next one if at start
                const newIndex = Math.min(oldIndex, filtered.length - 1);
                newActive = filtered[Math.max(0, newIndex)].url;
                setActive(newActive);
            }
            // Update the gallery thumbnail to show the latest non-deleted version.
            // The latest version is the first entry in the filtered array (newest first).
            const thumbnailUrl = newActive || filtered[0]?.url;
            if (thumbnailUrl && currentEditItem) {
                setGalleryItems((items) => items.map((item) => item.conversationId === currentEditItem.conversationId
                    ? { ...item, url: thumbnailUrl }
                    : item));
                setCurrentEditItem(prev => prev ? { ...prev, url: thumbnailUrl } : prev);
                // Persist the new active to backend
                selectActiveImage({
                    backendUrl,
                    apiKey,
                    conversationId: currentEditItem.conversationId,
                    image_url: thumbnailUrl,
                }).catch(err => console.warn('Failed to persist active image:', err));
            }
            return filtered;
        });
    }, [active, currentEditItem, backendUrl, apiKey]);
    // ==========================================================================
    // RENDER - Gallery View
    // ==========================================================================
    if (viewMode === 'gallery') {
        return (<div className="h-full w-full bg-black text-white font-sans overflow-hidden flex flex-col relative">
        {/* Header */}
        <div className="absolute top-0 left-0 right-0 z-20 flex justify-between items-center px-6 py-4 bg-gradient-to-b from-black/80 to-transparent pointer-events-none">
          <div className="pointer-events-auto flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-white/5 border border-white/10 flex items-center justify-center">
              <Edit3 size={16} className="text-white"/>
            </div>
            <div>
              <div className="text-sm font-semibold text-white leading-tight">HomePilot</div>
              <div className="text-xs text-white/50 leading-tight">Edit Studio</div>
            </div>
          </div>

          <div className="pointer-events-auto flex items-center gap-2">
            <input ref={fileInputRef} type="file" accept="image/*" className="hidden" onChange={(e) => {
                const file = e.target.files?.[0];
                if (file)
                    handleUploadNew(file);
                e.currentTarget.value = '';
            }}/>
            <button className="flex items-center gap-2 bg-white/5 hover:bg-white/10 border border-white/10 px-4 py-2 rounded-full text-sm font-semibold transition-all" type="button" onClick={() => fileInputRef.current?.click()} disabled={busy}>
              <Upload size={16} className="text-white/70"/>
              <span>Upload Image</span>
            </button>
          </div>
        </div>

        {/* Grid Gallery */}
        <div className="flex-1 overflow-y-auto px-4 pb-8 pt-20 scrollbar-hide">
          <div className="max-w-[1600px] mx-auto grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 content-start">
            <div ref={gridStartRef} className="col-span-full h-1"/>

            {/* Empty state */}
            {galleryItems.length === 0 && !busy ? (<div className="col-span-full">
                <EditDropzone onPickFile={handleUploadNew} disabled={busy}/>
              </div>) : null}

            {/* Loading skeleton */}
            {busy && (<div className="relative rounded-2xl overflow-hidden bg-white/5 border border-white/10 aspect-square animate-pulse">
                <div className="absolute inset-0 bg-gradient-to-tr from-white/10 to-transparent"></div>
                <div className="absolute bottom-4 left-4 text-sm font-mono text-white/70">Uploading…</div>
              </div>)}

            {/* Gallery items */}
            {galleryItems.map((item) => (<div key={item.id} onClick={() => handleOpenEditor(item)} className="relative group rounded-2xl overflow-hidden bg-white/5 border border-white/10 hover:border-white/20 transition-colors cursor-pointer aspect-square">
                <img src={resolveFileUrl(item.url, backendUrl)} alt={item.instruction} className="absolute inset-0 w-full h-full object-cover transition-transform duration-700 group-hover:scale-105" loading="lazy"/>

                <div className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity duration-300 flex flex-col justify-between p-4">
                  <div className="flex justify-end gap-2">
                    <button className="bg-white/10 backdrop-blur-md hover:bg-white/20 p-2 rounded-full text-white transition-colors" type="button" title="Edit" onClick={(e) => {
                    e.stopPropagation();
                    handleOpenEditor(item);
                }}>
                      <Edit3 size={16}/>
                    </button>
                    <button className="bg-red-500/20 backdrop-blur-md hover:bg-red-500/40 p-2 rounded-full text-red-400 hover:text-red-300 transition-colors" type="button" title="Delete" onClick={(e) => handleDeleteItem(item, e)}>
                      <Trash2 size={16}/>
                    </button>
                  </div>

                  <div>
                    <div className="text-xs text-white/80 line-clamp-2 mb-1">{item.instruction}</div>
                    <div className="text-[10px] text-white/50 flex items-center gap-1">
                      <Clock size={10}/>
                      {formatTimeAgo(item.createdAt)}
                    </div>
                  </div>
                </div>
              </div>))}
          </div>
        </div>

        {/* Floating Add Button */}
        {galleryItems.length > 0 && (<div className="absolute bottom-6 right-6 z-30">
            <button onClick={() => fileInputRef.current?.click()} disabled={busy} className="w-14 h-14 rounded-full bg-white text-black hover:bg-gray-200 transition-all shadow-2xl flex items-center justify-center" type="button" title="Upload new image">
              <Plus size={24}/>
            </button>
          </div>)}

        <style>{`
          .scrollbar-hide::-webkit-scrollbar { display: none; }
          .scrollbar-hide { -ms-overflow-style: none; scrollbar-width: none; }
          .line-clamp-2 {
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
          }
        `}</style>
      </div>);
    }
    // ==========================================================================
    // RENDER - Editor View (Original Grok-style design)
    // ==========================================================================
    if (!initialized) {
        return (<div className="w-full h-full flex items-center justify-center bg-black">
        <div className="flex flex-col items-center gap-4 text-white/50">
          <Loader2 size={32} className="animate-spin text-white"/>
          <span className="text-sm font-mono tracking-wider">INITIALIZING STUDIO...</span>
        </div>
      </div>);
    }
    return (<div className="relative flex h-full w-full bg-black text-white overflow-hidden font-sans">
      {/* --- Main Workspace (Canvas) --- */}
      <div className="flex-1 flex flex-col relative z-0">
        {/* Top Bar (Transparent) */}
        <div className="absolute top-0 left-0 right-0 p-6 flex items-start justify-between z-20 pointer-events-none">
          <div className="pointer-events-auto flex items-center gap-3">
            {/* Back to Gallery Button */}
            <button onClick={handleBackToGallery} className="h-8 w-8 rounded-full bg-white/10 hover:bg-white/20 flex items-center justify-center backdrop-blur-md transition-colors" title="Back to Gallery">
              <ChevronLeft size={18} className="text-white"/>
            </button>
            <div className="h-8 w-8 rounded-full bg-white/10 flex items-center justify-center backdrop-blur-md">
              <Sparkles size={16} className="text-white"/>
            </div>
            <div>
              <h1 className="text-sm font-bold tracking-wide">EDIT STUDIO</h1>
              <p className="text-[10px] text-white/40 font-mono uppercase tracking-wider">
                {hasImage ? 'Session Active' : 'No Image Loaded'}
              </p>
            </div>
          </div>

          <div className="pointer-events-auto flex gap-2">
            <input ref={fileInputRef} type="file" accept="image/*" className="hidden" onChange={(e) => {
            const file = e.target.files?.[0];
            if (file)
                handlePickFile(file);
            e.currentTarget.value = '';
        }}/>
            {hasImage && (<>
                <button onClick={() => fileInputRef.current?.click()} className="p-2 rounded-lg bg-black/40 hover:bg-white/10 border border-white/10 text-white/70 hover:text-white transition-colors backdrop-blur-md" title="Upload New">
                  <Upload size={18}/>
                </button>
                <button onClick={handleReset} className="p-2 rounded-lg bg-black/40 hover:bg-red-500/20 border border-white/10 text-white/70 hover:text-red-400 transition-colors backdrop-blur-md" title="Reset Session">
                  <Trash2 size={18}/>
                </button>
                <button onClick={() => setShowSettings(!showSettings)} className={`p-2 rounded-lg border border-white/10 transition-colors backdrop-blur-md ${showSettings ? 'bg-white text-black' : 'bg-black/40 text-white/70 hover:text-white'}`} title="Toggle Settings">
                  <Settings2 size={18}/>
                </button>
              </>)}
          </div>
        </div>

        {/* Canvas Area */}
        <div className="flex-1 relative flex items-center justify-center bg-[radial-gradient(circle_at_center,_var(--tw-gradient-stops))] from-white/5 to-black">
          {!hasImage ? (<div className="w-full max-w-xl px-6 relative z-10">
              <EditDropzone onPickFile={handlePickFile} disabled={busy}/>
            </div>) : (<div className="relative w-full h-full p-8 pb-32 flex items-center justify-center">
              <div className="relative group max-w-full max-h-full shadow-2xl">
                <img src={resolveFileUrl(active, backendUrl)} alt="Active Canvas" className="max-w-full max-h-[65vh] object-contain rounded-sm shadow-[0_0_50px_rgba(0,0,0,0.5)] border border-white/5"/>
                {/* Info icon — top-right, appears on hover */}
                <div className="absolute top-3 right-3 z-30 pointer-events-auto">
                  <button onClick={() => setShowInfo(!showInfo)} className={`p-2 rounded-lg transition-all duration-200 shadow-lg backdrop-blur-sm border ${showInfo
                ? 'bg-white/15 border-white/25 text-white'
                : 'bg-black/70 border-white/10 text-white/60 opacity-0 group-hover:opacity-100 hover:text-white hover:bg-black/90'}`} title="Generation details">
                    <Info size={16}/>
                  </button>

                  {/* Info popover */}
                  {showInfo && activeVersionInfo && (<div className="absolute top-full right-0 mt-2 w-72 bg-[#0C0C0C]/95 backdrop-blur-xl border border-white/10 rounded-xl shadow-2xl overflow-hidden animate-in fade-in slide-in-from-top-2 duration-150">
                      <div className="px-3.5 py-2.5 border-b border-white/[0.06] flex items-center justify-between">
                        <span className="text-[10px] font-bold uppercase tracking-widest text-white/40">Generation Info</span>
                        <button onClick={() => setShowInfo(false)} className="text-white/30 hover:text-white/70 transition-colors">
                          <X size={12}/>
                        </button>
                      </div>
                      <div className="px-3.5 py-3 space-y-2.5 text-[11px]">
                        {/* Prompt */}
                        {activeVersionInfo.instruction && (<div>
                            <div className="text-white/30 text-[9px] uppercase tracking-wider mb-0.5">Prompt</div>
                            <div className="text-white/80 leading-relaxed break-words line-clamp-4">{activeVersionInfo.instruction}</div>
                          </div>)}
                        {/* Settings grid */}
                        {activeVersionInfo.settings && Object.keys(activeVersionInfo.settings).length > 0 && (<div className="grid grid-cols-2 gap-x-4 gap-y-1.5 pt-1">
                            {activeVersionInfo.settings.model != null && (<div className="col-span-2">
                                <span className="text-white/30 text-[9px] uppercase tracking-wider">Model</span>
                                <div className="text-white/70 font-mono text-[10px] truncate">{String(activeVersionInfo.settings.model).replace('.safetensors', '').replace('.ckpt', '')}</div>
                              </div>)}
                            {activeVersionInfo.settings.steps != null && (<div>
                                <span className="text-white/30 text-[9px] uppercase tracking-wider">Steps</span>
                                <div className="text-white/70 font-mono">{String(activeVersionInfo.settings.steps)}</div>
                              </div>)}
                            {activeVersionInfo.settings.cfg != null && (<div>
                                <span className="text-white/30 text-[9px] uppercase tracking-wider">CFG</span>
                                <div className="text-white/70 font-mono">{String(activeVersionInfo.settings.cfg)}</div>
                              </div>)}
                            {activeVersionInfo.settings.denoise != null && (<div>
                                <span className="text-white/30 text-[9px] uppercase tracking-wider">Denoise</span>
                                <div className="text-white/70 font-mono">{String(activeVersionInfo.settings.denoise)}</div>
                              </div>)}
                            {activeVersionInfo.settings.seed != null && (<div>
                                <span className="text-white/30 text-[9px] uppercase tracking-wider">Seed</span>
                                <div className="text-white/70 font-mono">{String(activeVersionInfo.settings.seed)}</div>
                              </div>)}
                            {activeVersionInfo.settings.editMode != null && (<div>
                                <span className="text-white/30 text-[9px] uppercase tracking-wider">Mode</span>
                                <div className="text-white/70 font-mono">{String(activeVersionInfo.settings.editMode)}</div>
                              </div>)}
                          </div>)}
                        {/* LoRAs */}
                        {activeVersionInfo.settings && Array.isArray(activeVersionInfo.settings.loras) && activeVersionInfo.settings.loras.length > 0 && (<div className="pt-1">
                            <div className="text-white/30 text-[9px] uppercase tracking-wider mb-1">LoRAs</div>
                            <div className="space-y-0.5">
                              {activeVersionInfo.settings.loras.map((l) => (<div key={l.id} className="flex items-center justify-between">
                                  <span className="text-white/70 font-mono text-[10px]">{l.id}</span>
                                  <span className="text-white/40 font-mono text-[10px]">{l.weight.toFixed(2)}</span>
                                </div>))}
                            </div>
                          </div>)}
                        {/* Timestamp */}
                        {activeVersionInfo.created_at > 0 && (<div className="pt-1 border-t border-white/[0.06]">
                            <span className="text-white/25 text-[9px]">
                              {new Date(activeVersionInfo.created_at * 1000).toLocaleString()}
                            </span>
                          </div>)}
                        {/* Fallback for original / no settings */}
                        {!activeVersionInfo.instruction && (!activeVersionInfo.settings || Object.keys(activeVersionInfo.settings).length === 0) && (<div className="text-white/30 text-center py-2">Original image — no generation data</div>)}
                      </div>
                    </div>)}
                </div>

                {/* Invisible hover extension to keep buttons accessible */}
                <div className="absolute -bottom-2 -right-2 -left-2 h-16 pointer-events-none"/>
                {/* Action buttons - positioned inside image bounds with z-index above bottom bar */}
                <div className="absolute bottom-3 right-3 z-30 flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-auto">
                  <button onClick={() => active && onOpenLightbox(active)} className="p-2.5 bg-black/90 text-white rounded-lg hover:bg-white hover:text-black transition-colors shadow-lg backdrop-blur-sm border border-white/10" title="Full screen">
                    <Maximize2 size={18}/>
                  </button>
                  <button onClick={handleUpscale} disabled={isUpscaling || busy} className={`p-2.5 rounded-lg transition-colors shadow-lg backdrop-blur-sm border border-white/10 ${isUpscaling
                ? 'bg-purple-500/80 text-white animate-pulse'
                : 'bg-purple-500/90 text-white hover:bg-purple-400'}`} title="Upscale 2x">
                    {isUpscaling ? <Loader2 size={18} className="animate-spin"/> : <Sparkles size={18}/>}
                  </button>
                  <a href={active} download="edited-image.png" className="p-2.5 bg-black/90 text-white rounded-lg hover:bg-white hover:text-black transition-colors shadow-lg backdrop-blur-sm border border-white/10" title="Download">
                    <Download size={18}/>
                  </a>
                </div>

                {busy && (<div className="absolute inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center rounded-sm">
                    <div className="flex flex-col items-center gap-3">
                      <Loader2 size={32} className="animate-spin text-white"/>
                      <span className="text-xs font-mono uppercase tracking-widest text-white/70">Processing Edit...</span>
                    </div>
                  </div>)}
              </div>
            </div>)}
        </div>

        {/* Bottom Floating Bar (Input + History) */}
        {hasImage && (<div className="absolute bottom-0 left-0 right-0 z-20 flex flex-col items-center pb-6 px-4 bg-gradient-to-t from-black via-black/80 to-transparent pt-20">
            {error && (<div className="mb-4 flex items-center gap-3 px-4 py-3 bg-red-950/80 border border-red-500/30 rounded-lg backdrop-blur-xl animate-in fade-in slide-in-from-bottom-5">
                <AlertCircle size={16} className="text-red-400"/>
                <span className="text-sm text-red-100">{error}</span>
                <button onClick={() => setError(null)} className="ml-2 text-red-400 hover:text-white"><X size={14}/></button>
              </div>)}

            {/* Input Bar (Grok Style) */}
            <div className="w-full max-w-3xl relative mb-8">
              <form onSubmit={handleSubmit} className="relative group">
                <div className="absolute inset-0 bg-white/5 rounded-2xl blur-xl group-hover:bg-white/10 transition-colors"/>
                <div className="relative flex items-center bg-[#0A0A0A] border border-white/10 rounded-2xl shadow-2xl focus-within:border-white/30 transition-colors overflow-hidden">
                  <div className="pl-4 text-white/40">
                    <Wand2 size={20}/>
                  </div>
                  <input value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder={busy ? "Processing..." : "Describe changes naturally (e.g. 'Make the lighting cyberpunk', 'Add rain')..."} className="flex-1 bg-transparent border-none text-white px-4 py-4 focus:ring-0 placeholder:text-white/30 text-base outline-none" disabled={busy}/>
                  <div className="pr-3">
                    <button type="submit" disabled={!prompt.trim() || busy} className="py-2 px-5 rounded-xl bg-white text-black hover:bg-gray-200 disabled:bg-white/10 disabled:text-white/30 disabled:cursor-not-allowed transition-all font-medium text-sm">
                      Generate
                    </button>
                  </div>
                </div>
              </form>
            </div>

            {/* Filmstrip – unified rail: newest (left) → oldest (right), selected = displayed */}
            <div className="w-full max-w-5xl flex gap-2 overflow-x-auto pb-4 px-2 pt-2 snap-x scrollbar-hide items-end">
              {/* New results (not yet committed as versions) */}
              {results.map((url, idx) => {
                const isActive = active === url;
                return (<div key={`res-${idx}`} onClick={() => handleUse(url)} className={`snap-center shrink-0 relative group rounded-lg overflow-hidden cursor-pointer transition-all duration-200 ${isActive
                        ? 'w-[72px] h-[72px] border-2 border-purple-400 ring-2 ring-purple-400/40 shadow-[0_0_16px_rgba(147,51,234,0.4)]'
                        : 'w-16 h-16 border border-purple-500/30 hover:border-purple-400/60 opacity-70 hover:opacity-100'}`}>
                    <img src={resolveFileUrl(url, backendUrl)} className="w-full h-full object-cover" alt="Result"/>
                    <div className="absolute top-0.5 left-0.5 px-1 py-px bg-purple-500 text-[7px] font-bold text-white rounded">NEW</div>
                  </div>);
            })}

              {results.length > 0 && versions.length > 0 && (<div className="w-px h-12 bg-white/10 shrink-0 self-center mx-1"/>)}

              {/* Version history */}
              {versions.map((version, idx) => {
                const isActive = active === version.url;
                return (<div key={`ver-${version.url}-${idx}`} onClick={() => handleUse(version.url)} className={`snap-center shrink-0 relative group rounded-lg overflow-hidden cursor-pointer transition-all duration-200 ${isActive
                        ? 'w-[72px] h-[72px] border-2 border-white ring-2 ring-white/30 shadow-[0_0_16px_rgba(255,255,255,0.15)]'
                        : 'w-16 h-16 border border-white/10 hover:border-white/30 opacity-50 hover:opacity-100'}`}>
                    <img src={resolveFileUrl(version.url, backendUrl)} className="w-full h-full object-cover" alt="Version"/>

                    {/* Delete button - top right, visible on hover */}
                    <button onMouseDown={(e) => e.stopPropagation()} onClick={(e) => {
                        e.stopPropagation();
                        e.preventDefault();
                        if (window.confirm('Delete this version?')) {
                            handleDeleteVersion(version.url, e);
                        }
                    }} className="absolute top-0.5 right-0.5 p-0.5 bg-black/70 rounded opacity-0 group-hover:opacity-100 transition-opacity text-white/50 hover:text-red-400 hover:bg-black/90 z-10" title="Delete version">
                      <Trash2 size={10}/>
                    </button>

                    {/* Version index label on hover (prompt hidden — use info icon on main image) */}
                    <div className="absolute bottom-0 inset-x-0 bg-black/70 text-[8px] text-white/70 text-center py-0.5 opacity-0 group-hover:opacity-100 transition-opacity truncate px-1">
                      {idx === versions.length - 1 ? 'Original' : `v${versions.length - idx}`}
                    </div>
                  </div>);
            })}
              <div ref={resultsEndRef}/>
            </div>
          </div>)}
      </div>

      {/* --- Right Settings Panel (Collapsible) --- */}
      {hasImage && (<div className={`border-l border-white/10 bg-[#050505] transition-all duration-300 ease-in-out flex flex-col ${showSettings ? 'w-80 translate-x-0' : 'w-0 translate-x-full opacity-0 overflow-hidden'}`}>
          <div className="p-5 border-b border-white/10 flex items-center justify-between">
            <h3 className="font-bold text-sm tracking-wide flex items-center gap-2">
              <Settings2 size={16}/>
              PARAMETERS
            </h3>
            <button onClick={() => setShowSettings(false)} className="text-white/40 hover:text-white">
              <ChevronRight size={18}/>
            </button>
          </div>

          <div className="flex-1 overflow-y-auto p-5 space-y-6">
            {/* Advanced Mode Toggle */}
            <div className="space-y-3">
              <button onClick={() => setAdvancedMode(!advancedMode)} className={`w-full flex items-center justify-between p-3 rounded-xl border transition-colors ${advancedMode
                ? 'bg-purple-500/20 border-purple-500/40 text-purple-300'
                : 'bg-white/5 border-white/10 text-white/60 hover:border-white/20'}`}>
                <span className="flex items-center gap-2 font-medium text-sm">
                  <Sliders size={16}/>
                  Advanced Controls
                </span>
                {advancedMode ? <ChevronDown size={16}/> : <ChevronRight size={16}/>}
              </button>

              {advancedMode && (<div className="space-y-4 animate-in fade-in slide-in-from-top-2 duration-200">
                  <div className="space-y-2">
                    <label className="text-xs uppercase tracking-wider text-white/40 font-semibold">Edit Mode</label>
                    <select value={editMode} onChange={(e) => setEditMode(e.target.value)} className="w-full rounded-xl bg-white/5 border border-white/10 px-3 py-2.5 text-sm text-white focus:border-purple-500/50 focus:outline-none">
                      <option value="auto">Auto (Smart Detection)</option>
                      <option value="global">Global (Full Image)</option>
                      <option value="inpaint">Inpaint (Masked Area)</option>
                    </select>
                  </div>

                  <div className="space-y-2">
                    <div className="flex justify-between text-xs">
                      <span className="uppercase tracking-wider text-white/40 font-semibold">Steps</span>
                      <span className="text-white/60">{steps}</span>
                    </div>
                    <input type="range" min={10} max={50} value={steps} onChange={(e) => setSteps(Number(e.target.value))} className="w-full h-1.5 bg-white/10 rounded-full appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-purple-400 [&::-webkit-slider-thumb]:rounded-full"/>
                  </div>

                  <div className="space-y-2">
                    <div className="flex justify-between text-xs">
                      <span className="uppercase tracking-wider text-white/40 font-semibold">CFG Scale</span>
                      <span className="text-white/60">{cfg.toFixed(1)}</span>
                    </div>
                    <input type="range" min={1} max={15} step={0.5} value={cfg} onChange={(e) => setCfg(Number(e.target.value))} className="w-full h-1.5 bg-white/10 rounded-full appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-purple-400 [&::-webkit-slider-thumb]:rounded-full"/>
                  </div>

                  <div className="space-y-2">
                    <div className="flex justify-between text-xs">
                      <span className="uppercase tracking-wider text-white/40 font-semibold">Denoise Strength</span>
                      <span className="text-white/60">{denoise.toFixed(2)}</span>
                    </div>
                    <input type="range" min={0.1} max={1.0} step={0.05} value={denoise} onChange={(e) => setDenoise(Number(e.target.value))} className="w-full h-1.5 bg-white/10 rounded-full appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-purple-400 [&::-webkit-slider-thumb]:rounded-full"/>
                  </div>

                  <div className="flex items-center justify-between p-3 rounded-xl bg-white/5 border border-white/10">
                    <span className="text-sm text-white/80">Lock Seed</span>
                    <button onClick={() => {
                    if (!seedLock)
                        setSeed(Math.floor(Math.random() * 2147483647));
                    setSeedLock(!seedLock);
                }} className={`w-10 h-5 rounded-full transition-colors relative ${seedLock ? 'bg-purple-500' : 'bg-white/20'}`}>
                      <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${seedLock ? 'translate-x-5' : 'translate-x-0.5'}`}/>
                    </button>
                  </div>
                  {seedLock && (<input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} className="w-full rounded-xl bg-white/5 border border-white/10 px-3 py-2 text-sm text-white font-mono focus:border-purple-500/50 focus:outline-none" placeholder="Seed value"/>)}

                  <div className="flex items-center justify-between p-3 rounded-xl bg-white/5 border border-white/10">
                    <span className="text-sm text-white/80">Use ControlNet</span>
                    <button onClick={() => setUseCN(!useCN)} className={`w-10 h-5 rounded-full transition-colors relative ${useCN ? 'bg-purple-500' : 'bg-white/20'}`}>
                      <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${useCN ? 'translate-x-5' : 'translate-x-0.5'}`}/>
                    </button>
                  </div>
                  {useCN && (<div className="space-y-2">
                      <div className="flex justify-between text-xs">
                        <span className="uppercase tracking-wider text-white/40 font-semibold">CN Strength</span>
                        <span className="text-white/60">{cnStrength.toFixed(2)}</span>
                      </div>
                      <input type="range" min={0} max={2} step={0.05} value={cnStrength} onChange={(e) => setCnStrength(Number(e.target.value))} className="w-full h-1.5 bg-white/10 rounded-full appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-purple-400 [&::-webkit-slider-thumb]:rounded-full"/>
                    </div>)}
                </div>)}
            </div>

            {/* LoRA Add-ons (additive — Golden Rule 1.0) */}
            <LoraManager backendUrl={backendUrl} apiKey={apiKey} activeLoras={activeLoras} onLorasChange={setActiveLoras} disabled={busy} currentModel={providerModel} nsfwMode={nsfwMode}/>

            {/* Quick Enhancement Actions */}
            <QuickActions backendUrl={backendUrl} apiKey={apiKey} imageUrl={active} onResult={handleQuickActionResult} onError={(err) => setError(err)} disabled={busy} compact={false}/>

            {/* Background Tools */}
            <BackgroundTools backendUrl={backendUrl} apiKey={apiKey} imageUrl={active} onResult={handleBackgroundResult} onError={(err) => setError(err)} disabled={busy} compact={false}/>

            {/* Outpaint / Extend Canvas */}
            <OutpaintTools backendUrl={backendUrl} apiKey={apiKey} imageUrl={active} onResult={handleOutpaintResult} onError={(err) => setError(err)} disabled={busy}/>

            {/* Identity Tools — hidden until ComfyUI custom nodes (Impact-Pack,
               InstantID, gfpgan, facexlib) are reliably installed across environments.
               Re-enable in a future release once the dependency story is solid.
               See: backend/app/comfy_utils/node_aliases.py for the node alias table. */}
            {/* <IdentityTools
              backendUrl={backendUrl}
              apiKey={apiKey}
              imageUrl={active}
              onResult={handleIdentityToolResult}
              onError={(err) => setError(err)}
              disabled={busy}
              hasBasicIdentity={avatarCaps.canIdentityPortrait}
              hasFaceSwap={avatarCaps.canFaceSwap}
              maskDataUrl={maskDataUrl}
            /> */}

            {/* Inpainting Mask Section */}
            <div className="space-y-3">
              <div className="flex items-center justify-between text-xs uppercase tracking-wider text-white/40 font-semibold">
                <span className="flex items-center gap-2">
                  <PaintBucket size={14}/>
                  Inpainting Mask
                </span>
                {maskDataUrl && (<button onClick={() => setMaskDataUrl(null)} className="text-red-400 hover:text-red-300 text-[10px]">
                    Clear
                  </button>)}
              </div>

              {maskDataUrl ? (<div className="space-y-2">
                  <div className="relative rounded-lg overflow-hidden border border-purple-500/30 bg-purple-500/10">
                    <img src={maskDataUrl} alt="Mask preview" className="w-full h-20 object-contain opacity-70"/>
                    <div className="absolute inset-0 flex items-center justify-center">
                      <span className="text-[10px] text-purple-300 bg-black/60 px-2 py-1 rounded">
                        Mask Active
                      </span>
                    </div>
                  </div>
                  <button onClick={() => setShowMaskCanvas(true)} className="w-full flex items-center justify-center gap-2 p-2.5 rounded-xl bg-purple-500/20 border border-purple-500/30 text-purple-300 hover:bg-purple-500/30 transition-colors text-sm font-medium">
                    <PaintBucket size={14}/>
                    Edit Mask
                  </button>
                </div>) : (<button onClick={() => setShowMaskCanvas(true)} disabled={!active} className="w-full flex items-center justify-center gap-2 p-3 rounded-xl bg-white/5 border border-white/10 text-white/60 hover:bg-purple-500/20 hover:border-purple-500/30 hover:text-purple-300 disabled:opacity-40 disabled:cursor-not-allowed transition-colors text-sm font-medium">
                  <PaintBucket size={16}/>
                  Draw Mask for Inpainting
                </button>)}

              <p className="text-[10px] text-white/30 leading-relaxed">
                Draw a mask to edit only specific areas. White = areas to change, black = areas to preserve.
              </p>
            </div>

            {/* Version History Summary */}
            <div className="space-y-3">
              <div className="flex items-center justify-between text-xs uppercase tracking-wider text-white/40 font-semibold">
                <span className="flex items-center gap-2">
                  <History size={14}/>
                  Version History
                </span>
                <span className="text-white/30">{versions.length} versions</span>
              </div>
              <div className="space-y-2 max-h-48 overflow-y-auto">
                {versions.slice(0, 5).map((v, idx) => (<div key={`${v.url}-${idx}`} onClick={() => handleUse(v.url)} className={`flex items-center gap-3 p-2 rounded-lg cursor-pointer transition-colors group/item ${active === v.url
                    ? 'bg-purple-500/20 border border-purple-500/30'
                    : 'bg-white/5 border border-transparent hover:border-white/10'}`}>
                    <img src={resolveFileUrl(v.url, backendUrl)} alt="" className="w-10 h-10 rounded object-cover"/>
                    <div className="flex-1 min-w-0">
                      <div className="text-xs text-white/80 truncate">
                        {v.instruction || 'Original'}
                      </div>
                      <div className="text-[10px] text-white/40">
                        Version {versions.length - idx}
                      </div>
                    </div>
                    {active !== v.url && (<button className="p-1 text-white/30 hover:text-white opacity-0 group-hover/item:opacity-100 transition-opacity" title="Use this version">
                        <RotateCcw size={12}/>
                      </button>)}
                  </div>))}
              </div>
            </div>

            <div className="p-4 rounded-xl bg-purple-900/10 border border-purple-500/20 text-xs text-purple-200/70 leading-relaxed">
              <span className="font-bold text-purple-400 block mb-1">PRO TIP</span>
              Enable Advanced Controls to fine-tune edit parameters like steps, CFG, and denoise strength for better results.
            </div>
          </div>
        </div>)}

      {/* Mask Canvas Modal */}
      {showMaskCanvas && active && (<MaskCanvas imageUrl={active} initialMask={maskDataUrl} onSaveMask={(dataUrl) => {
                setMaskDataUrl(dataUrl);
                setShowMaskCanvas(false);
            }} onCancel={() => setShowMaskCanvas(false)}/>)}

      <style>{`
        .scrollbar-hide::-webkit-scrollbar { display: none; }
        .scrollbar-hide { -ms-overflow-style: none; scrollbar-width: none; }
      `}</style>
    </div>);
}
export default EditTab;
