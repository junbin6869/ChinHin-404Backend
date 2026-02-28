from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    foundry_project_endpoint: str
    auth_secret: str = "dev-secret-change-me"

    # Multi-agent names
    foundry_routing_agent_name: str = "routing-agent"
    foundry_general_agent_name: str = "general-agent"
    foundry_promotion_agent_name: str = "promotion-agent"
    foundry_procurement_agent_name: str = "procurement-agent"
    foundry_document_agent_name: str = "document-agent"


settings = Settings()