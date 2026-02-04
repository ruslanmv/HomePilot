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
  };

  enabled.forEach((p) => {
    const caps = PERSONALITY_CAPS[p.id];
    const category = caps?.category || 'general';
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
  };
  return icons[category];
}
