# System Design Document: Physical Hashing

## Archival Document Identification via Perceptual Hashing and Video Frame Extraction

---

## 1. Problem Statement

Archival workflows that digitize physical documents page-by-page via video recording introduce three core challenges:

1. **Document Identification** — Each video frame may or may not contain a distinct document page. The system must distinguish unique pages from redundant (inter-frame duplicate) captures.
2. **Transcription-Ready Image Extraction** — Frames suitable for OCR must be selected based on sharpness, alignment, and completeness, not merely presence.
3. **Barcode Replacement** — Physical documents in archival settings rarely carry machine-readable identifiers (barcodes, QR codes). The document's own visual content must serve as the unique identifier — a *physical hash*.

This system solves all three problems through a pipeline that combines **video keyframe extraction**, **perceptual hashing**, **document deduplication**, **image quality assessment**, and **OCR**.

---

## 2. System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                     PHYSICAL HASHING PIPELINE                       │
│                                                                     │
│  ┌──────────┐   ┌──────────────┐   ┌───────────────┐   ┌────────┐ │
│  │  Video   │──▶│  Keyframe    │──▶│  Perceptual   │──▶│ Dedup  │ │
│  │  Input   │   │  Extractor   │   │  Hasher       │   │ Engine │ │
│  └──────────┘   └──────────────┘   └───────────────┘   └───┬────┘ │
│                                                             │      │
│                                    ┌───────────────┐        │      │
│                                    │  Quality      │◀───────┘      │
│                                    │  Assessor     │               │
│                                    └──────┬────────┘               │
│                                           │                        │
│                          ┌────────────────┼───────────────┐        │
│                          ▼                ▼               ▼        │
│                   ┌───────────┐   ┌───────────┐   ┌───────────┐   │
│                   │    OCR    │   │  Physical  │   │  Document  │  │
│                   │  Engine   │   │  Hash ID   │   │  Archive   │  │
│                   └───────────┘   │  Generator │   │  Store     │  │
│                                   └───────────┘   └───────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Core Modules

### 3.1. Video Keyframe Extractor

**Purpose:** Extract candidate document frames from a video stream, discarding inter-frame duplicates and transitional frames (hand movement, page flips).

**Algorithm:**

1. Ingest video via OpenCV `VideoCapture`.
2. Apply scene change detection using content-based differencing (Structural Similarity Index — SSIM — or histogram comparison between consecutive frames).
3. For each detected scene change, extract the *most stable frame* within the scene (lowest motion blur, computed via Laplacian variance).
4. Output: ordered list of `(frame_index, timestamp, frame_image)` tuples.

**Key Parameters:**

| Parameter                 | Type    | Default | Description                                      |
| :------------------------ | :------ | :------ | :----------------------------------------------- |
| `scene_threshold`         | float   | 0.3     | SSIM delta threshold for scene change detection   |
| `min_scene_duration_ms`   | int     | 500     | Minimum scene duration to avoid false positives    |
| `blur_threshold`          | float   | 100.0   | Laplacian variance threshold for sharpness filter  |
| `sample_rate`             | int     | 5       | Process every Nth frame for performance            |

**Complexity:** $O(n)$ where $n$ is frame count. SSIM computation is $O(w \times h)$ per frame pair.

---

### 3.2. Perceptual Hasher

**Purpose:** Generate locality-sensitive fingerprints for each candidate frame, enabling near-duplicate detection invariant to minor scan/capture differences.

**Supported Algorithms:**

| Algorithm | Technique                      | Robustness          | Speed     | Hash Size |
| :-------- | :----------------------------- | :------------------ | :-------- | :-------- |
| **aHash** | Average luminance thresholding | Low                 | Fastest   | 64 bits   |
| **dHash** | Horizontal gradient comparison | Medium              | Fast      | 64 bits   |
| **pHash** | DCT-based frequency analysis   | High                | Moderate  | 64 bits   |
| **wHash** | Wavelet-based decomposition    | Highest             | Slowest   | 64 bits   |

**Default:** `pHash` — DCT provides optimal balance between robustness to minor visual perturbations (lighting, slight rotation, compression artifacts) and discriminative power.

**Similarity Metric:** Hamming distance between hash values.

$$d_H(h_1, h_2) = \sum_{i=0}^{63} h_1[i] \oplus h_2[i]$$

Two images are considered duplicates when $d_H < \tau$, where the default threshold $\tau = 10$.

---

### 3.3. Document Deduplication Engine

**Purpose:** Cluster extracted frames into equivalence classes where each class represents one unique physical document page.

**Algorithm:**

1. Compute perceptual hash for each candidate frame.
2. Build a hash index (VP-tree or BK-tree for efficient Hamming distance nearest-neighbor queries).
3. For each new hash, query the index with threshold $\tau$:
   - If a match is found → assign to existing cluster.
   - If no match → create new cluster.
4. Within each cluster, select the *representative frame* with the highest quality score.

**Data Structures:**

- **BK-Tree:** Metric tree optimized for discrete distance functions (Hamming). Lookup complexity: $O(\log n)$ average case.
- **Hash Index:** `Dict[int, List[FrameMetadata]]` for O(1) exact-match lookups before falling back to BK-tree for fuzzy matching.

---

### 3.4. Image Quality Assessor

**Purpose:** Rank candidate frames within a cluster to select the best representative for OCR.

**Quality Metrics (weighted combination):**

| Metric              | Weight | Computation                                              |
| :------------------ | :----- | :------------------------------------------------------- |
| Sharpness           | 0.40   | Laplacian variance of grayscale image                    |
| Contrast            | 0.20   | Standard deviation of pixel intensities                  |
| Alignment           | 0.20   | Hough line detection → angle deviation from orthogonal   |
| Completeness        | 0.10   | Document boundary detection (contour area / frame area)  |
| Noise Level         | 0.10   | Inverse of estimated noise (Median Absolute Deviation)   |

$$Q(f) = \sum_{i} w_i \cdot \hat{m}_i(f)$$

where $\hat{m}_i$ is the min-max normalized metric value.

---

### 3.5. OCR Engine

**Purpose:** Extract machine-readable text from the best representative frame of each unique document.

**Pipeline:**

1. **Preprocessing:** Adaptive thresholding (Otsu's method), deskewing, noise removal (morphological operations).
2. **Recognition:** Tesseract OCR with configurable language packs.
3. **Post-processing:** Confidence filtering ($c_{min} = 60\%$), layout-aware text reconstruction.

**Output:** Structured text with bounding box metadata per word/line.

---

### 3.6. Physical Hash ID Generator

**Purpose:** Generate a compact, deterministic identifier from a document's visual content — replacing traditional barcodes.

**Method:**

1. Compute `pHash` of the quality-assessed representative frame.
2. Concatenate with a truncated SHA-256 of the OCR text output (first 8 bytes).
3. Encode the composite hash as:
   - **Hex string:** for database storage and API usage.
   - **QR code:** for re-embedding on printed copies (optional downstream step).

**Composite Hash Structure:**

```
┌──────────────────────────┬──────────────────────────┐
│   pHash (64 bits / 8B)   │  SHA-256(OCR)[:8] (8B)   │
└──────────────────────────┴──────────────────────────┘
                    = 16 bytes = 128 bits
                    = 32-character hex string
```

**Properties:**

- **Perceptual stability:** Similar visual appearances → similar pHash component.
- **Content anchoring:** OCR hash ensures textual content contributes to identity.
- **Collision resistance:** The combination of visual + textual hash reduces collision probability to negligible levels for archival-scale datasets ($< 10^6$ documents).

---

## 4. Technology Stack

| Component            | Technology              | Justification                                               |
| :------------------- | :---------------------- | :---------------------------------------------------------- |
| **Language**         | Python 3.11+            | Ecosystem dominance in CV/ML, Tesseract bindings, rapid iteration |
| **Video Processing** | OpenCV 4.x              | Industry standard, hardware-accelerated decode               |
| **Scene Detection**  | PySceneDetect           | Purpose-built for shot boundary detection                    |
| **Perceptual Hash**  | `imagehash` + Pillow    | Maintained library implementing pHash/dHash/aHash/wHash      |
| **OCR**              | Tesseract 5.x (pytesseract) | Best open-source OCR engine, multi-language support      |
| **Image Processing** | scikit-image, NumPy     | Robust quality metrics, array operations                     |
| **Data Storage**     | SQLite (prototype) → PostgreSQL (production) | Zero-config local, scalable remote        |
| **QR Generation**    | `qrcode` library        | Lightweight, PNG/SVG output                                  |
| **CLI Framework**    | `click` or `argparse`   | Structured command-line interface                            |
| **Testing**          | `pytest` + `hypothesis` | Property-based testing for hash invariants                   |

---

## 5. Data Model

### 5.1. Database Schema

```sql
CREATE TABLE documents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    physical_hash   TEXT UNIQUE NOT NULL,     -- 32-char hex composite hash
    phash_visual    TEXT NOT NULL,            -- 16-char hex pHash
    phash_text      TEXT,                     -- 16-char hex SHA-256(OCR)[:8]
    ocr_text        TEXT,                     -- full OCR output
    ocr_confidence  REAL,                     -- average confidence score
    source_video    TEXT NOT NULL,            -- source video file path
    frame_index     INTEGER NOT NULL,         -- best frame index in video
    timestamp_ms    INTEGER NOT NULL,         -- timestamp in milliseconds
    quality_score   REAL NOT NULL,            -- composite quality score
    image_path      TEXT NOT NULL,            -- path to extracted image file
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_phash_visual ON documents(phash_visual);
CREATE INDEX idx_source_video ON documents(source_video);
```

### 5.2. Output Directory Structure

```
output/
├── {video_name}/
│   ├── frames/                  -- all candidate keyframes
│   │   ├── frame_0001_t12340.png
│   │   ├── frame_0002_t15670.png
│   │   └── ...
│   ├── documents/               -- deduplicated best-quality frames
│   │   ├── doc_001_{phash}.png
│   │   ├── doc_002_{phash}.png
│   │   └── ...
│   ├── ocr/                     -- OCR text output per document
│   │   ├── doc_001_{phash}.txt
│   │   ├── doc_002_{phash}.json  -- structured with bounding boxes
│   │   └── ...
│   ├── qrcodes/                 -- generated QR codes per document
│   │   ├── doc_001_{phash}.png
│   │   └── ...
│   └── manifest.json            -- pipeline run metadata
```

---

## 6. Pipeline Execution Flow

```python
# Pseudocode
def process_video(video_path: str, config: PipelineConfig) -> PipelineResult:
    # Phase 1: Extract keyframes
    keyframes = keyframe_extractor.extract(video_path, config.extraction)

    # Phase 2: Compute perceptual hashes
    for kf in keyframes:
        kf.phash = perceptual_hasher.compute(kf.image, algorithm="phash")

    # Phase 3: Deduplicate
    clusters = dedup_engine.cluster(keyframes, threshold=config.dedup_threshold)

    # Phase 4: Select best frame per cluster
    documents = []
    for cluster in clusters:
        best = quality_assessor.select_best(cluster.frames)
        documents.append(best)

    # Phase 5: OCR
    for doc in documents:
        doc.ocr_result = ocr_engine.recognize(doc.image, lang=config.ocr_lang)

    # Phase 6: Generate physical hash IDs
    for doc in documents:
        doc.physical_hash = hash_id_generator.generate(
            visual_hash=doc.phash,
            text_content=doc.ocr_result.text
        )

    # Phase 7: Persist
    storage.save(documents)

    return PipelineResult(documents=documents, stats=compute_stats(keyframes, clusters))
```

---

## 7. Configuration

```yaml
# config.yaml
pipeline:
  video_extensions: [".mp4", ".avi", ".mov", ".mkv"]

extraction:
  scene_threshold: 0.3
  min_scene_duration_ms: 500
  blur_threshold: 100.0
  sample_rate: 5

hashing:
  algorithm: "phash"         # phash | dhash | ahash | whash
  hash_size: 8               # produces hash_size^2 bit hash
  dedup_threshold: 10        # Hamming distance threshold

quality:
  weights:
    sharpness: 0.40
    contrast: 0.20
    alignment: 0.20
    completeness: 0.10
    noise: 0.10

ocr:
  engine: "tesseract"
  language: "ind+eng"        # Indonesian + English
  min_confidence: 60
  dpi: 300
  preprocessing:
    deskew: true
    denoise: true
    adaptive_threshold: true

output:
  format: "png"              # png | tiff | jpeg
  dpi: 300
  generate_qr: true
  database: "sqlite:///output/physical_hashing.db"
```

---

## 8. Performance Considerations

| Metric              | Target                    | Strategy                                              |
| :------------------ | :------------------------ | :---------------------------------------------------- |
| Throughput           | 30 FPS video processed    | Frame sampling (every Nth), parallel hash computation |
| Dedup Accuracy       | > 99% precision/recall    | Multi-algorithm voting (pHash + dHash consensus)      |
| OCR Accuracy         | > 95% for printed text    | Image preprocessing pipeline, Tesseract LSTM engine   |
| Memory Usage         | < 2 GB for 1-hour video   | Streaming frame processing, no full video in memory   |
| Storage              | ~500 KB per document page | PNG compression at 300 DPI                            |

---

## 9. Error Handling

| Failure Mode                      | Detection                     | Recovery                                 |
| :-------------------------------- | :---------------------------- | :--------------------------------------- |
| Corrupt video file                | OpenCV read failure           | Log error, skip to next video            |
| No keyframes detected             | Empty extraction result       | Reduce scene threshold, retry            |
| All frames below quality threshold| Quality assessor returns None | Lower threshold, flag for manual review  |
| OCR produces empty output         | Zero recognized characters    | Flag document, store image without text  |
| Hash collision between distinct docs | Manual review queue        | Human verification interface             |

---

## 10. Future Extensions

1. **Deep Learning Deduplication:** Replace perceptual hashing with learned embeddings (CLIP, DINOv2) for higher accuracy on degraded documents.
2. **Layout Analysis:** Segment document regions (headers, body, tables, images) before OCR for structured extraction.
3. **Batch Video Processing:** Multi-video pipeline with cross-video deduplication.
4. **Web Interface:** Browser-based review interface for quality verification and hash collision resolution.
5. **Blockchain Anchoring:** Hash registration on a public ledger for tamper-proof provenance.