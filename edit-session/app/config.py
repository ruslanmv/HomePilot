"""
Configuration module for edit-session service.

Uses pydantic-settings for environment-based configuration with sensible defaults.
"""

import os
import pathlib
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


# Detect if we're running in a Docker container
_IS_DOCKER = pathlib.Path("/.dockerenv").exists() or os.getenv("DOCKER_CONTAINER", "").lower() == "true"

# Default paths based on environment
if _IS_DOCKER:
    _DEFAULT_BACKEND_URL = "http://backend:8000"
    _DEFAULT_SQLITE_PATH = "/data/edit_sessions.sqlite"
    _DEFAULT_REDIS_URL = "redis://redis:6379/0"
else:
    # Local development: use relative paths
    _EDIT_SESSION_DIR = pathlib.Path(__file__).parent.parent  # edit-session/
    _DEFAULT_DATA_DIR = _EDIT_SESSION_DIR / "data"
    _DEFAULT_BACKEND_URL = "http://localhost:8000"
    _DEFAULT_SQLITE_PATH = str(_DEFAULT_DATA_DIR / "edit_sessions.sqlite")
    _DEFAULT_REDIS_URL = "redis://localhost:6379/0"


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    All settings can be overridden via environment variables.
    Example: EDIT_SESSION_API_KEY=mysecretkey
    """

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    # HomePilot backend connection
    HOME_PILOT_BASE_URL: str = Field(
        default=_DEFAULT_BACKEND_URL,
        description="Base URL of the HomePilot backend service"
    )
    HOME_PILOT_API_KEY: str | None = Field(
        default=None,
        description="API key for HomePilot backend (if required)"
    )

    # Sidecar security (optional but recommended for production)
    EDIT_SESSION_API_KEY: str | None = Field(
        default=None,
        description="API key required for this service's endpoints"
    )

    # Storage configuration
    STORE: str = Field(
        default="sqlite",
        description="Storage backend: 'sqlite' or 'redis'"
    )
    SQLITE_PATH: str = Field(
        default=_DEFAULT_SQLITE_PATH,
        description="Path to SQLite database file"
    )
    REDIS_URL: str = Field(
        default=_DEFAULT_REDIS_URL,
        description="Redis connection URL"
    )

    # Session management
    TTL_SECONDS: int = Field(
        default=60 * 60 * 24 * 7,  # 7 days
        description="Time-to-live for session data in seconds"
    )
    HISTORY_LIMIT: int = Field(
        default=10,
        description="Maximum number of images to keep in history per session"
    )

    # Upload constraints
    MAX_UPLOAD_MB: int = Field(
        default=20,
        description="Maximum upload file size in megabytes"
    )

    # SSRF protection: if empty, /select only allows HomePilot-hosted URLs
    ALLOWED_EXTERNAL_IMAGE_HOSTS: str = Field(
        default="",
        description="Comma-separated list of allowed external image hosts"
    )

    # Rate limiting (simple in-memory, best-effort)
    RATE_LIMIT_RPS: float = Field(
        default=3.0,
        description="Rate limit: requests per second per IP"
    )
    RATE_LIMIT_BURST: int = Field(
        default=10,
        description="Rate limit: burst capacity"
    )

    # Service metadata
    SERVICE_NAME: str = Field(
        default="edit-session",
        description="Service name for logging and health checks"
    )
    SERVICE_VERSION: str = Field(
        default="1.0.0",
        description="Service version"
    )


# Singleton settings instance
settings = Settings()
