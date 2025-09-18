# core/config.py
import os
from datetime import timedelta
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DATABASE_URL: str
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "your-secret-key")
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    
    SMTP_SERVER: str = os.getenv("SMTP_SERVER", "smtp.example.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", 587))
    SMTP_USER: str = os.getenv("SMTP_USER", "user@example.com")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "password")
    
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # Link with .env
    model_config = SettingsConfigDict(env_file="./.env", extra="ignore")

settings = Settings()