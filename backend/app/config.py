from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_path: str = "./study_helper.db"
    frontend_origin: str = "http://localhost:5173"
    openai_api_key: str | None = None
    openai_question_model: str = "gpt-4.1-mini"
    openai_planner_model: str = "gpt-4.1-mini"
    openai_topic_ingest_model: str = "gpt-4.1-mini"
    openai_timeout_seconds: int = 30

    mastery_second_attempt_discount: float = 0.6
    mastery_time_decay_lambda: float = 0.7
    mastery_confidence_k: float = 6.0
    forgetting_daily_decay: float = 0.015

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
