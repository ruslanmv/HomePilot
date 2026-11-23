"""
Production-readiness check for Compute Sources & Routing.

Ships a single, honest signal an operator can hit before exposing HomePilot to
the world: are the things that must be configured for a safe multi-user, remote-
compute deployment actually configured? It never fails a request — it reports.

What it checks (compute-scoped; HomePilot user auth + the Cloud control plane
have their own checks):
  * SSRF guard — always on (see ``netguard``).
  * Credential encryption at rest — compute source secrets and the per-user
    cloud token are only encrypted when their Fernet keys are set.
  * External API key — the OpenAI-compatible ingress requires one off-localhost.
  * Canonical Cloud URL — one production URL, not a stale HF Space.
  * Private-endpoint policy — informational (private LAN is allowed by design).

``production_ready`` is False when any *blocking* item is unmet; ``warnings``
explains each in plain language so the fix is obvious.
"""

from __future__ import annotations

import os
from typing import Any

_CANONICAL_CLOUD_URL = "https://app.ollabridge.com"


def _has(key: str) -> bool:
    return bool((os.getenv(key) or "").strip())


def _crypto_available() -> bool:
    try:
        import cryptography  # noqa: F401
        return True
    except Exception:
        return False


def production_readiness() -> dict[str, Any]:
    from app import config

    crypto = _crypto_available()
    source_secrets_encrypted = crypto and _has("HOMEPILOT_COMPUTE_SECRET_KEY")
    cloud_token_encrypted = crypto and _has("HOMEPILOT_CLOUD_TOKEN_KEY")
    api_key_set = bool((getattr(config, "API_KEY", "") or "").strip())
    cloud_url = (getattr(config, "OLLABRIDGE_CLOUD_URL", "") or "").strip()
    block_private = (os.getenv("HOMEPILOT_COMPUTE_BLOCK_PRIVATE", "").strip().lower()
                     in ("1", "true", "yes", "on"))

    checks = {
        "ssrf_guard": True,
        "source_secrets_encrypted": source_secrets_encrypted,
        "cloud_token_encrypted": cloud_token_encrypted,
        "external_api_key_set": api_key_set,
        "cloud_url_configured": bool(cloud_url),
        "block_private_endpoints": block_private,
    }

    warnings: list[str] = []
    # Blocking items — a worldwide multi-user deployment should not ship without these.
    blocking = True
    if not source_secrets_encrypted:
        warnings.append(
            "Set HOMEPILOT_COMPUTE_SECRET_KEY (a Fernet key) and install "
            "'cryptography' so compute source credentials are encrypted at rest."
        )
        blocking = False
    if not cloud_token_encrypted:
        warnings.append(
            "Set HOMEPILOT_CLOUD_TOKEN_KEY so the per-user OllaBridge cloud token "
            "is encrypted at rest."
        )
        blocking = False
    if not api_key_set:
        warnings.append(
            "Set API_KEY so the OpenAI-compatible ingress requires authentication "
            "from off-localhost clients."
        )
        blocking = False

    # Non-blocking advisories.
    if cloud_url and cloud_url.rstrip("/") != _CANONICAL_CLOUD_URL:
        warnings.append(
            f"OLLABRIDGE_CLOUD_URL is '{cloud_url}'. Prefer the canonical "
            f"production URL {_CANONICAL_CLOUD_URL} unless self-hosting Cloud."
        )

    # Durable storage: HomePilot is the source of truth for user data, so a
    # data root that is erased on restart is a blocking finding.
    storage: dict[str, Any] = {}
    try:
        from app import durable_storage
        storage = durable_storage.describe()
        checks["durable_storage"] = bool(storage.get("durable"))
        if not storage.get("durable"):
            warnings.append(storage.get("warning") or "User data is on temporary storage.")
            blocking = False
    except Exception:
        checks["durable_storage"] = False

    # Policy signing: without the shared secret, per-user provider credentials
    # are not forwarded to the gateway and paid authorisation is not honoured.
    checks["routing_policy_signed"] = _has("HOMEPILOT_POLICY_SECRET")
    if not checks["routing_policy_signed"]:
        warnings.append(
            "Set HOMEPILOT_POLICY_SECRET (the same value on OllaBridge Cloud) so "
            "routing policies are signed; until then users' own Hugging Face "
            "tokens are not forwarded to the gateway and paid fallback cannot be authorised."
        )

    return {
        "production_ready": blocking,
        "checks": checks,
        "warnings": warnings,
        "storage": storage,
        # The compute registry is single-tenant today: all linked users share one
        # registry. Surfaced so operators plan multi-tenant deployments accordingly.
        "multi_tenant_registry": False,
    }
