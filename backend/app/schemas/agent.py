from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class AgentEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    event_type: str = Field(..., description="e.g. BROWSER_START, PAGE_NAVIGATE, DOM_INSPECT, ACTION_EXECUTE, LLM_CALL, HUMAN_INTERRUPT, ERROR")
    message: str
    details: Optional[Dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
