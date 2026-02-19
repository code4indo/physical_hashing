"""Cryptographic hashing utilities for document fingerprinting.

Provides functions for generating content-based hashes for deduplication
and integrity verification of archival documents.
"""

import hashlib
from pathlib import Path
from typing import BinaryIO


def compute_file_hash(file_path: str | Path, algorithm: str = "sha256") -> str:
    """Compute cryptographic hash of a file.
    
    Args:
        file_path: Path to the file to hash
        algorithm: Hash algorithm (sha256, sha512, md5)
        
    Returns:
        Hexadecimal hash string
        
    Example:
        >>> hash_str = compute_file_hash("document.png")
        >>> print(hash_str)
        'a3f2b8c9d1e2f3a4b5c6d7e8f9a0b1c2...'
    """
    hasher = hashlib.new(algorithm)
    
    with open(file_path, "rb") as f:
        # Read in 8KB chunks to handle large files efficiently
        while chunk := f.read(8192):
            hasher.update(chunk)
    
    return hasher.hexdigest()


def compute_bytes_hash(data: bytes, algorithm: str = "sha256") -> str:
    """Compute cryptographic hash of byte data.
    
    Args:
        data: Bytes to hash
        algorithm: Hash algorithm (sha256, sha512, md5)
        
    Returns:
        Hexadecimal hash string
    """
    hasher = hashlib.new(algorithm)
    hasher.update(data)
    return hasher.hexdigest()


def compute_image_perceptual_hash(image_path: str | Path) -> str:
    """Compute perceptual hash (pHash) for near-duplicate image detection.
    
    Unlike cryptographic hashes, perceptual hashes are similar for
    visually similar images (e.g., different resolutions, slight edits).
    
    Args:
        image_path: Path to image file
        
    Returns:
        Hexadecimal perceptual hash string (64-bit)
        
    Note:
        Requires imagehash library: pip install imagehash pillow
    """
    try:
        import imagehash
        from PIL import Image
        
        img = Image.open(image_path)
        phash = imagehash.phash(img, hash_size=8)
        return str(phash)
    except ImportError:
        raise ImportError(
            "imagehash library required for perceptual hashing. "
            "Install with: pip install imagehash pillow"
        )


def is_duplicate_by_hash(hash1: str, hash2: str, threshold: int = 5) -> bool:
    """Check if two perceptual hashes represent duplicate/similar images.
    
    Args:
        hash1: First perceptual hash (from compute_image_perceptual_hash)
        hash2: Second perceptual hash
        threshold: Maximum Hamming distance to consider as duplicate (0-64)
                   Lower = more strict. 0 = exact match, 5 = very similar
        
    Returns:
        True if images are considered duplicates
    """
    try:
        import imagehash
        
        h1 = imagehash.hex_to_hash(hash1)
        h2 = imagehash.hex_to_hash(hash2)
        
        hamming_distance = h1 - h2
        return hamming_distance <= threshold
    except ImportError:
        raise ImportError(
            "imagehash library required. Install with: pip install imagehash"
        )


# Example usage for deduplication:
"""
# When registering a new document:
content_hash = compute_file_hash("new_document.png")

# Check if already exists in database:
existing = session.query(Document).filter_by(content_hash=content_hash).first()
if existing:
    raise DuplicateDocumentError(f"Document already exists: {existing.fingerprint}")

# For near-duplicate detection (perceptual):
perceptual_hash = compute_image_perceptual_hash("new_document.png")
# Compare with existing hashes in database...
"""
