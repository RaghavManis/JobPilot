from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class DocumentMetadata(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_name: str = Field(..., description="Filename e.g. resume_backend.md")
    document_type: str = Field(..., description="Category e.g. resume, project, experience, answer")
    chunk_id: str = Field(..., description="Unique chunk identifier e.g. resume_backend_001")
    source_path: str = Field(..., description="Absolute or relative file path")
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class DocumentChunk(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chunk_id: str
    text: str
    metadata: DocumentMetadata


class SearchResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chunk_id: str
    text: str
    document_name: str
    source_path: str
    score: float = Field(..., description="Similarity score normalized from 0.0 to 1.0")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Evidence(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    text: str = Field(..., description="Extracted chunk text supporting the query")
    document_name: str = Field(..., description="Source document name e.g. resume_backend.md")
    chunk_id: str = Field(..., description="Unique ID of supporting chunk")
    retrieval_score: float = Field(..., description="Vector search similarity score")
    evidence_type: str = Field(..., description="Document type e.g. resume, experience, answer")
    source_path: str = Field(..., description="File path")


class EvaluationResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    decision: str = Field(..., description="SUFFICIENT_EVIDENCE | WEAK_EVIDENCE | INSUFFICIENT_EVIDENCE")
    reason: str = Field(..., description="Explanation of evaluation rationale")
    confidence_score: float = Field(..., description="Confidence score from 0.0 to 1.0")
    best_evidence: Optional[Evidence] = Field(None, description="Primary supporting evidence chunk if available")
