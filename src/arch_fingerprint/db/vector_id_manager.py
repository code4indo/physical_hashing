"""Vector ID allocation manager for FAISS index.

For production-scale systems handling millions of documents, this module
provides efficient vector ID allocation strategies that prevent conflicts
and optimize FAISS index utilization.

Two strategies are supported:
1. SEQUENTIAL: Simple auto-increment (fast, but wastes IDs after deletions)
2. REUSE_GAPS: Reuses freed IDs from soft-deleted documents (space-efficient)
"""

import logging
from typing import Protocol

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from arch_fingerprint.db.models import Document

logger = logging.getLogger(__name__)


class VectorIDAllocator(Protocol):
    """Protocol for vector ID allocation strategies."""
    
    async def allocate_next_id(self, session: AsyncSession) -> int:
        """Allocate the next available vector ID."""
        ...


class SequentialAllocator:
    """Simple sequential allocator - always uses max(vector_id) + 1.
    
    Pros:
    - Fast O(1) allocation
    - Simple to implement
    - No fragmentation tracking needed
    
    Cons:
    - IDs keep growing even after deletions
    - FAISS index can have "holes" (wasted space)
    - Not ideal for high-churn workloads
    
    Best for: Write-heavy, low-deletion workloads
    """
    
    async def allocate_next_id(self, session: AsyncSession) -> int:
        """Get next ID by incrementing max vector_id."""
        result = await session.execute(
            select(func.max(Document.vector_id))
            .where(Document.vector_id.isnot(None))
        )
        max_id = result.scalar()
        next_id = 0 if max_id is None else max_id + 1
        logger.debug("Allocated vector_id=%d (sequential)", next_id)
        return next_id


class GapReuseAllocator:
    """Reuses IDs from soft-deleted documents before allocating new ones.
    
    Pros:
    - Space-efficient - reuses freed slots
    - Keeps FAISS index compact
    - Better for million+ document systems
    
    Cons:
    - Requires soft-delete tracking
    - Slightly slower allocation (needs gap search)
    - More complex implementation
    
    Best for: Production systems with frequent updates/replacements
    """
    
    async def allocate_next_id(self, session: AsyncSession) -> int:
        """Reuse a freed vector_id from deleted docs, or allocate new."""
        # Try to find a deleted document with a vector_id we can reuse
        result = await session.execute(
            select(Document.vector_id)
            .where(Document.status == "deleted")
            .where(Document.vector_id.isnot(None))
            .limit(1)
        )
        reusable_id = result.scalar()
        
        if reusable_id is not None:
            logger.debug("Reusing vector_id=%d from deleted document", reusable_id)
            return reusable_id
        
        # No gaps to reuse - allocate next sequential ID
        result = await session.execute(
            select(func.max(Document.vector_id))
            .where(Document.vector_id.isnot(None))
        )
        max_id = result.scalar()
        next_id = 0 if max_id is None else max_id + 1
        logger.debug("Allocated new vector_id=%d (no gaps available)", next_id)
        return next_id


# Factory function for production use
def get_vector_id_allocator(strategy: str = "sequential") -> VectorIDAllocator:
    """Get a vector ID allocator based on the specified strategy.
    
    Args:
        strategy: Either "sequential" or "reuse_gaps"
        
    Returns:
        Configured allocator instance
        
    Raises:
        ValueError: If strategy is not recognized
    """
    if strategy == "sequential":
        return SequentialAllocator()
    elif strategy == "reuse_gaps":
        return GapReuseAllocator()
    else:
        raise ValueError(f"Unknown vector ID allocation strategy: {strategy}")
