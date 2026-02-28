from pydantic import BaseModel, Field
from typing import Optional


class CopilotRequest(BaseModel):
    message: str = Field(..., min_length=1)
    conversation_id: Optional[str] = None


class CopilotResponse(BaseModel):
    reply: str
    conversation_id: str