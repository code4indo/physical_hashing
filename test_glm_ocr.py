#!/usr/bin/env python3
"""Test GLM-OCR with correct prompt format: 'Text Recognition:'"""
import requests, base64, os, time

OLLAMA_URL = "http://localhost:11434/api/generate"

# Find a test image
img_path = None
for f in sorted(os.listdir("data/uploads")):
    if f.endswith("_raw.png"):
        img_path = f"data/uploads/{f}"
        break

if not img_path:
    print("No test image found!")
    exit(1)

print(f"Image: {img_path} ({os.path.getsize(img_path)} bytes)")

with open(img_path, "rb") as f:
    img_b64 = base64.b64encode(f.read()).decode("utf-8")

# Test 1: CORRECT format — "Text Recognition:"
print("\n=== Test 1: 'Text Recognition:' (official format) ===")
start = time.time()
resp = requests.post(OLLAMA_URL, json={
    "model": "glm-ocr",
    "prompt": "Text Recognition:",
    "images": [img_b64],
    "stream": False,
}, timeout=120)
data = resp.json()
text = data.get("response", "")
dur = time.time() - start
print(f"Time: {dur:.1f}s | Text ({len(text)} chars):")
print(text[:500])
print(f"eval_count={data.get('eval_count')}, total_dur={data.get('total_duration',0)/1e9:.1f}s")

# Test 2: OLD prompt
print("\n=== Test 2: 'Extract all text...' (old prompt) ===")
start = time.time()
resp2 = requests.post(OLLAMA_URL, json={
    "model": "glm-ocr",
    "prompt": "Extract all text from this image exactly as it appears. Do not add commentary.",
    "images": [img_b64],
    "stream": False,
}, timeout=120)
data2 = resp2.json()
text2 = data2.get("response", "")
dur2 = time.time() - start
print(f"Time: {dur2:.1f}s | Text ({len(text2)} chars):")
print(text2[:500])
