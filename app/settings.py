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
    CREDENTIALS_PATH: Path = CREDENTIALS_DIR / "credentials.json"
    # Override via DB_PATH env-var — in Docker mount a volume to /data and set DB_PATH=/data/agent.db
    DB_PATH: Path = BASE_DIR / "data" / "agent.db"

    # Server
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 9000
    LOG_LEVEL: str = "INFO"
    POLL_INTERVAL_SECONDS: int = 60
    MAX_ANALYZE_PASSES: int = 4

    # Proxy
    PROXY_HOST: str | None = None
    PROXY_PORT: int | None = None

    # Google
    GMAIL_USER: str = ""
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

    @field_validator("PROXY_PORT", mode="before")
    @classmethod
    def parse_proxy_port(cls, value):
        if value in (None, ""):
            return None
        return int(value)

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

    @property
    def proxy_url(self) -> str | None:
        """Return full proxy URL if configured, else None."""
        if self.PROXY_HOST and self.PROXY_PORT:
            return f"http://{self.PROXY_HOST}:{self.PROXY_PORT}"
        return None


settings = Settings()