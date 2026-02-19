# Project Setup & Reproducibility Guide

This guide details how to set up the **ARCH-FINGERPRINT** system on a new server.

## 1. System Requirements
- **OS**: Linux (Ubuntu 22.04+ recommended) or macOS.
- **Python**: Version 3.11 or higher.
- **Ollama**: Required for local OCR capabilities. [Download Ollama](https://ollama.com/download).
- **System Libraries**:
  ```bash
  sudo apt-get update && sudo apt-get install -y libgl1-mesa-glx libglib2.0-0
  ```

## 2. Python Environment
1.  Clone the repository:
    ```bash
    git clone <your-repo-url>
    cd physical_hashing
    ```
2.  Create and activate a virtual environment:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```
3.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
    *Note: `requirements.txt` is generated from a working environment. For development, `pyproject.toml` is the source of truth.*

## 3. AI Model Setup
The system uses several AI models that must be downloaded or configured.

### A. SAM (Segment Anything Model)
1.  **FastSAM**: Automatically downloaded on first run (cached in `~/.cache/ultralytics` or local dir).
2.  **MobileSAM**:
    - Create a `weights` directory in the project root:
      ```bash
      mkdir -p weights
      ```
    - Download `mobile_sam.pt` and place it in `weights/mobile_sam.pt`.
      - **Source**: [MobileSAM GitHub Releases](https://github.com/ChaoningZhang/MobileSAM/blob/master/weights/mobile_sam.pt)

### B. OCR (Ollama)
1.  Start the Ollama server:
    ```bash
    ollama serve
    ```
2.  Create the custom OCR model using the provided Modelfile:
    ```bash
    ollama create glm-ocr-high-ctx -f Modelfile.glm-ocr-high-ctx
    ```
    *Check that the model is created successfully with `ollama list`.*

### C. DINOv2 / Faiss
- DINOv2 weights are downloaded automatically by `torch.hub`.
- Faiss indexes (`data/*.index`) are created automatically if not present.

## 4. Database Setup
1.  Initialize the database:
    ```bash
    # For development (resets DB):
    python reset_db_oneoff.py
    
    # For production usage (using migrations):
    alembic upgrade head
    ```

## 5. Running the API
```bash
uvicorn src.arch_fingerprint.api.main:app --host 0.0.0.0 --port 8000 --reload
```
