"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-5.4"
    openai_temperature: float = 0.1

    # Langfuse
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # Database
    db_path: str = "data/db/feedback.db"

    # Classification
    classification_confidence_threshold: float = 0.7

    # Quality
    quality_auto_approve_threshold: float = 7.0
    max_revision_count: int = 2

    # App
    log_level: str = "INFO"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
