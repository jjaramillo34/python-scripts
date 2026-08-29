# DuckDuckGo Image Search API & Streamlit App

This repository contains a FastAPI REST API and a Streamlit web app for searching images using DuckDuckGo.

The API will not start without a strong `API_KEY`. Search requests must send that key in the `X-API-Key` header.

## Project Structure

```
.
├── api.py                 # FastAPI REST API
├── requirements.txt       # FastAPI dependencies
├── .env.example           # Environment variable template
├── Procfile               # Railway / Heroku start command
├── render.yaml            # Render deployment config
├── templates/             # Homepage, Swagger, and ReDoc
├── tests/                 # Pytest suite
├── .github/workflows/ci.yml
├── requirements-dev.txt   # Test dependencies
├── streamlit_app/         # Streamlit application
│   ├── app.py
│   └── requirements.txt
└── README_API.md          # Full API documentation
```

## FastAPI REST API

**Location:** repository root (for Railway / Render / Heroku)

### Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Generate a key (16+ characters) and put it in `.env`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

```bash
API_KEY=paste_the_generated_key_here
ENVIRONMENT=development
```

Never commit `.env`.

### Run

```bash
uvicorn api:app --reload --host 127.0.0.1 --port 8000
```

Or:

```bash
python api.py
```

- Homepage: http://127.0.0.1:8000
- Swagger UI: http://127.0.0.1:8000/docs (on in development; off in production unless `ENABLE_DOCS=true`)
- Health: http://127.0.0.1:8000/health

### Call the search API

```bash
curl -H "X-API-Key: your_api_key" \
  "http://127.0.0.1:8000/api/search?query=butterfly&max_results=5"
```

```bash
curl -X POST "http://127.0.0.1:8000/api/search" \
  -H "X-API-Key: your_api_key" \
  -H "Content-Type: application/json" \
  -d '{"query": "butterfly", "max_results": 5}'
```

Query-string keys (`?api_key=`) are rejected so they cannot leak in logs or Referer headers.

### Production environment

Set these on Railway, Render, or Heroku:

| Variable | Required | Notes |
|---|---|---|
| `API_KEY` | Yes | Strong random secret, 16+ characters |
| `ENVIRONMENT` | Recommended | `production` |
| `ALLOWED_ORIGINS` | If browsers on another domain call the API | Comma-separated origins |
| `ENABLE_DOCS` | Optional | `true` to expose `/docs` in production |
| `API_KEYS` | Optional | Extra keys for rotation |

`/` and `/health` stay public. `/api/search` requires `X-API-Key`.

### Deploy to Railway

1. Push to GitHub
2. Create a project from the repo at https://railway.app
3. Railway picks up `requirements.txt` and `Procfile` in the root
4. Add `API_KEY` and `ENVIRONMENT=production`
5. Deploy

See `README_API.md` for Render, Fly.io, Heroku, and the full endpoint reference.

## Tests

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest
```

Use `python -m pytest` so tests run with this project's interpreter (not a Conda `pytest` on `PATH`).

The suite covers API key checks, rejected query-string keys, rate limits, public pages, and OpenAPI security. DuckDuckGo is mocked so CI does not call the network.

GitHub Actions runs the same tests on Python 3.11 and 3.12 for every push and pull request to `main`.

## Streamlit App

**Location:** `streamlit_app/`

```bash
cd streamlit_app
pip install -r requirements.txt
streamlit run app.py
```

### Deploy to Streamlit Cloud

1. Push to GitHub
2. Go to https://share.streamlit.io
3. Connect the repository
4. Set the main file to `streamlit_app/app.py`

## Documentation

- API: `README_API.md`
- Streamlit: `streamlit_app/README.md`
