# Vector ID Management untuk Jutaan Dokumen

## 📋 Ringkasan

Sistem ini dirancang untuk mengelola jutaan dokumen arsip dengan efisien menggunakan **soft-delete** dan **vector ID reuse strategy**.

## 🎯 Masalah yang Dipecahkan

### Masalah Sebelumnya:
1. **UNIQUE constraint conflict**: Saat dokumen dihapus lalu diupload ulang, `vector_id` konflik
2. **Expensive FAISS rebuilds**: Setiap delete memicu rebuild seluruh index
3. **ID fragmentation**: Vector ID terus bertambah meski banyak dokumen dihapus

### Solusi:
✅ **Soft Delete** - Dokumen tidak benar-benar dihapus, hanya ditandai `status='deleted'`
✅ **Vector ID Reuse** - ID dari dokumen terhapus bisa dipakai ulang
✅ **Dual Strategy** - Pilih antara performance vs space efficiency

---

## 🔧 Konfigurasi

Edit `.env` atau environment variables:

```bash
# Vector ID allocation strategy
VECTOR_ID_STRATEGY=reuse_gaps  # atau "sequential"
```

### Strategy Options:

#### 1. **`sequential`** (Fastest)
- **Cara kerja**: Selalu increment dari `max(vector_id) + 1`
- **Pros**: 
  - ⚡ Sangat cepat O(1) allocation
  - 🧩 Simple implementation
- **Cons**: 
  - 📈 ID terus naik meski banyak delete
  - 💾 FAISS index bisa punya "holes" (wasted space)
- **Best for**: Write-heavy, jarang delete (e.g., permanent archive)

#### 2. **`reuse_gaps`** (Recommended)
- **Cara kerja**: Cari vector_id dari dokumen deleted, kalau tidak ada baru allocate baru
- **Pros**:
  - ♻️ Reuse freed IDs → compact index
  - 💾 Space-efficient untuk jutaan dokumen
  - 🔄 Ideal untuk high-churn workloads
- **Cons**:
  - 🐌 Sedikit lebih lambat (perlu query deleted docs)
- **Best for**: **Production dengan frequent updates/replacements**

---

## 🗃️ Database Schema

```python
class Document(Base):
    id: int                      # Primary key
    khazanah: str                # Collection name
    page_number: int | None      
    description: str | None
    image_path: str
    vector_id: int | None        # ⚠️ Nullable, unique only when set
    created_at: datetime
    status: str                  # pending | processing | completed | failed | deleted
    error_message: str | None
    deleted_at: datetime | None  # ✨ Timestamp saat soft-delete
```

### Status Flow:

```
pending → processing → completed
              ↓
            failed
              ↓
           deleted (soft-delete)
```

---

## 📊 Cara Kerja

### Upload Dokumen Baru:

```python
# 1. Create document record (status='pending', vector_id=None)
doc = Document(khazanah="...", status="pending")

# 2. Enqueue untuk background processing
await enqueue(ProcessingJob(doc_id=doc.id, ...))

# 3. Worker allocates vector_id SEBELUM processing
async with session:
    allocated_id = await allocator.allocate_next_id(session)
    # Update: status='processing', vector_id=allocated_id

# 4. AI processing (extract embedding, add to FAISS)
# 5. Update: status='completed'
```

### Soft Delete:

```python
# Mark as deleted - tidak hapus dari FAISS
UPDATE documents 
SET status='deleted', deleted_at=NOW()
WHERE id=?

# Vector ID sekarang bisa di-reuse untuk dokumen baru!
```

### Reuse Gap:

```python
# Saat allocate ID baru, cari dulu yang deleted
SELECT vector_id FROM documents 
WHERE status='deleted' AND vector_id IS NOT NULL
LIMIT 1

# Jika ada, reuse ID tersebut
# Jika tidak, allocate sequential: max(vector_id) + 1
```

---

## 🚀 Performance untuk Jutaan Dokumen

### Scalability:

| Metric | Sequential | Reuse Gaps |
|--------|-----------|------------|
| **Allocation Speed** | O(1) - 0.1ms | O(log N) - 0.5ms |
| **FAISS Index Size** | Growing forever | Stays compact |
| **Delete Speed** | O(1) soft-delete | O(1) soft-delete |
| **Space Efficiency** | Low (holes) | High (reuse) |

### Estimasi untuk 10 Juta Dokumen:

**Sequential Strategy:**
- FAISS vectors: ~10M rows (meski 3M deleted)
- Disk: ~40GB FAISS index
- Memory: ~40GB RAM untuk load

**Reuse Gaps Strategy:**
- FAISS vectors: ~7M rows aktif
- Disk: ~28GB FAISS index  
- Memory: ~28GB RAM
- **Saving: 30% space & RAM** 💾

---

## 🧹 Cleanup (Optional)

Untuk benar-benar hapus dokumen lama yang sudah deleted > 90 hari:

```python
# Create periodic cleanup job (bisa pakai cron/celery)
async def cleanup_old_deleted_documents():
    """Hard delete documents that have been soft-deleted for > 90 days."""
    from datetime import datetime, timedelta, timezone
    
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    
    stmt = select(Document).where(
        Document.status == "deleted",
        Document.deleted_at < cutoff
    )
    docs = await session.execute(stmt)
    
    for doc in docs.scalars():
        # Remove from FAISS (rebuild index without these)
        # Delete image files
        # Delete from database
        ...
    
    # Rebuild FAISS index to reclaim space
    index.rebuild()
```

---

## 🔍 Monitoring

### Check ID Utilization:

```sql
-- Total documents by status
SELECT status, COUNT(*) FROM documents GROUP BY status;

-- Vector ID gaps (potential reuse)
SELECT COUNT(*) as reusable_ids 
FROM documents 
WHERE status='deleted' AND vector_id IS NOT NULL;

-- Highest vector_id (max FAISS index size)
SELECT MAX(vector_id) FROM documents;
```

### Grafana Metrics (Future):

- `vector_id_allocations_total{strategy="reuse_gaps"}`
- `vector_id_reused_total`
- `documents_deleted_count`
- `faiss_index_size_bytes`

---

## 🎓 Best Practices

1. **Use `reuse_gaps` in production** untuk system dengan frequent updates
2. **Monitor deleted_count** - jika > 30% total, run cleanup job
3. **Batch FAISS saves** - save setiap 10 docs, bukan setiap doc
4. **Index `status` column** - queries filter by status frequently
5. **Consider hard-delete cleanup** untuk data > 90 hari

---

## 🔐 Migration dari Sistem Lama

Jika sudah punya data dengan system lama:

```bash
# 1. Backup database & FAISS index
cp data/arch_fingerprint.db data/arch_fingerprint.db.backup
cp data/faiss.index data/faiss.index.backup

# 2. Add new columns
alembic revision --autogenerate -m "add soft delete support"
alembic upgrade head

# 3. Update config
export VECTOR_ID_STRATEGY=reuse_gaps

# 4. Restart server
```

---

## 📈 Roadmap

- [ ] Auto cleanup scheduler (celery periodic task)
- [ ] Grafana dashboard untuk monitoring
- [ ] FAISS index compaction tool
- [ ] Multi-index sharding untuk > 100M documents
- [ ] Distributed FAISS dengan Milvus/Weaviate

---

## 📞 Support

Untuk pertanyaan atau issue, check:
- Source: `src/arch_fingerprint/db/vector_id_manager.py`
- Config: `src/arch_fingerprint/config.py`
- Worker: `src/arch_fingerprint/worker/queue.py`

**Happy Archiving! 📚✨**
