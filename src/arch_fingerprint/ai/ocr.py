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

from arch_fingerprint.config import settings

logger = logging.getLogger(__name__)

# Default Ollama address
OLLAMA_URL = settings.ollama_ocr_url
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


def _prepare_full_page(img: Image.Image) -> str:
    """Resize entire image to fit MAX_OCR_DIM and encode as JPEG base64.

    GLM-OCR works best when it sees the entire page layout in one shot.
    This function always produces a single encoded image regardless of
    the original resolution.
    """
    target = img.copy()
    if target.mode == "RGBA":
        target = target.convert("RGB")
    if target.width > MAX_OCR_DIM or target.height > MAX_OCR_DIM:
        target.thumbnail((MAX_OCR_DIM, MAX_OCR_DIM), Image.Resampling.LANCZOS)

    buf = BytesIO()
    target.save(buf, format=OCR_IMAGE_FORMAT, quality=OCR_JPEG_QUALITY)
    logger.info(
        f"OCR: Full-page prepared ({target.size}) "
        f"as {OCR_IMAGE_FORMAT} ({len(buf.getvalue()) // 1024}KB)"
    )
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _make_tiles(img: Image.Image, tile_size: int, overlap: int) -> List[str]:
    """Split a large image into overlapping tiles for OCR fallback.

    Used only when the full-page approach returns empty and the image
    was heavily downscaled (large posters, maps, wide-format scans).
    """
    width, height = img.size

    def _get_intervals(limit: int, size: int, ol: int) -> List[Tuple[int, int]]:
        if limit <= size:
            return [(0, limit)]
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

    x_intervals = _get_intervals(width, tile_size, overlap)
    y_intervals = _get_intervals(height, tile_size, overlap)

    logger.info(
        f"OCR: Tiling {width}x{height} -> "
        f"{len(y_intervals)} rows x {len(x_intervals)} cols "
        f"= {len(y_intervals) * len(x_intervals)} tiles"
    )

    tiles: List[str] = []
    for y_start, y_end in y_intervals:
        for x_start, x_end in x_intervals:
            region = img.crop((x_start, y_start, x_end, y_end))
            if region.width > MAX_OCR_DIM or region.height > MAX_OCR_DIM:
                region.thumbnail(
                    (MAX_OCR_DIM, MAX_OCR_DIM), Image.Resampling.LANCZOS
                )
            if region.mode == "RGBA":
                region = region.convert("RGB")

            buf = BytesIO()
            region.save(buf, format=OCR_IMAGE_FORMAT, quality=OCR_JPEG_QUALITY)
            tiles.append(base64.b64encode(buf.getvalue()).decode("utf-8"))

    return tiles


# --- Adaptive thresholds --------------------------------------------------
# Minimum characters for full-page OCR to be considered successful.
FULL_PAGE_MIN_CHARS = 10
# If the resize scale factor drops below this, tiling *may* recover
# small text that was lost during downscaling.  0.35 ≈ image > ~5100 px
# in its largest dimension before tiling is even attempted.
TILING_SCALE_THRESHOLD = 0.35


async def run_ocr_async(image_path: str) -> Optional[str]:
    """Run GLM-OCR on the given image via Ollama, with adaptive strategy.

    Strategy (full-page-first, tiling-fallback):
    ─────────────────────────────────────────────
    1. **Always try full-page resize first.**
       GLM-OCR (1.1B) needs full-page context to recognise text reliably.
       Resize the whole image to MAX_OCR_DIM (1792 px) and run OCR once.
       This handles:
       • Standard documents (A4/A3 @ 150-300 DPI, up to ~5000 px)
       • Cover pages / sparse-text layouts
       • Photos of documents

    2. **Tiling fallback (large images only).**
       If full-page returned empty AND the original image was heavily
       downscaled (scale < TILING_SCALE_THRESHOLD), small text may have
       become unreadable.  In that case, tile the *original* image and
       run OCR on each tile, then smart-merge the results.
       This handles:
       • Very large posters / maps (> 5000 px)
       • Wide-format / panoramic scans
    """
    if not image_path:
        return None

    try:
        img = Image.open(image_path)
        w, h = img.size
        scale = min(MAX_OCR_DIM / w, MAX_OCR_DIM / h, 1.0)
        logger.info(
            f"OCR: Processing {image_path} ({w}x{h}), "
            f"scale_factor={scale:.2f}"
        )

        async with aiohttp.ClientSession(timeout=OCR_TIMEOUT) as session:
            # ── STRATEGY 1: Full Page (always first) ──────────────────
            full_encoded = _prepare_full_page(img)
            full_text = await _ocr_single_image_block(
                session, full_encoded, OLLAMA_MODEL
            )

            if full_text and len(full_text.strip()) > FULL_PAGE_MIN_CHARS:
                logger.info(
                    f"OCR: Full-page succeeded — {len(full_text)} chars"
                )
                return full_text

            # ── STRATEGY 2: Tiling Fallback ───────────────────────────
            # Only attempt if the image was significantly downscaled;
            # otherwise tiling won't help (the text was already large
            # enough, model just couldn't read it).
            if scale >= TILING_SCALE_THRESHOLD:
                logger.warning(
                    f"OCR: Full-page empty, scale={scale:.2f} "
                    f"(>= {TILING_SCALE_THRESHOLD}), "
                    f"tiling unlikely to help — returning empty"
                )
                return full_text  # may be None or short string

            logger.info(
                f"OCR: Full-page empty, scale={scale:.2f} "
                f"(< {TILING_SCALE_THRESHOLD}), attempting tiling fallback"
            )
            tiles = _make_tiles(img, TILE_SIZE, TILE_OVERLAP)

            if len(tiles) <= 1:
                # Single tile = same as full page, no point retrying.
                return full_text

            # Process tiles with concurrency limit to save VRAM
            sem = asyncio.Semaphore(2)

            async def _limited_ocr(encoded: str) -> Optional[str]:
                async with sem:
                    return await _ocr_single_image_block(
                        session, encoded, OLLAMA_MODEL
                    )

            tasks = [_limited_ocr(t) for t in tiles]
            results = await asyncio.gather(*tasks)

            valid_results = [r for r in results if r and len(r.strip()) > 5]

            if not valid_results:
                logger.warning(
                    f"OCR: Tiling also failed "
                    f"({len(tiles)} tiles, 0 valid results)"
                )
                return full_text  # return whatever full-page gave us

            # Smart-merge tile results in reading order
            merged = valid_results[0]
            for next_text in valid_results[1:]:
                merged = _smart_merge(merged, next_text)

            logger.info(
                f"OCR: Tiling succeeded — {len(merged)} chars "
                f"from {len(valid_results)}/{len(tiles)} tiles"
            )
            return merged

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
