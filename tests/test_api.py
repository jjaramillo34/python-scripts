import api


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"


def test_api_info(client):
    response = client.get("/api/info")
    assert response.status_code == 200
    body = response.json()
    assert "endpoints" in body
    assert "X-API-Key" in body["examples"]["get_request"]


def test_homepage(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "X-API-Key" in response.text
    assert "Try it" in response.text


def test_docs_and_redoc(client):
    docs = client.get("/docs")
    redoc = client.get("/redoc")
    assert docs.status_code == 200
    assert redoc.status_code == 200
    assert "SwaggerUIBundle" in docs.text
    assert "Redoc.init" in redoc.text


def test_openapi_security_and_models(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    spec = response.json()
    schemes = spec["components"]["securitySchemes"]
    assert "ApiKeyAuth" in schemes
    assert schemes["ApiKeyAuth"]["name"] == "X-API-Key"
    assert spec["paths"]["/api/search"]["get"]["security"] == [{"ApiKeyAuth": []}]
    assert "SearchResponse" in spec["components"]["schemas"]
    assert spec.get("x-tagGroups")


def test_format_image_results():
    formatted = api.format_image_results(
        [
            {
                "image": "https://cdn.example.com/pic.jpg",
                "title": "A bird",
                "thumbnail": "https://cdn.example.com/t.jpg",
                "url": "https://example.com/article",
                "width": 1024,
                "height": 768,
            }
        ]
    )
    assert formatted[0]["url"] == "https://cdn.example.com/pic.jpg"
    assert formatted[0]["website"]["name"] == "example.com"
    assert formatted[0]["dimensions"] == {"width": 1024, "height": 768}
    assert formatted[0]["position"] == 1


def test_sliding_window_limiter():
    limiter = api.SlidingWindowLimiter(2, 60)
    assert limiter.hit("ip") is True
    assert limiter.hit("ip") is True
    assert limiter.hit("ip") is False
    assert limiter.is_blocked("ip") is True
    assert limiter.hit("other") is True
