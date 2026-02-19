"""Document preprocessing using SAM (Segment Anything Model).

Replaces aggressive background removal with intelligent document boundary detection.
Preserves document content while removing background clutter.

Supports:
- MobileSAM: Lightweight (40MB), 60x faster than SAM
- FastSAM: YOLOv8-based, real-time performance
"""

import io
import logging
import cv2
import numpy as np
from PIL import Image, ImageOps
from typing import Literal

logger = logging.getLogger(__name__)

# Model choice
SAM_MODEL: Literal["mobile", "fast"] = "fast"  # mobile=MobileSAM, fast=FastSAM

# Singleton model instance
_SAM_MODEL = None

def _load_sam_model():
    """Load SAM model (lazy initialization)."""
    global _SAM_MODEL
    
    if _SAM_MODEL is not None:
        return _SAM_MODEL
    
    try:
        if SAM_MODEL == "mobile":
            # MobileSAM (requires mobile_sam package)
            from mobile_sam import sam_model_registry, SamPredictor
            import torch
            
            device = "cpu"  # Force CPU for stability
            model_type = "vit_t"
            checkpoint_path = "weights/mobile_sam.pt"
            
            sam = sam_model_registry[model_type](checkpoint=checkpoint_path)
            sam.to(device=device)
            sam.eval()
            
            _SAM_MODEL = SamPredictor(sam)
            logger.info(f"MobileSAM loaded on {device}")
            
        elif SAM_MODEL == "fast":
            # FastSAM (Ultralytics YOLOv8-based)
            from ultralytics import FastSAM
            
            # Auto-downloads model if not present
            _SAM_MODEL = FastSAM("FastSAM-x.pt")  # or FastSAM-s.pt for smaller/faster
            logger.info("FastSAM loaded successfully")
            
        return _SAM_MODEL
        
    except Exception as e:
        logger.error(f"Failed to load SAM model: {e}")
        return None


def _apply_illumination_normalization(pil_image: Image.Image) -> Image.Image:
    """Apply CLAHE to normalize lighting, especially for book spine shadows."""
    open_cv_image = np.array(pil_image.convert("RGB"))
    lab = cv2.cvtColor(open_cv_image, cv2.COLOR_RGB2LAB)
    l, a, b = cv2.split(lab)

    clahe = cv2.createCLAHE(clipLimit=1.0, tileGridSize=(8, 8))
    cl = clahe.apply(l)

    limg = cv2.merge((cl, a, b))
    final_img = cv2.cvtColor(limg, cv2.COLOR_LAB2RGB)
    
    return Image.fromarray(final_img)


def _segment_document_fastsam(image: np.ndarray) -> np.ndarray | None:
    """Segment document using FastSAM.
    
    Args:
        image: RGB numpy array (H, W, 3)
        
    Returns:
        Binary mask (H, W) where 1=document, 0=background
        None if segmentation fails
    """
    model = _load_sam_model()
    if model is None:
        return None
    
    try:
        # Run inference with automatic everything mode
        # Lower conf threshold to catch more document content
        results = model(
            image,
            device="cpu",  # Force CPU to avoid CUDA OOM (Requires ~4GB VRAM otherwise)
            retina_masks=True,
            imgsz=1024,
            conf=0.25,  # Lower threshold to preserve more content
            iou=0.7,    # Lower IOU to allow overlapping segments
        )
        
        if len(results) == 0 or len(results[0].masks) == 0:
            logger.warning("FastSAM: No masks detected")
            return None
        
        # Get masks sorted by area (largest first)
        masks_data = results[0].masks.data.cpu().numpy()  # (N, H, W)
        areas = [mask.sum() for mask in masks_data]
        
        # Strategy: Merge all large masks (>10% of image) to preserve multi-page documents
        h, w = image.shape[:2]
        total_pixels = h * w
        min_area = total_pixels * 0.05  # Minimum 5% of image to be considered
        
        # Combine all significant masks
        combined_mask = np.zeros((h, w), dtype=np.uint8)
        for mask, area in zip(masks_data, areas):
            if area > min_area:
                combined_mask = np.maximum(combined_mask, (mask > 0.5).astype(np.uint8))
        
        # If no significant masks, use largest
        if combined_mask.sum() == 0:
            largest_idx = np.argmax(areas)
            combined_mask = (masks_data[largest_idx] > 0.5).astype(np.uint8)
        
        return combined_mask
        
    except Exception as e:
        logger.error(f"FastSAM segmentation error: {e}")
        return None


def _segment_document_mobilesam(image: np.ndarray) -> np.ndarray | None:
    """Segment document using MobileSAM with center point prompt.
    
    Strategy: Assume document is in center, use center point as positive prompt.
    
    Args:
        image: RGB numpy array (H, W, 3)
        
    Returns:
        Binary mask (H, W) where 1=document, 0=background
        None if segmentation fails
    """
    predictor = _load_sam_model()
    if predictor is None:
        return None
    
    try:
        # Set image for embedding
        predictor.set_image(image)
        
        h, w = image.shape[:2]
        
        # Generate point prompts (center of image, assuming document is centered)
        input_point = np.array([[w // 2, h // 2]])
        input_label = np.array([1])  # 1 = foreground
        
        # Predict mask
        masks, scores, logits = predictor.predict(
            point_coords=input_point,
            point_labels=input_label,
            multimask_output=False,
        )
        
        # Return best mask
        return masks[0].astype(np.uint8)
        
    except Exception as e:
        logger.error(f"MobileSAM segmentation error: {e}")
        return None


def _refine_mask(mask: np.ndarray) -> np.ndarray:
    """Refine mask using morphological operations.
    
    Removes small noise and fills holes in document mask.
    """
    # Remove small noise
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    
    # Fill holes in document
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    
    return mask


def _apply_mask_with_padding(image: np.ndarray, mask: np.ndarray, padding_px: int = 10) -> Image.Image:
    """Apply mask to image and crop to bounding box with padding.
    
    Args:
        image: RGB image (H, W, 3)
        mask: Binary mask (H, W)
        padding_px: Padding around document in pixels
        
    Returns:
        Cropped PIL Image with black background
    """
    # Find bounding box of document
    coords = np.column_stack(np.where(mask > 0))
    if len(coords) == 0:
        logger.warning("Empty mask, returning original image")
        return Image.fromarray(image)
    
    y_min, x_min = coords.min(axis=0)
    y_max, x_max = coords.max(axis=0)
    
    # Add padding (with bounds checking)
    h, w = image.shape[:2]
    y_min = max(0, y_min - padding_px)
    x_min = max(0, x_min - padding_px)
    y_max = min(h, y_max + padding_px)
    x_max = min(w, x_max + padding_px)
    
    # Crop to bounding box
    cropped_image = image[y_min:y_max, x_min:x_max]
    cropped_mask = mask[y_min:y_max, x_min:x_max]
    
    # Create black background
    result = np.zeros_like(cropped_image)
    
    # Apply mask (keep document pixels, black everywhere else)
    result[cropped_mask > 0] = cropped_image[cropped_mask > 0]
    
    return Image.fromarray(result)


def preprocess_from_bytes(image_bytes: bytes, mode: str = "single") -> Image.Image:
    """Preprocess document image.
    
    Assumption: Input image is already cropped by the client (App).
    We only apply Illumination Normalization (CLAHE).
    Segmentation is SKIPPED to avoid double-cropping artifacts (server re-cropping an already cropped image).
    """
    try:
        # 1. Load Image
        image = Image.open(io.BytesIO(image_bytes))
        image = ImageOps.exif_transpose(image)
        
        # 2. Illumination normalization (CLAHE)
        # CLAHE enhances texture for fingerprinting but adds visual noise.
        # We process the full cropped image provided by the client.
        result = _apply_illumination_normalization(image)
        
        return result
        
    except Exception as e:
        logger.error(f"Preprocessing error: {e}")
        # Fallback: Return original RGB
        try:
            backup = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            return backup
        except:
            raise ValueError("Corrupt image data")


def preprocess_document_image(path: str) -> Image.Image:
    """Helper for local file processing."""
    with open(path, "rb") as f:
        return preprocess_from_bytes(f.read())
