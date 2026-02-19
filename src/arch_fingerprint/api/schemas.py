"""Pydantic schemas for API request/response validation."""

from datetime import datetime

from pathlib import Path
from pydantic import BaseModel, Field, computed_field


# --- Register ---

class RegisterRequest(BaseModel):
    """Metadata fields sent alongside the uploaded document image."""
    khazanah: str = Field(..., description="Archive collection name")
    page_number: int | None = Field(None, description="Page number within the collection")
    description: str | None = Field(None, description="Free-text description of the document")


class RegisterResponse(BaseModel):
    """Response after successfully registering a document."""
    id: int
    fingerprint: str = Field(..., description="Unique UUID fingerprint for this document")
    khazanah: str
    page_number: int | None
    vector_id: int
    message: str = "Document registered successfully"


# --- Search ---

class SearchMatch(BaseModel):
    """A single matching document from a search query."""
    id: int
    fingerprint: str = Field(..., description="Unique UUID fingerprint")
    khazanah: str
    page_number: int | None
    description: str | None
    similarity_score: float
    image_url: str


class SearchResponse(BaseModel):
    """Response containing search results."""
    query_processed: bool = True
    results: list[SearchMatch]
    total_results: int


# --- Document CRUD ---

class DocumentDetail(BaseModel):
    """Full details of a registered document."""
    id: int
    fingerprint: str = Field(..., description="Unique UUID fingerprint")
    khazanah: str
    page_number: int | None
    description: str | None
    image_path: str
    vector_id: int | None
    status: str
    error_message: str | None = None
    created_at: datetime
    content_hash: str | None = Field(None, description="SHA256 hash for deduplication")
    text_content: str | None = Field(None, description="OCR extracted text content")

    @computed_field
    def image_url(self) -> str:
        # Convert absolute path to relative /uploads URL
        return f"/uploads/{Path(self.image_path).name}"

    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    """Paginated list of documents."""
    documents: list[DocumentDetail]
    total: int
    page: int
    per_page: int


class DeleteResponse(BaseModel):
    """Response after deleting a document."""
    id: int
    message: str = "Document deleted successfully"
