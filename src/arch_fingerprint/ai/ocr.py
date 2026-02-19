import asyncio
import base64
import logging
import math
import re
import difflib
from collections import Counter
from io import BytesIO
from typing import List, Tuple, Optional

import aiohttp
from PIL import Image

logger = logging.getLogger(__name__)

# Default Ollama address
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "glm-ocr-high-ctx" 

# Fallback checking - handled by ensuring model exists or defaulting in config
GLM_OCR_PROMPT = "Text Recognition:"

# Timeouts
OCR_TIMEOUT = aiohttp.ClientTimeout(total=300, connect=10) # Increased for tiling

# Configuration: GLM-OCR / VLM Native Resolution
# IMPORTANT: Ollama's GGML backend crashes at exactly 2048px due to assertion failure.
# Empirically tested: 1792px is the maximum safe resolution that produces correct OCR.
# JPEG encoding drastically reduces payload size (3MB PNG -> 400KB JPEG) with identical results.
MAX_OCR_DIM = 1792
TILE_SIZE = 1792
TILE_OVERLAP = 256 # Minimal overlap for very large posters/maps only
OCR_IMAGE_FORMAT = "JPEG"
OCR_JPEG_QUALITY = 85

def _clean_ocr_response(raw: str) -> str:
    """Strip markdown code fences that GLM-OCR sometimes wraps around output."""
    if not raw:
        return ""
    text = raw.strip()
    # Remove ```json ... ``` or other fences
    text = re.sub(r'```[a-zA-Z]*\n', '', text)
    text = text.replace('```', '')
    return text.strip()


async def _ocr_single_image_block(session: aiohttp.ClientSession, encoded_image: str, model: str) -> Optional[str]:
    """Helper to run OCR on a single encoded image block."""
    try:
        payload = {
            "model": model,
            "prompt": "Text Recognition:",
            "images": [encoded_image],
            "stream": False,
            "options": {
                "num_ctx": 4096,
                "temperature": 0.0 # Strict deterministic output
            }
        }
        async with session.post(OLLAMA_URL, json=payload) as response:
            if response.status == 200:
                data = await response.json()
                return _clean_ocr_response(data.get("response", ""))
            return None
    except Exception as e:
        logger.error(f"OCR block exception: {e}")
        return None

def _smart_merge(text1: str, text2: str) -> str:
    """
    Merges two text blocks by finding the overlapping region.
    Uses dual-strategy: 
    1. Strongest single match (for clean OCR).
    2. Offset consistency (for noisy OCR with typos).
    """
    if not text1: return text2
    if not text2: return text1
    
    # 1000 chars is usually enough for 512px overlap (assuming ~2 chars/px density is unlikely, usually 0.1-0.2)
    window = 1000
    chunk1 = text1[-window:]
    chunk2 = text2[:window]
    
    s = difflib.SequenceMatcher(None, chunk1, chunk2)
    
    # --- Strategy 1: Longest Anchor ---
    match = s.find_longest_match(0, len(chunk1), 0, len(chunk2))
    
    # Check if anchor is valid (near boundary)
    # Relaxed tolerance (150 chars) for edge noise
    nearby_end1 = (match.a + match.size) >= (len(chunk1) - 150)
    nearby_start2 = match.b <= 150
    
    if match.size > 20 and nearby_end1 and nearby_start2:
        # Found a solid anchor.
        # We stitch exactly at the end of this anchor.
        # Keep text1 up to the end of the match.
        cut_idx1 = len(text1) - len(chunk1) + match.a + match.size
        # Start text2 after the match.
        cut_idx2 = match.b + match.size
        
        return text1[:cut_idx1] + text2[cut_idx2:]
        
    # --- Strategy 2: Fuzzy Offset Consensus (Noise/Typos) ---
    blocks = s.get_matching_blocks()
    
    # Calculate offsets (a - b) for all non-trivial blocks
    offsets = []
    for a, b, size in blocks:
        if size > 3: # Ignore tiny 1-2 char accidental matches
            offsets.extend([a - b] * size) # Weight by length
            
    if not offsets:
        return text1 + "\n" + text2
        
    # Find dominant offset (the true alignment shift)
    common_offset = Counter(offsets).most_common(1)[0][0]
    
    # Verify this offset explains a significant portion of the overlap
    valid_size = 0
    last_match_end_a = 0
    first_match_start_b = 9999
    
    for a, b, size in blocks:
        # Check if this block belongs to the dominant alignment (allowing +/- 5 chars jitter)
        if abs((a - b) - common_offset) < 5:
            valid_size += size
            last_match_end_a = max(last_match_end_a, a + size)
            first_match_start_b = min(first_match_start_b, b)
            
    # If we have enough alignment (>30 chars) and it effectively bridges the gap
    if valid_size > 30 and (last_match_end_a > len(chunk1) - 200) and (first_match_start_b < 200):
         # Valid fuzzy overlap detected.
         # Stitch at the end of the last participating block.
         
         cut_idx1 = len(text1) - len(chunk1) + last_match_end_a
         
         # Ideally text2 cut is where text1 cut maps to:
         # a - b = offset  =>  b = a - offset
         computed_cut_idx2 = last_match_end_a - common_offset
         
         # Clamp to bounds
         computed_cut_idx2 = max(0, min(computed_cut_idx2, len(text2)))
         
         return text1[:cut_idx1] + text2[computed_cut_idx2:]

    # Fallback
    return text1 + "\n" + text2


def _split_image(img: Image.Image, tile_size: int, overlap: int) -> List[str]:
    """
    Prepares image for OCR.
    Strategy:
    1. If image fits in TILE_SIZE x TILE_SIZE (2048x2048), send WHOLE. (Best for GLM-OCR)
    2. If larger, tile it.
    """
    width, height = img.size
    
    # --- STRATEGY 1: Full Page (Preferred) ---
    # Most documents (A4/High-DPI) are ~2500-3500px in height.
    # We resize to fit MAX_OCR_DIM (1792px) to avoid GGML crash at 2048px.
    # Threshold: 3000px — covers A4 @ 300 DPI (3508px is edge case, resize handles it).
    if width <= 3000 and height <= 3000:
        target_img = img.copy()
        if img.mode == "RGBA":
            target_img = target_img.convert("RGB")
        if width > MAX_OCR_DIM or height > MAX_OCR_DIM:
            target_img.thumbnail((MAX_OCR_DIM, MAX_OCR_DIM), Image.Resampling.LANCZOS)
        
        buf = BytesIO()
        target_img.save(buf, format=OCR_IMAGE_FORMAT, quality=OCR_JPEG_QUALITY)
        logger.info(f"OCR: Sending full page ({target_img.size}) as {OCR_IMAGE_FORMAT} ({len(buf.getvalue())//1024}KB)")
        return [base64.b64encode(buf.getvalue()).decode("utf-8")]
        
    # --- STRATEGY 2: Tiling (For Giant Maps/Posters) ---
    tiles = []
    
    # Helper for anchored intervals
    def get_intervals(limit, size, ol):
        if limit <= size: return [(0, limit)]
        res = []
        curr = 0
        while True:
            end = curr + size
            if end >= limit:
                res.append((max(0, limit - size), limit))
                break
            res.append((curr, end))
            curr += size - ol
        return sorted(list(set(res)))

    x_intervals = get_intervals(width, tile_size, overlap)
    y_intervals = get_intervals(height, tile_size, overlap)
    
    logger.info(f"Image too large ({width}x{height}). Tiling: {len(y_intervals)}x{len(x_intervals)}")
    
    for y_start, y_end in y_intervals:
        for x_start, x_end in x_intervals:
            box = (x_start, y_start, x_end, y_end)
            region = img.crop(box)
            
            # Ensure crop fits safe resolution
            if region.width > MAX_OCR_DIM or region.height > MAX_OCR_DIM:
                 region.thumbnail((MAX_OCR_DIM, MAX_OCR_DIM), Image.Resampling.LANCZOS)
            if region.mode == "RGBA":
                region = region.convert("RGB")

            buf = BytesIO()
            region.save(buf, format=OCR_IMAGE_FORMAT, quality=OCR_JPEG_QUALITY)
            tiles.append(base64.b64encode(buf.getvalue()).decode("utf-8"))
            
    return tiles


async def run_ocr_async(image_path: str) -> Optional[str]:
    """
    Run GLM-OCR on the given image path via Ollama API asynchronously.
    Uses smart tiling with overlap to handle large documents.
    """
    if not image_path:
        return None

    try:
        # Load image
        img = Image.open(image_path)
        
        # 1. Tiling Strategy
        # We ALWAYS tile if any dimension > TILE_SIZE, unlike before where we just resized.
        # Resizing destroys text clarity for OCR.
        
        logger.info(f"OCR: Processing {image_path} ({img.size}) with tile_size={TILE_SIZE}, overlap={TILE_OVERLAP}")
        
        tiles = _split_image(img, TILE_SIZE, TILE_OVERLAP)
        
        if not tiles:
            return None
            
        async with aiohttp.ClientSession(timeout=OCR_TIMEOUT) as session:
            # Process tiles in parallel with a concurrency limit
            sem = asyncio.Semaphore(2) # Process max 2 tiles at once to save VRAM
            
            async def limited_ocr(encoded):
                async with sem:
                    return await _ocr_single_image_block(session, encoded, OLLAMA_MODEL)
            
            tasks = [limited_ocr(t) for t in tiles]
            results = await asyncio.gather(*tasks)
            
            # Filter empty results
            valid_results = [r for r in results if r and len(r.strip()) > 5]
            
            if not valid_results:
                logger.warning(f"OCR: No text found in any of {len(tiles)} tiles.")
                return None
                
            # Smart Merge with Deduplication
            full_text = valid_results[0]
            for next_text in valid_results[1:]:
                full_text = _smart_merge(full_text, next_text)
            
            return full_text

    except Exception as e:
        logger.exception(f"OCR Global Exception for {image_path}: {e}")
        return None

def run_ocr(image_path: str) -> Optional[str]:
    """Synchronous wrapper for run_ocr_async."""
    try:
        return asyncio.run(run_ocr_async(image_path))
    except Exception as e:
        logger.error(f"Sync OCR wrapper failed: {e}")
        return None
