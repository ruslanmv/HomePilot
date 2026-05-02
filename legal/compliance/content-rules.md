# Content Rules Spec (Open-Source Baseline)

## Default Mode Policy
- Safe companion mode is default for all official deployments.
- Mature mode is optional and cannot disable hard legal blocks.
- No configuration or plugin may disable hard-deny categories.

## Taxonomy
- `ALLOWED_COMPANION`
- `ALLOWED_ROMANCE`
- `SOFT_SUGGESTIVE`
- `EXPLICIT_SEXUAL` (blocked in safe mode; restricted if mature mode enabled)
- `MINOR_SEXUAL` (always deny)
- `NON_CONSENSUAL_SEXUAL` (always deny)
- `EXPLOITATIVE_COERCION` (always deny)

## Edge Policy
- Ambiguous age => deny and safe-redirect.
- Ambiguous consent => deny and safe-redirect.
- If age, consent, or legality cannot be confidently determined, default to denial and safe redirection.

## Safe Fallback Requirement
Blocked outputs must return a safe, policy-aligned response instead of empty/error states.

## Decision Contract
- `decision`: allow | warn | block | escalate
- `reason_code`: machine-readable identifier
- `policy_version`: policy version used (must increment on policy changes)
