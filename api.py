"""
FastAPI application for DuckDuckGo Image Search API
Deploy to: Heroku, Railway, Render, Fly.io, or any Python hosting service
"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from ddgs import DDGS
from typing import List, Dict, Optional
from urllib.parse import urlparse
import time
from pydantic import BaseModel, Field

app = FastAPI(
    title="DuckDuckGo Image Search API",
    description="Search and scrape images using DuckDuckGo with advanced filtering options",
    version="1.0.0"
)

# Enable CORS for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request model
class ImageSearchRequest(BaseModel):
    query: str = Field(..., description="Search keywords")
    max_results: Optional[int] = Field(10, ge=1, le=100, description="Maximum number of results")
    region: Optional[str] = Field("us-en", description="Region code (wt-wt, us-en, uk-en, es-es, fr-fr)")
    safesearch: Optional[str] = Field("off", description="Safe search level (off, moderate, on)")
    timelimit: Optional[str] = Field(None, description="Time limit filter (d, w, m, y)")
    page: Optional[int] = Field(1, ge=1, le=10, description="Page number")
    backend: Optional[str] = Field("auto", description="Backend (auto, api, html)")
    size: Optional[str] = Field(None, description="Size filter (Small, Medium, Large, Wallpaper)")
    color: Optional[str] = Field(None, description="Color filter")
    type_image: Optional[str] = Field(None, description="Type filter (Photo, Clipart, Gif, Transparent, Line)")
    layout: Optional[str] = Field(None, description="Layout filter (Square, Tall, Wide)")
    license_image: Optional[str] = Field(None, description="License filter")
    validate_images: Optional[bool] = Field(False, description="Validate image URLs (slower but more reliable)")

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

@app.get("/")
async def root():
    """API root endpoint"""
    return {
        "message": "DuckDuckGo Image Search API",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": {
            "search": "/api/search",
            "search_post": "/api/search (POST)"
        }
    }

@app.get("/api/search")
async def search_images_get(
    query: str = Query(..., description="Search keywords"),
    max_results: int = Query(10, ge=1, le=100, description="Maximum number of results"),
    region: str = Query("us-en", description="Region code"),
    safesearch: str = Query("off", description="Safe search level"),
    timelimit: Optional[str] = Query(None, description="Time limit filter"),
    page: int = Query(1, ge=1, le=10, description="Page number"),
    backend: str = Query("auto", description="Backend"),
    size: Optional[str] = Query(None, description="Size filter"),
    color: Optional[str] = Query(None, description="Color filter"),
    type_image: Optional[str] = Query(None, description="Type filter"),
    layout: Optional[str] = Query(None, description="Layout filter"),
    license_image: Optional[str] = Query(None, description="License filter"),
    validate_images: bool = Query(False, description="Validate image URLs")
):
    """
    Search for images using DuckDuckGo (GET endpoint)
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.post("/api/search")
async def search_images_post(request: ImageSearchRequest):
    """
    Search for images using DuckDuckGo (POST endpoint)
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

