"""Debug OCR: Test with ACTUAL document image at various quality levels."""
import asyncio
import base64
import json
import aiohttp
from PIL import Image
from io import BytesIO

OLLAMA_URL = "http://localhost:11434/api/generate"

async def test_with_image(img, label):
    """Test OCR with given PIL image."""
    buf = BytesIO()
    img.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("utf-8")
    
    payload = {
        "model": "glm-ocr-high-ctx",
        "prompt": "Text Recognition:",
        "images": [encoded],
        "stream": False,
        "options": {"num_ctx": 4096, "temperature": 0.0}
    }
    
    timeout = aiohttp.ClientTimeout(total=120, connect=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(OLLAMA_URL, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    resp = data.get("response", "")
                    return f"OK ({len(resp)} chars): {resp[:80]}..."
                else:
                    data = await response.json()
                    err = data.get("error", "unknown")
                    return f"HTTP {response.status}: {err[:80]}"
    except Exception as e:
        return f"EXCEPTION: {str(e)[:80]}"

async def main():
    image_path = "/data/PROJECT/physical_hashing/data/uploads/13ece276ac044092ae8dfcc8f1978545_raw.png"
    img = Image.open(image_path)
    print(f"Original: {img.size}, mode={img.mode}")
    
    # Convert to RGB if needed (RGBA causes issues)
    if img.mode != "RGB":
        img = img.convert("RGB")
        print(f"Converted to RGB")
    
    tests = [
        ("Original (1873x2474)", img),
    ]
    
    # Test various thumbnail sizes
    for max_dim in [2048, 1792, 1536, 1344, 1024, 768]:
        resized = img.copy()
        resized.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
        tests.append((f"Thumbnail max={max_dim} -> {resized.size}", resized))
    
    # Test JPEG encoding (much smaller payload)
    for quality in [95, 85, 70]:
        resized = img.copy()
        resized.thumbnail((1792, 1792), Image.Resampling.LANCZOS)
        buf = BytesIO()
        resized.save(buf, format="JPEG", quality=quality)
        jpeg_encoded = base64.b64encode(buf.getvalue()).decode("utf-8")
        
        payload = {
            "model": "glm-ocr-high-ctx",
            "prompt": "Text Recognition:",
            "images": [jpeg_encoded],
            "stream": False,
            "options": {"num_ctx": 4096, "temperature": 0.0}
        }
        
        timeout = aiohttp.ClientTimeout(total=120, connect=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(OLLAMA_URL, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    resp = data.get("response", "")
                    print(f"JPEG q={quality} ({len(jpeg_encoded)//1024}KB) -> OK ({len(resp)} chars): {resp[:80]}...")
                else:
                    data = await response.json()
                    err = data.get("error", "unknown")
                    print(f"JPEG q={quality} ({len(jpeg_encoded)//1024}KB) -> HTTP {response.status}: {err[:80]}")
    
    for label, test_img in tests:
        buf = BytesIO()
        test_img.save(buf, format="PNG")
        b64_size = len(base64.b64encode(buf.getvalue()))
        print(f"\nTesting: {label} (payload: {b64_size//1024}KB)")
        result = await test_with_image(test_img, label)
        print(f"  Result: {result}")

asyncio.run(main())
