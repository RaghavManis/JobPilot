from typing import List, Optional, Any, Union
from pydantic import BaseModel, Field


class FormField(BaseModel):
    """Represents a clean extracted DOM interactive element."""
    data_jp_id: str = Field(..., description="Synthetic unique element identifier, e.g., field_001")
    tag_name: str = Field(..., description="HTML tag name, e.g. input, select, textarea, button")
    input_type: Optional[str] = Field(None, description="Input type attribute, e.g. text, email, radio, checkbox, file")
    name: Optional[str] = Field(None, description="HTML name attribute")
    element_id: Optional[str] = Field(None, description="HTML element id attribute")
    placeholder: Optional[str] = Field(None, description="Input placeholder attribute")
    label: Optional[str] = Field(None, description="Associated label or surrounding question text")
    visible_text: Optional[str] = Field(None, description="Visible text content (for buttons, options)")
    is_required: bool = False
    is_visible: bool = True
    current_value: Optional[str] = None
    options: List[str] = Field(default_factory=list, description="Available options for select dropdowns or radio groups")
    option_elements: Optional[dict[str, str]] = Field(default_factory=dict, description="Mapping from option label to element data_jp_id")
    section_heading: Optional[str] = Field(None, description="Enclosing section heading, fieldset legend, or group title")
    helper_text: Optional[str] = Field(None, description="Contextual instructions, format hint, or help block")


class FormPage(BaseModel):
    """Represents the parsed interactive structure of a web page."""
    url: str
    title: str
    fields: List[FormField] = Field(default_factory=list)
    has_login_wall: bool = False
    is_multi_page: bool = False
    page_type: str = Field(default="APPLICATION_FORM", description="AUTHENTICATION_REQUIRED, APPLICATION_FORM, JOB_DESCRIPTION, APPLICATION_SUBMITTED, UNKNOWN")
    auth_category: Optional[str] = Field(default=None, description="LOGIN, REGISTRATION, LOGIN_OR_REGISTER, OTP_VERIFICATION, CAPTCHA")
    auth_details: Optional[str] = Field(default=None, description="Human-readable description of authentication barrier")
    has_webcam_challenge: bool = False


class ConfidenceResult(BaseModel):
    """Encapsulates structured LLM reasoning and confidence assignment."""
    field_id: str = Field(..., description="Synthetic identifier matching data_jp_id")
    answer: Optional[Union[str, bool]] = Field(None, description="Determined fill value or selected option")
    confidence: float = Field(..., description="Confidence score from 0.0 to 1.0")
    reason: str = Field(..., description="Explanation of how the answer was inferred or why confidence is low")
    source_citations: List[str] = Field(default_factory=list, description="Sources relied upon, e.g., ['user_profile.personal.email']")
    requires_human_input: bool = Field(default=False, description="True if evidence is insufficient or question is sensitive")
    question_text: Optional[str] = Field(None, description="Full application question or resolved label")
    section_heading: Optional[str] = Field(None, description="Surrounding section heading or legend")
    helper_text: Optional[str] = Field(None, description="Contextual instructions, format hint, or help block")
    field_type: Optional[str] = Field(None, description="Field input type: select, radio, checkbox, text, date, textarea, file, etc.")
    options: List[str] = Field(default_factory=list, description="Available options for dropdown or radio group")
    option_elements: Optional[dict[str, str]] = Field(default_factory=dict, description="Mapping from option label to element data_jp_id")
    is_required: bool = Field(default=False, description="Whether field is required")


class FieldValue(BaseModel):
    """Value payload used by the browser action layer to fill a field."""
    data_jp_id: str
    value: Any
    field_type: Optional[str] = None
