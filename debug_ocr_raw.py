"""Debug OCR: Direct Ollama API call with detailed response logging."""
import asyncio
import base64
import json
import aiohttp
from PIL import Image
from io import BytesIO

OLLAMA_URL = "http://localhost:11434/api/generate"

async def test_direct():
    image_path = "/data/PROJECT/physical_hashing/data/uploads/13ece276ac044092ae8dfcc8f1978545_raw.png"
    
    # Load and resize image to fit 2048x2048
    img = Image.open(image_path)
    print(f"Original size: {img.size}")
    
    img.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
    print(f"Resized to: {img.size}")
    
    buf = BytesIO()
    img.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("utf-8")
    print(f"Base64 length: {len(encoded)}")
    
    # Test with glm-ocr-high-ctx
    payload = {
        "model": "glm-ocr-high-ctx",
        "prompt": "Text Recognition:",
        "images": [encoded],
        "stream": False,
        "options": {
            "num_ctx": 4096,
            "temperature": 0.0
        }
    }
    
    print("\n--- Calling Ollama glm-ocr-high-ctx ---")
    timeout = aiohttp.ClientTimeout(total=120, connect=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(OLLAMA_URL, json=payload) as response:
            print(f"HTTP Status: {response.status}")
            raw_text = await response.text()
            print(f"Raw response length: {len(raw_text)}")
            
            try:
                data = json.loads(raw_text)
                ocr_response = data.get("response", "")
                print(f"\n--- OCR Response ({len(ocr_response)} chars) ---")
                print(ocr_response[:500] if ocr_response else "<EMPTY>")
                print("---")
                
                # Check other fields 
                if "error" in data:
                    print(f"ERROR from Ollama: {data['error']}")
                    
                print(f"Total duration: {data.get('total_duration', 'N/A')}")
                print(f"Eval count: {data.get('eval_count', 'N/A')}")
            except json.JSONDecodeError:
                print(f"NOT JSON! Raw: {raw_text[:200]}")

    # Also test with base glm-ocr
    payload["model"] = "glm-ocr"
    print("\n--- Calling Ollama glm-ocr (base) ---")
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(OLLAMA_URL, json=payload) as response:
            print(f"HTTP Status: {response.status}")
            data = await response.json()
            ocr_response = data.get("response", "")
            print(f"OCR Response ({len(ocr_response)} chars):")
            print(ocr_response[:500] if ocr_response else "<EMPTY>")
            if "error" in data:
                print(f"ERROR: {data['error']}")

asyncio.run(test_direct())
