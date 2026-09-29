import api
import project_search

ADDRESS = "265 South St, New York, NY 10004"

YIMBY_URL = "https://newyorkyimby.com/2021/09/two-bridges-permits-265-south-street.html"
TRD_URL = "https://therealdeal.com/new-york/2021/11/19/joe-chetrit-buying-second-two-bridges-site/"
CRAINS_URL = "https://www.crainsnewyork.com/real-estate/lower-east-side-lawsuit"
OFFTOPIC_URL = "https://example.com/unrelated"

PAGES = {
    YIMBY_URL: """<html><head>
        <meta property="og:image" content="https://newyorkyimby.com/wp-content/uploads/2018/12/Tb-1.jpg">
        <meta property="article:published_time" content="2021-09-29T07:30:30-04:00">
        <meta property="og:site_name" content="New York YIMBY">
        </head><body>Permits filed for 265 South Street.</body></html>""",
    TRD_URL: """<html><head>
        <meta content="https://static.therealdeal.com/chetrit.jpg" property="og:image" />
        <script type="application/ld+json">{"datePublished": "2021-11-19T17:31:40+00:00"}</script>
        </head><body>Chetrit is buying the Two Bridges site.</body></html>""",
    # Snippet doesn't mention the project; only the full article text does.
    CRAINS_URL: """<html><head><meta name="twitter:image" content="/img/lawsuit.jpg"></head>
        <body><p>The lawsuit targets the Two Bridges towers.</p><time datetime="2022-03-01">Mar 1</time></body></html>""",
    OFFTOPIC_URL: "<html><body>Nothing relevant here.</body></html>",
}


class FakeProjectDDGS:
    queries = []

    def __init__(self, *args, **kwargs):
        pass

    def text(self, **kwargs):
        FakeProjectDDGS.queries.append(kwargs["query"])
        return [
            {"title": "Two Bridges Associates Files Permits at 265 South St", "href": YIMBY_URL, "body": "Permits for a 71-story tower."},
            {"title": "Joe Chetrit buying Two Bridges site", "href": TRD_URL + "?utm=x", "body": "The developer..."},
            {"title": "Lawsuit filed", "href": CRAINS_URL, "body": "Residents sued the city."},
            {"title": "Unrelated", "href": OFFTOPIC_URL, "body": "Nope."},
        ]

    def extract(self, url, fmt="text_markdown"):
        page = PAGES.get(url.split("?")[0])
        if page is None:
            raise Exception("Failed to fetch")
        return {"url": url, "content": page}


def _patch(monkeypatch):
    FakeProjectDDGS.queries = []
    monkeypatch.setattr(api, "DDGS", FakeProjectDDGS)


def test_project_requires_api_key(client):
    assert client.get("/api/project", params={"project": "Two Bridges"}).status_code == 401


def test_project_requires_address_or_project(client, auth_headers, monkeypatch):
    _patch(monkeypatch)
    assert client.get("/api/project", headers=auth_headers).status_code == 422
    assert client.get("/api/project", params={"address": "South Street"}, headers=auth_headers).status_code == 422


def test_project_search_enriched(client, auth_headers, monkeypatch):
    _patch(monkeypatch)
    response = client.get(
        "/api/project",
        params={"address": ADDRESS, "project": "Two Bridges"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()

    assert body["identities"] == ["265 South Street", "Two Bridges"]
    # 2 identities x (2 outlet groups + 1 web search)
    assert len(body["queries"]) == 6
    assert any("site:newyorkyimby.com" in q for q in body["queries"])
    assert '"265 South Street" New York NY' in body["queries"]

    urls = [r["url"] for r in body["results"]]
    # Deduped (the ?utm copy collapses), off-topic dropped, Crain's kept via full text.
    assert len(urls) == 3
    assert OFFTOPIC_URL not in urls
    assert body["filtered_out"] == 1

    # Newest first.
    assert [r["date"][:10] for r in body["results"]] == ["2022-03-01", "2021-11-19", "2021-09-29"]
    crains = body["results"][0]
    assert crains["image"] == "https://www.crainsnewyork.com/img/lawsuit.jpg"
    assert crains["mentions"] == ["Two Bridges"]
    yimby = body["results"][2]
    assert yimby["source"] == "New York YIMBY"
    assert yimby["outlet"] is True
    assert yimby["mentions"] == ["265 South Street", "Two Bridges"]
    assert len(body["images"]) == 3


def test_project_search_without_enrich_uses_snippets(client, auth_headers, monkeypatch):
    _patch(monkeypatch)
    response = client.post(
        "/api/project",
        json={"project": "Two Bridges", "enrich": False, "include_web": False},
        headers=auth_headers,
    )
    body = response.json()
    assert response.status_code == 200
    assert len(body["queries"]) == 2
    # Crain's snippet doesn't say "Two Bridges", so without the article text it's dropped.
    assert [r["url"] for r in body["results"]] == [YIMBY_URL, TRD_URL + "?utm=x"]
    assert all(r["date"] is None and r["enriched"] is False for r in body["results"])


def test_project_custom_sites_are_validated(client, auth_headers, monkeypatch):
    _patch(monkeypatch)
    ok = client.get(
        "/api/project",
        params={"project": "Two Bridges", "sites": ["https://www.nytimes.com/", "gothamist.com"], "include_web": "false", "enrich": "false"},
        headers=auth_headers,
    )
    assert ok.status_code == 200
    assert ok.json()["sites"] == ["nytimes.com", "gothamist.com"]
    assert FakeProjectDDGS.queries == ['"Two Bridges" (site:nytimes.com OR site:gothamist.com)']
    bad = client.get("/api/project", params={"project": "x", "sites": "not a domain"}, headers=auth_headers)
    assert bad.status_code == 422


def test_fetch_refuses_private_hosts():
    for url in ["http://localhost/x", "http://127.0.0.1/", "http://10.0.0.5/a", "http://169.254.169.254/latest", "file:///etc/passwd", "http://printer.local/"]:
        assert api._is_public_http_url(url) is False
    assert api._is_public_http_url("https://newyorkyimby.com/a") is True


def test_page_details_and_helpers():
    details = project_search.page_details(PAGES[TRD_URL], TRD_URL)
    assert details["image"] == "https://static.therealdeal.com/chetrit.jpg"
    assert details["date"] == "2021-11-19T17:31:40+00:00"
    assert "Two Bridges" in details["text"]
    assert project_search.canonical_url("https://www.x.com/a/?q=1#f") == project_search.canonical_url("http://x.com/a")
    assert project_search.site_groups(list("abcdefg")) == [list("abcde"), list("fg")]


def test_address_search_retries_with_abbreviation(client, auth_headers, monkeypatch):
    calls = []

    class SpellingSensitiveDDGS:
        def images(self, **kwargs):
            calls.append(kwargs["query"])
            if '"265 South St"' in kwargs["query"]:
                return [{"image": "https://x.com/a.jpg", "title": "265 South St tower", "url": "https://x.com/a", "thumbnail": "", "width": 1, "height": 1}]
            return [{"image": "https://x.com/b.jpg", "title": "Delta news", "url": "https://x.com/b", "thumbnail": "", "width": 1, "height": 1}]

    monkeypatch.setattr(api, "DDGS", SpellingSensitiveDDGS)
    response = client.get("/api/search", params={"address": ADDRESS}, headers=auth_headers)
    body = response.json()
    assert calls == ['"265 South Street" New York NY', '"265 South St" New York NY']
    assert body["count"] == 1
    assert body["effective_query"] == '"265 South St" New York NY'
