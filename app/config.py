from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8-sig")

    api_key: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    llm_model: str = Field(min_length=1)
    access_code: str = Field(min_length=1)
    mock_llm: bool = False
    session_ttl_seconds: int = 3600
    environment: str = "development"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
