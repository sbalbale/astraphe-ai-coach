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

    # --- LLM Provider ---
    # "gemini" (Google AI Studio) or "openai" (any OpenAI-compatible chat
    # completions endpoint — local llama.cpp/llama-swap, vLLM, LM Studio,
    # etc.). Only affects chat + insights + memory extraction (the model
    # names below); embeddings (GEMINI_EMBEDDING_MODEL) always use Gemini —
    # there's no provider-agnostic embeddings path here yet.
    LLM_PROVIDER: str = "gemini"
    # Base URL of an OpenAI-compatible /v1 API (e.g. "http://localhost:8080/v1"
    # or a llama-swap instance). Required when LLM_PROVIDER=openai.
    OPENAI_API_BASE_URL: Optional[str] = None
    # Most local OpenAI-compatible servers don't check this at all; set it if
    # yours does (e.g. behind a reverse proxy requiring a bearer token).
    OPENAI_API_KEY: Optional[str] = None

    # --- Gemini AI ---
    # Also used for LLM_PROVIDER=openai: these hold whatever model id
    # strings your OpenAI-compatible server expects (its /v1/models list),
    # not necessarily anything Gemini-branded despite the setting names —
    # kept as-is to avoid renaming every call site that reads them.
    GEMINI_API_KEY: str = "test-gemini-key"
    # gemini_quota.py's proactive RPM guardrail assumes Google AI Studio's
    # free-tier limits (30 RPM for the Gemma models this app uses, etc.) and
    # preemptively throttles calls to stay under them. Set this to false if
    # GEMINI_API_KEY is a paid/billed key with real quota — the guardrail
    # will no-op, same as it already does for LLM_PROVIDER=openai. Reactive
    # handling of an actual 429/RESOURCE_EXHAUSTED from Google (retry with
    # backoff, fall back to GEMINI_FALLBACK_MODEL) always stays on
    # regardless of this setting — that's a legitimate response to a real
    # rate-limit error either way, not a guess at one that hasn't happened.
    GEMINI_FREE_TIER: bool = True
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
    # CONSUMER_KEY/SECRET/OAUTH_CONFIRM_URL below are dormant scaffolding for
    # Garmin's official OAuth1.0a Connect Developer Program flow, which is
    # partner-approval-only and not currently in use. The active integration
    # (backend/app/services/garmin.py) instead authenticates via the
    # community `garminconnect` library using the athlete's own Garmin
    # username/password (see docs/GARMIN_INTEGRATION.md).
    GARMIN_CONSUMER_KEY: Optional[str] = None
    GARMIN_CONSUMER_SECRET: Optional[str] = None
    GARMIN_WEBHOOK_SECRET: Optional[str] = None
    GARMIN_OAUTH_CONFIRM_URL: str = "https://connect.garmin.com/oauthConfirm"
    # How often the background poll loop syncs each connected Garmin athlete.
    # Hourly by default so sleep/recovery data is fresh soon after waking,
    # rather than stale for up to several hours. No separate "startup backfill"
    # setting is needed (unlike Strava/WHOOP) — the poll loop runs its first
    # tick immediately on startup, which self-heals the same way.
    GARMIN_SYNC_POLL_HOURS: int = 1
    # Overrides GARMIN_SYNC_POLL_HOURS when set, for sub-hourly polling (e.g.
    # 15). The poll loop reuses the persisted session every tick (never
    # re-logs-in), so more frequent ticks only add more of Garmin's
    # lighter-weight authenticated-API rate limit, not the much stricter
    # SSO-login one — see garmin.py's module docstring. A 429 still triggers
    # the normal GARMIN_RATE_LIMIT_COOLDOWN_SEC backoff regardless of cadence.
    GARMIN_SYNC_POLL_MINUTES: Optional[int] = None

    # --- OAuth token encryption at rest ---
    # Fernet key (url-safe base64, 32 bytes) for encrypting every provider's
    # oauth_tokens.access_token / refresh_token (WHOOP, Strava, intervals.icu,
    # Garmin — see app/services/token_crypto.py). Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # When unset, tokens are stored plaintext (dev only). Production should set this.
    # Existing plaintext rows keep working after the key is introduced (read
    # path accepts plaintext); new writes are encrypted immediately.
    OAUTH_TOKEN_ENCRYPTION_KEY: Optional[str] = None

    # --- Strava API ---
    STRAVA_CLIENT_ID: str = ""
    STRAVA_CLIENT_SECRET: str = ""
    STRAVA_WEBHOOK_VERIFY_TOKEN: str = ""  # a static secret string you choose, used to verify Strava's hub challenge
    STRAVA_WEBHOOK_SUBSCRIPTION_ID: int = 0  # filled in after you register the webhook
    STRAVA_STARTUP_BACKFILL_ENABLED: bool = True
    STRAVA_STARTUP_BACKFILL_HOURS: int = 24

    # --- Intervals.icu API ---
    # Keep the base URL in backend/.env. No Python default is provided so local
    # and deployed environments choose their own target explicitly.
    INTERVALS_ICU_API_BASE: Optional[str] = None
    INTERVALS_ICU_AUTH_MODE: str = "basic"

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
