"""Application settings and environment configuration."""

from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables and .env file."""

    # Paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    CREDENTIALS_DIR: Path = BASE_DIR / "credentials"
    TOKEN_PATH: Path = CREDENTIALS_DIR / "token.json"
    CHECKPOINT_DB_PATH: Path = BASE_DIR / "data" / "checkpoints.db"

    # Server
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 9000
    LOG_LEVEL: str = "INFO"
    POLL_INTERVAL_SECONDS: int = 30
    MAX_ANALYZE_PASSES: int = 6

    # Google
    MANAGER_EMAIL: str = ""  # email address to send approval requests to
    SALES_REPLY_REQUIRES_APPROVAL: bool = False

    # OpenAI
    OPENAI_API_KEY: str = ""
    MODEL_NAME: str = "gpt-4o"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

    @field_validator("MAX_ANALYZE_PASSES", mode="before")
    @classmethod
    def validate_max_analyze_passes(cls, value):
        passes = int(value)
        if passes < 1:
            raise ValueError("MAX_ANALYZE_PASSES must be >= 1")
        return passes

    @field_validator("MANAGER_EMAIL", mode="before")
    @classmethod
    def validate_manager_email(cls, value):
        manager_email = str(value or "").strip()
        if not manager_email:
            raise ValueError("MANAGER_EMAIL is required for approval workflows.")
        return manager_email

    @field_validator("OPENAI_API_KEY", mode="before")
    @classmethod
    def validate_openai_api_key(cls, value):
        api_key = str(value or "").strip()
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY is required. Set it in your .env file or as an environment variable."
            )
        return api_key


settings = Settings()