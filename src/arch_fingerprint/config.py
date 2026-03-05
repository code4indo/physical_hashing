"""Configuration via environment variables with Pydantic Settings."""

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file."""

    # Database
    database_url: str = "sqlite+aiosqlite:///./data/arch_fingerprint.db"

    # FAISS
    faiss_index_path: str = "./data/faiss.index"

    # File storage
    upload_dir: str = "./data/uploads"

    # AI Model
    model_device: str = "cuda" if __import__("torch").cuda.is_available() else "cpu"
    # model_name: str = "dinov2_vitl14_reg"  # DINOv2 with registers (alternative)
    model_name: str = "facebook/dinov3-vitl16-pretrain-lvd1689m"  # DINOv3 via HuggingFace (GATED REPO — requires HF auth)
    # model_name: str = "dinov2_vitl14"  # DINOv2 ViT-L/14 via Torch Hub (public, no auth required)
    
    # Ollama OCR isolated endpoint (running on port 11435)
    ollama_ocr_url: str = "http://localhost:11435/api/generate"

    # Text Model (SentenceTransformer)
    text_model_name: str = "intfloat/multilingual-e5-large"
    faiss_text_index_path: str = "./data/faiss_text.index"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: list[str] = ["*"]

    # Search defaults
    default_top_k: int = 5
    similarity_threshold: float = 0.65
    
    # Vector ID allocation strategy: "sequential" or "reuse_gaps"
    # sequential: Fast, always increment. Best for write-heavy, low-deletion.
    # reuse_gaps: Reuses freed IDs from deleted docs. Best for production with updates.
    vector_id_strategy: str = "reuse_gaps"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def upload_path(self) -> Path:
        p = Path(self.upload_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def faiss_index_dir(self) -> Path:
        p = Path(self.faiss_index_path).parent
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
