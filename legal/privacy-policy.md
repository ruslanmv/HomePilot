# Privacy Notice (Draft)

## 1. Scope
Applies to official hosted instances and explains how personal data is handled. Self-hosted operators should adapt this notice to their deployment.

## 2. Data Categories
- Account/auth data
- Conversation and generated media (see Local-First Default below)
- Moderation/safety metadata
- Security logs

### Local-First Default
HomePilot is local-first. By default, generation runs on hardware you control
and your conversation history, prompts, RAG documents, and persona memory stay
on your device — they are **not** sent to the cloud control plane. Cloud sync is
**metadata-only and opt-in** (e.g. model names, routing profiles, health
metrics). The canonical hosted Privacy Policy at `/privacy` on the OllaBridge
Cloud deployment is authoritative for hosted instances; this notice mirrors it.

## 3. Purpose and Legal Basis (GDPR)
- Service operation
- Security and abuse prevention
- Legal compliance
- Consent-based optional analytics (if used)

## 4. Data Sharing
- Limited to necessary processors (hosting, security, support), if any.
- No sale of personal data.

## 5. Retention
- Retention defined by data class and operational need.
- Delete/anonymize when no longer required.

## 6. Data Subject Rights
- Access, correction, deletion, export, restriction, objection.
- Provide DSAR channel and response timelines for hosted instances.
- Hosted instances on OllaBridge Cloud support **in-app account deletion**
  (`DELETE /v1/account`), which removes the user record and associated devices,
  tokens, jobs, sharing policies, API keys, usage metadata, and personal
  organization (GDPR erasure).

## 7. Security
- Encryption, least privilege, logging, and incident response.

## 8. Children
- Service is adult-focused (18+).

## 9. Contact
- Provide controller/operator contact for each hosted instance.
