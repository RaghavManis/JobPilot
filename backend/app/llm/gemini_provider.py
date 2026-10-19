import json
from typing import Type, TypeVar, Optional
from pydantic import BaseModel
from backend.app.llm.provider import LLMProvider, T
from backend.app.config.settings import settings
from backend.app.core.logging import logger
from backend.app.core.exceptions import LLMProviderException

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False


class GeminiLLMProvider(LLMProvider):
    """Google Gemini implementation of LLMProvider interface."""

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model_name = model_name or settings.GEMINI_MODEL

        if not self.api_key or self.api_key == "mock_gemini_api_key":
            logger.warning("Gemini API key is missing or set to mock value. Calls will fail unless mocked.")

        self.client = None
        if GENAI_AVAILABLE and self.api_key and self.api_key != "mock_gemini_api_key":
            try:
                self.client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.error(f"Failed to initialize Gemini client: {e}")

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.2
    ) -> str:
        if not self.client:
            raise LLMProviderException("Gemini client is not configured or API key is missing.")

        try:
            config = types.GenerateContentConfig(
                temperature=temperature,
                system_instruction=system_prompt if system_prompt else None
            )
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=config
            )
            return response.text
        except Exception as e:
            logger.error(f"Gemini generation error: {e}")
            raise LLMProviderException(f"Gemini generation failed: {e}") from e

    async def generate_structured(
        self,
        prompt: str,
        response_schema: Type[T],
        system_prompt: Optional[str] = None,
        temperature: float = 0.1
    ) -> T:
        if not self.client:
            raise LLMProviderException("Gemini client is not configured or API key is missing.")

        try:
            config = types.GenerateContentConfig(
                temperature=temperature,
                system_instruction=system_prompt if system_prompt else None,
                response_mime_type="application/json",
                response_schema=response_schema
            )
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=config
            )

            # Parse returned JSON into target Pydantic schema
            raw_text = response.text
            parsed_data = json.loads(raw_text)
            return response_schema.model_validate(parsed_data)
        except Exception as e:
            logger.error(f"Gemini structured generation error: {e}")
            raise LLMProviderException(f"Gemini structured generation failed: {e}") from e
