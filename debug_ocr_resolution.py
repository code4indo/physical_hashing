"""Debug OCR: Test various resolutions to find what GLM-OCR accepts."""
import asyncio
import base64
import json
import aiohttp
from PIL import Image
from io import BytesIO

OLLAMA_URL = "http://localhost:11434/api/generate"

async def test_resolution(width, height):
    """Create a test image at specific resolution and try OCR."""
    # Create a simple test image with text-like content
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    
    buf = BytesIO()
    img.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("utf-8")
    
    payload = {
        "model": "glm-ocr",
        "prompt": "Text Recognition:",
        "images": [encoded],
        "stream": False,
        "options": {"num_ctx": 2048, "temperature": 0.0}
    }
    
    timeout = aiohttp.ClientTimeout(total=30, connect=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(OLLAMA_URL, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    resp = data.get("response", "")
                    return f"OK ({len(resp)} chars)"
                else:
                    data = await response.json()
                    err = data.get("error", "unknown")
                    return f"FAIL: {err[:60]}"
    except Exception as e:
        return f"EXCEPTION: {e}"

async def main():
    # Test various resolutions that are common for documents
    test_sizes = [
        (224, 224),      # Small patch
        (448, 448),      # 2x patch
        (560, 560),      # 2.5x patch
        (672, 672),      # 3x patch 
        (784, 784),      # 3.5x patch
        (896, 896),      # 4x patch
        (1024, 1024),    # Common
        (1120, 1120),    # 5x patch  
        (1344, 1344),    # 6x patch
        (1568, 1568),    # 7x patch
        (1792, 1792),    # 8x patch
        (2016, 2016),    # 9x patch
        (2048, 2048),    # Max reported
        (1550, 2048),    # Our failing resolution
        (1024, 2048),    # Mixed
        (768, 1024),     # Standard
        (800, 1200),     # Random
        (1536, 2048),    # 1.5:1 ratio
    ]
    
    for w, h in test_sizes:
        result = await test_resolution(w, h)
        print(f"{w:5d} x {h:5d} -> {result}")

asyncio.run(main())
