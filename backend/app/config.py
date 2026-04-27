from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    """Centralized configuration for the ASTRAPE backend."""
    
    # --- General App Configuration ---
    APP_NAME: str = "ASTRAPE-Backend"
    APP_ENV: str = "development" 
    PORT: int = 8000
    APP_BASE_URL: str = "http://localhost:8000"
    API_PREFIX: str = "/v1"
    MOBILE_DEEP_LINK_SCHEME: str = "astrape"

    # --- Supabase ---
    SUPABASE_URL: str
    SUPABASE_KEY: str

    # --- Gemini AI ---
    GEMINI_API_KEY: str
    GEMINI_MODEL: str = "gemini-flash-lite-latest"

    # --- Google Cloud ---
    GCP_PROJECT_ID: Optional[str] = None
    GCP_BUCKET_NAME: Optional[str] = None

    # --- WHOOP API ---
    WHOOP_CLIENT_ID: Optional[str] = None
    WHOOP_CLIENT_SECRET: Optional[str] = None
    WHOOP_WEBHOOK_SECRET: Optional[str] = None
    WHOOP_API_BASE: str = "https://api.prod.whoop.com/developer/v1"
    WHOOP_OAUTH_AUTH_URL: str = "https://api.prod.whoop.com/oauth/oauth2/auth"
    WHOOP_OAUTH_TOKEN_URL: str = "https://api.prod.whoop.com/oauth/oauth2/token"

    # --- Garmin API ---
    GARMIN_CONSUMER_KEY: Optional[str] = None
    GARMIN_CONSUMER_SECRET: Optional[str] = None
    GARMIN_WEBHOOK_SECRET: Optional[str] = None
    GARMIN_OAUTH_CONFIRM_URL: str = "https://connect.garmin.com/oauthConfirm"
    
    # --- Manual Testing ---
    TEST_ATHLETE_ID: str | None = None

    # --- Path Management ---
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    PROMPTS_DIR: Path = BASE_DIR / "app" / "prompts"
    COACH_PROMPT_FILE: str = "coach_behavior.md"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()