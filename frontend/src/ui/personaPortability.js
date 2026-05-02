/**
 * Persona Portability — Phase 3 v2
 *
 * Types and API helpers for .hpersona export/import:
 *   - Export a persona project as a downloadable .hpersona file
 *   - Preview a .hpersona package (parse + dependency check)
 *   - Import a .hpersona and create a new persona project
 */
// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------
function authHeaders(apiKey) {
    const h = {};
    if (apiKey && apiKey.trim().length > 0)
        h['x-api-key'] = apiKey;
    return h;
}
/**
 * Export a persona project — triggers a browser download of the .hpersona file.
 *
 * Uses mode='full' by default so avatar images are included as real files
 * inside the ZIP's assets/ folder, making the package fully portable.
 * The .hpersona ZIP structure:
 *   manifest.json
 *   blueprint/persona_agent.json
 *   blueprint/persona_appearance.json
 *   preview/card.json
 *   assets/avatar.png          <- main portrait (real image, not base64)
 *   assets/outfit_*.png        <- outfit images if any
 */
export async function exportPersona(params) {
    const mode = params.mode || 'full';
    const url = `${params.backendUrl}/projects/${params.projectId}/persona/export?mode=${mode}`;
    const res = await fetch(url, { headers: authHeaders(params.apiKey) });
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        throw new Error(err.detail || `Export failed: ${res.status}`);
    }
    // Get filename from Content-Disposition header
    const disposition = res.headers.get('Content-Disposition') || '';
    const filenameMatch = disposition.match(/filename="?([^"]+)"?/);
    const filename = filenameMatch?.[1] || 'persona.hpersona';
    // Trigger download
    const blob = await res.blob();
    const blobUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = blobUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(blobUrl);
}
/**
 * Preview a .hpersona file — parse + dependency check, no project created.
 */
export async function previewPersonaPackage(params) {
    const formData = new FormData();
    formData.append('file', params.file);
    const headers = {};
    if (params.apiKey)
        headers['x-api-key'] = params.apiKey;
    const res = await fetch(`${params.backendUrl}/persona/import/preview`, {
        method: 'POST',
        headers,
        body: formData,
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        throw new Error(err.detail || `Preview failed: ${res.status}`);
    }
    return await res.json();
}
/**
 * Import a .hpersona file — creates a new persona project.
 */
export async function importPersonaPackage(params) {
    const formData = new FormData();
    formData.append('file', params.file);
    const headers = {};
    if (params.apiKey)
        headers['x-api-key'] = params.apiKey;
    const res = await fetch(`${params.backendUrl}/persona/import`, {
        method: 'POST',
        headers,
        body: formData,
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        throw new Error(err.detail || `Import failed: ${res.status}`);
    }
    return await res.json();
}
/**
 * Atomic import — install MCP servers + create persona project in one call.
 * This is the recommended flow for community gallery imports.
 */
export async function importPersonaAtomic(params) {
    const formData = new FormData();
    formData.append('file', params.file);
    const headers = {};
    if (params.apiKey)
        headers['x-api-key'] = params.apiKey;
    const autoInstall = params.autoInstallServers !== false;
    const qs = `auto_install_servers=${autoInstall}&force_reinstall=${!!params.forceReinstall}`;
    const res = await fetch(`${params.backendUrl}/persona/import/atomic?${qs}`, { method: 'POST', headers, body: formData });
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        throw new Error(err.detail || `Atomic import failed: ${res.status}`);
    }
    return await res.json();
}
/**
 * Resolve MCP dependencies for a .hpersona — returns an install plan.
 * Does NOT install anything.
 */
export async function resolvePersonaDeps(params) {
    const formData = new FormData();
    formData.append('file', params.file);
    const headers = {};
    if (params.apiKey)
        headers['x-api-key'] = params.apiKey;
    const res = await fetch(`${params.backendUrl}/persona/import/resolve-deps`, {
        method: 'POST',
        headers,
        body: formData,
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        throw new Error(err.detail || `Dependency check failed: ${res.status}`);
    }
    const data = await res.json();
    return data.plan;
}
/**
 * Auto-install missing MCP servers — clones from git, starts, registers in Forge.
 */
export async function installPersonaDeps(params) {
    const formData = new FormData();
    formData.append('file', params.file);
    const headers = {};
    if (params.apiKey)
        headers['x-api-key'] = params.apiKey;
    const res = await fetch(`${params.backendUrl}/persona/import/install-deps`, {
        method: 'POST',
        headers,
        body: formData,
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        throw new Error(err.detail || `Installation failed: ${res.status}`);
    }
    const data = await res.json();
    return data.plan;
}
/**
 * Commit an avatar to durable project storage.
 *
 * Supports three modes (provide exactly one):
 *   - sourceFilename: file already in UPLOAD_PATH (legacy)
 *   - sourceUrl: ComfyUI /view?... URL (downloads first, then commits)
 *   - auto: true — resolve from persona_appearance.sets (repair mode)
 */
export async function commitPersonaAvatar(params) {
    const body = {};
    if (params.auto) {
        body.auto = true;
    }
    else if (params.sourceUrl) {
        body.source_url = params.sourceUrl;
    }
    else if (params.sourceFilename) {
        body.source_filename = params.sourceFilename;
    }
    const res = await fetch(`${params.backendUrl}/projects/${params.projectId}/persona/avatar/commit`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            ...authHeaders(params.apiKey),
        },
        body: JSON.stringify(body),
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        throw new Error(err.detail || `Commit failed: ${res.status}`);
    }
    return await res.json();
}
