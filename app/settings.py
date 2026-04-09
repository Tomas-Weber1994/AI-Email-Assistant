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

    # Server
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 9000
    LOG_LEVEL: str = "INFO"

    # Proxy
    PROXY_HOST: str | None = None
    PROXY_PORT: int | None = None

    # Google
    GMAIL_USER: str = ""

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

    @property
    def proxy_url(self) -> str | None:
        """Return full proxy URL if configured, else None."""
        if self.PROXY_HOST and self.PROXY_PORT:
            return f"http://{self.PROXY_HOST}:{self.PROXY_PORT}"
        return None


settings = Settings()