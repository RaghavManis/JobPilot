import re
from typing import List, Dict, Any
from backend.app.schemas.rag import DocumentChunk, DocumentMetadata
from backend.app.core.logging import logger


class TextChunker:
    """Splits loaded text content into clean DocumentChunks with metadata."""

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 100):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_document(self, doc_data: Dict[str, Any]) -> List[DocumentChunk]:
        """Split document text into structured DocumentChunks."""
        text = doc_data["content"]
        doc_name = doc_data["document_name"]
        doc_type = doc_data["document_type"]
        source_path = doc_data["source_path"]

        clean_name = re.sub(r'[^a-zA-Z0-9_]', '_', doc_name.rsplit('.', 1)[0])

        if not text:
            logger.warning(f"Document '{doc_name}' is empty.")
            return []

        chunks: List[DocumentChunk] = []
        start = 0
        text_length = len(text)
        index = 1

        while start < text_length:
            end = min(start + self.chunk_size, text_length)
            
            # Try splitting at paragraph or sentence boundary if possible
            if end < text_length:
                last_newline = text.rfind("\n", start, end)
                if last_newline != -1 and last_newline > start + self.chunk_size // 2:
                    end = last_newline + 1
                else:
                    last_period = text.rfind(". ", start, end)
                    if last_period != -1 and last_period > start + self.chunk_size // 2:
                        end = last_period + 1

            chunk_text = text[start:end].strip()
            if chunk_text:
                chunk_id = f"{clean_name}_{index:03d}"
                meta = DocumentMetadata(
                    document_name=doc_name,
                    document_type=doc_type,
                    chunk_id=chunk_id,
                    source_path=source_path
                )
                chunks.append(DocumentChunk(
                    chunk_id=chunk_id,
                    text=chunk_text,
                    metadata=meta
                ))
                index += 1

            if end >= text_length:
                break

            start = max(start + 1, end - self.chunk_overlap)

        logger.info(f"Chunked document '{doc_name}' into {len(chunks)} chunks (size={self.chunk_size}, overlap={self.chunk_overlap}).")
        return chunks
