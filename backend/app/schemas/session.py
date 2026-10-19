from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class BrowserSession(BaseModel):
    session_id: str
    is_headless: bool = True
    active_url: Optional[str] = None
    page_title: Optional[str] = None
    is_active: bool = True


class ApplicationSessionCreate(BaseModel):
    user_id: str = Field(..., description="ID of the user initiating the application")
    target_url: str = Field(..., description="URL of the target job application")


class ApplicationSession(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    target_url: str
    status: str = Field(default="CREATED", description="Status e.g. CREATED, RUNNING, PAUSED, READY_FOR_REVIEW, SUBMITTED, FAILED")
    current_page_title: Optional[str] = None
    current_url: Optional[str] = None
    submission_approved: bool = False
    created_at: datetime
    updated_at: datetime
