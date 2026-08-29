import os

TEST_API_KEY = "ci-test-api-key-16+"


def _configure_test_env() -> None:
    """Pin env before `api` loads so a local .env cannot leak into tests."""
    os.environ["API_KEY"] = TEST_API_KEY
    os.environ["API_KEYS"] = ""
    os.environ["ENVIRONMENT"] = "development"
    os.environ["ENABLE_DOCS"] = "true"
    os.environ["ALLOWED_HOSTS"] = ""
    os.environ["ALLOWED_ORIGINS"] = ""
    os.environ["TRUST_PROXY"] = "false"
    os.environ["RATE_LIMIT_SEARCH_PER_MINUTE"] = "100"
    os.environ["RATE_LIMIT_AUTH_FAIL_PER_MINUTE"] = "100"


_configure_test_env()

import api  # noqa: E402
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app():
    return api.app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def auth_headers():
    return {api.API_KEY_HEADER_NAME: TEST_API_KEY}


@pytest.fixture
def fake_images(monkeypatch):
    class FakeDDGS:
        def images(self, **kwargs):
            return [
                {
                    "image": "https://example.com/butterfly.jpg",
                    "title": "Butterfly",
                    "thumbnail": "https://example.com/thumb.jpg",
                    "url": "https://example.com/page",
                    "width": 800,
                    "height": 600,
                }
            ]

    monkeypatch.setattr(api, "DDGS", FakeDDGS)
