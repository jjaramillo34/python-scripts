import api

ADDRESS = "265 South Street Manhattan NY 10004"


def test_news_requires_api_key(client):
    assert client.get("/api/news", params={"query": "sun"}).status_code == 401
    assert client.post("/api/news", json={"query": "sun"}).status_code == 401


def test_news_basic_query(client, auth_headers, fake_ddgs):
    response = client.get(
        "/api/news",
        params={"query": "sun", "timelimit": "m", "max_results": 5},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert body["strict"] is False
    assert body["articles"][0]["domain"] == "news.example.com"
    assert body["articles"][0]["position"] == 1
    category, kwargs = fake_ddgs[0]
    assert category == "news"
    assert kwargs["query"] == "sun"
    assert kwargs["timelimit"] == "m"
    assert kwargs["max_results"] == 5


def test_news_address_is_precise(client, auth_headers, fake_ddgs):
    response = client.post(
        "/api/news",
        json={"address": ADDRESS, "max_results": 10},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["effective_query"] == '"265 South Street" Manhattan NY'
    assert body["address"]["zip_code"] == "10004"
    assert body["strict"] is True
    assert body["count"] == 1
    assert body["filtered_out"] == 1
    assert "265 South Street" in body["articles"][0]["body"]
    # Strict mode over-fetches so filtering can still fill max_results.
    assert fake_ddgs[0][1]["max_results"] == 30


def test_news_address_with_strict_off_keeps_everything(client, auth_headers, fake_ddgs):
    response = client.get(
        "/api/news",
        params={"address": ADDRESS, "strict": "false"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["count"] == 2


def test_news_validates_params(client, auth_headers, fake_ddgs):
    assert client.get("/api/news", headers=auth_headers).status_code == 422
    assert client.get("/api/news", params={"query": "x", "timelimit": "z"}, headers=auth_headers).status_code == 422
    assert client.get("/api/news", params={"query": "x", "backend": "google"}, headers=auth_headers).status_code == 422
    assert client.get("/api/news", params={"address": "South Street"}, headers=auth_headers).status_code == 422


def test_images_address_filters_and_prefers_bing(client, auth_headers, fake_ddgs):
    response = client.get("/api/search", params={"address": ADDRESS}, headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["filtered_out"] == 1
    assert body["images"][0]["url"] == "https://example.com/265.jpg"
    assert body["images"][0]["dimensions"] == {"width": 1200, "height": 800}
    assert fake_ddgs[0][1]["backend"] == "bing,duckduckgo"


def test_image_filters_force_duckduckgo(client, auth_headers, fake_ddgs):
    client.get("/api/search", params={"query": "butterfly", "color": "Monochrome"}, headers=auth_headers)
    client.get("/api/search", params={"query": "butterfly", "timelimit": "m", "backend": "bing"}, headers=auth_headers)
    client.get("/api/search", params={"query": "butterfly"}, headers=auth_headers)
    assert [kwargs["backend"] for _, kwargs in fake_ddgs] == ["duckduckgo", "duckduckgo", "auto"]


def test_images_strict_quoted_phrase(client, auth_headers, fake_ddgs):
    response = client.post(
        "/api/search",
        json={"query": '"265 South Street"', "strict": True},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["count"] == 1


def test_no_results_is_empty_not_error(client, auth_headers, monkeypatch):
    class EmptyDDGS:
        def news(self, **kwargs):
            raise Exception("No results found.")

    monkeypatch.setattr(api, "DDGS", EmptyDDGS)
    response = client.get("/api/news", params={"query": "zzzz"}, headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["count"] == 0


def test_news_is_rate_limited(client, auth_headers, fake_ddgs, monkeypatch):
    monkeypatch.setattr(api, "_search_limiter", api.SlidingWindowLimiter(1, 60))
    assert client.get("/api/news", params={"query": "x"}, headers=auth_headers).status_code == 200
    assert client.get("/api/search", params={"query": "x"}, headers=auth_headers).status_code == 429


def test_openapi_secures_news(client):
    spec = client.get("/openapi.json").json()
    assert spec["paths"]["/api/news"]["get"]["security"] == [{"ApiKeyAuth": []}]
    assert "NewsResponse" in spec["components"]["schemas"]
