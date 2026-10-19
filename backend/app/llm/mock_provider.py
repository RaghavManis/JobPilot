from typing import Type, Optional, Dict, Any
from pydantic import BaseModel
from backend.app.llm.provider import LLMProvider, T


class MockLLMProvider(LLMProvider):
    """Mock LLM Provider for unit testing and offline development."""

    def __init__(self, default_response: str = "Mock response", mock_structured_data: Optional[Dict[str, Any]] = None):
        self.default_response = default_response
        self.mock_structured_data = mock_structured_data or {}
        self.calls = []

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.2
    ) -> str:
        self.calls.append({"prompt": prompt, "system_prompt": system_prompt, "type": "unstructured"})
        return self.default_response

    async def generate_structured(
        self,
        prompt: str,
        response_schema: Type[T],
        system_prompt: Optional[str] = None,
        temperature: float = 0.1
    ) -> T:
        self.calls.append({"prompt": prompt, "system_prompt": system_prompt, "type": "structured"})

        if self.mock_structured_data:
            return response_schema.model_validate(self.mock_structured_data)

        # Generate dummy instance if no mock data provided
        dummy_fields = {}
        for field_name, field_info in response_schema.model_fields.items():
            if field_name == "confidence":
                dummy_fields[field_name] = 0.95
            elif field_name == "field_id":
                dummy_fields[field_name] = "field_001"
            elif field_name == "answer":
                dummy_fields[field_name] = "John Doe"
            elif field_name == "reason":
                dummy_fields[field_name] = "Matched from user profile"
            elif field_name == "source_citations":
                dummy_fields[field_name] = ["profile.personal.name"]
            elif field_name == "requires_human_input":
                dummy_fields[field_name] = False
            elif field_name == "is_required":
                dummy_fields[field_name] = False
            elif field_name == "options":
                dummy_fields[field_name] = []
            elif field_name == "option_elements":
                dummy_fields[field_name] = {}
            else:
                dummy_fields[field_name] = None

        return response_schema.model_validate(dummy_fields)
