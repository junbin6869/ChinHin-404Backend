from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.routes import router, init_orchestrator
from app.services.foundry_client import FoundryClient
from app.services.orchestrator import Orchestrator
from app.api.auth_routes import router as auth_router

app = FastAPI(title="Chinhin FastAPI Backend")
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://jolly-sky-0f21f0c10.2.azurestaticapps.net",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# step 1: initiate 
@app.on_event("startup")
def on_startup():
    agent_map = {
        "routing": settings.foundry_routing_agent_name,
        "promotion": settings.foundry_promotion_agent_name,
        "procurement": settings.foundry_procurement_agent_name,
        "document": settings.foundry_document_agent_name,
        "general": settings.foundry_general_agent_name,
    }

    foundry = FoundryClient(
        endpoint=settings.foundry_project_endpoint,
        agent_map=agent_map,
    )
    orchestrator = Orchestrator(foundry)
    init_orchestrator(orchestrator)

app.include_router(router, prefix="/api")

@app.get("/health")
async def health():
    return {"status": "okkkkk"}