import math
import hashlib
from typing import List
from backend.app.rag.embeddings.provider import EmbeddingProvider


class MockEmbeddingProvider(EmbeddingProvider):
    """Deterministic Mock Embedding Provider for fast unit tests without network calls."""

    def __init__(self, dimension: int = 64):
        self.dimension = dimension

    def _text_to_vector(self, text: str) -> List[float]:
        """Generate deterministic normalized hash vector from text tokens."""
        tokens = [t.strip().lower() for t in text.split() if t.strip()]
        vector = [0.0] * self.dimension

        if not tokens:
            return vector

        for token in tokens:
            # Deterministic hash index per token
            hash_val = int(hashlib.md5(token.encode('utf-8')).hexdigest(), 16)
            idx = hash_val % self.dimension
            sign = 1.0 if (hash_val % 2 == 0) else -1.0
            vector[idx] += sign * (1.0 + len(token) * 0.1)

        # L2 Normalize vector
        magnitude = math.sqrt(sum(v * v for v in vector))
        if magnitude > 0:
            vector = [v / magnitude for v in vector]

        return vector

    async def embed_query(self, text: str) -> List[float]:
        return self._text_to_vector(text)

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self._text_to_vector(text) for text in texts]
