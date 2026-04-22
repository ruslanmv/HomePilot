# Moderation Spec (Open-Source Operations)

## Required Layers
1. Input moderation
2. Intent moderation
3. Output moderation
4. User report + reviewer workflow

## Decisioning
- `allow`: compliant with active mode/policy
- `warn`: borderline content
- `block`: prohibited content
- `escalate`: repeat abuse / legal-risk severity

## Required Logs
- actor/session id (hashed/pseudonymous where possible)
- UTC timestamp
- decision + reason_code
- policy_version
- mode (safe/mature)
- content reference/hash (minimize personal data)

## Baseline Enforcement
- Repeated borderline or blocked attempts trigger temporary cooldowns before stronger enforcement.
- Warning/cooldown/suspension/ban policy
- Immediate hard block for minors/non-consent/exploitation classes
- Policy precedence over immersion quality

## Appeal Path
Users may request review of enforcement actions through a defined appeal channel where available.
