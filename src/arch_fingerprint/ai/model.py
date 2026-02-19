"""DINOv2 ViT-L/14 feature extraction for visual fingerprinting.

Loads the pre-trained DINOv2 model and extracts 1024-dimensional dense
vectors from document images. These vectors serve as the visual fingerprint
for archival document identification.
"""

import logging
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from torchvision import transforms

logger = logging.getLogger(__name__)

# ImageNet normalization constants used by DINOv2 pre-training
_IMAGENET_MEAN = [0.485, 0.456, 0.406]
_IMAGENET_STD = [0.229, 0.224, 0.225]

# DINOv2 ViT-L/14 expects 518x518 input (14px patches × 37 patches = 518)
_INPUT_SIZE = 518


class DINOv2Embedder:
    """Extracts visual embeddings from document images using DINOv2 ViT-L/14.

    The model produces a 1024-dimensional dense vector that captures the
    unique visual characteristics of a document's texture, paper grain,
    aging patterns, and content layout.
    """

    def __init__(self, model_name: str = "dinov2_vitl14", device: str = "cpu") -> None:
        self._device = torch.device(device)
        self._model_name = model_name
        self._model: torch.nn.Module | None = None
        self._processor = None
        self._transform = None
        self._use_transformers = False
        self._embed_dim_cache = None

        if "facebook/dinov3" in model_name or "huggingface.co" in model_name:
             self._use_transformers = True
        else:
            # Fallback to Torch Hub (DINOv2) default transform
            self._transform = transforms.Compose([
                transforms.Resize((_INPUT_SIZE, _INPUT_SIZE), interpolation=transforms.InterpolationMode.BICUBIC),
                transforms.ToTensor(),
                transforms.Normalize(mean=_IMAGENET_MEAN, std=_IMAGENET_STD),
            ])

    def load(self) -> None:
        """Load the model from Hugging Face or Torch Hub."""
        logger.info("Loading model '%s' on device '%s'...", self._model_name, self._device)

        if self._use_transformers:
            from transformers import AutoImageProcessor, AutoModel
            try:
                self._processor = AutoImageProcessor.from_pretrained(self._model_name)
                self._model = AutoModel.from_pretrained(self._model_name)
                self._model = self._model.to(self._device)
                self._model.eval()
                self._embed_dim_cache = self._model.config.hidden_size
                logger.info("HF Model loaded via Transformers. Hidden size: %d", self.embedding_dim)
            except Exception as e:
                logger.error("Failed to load HF model: %s", e)
                raise
        else:
            # DINOv2 via Torch Hub
            self._model = torch.hub.load(
                "facebookresearch/dinov2",
                self._model_name,
                pretrained=True,
            )
            self._model = self._model.to(self._device)
            self._model.eval()
            self._embed_dim_cache = self._model.embed_dim
            logger.info("Torch Hub Model loaded. Output dim: %d", self.embedding_dim)

    @property
    def embedding_dim(self) -> int:
        """Dimensionality of the output embedding vector."""
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load() first.")
        if self._embed_dim_cache:
             return self._embed_dim_cache
        # Fallback reading
        if hasattr(self._model, "embed_dim"):
             return self._model.embed_dim
        elif hasattr(self._model, "config"):
             return self._model.config.hidden_size
        return 1024 # Default DINOv2 Large

    def extract_embedding(self, image: Image.Image) -> np.ndarray:
        """Extract a normalized 1024-dim embedding from a PIL Image.

        Args:
            image: RGB PIL Image of the document.

        Returns:
            L2-normalized 1024-dimensional numpy float32 array.
        """
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load() first.")

        # Ensure RGB
        if image.mode != "RGB":
            image = image.convert("RGB")

        with torch.no_grad():
            if self._use_transformers:
                # Use Hugging Face Processor
                inputs = self._processor(images=image, return_tensors="pt").to(self._device)
                outputs = self._model(**inputs)
                # Extract CLS token from last_hidden_state (batch, seq_len, hidden_size)
                # DINOv3 CLS is at index 0
                embedding = outputs.last_hidden_state[:, 0, :]
            else:
                # Use Torch Hub (DINOv2)
                tensor = self._transform(image).unsqueeze(0).to(self._device)
                embedding = self._model(tensor)

        # L2-normalize for cosine similarity via inner product in FAISS
        embedding = F.normalize(embedding, p=2, dim=1)

        return embedding.cpu().numpy().astype(np.float32).flatten()

    def extract_embedding_from_path(self, image_path: str | Path) -> np.ndarray:
        """Convenience method: load image from disk and extract embedding."""
        image = Image.open(image_path)
        return self.extract_embedding(image)
