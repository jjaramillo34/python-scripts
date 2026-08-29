import api
from tests.conftest import TEST_API_KEY


def test_search_requires_api_key(client):
    response = client.get("/api/search", params={"query": "butterfly"})
    assert response.status_code == 401
    assert "X-API-Key" in response.json()["detail"]


def test_search_rejects_query_string_key(client):
    response = client.get(
        "/api/search",
        params={"query": "butterfly", "api_key": TEST_API_KEY},
    )
    assert response.status_code == 401


def test_search_rejects_wrong_key(client):
    response = client.get(
        "/api/search",
        params={"query": "butterfly"},
        headers={api.API_KEY_HEADER_NAME: "definitely-not-the-real-key"},
    )
    assert response.status_code == 401


def test_search_accepts_valid_key(client, auth_headers, fake_images):
    response = client.get(
        "/api/search",
        params={"query": "butterfly", "max_results": 1},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["query"] == "butterfly"
    assert body["images"][0]["url"] == "https://example.com/butterfly.jpg"


def test_search_post_requires_api_key(client):
    response = client.post("/api/search", json={"query": "butterfly"})
    assert response.status_code == 401


def test_search_post_accepts_valid_key(client, auth_headers, fake_images):
    response = client.post(
        "/api/search",
        json={"query": "sunset", "max_results": 1},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["query"] == "sunset"


def test_auth_failures_are_rate_limited(client, monkeypatch):
    monkeypatch.setattr(api, "_auth_fail_limiter", api.SlidingWindowLimiter(2, 60))
    client.get("/api/search", params={"query": "x"})
    client.get("/api/search", params={"query": "x"})
    blocked = client.get("/api/search", params={"query": "x"})
    assert blocked.status_code == 429


def test_search_is_rate_limited(client, auth_headers, fake_images, monkeypatch):
    monkeypatch.setattr(api, "_search_limiter", api.SlidingWindowLimiter(1, 60))
    first = client.get("/api/search", params={"query": "x"}, headers=auth_headers)
    second = client.get("/api/search", params={"query": "x"}, headers=auth_headers)
    assert first.status_code == 200
    assert second.status_code == 429


def test_api_key_compare_is_exact():
    assert api._api_key_is_valid(TEST_API_KEY) is True
    assert api._api_key_is_valid("") is False
    assert api._api_key_is_valid("wrong-key-value-xx") is False
