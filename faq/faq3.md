pre-processing masih belum optimal untuk dokumen cetak modern, sedangkan cukup baik untuk dokumen historis,  berikan alternatif
Masalah ini terjadi karena
dokumen cetak modern (HVS/Art Paper) memiliki permukaan yang "terlalu sempurna" dan homogen secara visual dibandingkan kertas historis yang kaya serat. Akibatnya, DINOv2 terkadang kesulitan menemukan titik unik (fiktur) yang membedakan satu lembar HVS dengan lembar lainnya jika hanya mengandalkan foto standar.
Untuk dokumen cetak modern, pendekatannya harus bergeser dari Tekstur Serat ke Mikro-Geometri Cetak dan Karakteristik Tinta. Berikut adalah 3 alternatif teknologi pre-processing dan ekstraksi yang lebih canggih untuk dokumen modern:
1. Mikro-OCR & Topografi Karakter (Font DNA)
Dokumen modern memiliki teks yang tajam. Rahasianya bukan pada "apa" teksnya, tapi "bagaimana" teks itu tercetak.

    Alternatif: Ekstraksi fitur pada tepi karakter (edge jitter). Printer laser atau inkjet memiliki noise unik saat menyemprotkan tinta pada kertas.
    Pre-processing: Gunakan Super-Resolution (SR) seperti Real-ESRGAN untuk memperbesar area teks 4x lipat sebelum masuk ke DINOv2.
    Mengapa Efektif? DINOv2 akan menangkap "cacat mikro" pada cetakan huruf (misal: titik tinta liar) yang konstan pada dokumen tersebut tetapi berbeda dengan dokumen hasil cetakan printer lain.

2. Deep Perceptual Hashing dengan Gabor Filters
Kertas modern seringkali memiliki pola halftone (titik-titik kecil) dari proses cetak offset.

    Alternatif: Gabungkan DINOv2 dengan Gabor Filters pada tahap pre-processing.
    Cara Kerja: Gabor filter sangat sensitif terhadap tekstur berulang dan orientasi garis. Ini membantu menonjolkan pola halftone yang biasanya tidak terlihat oleh mata manusia tetapi sangat unik secara matematis.
    Output: Gabungkan (concatenate) vektor Gabor dengan vektor DINOv2 untuk memperkuat "DNA" pada kertas yang halus.

3. Skenario "Specularity Mapping" (Multi-Flash)
Karena kertas modern cenderung lebih reflektif (glossy/semi-glossy), kita bisa memanfaatkan pantulan cahaya.

    Alternatif: Teknik Photometric Color Constancy.
    Pre-processing: Alih-alih satu foto, ambil dua foto (satu dengan flash, satu tanpa). Kurangi (subtract) foto satu dengan foto lainnya untuk mendapatkan Peta Pantulan (Specular Map).
    Mengapa Efektif? Peta pantulan ini menunjukkan kekasaran mikro permukaan kertas yang tidak terlihat pada foto RGB biasa. DINOv2 sangat kuat dalam mengenali pola anomali pada peta pantulan ini.

Perbandingan Strategi: Historis vs Modern
Aspek	Dokumen Historis	Dokumen Modern
Fokus Utama	Serat Selulosa & Noda Alami	Mikro-ink splatter & Pola Cetak
Pre-processing	Contrast Enhancement (CLAHE)	Super-Resolution & Edge Sharpening
Model	DINOv2 Standard	DINOv2 + Patch-based Magnification
Tingkat Kesulitan	Rendah (Tekstur melimpah)	Tinggi (Tekstur homogen)
Rekomendasi "Hybrid Fingerprinting"
Untuk sistem jutaan dokumen yang mencakup keduanya, gunakan Logic Switch:

    Sistem mendeteksi jenis kertas (via klasifikasi ringan).
    Jika Historis: Jalankan pipeline DINOv2 standar.
    Jika Modern: Jalankan pipeline Zoom-in Patch Extraction (fokus pada area teks yang diperbesar) sebelum di-hashing.