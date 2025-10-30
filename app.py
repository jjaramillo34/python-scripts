import streamlit as st
from ddgs import DDGS
import json
from typing import List, Dict, Optional
from urllib.parse import urlparse
import requests
from PIL import Image
from io import BytesIO
import time
from functools import wraps
import re
import platform
import subprocess

# Streamlit extras for enhanced UI
from streamlit_extras.colored_header import colored_header
from streamlit_extras.metric_cards import style_metric_cards

# Try importing clipboard libraries
try:
    import pyperclip
    HAS_PYPERCLIP = True
except ImportError:
    HAS_PYPERCLIP = False

try:
    from tkinter import Tk
    HAS_TKINTER = True
except ImportError:
    HAS_TKINTER = False

st.set_page_config(
    page_title="Image Scraper",
    page_icon="🔍",
    layout="wide"
)

def search_with_retry(ddgs, search_params, max_retries=3, delay=2):
    """
    Search with retry logic to handle rate limiting and temporary errors.
    """
    for attempt in range(max_retries):
        try:
            # Use the new API format
            results = list(ddgs.images(**search_params))
            return results, None
        except Exception as e:
            error_str = str(e)
            
            # Check if it's a rate limit error
            if "403" in error_str or "Ratelimit" in error_str or "rate limit" in error_str.lower():
                if attempt < max_retries - 1:
                    wait_time = delay * (attempt + 1)  # Exponential backoff
                    time.sleep(wait_time)
                    continue
                else:
                    return None, "Rate limit exceeded. Please wait a few minutes before trying again, or try different parameters."
            
            # Check if it's a temporary error
            if any(code in error_str for code in ["429", "503", "502"]):
                if attempt < max_retries - 1:
                    wait_time = delay * (attempt + 1)
                    time.sleep(wait_time)
                    continue
                else:
                    return None, "Service temporarily unavailable. Please try again later."
            
            # For other errors, return immediately
            return None, f"Search error: {error_str}"
    
    return None, "Maximum retries exceeded."

def validate_image_url(image_url: str, timeout: int = 5) -> bool:
    """
    Check if an image URL is valid and accessible.
    Returns True if the URL returns a valid image, False otherwise.
    """
    if not image_url or not image_url.startswith(('http://', 'https://')):
        return False
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    # Special handling for Google-hosted images
    if "googleusercontent.com" in image_url or "googleapis.com" in image_url:
        headers['Referer'] = 'https://www.google.com/'
    
    try:
        # First try HEAD request for efficiency
        response = requests.head(image_url, headers=headers, timeout=timeout, allow_redirects=True)
        
        # Check if response is successful
        if response.status_code == 200:
            # Check if content type is an image
            content_type = response.headers.get('Content-Type', '')
            if content_type.startswith('image/'):
                return True
        
        # If HEAD doesn't work or doesn't return content type, try GET with streaming
        response = requests.get(image_url, headers=headers, timeout=timeout, stream=True, allow_redirects=True)
        if response.status_code == 200:
            # Read first chunk to validate it's an image
            chunk = response.raw.read(1024)
            if chunk:
                try:
                    # Try to open as image to validate format
                    Image.open(BytesIO(chunk))
                    return True
                except Exception:
                    # Check content type from response
                    content_type = response.headers.get('Content-Type', '')
                    if content_type.startswith('image/'):
                        return True
        return False
    except requests.exceptions.Timeout:
        return False
    except requests.exceptions.RequestException:
        return False
    except Exception:
        return False

def filter_valid_images(results: List[Dict], progress_bar=None) -> List[Dict]:
    """
    Filter results to only include images with valid URLs.
    """
    valid_results = []
    
    for i, result in enumerate(results):
        image_url = result.get("url") or result.get("thumbnail", "")
        
        if progress_bar:
            progress_bar.progress((i + 1) / len(results), text=f"Validating image {i + 1}/{len(results)}")
        
        if image_url and validate_image_url(image_url):
            valid_results.append(result)
    
    return valid_results

def display_image_safe(image_url: str, caption: str = ""):
    """
    Safely display an image, handling Google-hosted and other protected images.
    """
    try:
        # Check if it's a Google-hosted image
        if "googleusercontent.com" in image_url or "googleapis.com" in image_url:
            # Try to download and display the image
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Referer': 'https://www.google.com/'
                }
                response = requests.get(image_url, headers=headers, timeout=10, stream=True)
                
                if response.status_code == 200:
                    # Try to read the image
                    img_data = response.content
                    img = Image.open(BytesIO(img_data))
                    st.image(img, width='stretch', caption=caption)
                    return True
                else:
                    # If direct download fails, try with st.image (it might handle it)
                    st.image(image_url, width='stretch', caption=caption)
                    return True
            except Exception as e:
                # If all else fails, show a clickable link
                st.warning(f"⚠️ Preview unavailable for this image")
                st.markdown(f"[🔗 View Image in Browser]({image_url})", unsafe_allow_html=True)
                return False
        else:
            # For regular images, use standard display
            st.image(image_url, width='stretch', caption=caption)
            return True
    except Exception as e:
        # Fallback: show as link
        st.warning(f"⚠️ Preview unavailable")
        st.markdown(f"[🔗 View Image: {image_url}]({image_url})", unsafe_allow_html=True)
        return False

def extract_restaurant_info(title: str, alt: str) -> tuple:
    """
    Extract restaurant name and address from title or alt text.
    Returns (restaurant_name, full_address)
    """
    # Try to extract from title first, then alt
    text = title or alt or ""
    
    # Common patterns for restaurant info:
    # "Restaurant Name, 123 Street, City, State ZIP"
    # "📍Restaurant Name] Address"
    # "Restaurant Name - Address"
    
    # Look for address patterns (numbers, street names, city, state)
    # Pattern to find potential addresses
    address_pattern = r'\d+[^,]*,[^,]*,[^,]*'  # Number, Street, City format
    
    # Split by common delimiters
    parts = re.split(r'[,\-–—\|\[\]]+', text)
    
    restaurant_name = ""
    full_address = ""
    
    # Try to find restaurant name (usually first part)
    if parts:
        # Remove emojis and clean up
        restaurant_name = re.sub(r'[📍🎯🌟⭐]', '', parts[0]).strip()
    
    # Try to find address
    address_match = re.search(address_pattern, text)
    if address_match:
        full_address = address_match.group(0).strip()
    
    # If no structured address found, try to extract from the text
    if not full_address and len(parts) > 1:
        # Take everything after the first comma as address
        full_address = ', '.join(parts[1:]).strip()
        # Clean up common prefixes
        full_address = re.sub(r'^(📍|🎯|at|in|near)\s*', '', full_address, flags=re.IGNORECASE)
    
    return restaurant_name, full_address

def copy_to_clipboard(text: str) -> bool:
    """
    Copy text to clipboard using multiple fallback methods.
    Tries: macOS pbcopy, tkinter, pyperclip, Windows clipboard.
    """
    if not text:
        return False
    
    # Method 1: macOS pbcopy (most reliable on macOS)
    if platform.system() == "Darwin":  # macOS
        try:
            process = subprocess.Popen(
                ['pbcopy'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            process.communicate(input=text.encode('utf-8'))
            process.wait()
            if process.returncode == 0:
                return True
        except Exception:
            pass
    
    # Method 2: Tkinter (cross-platform, built-in)
    if HAS_TKINTER:
        try:
            r = Tk()
            r.withdraw()  # Hide the main window
            r.clipboard_clear()
            r.clipboard_append(text)
            r.update()  # Now it stays on the clipboard after the window is closed
            r.destroy()
            return True
        except Exception:
            pass
    
    # Method 3: pyperclip (if available)
    if HAS_PYPERCLIP:
        try:
            pyperclip.copy(text)
            return True
        except Exception:
            pass
    
    # Method 4: Linux xclip
    if platform.system() == "Linux":
        try:
            process = subprocess.Popen(
                ['xclip', '-selection', 'clipboard'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            process.communicate(input=text.encode('utf-8'))
            if process.returncode == 0:
                return True
        except Exception:
            pass
    
    return False

def format_image_results(results: List[Dict]) -> List[Dict]:
    """Format DuckDuckGo image results to match the desired structure"""
    formatted_results = []
    
    for idx, result in enumerate(results, start=1):
        # Extract website name from URL
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

def main():
    # Enhanced header with colored_header
    colored_header(
        label="🔍 Image Scraper with DuckDuckGo",
        description="Search and scrape images using DuckDuckGo with advanced filtering options",
        color_name="blue-70"
    )
    
    # Sidebar for search controls
    with st.sidebar:
        colored_header(
            label="⚙️ Search Settings",
            description="Configure your image search",
            color_name="violet-70"
        )
        keywords = st.text_input("🔑 Search Keywords", value="butterfly", help="Enter what you want to search")
        max_results = st.number_input("📊 Max Results", min_value=1, max_value=100, value=10, step=1)
        
        with st.expander("🔧 Filter Options", expanded=False):
            region = st.selectbox("Region", ["wt-wt", "us-en", "uk-en", "es-es", "fr-fr"], index=1)  # Default to us-en
            safesearch = st.selectbox("Safe Search", ["off", "moderate", "on"], index=0)
            
            # Time limit filter
            timelimit = st.selectbox("Time Limit", ["None", "d", "w", "m", "y"], index=0, help="d=day, w=week, m=month, y=year")
            
            # Page number
            page = st.number_input("Page", min_value=1, max_value=10, value=1, step=1, help="Page number for results")
            
            # Backend selection
            backend = st.selectbox("Backend", ["auto", "api", "html"], index=0, help="Search backend to use")
            
            # Size filter
            size_filter = st.selectbox("Size", ["None", "Small", "Medium", "Large", "Wallpaper"])
            
            # Color filter
            color_filter = st.selectbox("Color", ["None", "Monochrome", "Red", "Orange", "Yellow", "Green", "Blue", "Purple", "Pink", "Brown", "Black", "Gray", "Teal", "White"])
            
            # Type filter
            type_filter = st.selectbox("Type", ["None", "Photo", "Clipart", "Gif", "Transparent", "Line"])
            
            # Layout filter
            layout_filter = st.selectbox("Layout", ["None", "Square", "Tall", "Wide"])
            
            # License filter
            license_filter = st.selectbox("License", ["None", "Public", "Share", "ShareCommercially", "Modify", "ModifyCommercially"])
        
        st.markdown("---")
        colored_header(
            label="🔍 Validation",
            description="",
            color_name="orange-70"
        )
        validate_images = st.checkbox("✅ Validate Images", value=True, help="Filter out broken/invalid image URLs (recommended)")
        
        st.markdown("---")
        colored_header(
            label="⚡ Rate Limiting",
            description="",
            color_name="red-70"
        )
        st.info("💡 If you get rate limit errors, wait a few minutes or reduce max results.")
        enable_delay = st.checkbox("⏱️ Add delay between searches", value=True, help="Helps prevent rate limiting")
        
        search_button = st.button("🔍 Search Images", type="primary", width='stretch')
    
    # Main content area
    if search_button or st.session_state.get('results'):
        if search_button:
            with st.spinner(f"Searching for '{keywords}'..."):
                try:
                    # Prepare search parameters using the new API format
                    search_params = {
                        "query": keywords,  # Changed from "keywords" to "query"
                        "region": region,
                        "safesearch": safesearch,
                        "timelimit": timelimit if timelimit != "None" else None,
                        "page": page,
                        "backend": backend,
                        "size": size_filter if size_filter != "None" else None,
                        "color": color_filter if color_filter != "None" else None,
                        "type_image": type_filter if type_filter != "None" else None,
                        "layout": layout_filter if layout_filter != "None" else None,
                        "license_image": license_filter if license_filter != "None" else None,
                        "max_results": max_results,
                    }
                    
                    # Add delay before search if enabled
                    if enable_delay:
                        time.sleep(1)  # Small delay to avoid rate limiting
                    
                    # Perform search using the new API format with retry logic
                    ddgs = DDGS()
                    raw_results, error_msg = search_with_retry(ddgs, search_params)
                    
                    # Handle search errors
                    if error_msg:
                        st.error(f"❌ {error_msg}")
                        st.info("""
                        **Tips to avoid rate limiting:**
                        - Wait 2-5 minutes before trying again
                        - Reduce the number of max results
                        - Try different search keywords
                        - Enable 'Add delay between searches' option
                        """)
                        st.session_state['results'] = None
                        return
                    
                    if raw_results:
                        # Format results
                        formatted_results = format_image_results(raw_results)
                        
                        # Validate images if option is enabled
                        if validate_images:
                            st.info(f"🔍 Validating {len(formatted_results)} images...")
                            progress_bar = st.progress(0, text="Starting validation...")
                            valid_results = filter_valid_images(formatted_results, progress_bar)
                            progress_bar.empty()
                            
                            if valid_results:
                                filtered_count = len(formatted_results) - len(valid_results)
                                if filtered_count > 0:
                                    st.warning(f"⚠️ Filtered out {filtered_count} invalid images. {len(valid_results)} valid images remaining.")
                                else:
                                    st.success(f"✅ All {len(valid_results)} images are valid!")
                                st.session_state['results'] = valid_results
                            else:
                                st.error("❌ No valid images found. Try different keywords or disable validation.")
                                st.session_state['results'] = None
                        else:
                            st.session_state['results'] = formatted_results
                            st.success(f"Found {len(formatted_results)} images!")
                        
                        st.session_state['keywords'] = keywords
                    else:
                        st.warning("No images found. Try different keywords.")
                        st.session_state['results'] = None
                        
                except Exception as e:
                    error_str = str(e)
                    if "403" in error_str or "Ratelimit" in error_str:
                        st.error("❌ Rate limit exceeded. Please wait a few minutes before trying again.")
                        st.info("""
                        **Tips to avoid rate limiting:**
                        - Wait 2-5 minutes before trying again
                        - Reduce the number of max results
                        - Enable 'Add delay between searches' option
                        """)
                    else:
                        st.error(f"❌ Error searching images: {error_str}")
                        st.info("If this error persists, try waiting a few minutes or reducing your search parameters.")
                    st.session_state['results'] = None
        
        # Display results
        if st.session_state.get('results'):
            results = st.session_state['results']
            
            # Display JSON format
            json_output = {"images": results}
            json_str = json.dumps(json_output, indent=2)
            
            # Copyable JSON text area with copy button
            st.markdown("### 📋 Copy JSON Results")
            
            # Copy button using JavaScript (works in browser)
            col_copy, col_info = st.columns([1, 4])
            with col_copy:
                # JavaScript-based copy button (works in browser)
                # json_str is already a JSON string - use json.dumps() to escape it properly for JavaScript
                # Then strip outer quotes since we embed it directly in a JavaScript string literal
                json_for_js = json.dumps(json_str)[1:-1]  # Escape properly, then remove outer JSON quotes
                copy_button_html = f"""
                <div id="copy-container">
                    <button onclick="copyToClipboard()" style="
                        width: 100%;
                        padding: 0.5rem;
                        background-color: #FF4B4B;
                        color: white;
                        border: none;
                        border-radius: 0.25rem;
                        cursor: pointer;
                        font-size: 1rem;
                        font-weight: 600;
                    " onmouseover="this.style.backgroundColor='#FF2B2B'" onmouseout="this.style.backgroundColor='#FF4B4B'">
                        📋 Copy JSON
                    </button>
                    <script>
                    // json_for_js is the escaped JSON string, use it directly
                    const jsonData = "{json_for_js}";
                    function copyToClipboard() {{
                        if (navigator.clipboard && navigator.clipboard.writeText) {{
                            navigator.clipboard.writeText(jsonData).then(function() {{
                                alert('✅ JSON copied to clipboard!');
                            }}, function(err) {{
                                fallbackCopy(jsonData);
                            }});
                        }} else {{
                            fallbackCopy(jsonData);
                        }}
                    }}
                    function fallbackCopy(text) {{
                        const textarea = document.createElement('textarea');
                        textarea.value = text;
                        textarea.style.position = 'fixed';
                        textarea.style.opacity = '0';
                        document.body.appendChild(textarea);
                        textarea.select();
                        try {{
                            document.execCommand('copy');
                            alert('✅ JSON copied to clipboard!');
                        }} catch (err) {{
                            alert('⚠️ Copy failed. Please use the text area below to copy manually.');
                        }}
                        document.body.removeChild(textarea);
                    }}
                    </script>
                </div>
                """
                st.components.v1.html(copy_button_html, height=45)
            
            with col_info:
                st.info("💡 Click the **Copy JSON** button above to copy the results.")
            
            # Server-side copy button (fallback)
            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                if st.button("📋 Copy via Server (Alternative)", width='stretch', key="copy_json_server"):
                    if copy_to_clipboard(json_str):
                        st.success("✅ JSON copied to clipboard!")
                    else:
                        st.warning("⚠️ Server-side copy failed. Use the 'Copy JSON' button above or the text area.")
            
            with col_btn2:
                st.download_button(
                    label="📥 Download JSON File",
                    data=json_str,
                    file_name=f"{st.session_state.get('keywords', 'search')}_results.json",
                    mime="application/json",
                    width='stretch',
                    type="primary"
                )
            
            # Optional: View formatted JSON in expander
            with st.expander("📖 View Formatted JSON", expanded=False):
                st.code(json_str, language="json")
            
            # Display images in grid with colored header
            colored_header(
                label=f"📸 Images for '{st.session_state.get('keywords', keywords)}'",
                description=f"Found {len(results)} image(s)",
                color_name="green-70"
            )
            
            # Create columns for grid layout - 5 images per row
            cols_per_row = 5
            num_cols = min(cols_per_row, len(results))
            
            for i in range(0, len(results), cols_per_row):
                cols = st.columns(num_cols)
                for j, col in enumerate(cols):
                    if i + j < len(results):
                        result = results[i + j]
                        with col:
                            # Display image
                            try:
                                # Try to display the main image, fallback to thumbnail
                                image_url = result.get("url") or result.get("thumbnail", "")
                                if image_url:
                                    # Use safe display function for Google images
                                    display_image_safe(image_url, caption=f"Image #{result.get('position', i+j+1)}")
                                    
                                    # Extract restaurant info and add copy button
                                    title = result.get('title', '')
                                    alt = result.get('alt', '')
                                    restaurant_name, full_address = extract_restaurant_info(title, alt)
                                    
                                    # Create a row for status/button
                                    status_col, button_col = st.columns([4, 1])
                                    
                                    with status_col:
                                        # Display status/info
                                        if restaurant_name or full_address:
                                            info_text = f"{restaurant_name} {full_address}".strip()
                                            if info_text:
                                                st.caption(f"📍 {info_text[:50]}{'...' if len(info_text) > 50 else ''}")
                                    
                                    with button_col:
                                        # Copy button
                                        if restaurant_name and full_address:
                                            copy_text = f"{restaurant_name} {full_address}"
                                            if st.button("📋", key=f"copy_{i}_{j}", help="Copy restaurant name and address", width='stretch'):
                                                # Try to copy to clipboard
                                                if copy_to_clipboard(copy_text):
                                                    st.session_state[f'copied_{i}_{j}'] = True
                                                    st.success("✅")
                                                else:
                                                    # Display text in a copyable format
                                                    st.code(copy_text)
                                    # Show success message if copied
                                    if st.session_state.get(f'copied_{i}_{j}', False):
                                        st.caption("✅ Copied!")
                                    
                                    # Display metadata with badges
                                    with st.expander(f"ℹ️ Details - Image #{result.get('position', i+j+1)}"):
                                        st.write(f"**Title:** {result.get('title', 'N/A')}")
                                        st.write(f"**Image URL:** [{result.get('url', 'N/A')}]({result.get('url', '#')})")
                                        
                                        # Use markdown badges for metadata
                                        source = result.get('source', 'N/A')
                                        st.markdown(f"**Source:** `{source}`")
                                        
                                        website_name = result.get('website', {}).get('name', 'N/A')
                                        website_url = result.get('website', {}).get('url', '#')
                                        st.write(f"**Website:** [{website_name}]({website_url})")
                                        
                                        width = result.get('dimensions', {}).get('width', 0)
                                        height = result.get('dimensions', {}).get('height', 0)
                                        if width and height:
                                            st.markdown(f"**Dimensions:** 📐 `{width} x {height} px`")
                                        
                                        position = result.get('position', i+j+1)
                                        st.markdown(f"**Position:** `#{position}`")
                                        
                                        # Copy JSON for this image
                                        image_json = json.dumps(result, indent=2)
                                        st.code(image_json, language="json")
                            except Exception as e:
                                st.error(f"Error loading image: {str(e)}")
                                st.write(f"**URL:** {result.get('url', 'N/A')}")
                                # Show the result data for debugging
                                with st.expander("Show raw data"):
                                    st.json(result)
            
            # Results summary with styled metrics
            st.markdown("---")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("📊 Total Images", len(results))
            with col2:
                avg_width = sum(r.get("dimensions", {}).get("width", 0) for r in results) / len(results) if results else 0
                st.metric("📐 Avg Width", f"{int(avg_width)}px")
            with col3:
                avg_height = sum(r.get("dimensions", {}).get("height", 0) for r in results) / len(results) if results else 0
                st.metric("📏 Avg Height", f"{int(avg_height)}px")
            
            # Style the metric cards
            style_metric_cards(
                background_color="#f0f2f6",
                border_left_color="#1f77b4",
                border_color="#d1d4dc",
                box_shadow="2px 2px 5px rgba(0,0,0,0.1)"
            )
    
    else:
        # Welcome message with enhanced styling
        st.info("👈 Use the sidebar to configure your search and click 'Search Images' to get started!")
        
        # Features in an accordion format
        with st.expander("🚀 Features & How to Use", expanded=False):
            st.markdown("""
            ### ✨ Advanced Search Capabilities:
            - 🔍 Search images using DuckDuckGo (new API format)
            - 🎨 Filter by color, size, type, layout, and license
            - ⏰ Time-based filtering (day, week, month, year)
            - 📄 Pagination support (multiple pages)
            - 🔧 Backend selection (auto, api, html)
            - 🌍 Choose region
            
            ### 🛡️ Quality & Protection:
            - ✅ Image validation (filter broken URLs)
            - 🛡️ Rate limiting protection
            - 📥 Download results as JSON
            - 📸 View images in a beautiful grid layout
            
            ### 📖 How to Use:
            1. Enter your search keywords in the sidebar
            2. Configure search filters (optional)
            3. Set the maximum number of results
            4. Click "Search Images" button
            5. Browse results and copy/download JSON data
            """)

if __name__ == "__main__":
    main()

