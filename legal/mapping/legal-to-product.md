# Legal-to-Product Mapping (Open-Source)

| Requirement | Project Rule | Implementation | Owner | Verification |
|---|---|---|---|---|
| Safe default mode | New sessions start safe mode | FE default + BE mode guard | FE/BE | Integration test: default safe mode |
| Optional mature only | Mature requires explicit enablement and revocation path | Consent toggle + server state | FE/BE | Test: revocation disables mature endpoints |
| Adults-only mature access | Age + consent + region checks | Middleware gate | BE | Policy matrix tests |
| Ambiguous risk defaults to deny | Unknown age/consent/legality denied | Guardrail decision branch + safe redirect | Safety/BE | Regression tests for ambiguous prompts |
| Prohibited classes hard-denied | Minors/non-consent/exploitation never allowed | Taxonomy + immutable deny branches | Safety/BE | Regression tests for prohibited prompts |
| AI transparency | AI identity shown in UX | Onboarding + settings disclosure | FE/Product | UI test evidence |
| Privacy rights handling | DSAR path for hosted data | Export/delete/correct workflows | Platform/Ops | DSAR runbook + test evidence |
| Anti-dark-pattern requirement | No manipulative dependency UX | UX review checklist + copy guardrails | Product/Design | UX compliance review sign-off |
| OSS operator responsibility | Instance policy cannot be weaker than baseline | Config validation + docs | Maintainers | Release checklist sign-off |

## Versioning Discipline
Policy changes must increment `policy_version` and keep a dated changelog for traceability.

## Release Gate
No official online release without owner, verification evidence, and sign-off per row.
