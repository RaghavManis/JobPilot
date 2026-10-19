import os
import json
import math
from typing import List, Optional, Dict, Any
from backend.app.rag.vector_store.interface import VectorStore
from backend.app.schemas.rag import DocumentChunk, SearchResult
from backend.app.core.logging import logger
from backend.app.core.exceptions import JobPilotException


def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """Calculate cosine similarity score between two float vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0

    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    score = dot_product / (norm_a * norm_b)
    # Clamp score to [0.0, 1.0] range
    return max(0.0, min(1.0, (score + 1.0) / 2.0 if score < 0 else score))


class FAISSVectorStore(VectorStore):
    """FAISS-compatible vector database engine supporting vector indexing and similarity retrieval."""

    def __init__(self, persist_dir: Optional[str] = None):
        self.persist_dir = persist_dir
        self._chunks: Dict[str, DocumentChunk] = {}
        self._vectors: Dict[str, List[float]] = {}

        if self.persist_dir and os.path.exists(self.persist_dir):
            self.load_from_disk(self.persist_dir)

    async def add_documents(
        self,
        chunks: List[DocumentChunk],
        embeddings: List[List[float]]
    ) -> List[str]:
        if len(chunks) != len(embeddings):
            raise JobPilotException("Number of document chunks does not match number of embeddings.")

        added_ids = []
        for chunk, emb in zip(chunks, embeddings):
            self._chunks[chunk.chunk_id] = chunk
            self._vectors[chunk.chunk_id] = emb
            added_ids.append(chunk.chunk_id)

        logger.info(f"Added {len(added_ids)} document chunks to FAISS vector store.")

        if self.persist_dir:
            self.save_to_disk(self.persist_dir)

        return added_ids

    async def similarity_search(
        self,
        query_embedding: List[float],
        top_k: int = 4,
        filter_metadata: Optional[Dict[str, Any]] = None
    ) -> List[SearchResult]:
        if not self._vectors:
            return []

        scored_results = []
        for chunk_id, vec in self._vectors.items():
            chunk = self._chunks[chunk_id]

            # Apply metadata filter if provided
            if filter_metadata:
                match = True
                meta_dict = chunk.metadata.model_dump()
                for fk, fv in filter_metadata.items():
                    if meta_dict.get(fk) != fv:
                        match = False
                        break
                if not match:
                    continue

            score = _cosine_similarity(query_embedding, vec)
            scored_results.append((score, chunk))

        # Sort by score descending
        scored_results.sort(key=lambda x: x[0], reverse=True)
        top_items = scored_results[:top_k]

        results = []
        for score, chunk in top_items:
            results.append(SearchResult(
                chunk_id=chunk.chunk_id,
                text=chunk.text,
                document_name=chunk.metadata.document_name,
                source_path=chunk.metadata.source_path,
                score=round(score, 4),
                metadata=chunk.metadata.model_dump()
            ))

        logger.info(f"FAISS vector search returned {len(results)} matches for query (top_k={top_k}).")
        return results

    async def delete(self, chunk_id: str) -> bool:
        if chunk_id in self._chunks:
            del self._chunks[chunk_id]
            del self._vectors[chunk_id]
            logger.info(f"Deleted chunk '{chunk_id}' from vector store.")
            if self.persist_dir:
                self.save_to_disk(self.persist_dir)
            return True
        return False

    async def rebuild(self):
        self._chunks.clear()
        self._vectors.clear()
        logger.info("Cleared FAISS vector store completely.")
        if self.persist_dir and os.path.exists(self.persist_dir):
            import shutil
            shutil.rmtree(self.persist_dir, ignore_errors=True)

    def save_to_disk(self, folder_path: str):
        """Persist vector index and document metadata to disk."""
        os.makedirs(folder_path, exist_ok=True)
        index_file = os.path.join(folder_path, "faiss_index.json")
        data = {
            "chunks": {cid: chunk.model_dump() for cid, chunk in self._chunks.items()},
            "vectors": self._vectors
        }
        with open(index_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Saved FAISS index to: {index_file}")

    def load_from_disk(self, folder_path: str):
        """Load vector index and metadata from disk."""
        index_file = os.path.join(folder_path, "faiss_index.json")
        if not os.path.exists(index_file):
            return

        try:
            with open(index_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._chunks = {cid: DocumentChunk(**cdict) for cid, cdict in data.get("chunks", {}).items()}
            self._vectors = data.get("vectors", {})
            logger.info(f"Loaded {len(self._chunks)} chunks from FAISS index disk store: {folder_path}")
        except Exception as e:
            logger.error(f"Failed to load FAISS index from disk: {e}")
