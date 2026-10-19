from typing import List, Optional
from backend.app.rag.embeddings.provider import EmbeddingProvider
from backend.app.config.settings import settings
from backend.app.core.logging import logger
from backend.app.core.exceptions import JobPilotException

try:
    from google import genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False


class GeminiEmbeddingProvider(EmbeddingProvider):
    """Google Gemini implementation of EmbeddingProvider interface."""

    def __init__(self, api_key: Optional[str] = None, model_name: str = "text-embedding-004"):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model_name = model_name
        self.client = None

        if GENAI_AVAILABLE and self.api_key and self.api_key != "mock_gemini_api_key":
            try:
                self.client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.error(f"Failed to initialize Gemini embedding client: {e}")

    async def embed_query(self, text: str) -> List[float]:
        if not self.client:
            raise JobPilotException("Gemini embedding client is not configured.")
        try:
            res = self.client.models.embed_content(
                model=self.model_name,
                contents=text
            )
            return res.embedding.values
        except Exception as e:
            logger.error(f"Gemini query embedding failed: {e}")
            raise JobPilotException(f"Gemini embedding error: {e}") from e

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        if not self.client:
            raise JobPilotException("Gemini embedding client is not configured.")
        try:
            embeddings = []
            for text in texts:
                res = self.client.models.embed_content(
                    model=self.model_name,
                    contents=text
                )
                embeddings.append(res.embedding.values)
            return embeddings
        except Exception as e:
            logger.error(f"Gemini document batch embedding failed: {e}")
            raise JobPilotException(f"Gemini batch embedding error: {e}") from e
