import sys
import torch
from PIL import Image
from rembg import remove, new_session
import time
import numpy as np

def test_rembg():
    print("Testing 1: U-2-Net (Background Removal)...")
    try:
        start_time = time.time()
        # Create a simple red square image 
        # (Must be non-trivial to ensure model runs)
        img = Image.new('RGB', (300, 300), color='red')
        
        # Draw something
        pixels = np.array(img)
        pixels[100:200, 100:200] = [0, 255, 0] # Green square inside
        img = Image.fromarray(pixels)
        
        # Run inference
        # This uses ONNX Runtime + Numba
        session = new_session("u2net")
        result = remove(img, session=session)
        
        # Check result
        if result.mode == 'RGBA':
            print(f"✅ REMBG Inference Success ({time.time() - start_time:.2f}s)")
            return True
        else:
            print("❌ REMBG returned invalid format.")
            return False
            
    except Exception as e:
        print(f"❌ REMBG Error: {e}")
        return False

def test_dinov2():
    print("\nTesting 2: DINOv2 (Feature Extraction)...")
    try:
        # Check CUDA
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Device: {device}")
        
        model = torch.hub.load("facebookresearch/dinov2", "dinov2_vitl14")
        model.to(device)
        model.eval()
        
        # Dummy input
        dummy_img = torch.randn(1, 3, 518, 518).to(device)
        
        with torch.no_grad():
            output = model(dummy_img)
            
        print(f"✅ DINOv2 Inference Success! Embedding shape: {output.shape}")
        
        embedding_dim = output.shape[1]
        if embedding_dim == 1024:
             print("✅ Embedding dimension correct (1024).")
             return True
        else:
             print(f"❌ Dimension mismatch: {embedding_dim}")
             return False

    except Exception as e:
        print(f"❌ DINOv2 Error: {e}")
        return False

if __name__ == "__main__":
    print("=== ARCH-FINGERPRINT DIAGNOSTIC ===")
    
    rembg_ok = test_rembg()
    dino_ok = test_dinov2()
    
    if rembg_ok and dino_ok:
        print("\n✅ SYSTEM IS READY FOR UPLOAD")
        sys.exit(0)
    else:
        print("\n❌ SYSTEM CHECK FAILED")
        sys.exit(1)
