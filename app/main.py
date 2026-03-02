from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.routes import router, init_orchestrator
from app.services.foundry_client import FoundryClient
from app.services.orchestrator import Orchestrator
from app.services.db import Database, DBConfig
from app.api.auth_routes import router as auth_router
from app import state

app = FastAPI(title="Chinhin FastAPI Backend")
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])

# Initialize database
db = Database(
    DBConfig(
        db_url=settings.DB_URL,
        allowed_objects=[x.strip() for x in settings.DB_ALLOWED_OBJECTS.split(",") if x.strip()] or None,
        default_row_limit=settings.DB_DEFAULT_ROW_LIMIT,
    )
)

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
        "data_fetch":settings.foudry_data_fetch_agent_name, 
    }

    foundry = FoundryClient(
        endpoint=settings.foundry_project_endpoint,
        agent_map=agent_map,
    )
    state.orchestrator = Orchestrator(foundry_client=foundry, db=db)
    init_orchestrator(state.orchestrator)

app.include_router(router, prefix="/api")

@app.get("/health")
async def health():
    return {"status": "okkkkk"}

@app.on_event("startup")
def startup():
    db.init()


@app.on_event("shutdown")
def shutdown():
    db.close()