# Age Policy (Open-Source Baseline)

## Principle
Mature capability is optional. If enabled, access must be adult-only, consented, and auditable.

## Baseline Tiers
- Tier 1: self-attestation
- Tier 2: token-based age verification
- Tier 3: higher assurance for higher-risk contexts

## Required Controls
- Server-side age + consent state
- Region-aware gating
- Re-verification triggers for suspicious use
- Minimize retained verification data

## Access Expression
`age_verified && consent_granted && region_allowed`
