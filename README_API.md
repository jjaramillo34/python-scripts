# DuckDuckGo Image Search API

A FastAPI-based REST API for searching images using DuckDuckGo, extracted from the Streamlit app.

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
- `/api/search` requires `X-API-Key`
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
Query parameters:
- `query` (required): Search keywords
- `max_results` (optional, default=10): Maximum results (1-100)
- `region` (optional, default="us-en"): Region code
- `safesearch` (optional, default="off"): Safe search level
- `validate_images` (optional, default=false): Validate image URLs

**Example:**
```bash
curl "http://localhost:8000/api/search?query=butterfly&max_results=5"
```

### POST `/api/search`
JSON body with same parameters as GET.

**Example:**
```bash
curl -X POST "http://localhost:8000/api/search" \
  -H "Content-Type: application/json" \
  -d '{"query": "butterfly", "max_results": 5}'
```

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

