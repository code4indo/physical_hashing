"""AI-Based Preprocessing for archival documents.

Replaces traditional OpenCV contour detection with Deep Learning background removal (U-Net).
Preserves torn/irregular edges crucial for identification, as per expert recommendation.
"""

import io
import logging
import cv2
import numpy as np
from PIL import Image, ImageOps
from rembg import remove, new_session

logger = logging.getLogger(__name__)

# Singleton ONNX Runtime session (initialized on import to avoid re-loading model per request)
# Using 'u2net' model (~176MB) which is robust for general object removal.
try:
    # Explicitly use CUDA if available, fallback to CPU
    import torch
    providers = ['CUDAExecutionProvider', 'CPUExecutionProvider'] if torch.cuda.is_available() else ['CPUExecutionProvider']
    _SESSION = new_session("u2net", providers=providers)
    logger.info(f"Rembg session initialized with providers: {providers}")
except Exception as e:
    logger.error(f"Failed to load rembg model: {e}")
    _SESSION = None

def _apply_illumination_normalization(pil_image: Image.Image) -> Image.Image:
    """Apply CLAHE to normalize lighting, especially for book spine shadows."""
    # Convert PIL to OpenCV (LAB space is best for lighting normalization)
    open_cv_image = np.array(pil_image.convert("RGB"))
    lab = cv2.cvtColor(open_cv_image, cv2.COLOR_RGB2LAB)
    l, a, b = cv2.split(lab)

    # Apply CLAHE to L-channel
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    cl = clahe.apply(l)

    # Merge back and convert to RGB
    limg = cv2.merge((cl, a, b))
    final_img = cv2.cvtColor(limg, cv2.COLOR_LAB2RGB)
    
    return Image.fromarray(final_img)


def _remove_fingers(pil_image: Image.Image) -> Image.Image:
    """Detect and remove fingers from document edges using skin color segmentation and inpainting."""
    # Convert to OpenCV format
    img = np.array(pil_image.convert("RGB"))
    
    # Convert to HSV for skin detection
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
    
    # Generic skin color range in HSV
    lower_skin = np.array([0, 20, 70], dtype=np.uint8)
    upper_skin = np.array([20, 255, 255], dtype=np.uint8)
    
    # Create skin mask
    mask = cv2.inRange(hsv, lower_skin, upper_skin)
    
    # Refine mask: morphological operations to remove noise
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_DILATE, kernel, iterations=2)
    
    # Only keep mask regions near the edges (assumption: fingers hold the book from sides)
    h, w = mask.shape
    border_margin = int(min(h, w) * 0.25) # Check outer 20% of image
    
    # Create a mask for the edges
    edge_mask = np.zeros_like(mask)
    edge_mask[0:h, 0:border_margin] = 255       # Left
    edge_mask[0:h, w-border_margin:w] = 255     # Right
    edge_mask[h-border_margin:h, 0:w] = 255     # Bottom
    
    # Combine skin mask with edge mask
    final_mask = cv2.bitwise_and(mask, edge_mask)
    
    # Inpaint (remove fingers)
    # Using Telea's algorithm which is fast and effective for small areas
    if np.count_nonzero(final_mask) > 0:
        inpainted = cv2.inpaint(img, final_mask, 3, cv2.INPAINT_TELEA)
        return Image.fromarray(inpainted)
        
    return pil_image


def preprocess_from_bytes(image_bytes: bytes, mode: str = "single") -> Image.Image:
    """Remove background from document image using AI segmentation.
    
    Returns RGB image on BLACK background, cropped to content bounds.
    Black background is preferred for DINOv2 embedding space separation from object.
    
    Args:
        image_bytes: Raw image file bytes.
        
    Returns:
        PIL.Image (RGB) ready for model inference.
    """
    try:
        # 1. Load Image
        image = Image.open(io.BytesIO(image_bytes))
        
        # Apply orientation metadata (Portrait vs Landscape)
        image = ImageOps.exif_transpose(image)
        
        # 2. Remove Background (if session available)
        if _SESSION:
            # Returns RGBA image with transparent background where background was removed
            # alpha_matting=True ensures smoother edges for torn paper
            image = remove(image, session=_SESSION, alpha_matting=True)
        else:
            logger.warning("REMBG session unavailable, skipping background removal.")

        # 3. Handle Transparency -> Black Background
        if image.mode == 'RGBA':
            # Create black background
            bg = Image.new("RGB", image.size, (0, 0, 0))
            
            # Composite using alpha channel as mask
            # This keeps the object pixels and makes transparent pixels black
            bg.paste(image, mask=image.split()[3])
            
            # 4. Auto-Crop to Content (Trim empty transparent/black borders)
            bbox = image.getbbox() 
            if bbox:
                bg = bg.crop(bbox)
            
            # 5. Expert Recommendation: Illumination Normalization
            bg = _apply_illumination_normalization(bg)

            # 6. Book Mode Specific: Finger Removal
            if mode == "book":
                bg = _remove_fingers(bg)
            
            return bg
        else:
            return image.convert("RGB")

    except Exception as e:
        logger.error(f"Preprocessing error: {e}")
        # Fallback: Just return original RGB to allow process to continue
        try:
             backup = Image.open(io.BytesIO(image_bytes)).convert("RGB")
             return backup
        except:
             raise ValueError("Corrupt image data")

def preprocess_document_image(path: str) -> Image.Image:
    """Helper for local file processing."""
    with open(path, "rb") as f:
        return preprocess_from_bytes(f.read())
