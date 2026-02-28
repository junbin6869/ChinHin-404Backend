from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool
from uuid import uuid4

from app.schemas.copilot import CopilotRequest, CopilotResponse
from app.services.orchestrator import Orchestrator

router = APIRouter()

_orchestrator: Orchestrator | None = None


def init_orchestrator(o: Orchestrator):
    global _orchestrator
    _orchestrator = o

#step 2: user ask question
@router.post("/copilot", response_model=CopilotResponse)
async def copilot(req: CopilotRequest):
    if _orchestrator is None:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized")

    conversation_id = req.conversation_id or str(uuid4())

    try:
        reply = await run_in_threadpool(_orchestrator.handle, conversation_id, req.message)
        # remove "Clarify: "
        return CopilotResponse(reply=reply, conversation_id=conversation_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Copilot failed: {e}")