/**
 * The two lists cannot separate again (batch V7).
 *
 * `backend/app/model_catalog_data.json` is the one catalog. `src/generated/modelCatalog.ts` is a
 * projection of it, committed so a frontend-only checkout still builds. This test regenerates the
 * projection in memory and fails if the committed file has drifted.
 *
 * It is the whole of V7's acceptance, and it is worth being blunt about why. Before this batch
 * there were two lists — the JSON and a hand-written copy in `Models.tsx` — and they had drifted
 * 43 field differences apart across 94 shared entries, in both directions: models the frontend
 * offered and the backend could not classify, and models the backend knew that the offline list
 * silently dropped. Nobody did that on purpose. It is what two hand-maintained lists do. Delete
 * this test and it happens again.
 */

import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

import { build, render, SOURCE, TARGET } from '../../scripts/generate-model-catalog.mjs';
import { GENERATED_CATALOGS } from './modelCatalog';

const source = JSON.parse(readFileSync(SOURCE, 'utf8'));

describe('the generated model catalog', () => {
    it('is exactly what the generator would write today', () => {
        // A diff here means somebody edited the JSON without regenerating, or edited the
        // generated file by hand. Both are fixed the same way:
        //     node scripts/generate-model-catalog.mjs
        expect(readFileSync(TARGET, 'utf8')).toBe(render(source));
    });

    it('carries every model the backend knows about', () => {
        const fromSource = new Set<string>();
        for (const kinds of Object.values(source.providers ?? {})) {
            for (const entries of Object.values(kinds as Record<string, unknown>)) {
                if (Array.isArray(entries)) {
                    for (const entry of entries) if (entry?.id) fromSource.add(entry.id);
                }
            }
        }
        const shipped = new Set<string>();
        for (const kinds of Object.values(GENERATED_CATALOGS)) {
            for (const entries of Object.values(kinds)) {
                for (const entry of entries) shipped.add(entry.id);
            }
        }
        expect([...fromSource].filter((id) => !shipped.has(id))).toEqual([]);
    });

    it('drops backend-only fields rather than shipping them to every browser', () => {
        // `context_window`, provider notes and the schema keys are the backend's business. The
        // projection is a deliberate subset, not a copy of the file.
        const entries = Object.values(GENERATED_CATALOGS).flatMap((kinds) =>
            Object.values(kinds).flat(),
        );
        expect(entries.length).toBeGreaterThan(100);
        expect(entries.some((entry) => 'context_window' in entry)).toBe(false);
    });

    it('still offers the vision models the hand-written list used to', () => {
        // These two were frontend-only before V7 — a person could pick a model the server had
        // never heard of. They are in the JSON now, so generating from it must not drop them.
        const multimodal = GENERATED_CATALOGS.ollama.multimodal.map((entry) => entry.id);
        expect(multimodal).toContain('internvl3:8b');
        expect(multimodal).toContain('smolvlm2:latest');
    });

    it('offers the chat models the hand-written list was missing', () => {
        // The clearest symptom of the drift: the offline list had no hosted providers at all,
        // so the models on screen changed once the backend answered.
        expect(GENERATED_CATALOGS.openai.chat.length).toBeGreaterThan(0);
        expect(GENERATED_CATALOGS.claude.chat.length).toBeGreaterThan(0);
        expect(GENERATED_CATALOGS.watsonx.chat.length).toBeGreaterThan(0);
    });

    it('keeps both kinds of ComfyUI addon', () => {
        // The two `addons` lists were disjoint: git-installed custom nodes on one side,
        // HuggingFace file downloads on the other. One catalog means the union.
        const addons = GENERATED_CATALOGS.comfyui.addons.map((entry) => entry.id);
        expect(addons).toContain('ComfyUI-VideoHelperSuite');
        expect(addons).toContain('t5xxl_fp16.safetensors');
    });

    it('projects an entry without inventing anything', () => {
        const projected = build({
            providers: {
                ollama: {
                    multimodal: [
                        { id: 'x:1b', label: 'X', context_window: 4096, _note: 'internal' },
                    ],
                },
            },
        });
        expect(projected.ollama.multimodal[0]).toEqual({ id: 'x:1b', label: 'X' });
    });

    it('passes vision_input through when an entry has one', () => {
        // Nothing has one yet — V8's bench set fills it in from measurement, the same discipline
        // that keeps V5's verified multi-image set empty. The seam is what ships here.
        const projected = build({
            providers: {
                ollama: {
                    multimodal: [{ id: 'y:7b', vision_input: { max_long_edge: 1024 } }],
                },
            },
        });
        expect(projected.ollama.multimodal[0].vision_input).toEqual({ max_long_edge: 1024 });
    });
});

describe('Models.tsx sources its fallback from the generated catalog', () => {
    // Without this, V7 is one regeneration away from being undone: somebody pastes a literal
    // back in, every other test still passes, and the two lists start drifting again from a
    // clean slate. The audit is on the source text because that is where the mistake would be.
    const source = readFileSync(resolve(dirname(TARGET), '../ui/Models.tsx'), 'utf8');

    it('imports it', () => {
        expect(source).toMatch(/import \{ GENERATED_CATALOGS \} from '\.\.\/generated\/modelCatalog'/);
    });

    it('and does not carry a catalog literal of its own', () => {
        const assignment = source.slice(source.indexOf('const FALLBACK_CATALOGS'));
        const body = assignment.slice(0, assignment.indexOf('\n\n'));
        expect(body).toContain('GENERATED_CATALOGS');
        expect(body).not.toMatch(/\bid:\s*'/);
    });
});
