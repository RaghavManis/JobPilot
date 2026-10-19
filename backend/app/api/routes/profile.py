from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database.session import get_db
from backend.app.schemas.profile import UserProfile
from backend.app.services.knowledge_service import KnowledgeService
from backend.app.rag.embeddings.mock_provider import MockEmbeddingProvider
from backend.app.rag.vector_store.faiss_store import FAISSVectorStore

router = APIRouter(prefix="/api/profile", tags=["User Profile"])

# In-memory shared store for Phase 2 API demo
_vector_store = FAISSVectorStore(persist_dir="./knowledge_base/faiss_index")
_embedding_provider = MockEmbeddingProvider()


def get_knowledge_service(db: AsyncSession = Depends(get_db)) -> KnowledgeService:
    return KnowledgeService(
        db=db,
        embedding_provider=_embedding_provider,
        vector_store=_vector_store
    )


@router.get("/", response_model=UserProfile)
async def get_profile(
    user_id: str = "user_default",
    service: KnowledgeService = Depends(get_knowledge_service)
):
    """Retrieve canonical UserProfile."""
    profile = await service.get_user_profile(user_id)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile for user '{user_id}' not found."
        )
    return profile


@router.put("/", response_model=UserProfile)
async def update_profile(
    profile: UserProfile,
    service: KnowledgeService = Depends(get_knowledge_service)
):
    """Update or save canonical UserProfile."""
    return await service.save_user_profile(profile)


import os
import shutil
from fastapi import UploadFile, File
from fastapi.responses import FileResponse

ALLOWED_PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_PHOTO_MIMES = {"image/jpeg", "image/png", "image/webp"}
MAX_PHOTO_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB


@router.post("/photo")
async def upload_profile_photo(
    file: UploadFile = File(...),
    user_id: str = "user_default",
    service: KnowledgeService = Depends(get_knowledge_service)
):
    """Securely upload and persistently store candidate profile photograph."""
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No file selected.")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_PHOTO_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid image format '{ext}'. Allowed: {', '.join(ALLOWED_PHOTO_EXTENSIONS)}"
        )

    if file.content_type and file.content_type not in ALLOWED_PHOTO_MIMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid MIME type '{file.content_type}'. Must be image/jpeg, image/png, or image/webp."
        )

    photos_dir = os.path.join(os.getcwd(), "knowledge_base", "photos")
    os.makedirs(photos_dir, exist_ok=True)

    dest_filename = f"profile_photo_{user_id}{ext}"
    dest_path = os.path.join(photos_dir, dest_filename)

    # Read and enforce file size limit
    content = await file.read()
    if len(content) > MAX_PHOTO_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File exceeds maximum allowed size of 5MB."
        )

    with open(dest_path, "wb") as f:
        f.write(content)

    # Update UserProfile personal.photo_path
    profile = await service.get_user_profile(user_id)
    if profile:
        profile.personal.photo_path = dest_path
        await service.save_user_profile(profile)

    return {
        "message": "Profile photograph uploaded and stored securely.",
        "filename": dest_filename,
        "photo_path": dest_path
    }


@router.get("/photo")
async def get_profile_photo(
    user_id: str = "user_default",
    service: KnowledgeService = Depends(get_knowledge_service)
):
    """Retrieve saved profile photograph."""
    profile = await service.get_user_profile(user_id)
    photo_path = profile.personal.photo_path if profile else None

    if not photo_path or not os.path.exists(photo_path):
        photos_dir = os.path.join(os.getcwd(), "knowledge_base", "photos")
        if os.path.exists(photos_dir):
            cands = [
                os.path.join(photos_dir, f) for f in os.listdir(photos_dir)
                if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
            ]
            if cands:
                photo_path = cands[0]

    if not photo_path or not os.path.exists(photo_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No profile photograph stored for this user."
        )

    ext = os.path.splitext(photo_path)[1].lower()
    media_type = "image/png" if ext == ".png" else "image/webp" if ext == ".webp" else "image/jpeg"
    return FileResponse(photo_path, media_type=media_type)
