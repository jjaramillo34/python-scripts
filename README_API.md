# DuckDuckGo Image & News Search API

A FastAPI-based REST API for searching images and news using DuckDuckGo (ddgs), extracted from the Streamlit app.

## Security

The API refuses to start without a strong `API_KEY` (16+ characters, not a placeholder). Search endpoints require that key in the `X-API-Key` header.

### Setting Up Security

1. Generate a key:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

2. Put it in `.env` (local) or your host's environment variables (production):
```bash
API_KEY=paste_the_generated_key_here
ENVIRONMENT=production
```

Optional:
- `API_KEYS` — extra comma-separated keys for rotation
- `ALLOWED_ORIGINS` — browser origins allowed to call the API (empty = no CORS)
- `ALLOWED_HOSTS` — host allowlist
- `ENABLE_DOCS` — `/docs` is off in production unless this is `true`
- `RATE_LIMIT_SEARCH_PER_MINUTE` — default 30
- `RATE_LIMIT_AUTH_FAIL_PER_MINUTE` — default 10
- `TRUST_PROXY` — trust `X-Forwarded-For` behind Railway/Render/Heroku (on by default in production)

### Using the API Key

Send the key in the header only. Query-string keys are rejected so they cannot leak in logs or Referer headers.

```bash
curl -H "X-API-Key: your_api_key" \
  "http://localhost:8000/api/search?query=butterfly&max_results=5"
```

```javascript
fetch('http://localhost:8000/api/search?query=butterfly&max_results=5', {
  headers: {
    'X-API-Key': 'your_api_key'
  }
})
```

### Security Notes

- The homepage (`/`) and health check (`/health`) are public
- `/api/search` and `/api/news` require `X-API-Key`
- Never commit `.env` or API keys to version control
- Set `ENVIRONMENT=production` on the host

## Quick Start

### Local Development

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Create a `.env` file (for local development):
```bash
cp .env.example .env
```

3. Edit `.env` and set a strong `API_KEY` (16+ characters).

The `.env` file is loaded automatically. You can also export `API_KEY` in the shell.

4. Run the API:
```bash
python api.py
```

Or with uvicorn directly:
```bash
uvicorn api:app --reload --host 0.0.0.0 --port 8000
```

3. Access API docs:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## API Endpoints

### GET `/api/search`
Query parameters (send `query`, `address`, or both):
- `query`: Search keywords. Quote words to require that exact phrase.
- `address`: US street address, e.g. `265 South Street Manhattan NY 10004` (see below)
- `strict` (default: on with `address`, off otherwise): drop results that don't mention the address or every quoted phrase
- `max_results` (optional, default=10): Maximum results (1-100)
- `region` (optional, default="us-en"): Region code
- `safesearch` (optional, default="off"): Safe search level
- `timelimit`, `size`, `color`, `type_image`, `layout`, `license_image`: filters. Any of these forces the `duckduckgo` backend, because `bing` ignores them.
- `backend` (optional, default="auto"): `auto`, `bing`, `duckduckgo`
- `validate_images` (optional, default=false): Validate image URLs

**Example:**
```bash
curl -H "X-API-Key: YOUR_API_KEY" "http://localhost:8000/api/search?query=butterfly&max_results=5"
```

### POST `/api/search`
JSON body with same parameters as GET.

**Example:**
```bash
curl -X POST "http://localhost:8000/api/search" \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "butterfly", "max_results": 5}'
```

### GET / POST `/api/news`
Same `query` / `address` / `strict` / `max_results` / `region` / `safesearch` / `page` parameters, plus:
- `timelimit`: `d`, `w`, `m`, `y`
- `backend` (default="auto"): `auto`, `bing`, `duckduckgo`, `yahoo`. `auto` falls back across engines, which matters because individual news engines often return nothing.

Each article has `title`, `body`, `url`, `image`, `source`, `date` (ISO 8601), `domain`, `position`.

```bash
curl -G -H "X-API-Key: YOUR_API_KEY" "http://localhost:8000/api/news" \
  --data-urlencode "query=sun" --data-urlencode "timelimit=m"
```

### GET / POST `/api/project`
Coverage of a NYC development: dated articles and lead photos, newest first.
`/api/news` only indexes recent stories, so older coverage (permits, sales, lawsuits,
topping out) comes from here.

- `address` and/or `project` (e.g. `Two Bridges`): at least one is required. Each is searched separately.
- `query`: extra topic words added to every search, e.g. `lawsuit`
- `sites`: outlet domains (repeat the parameter). Defaults to New York YIMBY, The Real Deal, Curbed NY, 6sqft, Crain's, amNY, BLDUP, StreetEasy, Commercial Observer, CityRealty. They are searched five at a time, which returned more relevant hits than one ten-site query.
- `include_web` (default true): also run an open-web search
- `enrich` (default true): fetch each article (up to 20) to read its publish date, lead image (`og:image`), and full text. Results are then kept if the article body mentions the address or project, not just the snippet. Only public http(s) hosts are fetched.
- `strict` (default true): drop results that mention neither the address nor the project
- `timelimit`, `region`, `max_results` (1-30)

The response has `results` (title, url, source, snippet, date, image, outlet, mentions), `images`
(unique lead photos with their article), and the `queries` that ran.

```bash
curl -G -H "X-API-Key: YOUR_API_KEY" "http://localhost:8000/api/project" \
  --data-urlencode "address=265 South Street Manhattan NY 10004" \
  --data-urlencode "project=Two Bridges"
```

### Precise US address search

Search engines treat `265 South Street Manhattan NY 10004` as loose words, so results drift to
anything mentioning "South", "Manhattan", or "10004". With `address`:

1. The address is parsed into number, street, city, state, and ZIP (commas optional).
2. The query becomes `"265 South Street" Manhattan NY`: the street line is quoted with the suffix spelled out ("St" becomes "Street", which engines match more reliably), and the ZIP is left out because it pulls in unrelated listings that share it. If strict filtering leaves nothing, the search is retried once with the abbreviated form.
3. With `strict` on, results must mention the street line in the title, body, or URL. Abbreviations and slugs match: `265 South St.` and `/265-south-st` both count.
4. Image address searches prefer Bing, which was far more precise in testing, and fall back to DuckDuckGo.

Add `query` for topic words, e.g. `address=265 South Street Manhattan NY&query=construction`.
Responses include `effective_query`, the parsed `address`, and `filtered_out` so you can see what happened.

```bash
curl -G -H "X-API-Key: YOUR_API_KEY" "http://localhost:8000/api/news" \
  --data-urlencode "address=265 South Street Manhattan NY 10004"
```

News coverage of a specific street address is often sparse, so an empty strict result usually
means no indexed article mentions it. Retry with `strict=false` to see the looser matches.

## Deployment Options

### Option 1: Railway (Recommended - Easiest)
1. Push to GitHub
2. Go to https://railway.app
3. New Project → Deploy from GitHub
4. Select repository
5. Railway auto-detects FastAPI
6. Add environment variables:
   - `API_KEY` = a strong random secret (16+ characters)
   - `ENVIRONMENT` = `production`
   - `ALLOWED_ORIGINS` = your frontend origin, if browsers will call the API
7. Deploy!

**To add variables in Railway:**
- Open your Railway project
- Click on the service
- Go to the **Variables** tab
- Click **+ New Variable**
- Add `API_KEY` and `ENVIRONMENT`

### Option 2: Render
1. Create `render.yaml`:
```yaml
services:
  - type: web
    name: duckduckgo-image-api
    env: python
    buildCommand: pip install -r requirements_api.txt
    startCommand: uvicorn api:app --host 0.0.0.0 --port $PORT
```

2. Connect GitHub repo to Render
3. Deploy!

### Option 3: Fly.io
1. Install flyctl: `curl -L https://fly.io/install.sh | sh`
2. Run: `fly launch`
3. Follow prompts
4. Deploy: `fly deploy`

### Option 4: Heroku
1. Create `Procfile`:
```
web: uvicorn api:app --host 0.0.0.0 --port $PORT
```

2. Deploy:
```bash
heroku create your-app-name
git push heroku main
```

## Example Response

```json
{
  "images": [
    {
      "url": "https://example.com/image.jpg",
      "alt": "Butterfly image",
      "thumbnail": "https://example.com/thumb.jpg",
      "title": "Beautiful Butterfly",
      "source": "DuckDuckGo Search Images",
      "website": {
        "url": "https://example.com",
        "title": "Example Site",
        "name": "example.com"
      },
      "dimensions": {
        "width": 1920,
        "height": 1080
      },
      "position": 1
    }
  ],
  "count": 1,
  "query": "butterfly",
  "max_results": 10
}
```

## Why FastAPI over Flask?

- ⚡ **Faster**: Built on Starlette (async support)
- 📚 **Auto docs**: Swagger/OpenAPI included
- 🔒 **Type safety**: Pydantic validation
- 🚀 **Modern**: Python 3.7+ features
- 📦 **Easy deploy**: Works everywhere Flask does

## CORS

Cross-origin browser calls are denied unless you set `ALLOWED_ORIGINS` (comma-separated). Server-side callers (curl, backends) are not affected.

