"""Lightweight async background job queue for AI processing.

For millions of documents, this can be replaced with Celery + Redis.
This version uses asyncio + ThreadPoolExecutor for single-server deployments.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from arch_fingerprint.ai.preprocessing_sam import preprocess_from_bytes
from arch_fingerprint.config import settings

logger = logging.getLogger(__name__)

# Dedicated thread pool for AI work — separate from FastAPI's default pool
_ai_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ai-worker")

# Global async lock to prevent race condition on vector_id allocation
# across concurrent background jobs in batch uploads
_vector_id_lock = asyncio.Lock()

# Async queue for pending jobs
_job_queue: asyncio.Queue | None = None
_worker_task: asyncio.Task | None = None


@dataclass
class ProcessingJob:
    """A document waiting for AI processing."""
    doc_id: int
    raw_image_path: str  # Path to saved raw upload
    mode: str = "single" # 'single' or 'book'
    is_handwriting: bool = False # Skip OCR if True


def get_queue() -> asyncio.Queue:
    global _job_queue
    if _job_queue is None:
        _job_queue = asyncio.Queue(maxsize=10000)
    return _job_queue


async def enqueue(job: ProcessingJob) -> None:
    """Add a job to the processing queue. Non-blocking."""
    q = get_queue()
    await q.put(job)
    logger.info("Enqueued doc_id=%d. Queue size: %d", job.doc_id, q.qsize())


def _process_document_sync(doc_id: int, raw_path: str, mode: str, embedder, index, start_vector_id: int | None = None) -> dict:
    """Heavy AI processing — runs in thread pool.
    
    Args:
        doc_id: Document ID
        raw_path: Path to raw uploaded image
        mode: 'single' or 'book' scanning mode
        embedder: AI embedder instance
        index: FAISS index instance
        start_vector_id: Optional starting ID. If None, uses current index size.
    
    Returns dict with results to be committed in async context.
    """
    from PIL import Image
    from arch_fingerprint.utils.hashing import compute_file_hash
    from arch_fingerprint.ai.region_strategy import crop_regions

    # 1. Load raw image
    raw_bytes = Path(raw_path).read_bytes()

    # 2. Background removal (rembg + U-2-Net)
    processed_image = preprocess_from_bytes(raw_bytes, mode=mode)
    
    # Apply perspective correction (auto-flatten)
    from arch_fingerprint.ai.robustness import correct_perspective
    processed_image = correct_perspective(processed_image)

    # 3. Save processed image as separate cleaner version
    processed_path = Path(raw_path).parent / f"{Path(raw_path).stem.replace('_raw', '')}_clean.png"
    processed_image.save(processed_path, format="PNG")
    
    # 4. Compute content hash for deduplication (SHA256 of processed image)
    content_hash = compute_file_hash(processed_path, algorithm="sha256")

    # 5. Multi-view augmented embedding for robust identification
    # Generates augmented views (flip, perspective warps) so documents
    # can be identified from different camera angles
    from arch_fingerprint.ai.region_strategy import crop_regions
    from arch_fingerprint.ai.robustness import generate_augmented_views
    
    registration_strategy = "9-grid"
    augmented_views = generate_augmented_views(processed_image)
    
    logger.info("doc_id=%d: Strategy='%s' | Augmented views=%d", 
                doc_id, registration_strategy, len(augmented_views))
    
    # 6. Extract embeddings for each view × each region → add to FAISS
    if start_vector_id is None:
        start_vector_id = index.total_vectors
        
    vector_offset = 0
    for view_name, view_image in augmented_views:
        regions = crop_regions(view_image, registration_strategy)
        
        for region_name, crop_img, weight in regions:
            embedding = embedder.extract_embedding(crop_img)
            
            expected_faiss_idx = start_vector_id + vector_offset
            actual_faiss_idx = index.add(doc_id, embedding)
            
            if actual_faiss_idx != expected_faiss_idx:
                logger.warning(
                    "FAISS mismatch doc_id=%d view=%s region=%s: expected %d, got %d",
                    doc_id, view_name, region_name, expected_faiss_idx, actual_faiss_idx
                )
            
            vector_offset += 1
        
        logger.info("  View '%s': %d region embeddings indexed", view_name, len(regions))
    
    logger.info("doc_id=%d: Total vectors indexed = %d (%d views × %d regions)",
                doc_id, vector_offset, len(augmented_views), len(regions))

    return {
        "processed_path": str(processed_path),
        "content_hash": content_hash,
        "start_vector_id": start_vector_id,  # Return the actual start position
    }


async def _worker_loop():
    """Continuously process jobs from the queue."""
    # Import dependencies upfront — if any fail, the worker task will crash
    # and _worker_done_callback will log it clearly.
    from arch_fingerprint.api.state import get_embedder, get_vector_index, get_text_embedder, get_text_vector_index
    from arch_fingerprint.db.session import async_session_factory
    from arch_fingerprint.db.models import Document
    from arch_fingerprint.db.vector_id_manager import get_vector_id_allocator
    from arch_fingerprint.config import settings as app_settings
    from arch_fingerprint.ai.ocr import run_ocr_async
    from sqlalchemy import update, select as sa_select, func

    q = get_queue()
    logger.info("Background AI worker started. Waiting for jobs...")

    # Get configured vector ID allocator
    allocator = get_vector_id_allocator(app_settings.vector_id_strategy)

    # Batch save counter — save FAISS every N docs instead of every doc
    docs_since_last_save = 0
    FAISS_SAVE_INTERVAL = 10

    while True:
        job: ProcessingJob = await q.get()
        logger.info("Processing doc_id=%d (queue remaining: %d)", job.doc_id, q.qsize())

        try:
            # Update status to processing
            async with async_session_factory() as session:
                await session.execute(
                    update(Document)
                    .where(Document.id == job.doc_id)
                    .values(status="processing")  # Don't set vector_id yet
                )
                await session.commit()

            # =================================================================
            # SEQUENTIAL execution to avoid GPU VRAM contention.
            # DINOv2 (~1.3GB) + FastSAM (~4GB) + Ollama GLM-OCR (~4.3GB)
            # would exceed 16GB VRAM if run in parallel.
            # =================================================================
            
            embedder = get_embedder()
            index = get_vector_index()
            loop = asyncio.get_event_loop()

            # =================================================================
            # KRITIS: Alokasikan start_vector_id dengan lock SEBELUM
            # proses AI berjalan di thread pool.
            #
            # Tanpa lock ini, batch upload (banyak job masuk hampir bersamaan)
            # bisa membaca index.total_vectors yang sama (race condition),
            # sehingga dua dokumen mendapat vector_id identik →
            # UNIQUE constraint failed.
            # =================================================================
            async with _vector_id_lock:
                start_vector_id = index.total_vectors
                logger.debug(
                    "doc_id=%d: Reserved start_vector_id=%d (index size before processing)",
                    job.doc_id, start_vector_id,
                )

            # Step 1: Visual Embedding (GPU-heavy: DINOv2 + FastSAM)
            logger.info("doc_id=%d: Starting visual processing...", job.doc_id)
            visual_result = await loop.run_in_executor(
                _ai_executor,
                _process_document_sync,
                job.doc_id,
                job.raw_image_path,
                job.mode,
                embedder,
                index,
                start_vector_id,  # Gunakan ID yang sudah di-reserve
            )
            logger.info("doc_id=%d: Visual processing complete.", job.doc_id)
            
            # Step 2: OCR (GPU via Ollama — runs AFTER visual to avoid VRAM clash)
            # SKIPPED if job is marked as Handwriting/Paleography to save GPU and avoid garbage.
            ocr_text = None
            if job.is_handwriting:
                logger.info("doc_id=%d: Marked as HANDWRITING. Skipping OCR to prevent hallucinations.", job.doc_id)
                ocr_text = "[HANDWRITING - SKIPPED]"
            else:
                try:
                    logger.info("doc_id=%d: Starting OCR...", job.doc_id)
                    ocr_text = await run_ocr_async(job.raw_image_path)
                    
                    if ocr_text and len(ocr_text.strip()) > 10:
                        logger.info("doc_id=%d: OCR success — %d chars extracted.", job.doc_id, len(ocr_text))
                        
                        # Step 3: Semantic Embedding (CPU/GPU)
                        try:
                            text_embedder = get_text_embedder()
                            text_index = get_text_vector_index()
                            
                            # Generate embedding
                            text_vector = await loop.run_in_executor(
                                _ai_executor, 
                                text_embedder.encode, 
                                ocr_text
                            )
                            
                            # Add to Text FAISS Index
                            await loop.run_in_executor(
                                _ai_executor,
                                text_index.add,
                                job.doc_id,
                                text_vector
                            )
                            logger.info("doc_id=%d: Semantic embedding added to Text Index.", job.doc_id)
                            
                        except Exception as sem_err:
                            logger.error("doc_id=%d: Semantic embedding failed: %s", job.doc_id, sem_err)
                    else:
                        logger.warning("doc_id=%d: OCR returned no text or too short.", job.doc_id)
                        
                except Exception as ocr_err:
                    logger.error("doc_id=%d: OCR failed (non-fatal): %s", job.doc_id, ocr_err)
                    # OCR failure is non-fatal — document still gets indexed visually

            start_vector_id = visual_result["start_vector_id"]
            
            # Step 3: Save results to DB with UNIQUE conflict handling
            async with async_session_factory() as session:
                # Safety net: cek apakah vector_id sudah dipakai dokumen lain
                # (bisa terjadi jika lock di atas di-bypass karena restart/recovery)
                conflict = await session.execute(
                    sa_select(Document.id)
                    .where(Document.vector_id == start_vector_id)
                    .where(Document.id != job.doc_id)
                )
                if conflict.scalar() is not None:
                    # vector_id sudah dipakai — ambil nilai baru yang aman
                    max_result = await session.execute(
                        sa_select(func.max(Document.vector_id))
                        .where(Document.vector_id.isnot(None))
                    )
                    max_vid = max_result.scalar() or 0
                    start_vector_id = max_vid + 1
                    logger.warning(
                        "doc_id=%d: vector_id conflict detected, reassigned to %d",
                        job.doc_id, start_vector_id,
                    )

                # Update main document metadata
                stmt = (
                    update(Document)
                    .where(Document.id == job.doc_id)
                    .values(
                        image_path=visual_result["processed_path"],
                        content_hash=visual_result["content_hash"],
                        vector_id=start_vector_id,
                        text_content=ocr_text,
                        status="completed"
                    )
                )
                await session.execute(stmt)
                await session.commit()
                
            logger.info("✅ JOB COMPLETE: doc_id=%d | vector_id=%d | text=%d chars", 
                        job.doc_id, start_vector_id, len(ocr_text) if ocr_text else 0)

            docs_since_last_save += 1

            # Batch-save FAISS index periodically
            if docs_since_last_save >= FAISS_SAVE_INTERVAL:
                await loop.run_in_executor(
                    _ai_executor, index.save, settings.faiss_index_path
                )
                # Also save text index if it exists
                # We need to access text_index from outer scope or re-get it
                try: 
                    ti = get_text_vector_index()
                    await loop.run_in_executor(
                        _ai_executor, ti.save, settings.faiss_text_index_path
                    )
                except:
                    pass
                
                docs_since_last_save = 0
                logger.info("FAISS indexes saved (batch checkpoint).")

            logger.info("✅ doc_id=%d completed.", job.doc_id)

        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            logger.error("❌ doc_id=%d failed: %s\n%s", job.doc_id, str(e), error_details)
            
            # Mark as failed in DB
            try:
                async with async_session_factory() as session:
                    await session.execute(
                        update(Document)
                        .where(Document.id == job.doc_id)
                        .values(status="failed", error_message=str(e)[:500])
                    )
                    await session.commit()
            except Exception as db_err:
                logger.critical("Failed to update status to 'failed' for doc_id=%d: %s", job.doc_id, db_err)
        finally:
            q.task_done()


async def recover_pending_jobs():
    """Find documents stuck in 'pending' or 'processing' and re-enqueue them."""
    from arch_fingerprint.db.session import async_session_factory
    from arch_fingerprint.db.models import Document
    from sqlalchemy import select, or_

    async with async_session_factory() as session:
        stmt = select(Document).where(
            or_(Document.status == "pending", Document.status == "processing")
        )
        result = await session.execute(stmt)
        docs = result.scalars().all()

        if docs:
            logger.info("Found %d stuck jobs. Re-enqueuing...", len(docs))
            for doc in docs:
                await enqueue(ProcessingJob(doc_id=doc.id, raw_image_path=doc.image_path, mode="single")) # Default to single for recovery


def _worker_done_callback(task: asyncio.Task):
    """Log if the worker task crashes unexpectedly."""
    try:
        exc = task.exception()
        if exc is not None:
            logger.critical(
                "🚨 Background worker CRASHED: %s: %s",
                type(exc).__name__, exc,
                exc_info=exc,
            )
    except asyncio.CancelledError:
        logger.info("Background worker cancelled (shutdown).")


async def start_worker():
    """Start the background worker as an asyncio task and recover old jobs."""
    global _worker_task
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_worker_loop(), name="ai-worker-loop")
        # Attach callback so crashes are logged instead of silently swallowed
        _worker_task.add_done_callback(_worker_done_callback)
        # Give worker a moment to start, then recover old jobs
        asyncio.create_task(recover_pending_jobs())
    return _worker_task


async def shutdown_worker():
    """Stop the worker and clean up resources."""
    global _worker_task
    logger.info("Stopping background worker...")
    from arch_fingerprint.api.state import get_vector_index, get_text_vector_index

    q = get_queue()
    if not q.empty():
        logger.info("Draining %d remaining jobs before shutdown...", q.qsize())
        await q.join()

    # Final FAISS save
    index = get_vector_index()
    await asyncio.to_thread(index.save, settings.faiss_index_path)
    
    # Save Text Index
    try:
        ti = get_text_vector_index()
        await asyncio.to_thread(ti.save, settings.faiss_text_index_path)
        logger.info("Final Text FAISS index saved.")
    except Exception as e:
        logger.warning(f"Failed to save Text FAISS index on shutdown: {e}")

    logger.info("Final FAISS indexes saved.")

    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
