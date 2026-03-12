"""Shared fixtures for the test suite."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide required env vars so Settings can be instantiated."""
    monkeypatch.setenv("CHATWOOT_BASE_URL", "http://localhost:3000")
    monkeypatch.setenv("CHATWOOT_API_TOKEN", "test-token")
    monkeypatch.setenv("CHATWOOT_ACCOUNT_IDS", "[1,2]")

    from app.config import get_settings
    get_settings.cache_clear()
