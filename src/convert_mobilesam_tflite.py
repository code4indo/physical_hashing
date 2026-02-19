#!/usr/bin/env python3
"""
Convert MobileSAM PyTorch model to TFLite for on-device inference.

This script:
1. Downloads MobileSAM checkpoint
2. Exports to ONNX
3. Converts ONNX to TFLite
4. Validates the output

Output: arch_fingerprint_gui/assets/models/mobile_sam.tflite
"""

import os
import sys
import torch
import numpy as np
import urllib.request

# ── Config ──────────────────────────────────────────────────────
CHECKPOINT_URL = "https://raw.githubusercontent.com/ChaoningZhang/MobileSAM/master/weights/mobile_sam.pt"
CHECKPOINT_PATH = "/tmp/mobile_sam.pt"
ONNX_PATH = "/tmp/mobile_sam_encoder.onnx"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 
                          "..", "arch_fingerprint_gui", "assets", "models")
TFLITE_PATH = os.path.join(OUTPUT_DIR, "mobile_sam.tflite")

INPUT_SIZE = 1024  # MobileSAM encoder input


def download_checkpoint():
    """Download MobileSAM checkpoint if not exists."""
    if os.path.exists(CHECKPOINT_PATH):
        size_mb = os.path.getsize(CHECKPOINT_PATH) / (1024 * 1024)
        print(f"✅ Checkpoint already exists ({size_mb:.1f}MB)")
        return True

    print(f"🔄 Downloading MobileSAM checkpoint...")
    print(f"   URL: {CHECKPOINT_URL}")
    
    try:
        urllib.request.urlretrieve(CHECKPOINT_URL, CHECKPOINT_PATH)
        size_mb = os.path.getsize(CHECKPOINT_PATH) / (1024 * 1024)
        print(f"✅ Downloaded: {size_mb:.1f}MB")
        return True
    except Exception as e:
        print(f"❌ Download failed: {e}")
        return False


def export_image_encoder_onnx():
    """Export MobileSAM image encoder to ONNX."""
    from mobile_sam import sam_model_registry

    print("🔄 Loading MobileSAM model...")
    model_type = "vit_t"
    sam = sam_model_registry[model_type](checkpoint=CHECKPOINT_PATH)
    sam.eval()

    # Extract image encoder only (for on-device use)
    encoder = sam.image_encoder
    encoder.eval()

    print(f"✅ Model loaded (type: {model_type})")
    print(f"   Encoder parameters: {sum(p.numel() for p in encoder.parameters()) / 1e6:.1f}M")

    # Create dummy input
    dummy_input = torch.randn(1, 3, INPUT_SIZE, INPUT_SIZE)

    print("🔄 Exporting to ONNX...")
    torch.onnx.export(
        encoder,
        dummy_input,
        ONNX_PATH,
        opset_version=12,
        input_names=["image"],
        output_names=["image_embeddings"],
        dynamic_axes=None,  # Fixed size for TFLite
    )

    size_mb = os.path.getsize(ONNX_PATH) / (1024 * 1024)
    print(f"✅ ONNX exported: {size_mb:.1f}MB")
    return True


def convert_onnx_to_tflite():
    """Convert ONNX model to TFLite."""
    import onnx
    from onnx_tf.backend import prepare
    import tensorflow as tf

    print("🔄 Loading ONNX model...")
    onnx_model = onnx.load(ONNX_PATH)
    onnx.checker.check_model(onnx_model)

    print("🔄 Converting ONNX → TensorFlow...")
    tf_rep = prepare(onnx_model)
    
    # Save as TF SavedModel
    tf_saved_model_path = "/tmp/mobile_sam_tf"
    tf_rep.export_graph(tf_saved_model_path)
    print(f"✅ TensorFlow SavedModel exported")

    print("🔄 Converting TensorFlow → TFLite...")
    converter = tf.lite.TFLiteConverter.from_saved_model(tf_saved_model_path)
    
    # Optimize for mobile
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.target_spec.supported_types = [tf.float16]
    
    tflite_model = converter.convert()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(TFLITE_PATH, "wb") as f:
        f.write(tflite_model)

    size_mb = os.path.getsize(TFLITE_PATH) / (1024 * 1024)
    print(f"✅ TFLite model saved: {TFLITE_PATH} ({size_mb:.1f}MB)")
    return True


def convert_via_direct_torch():
    """
    Alternative: Convert PyTorch → TFLite directly using ai_edge_torch
    or via PyTorch → ONNX → TFLite pipeline with simpler tools.
    """
    from mobile_sam import sam_model_registry
    import tensorflow as tf

    print("🔄 Loading MobileSAM model...")
    model_type = "vit_t"
    sam = sam_model_registry[model_type](checkpoint=CHECKPOINT_PATH)
    sam.eval()

    encoder = sam.image_encoder
    encoder.eval()
    
    print(f"✅ Model loaded")

    # Trace model with torch.jit
    print("🔄 Tracing model with TorchScript...")
    dummy_input = torch.randn(1, 3, INPUT_SIZE, INPUT_SIZE)
    
    with torch.no_grad():
        traced = torch.jit.trace(encoder, dummy_input)
        # Run inference to get output shape
        output = traced(dummy_input)
        print(f"   Input shape:  {dummy_input.shape}")
        print(f"   Output shape: {output.shape}")

    # Export to ONNX
    print("🔄 Exporting to ONNX...")
    torch.onnx.export(
        encoder,
        dummy_input,
        ONNX_PATH,
        opset_version=12,
        input_names=["image"],
        output_names=["image_embeddings"],
    )
    onnx_size = os.path.getsize(ONNX_PATH) / (1024 * 1024)
    print(f"✅ ONNX model: {onnx_size:.1f}MB")

    # Convert ONNX → TFLite using onnxruntime + tf
    print("🔄 Converting ONNX → TFLite via onnxruntime...")
    
    try:
        import onnxruntime as ort
        
        # Validate ONNX
        session = ort.InferenceSession(ONNX_PATH)
        input_name = session.get_inputs()[0].name
        test_input = np.random.randn(1, 3, INPUT_SIZE, INPUT_SIZE).astype(np.float32)
        onnx_output = session.run(None, {input_name: test_input})
        print(f"✅ ONNX validation passed, output shape: {onnx_output[0].shape}")
        
    except Exception as e:
        print(f"⚠️  ONNX validation: {e}")

    # Try onnx2tf or onnx-tf for conversion
    try:
        import subprocess
        
        # Install onnx2tf if needed
        subprocess.run([sys.executable, "-m", "pip", "install", "onnx2tf", "sng4onnx", "onnxsim", "-q"],
                      capture_output=True, timeout=120)
        
        print("🔄 Converting with onnx2tf...")
        result = subprocess.run(
            [sys.executable, "-m", "onnx2tf",
             "-i", ONNX_PATH,
             "-o", "/tmp/mobile_sam_tf",
             "-oiqt",  # INT8 quantization
             "--output_signaturedefs",
             ],
            capture_output=True, text=True, timeout=600
        )
        
        if result.returncode == 0:
            print("✅ onnx2tf conversion done")
            
            # Convert SavedModel to TFLite
            converter = tf.lite.TFLiteConverter.from_saved_model("/tmp/mobile_sam_tf")
            converter.optimizations = [tf.lite.Optimize.DEFAULT]
            converter.target_spec.supported_types = [tf.float16]
            
            tflite_model = converter.convert()
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            with open(TFLITE_PATH, "wb") as f:
                f.write(tflite_model)
            
            size_mb = os.path.getsize(TFLITE_PATH) / (1024 * 1024)
            print(f"✅ TFLite model saved: {size_mb:.1f}MB")
            return True
        else:
            print(f"⚠️  onnx2tf failed: {result.stderr[:500]}")
            
    except Exception as e:
        print(f"⚠️  onnx2tf method failed: {e}")

    # Fallback: Generate TFLite directly from ONNX via TF
    try:
        print("🔄 Trying onnx-tf conversion...")
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "onnx-tf", "-q"],
                      capture_output=True, timeout=120)
        
        from onnx_tf.backend import prepare
        import onnx
        
        onnx_model = onnx.load(ONNX_PATH)
        tf_rep = prepare(onnx_model)
        tf_rep.export_graph("/tmp/mobile_sam_tf_v2")
        
        converter = tf.lite.TFLiteConverter.from_saved_model("/tmp/mobile_sam_tf_v2")
        converter.optimizations = [tf.lite.Optimize.DEFAULT]
        converter.target_spec.supported_types = [tf.float16]
        
        tflite_model = converter.convert()
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(TFLITE_PATH, "wb") as f:
            f.write(tflite_model)
        
        size_mb = os.path.getsize(TFLITE_PATH) / (1024 * 1024)
        print(f"✅ TFLite model saved: {size_mb:.1f}MB")
        return True
        
    except Exception as e:
        print(f"❌ All conversion methods failed: {e}")
        return False


def validate_tflite():
    """Validate the converted TFLite model."""
    import tensorflow as tf

    if not os.path.exists(TFLITE_PATH):
        print("❌ TFLite model not found!")
        return False

    print("🔄 Validating TFLite model...")
    
    interpreter = tf.lite.Interpreter(model_path=TFLITE_PATH)
    interpreter.allocate_tensors()
    
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()
    
    print(f"   Input:  {input_details[0]['shape']} ({input_details[0]['dtype']})")
    print(f"   Output: {output_details[0]['shape']} ({output_details[0]['dtype']})")
    
    # Test inference
    input_shape = input_details[0]['shape']
    test_input = np.random.randn(*input_shape).astype(np.float32)
    interpreter.set_tensor(input_details[0]['index'], test_input)
    interpreter.invoke()
    output = interpreter.get_tensor(output_details[0]['index'])
    
    print(f"   Test output shape: {output.shape}")
    print(f"   Test output range: [{output.min():.4f}, {output.max():.4f}]")
    
    size_mb = os.path.getsize(TFLITE_PATH) / (1024 * 1024)
    print(f"\n✅ TFLite model validated! Size: {size_mb:.1f}MB")
    print(f"   Path: {TFLITE_PATH}")
    return True


def main():
    print("=" * 60)
    print("  MobileSAM → TFLite Conversion Pipeline")
    print("=" * 60)
    
    # Step 1: Download checkpoint
    if not download_checkpoint():
        sys.exit(1)
    
    # Step 2+3: Convert to TFLite
    if not convert_via_direct_torch():
        print("\n❌ Conversion failed!")
        sys.exit(1)
    
    # Step 4: Validate
    if not validate_tflite():
        sys.exit(1)
    
    print("\n" + "=" * 60)
    print("  ✅ DONE! MobileSAM TFLite model is ready")
    print(f"  📁 {TFLITE_PATH}")
    print("=" * 60)


if __name__ == "__main__":
    main()
