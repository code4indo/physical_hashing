"""POST /api/v1/search — Search for matching documents.

Accepts a query image (e.g., from an Android phone camera), extracts the
DINOv2 embedding, and searches the FAISS index for the most similar
registered documents.

Configurable thresholds can be passed from the client for transparent tuning.
"""

import asyncio
import logging
import time
import numpy as np

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from arch_fingerprint.ai.preprocessing_sam import preprocess_from_bytes
from arch_fingerprint.api.schemas import SearchMatch, SearchResponse
from arch_fingerprint.api.state import get_embedder, get_vector_index, get_text_embedder, get_text_vector_index
from arch_fingerprint.config import settings
from arch_fingerprint.db.models import Document
from arch_fingerprint.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/search", response_model=SearchResponse)
async def search_document(
    image: UploadFile = File(..., description="Query document image"),
    top_k: int = Form(5, description="Number of results to return"),
    visual_threshold: float = Form(0.55, description="Min visual similarity to consider a candidate"),
    text_threshold: float = Form(0.20, description="Min combined text ratio for hybrid match"),
    visual_only_threshold: float = Form(0.70, description="Min visual score when OCR is unavailable"),
    use_ocr: bool = Form(False, description="Enable OCR text verification (THOROUGH mode)."),
    region_strategy: str = Form("4-strip", description="Region strategy: '4-strip', '9-grid', or '16-grid'"),
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    """Search for the most similar registered documents.

    Supports two modes:
    - FAST (use_ocr=False, default): Visual-only matching.
    - THOROUGH (use_ocr=True): Visual + OCR text verification.
    
    Region strategies control fingerprint granularity:
    - 4-strip: 4 horizontal strips + global (fastest)
    - 9-grid: 3×3 grid + global (balanced)
    - 16-grid: 4×4 grid + global (most accurate)
    """
    t_start = time.time()
    
    embedder = get_embedder()
    index = get_vector_index()

    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty image file.")

    # Validate strategy
    valid_strategies = ("4-strip", "9-grid", "16-grid")
    if region_strategy not in valid_strategies:
        region_strategy = "4-strip"

    search_mode = "THOROUGH (Visual+OCR)" if use_ocr else "FAST (Visual-Only)"
    logger.info("=" * 70)
    logger.info("🔍 SEARCH [%s | %s] — top_k=%d | vis=%.2f | txt=%.2f | vo=%.2f",
                search_mode, region_strategy, top_k, visual_threshold, text_threshold, visual_only_threshold)
    logger.info("   Image size: %d bytes | FAISS vectors: %d", len(image_bytes), index.total_vectors)
    logger.info("=" * 70)

    # === PHASE 1: VISUAL EMBEDDING (using configurable region strategy) ===
    from arch_fingerprint.ai.region_strategy import crop_regions
    from arch_fingerprint.ai.robustness import correct_perspective, topk_weighted_score
    
    try:
        t_preprocess = time.time()
        processed_image = await asyncio.to_thread(preprocess_from_bytes, image_bytes)
        logger.info("⏱ Preprocessing: %.1fs | Result: %s", time.time() - t_preprocess, processed_image.size)
        
        # Perspective correction — fix camera angle distortion
        t_persp = time.time()
        processed_image = await asyncio.to_thread(correct_perspective, processed_image)
        logger.info("⏱ Perspective correction: %.1fs | Final: %s", time.time() - t_persp, processed_image.size)
        
        t_embed = time.time()
        regions = crop_regions(processed_image, region_strategy)
        
        query_embeddings = []
        region_names = []
        weights = []
        
        for name, crop_img, weight in regions:
            emb = await asyncio.to_thread(embedder.extract_embedding, crop_img)
            query_embeddings.append(emb)
            region_names.append(name)
            weights.append(weight)
        
        logger.info("⏱ Embedding extraction (%d regions, strategy=%s): %.1fs",
                     len(regions), region_strategy, time.time() - t_embed)
        
    except Exception as exc:
        logger.error("❌ Preprocessing/embedding failed: %s", exc)
        raise HTTPException(status_code=400, detail=f"Image processing failed: {exc}")

    # === PHASE 1b: FAISS SEARCH ===
    all_scores = []
    for i, emb in enumerate(query_embeddings):
        results = await asyncio.to_thread(index.search, emb, top_k * 3)
        region_scores = {res.doc_id: res.similarity_score for res in results}
        all_scores.append(region_scores)
        
        # Log top hits per region
        top3 = sorted(region_scores.items(), key=lambda x: x[1], reverse=True)[:3]
        top3_str = ", ".join([f"doc{did}={s:.3f}" for did, s in top3])
        logger.info("   Region [%s] w=%.2f top3: %s", region_names[i], weights[i], top3_str if top3 else "NO RESULTS")

    # Robust Top-K-of-N weighted aggregation
    # Ignores worst 30% of regions to handle occlusion (fingers, folds)
    candidates = {} 
    all_seen_ids = set().union(*[s.keys() for s in all_scores])
    
    keep_ratio = 0.7  # Keep best 70% of regions
    
    for doc_id in all_seen_ids:
        region_scores_list = []
        for i, score_map in enumerate(all_scores):
            s = score_map.get(doc_id, 0.0)
            region_scores_list.append(s)
        
        # Top-K scoring: ignore worst regions
        robust_score = topk_weighted_score(region_scores_list, weights, keep_ratio=keep_ratio)
        candidates[doc_id] = robust_score

    if not candidates:
        logger.warning("❌ No candidates found in FAISS index.")
        return SearchResponse(results=[], total_results=0)
    
    # Log Top-K details for best candidates
    n_regions = len(weights)
    k_used = max(2, int(n_regions * keep_ratio))
    logger.info("🛡️ Top-K Scoring: using best %d of %d regions (keep_ratio=%.0f%%, handles occlusion)",
                k_used, n_regions, keep_ratio * 100)

    # Sort and take top_k
    sorted_candidates = sorted(candidates.items(), key=lambda x: x[1], reverse=True)[:top_k]
    
    logger.info("─" * 50)
    logger.info("📊 WEIGHTED CANDIDATES (top %d):", len(sorted_candidates))
    for doc_id, score in sorted_candidates:
        details = []
        for i, score_map in enumerate(all_scores):
            s = score_map.get(doc_id, 0.0)
            details.append(f"{region_names[i]}={s:.3f}×{weights[i]}")
        logger.info("   doc_id=%d → weighted=%.4f [%s]", doc_id, score, " | ".join(details))
    logger.info("─" * 50)

    # Fetch metadata
    doc_ids = [doc_id for doc_id, score in sorted_candidates]
    score_map = dict(sorted_candidates)

    stmt = select(Document).where(Document.id.in_(doc_ids))
    result = await db.execute(stmt)
    docs = {doc.id: doc for doc in result.scalars().all()}

    matches = []
    for doc_id in doc_ids:
        doc = docs.get(doc_id)
        if doc is None:
            logger.warning("⚠️ FAISS returned doc_id=%d but NOT in DB (deleted?). Skipping.", doc_id)
            continue
        if doc.status == "deleted":
            logger.warning("⚠️ doc_id=%d status=deleted. Skipping.", doc_id)
            continue

        matches.append(SearchMatch(
            id=doc.id,
            fingerprint=doc.fingerprint,
            khazanah=doc.khazanah,
            page_number=doc.page_number,
            description=doc.description,
            similarity_score=round(score_map[doc_id], 4),
            image_url=f"/uploads/{doc.image_path.split('/')[-1]}",
        ))

    # Filter by visual similarity threshold (configurable from client!)
    visual_matches = [m for m in matches if m.similarity_score >= visual_threshold]
    rejected_visual = [m for m in matches if m.similarity_score < visual_threshold]
    
    logger.info("🎯 VISUAL FILTER (threshold=%.2f): %d passed, %d rejected",
                visual_threshold, len(visual_matches), len(rejected_visual))
    for m in rejected_visual:
        logger.info("   ❌ doc_id=%d rejected (score=%.4f < %.2f)", m.id, m.similarity_score, visual_threshold)
    
    # === PHASE 2: OCR TEXT VERIFICATION (only in THOROUGH mode) ===
    final_matches = []
    
    if not use_ocr:
        # FAST MODE: Skip OCR entirely, return all visual matches
        logger.info("⚡ FAST MODE: Skipping OCR verification. Returning %d visual matches directly.", len(visual_matches))
        for m in visual_matches:
            m.description = f"[Fast Mode] score={m.similarity_score:.3f}"
        final_matches = visual_matches
    elif visual_matches:
        import tempfile
        import os
        from arch_fingerprint.ai.ocr import run_ocr
        from difflib import SequenceMatcher

        # Save processed query image to temp file for OCR
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            processed_image.save(tmp.name)
            tmp_path = tmp.name
        
        try:
            t_ocr = time.time()
            logger.info("🔤 THOROUGH MODE: Running OCR on query image...")
            query_text = await asyncio.to_thread(run_ocr, tmp_path)
            logger.info("⏱ Query OCR: %.1fs", time.time() - t_ocr)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

        if query_text and len(query_text) > 10:
            logger.info("✅ Query OCR success: %d chars → \"%s...\"", len(query_text), query_text[:50])
            
            # Semantic DNA Verification
            try:
                text_embedder = get_text_embedder()
                query_text_emb = await asyncio.to_thread(text_embedder.encode, query_text)
            except Exception as sem_err:
                logger.error("❌ Semantic encoding of query failed: %s", sem_err)
                query_text_emb = None

            logger.info("─" * 50)
            logger.info("🧬 HYBRID DNA VERIFICATION (text_threshold=%.2f):", text_threshold)
            
            for match in visual_matches:
                doc = docs.get(match.id)
                
                # Handwriting Bypass
                if doc and doc.is_paleography:
                    logger.info("   doc_id=%d → ✅ HANDWRITING bypass (no OCR check)", match.id)
                    match.description = f"[Handwriting] {match.description or ''}"
                    final_matches.append(match)
                    continue

                candidate_text = doc.text_content if doc else None
                
                if not candidate_text or len(candidate_text) < 10:
                    logger.info("   doc_id=%d → ✅ No text in DB → Visual-Only pass (score=%.3f)", match.id, match.similarity_score)
                    match.description = f"[Visual Match Only] {match.description or ''}"
                    final_matches.append(match)
                    continue
                
                # String Similarity
                string_ratio = SequenceMatcher(None, query_text, candidate_text).ratio()
                
                # Semantic Similarity
                semantic_ratio = 0.0
                if query_text_emb is not None:
                    try:
                        text_index = get_text_vector_index()
                        cand_text_emb = await asyncio.to_thread(text_index.get_vector_by_doc_id, match.id)
                        
                        if cand_text_emb is None:
                            logger.info("   doc_id=%d not in Text Index, encoding on-the-fly...", match.id)
                            cand_text_emb = await asyncio.to_thread(text_embedder.encode, candidate_text)
                        
                        semantic_ratio = float(np.dot(query_text_emb, cand_text_emb))
                    except Exception as e:
                        logger.warning("   doc_id=%d semantic comparison failed: %s", match.id, e)

                combined_text_ratio = (string_ratio * 0.4) + (semantic_ratio * 0.6)
                
                logger.info("   doc_id=%d → visual=%.3f | string=%.1f%% | semantic=%.1f%% | combined=%.1f%%",
                            match.id, match.similarity_score, 
                            string_ratio * 100, semantic_ratio * 100, combined_text_ratio * 100)
                
                # HYBRID RULES (using configurable text_threshold)
                is_match = False
                reason = ""
                
                # Rule 1: Good visual + good text (configurable thresholds)
                if combined_text_ratio >= text_threshold and match.similarity_score > visual_threshold:
                    is_match = True
                    reason = f"[DNA Verified] text={combined_text_ratio:.0%}"
                # Rule 2: Excellent visual (>0.85) + minimal text support (>5%)
                elif match.similarity_score >= 0.85:
                    if combined_text_ratio >= 0.05:
                        is_match = True
                        reason = f"[High Visual] text={combined_text_ratio:.0%}"
                    else:
                        reason = f"TEXT MISMATCH ({combined_text_ratio:.1%})"
                else:
                    reason = f"Below thresholds (vis={match.similarity_score:.3f}<0.85, text={combined_text_ratio:.1%}<{text_threshold:.0%})"
                
                if is_match:
                    if combined_text_ratio > 0.7:
                        old_score = match.similarity_score
                        match.similarity_score = min(0.99, (match.similarity_score + combined_text_ratio) / 2)
                        logger.info("      → ✅ MATCH (boosted %.3f → %.3f) %s", old_score, match.similarity_score, reason)
                    else:
                        logger.info("      → ✅ MATCH %s", reason)
                    match.description = reason
                    final_matches.append(match)
                else:
                    logger.warning("      → ❌ REJECTED: %s", reason)
            
            logger.info("─" * 50)
        else:
            # Query OCR failed — fallback to visual-only with configurable threshold
            logger.warning("⚠️ Query OCR failed/empty. Fallback: Visual-Only (threshold=%.2f)", visual_only_threshold)
            for match in visual_matches:
                if match.similarity_score >= visual_only_threshold:
                    match.description = f"[Visual Only] score={match.similarity_score:.3f}"
                    final_matches.append(match)
                    logger.info("   doc_id=%d → ✅ Visual-Only pass (%.3f >= %.2f)", match.id, match.similarity_score, visual_only_threshold)
                else:
                    logger.info("   doc_id=%d → ❌ Visual-Only reject (%.3f < %.2f)", match.id, match.similarity_score, visual_only_threshold)
    else:
        logger.warning("❌ No visual matches passed threshold. 0 results.")
        final_matches = []

    elapsed = time.time() - t_start
    logger.info("=" * 70)
    logger.info("✅ SEARCH COMPLETE: %d results in %.1fs", len(final_matches), elapsed)
    for m in final_matches:
        logger.info("   → doc_id=%d | score=%.4f | %s | %s", m.id, m.similarity_score, m.khazanah, m.description)
    logger.info("=" * 70)

    return SearchResponse(
        results=final_matches,
        total_results=len(final_matches),
    )
