from pydantic import BaseModel, Field
from typing import Optional, Any

class ScreeningCheckIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=256)
    client_id: Optional[str] = None
    country_focus: Optional[str] = None

class ScreeningCheckOut(BaseModel):
    request_id: str
    risk_level: str
    confidence: int
    recommended_action: str
    top_matches: list[dict[str, Any]]
