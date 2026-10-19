from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database.session import get_db
from backend.app.schemas.rag import SearchResult, Evidence, EvaluationResult
from backend.app.services.knowledge_service import KnowledgeService
from backend.app.api.routes.profile import get_knowledge_service
from backend.app.core.exceptions import JobPilotException

router = APIRouter(prefix="/api/knowledge", tags=["Knowledge Base & RAG"])


class IngestRequest(BaseModel):
    path: Optional[str] = "./knowledge_base"


@router.post("/ingest")
async def ingest_documents(
    request: IngestRequest,
    service: KnowledgeService = Depends(get_knowledge_service)
):
    """Ingest a single document file or an entire knowledge base directory."""
    try:
        path = request.path or "./knowledge_base"
        if os.path.isfile(path):
            chunks = await service.ingest_file(path)
            return {"status": "success", "file": path, "chunks_ingested": len(chunks)}
        else:
            result = await service.ingest_directory(path)
            return {"status": "success", "directory": path, **result}
    except JobPilotException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)


import os

@router.get("/search", response_model=List[SearchResult])
async def search_knowledge(
    query: str = Query(..., description="Semantic question query"),
    top_k: int = Query(4, ge=1, le=10),
    service: KnowledgeService = Depends(get_knowledge_service)
):
    """Search knowledge base using vector similarity search."""
    try:
        return await service.search(query=query, top_k=top_k)
    except JobPilotException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)


@router.get("/evaluate", response_model=EvaluationResult)
async def evaluate_evidence(
    query: str = Query(..., description="Question query to evaluate for hallucination prevention"),
    top_k: int = Query(3, ge=1, le=5),
    service: KnowledgeService = Depends(get_knowledge_service)
):
    """Retrieve evidence for a query and perform zero-hallucination evaluation."""
    try:
        return await service.evaluate_evidence(query=query, top_k=top_k)
    except JobPilotException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)
