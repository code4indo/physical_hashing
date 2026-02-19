# Document Identification Strategy

## 🆔 Three Types of IDs in the System

### 1. **Database ID** (`id`) - Internal Auto-increment
- **Type**: Integer (1, 2, 3, ...)
- **Purpose**: Primary key for database queries
- **Scope**: Internal use only
- **Generation**: Auto-increment by SQLite/PostgreSQL
- **Example**: `42`

```python
doc = session.query(Document).filter_by(id=42).first()
```

---

### 2. **Document Fingerprint** (`fingerprint`) - Public UUID
- **Type**: UUID v4 (universally unique identifier)
- **Purpose**: Public-facing document identifier for API/UI
- **Scope**: External APIs, sharing, permanent references
- **Generation**: Auto-generated on document creation
- **Example**: `"a3f2b8c9-1234-5678-9abc-def012345678"`

**Why UUID?**
- ✅ Globally unique - no collisions even across systems
- ✅ Can be generated client-side before server insertion
- ✅ Not sequential - hides database size & prevents enumeration attacks
- ✅ Safe for public URLs: `/api/v1/documents/a3f2b8c9-1234-5678-9abc-def012345678`

```python
# User-facing API
GET /api/v1/documents/{fingerprint}
GET /api/v1/documents/a3f2b8c9-1234-5678-9abc-def012345678

# Response
{
  "fingerprint": "a3f2b8c9-1234-5678-9abc-def012345678",
  "khazanah": "Arsip Nasional",
  "created_at": "2026-02-14T10:30:00Z"
}
```

---

### 3. **Vector ID** (`vector_id`) - FAISS Index Position
- **Type**: Integer (0, 1, 2, ...)
- **Purpose**: Internal pointer to position in FAISS vector index
- **Scope**: FAISS library only - **NOT a fingerprint**
- **Generation**: Allocated sequentially by `VectorIDAllocator`
- **Example**: `27`

**Why Integer?**
- ✅ **FAISS requires it** - library only supports integer indexing
- ✅ O(1) array access performance
- ✅ Memory efficient (4 bytes vs 16 bytes for UUID)
- ❌ **Not globally unique** - can be reused after soft-delete

```python
# Internal use only
faiss_index.search(query_vector, k=5)
# Returns: [27, 42, 13, 8, 91]  <- These are vector_ids

# Map back to document IDs
id_map = [doc_id_1, doc_id_2, doc_id_3, ...]
doc_id = id_map[vector_id]
```

---

### 4. **Content Hash** (`content_hash`) - SHA256 of Image
- **Type**: String (64-char hexadecimal)
- **Purpose**: Deduplication - detect identical documents
- **Scope**: Before saving to prevent duplicates
- **Generation**: SHA256 hash of processed image bytes
- **Example**: `"a7f3c2e1d9b8f4a6c5e2d8f9b1c0a3e4..."`

**Use Case**: Prevent duplicate uploads

```python
# Before inserting new document
content_hash = compute_file_hash(image_path)

existing = session.query(Document).filter_by(content_hash=content_hash).first()
if existing:
    return {
        "error": "Duplicate document detected",
        "existing_fingerprint": existing.fingerprint,
        "message": f"This document already exists: {existing.khazanah}"
    }
```

---

## 📊 Comparison Table

| ID Type | Example | Size | Unique? | Public? | Purpose |
|---------|---------|------|---------|---------|---------|
| **Database ID** | `42` | 4-8 bytes | Per-DB | ❌ No | DB queries |
| **Fingerprint (UUID)** | `a3f2b8c9-...` | 16 bytes | Global | ✅ Yes | Public API |
| **Vector ID** | `27` | 4 bytes | Per-index | ❌ No | FAISS lookup |
| **Content Hash** | `a7f3c2e1...` | 32 bytes | Per-content | ⚠️ Internal | Deduplication |

---

## 🎯 When to Use Which ID?

### ✅ Use **Fingerprint (UUID)** for:
- Public API endpoints
- Sharing documents with external users
- QR codes / links to documents
- Mobile app references
- Long-term archival citations

```dart
// Flutter app
final response = await http.get(
  '$serverUrl/api/v1/documents/${document.fingerprint}'
);
```

### ✅ Use **Database ID** for:
- Internal database joins
- Admin tools / debugging
- Batch processing scripts

```python
# Admin script
for doc_id in range(1000, 2000):
    process_document(doc_id)
```

### ✅ Use **Vector ID** for:
- FAISS index operations only
- Never expose to users
- Internal vector search mapping

```python
# Internal worker
faiss_results = index.search(query, k=5)
doc_ids = [id_map[vid] for vid in faiss_results]
```

### ✅ Use **Content Hash** for:
- Deduplication checks before insert
- Integrity verification
- Finding exact duplicates

```python
# Check for duplicates
if session.query(Document).filter_by(content_hash=new_hash).exists():
    raise DuplicateError()
```

---

## 🔒 Security Benefits of UUID

### Problem with Sequential IDs:
```
❌ BAD: GET /api/v1/documents/42
        GET /api/v1/documents/43  <- Attacker can enumerate all docs
        GET /api/v1/documents/44
```

### Solution with UUIDs:
```
✅ GOOD: GET /api/v1/documents/a3f2b8c9-1234-5678-9abc-def012345678
         GET /api/v1/documents/f9e2d1c8-9876-5432-1abc-543210fedcba
         <- Impossible to guess other IDs
```

---

## 💾 Database Schema

```sql
CREATE TABLE documents (
    -- Internal DB primary key
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- Public-facing unique identifier
    fingerprint VARCHAR(36) UNIQUE NOT NULL,
    
    -- Content-based deduplication
    content_hash VARCHAR(64) UNIQUE,
    
    -- FAISS index position (internal only)
    vector_id INTEGER UNIQUE,
    
    -- Document metadata
    khazanah VARCHAR(255) NOT NULL,
    page_number INTEGER,
    description TEXT,
    image_path VARCHAR(512),
    
    -- Status tracking
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP
);

CREATE INDEX idx_fingerprint ON documents(fingerprint);
CREATE INDEX idx_content_hash ON documents(content_hash);
CREATE INDEX idx_status ON documents(status);
```

---

## 🚀 API Response Example

```json
{
  "fingerprint": "a3f2b8c9-1234-5678-9abc-def012345678",
  "khazanah": "Arsip Nasional - Bundle A",
  "page_number": 42,
  "description": "Historical manuscript",
  "image_url": "/uploads/a3f2b8c9_clean.png",
  "status": "completed",
  "created_at": "2026-02-14T10:30:00Z",
  "content_hash": "a7f3c2e1d9b8f4a6...",
  
  // Internal fields (optional, for admin only)
  "_internal": {
    "id": 123,
    "vector_id": 456
  }
}
```

---

## 🎓 Best Practices

1. **Never expose `vector_id` to users** - it's an internal FAISS implementation detail
2. **Always use `fingerprint` in public APIs** - it's globally unique and secure
3. **Use `content_hash` for deduplication** - check before insert
4. **Keep `id` for database operations** - fastest for internal queries
5. **Index all ID fields** - fingerprint, content_hash, status for fast lookups

---

## 🔄 Migration from Old System

If you have existing documents with only `id` and `vector_id`:

```python
import uuid

# Add fingerprint to existing documents
for doc in session.query(Document).filter(Document.fingerprint == None):
    doc.fingerprint = str(uuid.uuid4())
    
session.commit()
```

---

## 📚 Further Reading

- [UUID RFC 4122](https://tools.ietf.org/html/rfc4122)
- [FAISS Index Design](https://github.com/facebookresearch/faiss/wiki)
- [Cryptographic Hash Functions](https://en.wikipedia.org/wiki/SHA-2)
- [OWASP: Insecure Direct Object References](https://owasp.org/www-project-top-ten/2017/A5_2017-Broken_Access_Control)
