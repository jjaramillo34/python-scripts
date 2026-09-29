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


@pytest.fixture
def fake_ddgs(monkeypatch):
    """Fake DDGS that records calls and returns address-flavored images and news."""
    calls = []

    class FakeDDGS:
        def images(self, **kwargs):
            calls.append(("images", kwargs))
            return [
                {
                    "image": "https://example.com/265.jpg",
                    "title": "NEW YORK | 265 South St. | 73 floors",
                    "thumbnail": "https://example.com/265-thumb.jpg",
                    "url": "https://example.com/265-south-street",
                    "width": "1200",
                    "height": "800",
                },
                {
                    "image": "https://example.com/40-broad.jpg",
                    "title": "40 Broad St, New York, NY 10004",
                    "thumbnail": "https://example.com/40-thumb.jpg",
                    "url": "https://example.com/40-broad",
                    "width": 640,
                    "height": 480,
                },
            ]

        def news(self, **kwargs):
            calls.append(("news", kwargs))
            return [
                {
                    "date": "2026-08-30T14:00:00+00:00",
                    "title": "Two Bridges tower tops out",
                    "body": "The tower at 265 South Street rises over the Lower East Side.",
                    "url": "https://news.example.com/two-bridges",
                    "image": "https://news.example.com/img.jpg",
                    "source": "Example News",
                },
                {
                    "date": "2026-08-29T10:00:00+00:00",
                    "title": "Leases are the news in Manhattan",
                    "body": "Office demand keeps climbing downtown.",
                    "url": "https://news.example.com/leases",
                    "image": "",
                    "source": "Example News",
                },
            ]

    monkeypatch.setattr(api, "DDGS", FakeDDGS)
    return calls
