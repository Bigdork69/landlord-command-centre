"""Configuration singleton for landlord-command-centre."""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


class Config:
    """Singleton configuration class."""

    _instance: Optional["Config"] = None

    def __new__(cls) -> "Config":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        load_dotenv()
        self._load_config()

    def _load_config(self) -> None:
        """Load configuration from environment variables."""
        # Database path
        default_db = Path.home() / ".landlord" / "landlord.db"
        db_path_str = os.getenv("DATABASE_PATH", str(default_db))
        self.database_path = Path(db_path_str).expanduser()

        # Log level
        self.log_level = os.getenv("LOG_LEVEL", "INFO").upper()

        # Optional API keys for AI features
        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.groq_api_key = os.getenv("GROQ_API_KEY", "")

    @property
    def database_dir(self) -> Path:
        """Get the directory containing the database."""
        return self.database_path.parent

    def ensure_directories(self) -> None:
        """Ensure all required directories exist."""
        self.database_dir.mkdir(parents=True, exist_ok=True)


def get_config() -> Config:
    """Get the singleton config instance."""
    return Config()
