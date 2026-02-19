#!/usr/bin/env python3
"""
Export MobileSAM to ONNX format for Android deployment via ONNX Runtime.

MobileSAM has 2 components:
  1. Image Encoder (TinyViT) - heavy, runs once per image
  2. Mask Decoder - lightweight, runs per prompt

For document scanning we export the FULL pipeline as a single model
that takes an image and center point prompt, outputs a mask.
"""

import os
import sys
import torch
import numpy as np
from pathlib import Path

# Add mobile_sam to path
sys.path.insert(0, "/data/PROJECT/physical_hashing/venv/lib/python3.12/site-packages")

OUTPUT_DIR = Path("/data/PROJECT/physical_hashing/arch_fingerprint_gui/assets/models")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def export_encoder():
    """Export MobileSAM image encoder to ONNX."""
    from mobile_sam import sam_model_registry
    
    print("=" * 60)
    print("📦 MobileSAM ONNX Export")
    print("=" * 60)
    
    # Check for checkpoint
    checkpoint_path = None
    search_paths = [
        "/data/PROJECT/physical_hashing/models/mobile_sam.pt",
        "/data/PROJECT/physical_hashing/weights/mobile_sam.pt",
        os.path.expanduser("~/.cache/mobile_sam/mobile_sam.pt"),
    ]
    
    for p in search_paths:
        if os.path.exists(p):
            checkpoint_path = p
            break
    
    if checkpoint_path is None:
        # Download checkpoint
        print("⬇️  Downloading MobileSAM checkpoint...")
        import urllib.request
        os.makedirs("/data/PROJECT/physical_hashing/models", exist_ok=True)
        checkpoint_path = "/data/PROJECT/physical_hashing/models/mobile_sam.pt"
        url = "https://raw.githubusercontent.com/ChaoningZhang/MobileSAM/master/weights/mobile_sam.pt"
        urllib.request.urlretrieve(url, checkpoint_path)
        size_mb = os.path.getsize(checkpoint_path) / (1024 * 1024)
        print(f"   Downloaded: {size_mb:.1f} MB")
    
    print(f"📂 Using checkpoint: {checkpoint_path}")
    print(f"   Size: {os.path.getsize(checkpoint_path) / (1024*1024):.1f} MB")
    
    # Load model
    print("\n🔧 Loading MobileSAM...")
    model = sam_model_registry["vit_t"](checkpoint=checkpoint_path)
    model.eval()
    
    # =====================================================
    # Export 1: Image Encoder (TinyViT)
    # =====================================================
    print("\n📤 Exporting Image Encoder...")
    encoder = model.image_encoder
    encoder.eval()
    
    # Input: [1, 3, 1024, 1024] normalized image
    dummy_input = torch.randn(1, 3, 1024, 1024)
    
    encoder_path = OUTPUT_DIR / "mobilesam_encoder.onnx"
    
    with torch.no_grad():
        torch.onnx.export(
            encoder,
            dummy_input,
            str(encoder_path),
            opset_version=13,
            input_names=["image"],
            output_names=["image_embedding"],
            dynamic_axes={
                "image": {0: "batch"},
                "image_embedding": {0: "batch"},
            },
        )
    
    size_mb = os.path.getsize(encoder_path) / (1024 * 1024)
    print(f"   ✅ Encoder saved: {encoder_path}")
    print(f"   📏 Size: {size_mb:.1f} MB")
    
    # =====================================================
    # Export 2: Mask Decoder
    # =====================================================
    print("\n📤 Exporting Mask Decoder...")
    
    # Get a real embedding for tracing
    with torch.no_grad():
        test_embedding = encoder(dummy_input)
    
    print(f"   Embedding shape: {test_embedding.shape}")
    
    # Create decoder wrapper
    class MaskDecoderWrapper(torch.nn.Module):
        def __init__(self, sam_model):
            super().__init__()
            self.mask_decoder = sam_model.mask_decoder
            self.prompt_encoder = sam_model.prompt_encoder
            
        def forward(self, image_embedding, point_coords, point_labels):
            """
            Args:
                image_embedding: [1, 256, 64, 64] from encoder
                point_coords: [1, N, 2] point coordinates
                point_labels: [1, N] point labels (1=foreground, 0=background)
            Returns:
                masks: [1, 1, 256, 256] predicted masks
                scores: [1, 1] mask quality scores
            """
            sparse_embeddings, dense_embeddings = self.prompt_encoder(
                points=(point_coords, point_labels),
                boxes=None,
                masks=None,
            )
            
            low_res_masks, iou_predictions = self.mask_decoder(
                image_embeddings=image_embedding,
                image_pe=self.prompt_encoder.get_dense_pe(),
                sparse_prompt_embeddings=sparse_embeddings,
                dense_prompt_embeddings=dense_embeddings,
                multimask_output=False,
            )
            
            return low_res_masks, iou_predictions
    
    decoder_wrapper = MaskDecoderWrapper(model)
    decoder_wrapper.eval()
    
    # Dummy inputs for decoder
    dummy_embedding = test_embedding
    dummy_coords = torch.tensor([[[512.0, 512.0]]])  # Center point
    dummy_labels = torch.tensor([[1]])  # Foreground
    
    decoder_path = OUTPUT_DIR / "mobilesam_decoder.onnx"
    
    with torch.no_grad():
        torch.onnx.export(
            decoder_wrapper,
            (dummy_embedding, dummy_coords, dummy_labels),
            str(decoder_path),
            opset_version=13,
            input_names=["image_embedding", "point_coords", "point_labels"],
            output_names=["masks", "iou_predictions"],
            dynamic_axes={
                "point_coords": {1: "num_points"},
                "point_labels": {1: "num_points"},
            },
        )
    
    size_mb = os.path.getsize(decoder_path) / (1024 * 1024)
    print(f"   ✅ Decoder saved: {decoder_path}")
    print(f"   📏 Size: {size_mb:.1f} MB")
    
    # =====================================================
    # Verify with ONNX Runtime
    # =====================================================
    print("\n🧪 Verifying with ONNX Runtime...")
    import onnxruntime as ort
    
    # Test encoder
    enc_session = ort.InferenceSession(str(encoder_path))
    enc_input = {enc_session.get_inputs()[0].name: dummy_input.numpy()}
    enc_output = enc_session.run(None, enc_input)
    print(f"   Encoder output shape: {enc_output[0].shape}")
    
    # Test decoder
    dec_session = ort.InferenceSession(str(decoder_path))
    dec_input = {
        "image_embedding": enc_output[0],
        "point_coords": dummy_coords.numpy(),
        "point_labels": dummy_labels.numpy().astype(np.float32),
    }
    dec_output = dec_session.run(None, dec_input)
    print(f"   Decoder mask shape: {dec_output[0].shape}")
    print(f"   Decoder score shape: {dec_output[1].shape}")
    print(f"   Mask score: {dec_output[1][0][0]:.4f}")
    
    # =====================================================
    # Summary
    # =====================================================
    total_size = sum(
        os.path.getsize(OUTPUT_DIR / f) / (1024 * 1024)
        for f in ["mobilesam_encoder.onnx", "mobilesam_decoder.onnx"]
    )
    
    print("\n" + "=" * 60)
    print("✅ EXPORT COMPLETE!")
    print("=" * 60)
    print(f"📂 Output: {OUTPUT_DIR}")
    print(f"   mobilesam_encoder.onnx  ({os.path.getsize(encoder_path)/(1024*1024):.1f} MB)")
    print(f"   mobilesam_decoder.onnx  ({os.path.getsize(decoder_path)/(1024*1024):.1f} MB)")
    print(f"   Total: {total_size:.1f} MB")
    print()
    print("🤖 Ready for ONNX Runtime Mobile on Android!")
    

if __name__ == "__main__":
    export_encoder()
