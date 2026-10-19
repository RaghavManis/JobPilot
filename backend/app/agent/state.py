from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field
from backend.app.schemas.form import FormPage, FormField, ConfidenceResult, FieldValue


class ApplicationState(BaseModel):
    """Explicit Typed Application State maintained across the LangGraph execution flow."""

    application_id: str
    user_id: str
    target_url: str
    current_url: Optional[str] = None
    current_page_title: Optional[str] = None
    status: str = Field(default="CREATED", description="CREATED, RUNNING, LOGIN_REQUIRED, WAITING_FOR_USER, READY_FOR_REVIEW, SUBMITTED, FAILED")

    login_required: bool = False
    login_completed: bool = False
    page_type: str = Field(default="APPLICATION_FORM", description="AUTHENTICATION_REQUIRED, APPLICATION_FORM, JOB_DESCRIPTION, APPLICATION_SUBMITTED, UNKNOWN")
    auth_category: Optional[str] = Field(default=None, description="LOGIN, REGISTRATION, LOGIN_OR_REGISTER, OTP_VERIFICATION, CAPTCHA")
    auth_details: Optional[str] = Field(default=None, description="Human-readable description of current page authentication requirement")

    form_page: Optional[FormPage] = None
    detected_fields: List[FormField] = Field(default_factory=list)
    mapped_answers: Dict[str, ConfidenceResult] = Field(default_factory=dict)  # field_id -> ConfidenceResult

    auto_fill_queue: List[FieldValue] = Field(default_factory=list)
    human_review_queue: List[ConfidenceResult] = Field(default_factory=list)

    completed_pages: List[str] = Field(default_factory=list)
    validation_errors: List[str] = Field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 3

    submission_approved: bool = False
    has_next_page: bool = Field(default=False, description="True if the active form step has a Next/Continue button to advance to another step")
    has_auto_advanced: bool = Field(default=False, description="True if a file upload or interaction caused the portal to auto-advance to the next step")
    next_button_id: Optional[str] = Field(default=None, description="data-jp-id or selector of the detected Next/Continue button")
    current_step: int = Field(default=1, description="Current wizard step index in multi-page applications")
    total_fields_filled: int = Field(default=0, description="Cumulative count of fields auto-filled or verified across all steps")
    all_completed_fields: List[Dict[str, Any]] = Field(default_factory=list, description="Historical record of all filled fields across all steps for final review summary")
    error_message: Optional[str] = None

