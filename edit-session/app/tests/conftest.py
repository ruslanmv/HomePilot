"""
Pytest configuration and shared fixtures.
"""

import pytest


@pytest.fixture(autouse=True)
def reset_settings():
    """Reset settings to defaults before each test."""
    from app import config

    # Store original values
    original_api_key = config.settings.EDIT_SESSION_API_KEY

    # Disable API key requirement for tests
    config.settings.EDIT_SESSION_API_KEY = None

    yield

    # Restore original values
    config.settings.EDIT_SESSION_API_KEY = original_api_key
