# 🛠️ ARCH-FINGERPRINT Setup Guide

This comprehensive guide details how to set up the **ARCH-FINGERPRINT** system (Backend + Frontend) on a new server or development machine.

## 📋 Prerequisites

Ensure your system meets the following requirements:

*   **OS**: Linux (Ubuntu 22.04+ recommended) or macOS.
*   **Python**: Version 3.11+.
*   **Flutter**: Version 3.16+ (for the GUI). [Install Flutter](https://docs.flutter.dev/get-started/install).
*   **PostgreSQL**: Version 14+.
*   **Ollama**: For local OCR capabilities. [Download Ollama](https://ollama.com/download).
*   **System Libraries** (Linux):
    ```bash
    sudo apt-get update && sudo apt-get install -y libgl1-mesa-glx libglib2.0-0 postgresql postgresql-contrib
    ```

---

## 🚀 1. Backend Setup

### 1.1. Clone & Environment
```bash
# Clone the repository
git clone <your-repo-url>
cd physical_hashing

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows use: venv\Scripts\activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### 1.2. Configuration
1.  Copy the example environment file:
    ```bash
    cp .env.example .env
    ```
2.  Edit `.env` to match your local setup:
    *   **DATABASE_URL**: Update user/password for your Postgres instance.
    *   **MODEL_DEVICE**: Set to `cuda` if you have an NVIDIA GPU, otherwise `cpu`.

### 1.3. Database Initialization
1.  Start your PostgreSQL service.
2.  Create the database:
    ```bash
    createdb arch_fingerprint
    ```
3.  Run migrations (Production):
    ```bash
    alembic upgrade head
    ```
    *Or for a clean development reset (WARNING: Wipes data):*
    ```bash
    python reset_db_oneoff.py
    ```

---

## 🧠 2. AI Model Setup

### 2.1. MobileSAM (Segmentation)
The system requires the MobileSAM weights manually placed:
1.  Create the directory:
    ```bash
    mkdir -p weights
    ```
2.  Download `mobile_sam.pt` (approx. 40MB):
    *   **Download Link**: [MobileSAM GitHub Releases](https://github.com/ChaoningZhang/MobileSAM/blob/master/weights/mobile_sam.pt)
    *   **Save to**: `weights/mobile_sam.pt`

### 2.2. FastSAM
*   Automatically downloaded on first run to `~/.cache/ultralytics` (or local depending on config).

### 2.3. OCR (Ollama)
The system uses a custom high-context vision model named `glm-ocr-high-ctx`. You must set this up locally:

1.  **Install Ollama** and start the server:
    ```bash
    ollama serve
    ```

2.  **Pull a Base Vision Model**:
    We recommend `llama3.2-vision` (compatible size and performance) or `glm-4v` if available.
    ```bash
    ollama pull llama3.2-vision
    ```

3.  **Create the Base `glm-ocr` Model**:
    The project's Modelfile expects a model named `glm-ocr`. Create it from your pulled model:
    ```bash
    # Create an alias 'glm-ocr' pointing to the pulled model
    ollama cp llama3.2-vision glm-ocr
    ```

4.  **Create the High-Context Model**:
    Now create the final model used by the code:
    ```bash
    ollama create glm-ocr-high-ctx -f Modelfile.glm-ocr-high-ctx
    ```
    *Verify with `ollama list`. You should see `glm-ocr-high-ctx`.*

---

## 📱 3. Frontend (Flutter GUI) Setup

### 3.1. Install Dependencies
```bash
cd arch_fingerprint_gui
flutter pub get
```

### 3.2. Configuration
*   Ensure the backend URL is correctly set in `lib/preferences_service.dart` or via app settings (default: `http://localhost:8000`).

### 3.3. Run the App
*   **Web**:
    ```bash
    flutter run -d chrome
    ```
*   **Linux/Desktop**:
    ```bash
    flutter run -d linux
    ```
*   **Android (via USB)**:
    If running on a physical Android device, you must forward the port so the phone can access your computer's localhost:
    ```bash
    # Run this before starting the app
    adb reverse tcp:8000 tcp:8000
    ```
    Then simply use `http://127.0.0.1:8000` as the Server URL in the app.
    ```bash
    flutter run -d <device_id>
    ```

---

## ▶️ 4. Running the System

### Step 1: Start Backend API
From the project root (with venv activated):
```bash
uvicorn src.arch_fingerprint.api.main:app --host 0.0.0.0 --port 8000 --reload
```
*   API Docs will be available at: [http://localhost:8000/docs](http://localhost:8000/docs)

### Step 2: Start Frontend
From `arch_fingerprint_gui/`:
```bash
flutter run
```

---

## 🧪 Verification & Troubleshooting

### Check Backend Health
Visit `http://localhost:8000/health` (if implemented) or check the `/docs` endpoint to see if it loads without error.

### Common Issues
1.  **"CUDA not available"**: 
    *   Check your `.env` setting `MODEL_DEVICE`. Set to `cpu` if no GPU is available.
    *   Verify PyTorch is installed with CUDA support: `python -c "import torch; print(torch.cuda.is_available())"`
2.  **"Ollama connection refused"**:
    *   Ensure `ollama serve` is running in a separate terminal.
    *   Verify the URL in AI config (usually `http://localhost:11434`).
3.  **"Missing weights/mobile_sam.pt"**:
    *   Re-read Section 2.1 and ensure the file is named correctly and placed in `weights/` folder.
