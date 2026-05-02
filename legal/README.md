# Legal & Compliance (Open-Source Governance)

This folder is the policy baseline for HomePilot as an **open-source project** that can be run online.

## Purpose
- Keep official/community deployments aligned with law and platform rules.
- Turn policy into concrete engineering and moderation controls.
- Provide audit-ready traceability.

## Operator Responsibility
Operators of public instances are responsible for compliance with applicable laws, data protection requirements, and platform rules in their jurisdiction.

## Folder Structure

### Public-facing policies
- `terms-of-service.md` (project usage terms)
- `privacy-policy.md`
- `acceptable-use-policy.md`
- `ai-disclosure.md`
- `cookie-policy.md`

### Internal operating specs
- `compliance/content-rules.md`
- `compliance/ai-behavior-spec.md`
- `compliance/moderation-spec.md`
- `compliance/age-policy.md`

### Traceability
- `mapping/legal-to-product.md`

## Rules for Maintainers
1. Safe mode remains the default profile.
2. Optional mature mode cannot weaken hard legal blocks.
3. No configuration or plugin may disable hard-deny categories (minors, non-consensual, exploitative content).
4. Stricter instance policies are allowed; weaker ones are not.
5. Policy changes must update mapping, increment `policy_version`, and maintain changelog evidence.
