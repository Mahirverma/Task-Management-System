# core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str
    secret_key: str
    access_token_expire_minutes: int = 30
    algorithm: str = "HS256"

    # Link with .env
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()