#!/usr/bin/env python3
"""Setup script for SAM models.

Downloads and tests FastSAM or MobileSAM for document preprocessing.
"""

import sys
import subprocess
import os
from pathlib import Path

def install_dependencies():
    """Install required packages for SAM."""
    print("📦 Installing SAM dependencies...")
    
    # FastSAM (recommended - easier setup)
    packages = [
        "ultralytics",  # Contains FastSAM
    ]
    
    # Uncomment for MobileSAM (requires additional setup)
    # packages.extend([
    #     "mobile-sam",
    #     "segment-anything",
    # ])
    
    for package in packages:
        print(f"   Installing {package}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
    
    print("✅ Dependencies installed!\n")


def download_fastsam_model():
    """Download FastSAM model (auto-downloaded on first use)."""
    print("🔽 FastSAM model will auto-download on first use")
    print("   Model size: ~138MB (FastSAM-x) or ~23MB (FastSAM-s)")
    print("   Location: ~/.cache/ultralytics/\n")


def download_mobilesam_model():
    """Download MobileSAM checkpoint."""
    print("🔽 Downloading MobileSAM model...")
    
    weights_dir = Path("weights")
    weights_dir.mkdir(exist_ok=True)
    
    model_url = "https://github.com/ChaoningZhang/MobileSAM/blob/master/weights/mobile_sam.pt?raw=true"
    model_path = weights_dir / "mobile_sam.pt"
    
    if model_path.exists():
        print(f"   ✅ Model already exists: {model_path}\n")
        return
    
    import urllib.request
    print(f"   Downloading from GitHub...")
    urllib.request.urlretrieve(model_url, model_path)
    print(f"   ✅ Saved to: {model_path}\n")


def test_preprocessing():
    """Test SAM preprocessing on sample image."""
    print("🧪 Testing SAM preprocessing...")
    
    # Find a test image
    uploads_dir = Path("data/uploads")
    if not uploads_dir.exists():
        print("   ⚠️  No test images found in data/uploads/")
        return
    
    test_images = list(uploads_dir.glob("*.jpg")) + list(uploads_dir.glob("*.png"))
    if not test_images:
        print("   ⚠️  No .jpg or .png files found in data/uploads/")
        return
    
    test_image = test_images[0]
    print(f"   Testing with: {test_image.name}")
    
    try:
        # Import preprocessing
        from arch_fingerprint.ai.preprocessing_sam import preprocess_document_image
        
        # Process image
        result = preprocess_document_image(str(test_image))
        
        # Save result
        output_path = uploads_dir / f"test_sam_output_{test_image.stem}.jpg"
        result.save(output_path)
        
        print(f"   ✅ Processed successfully!")
        print(f"   📸 Output saved to: {output_path}")
        print(f"   📐 Output size: {result.size}")
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Main setup flow."""
    print("=" * 60)
    print("SAM Document Preprocessing Setup")
    print("=" * 60)
    print()
    
    # Step 1: Install dependencies
    install_dependencies()
    
    # Step 2: Download models
    print("📥 Model Selection:")
    print("   [1] FastSAM (recommended - automatic download, YOLOv8-based)")
    print("   [2] MobileSAM (manual download, smaller but requires more setup)")
    print()
    
    # Default to FastSAM
    choice = input("Choose model [1/2, default=1]: ").strip() or "1"
    
    if choice == "1":
        download_fastsam_model()
    elif choice == "2":
        download_mobilesam_model()
    else:
        print("Invalid choice, using FastSAM (default)")
        download_fastsam_model()
    
    # Step 3: Test
    print("🎯 Testing preprocessing...")
    test_preprocessing()
    
    print()
    print("=" * 60)
    print("✅ Setup Complete!")
    print("=" * 60)
    print()
    print("📝 Next Steps:")
    print("   1. Check the test output image quality")
    print("   2. Update worker to use SAM:")
    print("      from arch_fingerprint.ai import preprocessing_sam as preprocessing")
    print("   3. Restart the server")
    print()


if __name__ == "__main__":
    main()
