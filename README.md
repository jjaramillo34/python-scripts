# DuckDuckGo Image Search API & Streamlit App

This repository contains both a FastAPI REST API and a Streamlit web application for searching images using DuckDuckGo.

## 📁 Project Structure

```
.
├── api.py                    # FastAPI REST API (root - for Railway deployment)
├── requirements.txt          # FastAPI dependencies (root - Railway detects this)
├── Procfile                  # Railway/Heroku deployment config
├── render.yaml               # Render deployment config
├── streamlit_app/            # Streamlit application folder
│   ├── app.py               # Streamlit app
│   └── requirements.txt     # Streamlit dependencies
└── README_API.md            # API documentation
```

## 🚀 FastAPI REST API

**Location:** Root directory (for Railway deployment)

### Quick Start

```bash
pip install -r requirements.txt
python api.py
```

Then visit: http://localhost:8000/docs

### Deploy to Railway

1. Push to GitHub
2. Go to https://railway.app
3. New Project → Deploy from GitHub
4. Railway auto-detects `requirements.txt` and `api.py` in root
5. Deploy!

## 🎨 Streamlit App

**Location:** `streamlit_app/` folder

### Quick Start

```bash
cd streamlit_app
pip install -r requirements.txt
streamlit run app.py
```

### Deploy to Streamlit Cloud

1. Push to GitHub
2. Go to https://share.streamlit.io
3. Connect repository
4. Set main file: `streamlit_app/app.py`

## 📚 Documentation

- API Documentation: See `README_API.md`
- Streamlit App: See `streamlit_app/README.md`

