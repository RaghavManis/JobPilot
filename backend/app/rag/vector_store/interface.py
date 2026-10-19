from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from backend.app.schemas.rag import DocumentChunk, SearchResult


class VectorStore(ABC):
    """Abstract interface for Vector Store backends (FAISS, Chroma, Qdrant, etc.)."""

    @abstractmethod
    async def add_documents(
        self,
        chunks: List[DocumentChunk],
        embeddings: List[List[float]]
    ) -> List[str]:
        """Insert document chunks and their embedding vectors into store."""
        pass

    @abstractmethod
    async def similarity_search(
        self,
        query_embedding: List[float],
        top_k: int = 4,
        filter_metadata: Optional[Dict[str, Any]] = None
    ) -> List[SearchResult]:
        """Perform similarity search and return ranked SearchResult list."""
        pass

    @abstractmethod
    async def delete(self, chunk_id: str) -> bool:
        """Delete specific chunk by chunk_id."""
        pass

    @abstractmethod
    async def rebuild(self):
        """Clear store index completely."""
        pass
