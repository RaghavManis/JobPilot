from typing import List, Optional, Dict, Any
from backend.app.rag.embeddings.provider import EmbeddingProvider
from backend.app.rag.vector_store.interface import VectorStore
from backend.app.schemas.rag import SearchResult, Evidence
from backend.app.core.logging import logger


class Retriever:
    """Retrieves relevant document chunks and evidence for user queries."""

    def __init__(self, embedding_provider: EmbeddingProvider, vector_store: VectorStore):
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store

    async def search(
        self,
        query: str,
        top_k: int = 4,
        filter_metadata: Optional[Dict[str, Any]] = None
    ) -> List[SearchResult]:
        """Generate embedding for query string and perform similarity search."""
        logger.info(f"Performing vector similarity retrieval for query: '{query}'")
        query_embedding = await self.embedding_provider.embed_query(query)
        results = await self.vector_store.similarity_search(
            query_embedding=query_embedding,
            top_k=top_k,
            filter_metadata=filter_metadata
        )
        return results

    async def retrieve_evidence(
        self,
        query: str,
        top_k: int = 3,
        filter_metadata: Optional[Dict[str, Any]] = None
    ) -> List[Evidence]:
        """Retrieve top SearchResults converted into typed Evidence objects."""
        search_results = await self.search(query, top_k=top_k, filter_metadata=filter_metadata)

        evidence_list: List[Evidence] = []
        for r in search_results:
            doc_type = r.metadata.get("document_type", "general")
            evidence_list.append(Evidence(
                text=r.text,
                document_name=r.document_name,
                chunk_id=r.chunk_id,
                retrieval_score=r.score,
                evidence_type=doc_type,
                source_path=r.source_path
            ))

        return evidence_list
