import pytest
from backend.app.llm.mock_provider import MockLLMProvider
from backend.app.schemas.form import ConfidenceResult

@pytest.mark.asyncio
async def test_mock_llm_provider_unstructured():
    provider = MockLLMProvider(default_response="Generated answer")
    res = await provider.generate(prompt="Explain experience in Java")
    assert res == "Generated answer"
    assert len(provider.calls) == 1

@pytest.mark.asyncio
async def test_mock_llm_provider_structured():
    provider = MockLLMProvider()
    res = await provider.generate_structured(
        prompt="Map email field",
        response_schema=ConfidenceResult
    )
    assert isinstance(res, ConfidenceResult)
    assert res.field_id == "field_001"
    assert res.confidence == 0.95
