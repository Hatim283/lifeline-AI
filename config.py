import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    gemini_api_key: str
    gemini_model: str = "gemini-1.5-pro"
    openweather_api_key: Optional[str] = None
    google_maps_api_key: Optional[str] = None
    google_calendar_credentials: Optional[str] = None
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
