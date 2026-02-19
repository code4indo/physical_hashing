"""SQLAlchemy ORM models for archival document metadata."""

from datetime import datetime
import uuid

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all models."""
    pass


class Document(Base):
    """Represents a registered archival document with its metadata.

    Each document has:
    - id: Database auto-increment primary key
    - fingerprint: UUID-based unique document identifier (public-facing)
    - vector_id: FAISS index position (internal, for vector search)
    - content_hash: SHA256 of image content (deduplication)
    
    The khazanah field identifies the archive collection.
    """

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Public-facing unique identifier (UUID v4)
    fingerprint: Mapped[str] = mapped_column(
        String(36), 
        unique=True, 
        nullable=False, 
        default=lambda: str(uuid.uuid4()),
        index=True
    )
    
    # Content-based hash for deduplication (SHA256 of image bytes)
    content_hash: Mapped[str | None] = mapped_column(
        String(64), 
        unique=True, 
        nullable=True,
        index=True,
        comment="SHA256 hash of processed image for duplicate detection"
    )
    
    khazanah: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_path: Mapped[str] = mapped_column(String(512), nullable=False)
    
    # FAISS vector index position (internal use only)
    vector_id: Mapped[int | None] = mapped_column(
        Integer, 
        unique=True, 
        nullable=True,
        comment="FAISS index position - NOT a document fingerprint"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True, comment="OCR extracted text content")
    # Processing status: pending | processing | completed | failed | deleted
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Flag for paleography documents (historical handwriting - not suitable for GLM-OCR)
    is_paleography: Mapped[bool | None] = mapped_column(
        Integer,  # SQLite doesn't have native BOOLEAN, uses INTEGER
        default=0,
        nullable=True,
        comment="Flag for paleography documents (historical handwriting - GLM-OCR doesn't support HTR)"
    )

    def __repr__(self) -> str:
        return (
            f"<Document(id={self.id}, fingerprint='{self.fingerprint[:8]}...', "
            f"khazanah='{self.khazanah}', page={self.page_number}, vector_id={self.vector_id})>"
        )
