from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    foundry_project_endpoint: str 
    azure_openai_api_key: str 
    azure_openai_deployment: str 


settings = Settings()
