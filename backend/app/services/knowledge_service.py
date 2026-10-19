import os
import json
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.app.database.models import UserProfileModel
from backend.app.schemas.profile import UserProfile
from backend.app.schemas.rag import SearchResult, Evidence, EvaluationResult, DocumentChunk
from backend.app.rag.document_loader import DocumentLoader
from backend.app.rag.chunker import TextChunker
from backend.app.rag.embeddings.provider import EmbeddingProvider
from backend.app.rag.vector_store.interface import VectorStore
from backend.app.rag.retriever import Retriever
from backend.app.rag.evaluator import EvidenceEvaluator
from backend.app.core.logging import logger
from backend.app.core.exceptions import JobPilotException


class KnowledgeService:
    """Service layer managing canonical UserProfile, document ingestion, vector retrieval, and evidence evaluation."""

    def __init__(
        self,
        db: AsyncSession,
        embedding_provider: EmbeddingProvider,
        vector_store: VectorStore,
        chunk_size: int = 500,
        chunk_overlap: int = 100
    ):
        self.db = db
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store
        self.chunker = TextChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        self.retriever = Retriever(embedding_provider=embedding_provider, vector_store=vector_store)
        self.evaluator = EvidenceEvaluator()

    # User Profile Operations
    async def get_user_profile(self, user_id: str) -> Optional[UserProfile]:
        if self.db is not None:
            stmt = select(UserProfileModel).where(UserProfileModel.user_id == user_id)
            res = await self.db.execute(stmt)
            model = res.scalar_one_or_none()

            if model:
                profile_dict = model.get_profile_dict()
                return UserProfile.model_validate(profile_dict)

        # Fallback: try profile.json, then user_profile.json
        candidate_files = [
            os.path.join("knowledge_base", "profiles", "profile.json"),
            os.path.join("knowledge_base", "profiles", "user_profile.json"),
        ]
        for profile_file in candidate_files:
            if os.path.exists(profile_file):
                with open(profile_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Always bind this profile to the requested user_id so the
                # validator does not fail on a mismatched user_id in the file.
                data["user_id"] = user_id
                try:
                    return UserProfile.model_validate(data)
                except Exception as e:
                    logger.warning(f"Profile validation warning for {profile_file}: {e}")
                    # Still return a best-effort profile stripping unknown keys
                    clean = {k: data[k] for k in ("user_id", "personal", "professional", "education", "skills") if k in data}
                    return UserProfile.model_validate(clean)

        return None

    async def save_user_profile(self, profile: UserProfile) -> UserProfile:
        """Save or update UserProfile in database."""
        stmt = select(UserProfileModel).where(UserProfileModel.user_id == profile.user_id)
        res = await self.db.execute(stmt)
        model = res.scalar_one_or_none()

        if not model:
            model = UserProfileModel(
                id=f"profile_{profile.user_id}",
                user_id=profile.user_id,
                profile_data_json=json.dumps(profile.model_dump())
            )
            self.db.add(model)
        else:
            model.set_profile_dict(profile.model_dump())

        await self.db.commit()
        await self.db.refresh(model)
        logger.info(f"Saved canonical UserProfile for user '{profile.user_id}'.")
        return profile

    # User Feedback & Corrections Operations
    CORRECTIONS_FILE = os.path.join("knowledge_base", "answers", "user_corrections.json")

    @classmethod
    def normalize_question_key(cls, text: str) -> str:
        import re
        t = (text or "").lower().strip()
        t = re.sub(r"[\*:\?]", "", t).strip()
        return t

    def save_user_correction(self, question: str, answer: str, context: Optional[Dict[str, Any]] = None):
        """Persist reusable user-confirmed answer for a question without blindly spraying."""
        key = self.normalize_question_key(question)
        if not key or not answer:
            return

        data: Dict[str, Any] = {}
        if os.path.exists(self.CORRECTIONS_FILE):
            try:
                with open(self.CORRECTIONS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}

        data[key] = {
            "answer": answer.strip(),
            "context": context or {},
            "raw_question": question
        }

        os.makedirs(os.path.dirname(self.CORRECTIONS_FILE), exist_ok=True)
        with open(self.CORRECTIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Saved reusable user feedback for question: '{question}' -> '{answer}'")

    def get_user_correction(self, question: str) -> Optional[Dict[str, Any]]:
        """Retrieve previously saved user correction for a question."""
        key = self.normalize_question_key(question)
        if not key or not os.path.exists(self.CORRECTIONS_FILE):
            return None

        try:
            with open(self.CORRECTIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get(key)
        except Exception:
            return None

    # Document Ingestion Operations
    async def ingest_file(self, file_path: str) -> List[DocumentChunk]:
        """Load, chunk, embed, and store a document file into vector database."""
        doc_data = DocumentLoader.load_file(file_path)
        chunks = self.chunker.chunk_document(doc_data)

        if not chunks:
            return []

        texts = [c.text for c in chunks]
        embeddings = await self.embedding_provider.embed_documents(texts)
        await self.vector_store.add_documents(chunks, embeddings)

        logger.info(f"Successfully ingested file '{doc_data['document_name']}' into vector store ({len(chunks)} chunks).")
        return chunks

    async def ingest_directory(self, dir_path: str) -> Dict[str, int]:
        """Ingest all supported documents in directory recursively."""
        if not os.path.exists(dir_path):
            raise JobPilotException(f"Ingestion directory not found: {dir_path}")

        total_files = 0
        total_chunks = 0

        for root, _, files in os.walk(dir_path):
            for file in files:
                if file.endswith((".md", ".txt", ".pdf")):
                    full_path = os.path.join(root, file)
                    try:
                        chunks = await self.ingest_file(full_path)
                        total_files += 1
                        total_chunks += len(chunks)
                    except Exception as e:
                        logger.error(f"Failed to ingest file {full_path}: {e}")

        logger.info(f"Directory ingestion complete for '{dir_path}': {total_files} files, {total_chunks} chunks.")
        return {"ingested_files": total_files, "total_chunks": total_chunks}

    # Query & Retrieval Operations
    async def search(self, query: str, top_k: int = 4) -> List[SearchResult]:
        """Perform semantic similarity search over ingested knowledge base."""
        return await self.retriever.search(query=query, top_k=top_k)

    async def retrieve_evidence(self, query: str, top_k: int = 3) -> List[Evidence]:
        """Retrieve formatted Evidence items for query."""
        return await self.retriever.retrieve_evidence(query=query, top_k=top_k)

    async def evaluate_evidence(self, query: str, top_k: int = 3) -> EvaluationResult:
        """Retrieve evidence and run zero-hallucination EvidenceEvaluator rules."""
        evidence_list = await self.retrieve_evidence(query=query, top_k=top_k)
        return self.evaluator.evaluate(query=query, evidence_list=evidence_list)
