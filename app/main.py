from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.routes import router, init_foundry_client
from app.services.foundry_client import FoundryClient

app = FastAPI(title="Chinhin FastAPI Backend")

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

@app.on_event("startup")
def on_startup():
    # initialize once
    client = FoundryClient(
        endpoint=settings.foundry_project_endpoint,
        agent_name=settings.foundry_agent_name,
    )
    init_foundry_client(client)

app.include_router(router, prefix="/api")

@app.get("/health")
async def health():
    return {"status": "okkkkk"}

