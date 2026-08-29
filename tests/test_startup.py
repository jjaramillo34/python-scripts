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
