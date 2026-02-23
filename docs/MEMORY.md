# Persona Memory System

<p align="center">
  <strong>How HomePilot personas remember, forget, and grow</strong>
</p>

HomePilot gives every persona a **persistent memory** that survives across sessions.
Two memory engines are available — choose the one that fits your persona's purpose,
and switch anytime from Settings or during `.hpersona` import.

---

## At a glance: Adaptive vs Basic

<p align="center">
  <img src="../assets/memory-adaptive-vs-basic.svg"
       alt="Adaptive Memory vs Basic Memory comparison"
       width="820" />
</p>

| | Adaptive Memory | Basic Memory |
|---|---|---|
| **Internal name** | V2 engine | V1 engine |
| **Philosophy** | Brain-inspired — learns, forgets, evolves | Deterministic — explicit, auditable, strict |
| **Memory structure** | Three-tier hierarchy (Working → Semantic → Pinned) | Flat key-value store |
| **Decay** | Exponential: `A(t) = s · e^(-t/τ)` | No decay (TTL-based expiry only) |
| **Reinforcement** | Accessed memories grow stronger | Access count tracked, no strength change |
| **Consolidation** | Short-term → long-term promotion (sleep cycles) | N/A |
| **Pruning** | Automatic below activation threshold | TTL expiry + per-category caps |
| **Dedup** | Hash-based | Jaccard similarity (threshold 0.85) |
| **Best for** | Companion, Assistant, Partner, Custom | Secretary, Enterprise, Finance |
| **User-facing label** | *Adaptive Memory* | *Basic Memory* |

> **Switching:** You can change memory mode at any time from **Settings → Memory Mode**.
> The underlying `persona_memory` table is shared — both engines read/write to it safely.

---

## Adaptive Memory (V2) — brain-inspired

Adaptive Memory mimics how human memory works: important things stick,
unused things fade, and sleep consolidates the day's events.

### Memory hierarchy

<p align="center">
  <img src="../assets/memory-hierarchy.svg"
       alt="Memory hierarchy: Pinned → Semantic → Working"
       width="720" />
</p>

| Tier | Symbol | Decay τ | Description |
|------|--------|---------|-------------|
| **Pinned** | P | ∞ (never) | User-approved "core memories" — name, birthday, boundaries. Never auto-pruned. |
| **Semantic** | S | ~30 days | Stable facts and preferences. Slow decay, prunable when stale. |
| **Working** | W | ~6 hours | Short-lived context from the current conversation. Fast decay. |
| **Anchor** | A | — | Persona identity kernel (role, voice, rules). Injected from profile, never learned. |

### Decay and reinforcement

<p align="center">
  <img src="../assets/memory-decay-reinforcement.svg"
       alt="Exponential decay curves and reinforcement staircase"
       width="820" />
</p>

**Decay** — Every memory's activation fades over time following an exponential curve:

```
A(t) = strength · e^(-t / τ)
```

- Working memories (τ = 6h) fade within a day.
- Semantic memories (τ = 30d) fade over a month.
- Pinned memories never decay.

**Reinforcement** — When a memory is accessed or confirmed, its strength increases:

```
strength ← 1 - (1 - strength) · e^(-η)
```

- User confirms a fact: `η = 0.25` (strong boost)
- AI infers from context: `η = 0.05` (gentle boost)
- Strength saturates at 1.0 — diminishing returns prevent runaway scores.

**Consolidation** — A background "sleep cycle" promotes working memories to semantic when:

1. Repeated at least 2 times
2. Importance score ≥ 0.45
3. Current activation ≥ 0.25

**Pruning** — Semantic memories with activation < 0.05 *and* importance < 0.25 are forgotten automatically. This keeps the memory store lean and relevant.

### Configuration

```python
# memory_v2.py — V2Config defaults
tau_working          = 6 hours
tau_semantic         = 30 days
eta_user_confirmed   = 0.25
eta_inferred         = 0.05
consolidate_min_repeats    = 2
consolidate_min_importance = 0.45
prune_activation_thresh    = 0.05
prune_importance_thresh    = 0.25
top_pinned           = 4   # injected into prompt
top_semantic          = 8
top_working           = 1
```

### Retrieval budget

Each voice/chat turn injects at most **13 memories** into the system prompt:

| Tier | Slots | Selection |
|------|-------|-----------|
| Pinned | 4 | Highest strength first |
| Semantic | 8 | Highest activation × importance |
| Working | 1 | Most recent |

This keeps the context footprint small (~200-500 tokens) while surfacing the most relevant knowledge.

---

## Basic Memory (V1) — deterministic

Basic Memory is a flat, auditable key-value store designed for personas that need
predictability over personality: executive secretaries, finance assistants,
compliance bots.

### Key design

- **UPSERT by (project_id, category, key)** — "latest wins", no duplicates.
- **Bounded**: max ~200 entries per persona (configurable per category).
- **Explicit**: nothing is stored unless the AI (or user) explicitly triggers a memory save.
- **Auditable**: every entry has `source_type`, `confidence`, `access_count`, and `last_access_at`.

### Categories

| Category | TTL | Cap | Purpose |
|----------|-----|-----|---------|
| `fact` | Forever | 50 | User facts: name, job, location |
| `preference` | Forever | 40 | Likes/dislikes: favorite food, music |
| `important_date` | Forever | 20 | Birthdays, anniversaries, deadlines |
| `emotion_pattern` | 90 days | 15 | How user typically feels |
| `milestone` | Forever | 15 | Relationship milestones |
| `boundary` | Forever | 10 | User-set boundaries: tone, topics to avoid |
| `summary` | 30 days | 5 | Auto-updated relationship summary |

**Total cap**: 200 entries across all categories.

### Maintenance routines

Basic Memory runs three maintenance passes (manually or on a schedule):

1. **TTL expiry** — Delete entries older than their category's time-to-live.
2. **Per-category cap** — If a category exceeds its limit, evict the oldest non-pinned entries.
3. **Total cap** — If total entries exceed 200, evict the oldest non-pinned entries globally.

**Pinned entries** (`is_pinned = 1`) are exempt from all eviction.

### Near-duplicate detection

On every upsert, V1 checks existing entries in the same category for
near-identical values using Jaccard similarity on tokenized text:

```python
# Jaccard threshold = 0.85 (conservative: very high overlap required)
tokens_a = set(re.findall(r"[a-z0-9]{3,}", normalize(existing)))
tokens_b = set(re.findall(r"[a-z0-9]{3,}", normalize(new_value)))
jaccard = len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
```

If a near-duplicate is found, the existing entry is **reinforced** (access count +1)
instead of creating a redundant row.

### API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/persona/memory/maintenance` | Run TTL + cap cleanup for a persona |
| `GET` | `/persona/memory/stats` | Current memory usage and cap info |

---

## Shared infrastructure

Both engines share the `persona_memory` SQLite table. V2 adds optional columns
(`tier`, `activation`, `importance`, `repeat_count`, `content_hash`)
that are silently ignored by V1 queries. V1 adds `is_pinned` and `expires_at`,
which are compatible with V2's pin concept.

```
persona_memory
├── id, project_id, category, key, value       ← V1 core
├── confidence, source_session, source_type     ← V1 metadata
├── access_count, last_access_at               ← shared
├── is_pinned, expires_at                      ← V1 hardening
└── tier, activation, importance, repeat_count  ← V2 hierarchy
    content_hash
```

**Golden rule: ADDITIVE ONLY** — both engines extend the same table without
breaking each other. You can switch from Adaptive to Basic (or vice versa)
at any time without data loss.

---

## Context injection

Both engines produce a compact context block (~200-500 tokens) that is injected
into the system prompt on every turn:

```
WHAT YOU REMEMBER ABOUT THE USER (long-term memory):
  Facts:
    - name: Alex
    - job: Software engineer at Acme Corp
  Preferences:
    - coffee: Likes oat milk lattes
  Boundaries (respect these):
    - politics: Prefers not to discuss
```

This gives the persona natural awareness of the user without bloating context.

---

## `.hpersona` portability

When you export a persona as a `.hpersona` file, the **memory mode** is included
in the manifest:

```json
{
  "memory_mode": "adaptive",
  "package_version": 2,
  "schema_version": 2,
  ...
}
```

On import, the preview screen shows the persona's memory mode and lets you
switch it before installing — so you can import someone's "companion" persona
but run it in Basic mode if you prefer deterministic behavior.

---

## Profile Awareness vs Long-Term Memory

HomePilot has **two distinct systems** that help the AI know who you are:

### User Profile (always active)

Your **user profile** (set in Profile & Integrations) is injected into every conversation —
plain chat, persona chat, and agent chat. No setup needed. When you set your
display name, birthday, pronouns, or preferences, every AI conversation will see them.

| Profile field | Available in chat? |
|---|---|
| Display name / preferred name | Yes — always |
| Birthday and calculated age | Yes — always |
| Pronouns | Yes — always |
| Preferred tone, affection level | Yes — always |
| Likes, dislikes, boundaries | Yes — always |

**How to use:** Go to **Profile & Integrations → Profile tab**, fill in your name and
birthday, click **Save All**. The next chat message you send will include your profile
in the system prompt.

### Long-Term Memory (per-persona, opt-in)

**Memory** is a separate system that learns *new things about you from conversation* and
remembers them across sessions. It is available **only inside persona projects** with
memory mode set to `adaptive` or `basic`.

| Feature | Plain chat | Persona (memory=off) | Persona (memory=adaptive) | Persona (memory=basic) |
|---|---|---|---|---|
| Profile awareness (name, birthday) | Yes | Yes | Yes | Yes |
| Learns facts from conversation | No | No | Yes | Yes |
| Remembers across sessions | No | No | Yes | Yes |
| Decay and reinforcement | No | No | Yes | No |

**How to enable:** Create a persona → set Memory Mode to *Adaptive* or *Basic* in the
persona settings → chat inside that persona's conversation. The persona will learn
about you over time and remember facts, preferences, and patterns across sessions.

> **Key takeaway:** You do not need memory enabled for the AI to know your name.
> Your profile is always injected. Memory adds the ability to *accumulate knowledge
> over time* through conversation.

---

## Quick reference

| Question | Answer |
|----------|--------|
| **Does the AI know my name in plain chat?** | Yes — your user profile is always injected when you are logged in. |
| **Which memory engine should I choose?** | Adaptive for human-feeling personas; Basic for business/enterprise. |
| **Can I switch later?** | Yes — Settings → Memory Mode. No data is lost. |
| **Are memories portable?** | Yes — `.hpersona` export includes memory mode in the manifest. |
| **How many memories per persona?** | Up to 200 (Basic cap) or unbounded-with-pruning (Adaptive). |
| **Does memory affect voice?** | No — persona identity (role, tone, rules) is immutable. Memory only stores facts *about the user*. |
| **Where is data stored?** | Local SQLite database. Nothing leaves your machine. |
