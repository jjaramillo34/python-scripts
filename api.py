"""
FastAPI application for DuckDuckGo Image Search API
Deploy to: Heroku, Railway, Render, Fly.io, or any Python hosting service
"""
from fastapi import FastAPI, HTTPException, Query, Request, Depends, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import APIKeyHeader
from ddgs import DDGS
from typing import List, Dict, Optional
from urllib.parse import urlparse
from threading import Lock
from starlette.middleware.base import BaseHTTPMiddleware
import hmac
import time
import os
from pydantic import BaseModel, Field, ConfigDict
from dotenv import load_dotenv

# Load environment variables from .env file (for local development)
load_dotenv()

# ---------------------------------------------------------------------------
# Security configuration (fail closed — no hardcoded secrets)
# ---------------------------------------------------------------------------
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").strip().lower()
API_KEY_HEADER_NAME = "X-API-Key"
API_KEY_MIN_LENGTH = 16
PLACEHOLDER_KEYS = {
    "secure_password_change_in_production",
    "your_secure_password_here",
    "changeme",
    "secret",
}

ENABLE_DOCS = os.getenv(
    "ENABLE_DOCS",
    "true" if ENVIRONMENT != "production" else "false",
).strip().lower() in {"1", "true", "yes"}

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("ALLOWED_HOSTS", "").split(",")
    if host.strip()
]
TRUST_PROXY = os.getenv(
    "TRUST_PROXY",
    "true" if ENVIRONMENT == "production" else "false",
).strip().lower() in {"1", "true", "yes"}

RATE_LIMIT_SEARCH_PER_MINUTE = int(os.getenv("RATE_LIMIT_SEARCH_PER_MINUTE", "30"))
RATE_LIMIT_AUTH_FAIL_PER_MINUTE = int(os.getenv("RATE_LIMIT_AUTH_FAIL_PER_MINUTE", "10"))


def _load_api_keys() -> tuple[str, ...]:
    """Load API keys from the environment. Refuse weak or missing keys."""
    keys: list[str] = []
    single = os.getenv("API_KEY", "").strip()
    extra = os.getenv("API_KEYS", "").strip()
    if single:
        keys.append(single)
    if extra:
        keys.extend(part.strip() for part in extra.split(",") if part.strip())

    unique_keys = tuple(dict.fromkeys(keys))
    if not unique_keys:
        raise RuntimeError(
            "API_KEY is not set. Add a strong key to your environment or .env file "
            "(at least 16 characters). Example: "
            "python -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )
    for key in unique_keys:
        if key.lower() in PLACEHOLDER_KEYS or key.lower().startswith("your_"):
            raise RuntimeError(
                "Refusing to start with a placeholder API_KEY. Set a unique secret."
            )
        if len(key) < API_KEY_MIN_LENGTH:
            raise RuntimeError(
                f"API_KEY must be at least {API_KEY_MIN_LENGTH} characters."
            )
    return unique_keys


API_KEYS = _load_api_keys()


class SlidingWindowLimiter:
    """In-memory sliding-window limiter (per process)."""

    def __init__(self, max_hits: int, window_seconds: int):
        self.max_hits = max_hits
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = Lock()

    def _prune(self, key: str, now: float) -> list[float]:
        cutoff = now - self.window_seconds
        hits = [stamp for stamp in self._hits.get(key, []) if stamp > cutoff]
        if hits:
            self._hits[key] = hits
        else:
            self._hits.pop(key, None)
        return hits

    def is_blocked(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            return len(self._prune(key, now)) >= self.max_hits

    def hit(self, key: str) -> bool:
        """Record a hit. Returns True if the request is still allowed."""
        now = time.time()
        with self._lock:
            hits = self._prune(key, now)
            if len(hits) >= self.max_hits:
                return False
            hits.append(now)
            self._hits[key] = hits
            return True


_search_limiter = SlidingWindowLimiter(RATE_LIMIT_SEARCH_PER_MINUTE, 60)
_auth_fail_limiter = SlidingWindowLimiter(RATE_LIMIT_AUTH_FAIL_PER_MINUTE, 60)


def _client_ip(request: Request) -> str:
    if TRUST_PROXY:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _api_key_is_valid(provided: str) -> bool:
    """Constant-time compare against every configured key."""
    if not provided:
        return False
    matched = False
    for key in API_KEYS:
        if len(provided) == len(key) and hmac.compare_digest(provided, key):
            matched = True
    return matched


api_key_header = APIKeyHeader(name=API_KEY_HEADER_NAME, auto_error=False)


async def verify_api_key(
    request: Request,
    api_key_header_value: str = Security(api_key_header),
):
    """
    Require a valid API key via the X-API-Key header.
    Query-string keys are rejected so they cannot leak in logs or Referer headers.
    """
    client = _client_ip(request)
    if _auth_fail_limiter.is_blocked(client):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed authentication attempts. Try again later.",
            headers={"Retry-After": "60"},
        )

    provided = (api_key_header_value or "").strip()
    if not provided or not _api_key_is_valid(provided):
        _auth_fail_limiter.hit(client)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid API key required. Send it in the X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return True


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/api/search":
            if not _search_limiter.hit(_client_ip(request)):
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={"detail": "Too many requests. Try again later."},
                    headers={"Retry-After": "60"},
                )

        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response


OPENAPI_TAGS = [
    {
        "name": "Search",
        "description": "Image search. Requires the `X-API-Key` header. Use **Authorize** before Try it out.",
    },
    {
        "name": "Info",
        "description": "Public metadata about this API.",
    },
    {
        "name": "Health",
        "description": "Public liveness checks for load balancers.",
    },
]

app = FastAPI(
    title="DuckDuckGo Image Search API",
    summary="Search images with filters. Search routes require X-API-Key.",
    description="""
Search DuckDuckGo images with filters for size, color, type, layout, license, region, and time range.

## Authentication

1. Click **Authorize**
2. Paste your API key
3. Run any `/api/search` request

The key is sent as `X-API-Key`. Query-string keys are rejected.

`/`, `/health`, and `/api/info` stay public.

## Rate limits

- 30 search requests per minute per IP
- 10 failed authentication attempts per minute per IP

```bash
curl -H "X-API-Key: YOUR_API_KEY" \\
  "http://127.0.0.1:8000/api/search?query=butterfly&max_results=5"
```
    """,
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url="/openapi.json" if ENABLE_DOCS else None,
    openapi_tags=OPENAPI_TAGS,
    contact={
        "name": "API access",
        "email": "javier@privatediningpros.com",
    },
)

# Setup Jinja2 templates
templates = Jinja2Templates(directory="templates")

if ENABLE_DOCS:
    @app.get("/docs", include_in_schema=False)
    async def custom_docs(request: Request):
        return templates.TemplateResponse(
            request,
            "docs.html",
            {
                "title": "Image Search API — Docs",
                "openapi_url": app.openapi_url,
            },
        )

    @app.get("/redoc", include_in_schema=False)
    async def custom_redoc(request: Request):
        return templates.TemplateResponse(
            request,
            "redoc.html",
            {
                "title": "Image Search API — Reference",
                "openapi_url": app.openapi_url,
            },
        )

app.add_middleware(SecurityHeadersMiddleware)

if ALLOWED_HOSTS:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=[*ALLOWED_HOSTS, "localhost", "127.0.0.1"],
    )

# Browser clients on other origins are denied unless ALLOWED_ORIGINS is set.
if ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=[API_KEY_HEADER_NAME, "Content-Type", "Accept"],
    )

# Request model
class ImageSearchRequest(BaseModel):
    """Request model for image search"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "query": "butterfly",
                "max_results": 10,
                "region": "us-en",
                "safesearch": "off",
                "validate_images": False
            }
        }
    )
    
    query: str = Field(..., description="Search keywords")
    max_results: Optional[int] = Field(10, ge=1, le=100, description="Maximum number of results (1-100)")
    region: Optional[str] = Field("us-en", description="Region code: wt-wt (worldwide), us-en (US), uk-en (UK), es-es (Spain), fr-fr (France)")
    safesearch: Optional[str] = Field("off", description="Safe search level: off, moderate, on")
    timelimit: Optional[str] = Field(None, description="Time limit filter: d (day), w (week), m (month), y (year)")
    page: Optional[int] = Field(1, ge=1, le=10, description="Page number for pagination (1-10)")
    backend: Optional[str] = Field("auto", description="Backend to use: auto, api, html")
    size: Optional[str] = Field(None, description="Size filter: Small, Medium, Large, Wallpaper")
    color: Optional[str] = Field(None, description="Color filter: Monochrome, Red, Orange, Yellow, Green, Blue, Purple, Pink, Brown, Black, Gray, Teal, White")
    type_image: Optional[str] = Field(None, description="Type filter: Photo, Clipart, Gif, Transparent, Line")
    layout: Optional[str] = Field(None, description="Layout filter: Square, Tall, Wide")
    license_image: Optional[str] = Field(None, description="License filter: Public, Share, ShareCommercially, Modify, ModifyCommercially")
    validate_images: Optional[bool] = Field(False, description="Validate image URLs (slower but more reliable - checks if images are accessible)")


class ImageWebsite(BaseModel):
    url: str = ""
    title: str = ""
    name: str = ""


class ImageDimensions(BaseModel):
    width: int = 0
    height: int = 0


class ImageResult(BaseModel):
    url: str
    alt: str = ""
    thumbnail: str = ""
    title: str = ""
    source: str = "DuckDuckGo Search Images"
    website: ImageWebsite
    dimensions: ImageDimensions
    position: int


class SearchResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "images": [
                    {
                        "url": "https://example.com/image.jpg",
                        "alt": "Butterfly",
                        "thumbnail": "https://example.com/thumb.jpg",
                        "title": "Butterfly",
                        "source": "DuckDuckGo Search Images",
                        "website": {
                            "url": "https://example.com",
                            "title": "Example",
                            "name": "example.com",
                        },
                        "dimensions": {"width": 1920, "height": 1080},
                        "position": 1,
                    }
                ],
                "count": 1,
                "query": "butterfly",
                "max_results": 5,
            }
        }
    )
    images: List[ImageResult]
    count: int
    query: str
    max_results: Optional[int] = None


class ErrorMessage(BaseModel):
    detail: str


SEARCH_RESPONSES = {
    200: {"model": SearchResponse, "description": "Matching images"},
    401: {"model": ErrorMessage, "description": "Missing or invalid API key"},
    429: {"model": ErrorMessage, "description": "Rate limited"},
}


def search_with_retry(ddgs, search_params, max_retries=3, delay=2):
    """
    Search with retry logic to handle rate limiting and temporary errors.
    """
    for attempt in range(max_retries):
        try:
            results = list(ddgs.images(**search_params))
            return results, None
        except Exception as e:
            error_str = str(e)
            
            # Check if it's a rate limit error
            if "403" in error_str or "Ratelimit" in error_str or "rate limit" in error_str.lower():
                if attempt < max_retries - 1:
                    wait_time = delay * (attempt + 1)
                    time.sleep(wait_time)
                    continue
                else:
                    return None, "Rate limit exceeded. Please wait a few minutes before trying again."
            
            # Check if it's a temporary error
            if any(code in error_str for code in ["429", "503", "502"]):
                if attempt < max_retries - 1:
                    wait_time = delay * (attempt + 1)
                    time.sleep(wait_time)
                    continue
                else:
                    return None, "Service temporarily unavailable. Please try again later."
            
            return None, f"Search error: {error_str}"
    
    return None, "Maximum retries exceeded."

def validate_image_url(image_url: str, timeout: int = 5) -> bool:
    """
    Check if an image URL is valid and accessible.
    """
    import requests
    
    if not image_url or not image_url.startswith(('http://', 'https://')):
        return False
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    try:
        response = requests.head(image_url, headers=headers, timeout=timeout, allow_redirects=True)
        if response.status_code == 200:
            content_type = response.headers.get('Content-Type', '')
            if content_type.startswith('image/'):
                return True
        return False
    except Exception:
        return False

def format_image_results(results: List[Dict]) -> List[Dict]:
    """Format DuckDuckGo image results to match the desired structure"""
    formatted_results = []
    
    for idx, result in enumerate(results, start=1):
        website_url = result.get("url", "")
        website_name = ""
        try:
            if website_url:
                parsed = urlparse(website_url)
                website_name = parsed.netloc or parsed.path.split("/")[0] if parsed.path else ""
        except:
            website_name = website_url.split("/")[2] if len(website_url.split("/")) > 2 else website_url
        
        formatted_result = {
            "url": result.get("image", ""),
            "alt": result.get("title", ""),
            "thumbnail": result.get("thumbnail", ""),
            "title": result.get("title", ""),
            "source": "DuckDuckGo Search Images",
            "website": {
                "url": website_url,
                "title": result.get("title", ""),
                "name": website_name or "Unknown"
            },
            "dimensions": {
                "width": result.get("width", 0),
                "height": result.get("height", 0)
            },
            "position": idx
        }
        formatted_results.append(formatted_result)
    
    return formatted_results

@app.get("/", response_class=HTMLResponse, tags=["Info"], summary="Homepage")
async def root(request: Request):
    """
    API Homepage - Welcome page with API information and documentation links
    """
    # Get base URL from request
    base_url = str(request.base_url).rstrip('/')
    
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "base_url": base_url,
            "docs_enabled": ENABLE_DOCS,
            "version": "1.0.0",
        },
    )

@app.get("/api/info", tags=["Info"], summary="API metadata")
async def api_info():
    """Public JSON summary of endpoints and example calls."""
    return {
        "message": "DuckDuckGo Image Search API",
        "version": "1.0.0",
        "description": "A powerful REST API for searching images using DuckDuckGo",
        "docs": {
            "swagger_ui": "/docs",
            "redoc": "/redoc",
            "openapi_json": "/openapi.json",
            "homepage": "/"
        },
        "endpoints": {
            "search_get": {
                "url": "/api/search",
                "method": "GET",
                "description": "Search images with query parameters"
            },
            "search_post": {
                "url": "/api/search",
                "method": "POST",
                "description": "Search images with JSON body"
            },
            "health": {
                "url": "/health",
                "method": "GET",
                "description": "Health check endpoint"
            },
            "info": {
                "url": "/api/info",
                "method": "GET",
                "description": "API information (this endpoint)"
            }
        },
        "examples": {
            "get_request": "curl -H 'X-API-Key: YOUR_API_KEY' 'http://localhost:8000/api/search?query=butterfly&max_results=5'",
            "post_request": "curl -X POST 'http://localhost:8000/api/search' -H 'X-API-Key: YOUR_API_KEY' -H 'Content-Type: application/json' -d '{\"query\": \"butterfly\", \"max_results\": 5}'"
        }
    }

@app.get(
    "/api/search",
    tags=["Search"],
    summary="Search images",
    responses=SEARCH_RESPONSES,
    dependencies=[Depends(verify_api_key)],
)
async def search_images_get(
    query: str = Query(..., description="Search keywords (e.g., 'butterfly', 'sunset beach')", examples=["butterfly", "sunset beach"]),
    max_results: int = Query(10, ge=1, le=100, description="Maximum number of results to return (1-100)", examples=[10, 20, 50]),
    region: str = Query("us-en", description="Region code: wt-wt (worldwide), us-en (US), uk-en (UK), es-es (Spain), fr-fr (France)", examples=["us-en", "uk-en", "wt-wt"]),
    safesearch: str = Query("off", description="Safe search level: off, moderate, on", examples=["off", "moderate", "on"]),
    timelimit: Optional[str] = Query(None, description="Time limit filter: d (day), w (week), m (month), y (year)", examples=["d", "w", "m", "y"]),
    page: int = Query(1, ge=1, le=10, description="Page number for pagination (1-10)", examples=[1, 2, 3]),
    backend: str = Query("auto", description="Backend to use: auto, api, html", examples=["auto", "api", "html"]),
    size: Optional[str] = Query(None, description="Size filter: Small, Medium, Large, Wallpaper", examples=["Small", "Medium", "Large", "Wallpaper"]),
    color: Optional[str] = Query(None, description="Color filter: Monochrome, Red, Orange, Yellow, Green, Blue, Purple, Pink, Brown, Black, Gray, Teal, White", examples=["Red", "Blue", "Green"]),
    type_image: Optional[str] = Query(None, description="Type filter: Photo, Clipart, Gif, Transparent, Line", examples=["Photo", "Clipart", "Gif"]),
    layout: Optional[str] = Query(None, description="Layout filter: Square, Tall, Wide", examples=["Square", "Tall", "Wide"]),
    license_image: Optional[str] = Query(None, description="License filter: Public, Share, ShareCommercially, Modify, ModifyCommercially", examples=["Public", "Share"]),
    validate_images: bool = Query(False, description="Validate image URLs (slower but more reliable - checks if images are accessible)", examples=[True, False]),
):
    """
    Search images with query parameters. Authorize first so Swagger sends `X-API-Key`.

    All parameters except `query` are optional.
    """
    try:
        # Prepare search parameters
        search_params = {
            "query": query,
            "region": region,
            "safesearch": safesearch,
            "timelimit": timelimit,
            "page": page,
            "backend": backend,
            "size": size,
            "color": color,
            "type_image": type_image,
            "layout": layout,
            "license_image": license_image,
            "max_results": max_results,
        }
        
        # Remove None values
        search_params = {k: v for k, v in search_params.items() if v is not None}
        
        # Perform search
        ddgs = DDGS()
        raw_results, error_msg = search_with_retry(ddgs, search_params)
        
        if error_msg:
            raise HTTPException(status_code=429, detail=error_msg)
        
        if not raw_results:
            return JSONResponse(
                status_code=200,
                content={"images": [], "count": 0, "query": query}
            )
        
        # Format results
        formatted_results = format_image_results(raw_results)
        
        # Validate images if requested
        if validate_images:
            import requests
            valid_results = []
            for result in formatted_results:
                image_url = result.get("url") or result.get("thumbnail", "")
                if image_url and validate_image_url(image_url):
                    valid_results.append(result)
            formatted_results = valid_results
        
        return JSONResponse(
            status_code=200,
            content={
                "images": formatted_results,
                "count": len(formatted_results),
                "query": query,
                "max_results": max_results
            }
        )
        
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post(
    "/api/search",
    tags=["Search"],
    summary="Search images (JSON)",
    responses=SEARCH_RESPONSES,
    dependencies=[Depends(verify_api_key)],
)
async def search_images_post(request: ImageSearchRequest):
    """
    Same search as GET, with a JSON body. Authorize first so Swagger sends `X-API-Key`.
    """
    try:
        # Prepare search parameters
        search_params = {
            "query": request.query,
            "region": request.region,
            "safesearch": request.safesearch,
            "timelimit": request.timelimit,
            "page": request.page,
            "backend": request.backend,
            "size": request.size,
            "color": request.color,
            "type_image": request.type_image,
            "layout": request.layout,
            "license_image": request.license_image,
            "max_results": request.max_results,
        }
        
        # Remove None values
        search_params = {k: v for k, v in search_params.items() if v is not None}
        
        # Perform search
        ddgs = DDGS()
        raw_results, error_msg = search_with_retry(ddgs, search_params)
        
        if error_msg:
            raise HTTPException(status_code=429, detail=error_msg)
        
        if not raw_results:
            return JSONResponse(
                status_code=200,
                content={"images": [], "count": 0, "query": request.query}
            )
        
        # Format results
        formatted_results = format_image_results(raw_results)
        
        # Validate images if requested
        if request.validate_images:
            valid_results = []
            for result in formatted_results:
                image_url = result.get("url") or result.get("thumbnail", "")
                if image_url and validate_image_url(image_url):
                    valid_results.append(result)
            formatted_results = valid_results
        
        return JSONResponse(
            status_code=200,
            content={
                "images": formatted_results,
                "count": len(formatted_results),
                "query": request.query,
                "max_results": request.max_results
            }
        )
        
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/health", tags=["Health"], summary="Liveness")
async def health_check():
    """Public liveness check. Returns a simple status object."""
    return {
        "status": "healthy",
        "service": "DuckDuckGo Image Search API",
        "version": "1.0.0"
    }

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        summary=app.summary,
        description=app.description,
        routes=app.routes,
        tags=OPENAPI_TAGS,
        contact=app.contact,
    )
    schema["servers"] = [
        {"url": "/", "description": "This server"},
    ]
    schemes = schema.setdefault("components", {}).setdefault("securitySchemes", {})
    schemes.pop("APIKeyHeader", None)
    schemes["ApiKeyAuth"] = {
        "type": "apiKey",
        "in": "header",
        "name": API_KEY_HEADER_NAME,
        "description": "API key for /api/search. Send it in the X-API-Key header.",
    }
    search = schema.get("paths", {}).get("/api/search", {})
    for method in search.values():
        if isinstance(method, dict):
            method["security"] = [{"ApiKeyAuth": []}]
    schema["x-tagGroups"] = [
        {"name": "API", "tags": ["Search"]},
        {"name": "Status", "tags": ["Info", "Health"]},
    ]
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

