"""
FastAPI application for DuckDuckGo Image & News Search API
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
from typing import List, Dict, Literal, Optional
from urllib.parse import urlparse
from threading import Lock
from starlette.middleware.base import BaseHTTPMiddleware
import hmac
import time
import os
from pydantic import BaseModel, Field, ConfigDict
from dotenv import load_dotenv
from precision import build_address_query, matches_all, parse_us_address, required_phrases

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


def _normalize_host(value: str) -> str:
    """Accept a hostname or full URL and return just the hostname."""
    value = (value or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = f"https://{value}"
    return (urlparse(value).hostname or "").lower()


def _platform_hosts() -> list[str]:
    """Hosts injected by Railway, Render, and similar platforms."""
    hosts: list[str] = []
    for key in ("RAILWAY_PUBLIC_DOMAIN", "RENDER_EXTERNAL_HOSTNAME"):
        host = _normalize_host(os.getenv(key, ""))
        if host:
            hosts.append(host)
    static_url = os.getenv("RAILWAY_STATIC_URL", "")
    static_host = _normalize_host(static_url)
    if static_host:
        hosts.append(static_host)
    if os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_PROJECT_ID"):
        hosts.extend(["*.up.railway.app", "*.railway.app", "*.railway.internal"])
    return hosts


def _resolved_allowed_hosts() -> list[str]:
    configured = [
        _normalize_host(part)
        for part in os.getenv("ALLOWED_HOSTS", "").split(",")
    ]
    configured = [host for host in configured if host]
    extra = _platform_hosts()
    if not configured and not extra:
        return []
    return list(dict.fromkeys([*configured, *extra, "localhost", "127.0.0.1"]))


ALLOWED_HOSTS = _resolved_allowed_hosts()
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


def public_base_url(request: Request) -> str:
    """Public origin for docs examples. Prefer forwarded proto/host behind Railway."""
    proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",")[0].strip()
    scheme = proto or request.url.scheme
    netloc = host or request.url.netloc
    if ENVIRONMENT == "production" and scheme == "http":
        scheme = "https"
    return f"{scheme}://{netloc}".rstrip("/")


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


SEARCH_PATHS = {"/api/search", "/api/news"}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in SEARCH_PATHS:
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
        "name": "News",
        "description": "News search. Requires the `X-API-Key` header. Use `address` for precise US address matches.",
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
    title="DuckDuckGo Image & News Search API",
    summary="Search images and news, with precise US address matching. Search routes require X-API-Key.",
    description="""
Search DuckDuckGo images with filters for size, color, type, layout, license, region, and time range,
and search news from Bing, DuckDuckGo, and Yahoo.

## Precise address search

Pass `address` (e.g. `265 South Street Manhattan NY 10004`) instead of, or alongside, `query`.
The street line is quoted and results that don't mention it (as "265 South St" or
"265 South Street") are dropped. The response shows `effective_query`, the parsed
`address`, and how many results were `filtered_out`.

## Authentication

1. Click **Authorize**
2. Paste your API key
3. Run any `/api/search` or `/api/news` request

The key is sent as `X-API-Key`. Query-string keys are rejected.

`/`, `/health`, and `/api/info` stay public.

## Rate limits

- 30 search requests per minute per IP (images and news combined)
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
                "title": "Image & News Search API — Docs",
                "openapi_url": app.openapi_url,
            },
        )

    @app.get("/redoc", include_in_schema=False)
    async def custom_redoc(request: Request):
        return templates.TemplateResponse(
            request,
            "redoc.html",
            {
                "title": "Image & News Search API — Reference",
                "openapi_url": app.openapi_url,
            },
        )

app.add_middleware(SecurityHeadersMiddleware)

if ALLOWED_HOSTS:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)

# Browser clients on other origins are denied unless ALLOWED_ORIGINS is set.
if ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=[API_KEY_HEADER_NAME, "Content-Type", "Accept"],
    )

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------
SafeSearch = Literal["on", "moderate", "off"]
TimeLimit = Literal["d", "w", "m", "y"]
NewsBackend = Literal["auto", "bing", "duckduckgo", "yahoo"]

QUERY_DESCRIPTION = "Search keywords. Wrap words in double quotes to require that exact phrase."
ADDRESS_DESCRIPTION = (
    "US street address, e.g. '265 South Street Manhattan NY 10004'. The street line is "
    "quoted and results must mention it. Combine with `query` to add topic words "
    "(e.g. query='construction')."
)
STRICT_DESCRIPTION = (
    "Drop results that do not mention the address or every quoted phrase in the query. "
    "Defaults to on when `address` is set, off otherwise."
)


class ImageSearchRequest(BaseModel):
    """Request model for image search"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "address": "265 South Street Manhattan NY 10004",
                "max_results": 10,
                "region": "us-en",
                "safesearch": "off",
                "validate_images": False
            }
        }
    )

    query: Optional[str] = Field(None, description=QUERY_DESCRIPTION)
    address: Optional[str] = Field(None, description=ADDRESS_DESCRIPTION)
    strict: Optional[bool] = Field(None, description=STRICT_DESCRIPTION)
    max_results: Optional[int] = Field(10, ge=1, le=100, description="Maximum number of results (1-100)")
    region: Optional[str] = Field("us-en", description="Region code: wt-wt (worldwide), us-en (US), uk-en (UK), es-es (Spain), fr-fr (France)")
    safesearch: Optional[str] = Field("off", description="Safe search level: off, moderate, on")
    timelimit: Optional[str] = Field(None, description="Time limit filter: d (day), w (week), m (month), y (year)")
    page: Optional[int] = Field(1, ge=1, le=10, description="Page number for pagination (1-10)")
    backend: Optional[str] = Field("auto", description="Backend: auto, bing, duckduckgo. Filters and timelimit force duckduckgo (bing ignores them).")
    size: Optional[str] = Field(None, description="Size filter: Small, Medium, Large, Wallpaper")
    color: Optional[str] = Field(None, description="Color filter: Monochrome, Red, Orange, Yellow, Green, Blue, Purple, Pink, Brown, Black, Gray, Teal, White")
    type_image: Optional[str] = Field(None, description="Type filter: Photo, Clipart, Gif, Transparent, Line")
    layout: Optional[str] = Field(None, description="Layout filter: Square, Tall, Wide")
    license_image: Optional[str] = Field(None, description="License filter: Public, Share, ShareCommercially, Modify, ModifyCommercially")
    validate_images: Optional[bool] = Field(False, description="Validate image URLs (slower but more reliable - checks if images are accessible)")


class NewsSearchRequest(BaseModel):
    """Request model for news search"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "address": "265 South Street Manhattan NY 10004",
                "max_results": 10,
                "region": "us-en",
                "timelimit": "y",
            }
        }
    )

    query: Optional[str] = Field(None, description=QUERY_DESCRIPTION)
    address: Optional[str] = Field(None, description=ADDRESS_DESCRIPTION)
    strict: Optional[bool] = Field(None, description=STRICT_DESCRIPTION)
    max_results: int = Field(10, ge=1, le=100, description="Maximum number of results (1-100)")
    region: str = Field("us-en", pattern=r"^[a-z]{2}-[a-z]{2}$", description="Region code, e.g. us-en, uk-en, wt-wt")
    safesearch: SafeSearch = Field("off", description="Safe search level: off, moderate, on")
    timelimit: Optional[TimeLimit] = Field(None, description="Time limit: d (day), w (week), m (month), y (year)")
    page: int = Field(1, ge=1, le=10, description="Page number for pagination (1-10)")
    backend: NewsBackend = Field("auto", description="Backend: auto, bing, duckduckgo, yahoo. auto falls back across engines.")


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


class ParsedAddressModel(BaseModel):
    number: str
    street: str
    street_line: str
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None


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
                "effective_query": "butterfly",
                "address": None,
                "strict": False,
                "filtered_out": 0,
                "max_results": 5,
            }
        }
    )
    images: List[ImageResult]
    count: int
    query: str
    effective_query: str
    address: Optional[ParsedAddressModel] = None
    strict: bool = False
    filtered_out: int = 0
    max_results: Optional[int] = None


class NewsArticle(BaseModel):
    title: str = ""
    body: str = ""
    url: str = ""
    image: str = ""
    source: str = ""
    date: str = ""
    domain: str = ""
    position: int


class NewsResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "articles": [
                    {
                        "title": "Two Bridges tower at 265 South Street tops out",
                        "body": "The 70-story tower at 265 South Street on the Lower East Side...",
                        "url": "https://example.com/news/265-south-street",
                        "image": "https://example.com/news/265.jpg",
                        "source": "Example News",
                        "date": "2026-08-30T14:00:00+00:00",
                        "domain": "example.com",
                        "position": 1,
                    }
                ],
                "count": 1,
                "query": "265 South Street Manhattan NY 10004",
                "effective_query": '"265 South Street" Manhattan NY',
                "address": {
                    "number": "265",
                    "street": "South Street",
                    "street_line": "265 South Street",
                    "city": "Manhattan",
                    "state": "NY",
                    "zip_code": "10004",
                },
                "strict": True,
                "filtered_out": 4,
                "max_results": 10,
            }
        }
    )
    articles: List[NewsArticle]
    count: int
    query: str
    effective_query: str
    address: Optional[ParsedAddressModel] = None
    strict: bool = False
    filtered_out: int = 0
    max_results: Optional[int] = None


class ErrorMessage(BaseModel):
    detail: str


SEARCH_RESPONSES = {
    200: {"model": SearchResponse, "description": "Matching images"},
    401: {"model": ErrorMessage, "description": "Missing or invalid API key"},
    422: {"model": ErrorMessage, "description": "Missing query/address or invalid parameters"},
    429: {"model": ErrorMessage, "description": "Rate limited"},
    502: {"model": ErrorMessage, "description": "Upstream search provider error"},
}

NEWS_RESPONSES = {
    **SEARCH_RESPONSES,
    200: {"model": NewsResponse, "description": "Matching news articles"},
}

IMAGE_FILTER_FIELDS = ("size", "color", "type_image", "layout", "license_image")


class UpstreamError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def search_with_retry(ddgs, search_params, category="images", max_retries=3, delay=2):
    """
    Run a DDGS search with retries for rate limits and temporary errors.
    ddgs raises when no engine returns anything; that is an empty result, not an error.
    """
    search = getattr(ddgs, category)
    for attempt in range(max_retries):
        try:
            return list(search(**search_params)), None
        except Exception as e:
            error_str = str(e)

            if "no results found" in error_str.lower():
                return [], None

            # Check if it's a rate limit error
            if "403" in error_str or "Ratelimit" in error_str or "rate limit" in error_str.lower():
                if attempt < max_retries - 1:
                    time.sleep(delay * (attempt + 1))
                    continue
                return None, UpstreamError(429, "Rate limit exceeded. Please wait a few minutes before trying again.")

            # Check if it's a temporary error
            if any(code in error_str for code in ["429", "503", "502"]) or "timed out" in error_str.lower():
                if attempt < max_retries - 1:
                    time.sleep(delay * (attempt + 1))
                    continue
                return None, UpstreamError(503, "Service temporarily unavailable. Please try again later.")

            return None, UpstreamError(502, "Search provider error. Please try again later.")

    return None, UpstreamError(503, "Maximum retries exceeded.")

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


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc if url else ""
    except ValueError:
        return ""


def _to_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def format_image_results(results: List[Dict]) -> List[Dict]:
    """Format DuckDuckGo image results to match the desired structure"""
    formatted_results = []

    for idx, result in enumerate(results, start=1):
        website_url = result.get("url", "")
        formatted_result = {
            "url": result.get("image", ""),
            "alt": result.get("title", ""),
            "thumbnail": result.get("thumbnail", ""),
            "title": result.get("title", ""),
            "source": "DuckDuckGo Search Images",
            "website": {
                "url": website_url,
                "title": result.get("title", ""),
                "name": _domain(website_url) or "Unknown"
            },
            "dimensions": {
                # Bing returns dimensions as strings.
                "width": _to_int(result.get("width")),
                "height": _to_int(result.get("height"))
            },
            "position": idx
        }
        formatted_results.append(formatted_result)

    return formatted_results


def format_news_results(results: List[Dict]) -> List[Dict]:
    """Normalize ddgs news results into a stable shape."""
    return [
        {
            "title": result.get("title") or "",
            "body": result.get("body") or "",
            "url": result.get("url") or "",
            "image": result.get("image") or "",
            "source": result.get("source") or "",
            "date": result.get("date") or "",
            "domain": _domain(result.get("url") or ""),
            "position": idx,
        }
        for idx, result in enumerate(results, start=1)
    ]


class SearchPlan(BaseModel):
    """How a request's query/address/strict flags turn into a ddgs call and a filter."""
    query: str
    effective_query: str
    address: Optional[Dict] = None
    strict: bool = False
    required: List[str] = []


def plan_search(query: Optional[str], address: Optional[str], strict: Optional[bool]) -> SearchPlan:
    """Build the upstream query and the phrases strict mode requires."""
    query = (query or "").strip()
    address = (address or "").strip()
    if not query and not address:
        raise HTTPException(status_code=422, detail="Provide `query`, `address`, or both.")

    if address:
        parsed = parse_us_address(address)
        if not parsed:
            raise HTTPException(
                status_code=422,
                detail="Could not parse `address`. Start with a house number, e.g. '265 South Street Manhattan NY 10004'.",
            )
        effective = build_address_query(parsed, query or None)
        required = [parsed.street_line] + required_phrases(query)
        return SearchPlan(
            query=query or address,
            effective_query=effective,
            address=parsed.to_dict(),
            strict=True if strict is None else strict,
            required=required,
        )

    return SearchPlan(
        query=query,
        effective_query=query,
        strict=bool(strict),
        required=required_phrases(query),
    )


def _fetch_count(plan: SearchPlan, max_results: int) -> int:
    """Over-fetch when strict so filtering still leaves max_results."""
    if plan.strict and plan.required:
        return min(max_results * 3, 100)
    return max_results


def _apply_strict(plan: SearchPlan, results: List[Dict], fields: tuple) -> tuple[List[Dict], int]:
    if not (plan.strict and plan.required):
        return results, 0
    kept = [r for r in results if matches_all((str(r.get(f) or "") for f in fields), plan.required)]
    return kept, len(results) - len(kept)


def _image_backend(request: ImageSearchRequest, plan: SearchPlan) -> str:
    """
    Pick the image engine. Only duckduckgo supports filters and d/w/m/y timelimits,
    and ddgs 'auto' picks one engine at random, so filters could be silently ignored.
    For address searches Bing is far more precise, with duckduckgo as fallback.
    """
    backend = (request.backend or "auto").strip() or "auto"
    uses_filters = request.timelimit or any(getattr(request, f) for f in IMAGE_FILTER_FIELDS)
    if uses_filters and backend in {"auto", "bing"}:
        return "duckduckgo"
    if backend == "auto" and plan.address:
        return "bing,duckduckgo"
    return backend


def run_image_search(request: ImageSearchRequest) -> Dict:
    plan = plan_search(request.query, request.address, request.strict)
    max_results = request.max_results or 10
    search_params = {
        "query": plan.effective_query,
        "region": request.region,
        "safesearch": request.safesearch,
        "timelimit": request.timelimit,
        "page": request.page,
        "backend": _image_backend(request, plan),
        "size": request.size,
        "color": request.color,
        "type_image": request.type_image,
        "layout": request.layout,
        "license_image": request.license_image,
        "max_results": _fetch_count(plan, max_results),
    }
    search_params = {k: v for k, v in search_params.items() if v is not None}

    raw_results, error = search_with_retry(DDGS(), search_params, category="images")
    if error:
        raise HTTPException(status_code=error.status_code, detail=error.detail)

    raw_results, filtered_out = _apply_strict(plan, raw_results or [], ("title", "url", "image"))
    formatted_results = format_image_results(raw_results[:max_results])

    if request.validate_images:
        formatted_results = [
            result for result in formatted_results
            if (result.get("url") or result.get("thumbnail")) and validate_image_url(result.get("url") or result.get("thumbnail"))
        ]

    return {
        "images": formatted_results,
        "count": len(formatted_results),
        "query": plan.query,
        "effective_query": plan.effective_query,
        "address": plan.address,
        "strict": plan.strict,
        "filtered_out": filtered_out,
        "max_results": max_results,
    }


def run_news_search(request: NewsSearchRequest) -> Dict:
    plan = plan_search(request.query, request.address, request.strict)
    search_params = {
        "query": plan.effective_query,
        "region": request.region,
        "safesearch": request.safesearch,
        "timelimit": request.timelimit,
        "page": request.page,
        "backend": request.backend,
        "max_results": _fetch_count(plan, request.max_results),
    }
    search_params = {k: v for k, v in search_params.items() if v is not None}

    raw_results, error = search_with_retry(DDGS(), search_params, category="news")
    if error:
        raise HTTPException(status_code=error.status_code, detail=error.detail)

    raw_results, filtered_out = _apply_strict(plan, raw_results or [], ("title", "body", "url"))
    articles = format_news_results(raw_results[: request.max_results])
    return {
        "articles": articles,
        "count": len(articles),
        "query": plan.query,
        "effective_query": plan.effective_query,
        "address": plan.address,
        "strict": plan.strict,
        "filtered_out": filtered_out,
        "max_results": request.max_results,
    }


@app.get("/", response_class=HTMLResponse, tags=["Info"], summary="Homepage")
async def root(request: Request):
    """
    API Homepage - Welcome page with API information and documentation links
    """
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "base_url": public_base_url(request),
            "docs_enabled": ENABLE_DOCS,
            "version": "1.0.0",
        },
    )

@app.get("/api/info", tags=["Info"], summary="API metadata")
async def api_info():
    """Public JSON summary of endpoints and example calls."""
    return {
        "message": "DuckDuckGo Image & News Search API",
        "version": "1.0.0",
        "description": "A REST API for searching images and news using DuckDuckGo (ddgs), with precise US address search",
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
            "news_get": {
                "url": "/api/news",
                "method": "GET",
                "description": "Search news with query parameters"
            },
            "news_post": {
                "url": "/api/news",
                "method": "POST",
                "description": "Search news with JSON body"
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
            "post_request": "curl -X POST 'http://localhost:8000/api/search' -H 'X-API-Key: YOUR_API_KEY' -H 'Content-Type: application/json' -d '{\"query\": \"butterfly\", \"max_results\": 5}'",
            "address_images": "curl -G -H 'X-API-Key: YOUR_API_KEY' 'http://localhost:8000/api/search' --data-urlencode 'address=265 South Street Manhattan NY 10004'",
            "address_news": "curl -G -H 'X-API-Key: YOUR_API_KEY' 'http://localhost:8000/api/news' --data-urlencode 'address=265 South Street Manhattan NY 10004' --data-urlencode 'timelimit=y'"
        }
    }

# Search routes are sync `def` so FastAPI runs the blocking ddgs calls in a threadpool.
@app.get(
    "/api/search",
    tags=["Search"],
    summary="Search images",
    responses=SEARCH_RESPONSES,
    dependencies=[Depends(verify_api_key)],
)
def search_images_get(
    query: Optional[str] = Query(None, description=QUERY_DESCRIPTION, examples=["butterfly", '"265 South Street" tower']),
    address: Optional[str] = Query(None, description=ADDRESS_DESCRIPTION, examples=["265 South Street Manhattan NY 10004"]),
    strict: Optional[bool] = Query(None, description=STRICT_DESCRIPTION),
    max_results: int = Query(10, ge=1, le=100, description="Maximum number of results to return (1-100)", examples=[10, 20, 50]),
    region: str = Query("us-en", description="Region code: wt-wt (worldwide), us-en (US), uk-en (UK), es-es (Spain), fr-fr (France)", examples=["us-en", "uk-en", "wt-wt"]),
    safesearch: str = Query("off", description="Safe search level: off, moderate, on", examples=["off", "moderate", "on"]),
    timelimit: Optional[str] = Query(None, description="Time limit filter: d (day), w (week), m (month), y (year)", examples=["d", "w", "m", "y"]),
    page: int = Query(1, ge=1, le=10, description="Page number for pagination (1-10)", examples=[1, 2, 3]),
    backend: str = Query("auto", description="Backend: auto, bing, duckduckgo. Filters and timelimit force duckduckgo (bing ignores them).", examples=["auto", "bing", "duckduckgo"]),
    size: Optional[str] = Query(None, description="Size filter: Small, Medium, Large, Wallpaper", examples=["Small", "Medium", "Large", "Wallpaper"]),
    color: Optional[str] = Query(None, description="Color filter: Monochrome, Red, Orange, Yellow, Green, Blue, Purple, Pink, Brown, Black, Gray, Teal, White", examples=["Red", "Blue", "Green"]),
    type_image: Optional[str] = Query(None, description="Type filter: Photo, Clipart, Gif, Transparent, Line", examples=["Photo", "Clipart", "Gif"]),
    layout: Optional[str] = Query(None, description="Layout filter: Square, Tall, Wide", examples=["Square", "Tall", "Wide"]),
    license_image: Optional[str] = Query(None, description="License filter: Public, Share, ShareCommercially, Modify, ModifyCommercially", examples=["Public", "Share"]),
    validate_images: bool = Query(False, description="Validate image URLs (slower but more reliable - checks if images are accessible)", examples=[True, False]),
):
    """
    Search images with query parameters. Authorize first so Swagger sends `X-API-Key`.

    Send `query`, `address`, or both. For a place, prefer `address`: the street line is
    quoted and, with `strict` on, results that don't mention it are dropped.
    """
    return search_images_post(ImageSearchRequest(
        query=query, address=address, strict=strict, max_results=max_results,
        region=region, safesearch=safesearch, timelimit=timelimit, page=page,
        backend=backend, size=size, color=color, type_image=type_image,
        layout=layout, license_image=license_image, validate_images=validate_images,
    ))

@app.post(
    "/api/search",
    tags=["Search"],
    summary="Search images (JSON)",
    responses=SEARCH_RESPONSES,
    dependencies=[Depends(verify_api_key)],
)
def search_images_post(request: ImageSearchRequest):
    """
    Same search as GET, with a JSON body. Authorize first so Swagger sends `X-API-Key`.
    """
    try:
        return run_image_search(request)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get(
    "/api/news",
    tags=["News"],
    summary="Search news",
    responses=NEWS_RESPONSES,
    dependencies=[Depends(verify_api_key)],
)
def search_news_get(
    query: Optional[str] = Query(None, description=QUERY_DESCRIPTION, examples=["sun", '"265 South Street"']),
    address: Optional[str] = Query(None, description=ADDRESS_DESCRIPTION, examples=["265 South Street Manhattan NY 10004"]),
    strict: Optional[bool] = Query(None, description=STRICT_DESCRIPTION),
    max_results: int = Query(10, ge=1, le=100, description="Maximum number of results (1-100)"),
    region: str = Query("us-en", pattern=r"^[a-z]{2}-[a-z]{2}$", description="Region code, e.g. us-en, uk-en, wt-wt"),
    safesearch: SafeSearch = Query("off", description="Safe search level: off, moderate, on"),
    timelimit: Optional[TimeLimit] = Query(None, description="Time limit: d (day), w (week), m (month), y (year)"),
    page: int = Query(1, ge=1, le=10, description="Page number for pagination (1-10)"),
    backend: NewsBackend = Query("auto", description="Backend: auto, bing, duckduckgo, yahoo. auto falls back across engines."),
):
    """
    Search news with query parameters. Authorize first so Swagger sends `X-API-Key`.

    Send `query`, `address`, or both (e.g. address + query='rezoning').
    """
    return search_news_post(NewsSearchRequest(
        query=query, address=address, strict=strict, max_results=max_results,
        region=region, safesearch=safesearch, timelimit=timelimit, page=page,
        backend=backend,
    ))

@app.post(
    "/api/news",
    tags=["News"],
    summary="Search news (JSON)",
    responses=NEWS_RESPONSES,
    dependencies=[Depends(verify_api_key)],
)
def search_news_post(request: NewsSearchRequest):
    """
    Same news search as GET, with a JSON body.
    """
    try:
        return run_news_search(request)
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
        "description": "API key for /api/search and /api/news. Send it in the X-API-Key header.",
    }
    for path in SEARCH_PATHS:
        for method in schema.get("paths", {}).get(path, {}).values():
            if isinstance(method, dict):
                method["security"] = [{"ApiKeyAuth": []}]
    schema["x-tagGroups"] = [
        {"name": "API", "tags": ["Search", "News"]},
        {"name": "Status", "tags": ["Info", "Health"]},
    ]
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

