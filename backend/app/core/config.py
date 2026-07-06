from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "Gmail Multi-Account Manager"
    database_url: str = "sqlite:///./data/app.db"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/admin/oauth/google/callback"
    master_key: str = Field("change-me-to-a-long-random-secret", min_length=8)
    admin_token: str = ""
    frontend_origin: str = "http://127.0.0.1:5173"
    default_initial_sync_days: int = 30
    default_initial_sync_limit: int = 200
    oauth_state_ttl_seconds: int = 600

    @property
    def cors_origins(self) -> List[str]:
        values = [self.frontend_origin, "http://localhost:5173"]
        return list(dict.fromkeys([item for item in values if item]))


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
