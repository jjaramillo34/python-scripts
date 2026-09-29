"""
Find coverage of a NYC development project by address and/or project name.

`news()` only indexes recent stories, so older project coverage (permits, sales,
lawsuits, topping out) is missing. This module runs ddgs `text()` searches
restricted to NYC real-estate outlets plus an optional open-web search, then
optionally fetches each hit with `extract()` to read its publish date, lead
image, and full text.
"""
import html as html_lib
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Dict, List, Optional, Sequence
from urllib.parse import urlparse, urlunparse

from precision import matching_phrases

# Outlets that cover NYC development. Split into groups because engines return
# more relevant hits for five `site:` operators than for ten in one query.
NYC_PROJECT_SITES: List[str] = [
    "newyorkyimby.com",
    "therealdeal.com",
    "ny.curbed.com",
    "6sqft.com",
    "crainsnewyork.com",
    "amny.com",
    "bldup.com",
    "streeteasy.com",
    "commercialobserver.com",
    "cityrealty.com",
]
SITES_PER_QUERY = 5
MAX_ENRICH = 20
ENRICH_WORKERS = 6
MAX_PAGE_CHARS = 400_000

_META_TAG_RE = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
_ATTR_RE = re.compile(r'([a-zA-Z_:.-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\')')
_JSONLD_DATE_RE = re.compile(r'"datePublished"\s*:\s*"([^"]+)"')
_TIME_TAG_RE = re.compile(r'<time\b[^>]*\bdatetime\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_SCRIPT_STYLE_RE = re.compile(r"<(script|style|noscript)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")

IMAGE_META_KEYS = ("og:image", "og:image:url", "twitter:image", "twitter:image:src")
DATE_META_KEYS = (
    "article:published_time",
    "og:published_time",
    "datepublished",
    "pubdate",
    "publishdate",
    "date",
    "dc.date",
    "sailthru.date",
    "parsely-pub-date",
)


def site_groups(sites: Sequence[str]) -> List[List[str]]:
    return [list(sites[i:i + SITES_PER_QUERY]) for i in range(0, len(sites), SITES_PER_QUERY)]


def sites_clause(sites: Sequence[str]) -> str:
    return "(" + " OR ".join(f"site:{site}" for site in sites) + ")"


def canonical_url(url: str) -> str:
    """Dedupe key: drop scheme, www, query, fragment, and trailing slash."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return url
    host = (parsed.hostname or "").lower().removeprefix("www.")
    return urlunparse(("", host, parsed.path.rstrip("/"), "", "", ""))


def domain_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def is_outlet(url: str, sites: Sequence[str]) -> bool:
    host = domain_of(url)
    return any(host == site or host.endswith("." + site) for site in sites)


def parse_meta(page_html: str) -> Dict[str, str]:
    """Collect <meta> property/name -> content, first value wins."""
    meta: Dict[str, str] = {}
    for tag in _META_TAG_RE.findall(page_html):
        attrs = {m.group(1).lower(): m.group(2) if m.group(2) is not None else m.group(3) for m in _ATTR_RE.finditer(tag)}
        key = (attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or "").lower()
        content = attrs.get("content")
        if key and content and key not in meta:
            meta[key] = html_lib.unescape(content.strip())
    return meta


def page_details(page_html: str, page_url: str) -> Dict[str, Optional[str]]:
    """Publish date, lead image, site name, and visible text from an article page."""
    page_html = page_html[:MAX_PAGE_CHARS]
    meta = parse_meta(page_html)

    image = next((meta[key] for key in IMAGE_META_KEYS if meta.get(key)), None)
    if image and image.startswith("//"):
        image = "https:" + image
    elif image and image.startswith("/"):
        parsed = urlparse(page_url)
        image = f"{parsed.scheme}://{parsed.netloc}{image}"
    if image and not image.startswith(("http://", "https://")):
        image = None

    date = next((meta[key] for key in DATE_META_KEYS if meta.get(key)), None)
    if not date:
        match = _JSONLD_DATE_RE.search(page_html) or _TIME_TAG_RE.search(page_html)
        date = match.group(1) if match else None

    text = _TAG_RE.sub(" ", _SCRIPT_STYLE_RE.sub(" ", page_html))
    return {
        "date": date,
        "image": image,
        "site_name": meta.get("og:site_name"),
        "description": meta.get("og:description") or meta.get("description"),
        "text": html_lib.unescape(text),
    }


def build_queries(
    identities: Sequence[str],
    extra: Optional[str],
    sites: Sequence[str],
    include_web: bool,
    city_hint: Optional[str],
) -> List[Dict[str, str]]:
    """
    One search per identity (quoted address line or project name) per site
    group, plus an open-web search per identity. Searching each identity
    separately beats OR-ing them, which engines handle inconsistently.
    """
    queries = []
    for identity in identities:
        base = f'"{identity}"'
        if extra:
            base = f"{base} {extra}"
        for group in site_groups(sites):
            queries.append({"query": f"{base} {sites_clause(group)}", "kind": "outlet"})
        if include_web:
            web = f"{base} {city_hint}" if city_hint else base
            queries.append({"query": web, "kind": "web"})
    return queries


def merge_results(batches: Sequence[tuple], sites: Sequence[str]) -> List[Dict]:
    """Flatten (kind, results) batches, dedupe by URL, keep first-seen order."""
    seen: Dict[str, Dict] = {}
    for kind, results in batches:
        for result in results or []:
            url = result.get("href") or result.get("url") or ""
            if not url.startswith(("http://", "https://")):
                continue
            key = canonical_url(url)
            if key in seen:
                continue
            seen[key] = {
                "title": result.get("title") or "",
                "url": url,
                "snippet": result.get("body") or "",
                "domain": domain_of(url),
                "outlet": is_outlet(url, sites),
                "found_by": kind,
            }
    return list(seen.values())


def enrich(results: List[Dict], fetch_html: Callable[[str], str]) -> None:
    """Fetch pages concurrently and add date, image, site_name, page text. Failures are skipped."""
    def work(item: Dict) -> None:
        try:
            page_html = fetch_html(item["url"])
        except Exception:
            item["enriched"] = False
            return
        if isinstance(page_html, bytes):
            page_html = page_html.decode("utf-8", "ignore")
        item.update(page_details(page_html or "", item["url"]))
        item["enriched"] = True

    with ThreadPoolExecutor(max_workers=ENRICH_WORKERS, thread_name_prefix="enrich") as pool:
        list(pool.map(work, results))


def mentions(item: Dict, identities: Sequence[str]) -> List[str]:
    texts = [item.get("title"), item.get("snippet"), item.get("url"), item.get("description"), item.get("text")]
    return matching_phrases([t for t in texts if t], identities)


def parse_date(value: Optional[str]) -> Optional[datetime]:
    """Parse ISO 8601 or RFC 2822 dates from page metadata. Naive dates are treated as UTC."""
    if not value:
        return None
    value = value.strip()
    parsed = None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            match = re.match(r"\d{4}-\d{2}-\d{2}", value)
            if match:
                parsed = datetime.fromisoformat(match.group(0))
    if parsed and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def sort_newest_first(items: List[Dict]) -> List[Dict]:
    """Dated items newest first, then undated items in search order (sort is stable)."""
    def key(item: Dict):
        parsed = parse_date(item.get("date"))
        return (0, -parsed.timestamp()) if parsed else (1, 0)
    return sorted(items, key=key)
