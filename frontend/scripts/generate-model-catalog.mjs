/**
 * One catalog (batch V7).
 *
 * `backend/app/model_catalog_data.json` is the source of truth for every model HomePilot knows
 * how to offer. This script projects it into `src/generated/modelCatalog.ts`, which the UI uses
 * as its offline fallback when `/model-catalog` cannot be reached.
 *
 * ## Why this exists
 *
 * There used to be two lists: the backend's JSON, and a hand-maintained copy of it inside
 * `Models.tsx`. They had drifted 43 field differences apart across 94 shared entries, and in two
 * directions that both hurt:
 *
 *   * the frontend offered `internvl3:8b` and `smolvlm2:latest`, which the backend had never
 *     heard of — a person could pick a vision model the server could not classify;
 *   * the frontend's fallback was missing every OpenAI, Claude and watsonx chat model, so the
 *     model list *changed* depending on whether the backend had answered yet.
 *
 * Two lists maintained by hand will always end up here. One list and a generator cannot.
 *
 * ## Contract
 *
 * Run before build (`prebuild`) and checked by `modelCatalog.generated.test.ts`, which
 * regenerates in memory and fails if the committed file has drifted. That test is the only thing
 * that keeps the two from separating again, so it is not optional and it is not skippable.
 *
 * Usage:
 *   node scripts/generate-model-catalog.mjs           # write
 *   node scripts/generate-model-catalog.mjs --check    # exit 1 if the file is stale
 */

import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
export const SOURCE = resolve(here, '../../backend/app/model_catalog_data.json');
export const TARGET = resolve(here, '../src/generated/modelCatalog.ts');

/**
 * Fields the UI reads. Everything else in the JSON — `context_window`, `_comment`, provider
 * notes — is backend business and is left there rather than shipped to every browser.
 */
const KEEP = [
    'id',
    'label',
    'description',
    'recommended',
    'recommended_nsfw',
    'recommended_expert',
    'expert_hint',
    'protected',
    'nsfw',
    'size_gb',
    'resolution',
    'frames',
    'civitai_url',
    'civitai_version_id',
    'install',
    'provides_nodes',
    'requires',
    // V7. Optional, and populated for nothing yet: what a vision model can actually take.
    // V8's bench set is what fills it in, entry by entry, from measurement rather than from
    // a datasheet — the same discipline that keeps V5's multi-image set empty.
    'vision_input',
];

function project(entry) {
    const out = {};
    for (const key of KEEP) {
        if (entry[key] !== undefined) out[key] = entry[key];
    }
    return out;
}

export function build(source) {
    const catalog = {};
    for (const [provider, kinds] of Object.entries(source.providers || {})) {
        const projected = {};
        for (const [kind, entries] of Object.entries(kinds || {})) {
            if (!Array.isArray(entries)) continue;
            projected[kind] = entries.filter((e) => e && e.id).map(project);
        }
        catalog[provider] = projected;
    }
    return catalog;
}

export function render(source) {
    const catalog = build(source);
    const count = Object.values(catalog).reduce(
        (total, kinds) => total + Object.values(kinds).reduce((n, list) => n + list.length, 0),
        0,
    );
    return `// GENERATED FILE — DO NOT EDIT.
//
// Written by scripts/generate-model-catalog.mjs from backend/app/model_catalog_data.json,
// which is the single source of truth for HomePilot's model catalog (batch V7).
//
// To change what appears here, edit the backend JSON and run:
//     node scripts/generate-model-catalog.mjs
//
// \`modelCatalog.generated.test.ts\` fails if this file and the JSON have drifted apart. That
// test is what stops the two lists separating again, which is what happened to the hand-written
// copy this file replaced.
//
// Catalog version: ${JSON.stringify(source.version ?? 'unknown')}   Entries: ${count}

export type GeneratedCatalogEntry = {
    id: string;
    label?: string;
    description?: string;
    recommended?: boolean;
    recommended_nsfw?: boolean;
    recommended_expert?: boolean;
    expert_hint?: string;
    protected?: boolean;
    nsfw?: boolean;
    size_gb?: number;
    resolution?: string;
    frames?: number;
    civitai_url?: string;
    civitai_version_id?: string;
    install?: Record<string, unknown>;
    provides_nodes?: string[];
    requires?: unknown;
    /** What this vision model can take. Populated only where it has been measured (V8). */
    vision_input?: {
        max_long_edge?: number;
        max_megapixels?: number;
        preferred_mime?: string;
        supports_multiple_images?: boolean;
        strategy?: string;
    };
};

export const GENERATED_CATALOG_VERSION = ${JSON.stringify(source.version ?? 'unknown')};

export const GENERATED_CATALOGS: Record<string, Record<string, GeneratedCatalogEntry[]>> =
${JSON.stringify(catalog, null, 4)};

export default GENERATED_CATALOGS;
`;
}

function main() {
    if (!existsSync(SOURCE)) {
        console.error(`model catalog source not found: ${SOURCE}`);
        // Not fatal. A frontend-only checkout still has the committed generated file, and
        // failing the build over a missing backend would make the two halves of the repo
        // impossible to work on separately.
        process.exit(0);
    }
    const source = JSON.parse(readFileSync(SOURCE, 'utf8'));
    const rendered = render(source);
    const current = existsSync(TARGET) ? readFileSync(TARGET, 'utf8') : '';

    if (process.argv.includes('--check')) {
        if (current !== rendered) {
            console.error('src/generated/modelCatalog.ts is stale — run: node scripts/generate-model-catalog.mjs');
            process.exit(1);
        }
        console.log('model catalog is up to date');
        return;
    }
    if (current !== rendered) {
        writeFileSync(TARGET, rendered);
        console.log(`wrote ${TARGET}`);
    } else {
        console.log('model catalog already up to date');
    }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
    main();
}
