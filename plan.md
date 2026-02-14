# Plan: Add Personas to Voice Personality Selector

## Summary

Personas from the user's project library appear as a new **"Personas"** category section inside the existing Personality dropdown (PersonalityList.tsx). A single toggle in Voice Settings enables/disables them. No new screens, tabs, or navigation — purely additive to existing patterns.

## Architecture

**Data flow:**
```
GET /projects (frontend fetches on toggle-on)
  → filter project_type === 'persona'
  → map to PersonalityDef-compatible objects
  → inject into PersonalityList as a new "personas" category
  → selection stores persona project ID in localStorage
  → App.tsx reads it, builds voiceSystemPrompt from persona's system_prompt
  → backend receives voiceSystemPrompt (no project_id sent — privacy preserved)
```

Key design decisions:
- Personas are treated as **voice personalities** (prompt-only), NOT as full project contexts
- The previous privacy fix stays: `project_id` is never sent in voice mode
- Instead, the persona's `system_prompt` + `role` + `tone` are assembled into `voiceSystemPrompt` on the frontend, exactly like the existing "Custom" personality path
- This means zero backend changes needed

## Files to Modify (6 files, ~200 lines)

### 1. `frontend/src/ui/voice/personalityGating.ts` — Add personas toggle + category

- Add new localStorage key: `LS_PERSONAS_ENABLED = 'homepilot_voice_personas_enabled'`
- Add functions: `isPersonasEnabled()`, `setPersonasEnabled(bool)`
- Extend `PersonalityCategory` to include `'personas'`
- Add `getCategoryLabel('personas')` → `"Personas"`

### 2. `frontend/src/ui/voice/personalityCaps.ts` — Extend PersonalityCategory type

- Add `'personas'` to the `PersonalityCategory` union type

### 3. `frontend/src/ui/voice/personalities.ts` — Extend PersonalityDef for persona entries

- Widen `PersonalityId` type to accept `string` (for dynamic persona IDs like `persona:proj_abc123`)
- Add optional fields to `PersonalityDef`: `isPersona?: boolean`, `systemPrompt?: string`, `tone?: string`

### 4. `frontend/src/ui/voice/PersonalityList.tsx` — Render persona section

- Accept new optional prop: `personas: PersonalityDef[]`
- After the existing 4 categories, render a "Personas" section (if `personas.length > 0`)
- Uses User icon for persona items, shows persona label + tone
- Visual style: subtle purple/violet accent (distinct from orange 18+)

### 5. `frontend/src/ui/voice/SettingsModal.tsx` — Add "Enable Personas" toggle

- Add new toggle under Content Preferences, same pattern as the 18+ toggle
- Icon: `Users` from lucide-react
- Label: "Enable Personas" / "Use custom Personas as voice identities"
- Stores to `LS_PERSONAS_ENABLED`
- No age gate needed

### 6. `frontend/src/ui/App.tsx` — Handle persona selection in voice prompt assembly

- In the `voiceSystemPrompt` assembly block (~line 2318):
  - Check if `personalityId` starts with `persona:` prefix
  - If yes: read the cached persona data from localStorage (`homepilot_voice_persona_cache`)
  - Build voiceSystemPrompt from persona's `system_prompt`, `role`, and `tone`
  - The voice wrapper preamble stays the same

### 7. `frontend/src/ui/voice/VoiceSettingsPanel.tsx` — Fetch personas and pass to PersonalityList

- When `isPersonasEnabled()` is true, fetch persona projects from `/projects`
- Filter for `project_type === 'persona'`
- Map to `PersonalityDef[]` with `id: 'persona:<project_id>'`, `isPersona: true`
- Cache in localStorage for prompt assembly
- Pass to `<PersonalityList personas={...} />`

## Detailed Changes

### personalityGating.ts additions:

```typescript
export const LS_PERSONAS_ENABLED = 'homepilot_voice_personas_enabled';

export function isPersonasEnabled(): boolean {
  if (typeof window === 'undefined') return false;
  return localStorage.getItem(LS_PERSONAS_ENABLED) === 'true';
}

export function setPersonasEnabled(enabled: boolean): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(LS_PERSONAS_ENABLED, String(enabled));
}
```

### PersonalityList.tsx — new "Personas" section:

After the `(['general', 'wellness', 'kids', 'adult'])` map, add:

```tsx
{/* Persona section (from user's projects) */}
{personas.length > 0 && (
  <div className="mb-2">
    <div className="flex items-center gap-2 px-2 py-1.5 text-[10px] font-bold uppercase tracking-wider text-violet-400/70">
      <User size={12} />
      <span>Personas</span>
    </div>
    <div className="flex flex-col gap-0.5">
      {personas.map((p) => { /* same item rendering pattern */ })}
    </div>
  </div>
)}
```

### App.tsx — voice prompt for persona selection:

```typescript
if (personalityId?.startsWith('persona:')) {
  // Persona from user's project library
  const cached = localStorage.getItem('homepilot_voice_persona_cache');
  if (cached) {
    const personas = JSON.parse(cached);
    const persona = personas.find((p: any) => `persona:${p.id}` === personalityId);
    if (persona) {
      const name = persona.label || 'Assistant';
      const role = persona.role || '';
      const tone = persona.tone || 'warm';
      const prompt = persona.system_prompt || '';
      personalityPrompt = prompt
        || `You are ${name}${role ? ', ' + role : ''}. Your tone is ${tone}.`;
    }
  }
}
```

### SettingsModal.tsx — new toggle:

Same visual pattern as the 18+ toggle, placed right below it:

```tsx
<div className="flex items-center justify-between p-3 rounded-[12px] bg-white/5">
  <div className="flex items-center gap-3">
    <Users size={16} className="text-violet-400/70" />
    <div>
      <span className="text-[13px] text-white/80 block">Enable Personas</span>
      <span className="text-[10px] text-white/40">Use custom Personas as voice identities</span>
    </div>
  </div>
  {/* toggle button */}
</div>
```

## What stays the same

- Voice mode still never sends `project_id` (privacy fix preserved)
- Existing 15 built-in personalities unchanged
- 18+ gating unaffected
- Backend requires zero changes
- Voice settings panel layout/structure unchanged
- Custom personality instructions path unchanged

## Testing

- Toggle OFF (default): No personas visible — behavior identical to before
- Toggle ON with no persona projects: Empty section hidden, no visual change
- Toggle ON with personas: "Personas" section appears at bottom of personality list
- Select a persona: Bottom pill shows `Ara · Sarah`, voice uses persona's system_prompt
- Switch back to built-in personality: Works normally
- Exit voice and re-enter: Last selection remembered via localStorage
