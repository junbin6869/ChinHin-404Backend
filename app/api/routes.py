from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from app.schemas.copilot import CopilotRequest, CopilotResponse
from app.services.foundry_client import FoundryClient

router = APIRouter()


_foundry_client: FoundryClient | None = None


def init_foundry_client(client: FoundryClient):
    global _foundry_client
    _foundry_client = client


@router.post("/copilot", response_model=CopilotResponse)
async def copilot(req: CopilotRequest):
    if _foundry_client is None:
        raise HTTPException(status_code=500, detail="Foundry client not initialized")

    try:
        reply = await run_in_threadpool(_foundry_client.chat_once, req.message)
        return CopilotResponse(reply=reply)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Foundry call failed: {e}")
