from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """
    Centralized configuration for the ASTRAPE backend.
    Pydantic will automatically look for these keys in your .env file.
    """
    
    # --- General App Configuration ---
    # Pulled from .env
    APP_NAME: str = "ASTRAPE-Backend"
    APP_ENV: str = "development" 
    PORT: int = 8080

    # --- Supabase Configuration ---
    # Required for database and vector operations
    SUPABASE_URL: str
    SUPABASE_KEY: str

    # --- Gemini AI Configuration ---
    # Required for the AI Coach RAG pipeline
    GEMINI_API_KEY: str
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # --- Path Management ---
    # Automatically resolves paths for the Markdown instructions
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    PROMPTS_DIR: Path = BASE_DIR / "app" / "prompts"
    COACH_PROMPT_FILE: str = "coach_behavior.md"

    # --- Pydantic Settings Metadata ---
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore" # Prevents crashes if extra vars are in .env
    )

# Singleton instance to be imported across the app
settings = Settings()