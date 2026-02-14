/**
 * Personality Gating System
 *
 * Manages visibility and access to different personality types.
 * Handles 18+ content gating with explicit user opt-in.
 */

import { PERSONALITIES, PersonalityDef, PersonalityId } from './personalities';
import { PERSONALITY_CAPS, PersonalityCategory } from './personalityCaps';

// localStorage keys
export const LS_ADULT_ENABLED = 'homepilot_adult_content_enabled';
export const LS_ADULT_CONFIRMED = 'homepilot_adult_age_confirmed';
export const LS_PERSONAS_ENABLED = 'homepilot_voice_personas_enabled';
export const LS_PERSONA_CACHE = 'homepilot_voice_persona_cache';
export const LS_VOICE_LINKED = 'homepilot_voice_linked_to_project';

/**
 * Check if adult content is enabled
 */
export function isAdultContentEnabled(): boolean {
  if (typeof window === 'undefined') return false;
  return localStorage.getItem(LS_ADULT_ENABLED) === 'true';
}

/**
 * Check if user has confirmed they are 18+
 */
export function isAgeConfirmed(): boolean {
  if (typeof window === 'undefined') return false;
  return localStorage.getItem(LS_ADULT_CONFIRMED) === 'true';
}

/**
 * Enable adult content (requires age confirmation first)
 */
export function setAdultContentEnabled(enabled: boolean): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(LS_ADULT_ENABLED, String(enabled));
}

/**
 * Set age confirmation
 */
export function setAgeConfirmed(confirmed: boolean): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(LS_ADULT_CONFIRMED, String(confirmed));
  if (!confirmed) {
    // If age not confirmed, disable adult content
    setAdultContentEnabled(false);
  }
}

/**
 * Full check for adult content access
 */
export function canAccessAdultContent(): boolean {
  return isAgeConfirmed() && isAdultContentEnabled();
}

/**
 * Get enabled personalities based on current settings
 */
export function getEnabledPersonalities(): PersonalityDef[] {
  const adultAllowed = canAccessAdultContent();

  return PERSONALITIES.filter((p) => {
    // If personality is mature (18+), only show if adult content is allowed
    if (p.mature) {
      return adultAllowed;
    }
    return true;
  });
}

/**
 * Get personalities grouped by category
 */
export function getPersonalitiesByCategory(): Record<PersonalityCategory, PersonalityDef[]> {
  const enabled = getEnabledPersonalities();

  const grouped: Record<PersonalityCategory, PersonalityDef[]> = {
    general: [],
    kids: [],
    wellness: [],
    adult: [],
    personas: [],
  };

  enabled.forEach((p) => {
    const caps = PERSONALITY_CAPS[p.id as PersonalityId];
    const category: PersonalityCategory = caps?.category || 'general';
    grouped[category].push(p);
  });

  return grouped;
}

/**
 * Check if a specific personality is accessible
 */
export function isPersonalityAccessible(id: PersonalityId): boolean {
  const personality = PERSONALITIES.find((p) => p.id === id);
  if (!personality) return false;

  if (personality.mature) {
    return canAccessAdultContent();
  }

  return true;
}

/**
 * Get category label for UI
 */
export function getCategoryLabel(category: PersonalityCategory): string {
  const labels: Record<PersonalityCategory, string> = {
    general: 'General',
    kids: 'Kids & Family',
    wellness: 'Wellness',
    adult: '18+ Adult',
    personas: 'Personas',
  };
  return labels[category];
}

/**
 * Get category icon for UI
 */
export function getCategoryIcon(category: PersonalityCategory): string {
  const icons: Record<PersonalityCategory, string> = {
    general: 'sparkles',
    kids: 'stars',
    wellness: 'heart',
    adult: 'flame',
    personas: 'user',
  };
  return icons[category];
}

/**
 * Check if Personas in Voice is enabled
 */
export function isPersonasEnabled(): boolean {
  if (typeof window === 'undefined') return false;
  return localStorage.getItem(LS_PERSONAS_ENABLED) === 'true';
}

/**
 * Enable/disable Personas in Voice
 */
export function setPersonasEnabled(enabled: boolean): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(LS_PERSONAS_ENABLED, String(enabled));
}

/**
 * Check if Voice is linked to project (persistent mode)
 * When linked: backend handles persona (memory, RAG, tools, persistence)
 * When unlinked: client-side cache, fast, ephemeral
 */
export function isVoiceLinkedToProject(): boolean {
  if (typeof window === 'undefined') return false;
  return localStorage.getItem(LS_VOICE_LINKED) === 'true';
}

/**
 * Enable/disable Voice linked-to-project mode
 */
export function setVoiceLinkedToProject(linked: boolean): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(LS_VOICE_LINKED, String(linked));
}

/**
 * Get the project ID to send when voice is linked and a persona is selected.
 * Returns the persona's project ID if linked, undefined if unlinked.
 */
export function getVoiceLinkedProjectId(): string | undefined {
  if (!isVoiceLinkedToProject() || !isPersonasEnabled()) return undefined;
  const personalityId = localStorage.getItem('homepilot_personality_id') || '';
  if (!personalityId.startsWith('persona:')) return undefined;
  const projectId = personalityId.slice('persona:'.length);
  // Validate non-empty and looks like a UUID (project IDs are UUIDs)
  if (!projectId || !/^[0-9a-f-]{36}$/i.test(projectId)) return undefined;
  return projectId;
}
