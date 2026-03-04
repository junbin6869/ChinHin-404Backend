from pydantic_settings import BaseSettings, SettingsConfigDict
import os

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    foundry_project_endpoint: str
    auth_secret: str = "dev-secret-change-me"

    # Multi-agent names
    foundry_routing_agent_name: str = "routing-agent"
    foundry_general_agent_name: str = "general-agent"
    foudry_data_fetch_agent_name: str = "data-fetch-agent"
    foundry_promotion_recommendation_agent_name: str = "promotion-recommendation-agent" 
    foundry_promotion_analysis_agent_name: str = "promotion-analysis-agent"
    foundry_promotion_monitor_agent_name: str = "promotion-monitor-agent"
    foundry_document_classification_agent_name: str = "classification-agent"
    foundry_document_governance_agent_name: str = "governance-agent"
    foundry_document_retrieval_agent_name: str = "retrieval-agent"
    foundry_procurement_forecasting_agent_name: str = "procurement-forecasting"
    foundry_procurement_PRgeneration_agent_name: str = "procurement-PRgeneration"
    foundry_procurement_approval_insight_agent_name: str = "procurement-approval-insight"
    foundry_procurement_delivery_prediction_agent_name: str = "procurement-delivery-prediction"
    DB_URL: str = "mssql+pyodbc://CloudSA19804fa6:iloveUTAR888@404notfound.database.windows.net/404notfound?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=no"
    DB_ALLOWED_OBJECTS: str = ""
    DB_DEFAULT_ROW_LIMIT: int = 500


settings = Settings()