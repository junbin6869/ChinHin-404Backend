from fastapi import FastAPI
from app.core.config import settings
from app.api.routes import router, init_foundry_client
from app.services.foundry_client import FoundryClient

app = FastAPI(title="Chinhin FastAPI Backend")

@app.on_event("startup")
def on_startup():
    client = FoundryClient(
        endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        deployment=settings.azure_openai_deployment,
    )
    init_foundry_client(client)

app.include_router(router, prefix="/api")

@app.get("/health")
async def health():
    return {"status": "ok"}
