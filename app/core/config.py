from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    foundry_project_endpoint: str = "https://Testinggggggg.services.ai.azure.com/api/projects/proj-default"
    foundry_agent_name: str = "testing-LLM"


settings = Settings()
