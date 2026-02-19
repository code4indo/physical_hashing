SYSTEM DESIGN DOCUMENT (SDD)
Proyek: ARCH-FINGERPRINT (Sistem Identifikasi Otomatis Arsip Historis)
Versi: 1.0
Teknologi: DINOv2 Visual Fingerprinting & FAISS Vector Search
1. Pendahuluan
1.1 Tujuan
Membangun sistem identifikasi lembaran dokumen terpisah tanpa menggunakan label fisik (barcode/RFID), melainkan menggunakan "sidik jari visual" dari tekstur, serat kertas, dan pola penuaan dokumen historis.
1.2 Lingkup
Sistem terdiri dari aplikasi Android untuk akuisisi gambar dan backend berbasis AI untuk pencocokan metadata khazanah arsip.
2. Arsitektur Sistem
Sistem menggunakan arsitektur Client-Server dengan pemrosesan berat dilakukan di sisi GPU Server.

    Client (Android App): Berfungsi sebagai alat sensor/scanners.
    API Gateway (FastAPI): Mengatur lalu lintas data dan otentikasi.
    AI Engine (PyTorch + DINOv2): Mengekstrak fitur visual unik (Embedding).
    Vector Database (FAISS): Mesin pencari kemiripan vektor berkecepatan tinggi.
    Metadata DB (PostgreSQL): Menyimpan informasi detail khazanah arsip.

3. Spesifikasi Teknis
3.1 Model AI (Backbone)

    Model: DINOv2 ViT-L/14 (Pre-trained).
    Input Resolution:
    piksel.
    Output Vector: 1024-dimensional dense vector.
    Fungsi: Mengubah gambar fisik menjadi koordinat matematika unik yang merepresentasikan tekstur kertas.

3.2 Database Vektor

    Library: FAISS (Facebook AI Similarity Search).
    Metrik Kemiripan: Cosine Similarity.
    Kapasitas: Mampu menangani hingga >1.000.000 sidik jari dokumen dengan waktu pencarian
    .

4. Alur Kerja (Workflow)
4.1 Tahap Registrasi (Indexing)

    Admin memindai dokumen asli (High-res).
    Server mengekstrak vektor DINOv2.
    Vektor disimpan di FAISS, metadata (Khazanah, No. Halaman) disimpan di PostgreSQL.

4.2 Tahap Pencarian (Querying)

    User memotret lembaran lepas menggunakan HP Android.
    Aplikasi melakukan Auto-cropping untuk membuang latar belakang meja.
    Gambar dikirim ke Server.
    Server mencari vektor terdekat di FAISS.
    Sistem mengembalikan informasi detail dokumen ke layar HP.

5. Fitur Aplikasi Android

    Smart Capture: Panduan visual agar user memotret dengan fokus dan pencahayaan yang benar.
    Perspective Correction: Secara otomatis meluruskan dokumen yang difoto miring.
    History Match: Menyimpan riwayat dokumen yang telah berhasil diidentifikasi secara lokal.
    Offline Queue: Foto dapat diambil saat tidak ada sinyal dan akan diproses otomatis saat online.

6. Kebutuhan Infrastruktur
Komponen	Spesifikasi Minimum
Server GPU	NVIDIA RTX 3060 12GB atau lebih tinggi
RAM Server	32 GB
Mobile OS	Android 10 (API Level 29) atau lebih tinggi
Kamera HP	Minimal 12 MP dengan fitur Auto-focus
7. Rencana Pengujian (QA)

    Uji Rotasi: Apakah dokumen tetap dikenali jika difoto terbalik/miring?
    Uji Pencahayaan: Apakah dokumen dikenali di ruangan redup?
    Uji Granularitas: Apakah sistem bisa membedakan Halaman 1 dan Halaman 2 dari buku yang sama (tekstur kertas berbeda)?