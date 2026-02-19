"""Robustness augmentation utilities for document fingerprinting.

Provides:
1. Perspective correction   — fix camera angle distortion
2. Registration augmentation — store multiple view embeddings  
3. Top-K-of-N scoring       — ignore occluded/bad regions

Used by search.py and queue.py to make identification robust against:
- Different camera angles
- Partial occlusion (fingers, hands)  
- Folded/bent documents
- Varying lighting conditions
"""

import cv2
import numpy as np
import logging
from PIL import Image
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# 1. PERSPECTIVE CORRECTION
# ═══════════════════════════════════════════════════════════════════

def correct_perspective(image: Image.Image) -> Image.Image:
    """Detect document edges and apply perspective correction.
    
    Uses OpenCV contour detection to find the largest quadrilateral,
    then applies a homography transform to produce a top-down view.
    
    If no clear document boundary is found, returns the original image.
    """
    img_np = np.array(image)
    
    # Convert to grayscale
    if len(img_np.shape) == 3:
        gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
    else:
        gray = img_np.copy()
    
    # Edge detection
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    
    # Dilate to connect edge fragments
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    edges = cv2.dilate(edges, kernel, iterations=2)
    
    # Find contours
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if not contours:
        logger.debug("Perspective correction: No contours found, returning original")
        return image
    
    # Sort by area, take largest
    contours = sorted(contours, key=cv2.contourArea, reverse=True)
    
    h, w = gray.shape[:2]
    img_area = h * w
    
    for contour in contours[:5]:  # Check top 5 largest contours
        area = cv2.contourArea(contour)
        
        # Skip if too small (< 20% of image) or too large (> 98%)
        if area < img_area * 0.20 or area > img_area * 0.98:
            continue
        
        # Approximate to polygon
        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
        
        # Need exactly 4 corners for perspective transform
        if len(approx) == 4:
            pts = approx.reshape(4, 2).astype(np.float32)
            
            # Order points: top-left, top-right, bottom-right, bottom-left
            ordered = _order_points(pts)
            
            # Compute output dimensions
            width_top = np.linalg.norm(ordered[1] - ordered[0])
            width_bottom = np.linalg.norm(ordered[2] - ordered[3])
            height_left = np.linalg.norm(ordered[3] - ordered[0])
            height_right = np.linalg.norm(ordered[2] - ordered[1])
            
            out_w = int(max(width_top, width_bottom))
            out_h = int(max(height_left, height_right))
            
            # Sanity check: don't produce tiny images
            if out_w < 100 or out_h < 100:
                continue
            
            dst = np.array([
                [0, 0],
                [out_w - 1, 0],
                [out_w - 1, out_h - 1],
                [0, out_h - 1]
            ], dtype=np.float32)
            
            M = cv2.getPerspectiveTransform(ordered, dst)
            warped = cv2.warpPerspective(img_np, M, (out_w, out_h))
            
            logger.info("✅ Perspective corrected: %dx%d → %dx%d", w, h, out_w, out_h)
            return Image.fromarray(warped)
    
    logger.debug("Perspective correction: No suitable quadrilateral found")
    return image


def _order_points(pts: np.ndarray) -> np.ndarray:
    """Order 4 points as: top-left, top-right, bottom-right, bottom-left."""
    rect = np.zeros((4, 2), dtype=np.float32)
    
    # Top-left has smallest sum, bottom-right has largest sum
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    
    # Top-right has smallest difference, bottom-left has largest difference
    d = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(d)]
    rect[3] = pts[np.argmax(d)]
    
    return rect


# ═══════════════════════════════════════════════════════════════════
# 2. REGISTRATION AUGMENTATION
# ═══════════════════════════════════════════════════════════════════

def generate_augmented_views(image: Image.Image) -> List[Tuple[str, Image.Image]]:
    """Generate augmented versions of a document for robust registration.
    
    Returns list of (augmentation_name, augmented_image).
    The original image is always included as the first entry.
    
    Augmentations:
    - Original (always)
    - Horizontal flip (simulates mirror/reversed scan)
    - Perspective warp left (simulates left-angle camera)
    - Perspective warp right (simulates right-angle camera)
    """
    augmented = [("original", image)]
    
    img_np = np.array(image)
    h, w = img_np.shape[:2]
    
    # 1. Horizontal Flip
    flipped = cv2.flip(img_np, 1)
    augmented.append(("h_flip", Image.fromarray(flipped)))
    
    # 2. Perspective Warp — Left angle (~10° tilt)
    warp_amount = int(w * 0.08)  # 8% warp
    src_pts = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    
    dst_left = np.float32([
        [warp_amount, warp_amount],   # top-left pushed right+down
        [w, 0],                        # top-right stays
        [w, h],                        # bottom-right stays
        [warp_amount, h - warp_amount] # bottom-left pushed right+up
    ])
    M_left = cv2.getPerspectiveTransform(src_pts, dst_left)
    warped_left = cv2.warpPerspective(img_np, M_left, (w, h))
    augmented.append(("persp_left", Image.fromarray(warped_left)))
    
    # 3. Perspective Warp — Right angle (~10° tilt)
    dst_right = np.float32([
        [0, 0],                                    # top-left stays
        [w - warp_amount, warp_amount],            # top-right pushed left+down
        [w - warp_amount, h - warp_amount],        # bottom-right pushed left+up
        [0, h]                                      # bottom-left stays
    ])
    M_right = cv2.getPerspectiveTransform(src_pts, dst_right)
    warped_right = cv2.warpPerspective(img_np, M_right, (w, h))
    augmented.append(("persp_right", Image.fromarray(warped_right)))
    
    return augmented


# ═══════════════════════════════════════════════════════════════════
# 3. TOP-K-OF-N SCORING
# ═══════════════════════════════════════════════════════════════════

def topk_weighted_score(
    region_scores: List[float],
    region_weights: List[float],
    keep_ratio: float = 0.7,
) -> float:
    """Compute weighted score using only the top-K best regions.
    
    This handles occlusion (fingers, folds) by ignoring the worst regions.
    
    Args:
        region_scores: Raw similarity scores per region for a candidate doc
        region_weights: Weight per region
        keep_ratio: Fraction of regions to keep (0.7 = keep best 70%)
    
    Returns:
        Robust weighted score (normalized to [0,1])
    
    Example:
        10 regions, keep_ratio=0.7 → use best 7, ignore worst 3
        If 2 regions are occluded (score=0), they get dropped.
    """
    assert len(region_scores) == len(region_weights)
    n = len(region_scores)
    k = max(2, int(n * keep_ratio))  # Keep at least 2 regions
    
    # Pair scores with weights, sort by score descending
    paired = sorted(zip(region_scores, region_weights), key=lambda x: x[0], reverse=True)
    
    # Take top K
    top_k = paired[:k]
    
    # Weighted average of top K (re-normalize weights)
    total_weight = sum(w for _, w in top_k)
    if total_weight == 0:
        return 0.0
    
    score = sum(s * w for s, w in top_k) / total_weight
    return score
