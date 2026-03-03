# 🗃️ ARCH-FINGERPRINT (Physical Hashing)

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Flutter](https://img.shields.io/badge/dart_sdk-^3.11.0-blue)

**ARCH-FINGERPRINT** adalah platform identifikasi arsip fisik otomatis yang mengintegrasikan *visual fingerprinting* berbasis **DINOv3** (Vision Transformer), pencarian vektor **FAISS**, dan ekstraksi teks (OCR/VLM via Ollama). Proyek ini bertujuan untuk mengenali dan mendokumentasikan halaman arsip historis yang tidak memiliki penanda fisik (seperti *barcode* atau *QR code*), menggunakan konten visual dan semantik dokumen itu sendiri sebagai **"Physical Hash"** atau sidik jari fisik.

---

## 🎯 Mengapa Proyek Ini Dibuat? (Latar Belakang & Masalah)

Dalam digitalisasi arsip berskala besar, muncul tiga tantangan utama:

1. **Identifikasi Dokumen Tanpa Penanda:** Arsip historis sangat rentan dan sering kali tidak boleh ditempeli stiker *barcode* atau *tag* fisik untuk menjaga keasliannya.
2. **Redundansi Gambar:** Proses digitalisasi menghasilkan gambar duplikat. Dibutuhkan cara membedakan setiap halaman dokumen yang unik dari gambar yang mubazir.
3. **Kualitas Gambar untuk Transkripsi (OCR):** Tidak semua gambar cocok untuk ekstraksi teks. Sistem harus otomatis menangani berbagai kualitas input kamera.

**ARCH-FINGERPRINT** menyelesaikan masalah-masalah di atas melalui satu *pipeline* otomatis berbasis AI!

---

## ✨ Manfaat & Tujuan Proyek

- **Preservasi Tanpa Intervensi Fisik:** Menggunakan *neural embedding* visual (Physical Hashing) dan UUID sebagai ID unik pengganti *barcode*, sehingga dokumen fisik tetap aman dan murni.
- **Otomatisasi Preprocessing Cerdas:** Secara otomatis menerapkan *CLAHE illumination normalization* dan koreksi perspektif pada gambar input.
- **Deduplikasi Berbasis Konten:** SHA-256 dari gambar yang telah diproses digunakan sebagai *content hash* untuk mendeteksi dokumen duplikat secara tepat.
- **Hybrid Matching (Visual + Semantik):** Identifikasi didasari pada *dense embedding* visual dokumen (DINOv3) dipadukan dengan pemahaman semantik teks hasil OCR (`multilingual-e5-large`), menghasilkan representasi identitas arsip yang akurat.

---

## 🏗️ Arsitektur Sistem & Fitur Utama

Sistem bekerja melalui pipeline asinkron yang terdiri dari beberapa modul:

### Pipeline Registrasi Dokumen (Background Worker)

1. **Image Upload & Persistence**: Gambar dokumen diunggah via REST API, langsung disimpan ke disk dengan status `pending`. Respons API dikembalikan segera (fire-and-forget, HTTP 202).
2. **Preprocessing (CLAHE)**: Gambar diproses dengan *CLAHE (Contrast Limited Adaptive Histogram Equalization)* untuk normalisasi pencahayaan, terutama mengatasi bayangan pada punggung buku.
3. **Perspective Correction**: Koreksi distorsi perspektif kamera menggunakan deteksi kontur OpenCV dan transformasi *homography*.
4. **Content Hash (SHA-256)**: SHA-256 dari gambar yang telah diproses dihitung untuk keperluan deduplikasi tepat.
5. **Multi-View Augmentation**: Tiga versi augmentasi gambar dibuat (original, *horizontal flip*, *perspective warp* kiri & kanan) untuk ketahanan identifikasi dari berbagai sudut kamera.
6. **Visual Embedding (DINOv3 + Region Strategy)**: Setiap view diproses dengan strategi region (`9-grid` saat registrasi), menghasilkan multiple embedding per dokumen. Setiap embedding diekstrak menggunakan **DINOv3** (`facebook/dinov3-vitl16-pretrain-lvd1689m`) via HuggingFace Transformers, lalu diindeks ke **FAISS (IndexFlatIP)**.
7. **OCR (GLM-OCR via Ollama)**: Model VLM GLM-OCR (`glm-ocr-high-ctx`) dijalankan via Ollama API untuk mengekstraksi teks dokumen. Mendukung *smart tiling* untuk gambar berukuran besar (>3000px), dengan algoritma *smart merge* berbasis `SequenceMatcher` untuk menyatukan teks antar-tile.
8. **Semantic Embedding (multilingual-e5-large)**: Teks OCR di-encode menjadi vektor semantik menggunakan `intfloat/multilingual-e5-large` (SentenceTransformers), lalu diindeks ke FAISS Text Index terpisah.

### Pipeline Pencarian Dokumen

1. **FAST Mode** (`use_ocr=False`, default): Hanya melakukan pencarian visual (embedding FAISS). Lebih cepat (~2-18 detik tergantung *region strategy*).
2. **THOROUGH Mode** (`use_ocr=True`): Visual search → OCR pada gambar query → verifikasi teks hybrid (40% string similarity + 60% semantic similarity via vektor `multilingual-e5-large`).

### Region Strategies (Kontrol Granularitas Fingerprint)

| Strategi    | Total Region | Keterangan                        |
|------------|-------------|-----------------------------------|
| `4-strip`  | 4           | Header, Middle, Footer + Global   |
| `9-grid`   | 10          | Grid 3×3 + Global (default search)|
| `16-grid`  | 17          | Grid 4×4 + Global (paling akurat) |

---

## 🛠️ Teknologi yang Digunakan (Tech Stack)

### **Backend (Python 3.11+)**

| Kategori                  | Library / Model                                      |
|--------------------------|------------------------------------------------------|
| **Framework API**         | FastAPI + Uvicorn                                   |
| **Database**              | SQLite (default) / PostgreSQL via asyncpg + SQLAlchemy async |
| **Vector Index**          | FAISS (`IndexFlatIP`, exact cosine similarity)        |
| **Visual Embedding Model**| DINOv3 (`facebook/dinov3-vitl16-pretrain-lvd1689m`) via HuggingFace Transformers |
| **Teks Semantik Model**   | `intfloat/multilingual-e5-large` via SentenceTransformers |
| **OCR / VLM**             | GLM-OCR (`glm-ocr-high-ctx`) via Ollama API         |
| **Image Preprocessing**   | OpenCV (CLAHE, perspective correction), Pillow       |
| **Document Segmentation** | FastSAM (Ultralytics, tersedia namun tidak aktif di pipeline default) |
| **Async Processing**      | asyncio + ThreadPoolExecutor (background worker)     |

### **Frontend / GUI (Flutter/Dart)**

- **Dart SDK:** `^3.11.0`
- **Platform:** Android, Linux Desktop, Web
- Flutter app di direktori `arch_fingerprint_gui/`, berkomunikasi dengan backend via REST API.
- Fitur khusus: *on-device* MobileSAM mode (ONNX) untuk crop dokumen sebelum upload, menggunakan `onnxruntime` Flutter package.

---

## 📂 Struktur Repositori

```text
physical_hashing/
├── src/
│   └── arch_fingerprint/
│       ├── ai/                 # Model & pemrosesan AI
│       │   ├── model.py        # DINOv3 embedder (DINOv2Embedder class)
│       │   ├── ocr.py          # GLM-OCR via Ollama + smart tiling/merge
│       │   ├── text_model.py   # SentenceTransformer (multilingual-e5-large)
│       │   ├── preprocessing_sam.py  # CLAHE illumination normalization
│       │   ├── robustness.py   # Perspektif koreksi + augmentasi view
│       │   └── region_strategy.py   # Strategi crop region (4-strip/9-grid/16-grid)
│       ├── api/                # FastAPI routes & schemas
│       │   ├── main.py         # App entry point, lifespan management
│       │   └── routes/
│       │       ├── register.py # POST /api/v1/register
│       │       ├── search.py   # POST /api/v1/search
│       │       └── documents.py# GET/DELETE /api/v1/documents
│       ├── db/                 # ORM models & database session
│       ├── search/
│       │   └── faiss_index.py  # VectorIndex wrapper (FAISS IndexFlatIP)
│       ├── worker/
│       │   └── queue.py        # Async background job queue (AI processing)
│       └── config.py           # Konfigurasi via Pydantic Settings (.env)
├── arch_fingerprint_gui/       # Flutter app (Android/Linux/Web)
├── docs/                       # Dokumentasi teknis proyek
├── tests/                      # Unit & integration tests
├── Modelfile.glm-ocr-high-ctx  # Definisi model OCR untuk Ollama
├── pyproject.toml              # Build system & dependency declaration
├── requirements.txt            # Frozen dependencies (pip)
├── sdd.md                      # System Design Document lengkap
├── SETUP.md                    # Panduan instalasi langkah demi langkah
└── README.md                   # Anda berada di sini
```

> **Catatan:** Direktori `data/` (database SQLite, FAISS index, uploads) tidak disertakan dalam repository dan dibuat secara otomatis saat server pertama kali dijalankan.

---

## 🚀 Panduan Instalasi dan Menjalankan Proyek

Panduan instalasi yang mendetail tersedia di **[SETUP.md](SETUP.md)**.

**Langkah Singkat (Backend):**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # Sesuaikan konfigurasi (DATABASE_URL, MODEL_DEVICE, dll.)
uvicorn src.arch_fingerprint.api.main:app --host 0.0.0.0 --port 8000 --reload
```

**Variabel `.env` Utama:**

| Variable          | Default                                           | Keterangan                              |
|------------------|---------------------------------------------------|-----------------------------------------|
| `DATABASE_URL`    | `sqlite+aiosqlite:///./data/arch_fingerprint.db` | URL koneksi database                   |
| `MODEL_DEVICE`    | `cuda` (jika GPU tersedia) / `cpu`               | Device untuk DINOv3 & SentenceTransformer |
| `MODEL_NAME`      | `facebook/dinov3-vitl16-pretrain-lvd1689m`       | Model visual embedding                 |
| `FAISS_INDEX_PATH`| `./data/faiss.index`                             | Path visual FAISS index                |

**Langkah Singkat (Frontend GUI):**
```bash
cd arch_fingerprint_gui
flutter pub get
flutter run
```

**Dependency Tambahan (Ollama):**

GLM-OCR membutuhkan Ollama yang terinstall dan model didaftarkan dari `Modelfile.glm-ocr-high-ctx`:
```bash
ollama create glm-ocr-high-ctx -f Modelfile.glm-ocr-high-ctx
```

---

## 📖 Dokumentasi Lengkap

Untuk memahami secara spesifik arsitektur, alur pipeline, dan dasar saintifiknya, silakan baca **[System Design Document (sdd.md)](sdd.md)**.

---

## 📄 Lisensi

Proyek ini berada di bawah lisensi MIT.
