import torch
import os
import sys
from rembg import new_session

def download_dinov2():
    print("Downloading DINOv2 ViT-L/14 model (Facebook Research)...")
    try:
        # This will trigger download to ~/.cache/torch/hub/checkpoints
        model = torch.hub.load("facebookresearch/dinov2", "dinov2_vitl14")
        print("✅ DINOv2 downloaded successfully.")
    except Exception as e:
        print(f"❌ DINOv2 download failed: {e}")
        sys.exit(1)

def download_u2net():
    print("Downloading U-2-Net model (for Background Removal)...")
    try:
        # Initializing session triggers download if not present in ~/.u2net
        session = new_session("u2net")
        print("✅ U-2-Net downloaded successfully.")
    except Exception as e:
        print(f"❌ U-2-Net download failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    print("=== ARCH-FINGERPRINT Model Pre-Downloader ===")
    print("Ensuring all AI models are cached locally to prevent runtime timeouts.")
    
    download_dinov2()
    download_u2net()
    
    print("\n=== All models are ready! You can now start the backend server. ===")
