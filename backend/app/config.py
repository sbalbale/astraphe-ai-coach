from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Centralized configuration for the ASTRAPHE backend."""
    
    # --- General App Configuration ---
    APP_NAME: str = "ASTRAPHE-Backend"
    APP_VERSION: str = "1.0.0"
    APP_ENV: str = "development" 
    PORT: int = 8000
    APP_BASE_URL: str = "http://localhost:8000"
    API_PREFIX: str = "/v1"
    MOBILE_DEEP_LINK_SCHEME: str = "astraphe"

    # --- Supabase ---
    # Defaults allow unit tests to import the app without a real .env.
    # Runtime deployments should always provide real values via environment variables.
    SUPABASE_URL: str = "http://localhost:54321"
    SUPABASE_KEY: str = "test-anon-key"
    SUPABASE_SERVICE_ROLE_KEY: Optional[str] = None

    # --- Gemini AI ---
    GEMINI_API_KEY: str = "test-gemini-key"
    GEMINI_MODEL: str = "gemma-4-26b-a4b-it"
    # Fallback chat model when the primary model is overloaded (e.g. 503 UNAVAILABLE).
    GEMINI_FALLBACK_MODEL: str = "gemma-4-26b-a4b-it"
    GEMINI_ANALYSIS_MODEL: str = "gemini-flash-lite-latest"
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
    # Set True to accept webhooks without verifying the signature.
    # Use only in development when the portal-generated signing secret is not accessible.
    WHOOP_WEBHOOK_SKIP_SIG_CHECK: bool = False

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
    STRAVA_STARTUP_BACKFILL_ENABLED: bool = True
    STRAVA_STARTUP_BACKFILL_HOURS: int = 24

    # --- WHOOP startup backfill (self-heal missed webhooks after deploy/restart) ---
    WHOOP_STARTUP_BACKFILL_ENABLED: bool = True
    WHOOP_STARTUP_BACKFILL_HOURS: int = 24

    # --- Resend Email ---
    RESEND_API_KEY: Optional[str] = None
    RESEND_AUDIENCE_ID: Optional[str] = None

    # --- Redis ---
    # Local dev:  redis://localhost:6379
    # Upstash:    rediss://default:<token>@<host>.upstash.io:6380
    # Leave unset to use the in-process memory fallback.
    REDIS_URL: Optional[str] = None

    # --- IP Rate Limiting ---
    IP_RATE_LIMIT_RPM: int = 100  # requests per minute per IP across all endpoints

    # --- Push Notifications ---
    # Firebase service account JSON (full JSON string, not a file path).
    # Generate at: Firebase Console → Project Settings → Service Accounts → Generate new private key
    FCM_SERVICE_ACCOUNT_JSON: Optional[str] = None

    # VAPID keys for web push. Generate with:  npx web-push generate-vapid-keys
    VAPID_PUBLIC_KEY: Optional[str] = None
    VAPID_PRIVATE_KEY: Optional[str] = None
    VAPID_SUBJECT: str = "mailto:admin@astraphe.app"

    # --- Manual Testing ---
    TEST_ATHLETE_ID: str | None = None

    # --- Path Management ---
    BASE_DIR: Path = BACKEND_DIR
    PROMPTS_DIR: Path = BASE_DIR / "app" / "prompts"
    COACH_PROMPT_FILE: str = "coach_behavior.md"

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        # Prefer backend/.env over shell environment variables so stale shell
        # exports don't shadow local dev settings. In production no .env file
        # is present in the container, so env_settings wins by default.
        return init_settings, dotenv_settings, env_settings, file_secret_settings

settings = Settings()