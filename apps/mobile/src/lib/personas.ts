// MB4 — voice companion picker. Reuses the backend persona registry
// (GET /api/personalities) so the list is the single source of truth shared with
// web. Best-effort: returns [] when the backend has no persona API (e.g. a
// compute-only backend), so the picker simply hides.
import { getHttp } from './client';

export interface Persona {
  id: string;
  label: string;
  category: string;
}

export async function listPersonas(): Promise<Persona[]> {
  try {
    const all = await getHttp().get<Persona[]>('/api/personalities');
    return Array.isArray(all) ? all : [];
  } catch {
    return [];
  }
}
