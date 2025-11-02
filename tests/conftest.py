"""Pytest fixtures for offline tool tests."""

from __future__ import annotations

import os
from typing import Any, Dict

import pytest

# Ensure placeholder keys exist so modules that read env on import succeed.
os.environ.setdefault("GOOGLE_MAPS_API_KEY", "test-maps-key")
os.environ.setdefault("GOOGLE_API_KEY", "test-google-key")
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("AMADEUS_API_KEY", "test-amadeus-key")
os.environ.setdefault("AMADEUS_API_SECRET", "test-amadeus-secret")
os.environ.setdefault("RAPIDAPI_KEY", "x" * 40)


class FakeResponse:
    """Lightweight stand-in for httpx.Response used in patched requests."""

    def __init__(self, payload: Dict[str, Any], status_code: int = 200, headers: Dict[str, str] | None = None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = ""

    def json(self) -> Dict[str, Any]:
        return self._payload


@pytest.fixture
def fake_response():
    """Factory that returns FakeResponse objects."""

    def _factory(payload: Dict[str, Any], status_code: int = 200, headers: Dict[str, str] | None = None) -> FakeResponse:
        return FakeResponse(payload, status_code=status_code, headers=headers)

    return _factory

    