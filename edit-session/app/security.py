"""
Security module for edit-session service.

Provides:
- API key authentication
- Rate limiting (token bucket algorithm)
- SSRF protection for image URLs
"""

import time
from urllib.parse import urlparse
from fastapi import Header, HTTPException, Request
from .config import settings


class TokenBucket:
    """
    Simple in-memory token bucket rate limiter.

    This is a best-effort, per-process rate limiter. For production
    multi-instance deployments, use Redis-based rate limiting.
    """

    def __init__(self, rps: float, burst: int):
        """
        Initialize token bucket.

        Args:
            rps: Requests per second (refill rate)
            burst: Maximum tokens (burst capacity)
        """
        self.rps = max(rps, 0.1)
        self.burst = max(burst, 1)
        self.tokens: dict[str, float] = {}
        self.updated: dict[str, float] = {}

    def allow(self, key: str) -> bool:
        """
        Check if a request is allowed for the given key.

        Args:
            key: Unique identifier (typically IP address)

        Returns:
            True if request is allowed, False if rate limited
        """
        now = time.time()
        last = self.updated.get(key, now)

        # Refill tokens based on elapsed time
        current = self.tokens.get(key, float(self.burst))
        current = min(float(self.burst), current + (now - last) * self.rps)

        self.updated[key] = now

        if current >= 1.0:
            self.tokens[key] = current - 1.0
            return True

        self.tokens[key] = current
        return False

    def cleanup_old_entries(self, max_age_seconds: int = 3600) -> None:
        """
        Remove stale entries to prevent memory bloat.

        Should be called periodically in production.
        """
        now = time.time()
        stale_keys = [
            k for k, v in self.updated.items()
            if now - v > max_age_seconds
        ]
        for k in stale_keys:
            self.tokens.pop(k, None)
            self.updated.pop(k, None)


# Global rate limiter instance
bucket = TokenBucket(settings.RATE_LIMIT_RPS, settings.RATE_LIMIT_BURST)


def require_api_key(x_api_key: str | None) -> None:
    """
    Validate API key if required by configuration.

    Args:
        x_api_key: API key from request header

    Raises:
        HTTPException: 401 if API key is invalid
    """
    if settings.EDIT_SESSION_API_KEY and x_api_key != settings.EDIT_SESSION_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


async def enforce_security(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    """
    FastAPI dependency that enforces authentication and rate limiting.

    Args:
        request: FastAPI request object
        x_api_key: API key from X-API-Key header

    Raises:
        HTTPException: 401 for invalid API key, 429 for rate limit exceeded
    """
    # Check API key authentication
    require_api_key(x_api_key)

    # Apply rate limiting per IP (best effort)
    ip = request.client.host if request.client else "unknown"
    if not bucket.allow(ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")


def _allowed_hosts_set() -> set[str]:
    """
    Parse allowed external hosts from configuration.

    Returns:
        Set of lowercase hostnames that are allowed for external images
    """
    hosts: set[str] = set()
    if settings.ALLOWED_EXTERNAL_IMAGE_HOSTS.strip():
        for h in settings.ALLOWED_EXTERNAL_IMAGE_HOSTS.split(","):
            h = h.strip().lower()
            if h:
                hosts.add(h)
    return hosts


def validate_select_url(image_url: str, home_pilot_base_url: str) -> None:
    """
    Validate that an image URL is safe to use (SSRF protection).

    By default, only allows URLs hosted on the HomePilot backend.
    Additional hosts can be allowed via ALLOWED_EXTERNAL_IMAGE_HOSTS.

    Args:
        image_url: URL to validate
        home_pilot_base_url: HomePilot backend base URL

    Raises:
        HTTPException: 400 if URL is invalid or host not allowed
    """
    # Allow relative /files/... paths from the local backend
    # These are safe as they reference files in the backend's upload directory
    if image_url.startswith('/files/'):
        return

    try:
        parsed = urlparse(image_url)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image_url")

    # Only allow HTTP(S) URLs
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Invalid URL scheme")

    host = (parsed.hostname or "").lower()
    if not host:
        raise HTTPException(status_code=400, detail="Invalid URL host")

    allowed = _allowed_hosts_set()

    # Always allow HomePilot host
    hp = urlparse(home_pilot_base_url)
    hp_host = (hp.hostname or "").lower()

    if host == hp_host:
        return

    # Allow localhost variants for development
    localhost_variants = {"localhost", "127.0.0.1", "0.0.0.0"}
    if host in localhost_variants and hp_host in localhost_variants:
        return

    # Allow explicit external hosts if configured
    if host in allowed:
        return

    raise HTTPException(status_code=400, detail="image_url host not allowed")
