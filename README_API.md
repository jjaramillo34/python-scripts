# DuckDuckGo Image Search API

A FastAPI-based REST API for searching images using DuckDuckGo, extracted from the Streamlit app.

## Security

The API is protected with API key authentication. All GET and POST requests to `/api/search` require a valid API key.

### Setting Up Security

1. Set environment variables (recommended for production):
```bash
export ALLOWED_EMAIL=javier@privatediningpros.com
export API_KEY=your_secure_password_here
```

2. Or set them when running:
```bash
ALLOWED_EMAIL=javier@privatediningpros.com API_KEY=your_secure_password_here python api.py
```

### Using the API Key

**Option 1: Header (Recommended)**
```bash
curl -H "X-API-Key: your_secure_password_here" \
  "http://localhost:8000/api/search?query=butterfly&max_results=5"
```

**Option 2: Query Parameter**
```bash
curl "http://localhost:8000/api/search?query=butterfly&max_results=5&api_key=your_secure_password_here"
```

**JavaScript Example:**
```javascript
fetch('http://localhost:8000/api/search?query=butterfly&max_results=5', {
  headers: {
    'X-API-Key': 'your_secure_password_here'
  }
})
```

### Security Notes

- The homepage (`/`) and health check (`/health`) endpoints are **not** protected
- All `/api/search` endpoints require authentication
- In production, use a strong, randomly generated API key
- Never commit your API key to version control

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

3. Edit `.env` and set your credentials:
```bash
ALLOWED_EMAIL=javier@privatediningpros.com
API_KEY=your_secure_password_here
```

**Note:** The `.env` file is automatically loaded. You can also use environment variables directly:
```bash
export API_KEY=your_secure_password_here
export ALLOWED_EMAIL=javier@privatediningpros.com
```

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
   - Go to your project → **Variables** tab
   - Click **+ New Variable**
   - Add `ALLOWED_EMAIL` = `javier@privatediningpros.com`
   - Add `API_KEY` = `your_secure_password_here` (use a strong random password!)
7. Deploy!

**To add variables in Railway:**
- Open your Railway project
- Click on the service
- Go to the **Variables** tab
- Click **+ New Variable**
- Add each variable: `ALLOWED_EMAIL` and `API_KEY`

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

The API includes CORS middleware allowing all origins. For production, update:
```python
allow_origins=["https://yourdomain.com"]
```

