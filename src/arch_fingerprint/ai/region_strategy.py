"""Region cropping strategies for document DNA fingerprinting.

Each strategy defines how a document image is divided into regions,
with each region contributing a weighted embedding to the document's
visual fingerprint ("DNA").

Used by both:
- Worker (queue.py) for document registration
- Search API (search.py) for document identification

More regions = more unique fingerprint = better "barcode" capability,
but also more computation time per document.
"""

from typing import List, Tuple
from PIL import Image


# Type alias: (region_name, crop_box_or_None_for_global, weight)
RegionSpec = Tuple[str, Tuple[float, float, float, float] | None, float]


def get_region_specs(strategy: str) -> List[RegionSpec]:
    """Return region specifications for a given strategy.

    Each spec is (name, crop_ratios, weight).
    crop_ratios is (left%, top%, right%, bottom%) as fractions [0..1],
    or None for the global (full image) region.
    
    All weights sum to 1.0.
    
    Strategies:
        "4-strip"  — 4 horizontal strips + global (default)
        "9-grid"   — 3×3 grid + global  
        "16-grid"  — 4×4 grid + global
    """
    if strategy == "4-strip":
        return [
            ("Global",        None,                           0.20),
            ("Header",        (0.0, 0.0, 1.0, 0.25),         0.20),
            ("Middle",        (0.1, 0.35, 0.9, 0.65),        0.30),
            ("Footer",        (0.0, 0.80, 1.0, 1.0),         0.30),
        ]
    
    elif strategy == "9-grid":
        # 3×3 grid + global = 10 regions
        # Weight distribution: Global 10%, each cell ~10%
        w = 0.10  # per cell weight
        return [
            ("Global",        None,                           0.10),
            ("TL",            (0.0,  0.0,  0.33, 0.33),      w),
            ("TC",            (0.33, 0.0,  0.66, 0.33),      w),
            ("TR",            (0.66, 0.0,  1.0,  0.33),      w),
            ("ML",            (0.0,  0.33, 0.33, 0.66),      w),
            ("MC",            (0.33, 0.33, 0.66, 0.66),      w),
            ("MR",            (0.66, 0.33, 1.0,  0.66),      w),
            ("BL",            (0.0,  0.66, 0.33, 1.0),       w),
            ("BC",            (0.33, 0.66, 0.66, 1.0),       w),
            ("BR",            (0.66, 0.66, 1.0,  1.0),       w),
        ]
    
    elif strategy == "16-grid":
        # 4×4 grid + global = 17 regions
        # Weight: Global 7%, each cell ~5.8%
        w = 0.058  # ~5.8% per cell, 16 cells = 93%
        rows = [0.0, 0.25, 0.50, 0.75, 1.0]
        cols = [0.0, 0.25, 0.50, 0.75, 1.0]
        
        specs: List[RegionSpec] = [("Global", None, 0.07)]
        labels = ["1", "2", "3", "4"]
        
        for r in range(4):
            for c in range(4):
                name = f"R{labels[r]}C{labels[c]}"
                box = (cols[c], rows[r], cols[c + 1], rows[r + 1])
                specs.append((name, box, w))
        
        return specs
    
    else:
        raise ValueError(f"Unknown region strategy: {strategy!r}. Use '4-strip', '9-grid', or '16-grid'.")


def crop_regions(image: Image.Image, strategy: str) -> List[Tuple[str, Image.Image, float]]:
    """Crop an image into regions based on the strategy.
    
    Returns list of (region_name, cropped_image, weight).
    """
    width, height = image.size
    specs = get_region_specs(strategy)
    
    result = []
    for name, box, weight in specs:
        if box is None:
            # Global — use the full image
            result.append((name, image, weight))
        else:
            left = int(width * box[0])
            top = int(height * box[1])
            right = int(width * box[2])
            bottom = int(height * box[3])
            
            # Ensure minimum crop size (at least 32×32 for DINOv2)
            if right - left < 32 or bottom - top < 32:
                result.append((name, image, weight))
            else:
                crop = image.crop((left, top, right, bottom))
                result.append((name, crop, weight))
    
    return result


# For display / settings UI
STRATEGY_INFO = {
    "4-strip": {
        "label": "4 Strips",
        "description": "4 horizontal strips + global (fast)",
        "total_regions": 4,
        "speed": "~2-4 sec",
    },
    "9-grid": {
        "label": "9 Grid (3×3)",
        "description": "3×3 grid + global (balanced)",
        "total_regions": 10,
        "speed": "~5-10 sec",
    },
    "16-grid": {
        "label": "16 Grid (4×4)",
        "description": "4×4 grid + global (most accurate)",
        "total_regions": 17,
        "speed": "~10-18 sec",
    },
}
