import os
import pytest
from httpx import AsyncClient, ASGITransport
from backend.app.main import app
from backend.app.database.session import init_db, AsyncSessionLocal
from backend.app.rag.document_loader import DocumentLoader
from backend.app.rag.chunker import TextChunker
from backend.app.rag.embeddings.mock_provider import MockEmbeddingProvider
from backend.app.rag.vector_store.faiss_store import FAISSVectorStore
from backend.app.rag.evaluator import EvidenceEvaluator
from backend.app.services.knowledge_service import KnowledgeService
from backend.app.schemas.rag import Evidence

@pytest.mark.asyncio
async def test_document_loader_and_chunker():
    sample_path = os.path.join("knowledge_base", "resumes", "resume_backend.md")
    assert os.path.exists(sample_path)

    doc_data = DocumentLoader.load_file(sample_path)
    assert doc_data["document_name"] == "resume_backend.md"
    assert doc_data["document_type"] == "resume"
    assert len(doc_data["content"]) > 50

    chunker = TextChunker(chunk_size=300, chunk_overlap=50)
    chunks = chunker.chunk_document(doc_data)
    assert len(chunks) > 0
    assert chunks[0].metadata.document_name == "resume_backend.md"

@pytest.mark.asyncio
async def test_mock_embeddings_and_faiss_vector_store():
    embedder = MockEmbeddingProvider(dimension=32)
    store = FAISSVectorStore()

    texts = [
        "Senior Backend Engineer with 4 years of Python and FastAPI experience.",
        "Experienced in React and TypeScript web frontend applications."
    ]
    doc_data = {
        "content": "\n\n".join(texts),
        "document_name": "test_doc.md",
        "document_type": "experience",
        "source_path": "/path/test_doc.md"
    }
    chunker = TextChunker(chunk_size=100, chunk_overlap=10)
    chunks = chunker.chunk_document(doc_data)

    embeddings = await embedder.embed_documents([c.text for c in chunks])
    await store.add_documents(chunks, embeddings)

    query_emb = await embedder.embed_query("Python FastAPI experience")
    results = await store.similarity_search(query_emb, top_k=2)

    assert len(results) > 0
    assert results[0].score >= 0.0

@pytest.mark.asyncio
async def test_evidence_evaluator_sufficient_and_insufficient():
    evaluator = EvidenceEvaluator(sufficient_threshold=0.75, weak_threshold=0.50)

    # Empty evidence -> INSUFFICIENT_EVIDENCE
    result_empty = evaluator.evaluate("Kubernetes experience", [])
    assert result_empty.decision == "INSUFFICIENT_EVIDENCE"
    assert "No relevant information found" in result_empty.reason
    assert result_empty.confidence_score == 0.0

    # High score evidence -> SUFFICIENT_EVIDENCE
    high_evidence = [
        Evidence(
            text="4 years of Python experience",
            document_name="resume.md",
            chunk_id="c_001",
            retrieval_score=0.92,
            evidence_type="resume",
            source_path="/resume.md"
        )
    ]
    result_high = evaluator.evaluate("Python experience", high_evidence)
    assert result_high.decision == "SUFFICIENT_EVIDENCE"
    assert result_high.confidence_score == 0.92
    assert result_high.best_evidence.chunk_id == "c_001"

@pytest.mark.asyncio
async def test_knowledge_service_ingest_and_evaluate():
    await init_db()
    async with AsyncSessionLocal() as session:
        embedder = MockEmbeddingProvider()
        store = FAISSVectorStore()
        service = KnowledgeService(db=session, embedding_provider=embedder, vector_store=store)

        sample_dir = os.path.join("knowledge_base")
        res = await service.ingest_directory(sample_dir)
        assert res["ingested_files"] > 0

        eval_res = await service.evaluate_evidence("Python FastAPI experience")
        assert eval_res.decision in ("SUFFICIENT_EVIDENCE", "WEAK_EVIDENCE", "INSUFFICIENT_EVIDENCE")

@pytest.mark.asyncio
async def test_profile_api():
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/profile/?user_id=user_default")
    assert response.status_code == 200
    data = response.json()
    assert data["personal"]["first_name"] in ("Raghav", "Manish")
    assert "Python" in str(data["skills"])

@pytest.mark.asyncio
async def test_knowledge_api():
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Test Ingest
        ingest_res = await ac.post("/api/knowledge/ingest", json={"path": "./knowledge_base"})
        assert ingest_res.status_code == 200
        assert ingest_res.json()["status"] == "success"

        # Test Search
        search_res = await ac.get("/api/knowledge/search?query=Python%20experience")
        assert search_res.status_code == 200
        assert isinstance(search_res.json(), list)

        # Test Evaluate
        eval_res = await ac.get("/api/knowledge/evaluate?query=Python%20experience")
        assert eval_res.status_code == 200
        assert "decision" in eval_res.json()
