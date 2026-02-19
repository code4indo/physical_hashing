#!/usr/bin/env python3
"""Compare U-2-Net vs FastSAM preprocessing side-by-side.

Generates visual comparison to show quality differences.
"""

import sys
from pathlib import Path
import matplotlib.pyplot as plt
from PIL import Image
import numpy as np

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent))

def compare_methods(image_path: str):
    """Compare preprocessing methods on a single image."""
    
    print(f"📸 Processing: {Path(image_path).name}")
    
    # Load original
    with open(image_path, "rb") as f:
        image_bytes = f.read()
    
    original = Image.open(image_path).convert("RGB")
    
    # Method 1: U-2-Net (current)
    print("   [1/2] Running U-2-Net preprocessing...")
    try:
        from arch_fingerprint.ai.preprocessing import preprocess_from_bytes as u2net_preprocess
        u2net_result = u2net_preprocess(image_bytes)
    except Exception as e:
        print(f"      ❌ U-2-Net failed: {e}")
        u2net_result = None
    
    # Method 2: FastSAM
    print("   [2/2] Running FastSAM preprocessing...")
    try:
        from arch_fingerprint.ai.preprocessing_sam import preprocess_from_bytes as sam_preprocess
        sam_result = sam_preprocess(image_bytes)
    except Exception as e:
        print(f"      ❌ FastSAM failed: {e}")
        sam_result = None
    
    # Create comparison figure
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    
    # Original
    axes[0].imshow(original)
    axes[0].set_title("Original Image", fontsize=14, fontweight='bold')
    axes[0].axis('off')
    
    # U-2-Net
    if u2net_result:
        axes[1].imshow(u2net_result)
        axes[1].set_title(f"U-2-Net (rembg)\nSize: {u2net_result.size}", 
                          fontsize=14, fontweight='bold', color='red')
    else:
        axes[1].text(0.5, 0.5, "Failed", ha='center', va='center', fontsize=20)
        axes[1].set_title("U-2-Net (rembg)", fontsize=14, fontweight='bold', color='red')
    axes[1].axis('off')
    
    # FastSAM
    if sam_result:
        axes[2].imshow(sam_result)
        axes[2].set_title(f"FastSAM (YOLOv8)\nSize: {sam_result.size}", 
                          fontsize=14, fontweight='bold', color='green')
    else:
        axes[2].text(0.5, 0.5, "Failed", ha='center', va='center', fontsize=20)
        axes[2].set_title("FastSAM (YOLOv8)", fontsize=14, fontweight='bold', color='green')
    axes[2].axis('off')
    
    plt.tight_layout()
    
    # Save comparison
    output_path = Path("data/uploads") / f"comparison_{Path(image_path).stem}.png"
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"   ✅ Comparison saved to: {output_path}")
    
    # Show difference metrics
    print("\n📊 Quality Metrics:")
    
    if u2net_result and sam_result:
        # Calculate content preservation (non-black pixels)
        u2net_np = np.array(u2net_result)
        sam_np = np.array(sam_result)
        
        u2net_content = np.sum(u2net_np > 10) / u2net_np.size * 100
        sam_content = np.sum(sam_np > 10) / sam_np.size * 100
        
        print(f"   U-2-Net content preserved: {u2net_content:.2f}%")
        print(f"   FastSAM content preserved: {sam_content:.2f}%")
        print(f"   Difference: {sam_content - u2net_content:+.2f}% (higher = more preserved)")
    
    return original, u2net_result, sam_result


def main():
    """Run comparison on test images."""
    
    print("=" * 60)
    print("U-2-Net vs FastSAM Preprocessing Comparison")
    print("=" * 60)
    print()
    
    # Find test images
    uploads_dir = Path("data/uploads")
    test_images = list(uploads_dir.glob("*.jpg"))[:3]  # Test first 3 images
    
    if not test_images:
        print("❌ No test images found in data/uploads/")
        return
    
    print(f"Found {len(test_images)} test images\n")
    
    for i, img_path in enumerate(test_images, 1):
        print(f"\n{'='*60}")
        print(f"Image {i}/{len(test_images)}")
        print(f"{'='*60}")
        compare_methods(str(img_path))
    
    print("\n" + "=" * 60)
    print("✅ Comparison Complete!")
    print("=" * 60)
    print("\nCheck data/uploads/comparison_*.png for results")


if __name__ == "__main__":
    main()
