# 🗃️ ARCH-FINGERPRINT (Physical Hashing)

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Flutter](https://img.shields.io/badge/flutter-3.16%2B-blue)

**ARCH-FINGERPRINT** adalah sebuah platform identifikasi arsip fisik otomatis yang mengintegrasikan ekstraksi *keyframe* video, *perceptual hashing* (pHash), pencarian vektor (FAISS), serta ekstraksi teks (OCR/VLM). Proyek ini bertujuan untuk mengenali, mengekstraksi, dan mendokumentasikan halaman arsip historis yang tidak memiliki penanda fisik (seperti *barcode* atau *QR code*), menggunakan konten visual dokumen itu sendiri sebagai **"Physical Hash"** atau sidik jari fisik.

---

## 🎯 Mengapa Proyek Ini Dibuat? (Latar Belakang & Masalah) 

Dalam digitalisasi arsip berskala besar (misalnya menggunakan perekaman video halaman per halaman), sering kali muncul tiga tantangan utama:

1. **Identifikasi Dokumen Tanpa Penanda:** Arsip historis sangat rentan dan sering kali tidak boleh ditempeli stiker *barcode* atau *tag* fisik untuk menjaga keasliannya.
2. **Redundansi *Frame* Video:** Sebuah video digitalisasi mengandung banyak *frame* duplikat (saat transisi lembar halaman) dan *frame* kabur/buram (akibat pergerakan). Dibutuhkan cara membedakan setiap halaman dokumen yang unik dari *frame* yang mubazir.
3. **Kualitas Gambar untuk Transkripsi (OCR):** Tidak semua *frame* cocok untuk ekstraksi teks. Sistem harus bisa mendeteksi ketajaman (*sharpness*), perataan (*alignment*), dan kelengkapan (*completeness*) untuk menentukan *frame* terbaik yang layak di-OCR.

**ARCH-FINGERPRINT** menyelesaikan masalah-masalah di atas melalui satu *pipeline* otomatis dan cerdas!

---

## ✨ Manfaat & Tujuan Proyek

- **Preservasi Tanpa Intervensi Fisik:** Menggunakan ekstraksi fitur visual dan semantik (Physical Hashing) sebagai ID Unik (pengganti *barcode*), sehingga dokumen fisik tetap aman dan murni.
- **Otomatisasi Ekstraksi Cerdas:** Secara otomatis memilih gambar terbaik (*sharpest and best-aligned*) dari *stream* video.
- **Akurasi Pencarian & Kurasi Tinggi:** Teknik deduplikasi berbekal *Perceptual Hashing* dan *Vector Search* memastikan setiap dokumen hanya tersimpan satu kali, menekan duplikasi data secara signifikan.
- **Hybrid Matching (Visual + Semantik):** Identifikasi didasari pada bentuk rupa visual dokumen (DINOv2/MobileSAM) dipadukan dengan pemahaman ekstraksi teksnya (GLM-OCR/Ollama), menghasilkan representasi identitas arsip yang nyaris tanpa tabrakan (*collision-free*).

---

## 🏗️ Arsitektur Sistem & Fitur Utama

Sistem bekerja melalui beberapa modul inti (Pipeline):

1. **Video Keyframe Extractor**: Mengambil *frame-frame* stabil dari input video (membuang gambar dengan *motion-blur*).
2. **Perceptual Hasher**: Menghasilkan nilai *hash* (sidik jari lokal) berbasis ruang frekuensi (DCT-based `pHash`) dari gambar.
3. **Document Deduplication Engine**: Mengelompokkan *frame* yang mirip ke dalam satu entitas halaman dokumen menggunakan perbandingan *Hamming distance*.
4. **Image Quality Assessor**: Memberikan *ranking* pada setiap *frame* (berdasarkan ketajaman, kontras, presisi) di klaster yang sama untuk mencari **halaman perwakilan (Representative Frame)**.
5. **OCR & AI Engine**: Mengekstraksi teks pada gambar perwakilan menggunakan VLM (Ollama/GLM-OCR) atau Tesseract.
6. **Physical Hash ID Generator**: Menggabungkan sidik jari visual (pHash) dan tekstual (SHA-256 dari teks hasil OCR) menjadi satu Universal ID untuk dokumen tersebut.

---

## 🛠️ Teknologi yang Digunakan (Tech Stack)

### **Backend (Python 3.11+)**
- **Framework API:** FastAPI
- **Database / Vector Search:** PostgreSQL, FAISS, SQLite (development)
- **Computer Vision & Image Processing:** OpenCV 4.x, scikit-image, Pillow, `imagehash`
- **Machine Learning & AI:** PyTorch (DINOv2, SAM), Ollama (LLaMA3.2-Vision / `glm-ocr`)
- **OCR Engine:** Tesseract (pytesseract), Vision Language Models

### **Frontend / GUI (Flutter 3.16+)**
- **Aplikasi Antarmuka:** Tersedia dalam repositori `arch_fingerprint_gui` terintegrasi API Backend untuk memonitor klasterisasi dan pemindaian dalam *real-time*. Dapat dijalankan di Web, Linux Desktop, atau Android.

---

## 📂 Struktur Repositori

```text
physical_hashing/
├── src/                    # Source code API dan logika backend (Python)
├── data/                   # Lingkungan penyimpanan database/vector sementara
├── arch_fingerprint_gui/   # Source code antarmuka pengguna (Flutter/Dart)
├── docs/                   # Dokumentasi teknis proyek
├── tests/                  # Unit testing / Integration tests backend
├── sdd.md                  # System Design Document lengkap (Panduan Arsitektur)
├── SETUP.md                # Panduan langkah demi langkah proses Instalasi
└── README.md               # Anda berada di sini
```

---

## 🚀 Panduan Instalasi dan Menjalankan Proyek

Panduan instalasi yang mendetail, mencakup inisialisasi *Virtual Environment* Python, unduhan Model AI (MobileSAM, Ollama), penggunaan Database Postgres, hingga kompilasi aplikasi Flutter telah didokumentasikan sepenuhnya di **[SETUP.md](SETUP.md)**.

**Langkah Singkat (Backend):**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # Sesuaikan environment (Database, GPU Device)
uvicorn src.arch_fingerprint.api.main:app --host 0.0.0.0 --port 8000 --reload
```

**Langkah Singkat (Frontend GUI):**
```bash
cd arch_fingerprint_gui
flutter pub get
flutter run
```

---

## 📖 Dokumentasi Lengkap

Untuk memahami secara spesifik kinerja alur Pipeline Hashing dan dasar saintifiknya, silakan baca **[System Design Document (sdd.md)](sdd.md)**.

---

## 📄 Lisensi

Proyek ini berada di bawah lisensi MIT.
