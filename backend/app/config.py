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
    # Defaults allow unit tests to import the app without a real .env.
    # Runtime deployments should always provide real values via environment variables.
    SUPABASE_URL: str = "http://localhost:54321"
    SUPABASE_KEY: str = "test-anon-key"
    SUPABASE_SERVICE_ROLE_KEY: Optional[str] = None

    # --- Gemini AI ---
    GEMINI_API_KEY: str = "test-gemini-key"
    GEMINI_MODEL: str = "gemma-4-31b-it"
    GEMINI_ANALYSIS_MODEL: str = "gemini-3-flash-lite"
    GEMINI_EMBEDDING_MODEL: str = "gemini-embedding-2"

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
    WHOOP_WEBHOOK_LOG_RAW: bool = False

    # --- Garmin API ---
    GARMIN_CONSUMER_KEY: Optional[str] = None
    GARMIN_CONSUMER_SECRET: Optional[str] = None
    GARMIN_WEBHOOK_SECRET: Optional[str] = None
    GARMIN_OAUTH_CONFIRM_URL: str = "https://connect.garmin.com/oauthConfirm"

    # --- Strava API ---
    STRAVA_CLIENT_ID: str = ""
    STRAVA_CLIENT_SECRET: str = ""
    STRAVA_WEBHOOK_VERIFY_TOKEN: str = ""  # a static secret string you choose, used to verify Strava's hub challenge
    STRAVA_WEBHOOK_SUBSCRIPTION_ID: int = 0  # filled in after you register the webhook

    # --- Resend Email ---
    RESEND_API_KEY: Optional[str] = None
    RESEND_AUDIENCE_ID: Optional[str] = None

    # --- IP Rate Limiting ---
    IP_RATE_LIMIT_RPM: int = 100  # requests per minute per IP across all endpoints

    # --- Push Notifications ---
    # Firebase service account JSON (full JSON string, not a file path).
    # Generate at: Firebase Console → Project Settings → Service Accounts → Generate new private key
    FCM_SERVICE_ACCOUNT_JSON: Optional[str] = None

    # VAPID keys for web push. Generate with:  npx web-push generate-vapid-keys
    VAPID_PUBLIC_KEY: Optional[str] = None
    VAPID_PRIVATE_KEY: Optional[str] = None
    VAPID_SUBJECT: str = "mailto:admin@astrape.app"

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