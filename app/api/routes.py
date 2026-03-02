from fastapi import APIRouter, HTTPException, Request
from app import state
import traceback
import uuid

from app.schemas.copilot import CopilotRequest, CopilotResponse
from app.services.orchestrator import Orchestrator

router = APIRouter()

_orchestrator: Orchestrator | None = None


def init_orchestrator(o: Orchestrator):
    global _orchestrator
    _orchestrator = o

#step 2: user ask question
@router.post("/copilot", response_model=CopilotResponse)
def copilot(req: CopilotRequest, request: Request):
    """
    Main Copilot endpoint.

    Flow:
    1. Receive user message from frontend
    2. Pass message to orchestrator
    3. Orchestrator handles routing -> data fetch -> business agent
    4. Return final reply to frontend
    """

    try:
        # Step 1: Call orchestrator
        result = state.orchestrator.handle(
            user_message=req.message,
            conversation_id=req.conversation_id if hasattr(req, "conversation_id") else None,
        )
        conv_id = getattr(result, "conversation_id", None) or str(uuid.uuid4())
        reply = getattr(result, "reply", None)


        # Step 2: Return structured response
        return {
            "reply": reply,                 # ✅ string
            "intent": result.agent,                
            "conversation_id": conv_id,
        }   

    except ValueError as e:
        # Raised by SQL validation or JSON parsing errors
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        # Catch unexpected errors (DB failure, Foundry timeout, etc.)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal server error.")