from pydantic import BaseModel, Field


class CopilotRequest(BaseModel):
    message: str = Field(..., min_length=1)


class CopilotResponse(BaseModel):
    reply: str
