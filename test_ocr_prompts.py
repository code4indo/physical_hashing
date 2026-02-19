#!/usr/bin/env python3
"""Test GLM-OCR with various prompts to diagnose why it returns empty."""
import requests
import base64
import sys
import os

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "glm-ocr"

# Pick a test image
img_path = sys.argv[1] if len(sys.argv) > 1 else "data/uploads/09b47cf7c67044e0add3219c723afb88_raw.png"

if not os.path.exists(img_path):
    # Fallback: find any raw image
    for f in os.listdir("data/uploads"):
        if f.endswith("_raw.png"):
            img_path = f"data/uploads/{f}"
            break

print(f"Testing with: {img_path}")
print(f"File size: {os.path.getsize(img_path)} bytes")

with open(img_path, "rb") as f:
    img_b64 = base64.b64encode(f.read()).decode("utf-8")

print(f"Base64 length: {len(img_b64)} chars\n")

# Test various prompts
prompts = [
    "OCR",
    "",
    "Extract all text from this image exactly as it appears. Do not add commentary.",
    "请提取图片中的所有文字",
    "Read all text in this image",
    "What text do you see in this image?",
    "Describe what you see in this image",
]

for i, prompt in enumerate(prompts):
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "images": [img_b64],
        "stream": False,
    }
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
        data = resp.json()
        text = data.get("response", "")
        eval_count = data.get("eval_count", 0)
        eval_dur = data.get("eval_duration", 0) / 1e9
        total_dur = data.get("total_duration", 0) / 1e9
        prompt_eval = data.get("prompt_eval_count", 0)
        print(f"[{i}] Prompt: '{prompt[:60]}'")
        print(f"    Result ({len(text)} chars): {text[:200]}")
        print(f"    eval_count={eval_count}, prompt_eval={prompt_eval}, eval_dur={eval_dur:.2f}s, total={total_dur:.2f}s")
        print()
    except Exception as e:
        print(f"[{i}] Prompt: '{prompt[:60]}' => ERROR: {e}\n")

# Also test WITHOUT image to see if model behaves differently
print("--- Test WITHOUT image ---")
payload_no_img = {
    "model": MODEL,
    "prompt": "Hello, what can you do?",
    "stream": False,
}
resp = requests.post(OLLAMA_URL, json=payload_no_img, timeout=60)
data = resp.json()
print(f"No-image response: {data.get('response', '')[:300]}")
