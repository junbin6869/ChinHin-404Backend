from pydantic_settings import BaseSettings, SettingsConfigDict
import os

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    foundry_project_endpoint: str
    auth_secret: str = "dev-secret-change-me"

    # Multi-agent names
    foundry_routing_agent_name: str = "routing-agent"
    foundry_general_agent_name: str = "general-agent"
    foundry_promotion_agent_name: str = "promotion-agent-testing" 
    foundry_procurement_agent_name: str = "procurement-agent-testing"
    foundry_document_agent_name: str = "document-agent-testing"
    foudry_data_fetch_agent_name: str = "data-fetch-agent"
    DB_URL: str = "mssql+pyodbc://CloudSA19804fa6:iloveUTAR888@404notfound.database.windows.net/404notfound?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=no"
    DB_ALLOWED_OBJECTS: str = ""
    DB_DEFAULT_ROW_LIMIT: int = 500


settings = Settings()