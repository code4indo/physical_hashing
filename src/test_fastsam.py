#!/usr/bin/env python3
"""Quick test of FastSAM preprocessing on real documents."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from PIL import Image
import matplotlib.pyplot as plt

def test_fastsam(image_path: str):
    """Test FastSAM on a single image."""
    
    print(f"📸 Testing FastSAM on: {Path(image_path).name}")
    
    # Load original
    with open(image_path, "rb") as f:
        image_bytes = f.read()
    
    original = Image.open(image_path).convert("RGB")
    print(f"   Original size: {original.size}")
    
    # Process with FastSAM
    from arch_fingerprint.ai.preprocessing_sam import preprocess_from_bytes
    result = preprocess_from_bytes(image_bytes)
    print(f"   Processed size: {result.size}")
    
    # Create comparison
    fig, axes = plt.subplots(1, 2, figsize=(14, 7))
    
    axes[0].imshow(original)
    axes[0].set_title(f"Original\n{original.size[0]}x{original.size[1]}", 
                     fontsize=12, fontweight='bold')
    axes[0].axis('off')
    
    axes[1].imshow(result)
    axes[1].set_title(f"FastSAM Processed\n{result.size[0]}x{result.size[1]}", 
                     fontsize=12, fontweight='bold', color='green')
    axes[1].axis('off')
    
    plt.tight_layout()
    
    # Save
    output_path = Path("data/uploads") / f"fastsam_test_{Path(image_path).stem}.png"
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"   ✅ Saved to: {output_path}")
    
    # Also save processed image separately
    processed_path = Path("data/uploads") / f"fastsam_only_{Path(image_path).stem}.png"
    result.save(processed_path)
    print(f"   💾 Processed image: {processed_path}")
    
    return result


if __name__ == "__main__":
    # Find first image
    uploads_dir = Path("data/uploads")
    test_images = [
        p for p in uploads_dir.glob("*.jpg") 
        if "test_sam" not in p.name and "comparison" not in p.name and "fastsam" not in p.name
    ]
    
    if test_images:
        print("=" * 60)
        print("FastSAM Document Preprocessing Test")
        print("=" * 60)
        print()
        
        for img in test_images[:2]:  # Test first 2 images
            test_fastsam(str(img))
            print()
        
        print("=" * 60)
        print("✅ Testing complete! Check data/uploads/fastsam_*.png")
        print("=" * 60)
    else:
        print("No test images found")
