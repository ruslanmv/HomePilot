# .hpersona v3 Schema Extensions — Superintelligent Spatial Personas

## Overview

Schema v3 is a **purely additive** extension of the v2 `.hpersona` format.
No existing v2 fields are changed or removed.  Older HomePilot versions that
only understand v2 will ignore the new files gracefully.

## New Optional Files (inside the .hpersona ZIP)

All files below are **optional**.  A v3 package that omits them behaves
identically to a v2 package.

### `blueprint/cognitive_profile.json`
Defines **how the persona thinks** — reasoning mode, memory strategy,
initiative level, workflow orchestration, and safety policies.

### `blueprint/embodiment_profile.json`
Defines **how the persona moves** — gestures, expressions, look-at behavior,
personal distance, posture, sitting/standing, hand interactions.

### `blueprint/vr_profile.json`
Defines **how the persona behaves in VR/AR** — spawn distance, following,
navigation, locomotion, comfort limits, XR preferences.

### `blueprint/voice_profile.json`
Defines **how the persona sounds** — voice ID, pitch, rate, pause style,
emotional modulation, and provider preferences.

### `blueprint/relationship_model.json`
Defines **the relational dynamic** — relationship type, emotional continuity,
initiative balance, boundary rules, and interaction style.

### `dependencies/workflow.json`
Declares **orchestrated workflow graphs** the persona can execute (LangGraph
references, step definitions, confirmation policies).

## Manifest Changes

The `manifest.json` file gets one new optional field:

```json
{
  "schema_version": 3,
  "contents": {
    "has_cognitive_profile": true,
    "has_embodiment_profile": true,
    "has_vr_profile": true,
    "has_voice_profile": true,
    "has_relationship_model": true,
    "has_workflow": true
  }
}
```

All new `has_*` fields default to `false` if absent.

## Backward Compatibility

- v2 importers skip unknown files inside the ZIP — safe.
- v3 importers check `schema_version` and load new files if present.
- The `package_version` field stays at 2 (ZIP layout unchanged).
  Only `schema_version` advances to 3.

## Extended Package Layout

```
manifest.json
blueprint/
  persona_agent.json          (v2 — unchanged)
  persona_appearance.json     (v2 — unchanged)
  agentic.json                (v2 — unchanged)
  cognitive_profile.json      (v3 — NEW, optional)
  embodiment_profile.json     (v3 — NEW, optional)
  vr_profile.json             (v3 — NEW, optional)
  voice_profile.json          (v3 — NEW, optional)
  relationship_model.json     (v3 — NEW, optional)
dependencies/
  tools.json                  (v2 — unchanged)
  mcp_servers.json            (v2 — unchanged)
  a2a_agents.json             (v2 — unchanged)
  models.json                 (v2 — unchanged)
  suite.json                  (v2 — unchanged)
  workflow.json               (v3 — NEW, optional)
assets/
  avatar_<stem>.<ext>
  thumb_avatar_<stem>.webp
preview/
  card.json
```
