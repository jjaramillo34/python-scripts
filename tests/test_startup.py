import pytest

import api


def test_load_api_keys_requires_env(monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("API_KEYS", raising=False)
    with pytest.raises(RuntimeError, match="API_KEY is not set"):
        api._load_api_keys()


@pytest.mark.parametrize("key", ["changeme", "secret", "your_secure_password_here"])
def test_load_api_keys_rejects_placeholders(monkeypatch, key):
    monkeypatch.setenv("API_KEY", key)
    monkeypatch.delenv("API_KEYS", raising=False)
    with pytest.raises(RuntimeError, match="placeholder"):
        api._load_api_keys()


def test_load_api_keys_rejects_short_keys(monkeypatch):
    monkeypatch.setenv("API_KEY", "too-short")
    monkeypatch.delenv("API_KEYS", raising=False)
    with pytest.raises(RuntimeError, match="at least"):
        api._load_api_keys()


def test_load_api_keys_supports_rotation(monkeypatch):
    monkeypatch.setenv("API_KEY", "primary-key-16xxxx")
    monkeypatch.setenv("API_KEYS", "rotated-key-16xxxx, primary-key-16xxxx")
    keys = api._load_api_keys()
    assert keys == ("primary-key-16xxxx", "rotated-key-16xxxx")


def test_normalize_host_accepts_urls():
    assert api._normalize_host("https://www.example.com/docs") == "www.example.com"
    assert api._normalize_host("example.com") == "example.com"


def test_resolved_hosts_include_railway(monkeypatch):
    monkeypatch.setenv("ALLOWED_HOSTS", "example.com")
    monkeypatch.setenv("RAILWAY_PROJECT_ID", "proj_123")
    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "my-app.up.railway.app")
    hosts = api._resolved_allowed_hosts()
    assert "example.com" in hosts
    assert "my-app.up.railway.app" in hosts
    assert "*.up.railway.app" in hosts
    assert "localhost" in hosts


def test_resolved_hosts_empty_without_config(monkeypatch):
    monkeypatch.delenv("ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("RAILWAY_PROJECT_ID", raising=False)
    monkeypatch.delenv("RAILWAY_PUBLIC_DOMAIN", raising=False)
    monkeypatch.delenv("RAILWAY_STATIC_URL", raising=False)
    monkeypatch.delenv("RENDER_EXTERNAL_HOSTNAME", raising=False)
    assert api._resolved_allowed_hosts() == []
