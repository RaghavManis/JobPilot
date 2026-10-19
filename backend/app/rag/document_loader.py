import os
from pathlib import Path
from typing import Dict, Any, Optional
from backend.app.core.logging import logger
from backend.app.core.exceptions import JobPilotException

try:
    import pypdf
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False


class DocumentLoader:
    """Loads and extracts plain text from Markdown, TXT, and PDF files."""

    @staticmethod
    def infer_document_type(file_path: str) -> str:
        """Infer document category from path parent directory or name."""
        path_lower = file_path.lower()
        if "resume" in path_lower:
            return "resume"
        elif "project" in path_lower:
            return "project"
        elif "experience" in path_lower:
            return "experience"
        elif "education" in path_lower:
            return "education"
        elif "answer" in path_lower:
            return "answer"
        elif "achievement" in path_lower:
            return "achievement"
        return "general"

    @classmethod
    def load_file(cls, file_path: str) -> Dict[str, Any]:
        """Load text content and metadata from a file."""
        if not os.path.exists(file_path):
            raise JobPilotException(f"Document file not found: {file_path}")

        ext = Path(file_path).suffix.lower()
        doc_name = os.path.basename(file_path)
        doc_type = cls.infer_document_type(file_path)

        logger.info(f"Loading document '{doc_name}' ({ext}) [Type: {doc_type}]...")

        if ext in (".md", ".txt"):
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read().strip()
        elif ext == ".pdf":
            if not PYPDF_AVAILABLE:
                raise JobPilotException("pypdf package is required to read PDF files.")
            try:
                reader = pypdf.PdfReader(file_path)
                pages_text = [page.extract_text() for page in reader.pages if page.extract_text()]
                content = "\n\n".join(pages_text).strip()
            except Exception as e:
                logger.error(f"Failed to extract PDF content from {file_path}: {e}")
                raise JobPilotException(f"PDF extraction error: {e}") from e
        else:
            raise JobPilotException(f"Unsupported file format: {ext}")

        return {
            "document_name": doc_name,
            "document_type": doc_type,
            "source_path": os.path.abspath(file_path),
            "content": content
        }
